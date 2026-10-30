"""Offline sender study CLI; never sends mail, writes categories or calls Microsoft."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from agenttrace_feasibility.validation import canonical_bytes

from .accuracy import inspect_study, run_study
from .accuracy_collection import prepare_collection
from .accuracy_contracts import AccuracyDataset, Split
from .accuracy_io import (
    asset_bytes,
    checked_path,
    decode,
    detector_digest,
    digest,
    load_dataset,
    policy_digest,
    read,
    write_new,
)
from .errors import OutlookError
from .evaluation_lock import grant, open_once, seal


def export_development(
    root: Path, dataset: AccuracyDataset, destination: Path, now: datetime
) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    selected = tuple(c for c in dataset.cases if c.split != "evaluation")
    exported = dataset.model_copy(update={"cases": selected, "usage": "development_export"})
    for case in selected:
        for asset in (
            case.input,
            case.action,
            case.rights,
            *[r.attestation for r in case.reviews],
            *([case.message] if case.message else []),
        ):
            path = destination / asset.path
            if not path.resolve().is_relative_to(destination.resolve()):
                raise OutlookError("study_asset_outside_root")
            data = asset_bytes(root, asset, now)
            if path.exists():
                if digest(read(path)) != digest(data):
                    raise OutlookError("study_export_asset_conflict")
                continue
            checked_path(path)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.touch(mode=0o600, exist_ok=False)
            path.write_bytes(data)
    write_new(destination / "dataset.json", exported.model_dump(mode="json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("fingerprint")
    freeze.add_argument("--output", type=Path, required=True)
    key = sub.add_parser("create-key")
    key.add_argument("--output", type=Path, required=True)
    collection = sub.add_parser("prepare-collection")
    collection.add_argument("--output", type=Path, required=True)
    for command in ("inspect", "run", "export-development", "seal"):
        item = sub.add_parser(command)
        item.add_argument("--dataset", type=Path, required=True)
        item.add_argument("--output", type=Path, required=True)
        if command == "run":
            item.add_argument("--split", choices=["development", "calibration"], required=True)
        if command == "seal":
            item.add_argument("--key", type=Path, required=True)
            item.add_argument("--developer-principal", required=True)
            item.add_argument("--control-drill", action="store_true")
    for command in ("grant", "evaluate-locked"):
        item = sub.add_parser(command)
        item.add_argument("--archive", type=Path, required=True)
        item.add_argument("--key", type=Path, required=True)
        item.add_argument("--output", type=Path, required=True)
        if command == "evaluate-locked":
            item.add_argument("--permit", type=Path, required=True)
            item.add_argument("--receipts", type=Path, required=True)
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    try:
        if args.command == "prepare-collection":
            prepare_collection(args.output)
        elif args.command == "fingerprint":
            write_new(
                args.output,
                {
                    "detector_sha256": detector_digest(),
                    "policy_sha256": policy_digest(),
                    "created_at": now.isoformat(),
                },
            )
        elif args.command == "create-key":
            checked_path(args.output)
            args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(secrets.token_bytes(32))
        elif args.command == "grant":
            write_new(args.output, grant(args.archive, args.key, now))
        elif args.command == "evaluate-locked":
            frozen = open_once(
                args.archive, decode(read(args.permit)), args.key, args.receipts, now
            )
            args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.TemporaryDirectory(
                dir=args.output.parent, prefix="locked-replay-"
            ) as temporary:
                root = Path(temporary)
                assert root.resolve().is_relative_to(args.output.parent.resolve())
                for relative, content in frozen["assets"].items():
                    path = root / relative
                    if Path(relative).is_absolute() or not path.resolve().is_relative_to(
                        root.resolve()
                    ):
                        raise OutlookError("study_asset_outside_root")
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    path.touch(mode=0o600, exist_ok=False)
                    path.write_bytes(base64.b64decode(content, validate=True))
                dataset = AccuracyDataset.model_validate_json(canonical_bytes(frozen["dataset"]))
                report = run_study(root, dataset, "evaluation", now, locked_access_verified=True)
                # Control drills exercise software but never establish actual independent access.
                report["locked_access_verified"] = frozen["metadata"]["access"][
                    "independent_access_verified"
                ]
                report["control_drill"] = frozen["metadata"]["control_drill"]
                if not report["locked_access_verified"]:
                    report["release_accuracy_qualified"] = False
                    report["release_status"] = "pilot_only_or_unqualified"
                write_new(args.output, report)
            print(
                json.dumps(
                    {
                        "study_completed": True,
                        "release_accuracy_qualified": report["release_accuracy_qualified"],
                        "case_count": report["case_count"],
                    }
                )
            )
            return 0 if report["release_accuracy_qualified"] else 1
        else:
            dataset = load_dataset(args.dataset)
            root = args.dataset.parent
            if args.command == "seal":
                seal(
                    root,
                    dataset,
                    args.output,
                    args.key,
                    now,
                    developer_principal=args.developer_principal,
                    control_drill=args.control_drill,
                )
            elif args.command == "export-development":
                export_development(root, dataset, args.output, now)
            elif args.command == "inspect":
                result = inspect_study(root, dataset, now)
                write_new(args.output, {k: v for k, v in result.items() if k != "packets"})
                print(
                    json.dumps(
                        {
                            "study_valid": not result["issues"]
                            and not any(result["case_issues"].values()),
                            "case_count": len(dataset.cases),
                        }
                    )
                )
                return 0 if not result["issues"] and not any(result["case_issues"].values()) else 1
            else:
                if dataset.usage != "development_export" or any(
                    c.split == "evaluation" for c in dataset.cases
                ):
                    raise OutlookError("ordinary_run_cannot_open_holdout_manifest")
                split: Split = args.split
                report = run_study(root, dataset, split, now)
                write_new(args.output, report)
                print(
                    json.dumps(
                        {
                            "study_completed": True,
                            "release_accuracy_qualified": False,
                            "case_count": report["case_count"],
                        }
                    )
                )
                return 0 if not report["issues"] else 1
        print(
            json.dumps(
                {"operation_completed": True, "email_mutations": 0, "category_writes": False}
            )
        )
        return 0
    except (OutlookError, ValidationError, OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"error": "study_input_or_authorization_invalid", "email_mutations": 0}))
        return 2
    except Exception:
        print(json.dumps({"error": "study_runtime_failed", "email_mutations": 0}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
