"""Advance the approved bounded Exchange audit reader; print only aggregate status."""

import json
from pathlib import Path
from uuid import UUID, uuid4

from agenttrace_foundation.workload_identity import CertificateTokenProvider
from agenttrace_ingestion.audit import ExchangeAuditCollector, OptionalActivityCollector
from agenttrace_ingestion.contracts import IngestionError, utc_now
from agenttrace_ingestion.runtime import load
from agenttrace_ingestion.transport import MicrosoftTransport

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "work/private/mail-ingestion"
    _, enrollment, operator, _, _ = load(directory / "runtime.private.json", operator=True)
    _, _, collector, _, _ = load(directory / "runtime.private.json")
    baseline = ROOT / "work/private/secure-access"
    identities = json.loads((baseline / "workload-identities.private.json").read_text())
    settings = json.loads(
        (baseline / "sandbox-settings.private.json").read_text(encoding="utf-8-sig")
    )
    refs_file = directory / "audit-sources.private.json"
    refs = (
        json.loads(refs_file.read_text())
        if refs_file.exists()
        else {
            kind: str(uuid4()) for kind in ["exchange_audit", "office_activity", "graph_activity"]
        }
    )
    refs_file.write_text(json.dumps(refs, indent=2))
    for kind, ref in refs.items():
        operator.enroll(
            enrollment.model_copy(update={"source_ref": UUID(ref)}),
            kind=kind,
            alias=kind.replace("_", "-"),
        )
    with collector.database.connect() as connection:
        rows = connection.execute(
            "SELECT message_ref,locator_cipher FROM ingest_copies WHERE source_ref=%s",
            (enrollment.source_ref,),
        ).fetchall()
    message_ids = set()
    for row in rows:
        value = collector.cipher.open(
            bytes(row["locator_cipher"]), context="message:" + str(row["message_ref"])
        )
        if value.get("internet_message_id"):
            message_ids.add(value["internet_message_id"])
    if not message_ids:
        raise IngestionError("synthetic_message_identifiers_required")
    identity = identities["audit-collector"]
    provider = CertificateTokenProvider(
        settings["tenant"],
        identity["application"]["appId"],
        identity["certificate"]["thumbprint"],
        ROOT / "scripts/manage-workload-certificate.ps1",
    )
    transport = MicrosoftTransport(
        lambda *, force_refresh=False: provider.token(
            "https://graph.microsoft.com", force_refresh=force_refresh
        )
    )
    audit = ExchangeAuditCollector(
        collector,
        transport,
        UUID(refs["exchange_audit"]),
        mailbox=settings["mailbox"],
        collector_clients={
            identities[name]["application"]["appId"]
            for name in ["mail-collector", "audit-collector"]
        },
        allowed_message_ids=message_ids,
    )
    count = audit.collect(window_end=utc_now())
    for kind in ["office_activity", "graph_activity"]:
        OptionalActivityCollector(collector, UUID(refs[kind]), kind).unavailable()
    health = collector.health(UUID(refs["exchange_audit"]))
    result = {
        "exchange_audit_records_added": count,
        "checkpoint": health["checkpoints"],
        "optional_activity_sources": "explicitly_unavailable_no_new_grants",
    }
    (directory / "audit-collection-status.private.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
