"""Read-only evidence ports. There is no execution operation in this interface."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class EvidenceReader(Protocol):
    def read_bundle(self, reference: str) -> Path: ...


@dataclass(frozen=True)
class AuthoredExampleReader:
    repository_root: Path

    def read_bundle(self, reference: str) -> Path:
        if reference != "authored_contract_example":
            raise ValueError("unsupported_evidence_reference")
        path = self.repository_root / "examples/evidence-contract"
        if not path.is_dir():
            raise ValueError("authored_example_not_available")
        return path
