"""Download the hash-pinned operator-only Exchange module without global installation."""

import hashlib
import io
import json
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    entry = json.loads((ROOT / "config/administration-toolchain.json").read_text())[
        "exchange_online_management"
    ]
    target = ROOT / "work/tools/ExchangeOnlineManagement" / entry["version"]
    with urlopen(entry["url"], timeout=60) as response:
        source = response.read(40_000_001)
    if len(source) > 40_000_000 or hashlib.sha256(source).hexdigest() != entry["sha256"]:
        raise ValueError("administration_tool_hash_mismatch")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(source)) as archive:
        if any(
            not (target / name).resolve().is_relative_to(target.resolve())
            for name in archive.namelist()
        ):
            raise ValueError("unsafe_administration_archive")
        archive.extractall(target)
    print(
        json.dumps(
            {
                "operator_tool": "ExchangeOnlineManagement",
                "version": entry["version"],
                "sha256_verified": True,
            }
        )
    )


if __name__ == "__main__":
    main()
