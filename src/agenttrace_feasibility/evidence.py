"""Message observations and authenticated, source-scoped evidence validation."""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .mime import parse_mime
from .validation import (
    InputError,
    canonical_bytes,
    child_path,
    digest,
    load_json,
    object_fields,
    read_bytes,
    record_list,
    text,
    timestamp,
)

BINDING_FIELDS = {"tenant_ref", "mailbox_ref", "immutable_id", "internet_message_id", "mime_sha256"}
RECORD_FIELDS = {
    "schema_version",
    "evidence_id",
    "issuer",
    "key_id",
    "kind",
    "binding",
    "occurred_at",
    "emitted_at",
    "expires_at",
    "facts",
}
SEND_FIELDS = {"executor_type", "actor_ref", "action", "outcome", "execution_id"}
CONTENT_FIELDS = {"operation", "material_origin", "inclusion_method", "body_sha256"}


@dataclass(frozen=True)
class MessageObservation:
    message_ref: str
    binding: dict[str, str]
    state: str
    observed_at: datetime
    body: str
    body_language: str


@dataclass(frozen=True)
class VerifiedRecord:
    evidence_id: str
    kind: str
    facts: dict[str, str]
    occurred_at: datetime
    emitted_at: datetime


def load_messages(bundle: Path, profile: dict) -> list[MessageObservation]:
    observations = record_list(load_json(bundle / "observations.json"))
    messages: list[MessageObservation] = []
    seen: set[tuple[str, str, str]] = set()
    refs: set[str] = set()
    for item in observations:
        object_fields(
            item,
            {
                "message_ref",
                "tenant_ref",
                "mailbox_ref",
                "immutable_id",
                "internet_message_id",
                "state",
                "observed_at",
                "mime_file",
                "body_language",
            },
        )
        for value in item.values():
            text(value)
        if (
            item["tenant_ref"] != profile["tenant_ref"]
            or item["mailbox_ref"] not in profile["mailbox_refs"]
        ):
            raise InputError("outside_authorized_scope")
        if item["body_language"] not in {"en", "unsupported", "unknown"}:
            raise InputError("invalid_language_scope")
        if item["state"] not in {"sent", "received", "draft", "unknown"}:
            raise InputError("invalid_observation_state")
        key = (item["tenant_ref"], item["mailbox_ref"], item["immutable_id"])
        if key in seen or item["message_ref"] in refs:
            raise InputError("duplicate_message_observation")
        seen.add(key)
        refs.add(item["message_ref"])
        raw = read_bytes(child_path(bundle, item["mime_file"]))
        message = parse_mime(raw)
        ids = message.get_all("Message-ID", [])
        if len(ids) != 1 or str(ids[0]).strip() != item["internet_message_id"]:
            raise InputError("message_id_missing_ambiguous_or_mismatched")
        body_part = message.get_body(preferencelist=("plain",))
        body = ""
        if body_part is not None:
            try:
                body = body_part.get_content()
            except (LookupError, UnicodeError, ValueError) as exc:
                raise InputError("unsupported_body_encoding") from exc
        # HTML, attachments and protected bodies are intentionally not decoded by this spike.
        if not isinstance(body, str):
            body = ""
        binding = {k: item[k] for k in BINDING_FIELDS - {"mime_sha256"}}
        binding["mime_sha256"] = digest(raw)
        messages.append(
            MessageObservation(
                item["message_ref"],
                binding,
                item["state"],
                timestamp(item["observed_at"]),
                body,
                item["body_language"],
            )
        )
    return messages


def load_profile(path: Path) -> dict:
    profile = object_fields(
        load_json(path), {"schema_version", "environment", "tenant_ref", "mailbox_refs", "issuers"}
    )
    if profile["schema_version"] != "1.0" or profile["environment"] not in {
        "contract_example",
        "synthetic_test_tenant",
    }:
        raise InputError("unsupported_profile_version_or_environment")
    text(profile["tenant_ref"])
    for mailbox in record_list(profile["mailbox_refs"]):
        text(mailbox)
    if not isinstance(profile["issuers"], dict) or len(profile["issuers"]) > 100:
        raise InputError("invalid_issuer_registry")
    for issuer, config in profile["issuers"].items():
        text(issuer)
        object_fields(
            config,
            {
                "key_id",
                "public_key_base64",
                "valid_from",
                "valid_until",
                "revoked",
                "agent_actor_refs",
                "allowed_kinds",
            },
        )
        if type(config["revoked"]) is not bool:
            raise InputError("boolean_required")
        text(config["key_id"])
        decode_public_key(config["public_key_base64"])
        if timestamp(config["valid_from"]) >= timestamp(config["valid_until"]):
            raise InputError("invalid_key_validity")
        for actor in record_list(config["agent_actor_refs"]):
            text(actor)
        kinds = record_list(config["allowed_kinds"])
        for kind in kinds:
            text(kind)
        if not set(kinds) <= {"send_execution", "content_inclusion"}:
            raise InputError("unsupported_evidence_kind")
    return profile


def decode_public_key(value: Any) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(text(value), validate=True))
    except (ValueError, binascii.Error) as exc:
        raise InputError("invalid_public_key") from exc


def verify_record(
    envelope: Any, message: MessageObservation, profile: dict, as_of: datetime
) -> VerifiedRecord:
    object_fields(envelope, {"record", "signature_base64"})
    record = object_fields(envelope["record"], RECORD_FIELDS)
    for key in RECORD_FIELDS - {"binding", "facts"}:
        text(record[key])
    if record["schema_version"] != "1.0":
        raise InputError("unsupported_evidence_version")
    issuer = profile["issuers"].get(record["issuer"])
    if issuer is None or issuer["key_id"] != record["key_id"]:
        raise InputError("unknown_issuer_or_key")
    if issuer["revoked"]:
        raise InputError("revoked_issuer")
    if record["kind"] not in issuer["allowed_kinds"]:
        raise InputError("unauthorized_evidence_kind")
    try:
        signature = base64.b64decode(text(envelope["signature_base64"]), validate=True)
        decode_public_key(issuer["public_key_base64"]).verify(signature, canonical_bytes(record))
    except (InvalidSignature, ValueError, binascii.Error) as exc:
        raise InputError("invalid_evidence_signature") from exc
    binding = object_fields(record["binding"], BINDING_FIELDS)
    if binding != message.binding:
        raise InputError("message_binding_mismatch")
    if (
        binding["tenant_ref"] != profile["tenant_ref"]
        or binding["mailbox_ref"] not in profile["mailbox_refs"]
    ):
        raise InputError("outside_authorized_scope")
    occurred = timestamp(record["occurred_at"])
    emitted = timestamp(record["emitted_at"])
    expires = timestamp(record["expires_at"])
    if not (
        timestamp(issuer["valid_from"])
        <= occurred
        <= emitted
        <= as_of
        < expires
        <= timestamp(issuer["valid_until"])
    ):
        raise InputError("invalid_or_expired_evidence_time")
    if occurred > message.observed_at + timedelta(minutes=5) or message.observed_at > as_of:
        raise InputError("impossible_observation_time")
    fields = SEND_FIELDS if record["kind"] == "send_execution" else CONTENT_FIELDS
    facts = object_fields(record["facts"], fields)
    for value in facts.values():
        text(value)
    if record["kind"] == "send_execution":
        if facts["executor_type"] not in {"ai_agent", "human", "non_ai_application", "unknown"}:
            raise InputError("invalid_executor_type")
        if facts["action"] not in {"send", "draft", "read"} or facts["outcome"] not in {
            "completed",
            "accepted",
            "failed",
            "cancelled",
        }:
            raise InputError("invalid_execution_state")
        if (
            facts["executor_type"] == "ai_agent"
            and facts["actor_ref"] not in issuer["agent_actor_refs"]
        ):
            raise InputError("agent_identity_not_established")
    else:
        if facts["operation"] not in {
            "draft_generation",
            "substantial_rewrite",
            "translation_into_english",
            "basic_correction",
            "unknown",
        }:
            raise InputError("unsupported_content_operation")
        if facts["material_origin"] not in {
            "new_generated_output",
            "human_input_with_basic_correction",
            "echoed_human_input",
            "common_template",
            "unknown",
        }:
            raise InputError("unsupported_content_origin")
        if facts["inclusion_method"] not in {
            "authenticated_transfer_lineage",
            "output_similarity_only",
            "unknown",
        }:
            raise InputError("unsupported_inclusion_method")
        if not re.fullmatch(r"[0-9a-f]{64}", facts["body_sha256"]):
            raise InputError("invalid_content_digest")
        if facts["body_sha256"] != digest(message.body.encode("utf-8")):
            raise InputError("content_binding_mismatch")
    return VerifiedRecord(record["evidence_id"], record["kind"], facts, occurred, emitted)
