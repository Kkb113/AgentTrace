"""Behavioral tests for the read-only terminal demo and conservative evidence policy."""

from __future__ import annotations

import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from agenttrace_feasibility.mail_monitor import (
    AuditJob,
    ExchangeEvidence,
    MailSource,
    Monitor,
    display,
    header_rows,
    initial_result,
    main,
    safe,
)
from agenttrace_ingestion.contracts import IngestionError
from tests import test_audit_capture as audit_fixtures

MAILBOX_ID = "00000000-0000-0000-0000-000000000001"
OWNER = "operator@example.invalid"
NOW = datetime(2026, 10, 28, 14, 31, 33, tzinfo=UTC)


def message(ref="copy-one", **extra):
    return {
        "id": ref,
        "subject": "Same ordinary subject",
        "isDraft": False,
        "from": {"emailAddress": {"address": "sender@example.invalid"}},
        "parentFolderId": "inbox",
        "receivedDateTime": NOW.isoformat(),
        "sentDateTime": (NOW - timedelta(seconds=10)).isoformat(),
        "internetMessageId": "<test@example.invalid>",
        "internetMessageHeaders": [],
        **extra,
    }


class MonitorTests(unittest.TestCase):
    def test_office365_mcp_marker_uses_exact_demo_label_and_evidence(self):
        for name, value in [
            ("x-ai-generated", "mcp-office365"),
            ("X-AI-Generated", "  MCP-OFFICE365  "),
        ]:
            with self.subTest(name=name, value=value):
                msg = message(internetMessageHeaders=[{"name": name, "value": value}])
                result = initial_result(msg, OWNER, demo_heuristic=True)
                self.assertEqual(result["classification"], "Sent by AI Agent")
                self.assertEqual(result["qualification"], "experimental_header_heuristic")
                self.assertIn("x-ai-generated: mcp-office365", result["evidence"][0])
                self.assertIn("Office365 MCP", result["submission_hint"])
                self.assertEqual(
                    initial_result(msg, OWNER)["classification"], "Unable to determine"
                )

    def test_office365_marker_requires_exact_header_and_value(self):
        for name, value in [
            ("x-ai-generated", "mcp-office365-other"),
            ("x-ai-generated", "not-mcp-office365"),
            ("x-ai-generated", "true"),
            ("x-other", "mcp-office365"),
            ("Subject", "x-ai-generated: mcp-office365"),
        ]:
            with self.subTest(name=name, value=value):
                result = initial_result(
                    message(internetMessageHeaders=[{"name": name, "value": value}]),
                    OWNER,
                    demo_heuristic=True,
                )
                self.assertEqual(result["classification"], "Sent by Human")

    def test_office365_duplicate_headers_are_preserved_in_continuous_monitor(self):
        mail, events = Mock(), []
        msg = message(
            internetMessageHeaders=[{"name": "X-AI-Generated", "value": "mcp-office365"}] * 2
        )
        mail.incoming.return_value = [msg]
        mail.detail.return_value = msg
        monitor = Monitor(mail, OWNER, events.append, demo_heuristic=True)
        self.assertEqual(monitor.cycle(NOW, NOW), 1)
        self.assertEqual(monitor.cycle(NOW, NOW), 0)
        self.assertEqual(events[0]["classification"], "Sent by AI Agent")
        self.assertEqual(len(events[0]["headers"]), 2)

    def test_requested_demo_label_is_exact_and_qualification_is_separate(self):
        msg = message(
            internetMessageHeaders=[
                {"name": "Received", "value": "by gmailapi.google.com with HTTPREST; date"}
            ]
        )
        result = initial_result(msg, OWNER, demo_heuristic=True)
        self.assertEqual(result["classification"], "Sent by AI Agent")
        self.assertEqual(result["qualification"], "experimental_header_heuristic")
        self.assertIn("non-AI applications", result["evidence"][0])
        self.assertEqual(
            initial_result(message(), OWNER, demo_heuristic=True)["classification"],
            "Sent by Human",
        )

    def test_actual_api_trace_pattern_is_only_a_submission_hint(self):
        for value, hint in [
            ("from source by gmailapi.google.com with HTTPREST; example date", True),
            ("by mail.example.invalid with SMTP; example date", False),
            ("from source by gmailapi.google.com with SMTP; example date", False),
        ]:
            with self.subTest(value=value):
                result = initial_result(
                    message(internetMessageHeaders=[{"name": "Received", "value": value}]), OWNER
                )
                self.assertEqual(
                    "Gmail API submission indicated" in result["submission_hint"], hint
                )
                self.assertEqual(result["classification"], "Unable to determine")

    def test_no_headers_and_ai_headers_never_prove_either_actor(self):
        for rows in [
            [],
            [{"name": "X-AI-Agent", "value": "Claude"}],
            [{"name": "X-Mailer", "value": "Outlook"}],
            [{"name": "Authentication-Results", "value": "receiver; dkim=pass"}],
            [{"name": "Auto-Submitted", "value": "auto-replied"}],
        ]:
            with self.subTest(rows=rows):
                result = initial_result(message(internetMessageHeaders=rows), OWNER)
                self.assertEqual(result["classification"], "Unable to determine")

    def test_header_duplicates_and_inert_terminal_output(self):
        rows = [
            {"name": "Authentication-Results", "value": "first"},
            {"name": "Authentication-Results", "value": "second"},
            {"name": "X-AI-Agent", "value": "Claude\x1b[2J\nFAKE HUMAN\u202e"},
        ]
        result = initial_result(
            message(subject="Injected\r\nSubject", internetMessageHeaders=rows), OWNER
        )
        self.assertEqual(len(result["headers"]), 3)
        stream = io.StringIO()
        with redirect_stdout(stream):
            display(result)
        self.assertNotIn("\x1b", stream.getvalue())
        self.assertNotIn("\u202e", stream.getvalue())
        self.assertIn("\\u001b", stream.getvalue())
        self.assertIn("\\u000a", stream.getvalue())
        self.assertEqual(safe("abc", 2), "ab... [truncated]")

    def test_malformed_and_oversized_headers_rejected(self):
        for rows in [
            None,
            [{}],
            [{"name": "x-ai", "value": 42}],
            [{"name": "x", "value": "x" * 131073}],
            [{"name": "x", "value": "x"}] * 501,
        ]:
            with self.subTest(kind=type(rows).__name__):
                with self.assertRaises(IngestionError):
                    header_rows(message(internetMessageHeaders=rows))

    def test_new_mail_move_duplicate_and_later_arrival(self):
        mail, events = Mock(), []
        first, later = message(), message("copy-two")
        mail.incoming.side_effect = [[first], [first, later], [later, first]]
        mail.detail.side_effect = lambda item: item
        monitor = Monitor(mail, OWNER, events.append)
        self.assertEqual([monitor.cycle(NOW, NOW) for _ in range(3)], [1, 1, 0])
        self.assertEqual(len(events), 2)

    def test_temporary_failure_is_not_marked_seen_and_retries(self):
        mail, events = Mock(), []
        mail.incoming.return_value = [message()]
        mail.detail.side_effect = [IngestionError("temporary", retryable=True), message()]
        monitor = Monitor(mail, OWNER, events.append)
        with self.assertRaises(IngestionError):
            monitor.cycle(NOW, NOW)
        self.assertFalse(monitor.seen)
        self.assertEqual(monitor.cycle(NOW, NOW), 1)

    def test_deleted_before_read_is_explicit_and_not_seen(self):
        mail, events = Mock(), []
        mail.incoming.return_value = [message()]
        mail.detail.side_effect = IngestionError("source_item_not_found")
        monitor = Monitor(mail, OWNER, events.append)
        self.assertEqual(monitor.cycle(NOW, NOW), 0)
        self.assertEqual(events[0]["event"], "coverage_gap")
        self.assertFalse(monitor.seen)

    def test_wrong_detail_identity_is_rejected(self):
        mail = Mock()
        mail.incoming.return_value = [message()]
        mail.detail.return_value = message("wrong-id")
        with self.assertRaisesRegex(IngestionError, "identity_mismatch"):
            Monitor(mail, OWNER, Mock()).cycle(NOW, NOW)

    def test_continuous_cli_stops_cleanly_on_ctrl_c(self):
        mail = Mock()
        mail.incoming.return_value = []
        stream = io.StringIO()
        with (
            patch(
                "agenttrace_feasibility.mail_monitor.build_sources",
                return_value=({"mailbox": OWNER}, mail, None),
            ),
            patch("agenttrace_feasibility.mail_monitor.time.sleep", side_effect=KeyboardInterrupt),
            redirect_stdout(stream),
        ):
            self.assertEqual(main(["--json"]), 0)
        events = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertEqual(events[-1]["event"], "stopped")
        mail.prepare.assert_called_once()

    def test_throttled_monitor_retries_then_stops_without_classification(self):
        mail = Mock()
        mail.incoming.side_effect = [
            IngestionError("source_throttled", retryable=True, retry_after=45),
            [],
        ]
        stream = io.StringIO()
        with (
            patch(
                "agenttrace_feasibility.mail_monitor.build_sources",
                return_value=({"mailbox": OWNER}, mail, None),
            ),
            patch(
                "agenttrace_feasibility.mail_monitor.time.sleep",
                side_effect=[None, KeyboardInterrupt],
            ) as sleep,
            redirect_stdout(stream),
        ):
            self.assertEqual(main(["--json"]), 0)
        self.assertEqual(sleep.call_args_list[0].args[0], 45)
        self.assertEqual(mail.incoming.call_count, 2)
        events = [json.loads(line) for line in stream.getvalue().splitlines()]
        self.assertIn("retry", [event["event"] for event in events])
        self.assertNotIn("message", [event["event"] for event in events])

    def test_cli_error_does_not_expose_source_payload(self):
        stream = io.StringIO()
        with (
            patch(
                "agenttrace_feasibility.mail_monitor.build_sources",
                side_effect=OSError("PRIVATE RAW RESPONSE"),
            ),
            redirect_stdout(stream),
        ):
            self.assertEqual(main(["--once", "--json"]), 1)
        self.assertNotIn("PRIVATE RAW RESPONSE", stream.getvalue())


class MailScopeTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock()
        self.source = MailSource(self.transport, MAILBOX_ID)

    def test_forbidden_urls_fields_or_duplicate_parameters_never_reach_transport(self):
        bad = [
            "https://other.invalid/v1.0/users/" + MAILBOX_ID + "/messages?$select=id",
            self.source.base.replace(MAILBOX_ID, "other-mailbox") + "/messages?$select=id",
            self.source.base + "/messages/one/$value?$select=id",
            self.source.base + "/messages/one/sendMail?$select=id",
            self.source.base + "/messages?$select=body",
            self.source.base + "/messages?$select=id&$expand=attachments",
            self.source.base + "/messages?$select=id&$select=body",
        ]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(IngestionError):
                self.source.get(url)
        self.transport.request.assert_not_called()

    def test_receiving_folders_and_pagination(self):
        self.source.excluded = {"sent", "drafts", "outbox"}
        next_url = (
            self.source.base
            + "/messages?"
            + urlencode({"$select": "id,isDraft,parentFolderId", "$skip": "100"})
        )
        self.transport.request.side_effect = [
            {
                "value": [message(), message("sent-one", parentFolderId="sent")],
                "@odata.nextLink": next_url,
            },
            {
                "value": [
                    message("rules-folder", parentFolderId="rule"),
                    message("draft", isDraft=True),
                ]
            },
        ]
        self.assertEqual(
            [m["id"] for m in self.source.incoming(NOW, NOW)], ["copy-one", "rules-folder"]
        )
        for call in self.transport.request.call_args_list:
            self.assertEqual(call.args[0], "GET")
            self.assertNotIn("body", call.args[1])

    def test_cross_scope_or_cyclic_pagination_fails_without_partial_success(self):
        for link in [self.source.base + "/messages?$select=id", "https://other.invalid/collect"]:
            self.transport.request.reset_mock()
            self.transport.request.return_value = {"value": [message()], "@odata.nextLink": link}
            with self.assertRaises(IngestionError):
                self.source.pages(self.source.base + "/messages?$select=id")


class DemoAuditTests(unittest.TestCase):
    def setUp(self):
        fixture = audit_fixtures.AuditCaptureTests()
        fixture.setUp()
        self.fixture = fixture
        self.mail, self.audit = Mock(), Mock()
        self.mail.sent_folder = "sent-folder-example"
        self.mail.sent_copies.return_value = [fixture.message]
        self.evidence = ExchangeEvidence(
            self.mail, self.audit, {"tenant": fixture.tenant, "mailbox": fixture.mailbox}
        )

    def job(self):
        received = {
            **self.fixture.message,
            "id": "received-copy",
            "parentFolderId": "inbox",
            "internetMessageHeaders": [],
        }
        return AuditJob(
            received, initial_result(received, self.fixture.mailbox), NOW, query_id="query"
        )

    def test_gmail_sender_is_not_eligible_for_microsoft_send_evidence(self):
        self.assertFalse(self.evidence.eligible(message()))
        self.audit.request.assert_not_called()

    def test_authenticated_enrolled_rule_upgrades_and_rejects_forged_or_wrong_records(self):
        cases = [
            ({}, True),
            ({"ClientAppId": "generic-app"}, False),
            ({"Operation": "MailItemsAccessed"}, False),
            ({"ResultStatus": "Failed"}, False),
            ({"TokenTenantId": "other"}, False),
        ]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                event = copy.deepcopy(self.fixture.event)
                event["auditData"].update(changes)
                self.audit.request.side_effect = [{"status": "succeeded"}, {"value": [event]}]
                result = self.evidence.step(self.job(), NOW)
                self.assertEqual(result is not None, expected)
                if result:
                    self.assertEqual(result["classification"], "Sent by AI Agent")

    def test_received_copy_inconsistent_with_send_cannot_upgrade(self):
        job = self.job()
        job.message["sentDateTime"] = NOW.isoformat()
        self.audit.request.side_effect = [{"status": "succeeded"}, {"value": [self.fixture.event]}]
        self.assertIsNone(self.evidence.step(job, NOW))

    def test_pending_and_empty_completed_query_do_not_infer_human(self):
        self.audit.request.side_effect = [{"status": "running"}]
        self.assertIsNone(self.evidence.step(self.job(), NOW))
        self.audit.request.side_effect = [{"status": "succeeded"}, {"value": []}]
        job = self.job()
        self.assertIsNone(self.evidence.step(job, NOW))
        self.assertIsNone(job.query_id)

    def test_analytical_query_creation_is_send_filtered_not_email_mutation(self):
        job = self.job()
        job.query_id = None
        self.audit.request.side_effect = [{"id": "new-query"}]
        self.assertIsNone(self.evidence.step(job, NOW))
        args, kwargs = self.audit.request.call_args
        self.assertEqual(args, ("POST", self.evidence.root))
        self.assertEqual(kwargs["body"]["operationFilters"], ["Send"])
        self.assertNotIn("/sendMail", args[1])

    def test_expired_wait_is_explicit_unknown_not_human(self):
        result = self.evidence.step(self.job(), NOW + timedelta(hours=3))
        self.assertEqual(result["classification"], "Unable to determine")
        self.audit.request.assert_not_called()
