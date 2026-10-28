"""Manifest checks for separately stored, reviewed model and data components."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from agenttrace_contracts import Contract
from pydantic import Field, model_validator


class ArtifactComponent(Contract):
    component_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,99}$")
    kind: Literal["research_code", "model_weights", "tokenizer", "dataset", "calibration"]
    state: Literal["not_acquired", "verified"]
    source_url: str
    revision: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    license_spdx: str | None = None
    license_evidence_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    license_reviewed: bool = False
    trust_remote_code: Literal[False] = False

    @model_validator(mode="after")
    def verified_components_are_complete(self) -> ArtifactComponent:
        if self.state == "verified" and not all(
            [
                self.revision,
                self.sha256,
                self.license_spdx,
                self.license_evidence_sha256,
                self.license_reviewed,
            ]
        ):
            raise ValueError("verified_artifact_requires_revision_hash_and_license_evidence")
        if self.state == "not_acquired" and self.sha256 is not None:
            raise ValueError("unacquired_artifact_cannot_claim_verified_bytes")
        return self


def verify_local_component(component: ArtifactComponent, path: Path, artifact_root: Path) -> None:
    if component.state != "verified" or not path.resolve().is_relative_to(artifact_root.resolve()):
        raise ValueError("approved_local_artifact_required")
    if component.kind == "model_weights" and path.suffix != ".safetensors":
        raise ValueError("reviewed_safetensors_weights_required")
    result = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            result.update(chunk)
    if result.hexdigest() != component.sha256:
        raise ValueError("artifact_hash_mismatch")
