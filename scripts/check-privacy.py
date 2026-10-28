"""Reject accidental real addresses, unknown identifiers and model/data binaries."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUID = re.compile(r"\b[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def main() -> int:
    known = set(json.loads((ROOT / "config/public-identifiers.json").read_text())["identifiers"])
    response = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    issues = []
    for name in sorted(set(filter(None, response.stdout.decode().split("\0")))):
        if name.startswith("outputs/"):
            continue
        path = ROOT / name
        if path.suffix in {
            ".safetensors",
            ".onnx",
            ".pt",
            ".bin",
            ".parquet",
            ".jsonl",
            ".pfx",
            ".key",
            ".pem",
        }:
            issues.append({"path": name, "reason": "artifact_or_credential_file_in_git_scope"})
        if not path.is_file() or path.suffix not in {
            ".py",
            ".md",
            ".json",
            ".yml",
            ".yaml",
            ".toml",
            ".txt",
            ".bicep",
            ".eml",
            ".bicepparam",
        }:
            continue
        content = path.read_text(encoding="utf-8-sig")
        if any(
            value not in known and not value.startswith("00000000-")
            for value in GUID.findall(content)
        ):
            issues.append({"path": name, "reason": "unreviewed_identifier"})
        if any(not domain.endswith(".invalid") for domain in EMAIL.findall(content)):
            issues.append({"path": name, "reason": "nonfictional_email_address"})
        if "-----BEGIN " + "PRIVATE KEY-----" in content or re.search(
            r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.", content
        ):
            issues.append({"path": name, "reason": "credential_material"})
    print(json.dumps({"privacy_issues": issues}))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
