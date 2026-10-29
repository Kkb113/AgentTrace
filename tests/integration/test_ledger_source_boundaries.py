from uuid import uuid4

import pytest

from agenttrace_ingestion.pipeline import MailboxPipeline
from agenttrace_ingestion.store import IngestionStore
from agenttrace_ledger.bridge import enroll_ingestion_source, observe_ingested_snapshot
from agenttrace_ledger.canonical import LedgerError
from agenttrace_ledger.contracts import CopyMapping
from agenttrace_ledger.store import EvidenceLedger
from tests.ingestion_support import CLIENT, TENANT, GraphSource, cipher, enrollment, keypair
from tests.ledger_support import enrolled, observation, principal, send_fact, signed

pytestmark = pytest.mark.integration


def test_ambiguous_extraction_does_not_acquire_authored_provenance(database):
    source_scope = enrollment()
    ingestion = IngestionStore(database, cipher())
    ingestion.enroll(source_scope)
    source = GraphSource(source_scope)
    source.put(body="New\u200b text")
    pipeline = MailboxPipeline(ingestion, source.client(), keypair().public_key())
    assert pipeline.reconcile("pilot-folder") == 1 and pipeline.process_one()
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    enroll_ingestion_source(ledger, ingestion, source_scope)
    snapshot = source.client().read("MessageCaseSensitive")
    ref = observe_ingested_snapshot(ledger, ingestion, source_scope, snapshot)
    original = ingestion.cipher.reference(str(source_scope.source_ref), snapshot.immutable_id)
    version = ingestion.cipher.reference(str(original), snapshot.change_key)
    view = ledger.view(source_scope.tenant_id, source_scope.mailbox_id, ref, version)
    assert view["source"]["content_available"] is False
    assert view["correlations"]["content_assessment"] == []


@pytest.mark.parametrize("mismatched_identity", [False, True])
def test_cross_mailbox_mapping_requires_dual_matching_issuer_enrollment(
    database, mismatched_identity
):
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation()
    issuer, key, private = enrolled(ledger, message)
    ref = ledger.observe(message)
    other = observation(
        mailbox_id=uuid4(), immutable_id="ScopedRecipient", copy_role="recipient", state="received"
    )
    ledger.enroll_scope(other.tenant_id, other.mailbox_id)
    ledger.enroll_observer(other.tenant_id, other.mailbox_id, other.source_ref)
    ledger.enroll_issuer(
        other.tenant_id,
        other.mailbox_id,
        issuer,
        client=uuid4() if mismatched_identity else CLIENT,
        subject=CLIENT,
        kinds=("copy_mapping",),
    )
    other_ref = ledger.observe(other)
    fact = CopyMapping(
        other_message_ref=other_ref,
        other_version_ref=other.version_ref,
        relation="delivery_copy",
        mapping_basis="authenticated_source_mapping",
    )
    ledger.submit(signed(message, ref, issuer, key, private, fact), principal())
    view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert view["copy_mappings"][0]["classification"] == (
        "candidate" if mismatched_identity else "exact_mapping"
    )
    assert view["correlations"]["agent_send_attribution"] == []


def test_unavailable_content_does_not_block_independent_exact_action_evidence(database):
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation(body="", content_available=False)
    issuer, key, private = enrolled(ledger, message)
    ref = ledger.observe(message)
    ledger.submit(signed(message, ref, issuer, key, private, send_fact(message)), principal())
    view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert view["source"]["content_available"] is False
    assert view["correlations"]["agent_send_attribution"][0]["classification"] == "exact"
    assert view["correlations"]["content_assessment"] == []


def test_issuer_kind_and_observer_schema_enrollment_are_enforced(database):
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation()
    issuer, key, private = enrolled(ledger, message, kinds=("generation",))
    with pytest.raises(LedgerError, match="observer_not_enrolled"):
        ledger.observe(message.model_copy(update={"source_schema_version": "unreviewed-v2"}))
    ref = ledger.observe(message)
    with pytest.raises(LedgerError, match="capability_untrusted"):
        ledger.submit(signed(message, ref, issuer, key, private, send_fact(message)), principal())


def test_tied_versions_and_contradictory_completed_actions_remain_uncertain(database):
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    message = observation()
    issuer, key, private = enrolled(ledger, message)
    ref = ledger.observe(message)
    ledger.submit(signed(message, ref, issuer, key, private, send_fact(message)), principal())
    ledger.submit(
        signed(message, ref, issuer, key, private, send_fact(message, actor="human")), principal()
    )
    assert all(
        r["classification"] == "conflicting"
        for r in ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)[
            "correlations"
        ]["agent_send_attribution"]
    )
    ledger.observe(message.model_copy(update={"version_ref": uuid4(), "source_event_ref": uuid4()}))
    view = ledger.view(message.tenant_id, message.mailbox_id, ref, message.version_ref)
    assert view["current_message_version"] is False
    assert all(
        r["classification"] == "invalid" for r in view["correlations"]["agent_send_attribution"]
    )
