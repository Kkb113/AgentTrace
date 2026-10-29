"""Transactional append-only evidence, current trust evaluation and sealed input history."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import ValidationError

from agenttrace_foundation.authorization import Principal, audit
from agenttrace_foundation.database import Database
from agenttrace_ingestion.protection import EvidenceCipher

from .canonical import LedgerError, canonical_bytes, fingerprint, message_material
from .contracts import CorrelationView, Kind, MessageObservation, SignedEvidence
from .signatures import verify_signature


def utc_now() -> datetime:
    return datetime.now(UTC)


class EvidenceLedger:
    def __init__(
        self, database: Database, cipher: EvidenceCipher, tenant_keys: Mapping[UUID, bytes]
    ):
        if not tenant_keys or any(
            not isinstance(tenant, UUID) or not isinstance(key, bytes) or len(key) != 32
            for tenant, key in tenant_keys.items()
        ):
            raise LedgerError("invalid_tenant_fingerprint_configuration")
        if len(set(tenant_keys.values())) != len(tenant_keys):
            raise LedgerError("tenant_fingerprint_key_reuse_forbidden")
        self.database, self.cipher = database, cipher
        self.tenant_keys = MappingProxyType(dict(tenant_keys))

    def _key(self, tenant: UUID) -> bytes:
        if tenant not in self.tenant_keys or len(self.tenant_keys[tenant]) != 32:
            raise LedgerError("tenant_fingerprint_key_unavailable")
        return self.tenant_keys[tenant]

    def _scope(self, tenant: UUID, mailbox: UUID) -> UUID:
        self._key(tenant)
        return self.cipher.reference("ledger-scope", str(tenant), str(mailbox))

    @staticmethod
    def _lock(connection: Connection[DictRow], scope: UUID) -> None:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (str(scope),))

    def enroll_scope(
        self, tenant: UUID, mailbox: UUID, *, roles: tuple[str, ...] = ("agenttrace_ledger",)
    ) -> UUID:
        scope = self._scope(tenant, mailbox)
        if any(
            role
            not in {
                "agenttrace_ledger",
                "agenttrace_collector",
                "agenttrace_api",
                "agenttrace_attribution",
            }
            for role in roles
        ):
            raise LedgerError("unapproved_ledger_database_role")
        with self.database.connect() as c:
            c.execute(
                "INSERT INTO ledger_scopes VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                (scope, tenant, mailbox),
            )
            for role in roles:
                c.execute(
                    "INSERT INTO ledger_acl VALUES(%s,%s) ON CONFLICT DO NOTHING", (scope, role)
                )
        return scope

    def enroll_issuer(
        self,
        tenant: UUID,
        mailbox: UUID,
        issuer: UUID,
        *,
        client: UUID,
        subject: UUID,
        kinds: tuple[Kind, ...],
    ) -> None:
        if not kinds:
            raise LedgerError("issuer_capabilities_required")
        with self.database.connect() as c:
            self._lock(c, self._scope(tenant, mailbox))
            c.execute(
                "INSERT INTO ledger_issuers(scope_ref,issuer_ref,client_id,subject_id,kinds) VALUES(%s,%s,%s,%s,%s)",
                (self._scope(tenant, mailbox), issuer, client, subject, list(kinds)),
            )
        audit("ledger_issuer_enrollment", "allowed")

    def enroll_observer(
        self,
        tenant: UUID,
        mailbox: UUID,
        source: UUID,
        *,
        namespace: str = "graph_immutable",
        schema_version: str = "graph-v1",
        capture_basis: str = "synthetic_fixture",
    ) -> None:
        with self.database.connect() as c:
            c.execute(
                "INSERT INTO ledger_observers VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (self._scope(tenant, mailbox), source, namespace, schema_version, capture_basis),
            )
            row = c.execute(
                "SELECT namespace,source_schema_version,capture_basis FROM ledger_observers WHERE scope_ref=%s AND source_ref=%s",
                (self._scope(tenant, mailbox), source),
            ).fetchone()
            if not row or (
                row["namespace"],
                row["source_schema_version"],
                row["capture_basis"],
            ) != (namespace, schema_version, capture_basis):
                raise LedgerError("observer_enrollment_conflict")

    def enroll_key(
        self,
        tenant: UUID,
        mailbox: UUID,
        issuer: UUID,
        key_ref: UUID,
        public_key: bytes,
        valid_from: datetime,
        valid_until: datetime,
    ) -> None:
        if (
            len(public_key) != 32
            or valid_from.tzinfo is None
            or valid_until.tzinfo is None
            or valid_until <= valid_from
        ):
            raise LedgerError("invalid_issuer_key")
        with self.database.connect() as c:
            self._lock(c, self._scope(tenant, mailbox))
            c.execute(
                "INSERT INTO ledger_keys VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    self._scope(tenant, mailbox),
                    issuer,
                    key_ref,
                    public_key,
                    valid_from,
                    valid_until,
                ),
            )

    def revoke(
        self,
        tenant: UUID,
        mailbox: UUID,
        issuer: UUID,
        *,
        key_ref: UUID | None = None,
        reason: str = "compromise",
    ) -> None:
        if reason not in {"compromise", "retired", "owner_withdrawal"}:
            raise LedgerError("invalid_revocation_reason")
        with self.database.connect() as c:
            self._lock(c, self._scope(tenant, mailbox))
            if (
                key_ref is not None
                and not c.execute(
                    "SELECT 1 FROM ledger_keys WHERE scope_ref=%s AND issuer_ref=%s AND key_ref=%s",
                    (self._scope(tenant, mailbox), issuer, key_ref),
                ).fetchone()
            ):
                raise LedgerError("issuer_key_not_found")
            c.execute(
                "INSERT INTO ledger_revocations(revocation_ref,scope_ref,issuer_ref,key_ref,reason) VALUES(%s,%s,%s,%s,%s)",
                (uuid4(), self._scope(tenant, mailbox), issuer, key_ref, reason),
            )
        audit("ledger_trust_revocation", "allowed")

    def observe(self, message: MessageObservation) -> UUID:
        now = utc_now()
        if not now - timedelta(days=7) < message.observed_at <= now:
            raise LedgerError("message_observation_not_current")
        if message.normalization_version not in {"mail-text-v1", "text-extraction/1.0"}:
            raise LedgerError("unsupported_message_normalization")
        if (
            message.snapshot_expires_at
            and not now < message.snapshot_expires_at <= message.observed_at + timedelta(days=7)
        ):
            raise LedgerError("snapshot_retention_out_of_bounds")
        material = message_material(message, self._key(message.tenant_id))
        material.update(
            {
                "snapshot_ref": str(message.snapshot_ref) if message.snapshot_ref else None,
                "snapshot_expires_at": message.snapshot_expires_at.isoformat()
                if message.snapshot_expires_at
                else None,
                "normalization_version": message.normalization_version,
            }
        )
        scope = self._scope(message.tenant_id, message.mailbox_id)
        ref = self.cipher.reference(
            "ledger-copy",
            str(scope),
            message.namespace,
            str(message.source_ref) if message.namespace == "external_source" else "mailbox",
            message.immutable_id,
        )
        digest = fingerprint(
            self._key(message.tenant_id), message.tenant_id, "observation", message
        )
        material["binding"] = json.loads(
            canonical_bytes(
                {
                    "scope_ref": scope,
                    "message_ref": ref,
                    "version_ref": message.version_ref,
                    "source_ref": message.source_ref,
                    "source_event_ref": message.source_event_ref,
                    "source_schema_version": message.source_schema_version,
                    "namespace": message.namespace,
                    "immutable_digest": material["immutable_digest"],
                    "internet_digest": material["internet_digest"],
                    "copy_role": message.copy_role,
                    "message_state": message.state,
                    "observed_at": message.observed_at,
                    "source_event_at": message.source_event_at,
                    "sent_at": message.sent_at,
                }
            )
        )
        with self.database.connect() as c:
            self._lock(c, scope)
            observer = c.execute(
                "SELECT * FROM ledger_observers WHERE scope_ref=%s AND source_ref=%s",
                (scope, message.source_ref),
            ).fetchone()
            if (
                not observer
                or observer["namespace"] != message.namespace
                or observer["source_schema_version"] != message.source_schema_version
            ):
                raise LedgerError("message_observer_not_enrolled_for_schema")
            existing = c.execute(
                "SELECT material_digest FROM ledger_messages WHERE scope_ref=%s AND message_ref=%s AND version_ref=%s",
                (scope, ref, message.version_ref),
            ).fetchone()
            if existing:
                if existing["material_digest"] != digest:
                    raise LedgerError("message_version_reuse_conflict")
                return ref
            c.execute(
                "INSERT INTO ledger_messages(scope_ref,message_ref,version_ref,source_ref,source_event_ref,source_schema_version,namespace,immutable_digest,internet_digest,copy_role,message_state,observed_at,source_event_at,sent_at,material_cipher,material_digest,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    scope,
                    ref,
                    message.version_ref,
                    message.source_ref,
                    message.source_event_ref,
                    message.source_schema_version,
                    message.namespace,
                    material["immutable_digest"],
                    material["internet_digest"],
                    message.copy_role,
                    message.state,
                    message.observed_at,
                    message.source_event_at,
                    message.sent_at,
                    self.cipher.seal(
                        material,
                        context="ledger-message:"
                        + str(scope)
                        + ":"
                        + str(ref)
                        + ":"
                        + str(message.version_ref),
                    ),
                    digest,
                    message.observed_at + timedelta(days=7),
                ),
            )
        return ref

    def _trusted(
        self,
        c: Connection[DictRow],
        envelope: SignedEvidence,
        scope: UUID,
        now: datetime,
        principal: Principal | None = None,
    ) -> None:
        record = envelope.record
        issuer = c.execute(
            "SELECT * FROM ledger_issuers WHERE scope_ref=%s AND issuer_ref=%s",
            (scope, record.issuer_ref),
        ).fetchone()
        key = c.execute(
            "SELECT * FROM ledger_keys WHERE scope_ref=%s AND issuer_ref=%s AND key_ref=%s",
            (scope, record.issuer_ref, envelope.key_ref),
        ).fetchone()
        revoked = c.execute(
            "SELECT 1 FROM ledger_revocations WHERE scope_ref=%s AND issuer_ref=%s AND (key_ref IS NULL OR key_ref=%s)",
            (scope, record.issuer_ref, envelope.key_ref),
        ).fetchone()
        if not issuer or not key or revoked or record.fact.kind not in issuer["kinds"]:
            raise LedgerError("evidence_issuer_key_or_capability_untrusted")
        if principal and (
            not principal.application
            or principal.tenant != str(record.tenant_id)
            or principal.client != str(issuer["client_id"])
            or principal.subject != str(issuer["subject_id"])
        ):
            raise LedgerError("evidence_source_principal_mismatch")
        verify_signature(
            envelope, bytes(key["public_key"]), now, key["valid_from"], key["valid_until"]
        )

    def submit(self, envelope: SignedEvidence, principal: Principal) -> dict[str, Any]:
        try:
            envelope = SignedEvidence.model_validate_json(envelope.model_dump_json())
        except (ValidationError, ValueError):
            raise LedgerError("invalid_signed_evidence_schema") from None
        record = envelope.record
        scope = self._scope(record.tenant_id, record.mailbox_id)
        ref = self.cipher.reference(
            "ledger-event", str(scope), str(record.issuer_ref), str(record.event_id)
        )
        digest = hashlib.sha256(canonical_bytes(record)).hexdigest()
        conflict = False
        with self.database.connect() as c:
            self._lock(c, scope)
            now = utc_now()
            self._trusted(c, envelope, scope, now, principal)
            message = c.execute(
                "SELECT * FROM ledger_messages WHERE scope_ref=%s AND message_ref=%s AND version_ref=%s AND expires_at>%s",
                (scope, record.message_ref, record.version_ref, now),
            ).fetchone()
            if not message or record.expires_at > message["expires_at"]:
                raise LedgerError("evidence_message_binding_missing_or_expired")
            previous = c.execute(
                "SELECT record_digest,expires_at FROM ledger_receipts WHERE scope_ref=%s AND issuer_ref=%s AND event_id=%s",
                (scope, record.issuer_ref, record.event_id),
            ).fetchone()
            if previous:
                conflict = previous["record_digest"] != digest
                if conflict:
                    c.execute(
                        "INSERT INTO ledger_conflicts(conflict_ref,scope_ref,evidence_ref,conflicting_digest,expires_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (uuid4(), scope, ref, digest, previous["expires_at"]),
                    )
            else:
                c.execute(
                    "INSERT INTO ledger_receipts(evidence_ref,scope_ref,issuer_ref,key_ref,event_id,message_ref,version_ref,kind,record_digest,envelope_cipher,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        ref,
                        scope,
                        record.issuer_ref,
                        envelope.key_ref,
                        record.event_id,
                        record.message_ref,
                        record.version_ref,
                        record.fact.kind,
                        digest,
                        self.cipher.seal(
                            envelope.model_dump(mode="json"), context="ledger-receipt:" + str(ref)
                        ),
                        record.expires_at,
                    ),
                )
        audit(
            "ledger_evidence_submission", "conflict" if conflict else "allowed", principal.subject
        )
        if conflict:
            raise LedgerError("evidence_event_reuse_conflict")
        return {"evidence_ref": str(ref), "idempotent_replay": previous is not None}

    def _open(self, c: Connection[DictRow], row: dict[str, Any], now: datetime) -> SignedEvidence:
        raw = self.cipher.open(
            bytes(row["envelope_cipher"]), context="ledger-receipt:" + str(row["evidence_ref"])
        )
        try:
            envelope = SignedEvidence.model_validate_json(json.dumps(raw))
        except (ValidationError, ValueError, TypeError):
            raise LedgerError("stored_evidence_schema_invalid") from None
        if hashlib.sha256(canonical_bytes(envelope.record)).hexdigest() != row["record_digest"]:
            raise LedgerError("stored_evidence_digest_mismatch")
        if (
            envelope.record.message_ref != row["message_ref"]
            or self._scope(envelope.record.tenant_id, envelope.record.mailbox_id)
            != row["scope_ref"]
            or envelope.record.version_ref != row["version_ref"]
            or envelope.record.issuer_ref != row["issuer_ref"]
            or envelope.key_ref != row["key_ref"]
            or envelope.record.event_id != row["event_id"]
            or envelope.record.fact.kind != row["kind"]
        ):
            raise LedgerError("stored_evidence_binding_mismatch")
        self._trusted(c, envelope, row["scope_ref"], now)
        if c.execute(
            "SELECT 1 FROM ledger_conflicts WHERE scope_ref=%s AND evidence_ref=%s AND expires_at>%s",
            (row["scope_ref"], row["evidence_ref"], now),
        ).fetchone():
            raise LedgerError("evidence_event_reuse_conflict")
        return envelope

    def _material(self, row: dict[str, Any]) -> dict[str, Any]:
        material = self.cipher.open(
            bytes(row["material_cipher"]),
            context="ledger-message:"
            + str(row["scope_ref"])
            + ":"
            + str(row["message_ref"])
            + ":"
            + str(row["version_ref"]),
        )
        binding = {key: row[key] for key in material["binding"]}
        if not hmac.compare_digest(canonical_bytes(material["binding"]), canonical_bytes(binding)):
            raise LedgerError("message_metadata_integrity_mismatch")
        return material

    def _view(
        self,
        c: Connection[DictRow],
        tenant: UUID,
        mailbox: UUID,
        message: UUID,
        version: UUID,
        now: datetime,
    ) -> dict[str, Any]:
        scope = self._scope(tenant, mailbox)
        observed = c.execute(
            "SELECT * FROM ledger_messages WHERE scope_ref=%s AND message_ref=%s AND version_ref=%s AND expires_at>%s",
            (scope, message, version, now),
        ).fetchone()
        if not observed:
            raise LedgerError("ledger_message_not_found")
        material = self._material(observed)
        observer = c.execute(
            "SELECT capture_basis FROM ledger_observers WHERE scope_ref=%s AND source_ref=%s",
            (scope, observed["source_ref"]),
        ).fetchone()
        if not observer:
            raise LedgerError("message_observer_not_enrolled_for_schema")
        latest = c.execute(
            "SELECT version_ref FROM ledger_messages WHERE scope_ref=%s AND message_ref=%s AND expires_at>%s AND coalesce(source_event_at,observed_at)>=coalesce(%s,%s) LIMIT 2",
            (scope, message, now, observed["source_event_at"], observed["observed_at"]),
        ).fetchall()
        current = len(latest) == 1 and latest[0]["version_ref"] == version
        rows = c.execute(
            "SELECT * FROM ledger_receipts WHERE scope_ref=%s AND message_ref=%s AND version_ref=%s AND expires_at>%s ORDER BY evidence_ref LIMIT 1001",
            (scope, message, version, now),
        ).fetchall()
        if len(rows) > 1000:
            raise LedgerError("evidence_view_limit_requires_bounded_export")
        groups: dict[str, list[dict[str, Any]]] = {
            "agent_send_attribution": [],
            "content_assessment": [],
        }
        mappings = []

        def parent(ref: UUID, allowed: set[str], *, same_copy: bool = True) -> SignedEvidence:
            row = c.execute(
                "SELECT * FROM ledger_receipts WHERE evidence_ref=%s AND scope_ref=%s AND expires_at>%s",
                (ref, scope, now),
            ).fetchone()
            if (
                not row
                or row["kind"] not in allowed
                or (same_copy and row["message_ref"] != message)
            ):
                raise LedgerError("content_parent_missing_or_out_of_scope")
            return self._open(c, row, now)

        for row in rows:
            axis = (
                "agent_send_attribution"
                if row["kind"] == "send_execution"
                else "content_assessment"
            )
            link = {
                "evidence_ref": str(row["evidence_ref"]),
                "source_ref": str(row["issuer_ref"]),
                "key_ref": str(row["key_ref"]),
                "record_digest": row["record_digest"],
                "schema_version": "1.0",
                "ingested_at": row["received_at"].isoformat(),
                "classification": "unsupported",
                "reason": "insufficient_linkage",
            }
            try:
                envelope = self._open(c, row, now)
                record, fact = envelope.record, envelope.record.fact
                link["source_schema_version"] = record.source_schema_version
                link["occurred_at"] = record.occurred_at.isoformat()
                if not current:
                    raise LedgerError("message_version_superseded_or_ambiguous")
                if record.occurred_at > observed["observed_at"]:
                    raise LedgerError("evidence_after_observed_message")
                if fact.kind == "send_execution":
                    exact = False
                    if fact.identifier:
                        domain = (
                            "identifier:" + observed["namespace"]
                            if fact.identifier.kind == "mailbox_immutable"
                            else "internet_message_id"
                        )
                        digest = fingerprint(
                            self._key(tenant), tenant, domain, fact.identifier.value
                        )
                        if fact.identifier.kind == "mailbox_immutable":
                            exact = (
                                observed["namespace"] == "graph_immutable"
                                and digest == observed["immutable_digest"]
                            )
                        else:
                            copies = c.execute(
                                "SELECT DISTINCT message_ref FROM ledger_messages WHERE scope_ref=%s AND internet_digest=%s AND copy_role='sender' AND message_state='sent' AND expires_at>%s",
                                (scope, digest, now),
                            ).fetchall()
                            exact = digest == observed["internet_digest"] and len(copies) == 1
                    timing = (
                        observed["sent_at"] is not None
                        and abs((record.occurred_at - observed["sent_at"]).total_seconds()) <= 2
                    )
                    if (
                        fact.link_method == "exact_identifier"
                        and exact
                        and timing
                        and fact.outcome == "completed"
                        and observed["copy_role"] == "sender"
                        and observed["message_state"] == "sent"
                        and fact.actor != "unknown"
                        and fact.mechanism
                        in {
                            "unknown",
                            {
                                "ai_agent": "agent",
                                "human": "human_interaction_observed",
                                "non_ai_application": "conventional_automation",
                            }.get(fact.actor),
                        }
                    ):
                        link.update(
                            classification="exact",
                            reason="authenticated_completed_send_exact_message",
                            actor=fact.actor,
                            execution_ref=str(fact.execution_ref),
                        )
                    else:
                        link.update(
                            classification="candidate",
                            reason="send_execution_or_message_link_insufficient",
                        )
                elif fact.kind == "content_inclusion":
                    generation = parent(fact.generation_ref, {"generation"}, same_copy=False).record
                    gen = generation.fact
                    if gen.kind != "generation":
                        raise LedgerError("content_parent_wrong_kind")
                    matches = [
                        r
                        for r in material["regions"]
                        if r["start"] == fact.region_start
                        and r["end"] == fact.region_end
                        and r["digest"]
                        == fingerprint(
                            self._key(tenant), tenant, "content_sha256", fact.output_sha256
                        )
                    ]
                    supported = (
                        fact.method == "authenticated_transfer_lineage"
                        and gen.origin == "new_generated_output"
                        and gen.operation != "basic_correction"
                        and gen.output_sha256 == fact.output_sha256
                        and generation.occurred_at <= record.occurred_at
                        and len(matches) == 1
                        and matches[0]["role"] == "authored"
                    )
                    link.update(
                        classification="exact" if supported else "candidate",
                        reason="authenticated_generation_and_inclusion"
                        if supported
                        else "content_overlap_or_operation_insufficient",
                        parent_ref=str(fact.generation_ref),
                    )
                elif fact.kind == "content_edit":
                    inclusion = parent(fact.parent_inclusion_ref, {"content_inclusion"}).record
                    inc = inclusion.fact
                    if inc.kind != "content_inclusion":
                        raise LedgerError("content_parent_wrong_kind")
                    generation = parent(inc.generation_ref, {"generation"}, same_copy=False).record
                    gen = generation.fact
                    old = c.execute(
                        "SELECT * FROM ledger_messages WHERE scope_ref=%s AND message_ref=%s AND version_ref=%s AND expires_at>%s",
                        (scope, message, inclusion.version_ref, now),
                    ).fetchone()
                    before = fingerprint(
                        self._key(tenant), tenant, "content_sha256", fact.before_sha256
                    )
                    after = fingerprint(
                        self._key(tenant), tenant, "content_sha256", fact.after_sha256
                    )
                    old_regions = self._material(old)["regions"] if old else []
                    source_span = any(
                        r["start"] == inc.region_start
                        and r["end"] == inc.region_end
                        and r["digest"] == before
                        and r["role"] == "authored"
                        for r in old_regions
                    )
                    target_span = any(
                        r["start"] == fact.region_start
                        and r["end"] == fact.region_end
                        and r["digest"] == after
                        and r["role"] == "authored"
                        for r in material["regions"]
                    )
                    supported = (
                        gen.kind == "generation"
                        and gen.origin == "new_generated_output"
                        and gen.operation != "basic_correction"
                        and gen.output_sha256
                        == inc.output_sha256
                        == fact.before_sha256
                        == fact.after_sha256
                        and inc.method == "authenticated_transfer_lineage"
                        and fact.method == "authenticated_unchanged_span"
                        and generation.occurred_at <= inclusion.occurred_at <= record.occurred_at
                        and old is not None
                        and inclusion.occurred_at <= old["observed_at"] <= observed["observed_at"]
                        and source_span
                        and target_span
                    )
                    link.update(
                        classification="exact" if supported else "candidate",
                        reason="authenticated_unchanged_generated_span"
                        if supported
                        else "changed_or_unverified_edit_lineage",
                        parent_ref=str(fact.parent_inclusion_ref),
                    )
                elif fact.kind == "copy_mapping":
                    other = c.execute(
                        """SELECT m.*,s.tenant_id FROM ledger_messages m
                           JOIN ledger_scopes s USING(scope_ref)
                           JOIN ledger_issuers i ON i.scope_ref=m.scope_ref
                           WHERE m.message_ref=%s AND m.version_ref=%s AND m.expires_at>%s
                             AND i.issuer_ref=%s AND 'copy_mapping'=ANY(i.kinds)
                             AND (i.client_id,i.subject_id)=(SELECT client_id,subject_id
                                 FROM ledger_issuers WHERE scope_ref=%s AND issuer_ref=%s)
                             AND NOT EXISTS(SELECT 1 FROM ledger_revocations r
                                 WHERE r.scope_ref=i.scope_ref AND r.issuer_ref=i.issuer_ref AND r.key_ref IS NULL)""",
                        (
                            fact.other_message_ref,
                            fact.other_version_ref,
                            now,
                            record.issuer_ref,
                            scope,
                            record.issuer_ref,
                        ),
                    ).fetchall()
                    exact = (
                        len(other) == 1
                        and other[0]["tenant_id"] == tenant
                        and fact.mapping_basis == "authenticated_source_mapping"
                        and fact.relation != "forward_context"
                        and material["payload_digest"] is not None
                        and self._material(other[0])["payload_digest"] == material["payload_digest"]
                    )
                    # Cross-mailbox disclosure is deliberately limited to an opaque mapping receipt.
                    link.update(
                        classification="exact_mapping" if exact else "candidate",
                        reason="mapping_never_propagates_actor_or_authorship",
                        relation=fact.relation,
                    )
                    mappings.append(link)
                    continue
                else:
                    link.update(
                        classification="context", reason="generation_alone_does_not_prove_inclusion"
                    )
            except LedgerError as error:
                link.update(classification="invalid", reason=str(error))
            if row["kind"] == "copy_mapping":
                mappings.append(link)
            else:
                groups[axis].append(link)
        actors = {
            (r.get("actor"), r.get("execution_ref"))
            for r in groups["agent_send_attribution"]
            if r["classification"] == "exact"
        }
        for axis, links in groups.items():
            if any(r["classification"] == "invalid" for r in links) or (
                axis == "agent_send_attribution" and len(actors) > 1
            ):
                for link in links:
                    if link["classification"] == "exact":
                        link.update(
                            classification="conflicting",
                            reason="material_evidence_conflict_requires_reassessment",
                        )
        return {
            "schema_version": "1.0",
            "rule_version": "correlation-v1",
            "message_ref": str(message),
            "version_ref": str(version),
            "source": {
                "source_ref": str(observed["source_ref"]),
                "source_event_ref": str(observed["source_event_ref"]),
                "schema_version": observed["source_schema_version"],
                "normalization_version": material["normalization_version"],
                "canonicalization_version": material["canonicalization_version"],
                "observation_digest": observed["material_digest"],
                "capture_basis": observer["capture_basis"],
                "content_available": material["content_available"],
                "recipients_complete": material["recipients_complete"],
                "source_event_at": observed["source_event_at"].isoformat()
                if observed["source_event_at"]
                else None,
                "observed_at": observed["observed_at"].isoformat(),
            },
            "current_message_version": current,
            "correlations": groups,
            "copy_mappings": mappings,
            "replay": {
                "snapshot_ref": material["snapshot_ref"],
                "snapshot_reference_within_retention": bool(
                    material["snapshot_ref"]
                    and datetime.fromisoformat(material["snapshot_expires_at"]) > now
                ),
                "snapshot_bytes_verified": False,
                "model_reexecution_available": False,
                "reason": "model_not_installed_and_artifacts_not_pinned",
            },
            "qualification": "evidence_correlation_only_not_a_detection_accuracy_claim",
        }

    def view(self, tenant: UUID, mailbox: UUID, message: UUID, version: UUID) -> dict[str, Any]:
        with self.database.connect() as c:
            self._lock(c, self._scope(tenant, mailbox))
            return self._view(c, tenant, mailbox, message, version, utc_now())

    def record_inputs(self, tenant: UUID, mailbox: UUID, message: UUID, version: UUID) -> UUID:
        scope, ref = self._scope(tenant, mailbox), uuid4()
        with self.database.connect() as c:
            self._lock(c, scope)
            now = utc_now()
            view = self._view(c, tenant, mailbox, message, version, now)
            try:
                CorrelationView.model_validate_json(json.dumps(view))
            except ValidationError:
                raise LedgerError("invalid_persisted_input_schema") from None
            prior = c.execute(
                "SELECT input_ref,revision FROM ledger_inputs WHERE scope_ref=%s AND message_ref=%s AND expires_at>%s ORDER BY revision DESC LIMIT 1",
                (scope, message, now),
            ).fetchone()
            revision = prior["revision"] + 1 if prior else 1
            prior_ref = prior["input_ref"] if prior else None
            expires = now + timedelta(days=30)
            snapshot = {
                "view": view,
                "binding": json.loads(
                    canonical_bytes(
                        {
                            "input_ref": ref,
                            "scope_ref": scope,
                            "message_ref": message,
                            "version_ref": version,
                            "revision": revision,
                            "prior_input_ref": prior_ref,
                            "recorded_at": now,
                            "expires_at": expires,
                            "schema_version": "1.0",
                            "rule_version": "correlation-v1",
                        }
                    )
                ),
            }
            c.execute(
                "INSERT INTO ledger_inputs(input_ref,scope_ref,message_ref,version_ref,schema_version,rule_version,revision,prior_input_ref,view_cipher,view_digest,recorded_at,expires_at) VALUES(%s,%s,%s,%s,'1.0','correlation-v1',%s,%s,%s,%s,%s,%s)",
                (
                    ref,
                    scope,
                    message,
                    version,
                    revision,
                    prior_ref,
                    self.cipher.seal(snapshot, context="ledger-input:" + str(ref)),
                    fingerprint(self._key(tenant), tenant, "input-view", snapshot),
                    now,
                    expires,
                ),
            )
        return ref

    def history(self, tenant: UUID, mailbox: UUID, message: UUID) -> list[dict[str, Any]]:
        scope = self._scope(tenant, mailbox)
        with self.database.connect() as c:
            rows = c.execute(
                "SELECT * FROM ledger_inputs WHERE scope_ref=%s AND message_ref=%s AND expires_at>now() ORDER BY revision LIMIT 101",
                (scope, message),
            ).fetchall()
            if len(rows) > 100:
                raise LedgerError("input_history_limit_requires_bounded_export")
            results = []
            for row in rows:
                snapshot = self.cipher.open(
                    bytes(row["view_cipher"]), context="ledger-input:" + str(row["input_ref"])
                )
                if not hmac.compare_digest(
                    row["view_digest"],
                    fingerprint(self._key(tenant), tenant, "input-view", snapshot),
                ):
                    raise LedgerError("input_history_integrity_failure")
                binding = {key: row[key] for key in snapshot["binding"]}
                if not hmac.compare_digest(
                    canonical_bytes(snapshot["binding"]), canonical_bytes(binding)
                ):
                    raise LedgerError("input_history_metadata_integrity_failure")
                view = snapshot["view"]
                results.append(
                    {
                        "input_ref": str(row["input_ref"]),
                        "revision": row["revision"],
                        "input_digest": row["view_digest"],
                        "prior_input_ref": str(row["prior_input_ref"])
                        if row["prior_input_ref"]
                        else None,
                        "recorded_at": row["recorded_at"].isoformat(),
                        "expires_at": row["expires_at"].isoformat(),
                        "historical_only": True,
                        "view": view,
                    }
                )
            return results
