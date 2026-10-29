"""Shared fail-fast commands for local runs, GitHub Actions and Azure Pipelines."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def run(command: list[str], *, environment: dict[str, str] | None = None) -> int:
    return subprocess.run(command, cwd=ROOT, env=environment, shell=False, check=False).returncode


def tool(name: str) -> str:
    config = json.loads((ROOT / "config/toolchain.json").read_text())
    return str(
        ROOT
        / "work/tools"
        / f"{name}-{config[name]['version']}"
        / (name + (".exe" if os.name == "nt" else ""))
    )


def source_files() -> list[str]:
    response = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return sorted(set(filter(None, response.stdout.decode().split("\0"))))


def secret_scan(directory: Path) -> int:
    return run(
        [tool("gitleaks"), "dir", str(directory), "--redact", "--no-banner", "--exit-code", "1"]
    )


def security() -> int:
    with tempfile.TemporaryDirectory(dir=ROOT / "work", prefix="source-scan-") as temporary:
        export = Path(temporary)
        assert export.resolve().is_relative_to((ROOT / "work").resolve())
        for name in source_files():
            if name.startswith("outputs/"):
                continue  # Pre-existing client workbook is outside this implementation's publishing scope.
            source = ROOT / name
            if source.is_file():
                target = export / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        result = secret_scan(export)
        if result:
            return result
    commands = [
        [PYTHON, "scripts/check-privacy.py"],
        [PYTHON, "scripts/check-licenses.py"],
        [
            PYTHON,
            "-m",
            "pip_audit",
            "-r",
            "requirements-development.txt",
            "--require-hashes",
            "--no-deps",
            "--disable-pip",
            "--progress-spinner",
            "off",
            "--format",
            "json",
            "--output",
            "work/reports/dependency-audit.json",
        ],
    ]
    for command in commands:
        if result := run(command):
            return result
    return 0


def guard_controls() -> int:
    with tempfile.TemporaryDirectory(dir=ROOT / "work", prefix="guard-controls-") as temporary:
        directory = Path(temporary)
        assert directory.resolve().is_relative_to((ROOT / "work").resolve())
        (directory / "invalid.json").write_text(
            '{"findings":{"third_finding":{}}}', encoding="utf-8"
        )
        (directory / "test_deliberate_failure.py").write_text(
            "def test_deliberate_failure():\n    assert False\n", encoding="utf-8"
        )
        # Assembled at runtime: deliberately invalid, nonfunctional synthetic credential.
        (directory / "synthetic.env").write_text(
            "AWS_ACCESS_KEY_ID=" + "AK" + "IA" + "ABCDEFGHIJKLMNOP" + "\n", encoding="utf-8"
        )
        outcomes = {
            "invalid_contract": run(
                [PYTHON, "scripts/validate-contract.py", str(directory / "invalid.json")]
            ),
            "failing_test": run(
                [
                    PYTHON,
                    "-m",
                    "pytest",
                    str(directory / "test_deliberate_failure.py"),
                    "-q",
                    "--tb=no",
                ]
            ),
            "synthetic_secret": secret_scan(directory),
        }
        output = ROOT / "work/reports/guard-controls.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(outcomes, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps({"negative_gate_exit_codes": outcomes}))
        return 0 if all(value == 1 for value in outcomes.values()) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "gate", choices=["quality", "security", "infrastructure", "integration", "guard-controls"]
    )
    args = parser.parse_args()
    (ROOT / "work/reports").mkdir(parents=True, exist_ok=True)
    if args.gate == "security":
        return security()
    if args.gate == "guard-controls":
        return guard_controls()
    if args.gate == "infrastructure":
        return run([PYTHON, "scripts/validate-infrastructure.py"])
    if args.gate == "integration":
        if result := run([PYTHON, "scripts/dev-services.py", "start"]):
            return result
        environment = dict(os.environ, AGENTTRACE_INTEGRATION="1")
        return run(
            [
                PYTHON,
                "-m",
                "pytest",
                "-m",
                "integration",
                "-q",
                "--tb=short",
                "--junitxml=work/reports/integration.xml",
            ],
            environment=environment,
        )
    for command in [
        [PYTHON, "-m", "ruff", "check", "src", "packages", "scripts", "tests"],
        [PYTHON, "-m", "ruff", "format", "--check", "src", "packages", "scripts", "tests"],
        [PYTHON, "-m", "mypy"],
        [PYTHON, "scripts/export-locks.py", "--check"],
        [PYTHON, "scripts/export-contracts.py", "--check"],
        [PYTHON, "scripts/verify-outlook-baseline.py"],
        [
            PYTHON,
            "-m",
            "mypy",
            "--strict",
            "--follow-imports",
            "normal",
            "src/agenttrace_feasibility/outlook_baseline.py",
        ],
        [PYTHON, "scripts/check-boundaries.py"],
        [PYTHON, "scripts/verify-language-artifacts.py"],
        [
            PYTHON,
            "-m",
            "pytest",
            "-m",
            "not integration",
            "-q",
            "--tb=short",
            "--junitxml=work/reports/unit.xml",
        ],
    ]:
        if result := run(command):
            return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
