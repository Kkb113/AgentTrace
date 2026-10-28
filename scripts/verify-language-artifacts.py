"""Verify bundled offline language profiles and their shipped license notices."""

import hashlib
import importlib.metadata
import json
from pathlib import Path

from langdetect.detector_factory import PROFILES_DIRECTORY

ROOT = Path(__file__).resolve().parents[1]


def inventory():
    files = []
    for path in sorted(Path(PROFILES_DIRECTORY).iterdir()):
        if path.is_file():
            files.append(
                {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            )
    distribution = importlib.metadata.distribution("langdetect")
    notices = []
    for entry in distribution.files or []:
        if entry.name in {"LICENSE", "NOTICE"}:
            notices.append(
                {
                    "path": entry.name,
                    "sha256": hashlib.sha256(
                        distribution.locate_file(entry).read_bytes()
                    ).hexdigest(),
                }
            )
    return {
        "package": "langdetect",
        "version": distribution.version,
        "profile_count": len(files),
        "profile_manifest_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "notices": sorted(notices, key=lambda n: n["path"]),
    }


def main():
    expected = json.loads((ROOT / "config/language-artifacts.json").read_text())
    actual = inventory()
    if expected != actual:
        raise RuntimeError("offline_language_artifacts_differ_from_reviewed_manifest")
    print(
        json.dumps(
            {
                "offline_language_profiles_verified": actual["profile_count"],
                "runtime_downloads": False,
            }
        )
    )


if __name__ == "__main__":
    main()
