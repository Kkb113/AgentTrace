from dataclasses import replace

import pytest

from agenttrace_ingestion.pipeline import MailboxPipeline
from agenttrace_ingestion.store import IngestionStore
from agenttrace_ledger.bridge import enroll_ingestion_source, observe_ingested_snapshot
from agenttrace_ledger.canonical import LedgerError
from agenttrace_ledger.store import EvidenceLedger
from tests.ingestion_support import TENANT, GraphSource, cipher, enrollment, keypair

pytestmark = pytest.mark.integration


def test_committed_ingestion_extraction_and_ledger_have_an_exact_version_chain(database):
    source_scope = enrollment()
    ingestion = IngestionStore(database, cipher())
    ingestion.enroll(source_scope)
    source = GraphSource(source_scope)
    source.put()
    pipeline = MailboxPipeline(ingestion, source.client(), keypair().public_key())
    assert pipeline.reconcile("pilot-folder") == 1
    assert pipeline.process_one()
    ledger = EvidenceLedger(database, cipher(), {TENANT: bytes([9]) * 32})
    enroll_ingestion_source(ledger, ingestion, source_scope)
    snapshot = source.client().read("MessageCaseSensitive")
    ref = observe_ingested_snapshot(ledger, ingestion, source_scope, snapshot)
    ingest_ref = ingestion.cipher.reference(str(source_scope.source_ref), snapshot.immutable_id)
    version_ref = ingestion.cipher.reference(str(ingest_ref), snapshot.change_key)
    view = ledger.view(source_scope.tenant_id, source_scope.mailbox_id, ref, version_ref)
    assert view["source"]["source_event_ref"] == str(version_ref)
    assert view["source"]["capture_basis"] == "committed_ingestion"
    assert view["source"]["recipients_complete"] is False
    assert view["correlations"]["agent_send_attribution"] == []
    assert observe_ingested_snapshot(ledger, ingestion, source_scope, snapshot) == ref
    with pytest.raises(LedgerError, match="content_version"):
        observe_ingested_snapshot(
            ledger, ingestion, source_scope, replace(snapshot, body="Altered body")
        )
    with pytest.raises(LedgerError, match="identifier_mapping"):
        observe_ingested_snapshot(
            ledger,
            ingestion,
            source_scope,
            replace(snapshot, internet_message_id="<wrong@example.invalid>"),
        )
    with pytest.raises(LedgerError, match="current_ingestion_version"):
        observe_ingested_snapshot(
            ledger, ingestion, source_scope, replace(snapshot, change_key="wrong-version")
        )
