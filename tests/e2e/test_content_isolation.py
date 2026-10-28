import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[2]


def test_running_content_container_has_no_external_route_or_other_workload_credentials():
    if os.environ.get("AGENTTRACE_INTEGRATION") != "1":
        pytest.skip("Explicit sandbox integration required")
    probe = """
import json, pathlib, socket
routes=pathlib.Path('/proc/net/route').read_text().splitlines()[1:]
default_route=any(row.split()[1]=='00000000' for row in routes if row.split())
connected=False
try:
    connection=socket.create_connection(('1.1.1.1',443),timeout=3)
    connected=True
    connection.close()
except OSError:
    pass
print(json.dumps({'default_route':default_route,'external_tcp_connected':connected,'mounted_secrets':sorted(p.name for p in pathlib.Path('/run/secrets').iterdir())}))
"""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-name",
            os.environ.get("AGENTTRACE_COMPOSE_PROJECT", "agenttrace-foundation"),
            "--file",
            "compose.yaml",
            "exec",
            "-T",
            "content-worker",
            "python",
            "-c",
            probe,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    observed = json.loads(result.stdout)
    assert not observed["default_route"] and not observed["external_tcp_connected"]
    assert observed["mounted_secrets"] == ["content_password"]
