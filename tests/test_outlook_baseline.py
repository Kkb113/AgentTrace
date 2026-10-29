"""Freeze baseline requirements without treating them as a qualified detector."""

import copy
import importlib.util
import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from agenttrace_feasibility.outlook_baseline import OutlookBaseline, main, read_baseline, verify

ROOT = Path(__file__).resolve().parents[1]


class OutlookBaselineTests(unittest.TestCase):
    def test_cli_inventory_decodes_windows_encoding_without_losing_unicode(self):
        spec = importlib.util.spec_from_file_location(
            "baseline_inspector", ROOT / "scripts/inspect-outlook-baseline.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        expected = {"description": "Example \u2014 role"}
        for raw in [
            json.dumps(expected, ensure_ascii=False).encode("utf-8"),
            json.dumps(expected, ensure_ascii=False).encode("cp1252"),
        ]:
            self.assertEqual(module.decode_cli_json(raw), expected)

    def test_inspector_rejects_nonprivate_paths_before_constructing_clients(self):
        spec = importlib.util.spec_from_file_location(
            "baseline_inspector", ROOT / "scripts/inspect-outlook-baseline.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.object(module, "build_sources") as clients:
            with self.assertRaises(ValueError):
                module.inspect(
                    ROOT / "config/outlook-production-baseline.json",
                    ROOT / "work/reports/rejected-capture",
                )
        clients.assert_not_called()

    def setUp(self):
        self.value = json.loads((ROOT / "config/outlook-production-baseline.json").read_text())

    def test_baseline_and_schema_are_current_and_non_executing(self):
        report = verify(ROOT)
        self.assertTrue(report["schema_current"])
        self.assertFalse(report["category_writes_enabled"])
        self.assertEqual(
            report["human_capability"], "policy_feasible_accuracy_qualification_pending"
        )

    def test_unsafe_policy_drift_is_rejected(self):
        for field, unsafe in [
            ("incomplete_inspection_category", "Human"),
            ("human_result_basis", "verified_human_execution"),
            ("untrusted_declaration_category", "AI Agent"),
            ("generic_api_category", "AI Agent"),
            ("non_ai_automation_category", "Human"),
            ("demo_predictions_eligible_for_write", True),
            ("category_writes_enabled", True),
            ("new_permissions_authorized", True),
            ("human_rule_status", "qualified"),
            ("qualification_status", "passed"),
            ("raw_retention_days", 8),
            ("category_lifetime_days", 365),
            ("no_standalone_application", False),
        ]:
            with self.subTest(field=field):
                value = copy.deepcopy(self.value)
                value[field] = unsafe
                with self.assertRaises(ValidationError):
                    OutlookBaseline.model_validate_json(json.dumps(value))

    def test_wrong_colors_duplicates_and_unknown_fields_are_rejected(self):
        for mutate in [
            lambda v: v["categories"][0].update(color="green", preset="preset4"),
            lambda v: v["categories"].__setitem__(2, v["categories"][1]),
            lambda v: v.update(client_secret="not-a-real-secret"),
            lambda v: v.update(receiving_routes=["gmail_to_gmail", "outlook_to_outlook"]),
        ]:
            value = copy.deepcopy(self.value)
            mutate(value)
            with self.assertRaises(ValidationError):
                OutlookBaseline.model_validate_json(json.dumps(value))

    def test_command_reports_only_safe_validation_error(self):
        output = io.StringIO()
        with (
            patch(
                "agenttrace_feasibility.outlook_baseline.verify",
                side_effect=ValueError("PRIVATE INPUT"),
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(main([]), 1)
        self.assertNotIn("PRIVATE INPUT", output.getvalue())

    def test_fresh_cli_process_validates_contract_end_to_end(self):
        result = subprocess.run(
            [sys.executable, "scripts/verify-outlook-baseline.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["qualification_status"], "not_measured")
        self.assertFalse(
            read_baseline(ROOT / "config/outlook-production-baseline.json").category_writes_enabled
        )
