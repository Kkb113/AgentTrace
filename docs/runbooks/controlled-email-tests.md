# Controlled actual-email POC tests

Test actual sending actions, not writing style. Operators send harmless synthetic mail manually in their clients or through an existing agent; AgentTrace only reads the received copies and classifies them. No public dataset or separate review team is required.

## Test cases

| Actual operator action | Expected supported POC result |
| --- | --- |
| Manually send in Outlook, including copied AI-written wording | Human when complete inspection shows no automation/conflict |
| Manually send Gmail → Outlook | Human when the received fields meet the same inspection policy |
| Claude Microsoft 365 connector executes Send, with or without approval | AI Agent when the known marker, authenticated Send, publisher and copy-context evidence qualify; otherwise Unknown |
| Generic Gmail API/MCP-looking header without enrolled corroboration | Unknown; API submission alone does not establish an AI executor |
| Incomplete inspection, failed/stale/conflicting required evidence | Unknown |
| Normal browser controlled by a person or agent | Human under the previously approved compatibility policy |

Record which action was actually performed before inspecting the result. Use the same harmless wording for manual and agent messages. The action log supplies expected outcomes only; subjects, expected labels and body origin must not feed the classifier. These results do not prove human identity or universal agent coverage.

## Run the existing monitor

Use the existing private runtime configuration and designated mailbox. Keep the synthetic-only collection boundary: new test subjects start with `AgentTrace synthetic test:` and the message contains invented, non-sensitive information.

```powershell
uv run agenttrace-outlook --config work/private/sender-rules-live/runtime.private.json
```

Send the manual and Claude test messages yourself through the respective tools. AgentTrace has no send capability. Source searches are asynchronous: a received Claude message can initially be Unknown and later become AI Agent. Record that delay; do not promote its marker alone.

Stop with Ctrl+C, then inspect persisted rule output:

```powershell
uv run agenttrace-outlook --config work/private/sender-rules-live/runtime.private.json --inspect-rules
```

The inspector is an offline stored view, explicitly `evidence_refreshed=false`. The running monitor refreshes evidence; the inspector does not. Output contains hashed message/evidence references and reasons. Private validation records can map those references to the exact test emails without putting addresses, headers or provider IDs into Git. See [sender rule operations](sender-detection-rules.md) for authentication, source freshness and recovery.

For each case keep a small private record: actual send method, expected policy class, received-message reference, observed result, reason/evidence references, test time and any delay/mismatch. Keep original raw-retention deadlines. This is a test log, not an AI-text training corpus.

## Acceptance and limits

Supported actual-mail cases must match their recorded actions, and tested manual messages must not receive an AI badge. Automated semantic/adversarial regressions cover malformed/forged/missing/source-failure cases without changing real mailbox permissions to create outages. Retrospective authenticated rereads demonstrate reproducibility; they do not measure new-message latency.

Report the number of real examples and what happened. Zero observed false flags in a few manual tests is a POC observation, not a population-level 0.1% false-positive guarantee. Formal G1/G2 measurement remains future qualification. External Gmail-agent attribution remains unsupported without additional evidence; no external-source message is forced into AI merely to make the demo pass. Category creation and writes remain separate subsequent phases.
