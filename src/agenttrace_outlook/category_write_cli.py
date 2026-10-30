"""Explicit synthetic-pilot writer commands; continuous automatic application stays disabled."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from agenttrace_feasibility.validation import canonical_bytes, load_json

from .category_catalog import certificate_catalog
from .category_contracts import CategorySettings
from .category_endpoint import CategoryEndpoint
from .category_ownership import OwnershipStore, verify_ownership
from .category_write_contracts import CategoryEndpointQualification
from .category_writer import CategoryWriter
from .config import read_config
from .errors import OutlookError
from .state import StateStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=["qualify", "plan", "apply", "retry", "verify", "rollback", "status"]
    )
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path)
    parser.add_argument("--qualification", type=Path)
    parser.add_argument("--message-id")
    parser.add_argument("--intent-id", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    ownership = None
    qualification: CategoryEndpointQualification | None
    try:
        if args.output.exists():
            raise OutlookError("new_private_category_report_required")
        settings = CategorySettings.model_validate_json(canonical_bytes(load_json(args.settings)))
        ownership = OwnershipStore(settings)
        registry = ownership.load()
        if registry is None:
            raise OutlookError("category_ownership_required")
        catalog = certificate_catalog(settings, "writer")
        if args.operation == "qualify":
            if args.message_id is None:
                raise OutlookError("synthetic_probe_reference_required")
            verify_ownership(registry, catalog.inventory())
            qualification = CategoryEndpoint(settings, catalog.transport).qualify(
                args.message_id, datetime.now(UTC)
            )
            report = qualification.model_dump(mode="json")
            summary = {"endpoint_qualified": True, "classification_labels_applied": 0}
        else:
            if args.runtime_config is None:
                raise OutlookError("category_runtime_configuration_required")
            runtime = read_config(args.runtime_config)
            qualification = (
                CategoryEndpointQualification.model_validate_json(
                    canonical_bytes(load_json(args.qualification))
                )
                if args.qualification
                else None
            )
            with StateStore(runtime) as state:
                writer = CategoryWriter(state, catalog, registry, qualification)
                if args.operation == "plan":
                    report = {
                        "intent_ids": writer.plan(args.message_id),
                        "mailbox_mutation_performed": False,
                    }
                elif args.operation == "status":
                    if args.intent_id is None:
                        raise OutlookError("category_intent_reference_required")
                    report = writer.summary(args.intent_id)
                else:
                    if args.intent_id is None or args.intent_id < 1:
                        raise OutlookError("category_intent_reference_required")
                    if args.operation == "rollback":
                        writer.request_rollback(args.intent_id)
                    if args.operation == "retry":
                        writer.request_retry(args.intent_id)
                    report = (
                        writer.verify(args.intent_id)
                        if args.operation == "verify"
                        else writer.step(args.intent_id)
                    )
            summary = report
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
        args.output.chmod(0o600)
        print(json.dumps({**summary, "automatic_application_enabled": False}, sort_keys=True))
        return (
            1
            if report.get("status")
            in {
                "blocked",
                "superseded",
                "rollback_blocked",
                "uncertain",
                "prepared",
                "pending",
                "rollback_pending",
            }
            else 0
        )
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "error": "category_writer_interrupted_inspect_intent",
                    "automatic_application_enabled": False,
                }
            )
        )
        return 130
    except OutlookError as error:
        print(json.dumps({"error": error.code, "automatic_application_enabled": False}))
        return 2
    except Exception:
        print(
            json.dumps(
                {"error": "category_writer_unavailable", "automatic_application_enabled": False}
            )
        )
        return 2
    finally:
        if ownership:
            ownership.close()


if __name__ == "__main__":
    raise SystemExit(main())
