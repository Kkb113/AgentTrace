"""Compile Bicep and check foundation defaults without provisioning anything."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    version = json.loads((ROOT / "config/toolchain.json").read_text())["bicep"]["version"]
    executable = (
        ROOT / "work/tools" / ("bicep-" + version) / ("bicep.exe" if os.name == "nt" else "bicep")
    )
    output = ROOT / "work/infra"
    output.mkdir(parents=True, exist_ok=True)
    extraction = ROOT / "work/dotnet-bundle"
    extraction.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, DOTNET_BUNDLE_EXTRACT_BASE_DIR=str(extraction))
    for source in sorted((ROOT / "infra/bicep").rglob("*.bicep")):
        result = subprocess.run(
            [
                str(executable),
                "build",
                str(source),
                "--outfile",
                str(output / (source.stem + ".json")),
            ],
            check=False,
            shell=False,
            env=environment,
        )
        if result.returncode:
            return result.returncode
    result = subprocess.run(
        [
            str(executable),
            "build-params",
            str(ROOT / "infra/bicep/validation.bicepparam"),
            "--outfile",
            str(output / "validation.parameters.json"),
        ],
        check=False,
        shell=False,
        env=environment,
    )
    if result.returncode:
        return result.returncode
    template = json.loads((output / "main.json").read_text(encoding="utf-8-sig"))
    parameters = template["parameters"]
    assert parameters["enableProvisioning"]["defaultValue"] is False
    assert parameters["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert parameters["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in resource for resource in template["resources"])
    access = json.loads((output / "access-sandbox.json").read_text(encoding="utf-8-sig"))
    assert access["parameters"]["enableProvisioning"]["defaultValue"] is False
    assert access["parameters"]["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert access["parameters"]["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in resource for resource in access["resources"])
    notifications = json.loads(
        (output / "notification-transport.json").read_text(encoding="utf-8-sig")
    )
    assert notifications["parameters"]["enableProvisioning"]["defaultValue"] is False
    assert notifications["parameters"]["expectedResourceGroup"]["allowedValues"] == ["kb-agentdemo"]
    assert notifications["parameters"]["location"]["allowedValues"] == ["eastus"]
    assert all("condition" in resource for resource in notifications["resources"])
    print(
        json.dumps(
            {
                "bicep_modules_compiled": len(list((ROOT / "infra/bicep").rglob("*.bicep"))),
                "parameters_compiled": True,
                "resources_provisioned": 0,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
