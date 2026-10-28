"""Synthetic, offline evidence builders used only by tests.

No messages are sent. Private test keys exist only in memory and are not exported.
These examples establish contract behavior, not independent real-world labels.
"""

from __future__ import annotations

import base64
import copy
import json
import tempfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agenttrace_feasibility.validation import canonical_bytes, digest

REPLAY_TIME = "2026-10-28T10:10:00Z"


def temporary_workspace() -> tempfile.TemporaryDirectory:
    workspace = Path(__file__).resolve().parents[1] / "work" / "test-runs"
    workspace.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.TemporaryDirectory(dir=workspace)
    if not Path(temporary.name).resolve().is_relative_to(workspace.resolve()):
        raise RuntimeError("test_directory_outside_workspace")
    return temporary


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def signed(record: dict, key: Ed25519PrivateKey) -> dict:
    return {
        "record": copy.deepcopy(record),
        "signature_base64": base64.b64encode(key.sign(canonical_bytes(record))).decode("ascii"),
    }


def make_bundle(
    root: Path,
    executor: str = "ai_agent",
    *,
    operation: str | None = None,
    language: str = "en",
    action: str = "send",
    outcome: str = "completed",
    state: str = "sent",
) -> tuple[Path, Ed25519PrivateKey]:
    root.mkdir(parents=True, exist_ok=True)
    key = Ed25519PrivateKey.generate()
    profile = {
        "schema_version": "1.0",
        "environment": "contract_example",
        "tenant_ref": "tenant-example",
        "mailbox_refs": ["mailbox-example"],
        "issuers": {
            "source-example": {
                "key_id": "test-key",
                "public_key_base64": base64.b64encode(key.public_key().public_bytes_raw()).decode(
                    "ascii"
                ),
                "valid_from": "2026-01-01T00:00:00Z",
                "valid_until": "2027-01-01T00:00:00Z",
                "revoked": False,
                "agent_actor_refs": ["agent-example"],
                "allowed_kinds": ["send_execution", "content_inclusion"],
            }
        },
    }
    write_json(root / "trust-profile.json", profile)
    message = EmailMessage()
    message["From"] = "sender@example.invalid"
    message["To"] = "recipient@example.invalid"
    message["Subject"] = "Synthetic business-message contract example"
    message["Message-ID"] = "<message-example@example.invalid>"
    message["Date"] = "Wed, 28 Oct 2026 10:00:00 +0000"
    message.set_content("The meeting is scheduled for Thursday. Please bring the current agenda.")
    raw = message.as_bytes(policy=policy.SMTP)
    (root / "message.eml").write_bytes(raw)
    observation = {
        "message_ref": "message-example",
        "tenant_ref": "tenant-example",
        "mailbox_ref": "mailbox-example",
        "immutable_id": "opaque-message-example",
        "internet_message_id": str(message["Message-ID"]),
        "state": state,
        "observed_at": "2026-10-28T10:00:04Z",
        "mime_file": "message.eml",
        "body_language": language,
    }
    write_json(root / "observations.json", [observation])
    binding = {
        k: observation[k]
        for k in ["tenant_ref", "mailbox_ref", "immutable_id", "internet_message_id"]
    }
    binding["mime_sha256"] = digest(raw)
    record = {
        "schema_version": "1.0",
        "evidence_id": "send-example",
        "issuer": "source-example",
        "key_id": "test-key",
        "kind": "send_execution",
        "binding": binding,
        "occurred_at": "2026-10-28T10:00:00Z",
        "emitted_at": "2026-10-28T10:00:02Z",
        "expires_at": "2026-10-29T10:00:00Z",
        "facts": {
            "executor_type": executor,
            "actor_ref": "agent-example" if executor == "ai_agent" else "operator-example",
            "action": action,
            "outcome": outcome,
            "execution_id": "execution-example",
        },
    }
    evidence = [signed(record, key)]
    if operation:
        content = copy.deepcopy(record)
        content.update({"evidence_id": "content-example", "kind": "content_inclusion"})
        body = (
            BytesParser(policy=policy.default)
            .parsebytes(raw)
            .get_body(preferencelist=("plain",))
            .get_content()
        )
        content["facts"] = {
            "operation": operation,
            "material_origin": "human_input_with_basic_correction"
            if operation == "basic_correction"
            else "new_generated_output",
            "inclusion_method": "authenticated_transfer_lineage",
            "body_sha256": digest(body.encode("utf-8")),
        }
        evidence.append(signed(content, key))
    write_json(root / "evidence.json", evidence)
    return root / "trust-profile.json", key
