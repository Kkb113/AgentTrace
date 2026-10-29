# Live terminal email demonstration

This remains the working experimental demo. The [new Outlook-native production roadmap](../../implementation.md) defines a separate monitor with AI Agent/Human/Unknown categories and safe write permissions; this runbook does not implement or qualify that monitor.

This operator-only script monitors the already configured Microsoft mailbox using the existing certificate-based mail reader. It requests metadata and headers, not message bodies or attachments. It creates no Azure resources, changes no permissions and never sends/changes email. The owner's explicit demo request authorizes this mailbox-wide incoming-metadata view; it does not expand the separate hosted synthetic collectors or authorize customer-data/model processing.

For this terminal test, the owner explicitly requested exactly **Sent by AI Agent** or **Sent by Human** as the classification. The script entry point enables an experimental binary header heuristic: either the Gmail API trace or the exact Office365 MCP declaration maps to AI Agent; otherwise it maps to Human. Its evidence and JSON qualification remain separate from the exact classification text; neither prediction is qualified actor attribution. The underlying module keeps conservative behavior unless `--demo-heuristic` is passed, and no production policy is changed.

From PowerShell, run:

```powershell
& "C:\AgentDetection\.venv\Scripts\python.exe" "C:\AgentDetection\scripts\watch-incoming-mail.py" --lookback-minutes 60
```

Keep it running and send the test messages externally. Ctrl+C stops cleanly. The default poll interval is ten seconds; a heartbeat appears each minute. Without a lookback argument, only messages received after startup are considered. Restarting with lookback intentionally redisplays matching messages because no checkpoint/raw mail is written by this tool.

The script reads all receiving folders in the authorized mailbox, including rule-routed/Junk mail, excluding Sent Items, Drafts and Outbox. It pages through the session window before declaring a successful scan, deduplicates immutable message IDs in memory, handles moves, honors throttling/backoff and reports access/coverage failures. Deleted/unavailable messages are gaps, not fabricated classifications. It is a bounded demo, not a replacement for the production subscription/reconciliation service: after 10,000 session messages or 100 pages, it exits with an explicit restart-required error rather than silently skipping data. Sent copies manually relocated into other folders cannot always be distinguished by metadata alone.

## Terminal output and policy

Each new item shows sender, subject, receipt time, classification, Message-ID, source evidence and readable selected headers, including duplicate fields. Untrusted terminal control/bidirectional characters are escaped. Add `--all-headers` for the complete bounded collected header view or `--json` for NDJSON. `--once` performs one connectivity/read cycle and exits; it does not wait for delayed audit.

- **Sent by AI Agent** in this terminal test can come from the experimental Gmail API or Office365 MCP header rule, or from the separately qualified Microsoft audit route. The evidence/qualification distinguishes these bases.
- **Sent by Human** is the demo prediction when neither recognized marker appears, not a qualified human-action finding.
- **Unable to determine** remains the conservative underlying module's default without the demo flag. Errors and missing messages stay explicit coverage gaps.
- A Received field containing `gmailapi.google.com` and `with HTTPREST` triggers the owner's requested demo label. This is an API-routing heuristic: other applications can use the API, headers can be forged, and no marker does not establish human execution.
- The header `x-ai-generated: mcp-office365` also triggers **Sent by AI Agent** in demo mode. Header names/values are matched case-insensitively and surrounding value whitespace is ignored; different values and body/subject mentions do not match. The exact triggering header appears in the evidence. This sender declaration stays unverified outside the separate authenticated audit rule.

The actual owner-prepared A/B test showed this API hint in the Claude-sent Gmail message and no recognized API marker in the manual Gmail message. With the binary demo rule enabled, B receives **Sent by AI Agent** and A receives **Sent by Human**. This is a two-message observation, not a general validated classifier. Neither the subject A/B nor the owner's supplied truth is used as a prediction feature. Non-AI API senders and agents without the marker can be misclassified. Do not present the heuristic as independent proof of either actor.

## Existing Microsoft/Claude route

Enable the original narrow route separately:

```powershell
& "C:\AgentDetection\.venv\Scripts\python.exe" "C:\AgentDetection\scripts\watch-incoming-mail.py" --lookback-minutes 60 --exchange-audit
```

This verifies the enrolled connector publisher using the operator's existing Azure CLI session and explicit configured subscription, then uses the isolated audit reader for analytical Exchange Send searches. Analytical POST requests create search jobs, not outbound email. Only messages whose sender is the configured Microsoft mailbox are eligible. The rule requires the original successful Send/tenant/mailbox/enrolled-app checks, a unique scoped Sent Items copy, matching subject/send time/Internet Message-ID and consistent received-copy metadata. It preserves the known limitation that sender/recipient immutable-ID equivalence is not established and an Internet Message-ID is not a universal authenticated key.

Incoming messages are printed immediately as indeterminate while evidence is missing. Audit checks run at most one task per collection cycle; a completed query without qualifying evidence is retried after five minutes. Evidence can be delayed many minutes or longer. The script stops reassessing a particular item after two hours, keeping the unknown result; it continues mailbox monitoring. Missing/failed audit and publisher checks do not manufacture a human result. This route is not applied to external Gmail senders.

## How to qualify Gmail agent attribution

The receiving Outlook mailbox cannot query personal Gmail's send execution history. Connecting the sender's ordinary Gmail API alone still does not expose a general AI-versus-human executor field. The observed HTTPREST pattern supplies a useful routing hint, not that missing actor evidence.

For the built-in Claude website/Desktop Gmail connector, investigate an authenticated source record of the actual Gmail send tool call and successful result. With an eligible existing Claude Enterprise organization, the Compliance API can provide organization/chat data; validate that this specific connector's tool result, provenance and message identifier are actually exposed before claiming the route works. A generic activity/login event is insufficient. [Claude Compliance API](https://platform.claude.com/docs/en/manage-claude/compliance-api).

The intended evidence chain is: authenticated Claude send operation → successful Gmail result → sender-side Gmail message/Internet Message-ID mapping where necessary → unambiguous observed Outlook copy. Validate execution semantics, actor scope, collisions, replay and source completeness. A Gmail-local message ID is not the same as the Internet Message-ID. User-pasted transcripts remain user-supplied source statements rather than authenticated vendor API captures; a later same-subject search is not an exact causal link.

Alternatives are a separately qualified read-only source trace from an existing instrumented agent, or licensed Workspace audit records that actually expose the required action/application/message fields. Workspace administrator logs do not exist merely because a personal Gmail account is connected. Do not purchase Enterprise/Workspace or build an email-sending tool just to force a demo badge. No such new source access has been configured by this script.

## Data and test evidence

Private settings are read from `work/private/secure-access/`; certificates remain in the current Windows user's store and tokens stay in memory. Do not run the monitor as an unrelated Windows user or publish private settings. Terminal output contains addresses/header metadata; any redirected capture must be protected and follow the seven-day raw-evidence policy. The script itself writes no raw capture or decisions to disk.

Targeted tests cover the actual evidence rule, forged declarations, wrong source/scope, API hints, metadata-only requests, pagination, retries, deduplication, terminal injection, disappearing messages and Ctrl+C. The tests are authored behavioral checks, not independent accuracy measurements. Live A/B captures remain under ignored `work/private/`; sanitized operational results are under `work/reports/`.

```powershell
& "C:\AgentDetection\.venv\Scripts\python.exe" -m pytest tests/test_mail_monitor.py tests/test_audit_capture.py -q
```

The broader in-progress sender-only runtime migration is still required. This standalone diagnostic does not certify the new platform, general Gmail actor detection, a human classifier or any false-positive rate.
