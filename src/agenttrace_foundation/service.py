"""Local synthetic reference processing; external mailbox ingestion is not enabled."""

from pathlib import Path

from agenttrace_attribution import assess_authored_example
from agenttrace_contracts import DetectionDecision
from agenttrace_evidence_adapters import AuthoredExampleReader

from .database import Database, StorageUnavailable
from .queue import DevelopmentQueue
from .store import DecisionStore


def process_one(database: Database, repository: Path) -> DetectionDecision | None:
    queue = DevelopmentQueue(database, "agent-evidence")
    lease = queue.receive()
    if lease is None:
        return None
    try:
        bundle = AuthoredExampleReader(repository).read_bundle(lease.payload.fixture_ref)
        findings = assess_authored_example(bundle)
        return DecisionStore(database).complete("agent-evidence", lease, findings)
    except (OSError, ValueError, StorageUnavailable):
        queue.retry(lease, delay_seconds=min(60, 2**lease.attempts))
        return None
