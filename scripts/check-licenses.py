"""Fail closed on unknown/new license metadata and retain a dependency inventory."""

import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    policy = json.loads((ROOT / "config/dependency-license-policy.json").read_text())
    result = subprocess.run(
        [sys.executable, "-m", "piplicenses", "--format=json", "--with-system", "--with-urls"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )
    packages = json.loads(result.stdout)
    failures, inventory = [], []
    for package in packages:
        name = package["Name"]
        if name == policy["own_project"]:
            continue
        license_name = package["License"]
        review = policy["reviewed_legacy_metadata"].get(name)
        if (
            review
            and package["Version"] == review["version"]
            and license_name == review["metadata"]
        ):
            license_name = review["spdx"]
        if license_name not in policy["allowed_metadata"]:
            failures.append(name)
        texts = []
        distribution = importlib.metadata.distribution(name)
        for file in distribution.files or []:
            if "license" in file.name.lower() or file.name.lower() in {"copying", "notice"}:
                path = distribution.locate_file(file)
                if path.is_file():
                    texts.append(hashlib.sha256(path.read_bytes()).hexdigest())
        inventory.append(
            {
                "name": name,
                "version": package["Version"],
                "declared_license": package["License"],
                "reviewed_license": license_name,
                "license_text_sha256": sorted(set(texts)),
            }
        )
    output = ROOT / "work/reports/dependency-licenses.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"packages": inventory, "unreviewed_packages": failures}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"dependencies_reviewed": len(inventory), "unreviewed_packages": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
