import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agenttrace_foundation.artifacts import ArtifactComponent, verify_local_component
from tests.support import temporary_workspace

ROOT = Path(__file__).resolve().parents[2]


def test_catalog_records_unacquired_components_without_invented_hashes():
    catalog = json.loads((ROOT / "config/artifact-catalog.json").read_text())
    components = [ArtifactComponent.model_validate(item) for item in catalog["components"]]
    assert {c.kind for c in components} >= {
        "research_code",
        "model_weights",
        "tokenizer",
        "dataset",
    }
    assert all(c.state == "not_acquired" and c.sha256 is None for c in components)


def test_verified_artifact_requires_separate_license_evidence():
    with pytest.raises(ValidationError):
        ArtifactComponent(
            component_id="missing-rights",
            kind="model_weights",
            state="verified",
            source_url="local:fixture",
            revision="test",
            sha256="0" * 64,
        )


def test_hash_mismatch_and_path_escape_fail_before_inference():
    with temporary_workspace() as temporary:
        root = Path(temporary)
        content = b"Authored test artifact; not trained model weights."
        path = root / "test.safetensors"
        path.write_bytes(content)
        item = ArtifactComponent(
            component_id="authored-test",
            kind="model_weights",
            state="verified",
            source_url="local:authored-test",
            revision="test-fixture",
            sha256=hashlib.sha256(content).hexdigest(),
            license_spdx="LicenseRef-AuthoredTest",
            license_evidence_sha256=hashlib.sha256(b"Authored test rights").hexdigest(),
            license_reviewed=True,
        )
        verify_local_component(item, path, root)
        with pytest.raises(ValueError, match="approved_local_artifact"):
            verify_local_component(item, path, root / "other")
        path.write_bytes(b"tampered")
        with pytest.raises(ValueError, match="artifact_hash_mismatch"):
            verify_local_component(item, path, root)
