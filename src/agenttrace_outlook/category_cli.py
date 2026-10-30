"""Category definitions, ownership and no-op permission checks; classification apply is absent."""

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agenttrace_feasibility.validation import canonical_bytes, load_json

from .category_catalog import certificate_catalog
from .category_contracts import CategoryOwnership, CategorySettings
from .category_ownership import OwnershipStore, provision, verify_ownership
from .category_preview import category_preview
from .category_probe import CategoryPermissionProbe
from .config import read_config
from .contracts import Decision, Observation
from .errors import OutlookError
from .rule_store import RuleStore
from .state import StateStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["provision", "verify", "preview", "probe"])
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path)
    parser.add_argument(
        "--message-id", help="Exact designated synthetic item reference, never a subject."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    store = None
    registry: CategoryOwnership | None = None
    report: dict[str, Any]
    try:
        settings = CategorySettings.model_validate_json(canonical_bytes(load_json(args.settings)))
        if args.output.exists():
            raise OutlookError("new_private_category_report_required")
        args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        store = OwnershipStore(settings)
        if args.operation == "provision":
            registry = provision(store, certificate_catalog(settings, "setup"), datetime.now(UTC))
            report = {
                "owned_categories": len(registry.categories),
                "master_categories_ready": True,
                "automatic_application_enabled": False,
            }
        else:
            registry = store.load()
            if registry is None:
                raise OutlookError("category_ownership_required")
            catalog = certificate_catalog(settings, "writer")
            inventory = catalog.inventory()
            verify_ownership(registry, inventory)
            report = {
                "owned_categories": 3,
                "ownership_verified": True,
                "automatic_application_enabled": False,
            }
            if args.operation == "probe":
                if args.message_id is None:
                    raise OutlookError("synthetic_probe_reference_required")
                probe = CategoryPermissionProbe(settings, catalog.transport)
                before = probe.metadata(args.message_id)
                probe.unchanged_patch(before, mailbox_id=settings.scope.mailbox_id)
                after = probe.metadata(args.message_id)
                if before["categories"] != after["categories"]:
                    raise OutlookError("category_probe_changed_membership")
                report.update(
                    allowed_noop_patch_verified=True,
                    category_membership_unchanged=True,
                    **probe.denied_outside_scope(after),
                )
            if args.operation == "preview":
                if args.runtime_config is None:
                    raise OutlookError("runtime_config_required_for_preview")
                runtime = read_config(args.runtime_config)
                if runtime.scope != settings.scope:
                    raise OutlookError("category_runtime_scope_mismatch")
                rows = []
                with StateStore(runtime) as state:
                    rules = RuleStore(state)
                    with state.transaction(lease=state.lease) as db:
                        current = db.execute(
                            "SELECT d.payload,o.payload,o.id FROM messages m JOIN observations o ON o.id=m.current_observation JOIN decisions d ON d.message_id=m.message_id AND d.version=m.decision_version"
                        ).fetchall()
                    probe = CategoryPermissionProbe(settings, catalog.transport)
                    for row in current:
                        decision, observation = (
                            Decision.model_validate_json(row[0]),
                            Observation.model_validate_json(row[1]),
                        )
                        reference = hashlib.sha256(decision.message_id.encode()).hexdigest()
                        try:
                            item = category_preview(
                                registry,
                                inventory,
                                decision,
                                observation,
                                rules.snapshot(observation),
                                rules.source(row[2]),
                                probe.metadata(decision.message_id),
                                datetime.now(UTC),
                            )
                            rows.append({"message_ref_sha256": reference, "preview": item})
                        except OutlookError as error:
                            rows.append({"message_ref_sha256": reference, "skipped": error.code})
                report.update(preview_rows=rows, preview_only=True, mail_mutations=0)
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2)
        args.output.chmod(0o600)
        print(json.dumps({k: v for k, v in report.items() if k != "preview_rows"}, sort_keys=True))
        return 0
    except OutlookError as error:
        print(json.dumps({"error": error.code, "automatic_application_enabled": False}))
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        print(
            json.dumps(
                {
                    "error": "category_setup_or_verification_failed",
                    "automatic_application_enabled": False,
                }
            )
        )
        return 2
    except Exception:
        print(
            json.dumps(
                {"error": "category_operation_unavailable", "automatic_application_enabled": False}
            )
        )
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
