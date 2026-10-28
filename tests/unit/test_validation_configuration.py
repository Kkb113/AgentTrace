import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_both_ci_definitions_call_the_shared_fail_fast_gates():
    github = (ROOT / ".github/workflows/validation.yml").read_text()
    azure = (ROOT / "ci/azure-pipelines.yml").read_text()
    document = yaml.load(github, Loader=yaml.BaseLoader)
    assert "pull_request" in document["on"]
    assert document["permissions"] == {"contents": "read"}
    assert "pull_request_target" not in document["on"]
    gates = document["jobs"]["validation"]["strategy"]["matrix"]["gate"]
    assert set(gates) == {"security", "infrastructure", "integration", "guard-controls"}
    assert "ci-checks.py quality" in github
    assert all("ci-checks.py " + gate in azure for gate in ["quality", *gates])
    assert "continue-on-error" not in github and "continueOnError" not in azure
    assert "secrets." not in github and "id-token: write" not in github


def test_local_ports_are_loopback_and_workers_stay_on_internal_network():
    config = yaml.safe_load((ROOT / "compose.yaml").read_text())
    assert config["networks"]["private"]["internal"] is True
    for service in config["services"].values():
        for port in service.get("ports", []):
            assert port.startswith("127.0.0.1:")
    for role in ["content-worker", "attribution-worker"]:
        assert config["services"][role]["networks"] == ["private"]
        assert not config["services"][role].get("ports")
    assert "@sha256:" in config["services"]["postgres"]["image"]
    assert "@sha256:" in (ROOT / "Dockerfile").read_text().splitlines()[0]


def test_sensitive_artifacts_are_excluded_from_build_and_git():
    ignored = (ROOT / ".gitignore").read_text()
    context = (ROOT / ".dockerignore").read_text()
    for token in ["work/", ".env", "*.safetensors", "*.parquet"]:
        assert token in ignored
    assert "work" in context and "outputs" in context and ".git" in context


def test_schema_exports_have_exactly_two_findings():
    contract = json.loads(
        (ROOT / "packages/contracts/schemas/detection-decision.schema.json").read_text()
    )
    assert set(contract["$defs"]["DetectionFindings"]["properties"]) == {
        "agent_send_attribution",
        "content_assessment",
    }
