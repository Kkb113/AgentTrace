import json
import os
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

import pytest
from agenttrace_contracts import DetectionDecision

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_real_api_worker_database_round_trip_over_loopback():
    if os.environ.get("AGENTTRACE_INTEGRATION") != "1":
        pytest.skip("Explicit local-stack integration run required")
    with urlopen("http://127.0.0.1:8080/health/ready", timeout=5) as response:
        health = json.load(response)
    assert health["status"] == "ready" and health["content_model"] == "not_installed"
    created = subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            os.environ.get("AGENTTRACE_COMPOSE_PROJECT", "agenttrace-foundation"),
            "--file",
            "compose.yaml",
            "exec",
            "-T",
            "api",
            "agenttrace-foundation",
            "enqueue-example",
            "--key",
            uuid4().hex,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    decision_id = json.loads(created.stdout)["decision_id"]
    deadline = time.monotonic() + 15
    result = None
    while time.monotonic() < deadline:
        try:
            with urlopen(
                "http://127.0.0.1:8080/v1/decisions/" + decision_id, timeout=3
            ) as response:
                result = DetectionDecision.model_validate_json(response.read())
            break
        except HTTPError as error:
            assert error.code == 404
            time.sleep(0.25)
    assert result is not None
    assert result.validation_basis == "authored_contract_example"
    assert result.findings.agent_send_attribution.flagged is True
    assert result.findings.content_assessment.flagged is None
