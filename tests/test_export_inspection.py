from __future__ import annotations

import unittest
from email import policy
from email.message import EmailMessage
from pathlib import Path

from agenttrace_feasibility.exports import inspect_synthetic_export
from agenttrace_feasibility.validation import InputError
from tests.support import temporary_workspace, write_json


class ExportInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_workspace()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.mime = self.root / "received-message.eml"
        self.transcript_path = self.root / "source-transcript.json"
        self.message = EmailMessage()
        self.message["Subject"] = "AgentTrace synthetic test: contract-example"
        self.message["Message-ID"] = "<contract-example@example.invalid>"
        self.message["x-ai-generated"] = "mcp-office365"
        self.message.set_content("Synthetic test only.")
        self.transcript = {
            "source": "operator_provided_unverified_transcript",
            "send_operation": "example_send_tool",
            "send_result": "Sent",
            "send_message_id": None,
            "send_request_id": None,
            "send_timestamp": None,
            "lookup_operation": "example_search_tool",
            "lookup": {
                "message_id": "opaque-default-id",
                "internet_message_id": "<contract-example@example.invalid>",
                "sent_at": "2026-10-28T13:34:24Z",
            },
        }

    def inspect(self):
        self.mime.write_bytes(self.message.as_bytes(policy=policy.SMTP))
        write_json(self.transcript_path, self.transcript)
        return inspect_synthetic_export(self.mime, self.transcript_path)

    def test_real_export_path_preserves_unknown_with_matching_later_lookup(self):
        result = self.inspect()
        self.assertTrue(
            result["supporting_observations"]["received_and_sent_lookup_internet_message_ids_match"]
        )
        self.assertIsNone(result["findings"]["agent_send_attribution"]["flagged"])
        self.assertIsNone(result["findings"]["content_assessment"]["flagged"])
        self.assertIsNone(
            result["supporting_observations"]["actual_audit_availability_lag_seconds"]
        )

    def test_declared_header_and_fabricated_id_are_not_verified_provenance(self):
        self.transcript["send_message_id"] = "operator-asserted-id"
        result = self.inspect()
        self.assertTrue(result["supporting_observations"]["header_declaration_present"])
        self.assertEqual(result["findings"]["agent_send_attribution"]["status"], "unknown")

    def test_mismatched_copy_is_recorded_and_not_promoted(self):
        self.transcript["lookup"]["internet_message_id"] = "<different@example.invalid>"
        result = self.inspect()
        self.assertFalse(
            result["supporting_observations"]["received_and_sent_lookup_internet_message_ids_match"]
        )
        self.assertIn(
            "sent_lookup_and_received_message_id_mismatch",
            result["findings"]["agent_send_attribution"]["reason_codes"],
        )

    def test_ordinary_email_export_is_rejected(self):
        self.message.replace_header("Subject", "Ordinary email")
        with self.assertRaisesRegex(InputError, "only_marked_synthetic_exports_allowed"):
            self.inspect()

    def test_full_body_is_not_exported_in_assessment(self):
        self.assertNotIn("Synthetic test only.", str(self.inspect()))
