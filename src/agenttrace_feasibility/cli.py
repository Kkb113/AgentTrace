"""Command-line entry points for evidence replay and read-only capability checks."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .attribution import assess_bundle
from .capabilities import collect_capabilities
from .exports import inspect_synthetic_export
from .reader import collect_reader_evidence
from .validation import InputError, timestamp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AgentTrace read-only feasibility checks")
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser(
        "assess-evidence", help="Read an evidence bundle; never send or alter mail"
    )
    replay.add_argument("--bundle", type=Path, required=True)
    replay.add_argument("--trust-profile", type=Path, required=True)
    replay.add_argument("--as-of", help="Explicit replay time; default is current UTC")
    replay.add_argument("--output", type=Path, required=True)
    collect = commands.add_parser(
        "inspect-environment", help="Collect existing Azure/M365 capabilities read-only"
    )
    collect.add_argument("--subscription", required=True)
    collect.add_argument("--resource-group", choices=["kb-agentdemo"], default="kb-agentdemo")
    collect.add_argument("--private-output", type=Path, required=True)
    exported = commands.add_parser(
        "inspect-export", help="Compare a marked synthetic EML with an unverified source transcript"
    )
    exported.add_argument("--mime-file", type=Path, required=True)
    exported.add_argument("--source-transcript", type=Path, required=True)
    exported.add_argument("--private-output", type=Path, required=True)
    reader = commands.add_parser(
        "inspect-reader",
        help="Read marked test messages and Exchange audit through an approved reader",
    )
    reader.add_argument("--settings", type=Path, required=True)
    reader.add_argument("--private-output", type=Path, required=True)
    reader.add_argument("--reuse-searches-from", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "assess-evidence":
            as_of = timestamp(arguments.as_of) if arguments.as_of else datetime.now(UTC)
            result = assess_bundle(arguments.bundle, arguments.trust_profile, as_of)
            output = arguments.output.resolve()
            root = arguments.bundle.resolve()
            if output.is_relative_to(root) or output == arguments.trust_profile.resolve():
                raise InputError("output_cannot_overwrite_evidence_inputs")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "status": "completed",
                        "messages_assessed": len(result["decisions"]),
                        "environment": result["environment"],
                    }
                )
            )
        elif arguments.command == "inspect-environment":
            result = collect_capabilities(
                arguments.subscription, arguments.resource_group, arguments.private_output
            )
            print(
                json.dumps(
                    {
                        "status": "completed",
                        "new_resources_created": 0,
                        "synthetic_message_read": result["checks"]["synthetic_message_read"][
                            "status"
                        ],
                    }
                )
            )
        elif arguments.command == "inspect-reader":
            result = collect_reader_evidence(
                arguments.settings, arguments.private_output, arguments.reuse_searches_from
            )
            print(
                json.dumps({"status": "completed", "messages_assessed": len(result["assessments"])})
            )
        else:
            if not arguments.private_output.resolve().is_relative_to(
                Path.cwd().resolve() / "work" / "private"
            ):
                raise InputError("private_output_directory_required")
            if arguments.private_output.resolve() in {
                arguments.mime_file.resolve(),
                arguments.source_transcript.resolve(),
            }:
                raise InputError("output_cannot_overwrite_evidence_inputs")
            result = inspect_synthetic_export(arguments.mime_file, arguments.source_transcript)
            arguments.private_output.parent.mkdir(parents=True, exist_ok=True)
            arguments.private_output.write_text(
                json.dumps(result, indent=2) + "\n", encoding="utf-8"
            )
            print(
                json.dumps(
                    {
                        "status": "completed",
                        "agent_finding": result["findings"]["agent_send_attribution"]["status"],
                        "message_copy_ids_match": result["supporting_observations"][
                            "received_and_sent_lookup_internet_message_ids_match"
                        ],
                    }
                )
            )
        return 0
    except (InputError, OSError) as exc:
        # Avoid echoing raw paths, email content, API responses, or credentials.
        code = str(exc) if isinstance(exc, InputError) else "file_operation_failed"
        print(json.dumps({"status": "failed", "reason": code}), file=sys.stderr)
        return 2
