"""Start/stop only the named local synthetic Compose project."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop", "status"])
    parser.add_argument(
        "--project",
        choices=["agenttrace-foundation", "agenttrace-foundation-clean"],
        default="agenttrace-foundation",
    )
    args = parser.parse_args()
    secret = ROOT / "work/local/postgres-password"
    if args.command == "start" and not secret.exists():
        secret.parent.mkdir(parents=True, exist_ok=True)
        secret.parent.chmod(0o700)
        with secret.open("x", encoding="utf-8") as output:
            output.write(secrets.token_urlsafe(32))
        # The host directory is private; the mounted file must be readable by
        # the non-root application UID on Linux. It holds only a local test secret.
        secret.chmod(0o644)
    command = [
        "docker",
        "compose",
        "--project-name",
        args.project,
        "--file",
        str(ROOT / "compose.yaml"),
    ]
    if args.command == "start":
        built = subprocess.run(command + ["build", "migrate"], cwd=ROOT, shell=False, check=False)
        if built.returncode:
            return built.returncode
    command += {
        "start": ["up", "--wait", "--wait-timeout", "180"],
        "stop": ["down"],
        "status": ["ps"],
    }[args.command]
    result = subprocess.run(command, cwd=ROOT, shell=False, check=False)
    print(json.dumps({"operation": args.command, "succeeded": result.returncode == 0}))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
