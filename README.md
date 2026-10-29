# AgentTrace

AgentTrace detects two independent things in Outlook/Exchange Online email: whether an AI agent executed the send, and whether the body contains AI-generated content. Accurate agent attribution with low false positives is the priority. Content scoring is a separate best-effort capability.

Graph API activity delivery is under investigation. The independent workspace
canary passed; it does not qualify the Graph publisher. See the
[recovery findings and next steps](docs/graph-routing-recovery.md). Authenticated
Exchange Send audit correlation remains an independent supported evidence path.

This checkout contains the typed product foundation, a secured local synthetic PostgreSQL/API/worker stack, scoped Microsoft 365 access, a minimal Azure access sandbox, reliable versioned mailbox/audit ingestion, offline text extraction and reproducible CI/security/infrastructure gates. The dashboard/add-in UI and production rollout remain later work. Statistical content models are not installed. Read [the implementation plan](implementation.md), [the secure-access review](docs/secure-access-report.md) and [the feasibility report](docs/feasibility-report.md) before interpreting access tests or authored fixtures as detector qualification.

## Run locally

Requires Python 3.12.14, uv 0.12.12 and Docker with Compose. From the repository root:

`uv.lock` pins runtime and development dependencies with hashes. Generated requirements also support hash-enforced container builds. Use the same gate commands locally and in CI:

```powershell
uv sync --frozen --all-groups
uv run python scripts/bootstrap-tools.py all
uv run python scripts/ci-checks.py quality
uv run python scripts/ci-checks.py security
uv run python scripts/ci-checks.py infrastructure
uv run python scripts/ci-checks.py guard-controls
uv run python scripts/ci-checks.py integration
```

The integration gate generates local development keys, starts only the named synthetic stack and exercises PostgreSQL workload roles, queues, separate workers and an authenticated GET API over loopback. It also checks expired/untrusted tokens, decision retention and content-network isolation. Stop with `uv run python scripts/dev-services.py stop`. See the [local runbook](docs/runbooks/local-development.md) for health, clean-checkout testing and credential handling. Unit tests use offline fictional inputs; integration tests use disposable local schemas and explicit synthetic public-schema rows. No test sends email. Authored signed examples test semantics and are not independent tenant labels or vendor attestations.

Phase 1 exit evidence is recorded in [the foundation review](docs/repository-foundation.md). Active pull-request checks use GitHub Actions per the owner's selection after Azure project creation was denied. Equivalent [Azure Pipelines YAML](ci/azure-pipelines.yml) calls the same gates. Compile-only CI needs no Azure identity or secret. The optional WIF what-if template is reserved for a separately authorized protected connection. [CI decision](docs/adr/ci-and-release.md).

The API validates tenant, issuer, audience, signature, lifetime, client, role and server-owned message entitlements. The local stack uses fictional signing keys; a separate live probe verifies actual Entra-issued API tokens. The [access runbook](docs/runbooks/secure-access.md) covers the accepted certificate identities, exact-mailbox Exchange RBAC, isolated audit reader, Azure data roles and operator-only setup. Cloud/live probes never run in untrusted PR CI. The model-absent content worker remains in standby and does not acknowledge content jobs. The separate ingestion collector supports bounded continuous collection and native Event Grid delivery. Its message observations never enter the authored-example detector. Statistical scoring, evidence qualification and UI implementation remain later milestones. See [the ingestion design](docs/mail-ingestion.md), [operations runbook](docs/runbooks/mail-ingestion.md), and the subsequently configured [Graph activity source](docs/graph-activity-logging.md).

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
