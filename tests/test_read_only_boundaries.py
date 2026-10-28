from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from agenttrace_feasibility.capabilities import SYNTHETIC_SUBJECT_PREFIX, graph_uri, run_read_only
from agenttrace_feasibility.validation import InputError
from tests.support import REPLAY_TIME, make_bundle, temporary_workspace

ROOT = Path(__file__).resolve().parents[1]
SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"


class ReadOnlyBoundaryTests(unittest.TestCase):
    def test_write_commands_are_rejected_before_azure_cli_runs(self):
        for command in [
            ["group", "create"],
            ["resource", "delete"],
            ["rest", "--method", "post", "--url", "https://graph.microsoft.com/v1.0/me/sendMail"],
            [
                "rest",
                "--method",
                "get",
                "--url",
                "https://graph.microsoft.com/v1.0/me",
                "--method",
                "post",
            ],
        ]:
            with self.subTest(command=command), patch("subprocess.run") as execute:
                with self.assertRaisesRegex(InputError, "azure_operation_not_allowlisted"):
                    run_read_only(command, SUBSCRIPTION)
                execute.assert_not_called()

    def test_arbitrary_url_is_rejected(self):
        with patch("subprocess.run") as execute:
            with self.assertRaises(InputError):
                run_read_only(
                    ["rest", "--method", "get", "--url", "https://untrusted.invalid/collect"],
                    SUBSCRIPTION,
                )
            execute.assert_not_called()

    def test_directory_read_cannot_expand_into_unfiltered_messages(self):
        with patch("subprocess.run") as execute:
            with self.assertRaises(InputError):
                run_read_only(
                    ["rest", "--method", "get", "--url", graph_uri("me", {"$expand": "messages"})],
                    SUBSCRIPTION,
                )
            execute.assert_not_called()

    def test_unfiltered_mailbox_read_and_body_selection_are_rejected(self):
        for query in [
            {},
            {
                "$top": "5",
                "$filter": f"startswith(subject,'{SYNTHETIC_SUBJECT_PREFIX}')",
                "$select": "body",
            },
        ]:
            with self.subTest(query=query), patch("subprocess.run") as execute:
                with self.assertRaises(InputError):
                    run_read_only(
                        ["rest", "--method", "get", "--url", graph_uri("me/messages", query)],
                        SUBSCRIPTION,
                    )
                execute.assert_not_called()

    def test_cli_uses_argument_array_explicit_subscription_and_no_shell(self):
        with (
            patch(
                "agenttrace_feasibility.capabilities.azure_cli_prefix",
                return_value=["azure-python", "-IBm", "azure.cli"],
            ),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, '{"name":"kb-agentdemo"}', ""),
            ) as execute,
        ):
            result = run_read_only(["group", "show", "--name", "kb-agentdemo"], SUBSCRIPTION)
            args, kwargs = execute.call_args
            self.assertIn(SUBSCRIPTION, args[0])
            self.assertIn("--subscription", args[0])
            self.assertFalse(kwargs["shell"])
            self.assertEqual(result["status"], "observed")

    def test_denied_requests_are_not_reported_as_missing_capabilities(self):
        with (
            patch("agenttrace_feasibility.capabilities.azure_cli_prefix", return_value=["az"]),
            patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [], 1, "", "Forbidden raw-sensitive-value"
                ),
            ),
        ):
            result = run_read_only(["account", "show"], SUBSCRIPTION)
            self.assertEqual(result, {"status": "unavailable", "reason": "access_denied"})
            self.assertNotIn("raw-sensitive-value", json.dumps(result))

    def test_timeout_remains_explicit(self):
        with (
            patch("agenttrace_feasibility.capabilities.azure_cli_prefix", return_value=["az"]),
            patch("subprocess.run", side_effect=subprocess.TimeoutExpired("az", 45)),
        ):
            self.assertEqual(
                run_read_only(["account", "show"], SUBSCRIPTION)["reason"], "request_timeout"
            )

    def test_windows_batch_wrapper_is_bypassed(self):
        from agenttrace_feasibility.capabilities import azure_cli_prefix

        with (
            patch("agenttrace_feasibility.capabilities.sys.platform", "win32"),
            patch("shutil.which", return_value="C:/Azure/wbin/az.cmd"),
            patch("pathlib.Path.is_file", return_value=True),
        ):
            prefix = azure_cli_prefix()
            self.assertTrue(prefix[0].endswith("python.exe"))
            self.assertEqual(prefix[1:], ["-IBm", "azure.cli"])


class CommandLineEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temporary = temporary_workspace()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle"
        self.profile, _ = make_bundle(self.bundle, "human", operation="draft_generation")
        self.env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))

    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "agenttrace_feasibility", *arguments],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
            shell=False,
        )

    def test_full_import_signature_message_link_and_two_findings(self):
        output = self.root / "assessment.json"
        result = self.run_cli(
            "assess-evidence",
            "--bundle",
            str(self.bundle),
            "--trust-profile",
            str(self.profile),
            "--as-of",
            REPLAY_TIME,
            "--output",
            str(output),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        finding = json.loads(output.read_text())["decisions"][0]["findings"]
        self.assertIs(finding["agent_send_attribution"]["flagged"], False)
        self.assertIs(finding["content_assessment"]["flagged"], True)
        self.assertEqual(len(finding), 2)

    def test_bad_contract_returns_sanitized_error_and_no_report(self):
        (self.bundle / "observations.json").write_text('{"secret-content": true}')
        output = self.root / "assessment.json"
        result = self.run_cli(
            "assess-evidence",
            "--bundle",
            str(self.bundle),
            "--trust-profile",
            str(self.profile),
            "--output",
            str(output),
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(output.exists())
        self.assertNotIn("secret-content", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_input_bundle_cannot_be_overwritten_by_report(self):
        result = self.run_cli(
            "assess-evidence",
            "--bundle",
            str(self.bundle),
            "--trust-profile",
            str(self.profile),
            "--as-of",
            REPLAY_TIME,
            "--output",
            str(self.bundle / "evidence.json"),
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("output_cannot_overwrite_evidence_inputs", result.stderr)

    def test_no_send_or_approval_command_exists(self):
        for verb in ["send", "approve", "generate", "schedule"]:
            with self.subTest(verb=verb):
                self.assertNotEqual(self.run_cli(verb).returncode, 0)
