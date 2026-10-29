"""Fictional observations and independently signed test receipts; no email sending."""

import base64
from datetime import timedelta
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agenttrace_foundation.authorization import Principal
from agenttrace_ledger.contracts import EvidenceRecord, MessageObservation, SignedEvidence
from agenttrace_ledger.signatures import signing_bytes
from agenttrace_ledger.store import utc_now
from tests.ingestion_support import CLIENT, MAILBOX, TENANT

BODY = "Invented content for a provenance experiment. No customer data."


def observation(**changes):
    now = utc_now()
    return MessageObservation(
        **{
            "tenant_id": TENANT,
            "mailbox_id": MAILBOX,
            "source_ref": UUID("00000000-0000-4000-8000-000000000006"),
            "source_event_ref": uuid4(),
            "source_schema_version": "graph-v1",
            "namespace": "graph_immutable",
            "immutable_id": "CaseSensitiveSyntheticID",
            "internet_message_id": "<synthetic@example.invalid>",
            "version_ref": uuid4(),
            "copy_role": "sender",
            "state": "sent",
            "observed_at": now - timedelta(seconds=1),
            "sent_at": now - timedelta(seconds=5),
            "subject": "Synthetic test",
            "body": BODY,
            "recipients": (),
            **changes,
        }
    )


def principal(**changes):
    return Principal(
        **{
            "tenant": str(TENANT),
            "subject": str(CLIENT),
            "client": str(CLIENT),
            "roles": frozenset({"Detection.Investigator"}),
            "application": True,
            **changes,
        }
    )


def signed(message, message_ref, issuer, key_ref, private, fact, **changes):
    record = EvidenceRecord(
        **{
            "issuer_ref": issuer,
            "event_id": uuid4(),
            "tenant_id": message.tenant_id,
            "mailbox_id": message.mailbox_id,
            "message_ref": message_ref,
            "version_ref": message.version_ref,
            "occurred_at": message.sent_at,
            "issued_at": message.observed_at,
            "expires_at": message.observed_at + timedelta(days=2),
            "source_schema_version": "synthetic-source-v1",
            "fact": fact,
            **changes,
        }
    )
    envelope = SignedEvidence(
        key_ref=key_ref, record=record, signature=base64.b64encode(bytes(64)).decode()
    )
    return envelope.model_copy(
        update={"signature": base64.b64encode(private.sign(signing_bytes(envelope))).decode()}
    )


def enrolled(
    ledger,
    message,
    *,
    kinds=("send_execution", "generation", "content_inclusion", "content_edit", "copy_mapping"),
):
    ledger.enroll_scope(message.tenant_id, message.mailbox_id)
    ledger.enroll_observer(message.tenant_id, message.mailbox_id, message.source_ref)
    issuer, key = uuid4(), uuid4()
    private = Ed25519PrivateKey.generate()
    ledger.enroll_issuer(
        message.tenant_id, message.mailbox_id, issuer, client=CLIENT, subject=CLIENT, kinds=kinds
    )
    ledger.enroll_key(
        message.tenant_id,
        message.mailbox_id,
        issuer,
        key,
        private.public_key().public_bytes_raw(),
        utc_now() - timedelta(days=1),
        utc_now() + timedelta(days=7),
    )
    return issuer, key, private


def send_fact(message, **changes):
    from agenttrace_ledger.contracts import Identifier, SendExecution

    return SendExecution(
        **{
            "outcome": "completed",
            "actor": "ai_agent",
            "execution_ref": uuid4(),
            "actor_ref": CLIENT,
            "application_ref": CLIENT,
            "workflow_version": "fixture-v1",
            "mechanism": {
                "ai_agent": "agent",
                "human": "human_interaction_observed",
                "non_ai_application": "conventional_automation",
                "unknown": "unknown",
            }[changes.get("actor", "ai_agent")],
            "link_method": "exact_identifier",
            "identifier": Identifier(kind="mailbox_immutable", value=message.immutable_id),
            **changes,
        }
    )
