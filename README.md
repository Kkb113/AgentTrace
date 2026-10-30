# AgentTrace

AgentTrace is becoming an Outlook-native sender detector: a small supervised Python monitor that applies **AI Agent** (red), **Human-capable** (green) or **Unknown** (yellow) categories. No standalone application, custom API, add-in or AI-text detector is required.

The current [owner-approved POC policy](docs/adr/human-capable-classification.md) uses Human-capable for a complete normal-client-compatible inspection, whether a person or an agent controls the browser. AI Agent requires the narrow corroborated MCP/audit rule. Missing/conflicting evidence remains Unknown; neither label claims forensic controller identity.

## Current delivery

Phase 0 of the Outlook-native baseline is complete, with [four exit criteria evidenced](config/outlook-baseline-exits.json). Its [frozen contract](config/outlook-production-baseline.json) and [implementation plan](implementation.md) define scope, colors, data/retention, ownership, permissions and release gates. The [baseline review](docs/outlook-production-baseline.md) records actual feasibility evidence and open dependencies.

The working demo uses experimental binary header rules, including a Human fallback. It is preserved separately; it does not establish production accuracy. The narrow authenticated Microsoft/Claude Exchange Send route has actual source evidence. Phase 1 is complete, with [four exits validated](docs/outlook-runtime-review.md). Its separate runner processes synthetic metadata into durable Unknown previews. Phase 2 adds [durable read-only mailbox synchronization](docs/runbooks/outlook-mailbox-sync.md), including receiving-folder discovery, delta checkpoints, move/restart recovery and synthetic-only header capture. Phase 3 adds the [approved POC sender rules](docs/runbooks/sender-detection-rules.md). Independent numeric accuracy remains unmeasured; the current scoped category-writer status is described below. See the [runtime runbook](docs/runbooks/outlook-runtime.md) for preparation, commands and recovery behavior.

## Run the existing terminal demo

Phase 5's [scoped category setup](docs/outlook-category-access.md) established the one-mailbox writer and owned colors. Phase 6 adds [explicit apply, readback, retry and conservative rollback](docs/outlook-category-writer.md), with durable decision-bound intents and qualified conditional updates. Actual synthetic Unknown/AI Agent/Human-capable writes, concurrency and preservation were tested. Continuous automatic application remains disabled for the later operational/pilot gates. [Writer commands](docs/runbooks/outlook-category-writer.md).

Phase 4's [controlled actual-email tests](docs/runbooks/controlled-email-tests.md) pass under the [owner-approved POC revision](docs/adr/live-email-poc-validation.md): manual Outlook/Gmail cases return Human-capable and the supported Claude/Microsoft 365 case returns AI Agent. No external corpus or separate curator is required for this POC. The formal [accuracy workbench](docs/runbooks/sender-accuracy.md) remains optional for future G1/G2 qualification. These tests make no population-accuracy claim; the existing terminal demo only reads mail. Scoped pilot category commands are documented above.

From PowerShell:

```powershell
& "C:\AgentDetection\.venv\Scripts\python.exe" "C:\AgentDetection\scripts\watch-incoming-mail.py" --lookback-minutes 60
```

Ctrl+C stops monitoring. This reads the configured Microsoft mailbox using existing operator certificate credentials, prints metadata/headers and never changes mail. [Demo operations and limitations](docs/runbooks/terminal-email-demo.md).

## Validate the production baseline

```powershell
uv sync --frozen --all-groups
uv run python scripts/verify-outlook-baseline.py
uv run python -m pytest tests/test_outlook_baseline.py tests/test_mail_monitor.py tests/test_audit_capture.py -q
```

The baseline verifier checks the frozen policy and generated schema. It does not run the production detector or enable categories. The separate [read-only feasibility inspector](docs/runbooks/outlook-baseline-verification.md) uses private synthetic locators and existing permissions; it never runs in untrusted PR CI.

## Engineering and history

Required local/hosted checks use the shared commands below:

```powershell
uv run python scripts/bootstrap-tools.py all
uv run python scripts/ci-checks.py quality
uv run python scripts/ci-checks.py security
uv run python scripts/ci-checks.py infrastructure
uv run python scripts/ci-checks.py guard-controls
uv run python scripts/ci-checks.py integration
```

Earlier phases delivered reusable [source feasibility](docs/feasibility-report.md), [repository/CI foundations](docs/repository-foundation.md), [secure access](docs/secure-access-report.md), [ingestion](docs/mail-ingestion-report.md) and [evidence correlation](docs/evidence-ledger-review.md). Their original reports remain historical; the new ten-phase plan does not inherit their completion states. Existing v1 API/content components are retained for compatibility, not new product obligations.

[Current scope](docs/scope.md), [Outlook-native decision](docs/adr/outlook-native-categorization.md), [permissions](docs/permissions-matrix.md) and [threat model](docs/threat-model.md) distinguish current requirements from historical grants. Graph activity-log delivery remains unqualified; the independent Exchange audit route does not depend on it.

Actual email, headers, account IDs, tokens, certificates and reviewer/source records stay out of Git. Qualification/write tests use synthetic data. Raw evidence expires after seven days, decision metadata after thirty days. New Azure resources, if later justified, must use kb-agentdemo, an explicit subscription and minimal suitable cost. No new resource or category permission is needed for the baseline.
