# Outlook runtime foundation review

The Phase 1 foundation is implemented and validated independently of the old application stack. It adds the installed `agenttrace-outlook` command and `scripts/monitor-outlook-mail.py`, strict contracts/configuration, a fixed-mailbox metadata GET adapter, durable SQLite work and versioned decisions with a separate preview outbox. No new dependency, cloud resource, permission or live-mail write was introduced. The archived terminal demo and client workbook remain unchanged.

## Exit review

| Exit | Executed evidence | Result |
| --- | --- | --- |
| Runner starts without dashboard/API/content workers | Installed command validates and processes fictional metadata with the Compose stack stopped; script replay preserves one decision/preview | Pass |
| Migrations/state/leases recover across crashes and restarts | Subprocess exits during uncommitted schema/work and after committed observation/decision; integrity checks, version preservation, lease generations and process exclusion | Pass |
| Dry-run never mutates mail; non-production verdicts are rejected | Socket-denied CLI test, fixed GET adapter contract, apply blocked before state, experimental/unenrolled/expired/scope-conflicting decision rejection; preview cannot mean applied | Pass |
| Relevant engineering checks pass the tested source | Clean selected-source installation; formatting, strict types, contracts, demo archive, import/network boundaries, secrets/privacy/licenses/dependency audit, infrastructure, negative controls, unit/security and existing integration suite | Pass |

The [executed validation record](evidence/outlook-runtime-validation.json) records counts, source digest, exclusions and limits. [Operations and commands](runbooks/outlook-runtime.md) explain the actual runnable behavior. The final published PR also runs the five shared GitHub Actions gates against its exact head revision.

## Engineering review

The review followed input → observation → work → decision → annotation preview, then startup/crash/restart paths. Findings fixed during implementation: immediately supersede an old preview when a new observation arrives; reject out-of-order versions and unbounded work limits; sanitize rollback/driver failures; always close the SQLite connection before releasing the OS lock. Decision insertion and preview insertion cannot commit separately. SQLite FULL and injected outbox failure tests establish rollback and retry behavior rather than merely checking method return values.

The OS lock is acquired before SQLite is opened and held across all transactions, migrations and status reads. This excludes simultaneous cooperating connections even after a lease timeout. The additional persisted lease fences a stale owner/generation and expires visibly after a prolonged pause. An abrupt process exit releases the OS lock; restart recovers committed work and rolls back uncommitted changes without duplicate logical decisions. Schema v1 is created transactionally, validated on restart and refuses unknown versions/drift; no destructive reset/migration shortcut exists.

Runtime imports do not load the demo, dashboard, API, content worker or AI SDK. The reviewed certificate/transport helpers are reused only by the optional metadata reader, not instantiated by fixture startup. Reused transport assumptions include fixed Microsoft HTTPS origin, no redirects, bounded response size, timeout and credential-safe errors. The new adapter fixes mailbox, operation, fields and immutable-ID preference; arbitrary URLs and payloads are not accepted. Live Graph collection/backoff is still Phase 2 work and is not simulated as a successful live test here.

The pure annotation admission interface rejects experimental decisions and all unenrolled positive rules, even if a caller asserts `qualified`. Only the foundation's explicit production Unknown rule can create a preview. The outbox has no applied state and there is no PATCH route. The owner’s inferred-manual policy remains the planned Human rule; Phase 1 deliberately makes no accuracy claim before its qualification.

## Boundaries and remaining work

All new end-to-end runs use invented metadata; there was no new live mailbox operation. The pre-existing legacy integration stack is regression coverage and is not a runtime requirement. No Graph activity-log delivery claim, new source enrollment, accuracy/recall claim, false-positive estimate or Outlook rendering claim is made by these tests.

The runner does not yet collect messages, evaluate qualified positive rules, apply categories, purge physical rows, provision encrypted storage/ACLs, back up state or run unattended. Expiry deadlines and admission guards are present; physical retention and deployment hardening remain later gates. On Windows the one symlink-creation test is unavailable without extra privileges; hard-link alias rejection is tested locally and the symlink test runs on Linux CI. A sandbox-restricted initial legacy HTTP test run was stopped and repeated with localhost access; the complete rerun passed. No implementation defect is hidden by that environment limitation.

The earlier evaluation work and spreadsheet changes were excluded using a selected-index export. Local regression containers were stopped after testing; original database volumes were retained. No unresolved critical/high defect was found within this foundation's tested scope. General production readiness remains gated by the rest of `implementation.md`.
