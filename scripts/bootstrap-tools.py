"""Install only hash-pinned official validation tools into ignored workspace storage."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import tarfile
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def install(name: str) -> Path:
    config = json.loads((ROOT / "config/toolchain.json").read_text())[name]
    platform = "windows" if sys.platform == "win32" else "linux"
    spec = config[platform]
    expected_prefix = {
        "gitleaks": "https://github.com/gitleaks/gitleaks/releases/download/",
        "bicep": "https://github.com/Azure/bicep/releases/download/",
    }[name]
    if not spec["url"].startswith(expected_prefix):
        raise ValueError("unapproved_tool_source")
    directory = ROOT / "work/tools" / f"{name}-{config['version']}"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / "download"
    if not archive.is_file() or hashlib.sha256(archive.read_bytes()).hexdigest() != spec["sha256"]:
        with urlopen(spec["url"], timeout=60) as response, archive.open("wb") as output:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > 200 * 1024 * 1024:
                    raise ValueError("tool_download_too_large")
                output.write(chunk)
    payload = archive.read_bytes()
    if hashlib.sha256(payload).hexdigest() != spec["sha256"]:
        raise ValueError("tool_hash_mismatch")
    filename = name + (".exe" if os.name == "nt" else "")
    target = directory / filename
    if name == "gitleaks":
        if platform == "windows":
            with zipfile.ZipFile(io.BytesIO(payload)) as contents:
                binary = contents.read(filename)
        else:
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as contents:
                member = contents.getmember(filename)
                if not member.isfile() or member.size > 100 * 1024 * 1024:
                    raise ValueError("unexpected_tool_archive")
                stream = contents.extractfile(member)
                assert stream is not None
                binary = stream.read()
        target.write_bytes(binary)
    else:
        target.write_bytes(payload)
    target.chmod(0o755)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", choices=["gitleaks", "bicep", "all"])
    args = parser.parse_args()
    for name in ["gitleaks", "bicep"] if args.tool == "all" else [args.tool]:
        install(name)
        print(json.dumps({"tool": name, "status": "verified"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
