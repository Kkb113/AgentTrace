from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from agenttrace_feasibility.attribution import assess_bundle
from agenttrace_feasibility.validation import InputError, load_json, timestamp
from tests.support import REPLAY_TIME, make_bundle, signed, temporary_workspace, write_json


class EvidenceAttributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_workspace()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = Path(self.temporary.name) / "bundle"
        self.profile, self.key = make_bundle(self.bundle)

    def assess(self):
        return assess_bundle(self.bundle, self.profile, timestamp(REPLAY_TIME))["decisions"][0][
            "findings"
        ]

    def alter_record(self, update, index=0):
        evidence = load_json(self.bundle / "evidence.json")
        update(evidence[index]["record"])
        evidence[index] = signed(evidence[index]["record"], self.key)
        write_json(self.bundle / "evidence.json", evidence)

    def test_agent_send_has_no_automatic_content_positive(self):
        result = self.assess()
        self.assertEqual(set(result), {"agent_send_attribution", "content_assessment"})
        self.assertIs(result["agent_send_attribution"]["flagged"], True)
        self.assertIsNone(result["content_assessment"]["flagged"])

    def test_human_sent_generated_content_is_independent(self):
        make_bundle(self.bundle, "human", operation="draft_generation")
        result = self.assess()
        self.assertIs(result["agent_send_attribution"]["flagged"], False)
        self.assertIs(result["content_assessment"]["flagged"], True)

    def test_untracked_manual_paste_is_not_agent_evidence(self):
        make_bundle(self.bundle, "human")
        result = self.assess()
        self.assertIs(result["agent_send_attribution"]["flagged"], False)
        self.assertIsNone(result["content_assessment"]["flagged"])

    def test_non_ai_application_is_not_agent(self):
        make_bundle(self.bundle, "non_ai_application")
        self.assertIs(self.assess()["agent_send_attribution"]["flagged"], False)

    def test_draft_read_failed_and_accepted_are_not_completed_sends(self):
        for action, outcome in [
            ("draft", "completed"),
            ("read", "completed"),
            ("send", "failed"),
            ("send", "accepted"),
            ("send", "cancelled"),
        ]:
            with self.subTest(action=action, outcome=outcome):
                make_bundle(self.bundle, action=action, outcome=outcome)
                self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_draft_observation_cannot_confirm_send(self):
        make_bundle(self.bundle, state="draft")
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_basic_correction_does_not_trigger_content_flag(self):
        make_bundle(self.bundle, "human", operation="basic_correction")
        self.assertIs(self.assess()["content_assessment"]["flagged"], False)

    def test_rewrites_and_english_translations_have_independent_content_results(self):
        for operation in ["substantial_rewrite", "translation_into_english"]:
            with self.subTest(operation=operation):
                make_bundle(self.bundle, "human", operation=operation)
                result = self.assess()
                self.assertFalse(result["agent_send_attribution"]["flagged"])
                self.assertTrue(result["content_assessment"]["flagged"])

    def test_unsupported_language_does_not_suppress_agent_result(self):
        make_bundle(self.bundle, operation="draft_generation", language="unsupported")
        result = self.assess()
        self.assertTrue(result["agent_send_attribution"]["flagged"])
        self.assertIsNone(result["content_assessment"]["flagged"])

    def test_human_echo_and_common_template_cannot_verify_generated_origin(self):
        for origin in ["echoed_human_input", "common_template"]:
            with self.subTest(origin=origin):
                self.profile, self.key = make_bundle(
                    self.bundle, "human", operation="draft_generation"
                )
                self.alter_record(lambda r: r["facts"].update(material_origin=origin), index=1)
                self.assertIsNone(self.assess()["content_assessment"]["flagged"])

    def test_similarity_without_inclusion_lineage_is_insufficient(self):
        self.profile, self.key = make_bundle(self.bundle, "human", operation="draft_generation")
        self.alter_record(
            lambda r: r["facts"].update(inclusion_method="output_similarity_only"), index=1
        )
        self.assertIsNone(self.assess()["content_assessment"]["flagged"])

    def test_unsigned_header_is_not_evidence(self):
        path = self.bundle / "message.eml"
        path.write_bytes(
            b"X-AI-Agent: true\r\nAuto-Submitted: auto-generated\r\n" + path.read_bytes()
        )
        write_json(self.bundle / "evidence.json", [])
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_forged_signature_is_rejected(self):
        evidence = load_json(self.bundle / "evidence.json")
        evidence[0]["record"]["facts"]["execution_id"] = "tampered"
        write_json(self.bundle / "evidence.json", evidence)
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_key_revocation_is_effective(self):
        profile = load_json(self.profile)
        profile["issuers"]["source-example"]["revoked"] = True
        write_json(self.profile, profile)
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_wrong_tenant_mailbox_id_and_content_digest_are_rejected(self):
        for field, value in [
            ("tenant_ref", "other-tenant"),
            ("mailbox_ref", "other-mailbox"),
            ("internet_message_id", "<other@example.invalid>"),
            ("mime_sha256", "0" * 64),
        ]:
            with self.subTest(field=field):
                self.profile, self.key = make_bundle(self.bundle)
                self.alter_record(lambda r: r["binding"].update({field: value}))
                self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_changed_mime_is_not_bound_to_old_receipt(self):
        message = self.bundle / "message.eml"
        message.write_bytes(message.read_bytes().replace(b"Thursday", b"Saturday"))
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_expired_and_future_evidence_are_rejected(self):
        for field, value in [
            ("expires_at", "2026-10-28T10:05:00Z"),
            ("occurred_at", "2026-10-30T10:00:00Z"),
        ]:
            with self.subTest(field=field):
                self.profile, self.key = make_bundle(self.bundle)
                self.alter_record(lambda r: r.update({field: value}))
                self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_unknown_actor_is_not_registered_by_its_own_assertion(self):
        self.alter_record(lambda r: r["facts"].update(actor_ref="unregistered-agent"))
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_invalid_content_record_cannot_change_valid_agent_finding(self):
        self.profile, self.key = make_bundle(self.bundle, operation="draft_generation")
        self.alter_record(lambda r: r["facts"].update(body_sha256="0" * 64), index=1)
        findings = self.assess()
        self.assertTrue(findings["agent_send_attribution"]["flagged"])
        self.assertIsNone(findings["content_assessment"]["flagged"])

    def test_invalid_send_record_cannot_erase_independent_content_provenance(self):
        self.profile, self.key = make_bundle(self.bundle, operation="draft_generation")
        self.alter_record(lambda r: r["facts"].update(actor_ref="unregistered-agent"))
        findings = self.assess()
        self.assertIsNone(findings["agent_send_attribution"]["flagged"])
        self.assertTrue(findings["content_assessment"]["flagged"])

    def test_duplicate_receipt_is_idempotent(self):
        before = self.assess()
        evidence = load_json(self.bundle / "evidence.json")
        write_json(self.bundle / "evidence.json", evidence + evidence)
        self.assertEqual(before, self.assess())

    def test_conflicting_executors_are_unknown(self):
        evidence = load_json(self.bundle / "evidence.json")
        other = copy.deepcopy(evidence[0]["record"])
        other["evidence_id"] = "other-send"
        other["facts"].update(executor_type="human", actor_ref="human-example")
        evidence.append(signed(other, self.key))
        write_json(self.bundle / "evidence.json", evidence)
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_same_id_with_different_signed_payload_is_rejected(self):
        evidence = load_json(self.bundle / "evidence.json")
        other = copy.deepcopy(evidence[0]["record"])
        other["facts"]["execution_id"] = "other-execution"
        evidence.append(signed(other, self.key))
        write_json(self.bundle / "evidence.json", evidence)
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_cross_message_replay_cannot_establish_agent_send(self):
        observations = load_json(self.bundle / "observations.json")
        observations[0]["immutable_id"] = "different-item"
        write_json(self.bundle / "observations.json", observations)
        self.assertIsNone(self.assess()["agent_send_attribution"]["flagged"])

    def test_scope_is_checked_before_opening_message(self):
        observations = load_json(self.bundle / "observations.json")
        observations[0].update(mailbox_ref="unauthorized", mime_file="missing.eml")
        write_json(self.bundle / "observations.json", observations)
        with self.assertRaisesRegex(InputError, "outside_authorized_scope"):
            self.assess()

    def test_path_escape_is_rejected(self):
        observations = load_json(self.bundle / "observations.json")
        observations[0]["mime_file"] = "../outside.eml"
        write_json(self.bundle / "observations.json", observations)
        with self.assertRaisesRegex(InputError, "path_outside_bundle"):
            self.assess()

    def test_duplicate_message_id_header_is_rejected(self):
        path = self.bundle / "message.eml"
        path.write_bytes(b"Message-ID: <other@example.invalid>\r\n" + path.read_bytes())
        with self.assertRaisesRegex(InputError, "message_id_missing_ambiguous_or_mismatched"):
            self.assess()

    def test_duplicate_json_keys_and_non_finite_numbers_are_rejected(self):
        for raw in ['{"key":1,"key":2}', '{"value":NaN}']:
            with self.subTest(raw=raw):
                path = self.bundle / "malformed.json"
                path.write_text(raw, encoding="utf-8")
                with self.assertRaises(InputError):
                    load_json(path)

    def test_timezone_is_required(self):
        with self.assertRaisesRegex(InputError, "timezone_required"):
            timestamp("2026-10-28T10:00:00")

    def test_malformed_trust_kind_does_not_escape_contract_validation(self):
        profile = load_json(self.profile)
        profile["issuers"]["source-example"]["allowed_kinds"] = [{}]
        write_json(self.profile, profile)
        with self.assertRaises(InputError):
            self.assess()

    def test_unhashable_record_kind_is_rejected_as_invalid_input(self):
        for malformed in [{}, []]:
            with self.subTest(kind=malformed):
                self.profile, self.key = make_bundle(self.bundle)
                self.alter_record(lambda r: r.update(kind=malformed))
                with self.assertRaisesRegex(InputError, "unsupported_evidence_kind"):
                    self.assess()

    def test_reproducible_results_do_not_include_message_content(self):
        first = assess_bundle(self.bundle, self.profile, timestamp(REPLAY_TIME))
        second = assess_bundle(self.bundle, self.profile, timestamp(REPLAY_TIME))
        self.assertEqual(first, second)
        self.assertNotIn("Please bring", json.dumps(first))
        self.assertEqual(
            first["validation_basis"],
            "authored_contract_examples_not_independent_tenant_validation",
        )
