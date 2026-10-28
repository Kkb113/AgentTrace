from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from agenttrace_feasibility.audit import CLAUDE_CONNECTOR_APP_ID, assess_audit_capture
from agenttrace_feasibility.reader import (
    GraphReader,
    NoRedirect,
    validate_reused_query,
    validate_settings,
)
from agenttrace_feasibility.validation import InputError, timestamp
from tests.support import temporary_workspace, write_json


class AuditCaptureTests(unittest.TestCase):
    def setUp(self):
        self.subject = "AgentTrace synthetic test: contract-example"
        self.mailbox = "operator@example.invalid"
        self.tenant = "tenant-example"
        self.message = {
            "id": "graph-immutable-example",
            "internetMessageId": "<example@example.invalid>",
            "subject": self.subject,
            "parentFolderId": "sent-folder-example",
            "isDraft": False,
            "sentDateTime": "2026-10-28T13:34:24Z",
            "from": {"emailAddress": {"address": self.mailbox}},
        }
        self.event = {
            "id": "audit-record-example",
            "createdDateTime": "2026-10-28T13:34:24Z",
            "organizationId": self.tenant,
            "userPrincipalName": self.mailbox,
            "operation": "Send",
            "auditData": {
                "Id": "audit-record-example",
                "OrganizationId": self.tenant,
                "TokenTenantId": self.tenant,
                "MailboxOwnerUPN": self.mailbox,
                "MailboxGuid": "mailbox-guid-example",
                "Operation": "Send",
                "ResultStatus": "Succeeded",
                "ClientAppId": CLAUDE_CONNECTOR_APP_ID,
                "AppAccessContext": {"ClientAppId": CLAUDE_CONNECTOR_APP_ID},
                "ClientRequestId": "request-example",
                "Item": {
                    "InternetMessageId": self.message["internetMessageId"],
                    "Subject": self.subject,
                },
            },
        }

    def assess(self, messages=None, records=None, **kwargs):
        return assess_audit_capture(
            [self.message] if messages is None else messages,
            [self.event] if records is None else records,
            tenant_id=self.tenant,
            mailbox=self.mailbox,
            subject=self.subject,
            sent_folder_id="sent-folder-example",
            first_seen=timestamp("2026-10-28T14:31:33Z"),
            authenticated_live_capture=kwargs.get("authenticated", True),
            complete=kwargs.get("complete", True),
        )

    def test_completed_known_connector_send_and_content_are_independent(self):
        result = self.assess()
        self.assertTrue(result["findings"]["agent_send_attribution"]["flagged"])
        self.assertIsNone(result["findings"]["content_assessment"]["flagged"])
        self.assertEqual(
            result["supporting_observations"]["first_successful_collection_age_seconds"], 3429
        )
        self.assertFalse(
            result["supporting_observations"]["audit_to_graph_immutable_id_equivalence_established"]
        )

    def test_untrusted_import_and_incomplete_pages_never_verify(self):
        for kwargs in [{"authenticated": False}, {"complete": False}]:
            with self.subTest(kwargs=kwargs):
                self.assertIsNone(
                    self.assess(**kwargs)["findings"]["agent_send_attribution"]["flagged"]
                )

    def test_read_draft_failed_accepted_and_generic_application_are_not_agent(self):
        for field, value in [
            ("Operation", "MailItemsAccessed"),
            ("Operation", "Update"),
            ("ResultStatus", "Failed"),
            ("ResultStatus", "Accepted"),
            ("ClientAppId", "00000003-0000-0000-c000-000000000000"),
            ("ClientAppId", "outlook-or-conventional-application"),
            ("ClientRequestId", None),
        ]:
            with self.subTest(field=field, value=value):
                event = copy.deepcopy(self.event)
                event["auditData"][field] = value
                self.assertIsNone(
                    self.assess(records=[event])["findings"]["agent_send_attribution"]["flagged"]
                )

    def test_wrong_tenant_mailbox_or_message_does_not_bind(self):
        for key in ["OrganizationId", "TokenTenantId", "MailboxOwnerUPN"]:
            with self.subTest(key=key):
                event = copy.deepcopy(self.event)
                event["auditData"][key] = "wrong-scope"
                self.assertIsNone(
                    self.assess(records=[event])["findings"]["agent_send_attribution"]["flagged"]
                )
        self.event["auditData"]["Item"]["InternetMessageId"] = "<other@example.invalid>"
        self.assertIsNone(self.assess()["findings"]["agent_send_attribution"]["flagged"])

    def test_same_message_id_in_another_sent_copy_is_ambiguous(self):
        other = copy.deepcopy(self.message)
        other["id"] = "another-item"
        self.assertIsNone(
            self.assess(messages=[self.message, other])["findings"]["agent_send_attribution"][
                "flagged"
            ]
        )

    def test_received_copy_alone_or_draft_cannot_establish_send(self):
        for field, value in [("parentFolderId", "inbox"), ("isDraft", True)]:
            with self.subTest(field=field):
                item = copy.deepcopy(self.message)
                item[field] = value
                self.assertIsNone(
                    self.assess(messages=[item])["findings"]["agent_send_attribution"]["flagged"]
                )

    def test_duplicate_audit_is_idempotent_and_conflict_is_unknown(self):
        self.assertEqual(self.assess(records=[self.event, self.event]), self.assess())
        other = copy.deepcopy(self.event)
        other["auditData"]["ClientAppId"] = "another-application"
        self.assertIsNone(
            self.assess(records=[self.event, other])["findings"]["agent_send_attribution"][
                "flagged"
            ]
        )

    def test_empty_audit_is_unknown_not_human(self):
        self.assertIsNone(self.assess(records=[])["findings"]["agent_send_attribution"]["flagged"])

    def test_event_and_application_context_inconsistency_is_unknown(self):
        self.event["auditData"]["AppAccessContext"]["ClientAppId"] = "different-application"
        self.assertIsNone(self.assess()["findings"]["agent_send_attribution"]["flagged"])

    def test_legacy_exchange_sender_requires_same_item_mime_fallback(self):
        self.message["from"]["emailAddress"]["address"] = "/O=EXAMPLE/OU=GROUP/CN=RECIPIENT"
        self.assertIsNone(self.assess()["findings"]["agent_send_attribution"]["flagged"])
        self.message["captured_mime_from_address"] = self.mailbox
        self.assertTrue(self.assess()["findings"]["agent_send_attribution"]["flagged"])
        self.message["from"]["emailAddress"]["address"] = "other@example.invalid"
        self.assertIsNone(self.assess()["findings"]["agent_send_attribution"]["flagged"])


class ReaderBoundaryTests(unittest.TestCase):
    def test_reused_search_must_match_exact_actor_message_window_and_operations(self):
        expected = {
            "keywordFilter": "<example@example.invalid>",
            "userPrincipalNameFilters": ["operator@example.invalid"],
            "operationFilters": ["Send", "SendAs", "SendOnBehalf"],
            "recordTypeFilters": ["exchangeItem"],
            "filterStartDateTime": "2026-10-28T13:32:24Z",
            "filterEndDateTime": "2026-10-28T13:36:24Z",
        }
        validate_reused_query(expected, expected)
        for field, value in [
            ("keywordFilter", "different"),
            ("userPrincipalNameFilters", ["different@example.invalid"]),
            ("operationFilters", []),
            ("filterStartDateTime", "2026-10-27T13:32:24Z"),
        ]:
            query = dict(expected)
            query[field] = value
            with self.subTest(field=field), self.assertRaises(InputError):
                validate_reused_query(query, expected)

    def test_send_write_and_external_urls_fail_before_network(self):
        reader = GraphReader("memory-only-test-value")
        with patch.object(reader._opener, "open") as network:
            for path, body in [
                ("me/sendMail", {}),
                ("me/messages", {}),
                ("https://untrusted.invalid/collect", None),
                ("me/messages/../sendMail", {}),
                ("applications", {}),
            ]:
                with self.subTest(path=path):
                    with self.assertRaisesRegex(InputError, "reader_operation_not_allowlisted"):
                        reader.request(path, body)
            network.assert_not_called()

    def test_graph_redirect_cannot_forward_authorization(self):
        with self.assertRaisesRegex(InputError, "graph_redirect_rejected"):
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://untrusted.invalid")

    def test_response_size_is_bounded(self):
        reader = GraphReader("memory-only-test-value")
        response = Mock()
        response.read.return_value = b"x" * (2 * 1024 * 1024 + 1)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        with patch.object(reader._opener, "open", return_value=response):
            with self.assertRaisesRegex(InputError, "graph_response_too_large"):
                reader.request("me/mailFolders/sentitems?$select=id")

    def test_config_rejects_ordinary_mail_and_arbitrary_authority(self):
        with temporary_workspace() as temporary:
            path = Path(temporary) / "settings.json"
            base = {
                "tenant_id": "00000000-0000-0000-0000-000000000001",
                "client_id": "00000000-0000-0000-0000-000000000002",
                "operator_id": "00000000-0000-0000-0000-000000000003",
                "mailbox": "operator@example.invalid",
                "subjects": ["Ordinary email"],
            }
            write_json(path, base)
            with self.assertRaises(InputError):
                validate_settings(path)
            base["tenant_id"] = "https://untrusted.invalid"
            base["subjects"] = ["AgentTrace synthetic test: example"]
            write_json(path, base)
            with self.assertRaises(InputError):
                validate_settings(path)
