# AgentTrace

AgentTrace detects two independent things in Outlook/Exchange Online email: whether an AI agent executed the send, and whether the body contains AI-generated content. Accurate agent attribution with low false positives is the priority. Content scoring is a separate best-effort capability.

This checkout currently contains bounded feasibility tooling and the initial evidence/policy documents. It does not contain the full hosted application, Outlook add-in or statistical content model. Read [the implementation plan](implementation.md) and [the current feasibility report](docs/feasibility-report.md) before interpreting results as completed release qualification.

## Run locally

Requires Python 3.12+, `cryptography==50.0.2` and `msal==1.39.0`. Create an isolated environment and install the pinned requirements using your normal Python/package manager. From the repository root in PowerShell:

With `uv`, prefer `uv sync --frozen`, which installs the project and the transitive dependency versions/hashes from `uv.lock`. It also installs the pinned development linter; run `uv run ruff check src tests scripts` and `uv run ruff format --check src tests scripts`. The standard-library test suite needs no separate test-runner dependency.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-feasibility.txt
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts/verify-feasibility.py
```

The tests create only offline synthetic files in an ignored workspace and never send email. Their keys are generated in memory. Authored signed examples test contract semantics and are not independent tenant labels or vendor attestations.

To replay the reviewed public example:

```powershell
python -m agenttrace_feasibility assess-evidence `
  --bundle examples/evidence-contract `
  --trust-profile examples/evidence-contract/trust-profile.json `
  --as-of 2026-10-28T10:10:00Z `
  --output work/reports/example-assessment.json
```

To inspect the existing environment, use the operator's already authenticated Azure CLI session, without displaying or supplying tokens:

```powershell
python -m agenttrace_feasibility inspect-environment `
  --subscription <explicit-subscription-guid> `
  --resource-group kb-agentdemo `
  --private-output work/private/tenant-preflight
```

The collector allows selected GET/read commands only and limits mailbox requests to metadata for the `AgentTrace synthetic test:` subject prefix. It never grants permissions, enables logs or creates resources. Raw responses remain private. On Windows it bypasses the `az.cmd` batch wrapper to preserve `&` in API query strings safely.

To inspect an externally sent live synthetic message:

```powershell
python -m agenttrace_feasibility inspect-export `
  --mime-file work/private/test/received-message.eml `
  --source-transcript work/private/test/source-transcript.private.json `
  --private-output work/private/test/assessment.private.json
```

See [the collection runbook](docs/runbooks/synthetic-email-evidence.md). The live export path preserves unknown when an unverified tool transcript or later subject search cannot authenticate the send-to-message relationship. It never upgrades from an AI header or from content style.

For an already authorized temporary reader, copy `config/reader-settings.example.json` into `work/private/`, insert the real tenant/client/operator IDs, designated mailbox and up to three exact synthetic subjects, then run:

```powershell
python -m agenttrace_feasibility inspect-reader `
  --settings work/private/reader-settings.private.json `
  --private-output work/private/new-reader-capture
```

The output directory must be new. Complete Microsoft's browser sign-in yourself if prompted. This command requests only the already approved delegated `Mail.Read` and `AuditLogsQuery-Exchange.Read.All` scopes. It does not create an application or grant consent. Tokens stay in memory. An audit-search POST creates an analytical search job; the tool has no email send/write operation. Query failures, pending searches, incomplete pages, missing or ambiguous message copies and unknown executors produce unknown findings.

The live audit rule requires a successful Exchange Send event, consistent tenant/mailbox/application context, and a unique scoped Sent Items match. It pins Anthropic's documented Claude connector application ID; a generic Graph application, an app's display name, a declaration header or writing style cannot trigger it. This narrowly supported route does not establish universal agent coverage or content authorship. Store the original private Microsoft responses and capture hashes; they are authenticated API observations, not vendor-signed receipts. Audit and Graph immutable-ID equivalence remains a separately disclosed limitation.

To reassess after a pending search or repeat a read without creating another search, add `--reuse-searches-from work/private/previous-reader-capture` and choose a new output directory. The server-side message/actor/window/operation filters must match exactly before the search can be reused. The initial temporary reader has been retired after explicit owner approval; future live runs require an authorized identity and consent. See [the access record](docs/access-remediation.md).

## Evidence and decisions

- [Scope and accepted data baseline](docs/scope.md)
- [Threat model](docs/threat-model.md)
- [Frozen acceptance criteria](docs/acceptance.md)
- [Tenant capability matrix](docs/tenant-capabilities.md)
- [Source fields and linkage rules](docs/source-field-matrix.md)
- [Content policy](docs/content-policy.md) and [bounded experiment](docs/content-feasibility.md)
- [Azure sizing and cost baseline](docs/azure-cost-baseline.md)

All actual email, source transcripts, IDs, tenant inventories, tokens and sensitive captures stay outside Git. `work/`, environment files, keys and local environments are ignored. The tracked examples use fictional `.invalid` identities and public test keys only. New Azure resources, when needed in later work, must use `kb-agentdemo` with explicit subscription selection and suitable low-cost configurations.
