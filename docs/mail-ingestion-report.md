# Mail ingestion implementation review

The reliable-ingestion milestone is implemented for the approved synthetic Outlook
scope. It delivers durable notification intake, scoped reconciliation, recoverable
checkpoints, explicit source gaps, independent versioned analysis work, offline text
extraction and read-only operational health. It adds no email-sending or approval feature.

## Exit evidence

| Exit | Verification |
| --- | --- |
| G7 outage/replay accounting | Real PostgreSQL transactions exercise crash-before-commit, retry-after-commit, duplicates, out-of-order reads, missed notifications, invalid cursors/full resync, stale/concurrent receipts, moves, deletion, poison and exact replay. Historical loss remains explicit. |
| Subscription/checkpoint/dead-letter health | Authenticated source health and operator CLI expose subscription expiry, partition freshness, queue age, retry/poison state, current message/version inventory and coverage gaps. Renewal/replacement and native invalid-payload quarantine are tested. |
| Persist before acknowledgment | Local HTTP ingestion commits before 202; storage failure returns 503. Native Azure receipts are deleted after durable commit. A failed commit leaves the receipt available for redelivery. |
| Minimum-data access/retention | Exact-folder synthetic body reads, encrypted locators/cursors/audit evidence, transient version-bound content capsules, raw snapshots off, actual SQL role denial tests, expiry/purge tests and unchanged original Azure firewalls. |
| Correct extraction/version/exclusion semantics | Labeled HTML/plain/MIME/Unicode/quote/forward/footer/language/length fixtures, source-offset checks, stale-version fencing and canary scans of summaries, queues, health and captured output. |

[The machine-readable exit matrix](../config/mail-ingestion-exits.json) names the
required executed tests. [The validation report](evidence/mail-ingestion-validation.json)
records their results and source hashes. The five shared local/PR gates cover formatting,
typing, exported contracts/locks, boundaries, licenses, vulnerability/secret/privacy
scans, Bicep compilation, real local services and deliberate CI failure controls.

## Actual Microsoft/Azure validation

The [live report](evidence/mail-ingestion-live-validation.json) records 13 passing
checks, four observed synthetic mailbox copies, three native Graph/Event Grid
notifications received and processed, and three authorized Exchange audit records.
This is actual tenant/Azure source evidence, separate from controlled fixture results.

The operator sent and moved the new synthetic Outlook test. A failed initial Azure
delivery setup provided a real recovery check: folder delta found the new message
while native delivery was unavailable. After the owner accepted the destination-account
role amendment, Azure reached terminal `Succeeded`. A fresh operator folder move then
delivered native notifications. The live Outlook envelope's explicit PascalCase fields
are covered by regression tests, including conflicting-alias rejection. No AgentTrace
operation sent or moved email.

The new resources are an East US Standard LRS metadata storage account, a Microsoft
Graph partner configuration and its partner topic/event subscription, with scoped
data roles. There is no new cloud compute, hosted database, GPU or premium tier.
Queue TTL is seven days; Event Grid attempts delivery up to 30 times for up to 24
hours, with seven-day dead-letter blob cleanup. The existing evidence account and
Key Vault retain their previous default-deny/no-bypass network configuration.

## Deliberate limits

- This is ingestion/extraction qualification. It establishes no production agent
  detection precision/recall and no AI-content accuracy. Statistical content scoring
  and stronger authenticated evidence/correlation remain later implementation work.
- A native notification, an API send or a candidate delivery-header group does not
  identify an AI agent. All actual observations remain separate from the foundation's
  authored example evaluator. Agent and content work remain independently pending
  until the respective real engines are integrated.
- Graph activity collection is implemented for an explicitly configured eligible
  workspace, but its live destination is absent. It is unavailable, not a passing
  telemetry source. Legacy Office Management feed access remains disabled; approved
  Office 365 Exchange audit is collected through Graph Purview Audit Query.
- Live scope is the enrolled pilot folder in one mailbox. Fixtures cover additional
  enrolled folders and separate delivery copies. No live shared-mailbox or archive
  coverage is claimed. Newly created folders require explicit enrollment.
- Heuristic segmentation/language eligibility can abstain. The 100-word English gate
  is an initial hypothesis for later statistical evaluation, not a demonstrated
  detection threshold. The actual production-normalized input round trip is tested;
  actual model inference and held-out authorship benchmarks remain required later.
- Current-state recovery cannot restore unobserved deleted messages or overwritten
  intermediate versions. Unknown lost-event counts stay unknown. Expired transient
  inputs cannot support exact scoring replay. Retention maintenance must be operated
  as described in the runbook.

Owner approvals for the network exception and delivery-role amendment are retained
in [the acceptance record](evidence/notification-transport-acceptance.json).
