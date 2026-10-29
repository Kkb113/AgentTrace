# Evidence ledger implementation review

The implementation adds scoped, versioned evidence persistence and correlation to
the existing ingestion foundation. The two action/content paths remain independent.
The API emits qualified evidence relationships and append-only input revisions;
statistical detection, final flag policy, UI and new live adapters remain later work.

The review artifacts are [schema and trust](evidence-schema.md),
[correlation/retention rules](correlation-rules.md), [operations](runbooks/evidence-ledger.md)
and the executed [exit report](evidence/evidence-ledger-validation.json).

## Engineering review and incremental validation

This was an implementation self-review supported by regression tests and CI, not an
independent human peer review. The incremental work covered canonical/signature units
first, then transactional storage, authenticated API behavior, real SQL identities,
ingestion integration and a real TCP HTTP service restart.

| Reviewed issue | Final behavior / regression |
| --- | --- |
| Local FastAPI dependency resolution and established token-role restrictions | Runtime-resolved dependencies; existing app-viewer boundary preserved; issuer enrollment/signature checked separately; delegated investigator required for reassessment |
| Altered event replay could roll back its own conflict record on exception | Conflict is committed before returning the rejection; original receipt/history unchanged |
| Concurrent transaction-start times are not revision order | Scope lock, explicit revision sequence, post-lock evaluation time and metadata-bound history |
| Expired but unpurged revisions can collide with a new assessment | Explicit authenticated history epochs; retained history extends its prior revision and expiry can start a new epoch without waiting for purge |
| Encryption/hash without metadata binding leaves a substitution gap | Observation and input bindings are authenticated; privileged metadata-tampering regressions fail closed |
| Database rollback is not detected by a database-only hash | Independently held authenticated anchor validates the retained history prefix; explicit owner/OS/key-compromise limits |
| Identical bodies, subjects and Internet Message-IDs are ambiguous | Scoped distinct copies, exact-versus-candidate classes, explicit mappings and no implicit actor propagation |
| Generation receipts, echoes and output overlap can be misleading | Causal generation plus authenticated inclusion required; basic corrections, echoes, inherited regions and similarity stay context/candidates |
| A copy-mapping context must not become content evidence | Mappings retain their own supporting-observation list, including invalid mappings |
| Incomplete recipients or ambiguous extraction are not complete canonical content | Missing complete-payload digest; ambiguous authored-content lineage unavailable; independent action evidence can still be used |
| A snapshot reference is not proof of full replay | Reference-retention, byte verification and model re-execution are separate; model replay remains unavailable |

PostgreSQL grants/RLS and triggers were exercised using actual restricted logins.
The receiver cannot modify existing records or enroll trust; the collector cannot
read receipts; the content identity cannot read ledger tables. The dedicated ledger
role/configuration is local only. No new Azure resource, billable plan, Microsoft 365
permission or email mutation was introduced.

The source/hash-bound report records each of the five Phase 4 exits against executed
tests. Graph activity delivery remains explicitly unqualified and was not used to
manufacture a passing result. Existing live Exchange audit feasibility is independent;
the ledger tests use synthetic source records and do not establish release accuracy.

All five exits passed with 252 unit/security tests, 52 subtests and 123 integration
tests across the full repository gates. CI also validates pull requests targeting
managed `codex/**` branches so this phase can be reviewed separately from its pending
Graph-source dependency. Workflow permissions remain read-only and no cloud/live
probe runs in untrusted PR CI.
