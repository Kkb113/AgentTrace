# Read-only Outlook mailbox synchronization

The standalone runner now supports durable Graph collection for one designated receiving mailbox. It still produces only Unknown previews: positive AI/Human qualification and Outlook category application remain later milestones. No Graph activity-log prerequisite, application server, dashboard, new Azure resource or category permission was introduced.

## Start safely

Use the existing mailbox-scoped certificate reader under the account that owns its Windows certificate. Copy `config/outlook-sync.example.json` to an ignored private directory and replace the fictional tenant/mailbox/client GUIDs, thumbprint and state path with approved values. Never commit this configuration or copy credentials into the example. Use a pre-provisioned encrypted, operator-only local state directory; Windows ACL provisioning and unattended hosting remain deployment-hardening work.

For this workspace the live synthetic-test configuration is already prepared at `work/private/outlook-sync-live/runtime.private.json`. Its two-hour backfill was explicitly selected for the test. Inspect it privately before reusing it; do not substitute another mailbox into its existing database.

```powershell
uv sync --frozen --all-groups
uv run agenttrace-outlook --config work/private/outlook-sync-live/runtime.private.json --check
uv run python scripts/monitor-outlook-mail.py --config work/private/outlook-sync-live/runtime.private.json
```

Ctrl+C closes the database and releases the OS lock. `--once` runs one bounded cycle; it is not a promise that the initial inventory is drained. Run repeated cycles until coverage/backlog counters are current. `--check` never connects to Microsoft or opens state. Fixture mode remains available with `sync_enabled=false`; live collection and fixture import cannot be combined. Apply mode remains blocked before credentials/network/state access.

## What is collected

The receiving-folder hierarchy is discovered recursively, with durable pagination for each child listing. Sent Items, Drafts, Outbox, Deleted Items, their discovered descendants and hidden folders are explicitly excluded. Inbox, Junk and visible custom receiving folders are enrolled. New folders are found on periodic discovery, initially every five minutes. Inventory failures remain visible and prevent claiming full coverage; a folder disappearing during a scan is an explicit gap rather than silent completion. Discovery snapshots are eventually consistent when the hierarchy changes concurrently.

Each receiving folder has its own message-delta continuation/delta link, generation, resynchronization epoch, retry state and schedule position. The initial query has no received-date filter: Microsoft documents a 5,000-message ceiling for filtered message delta. Eligibility is evaluated locally, so there is no page/session population ceiling. The page size and operations-per-cycle settings bound individual requests and work turns, not total coverage. Opaque continuation links are reused unchanged after validating exact Microsoft host, mailbox, folder, route and allowed fields. Credentials are never forwarded to another origin or mailbox. [Message delta semantics](https://learn.microsoft.com/en-us/graph/delta-query-messages).

Incoming metadata is inspected for any sender domain under the existing approved diagnostic boundary. For the current synthetic-only POC, minimum message metadata is read first; only messages received on/after the frozen activation/backfill cutoff and bearing the `AgentTrace synthetic test:` prefix are eligible for header snapshots and decision previews. Subject is used solely to select the authorized test population, never as actor evidence. Ordinary/historical subjects are not stored; their headers, bodies and attachments are not requested. Snapshots contain only selected synthetic sender-evidence metadata and headers. This marker is an operator-controlled collection boundary, not a DLP guarantee or a production sender rule.

By default the eligibility cutoff is the database's original activation time. `backfill_since` explicitly permits at most seven days when first enrolling sync. The chosen boundary is persisted and cannot change on restart; choose a new reviewed test state to change it rather than silently backfilling the mailbox. Older initial inventory remains visible as history and never receives a decision preview. No existing Outlook category or independent test label is used as a prediction feature.

## Crash, move and replay behavior

Schema v2 upgrades the exact validated v1 schema in one transaction and preserves existing activation, observations, work and decisions. A corrupt or modified schema is rejected. The process lock precedes database opening; the persisted lease fences every checkpoint transaction. Signing and Microsoft HTTP requests have timeouts, with lease checks before source work and again before committing it.

A delta page atomically persists its message/folder membership observations, durable detail jobs and continuation checkpoint. A detail GET atomically persists its qualified-population snapshot, observation/work and detail acknowledgement. Discovery pages atomically persist folders, child/delta jobs and pagination. A crash before commit leaves the previous checkpoint; a crash after commit resumes the next work. Generation checks reject an old page response after progress has advanced. Current-state reconciliation is deliberate: Graph pages may repeat items or arrive out of event order, so they enqueue an immutable-ID message GET instead of directly establishing a verdict from a stale page.

All message reads request [immutable IDs](https://learn.microsoft.com/en-us/graph/outlook-immutable-id). A folder tombstone is not treated as global deletion: the mailbox-wide immutable-ID GET resolves the message's current folder. A successful receiving-folder move updates membership without another logical decision when evidence is unchanged. A 404 becomes `gone_or_inaccessible`, supersedes pending annotation previews and records an explicit gap; it does not prove whether mail was deleted or moved beyond readable coverage. Archive/export/reimport and different-mailbox copies remain different identities. Duplicate Internet Message-IDs never collapse received copies.

The semantic fingerprint uses selected sender-evidence metadata and canonical headers, excluding category arrays, read state, folder location and provider change keys. Replaying a category/read-state change acknowledges delta progress without another logical decision or preview. Relevant evidence changes create a new version, even if evidence later returns to a previously seen value. Re-entry from excluded coverage also requires a fresh observation. Actual category writes and write-loop validation against Outlook are deferred to the category-writer phase; this phase tests the incoming echo behavior deterministically.

Scheduling uses a durable monotonic turn counter rather than wall-clock timestamps. Discovery, message pages and detail jobs therefore take turns despite identical timestamps or a large message population. Per-cycle budgets leave unprocessed pages/jobs in SQLite. `sync_ready_jobs`, `sync_pending_items`, `oldest_pending_age_seconds`, `discovery_jobs_pending`, receiving/excluded counts and retry/dead-letter/gap counters make incomplete collection visible.

## Failures and recovery

429, transient HTTP/network errors and Retry-After produce persisted future due times with exponential backoff and positive jitter. The shared transport caps Retry-After parsing at an hour; the new scheduler blocks an hour-or-longer result for operator review instead of retrying earlier than an unknown larger server interval. Finite retry exhaustion becomes a durable dead letter. Authentication/authorization errors, malformed pages and unsafe continuation links block their job without advancing it. Source faults never imply Human.

A message-delta 410 discards only that folder's expired token, advances its resynchronization epoch and performs a full reconciliation. Items absent from the new scan receive current-ID reconciliation. The potentially missed interval stays recorded as `cursor_expired_unobserved_window`; a full scan cannot recover messages that arrived and disappeared during the gap. Expired discovery continuations restart their collection, also retaining a gap. An initial tokenless 410 is blocked rather than reset forever.

After fixing the actual cause, explicitly requeue failed read jobs without deleting the database:

```powershell
uv run agenttrace-outlook --config work/private/outlook-sync-live/runtime.private.json --retry-failed-sync --once
```

Retry alone does not close a gap. A successful checkpoint may close a recoverable outage, while historical gap rows and unobservable windows remain. `sync_health=degraded` and a nonzero one-cycle exit identify unresolved gaps/blocked work. Continuous mode keeps reporting the durable problem so other healthy folders can progress. Never delete state or rewrite a continuation token to manufacture a green result.

General logs contain counts, timings, stage and stable error codes; no subject, address, message/folder ID, complete cursor, headers, token or certificate reference. The final exception boundary suppresses third-party error text and exits unsuccessfully. Raw/snapshot deadlines are seven days and decision deadlines thirty days; automatic physical purge, encrypted backups and unattended supervision remain later gates. Stop the worker before any private database inspection.

## Verification and limits

```powershell
uv run python scripts/export-outlook-contracts.py --check
uv run python scripts/check-outlook-boundaries.py
uv run python -m pytest tests/unit/test_outlook_sync.py tests/unit/test_outlook_runtime.py -q
```

The suite includes 10,023 messages across restart, paged/nested/removed folders, retry/dead-letter handling, expired cursors, incomplete metadata, duplicate Internet IDs, stale responses, category echoes and subprocess crashes before/after all three checkpoint types. Live tests exercise an externally sent Gmail synthetic message through Inbox, the custom synthetic receiving folder, Junk and back to Inbox across separate process launches. Live custom-folder movement validates collection, not automatic mailbox-rule creation; routing into a folder is modeled separately in deterministic tests. No sender accuracy, full audit correlation, production data enrollment or category-display claim follows from synchronization passing.
