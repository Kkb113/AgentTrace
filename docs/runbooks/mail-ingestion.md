# Mail ingestion operations

Use the protected synthetic configuration under `work/private/mail-ingestion`.
Do not copy it, tokens, certificates, actual source IDs or message bodies into issues,
CI artifacts, commits or chat. `scripts/protect-local-access.ps1` applies the private
directory ACL. Live test messages are prepared outside AgentTrace by the operator.

## Start and inspect

1. Run `uv sync --frozen --all-groups` and `python scripts/dev-services.py start`.
2. Ensure the enrolled synthetic folder exists. Its messages must start with
   `AgentTrace synthetic test:`. New folders require explicit enrollment.
3. Existing live setup: `python -m agenttrace_ingestion.cli watch --configuration
   work/private/mail-ingestion/runtime.private.json`. Run this as a supervised local
   process. `--iterations 1` performs one bounded cycle; Ctrl+C stops it. The loop
   renews subscriptions, receives metadata events, reconciles each enrolled folder
   and processes at most 100 inbox items per cycle. It has no email-write operation.
4. `python -m agenttrace_ingestion.cli health --configuration
   work/private/mail-ingestion/runtime.private.json` displays operator health locally.
   For authenticated API access, instantiate `agenttrace_ingestion.api.create_app`
   with the API database identity, authorization policy and Entra validator. Enroll
   each source reference to its owning mailbox in the server policy. Run Uvicorn on
   loopback with access logs disabled; notification validation tokens must not be
   captured by reverse-proxy access logs.
5. Advance the separate audit source with `python scripts/collect-audit-evidence.py`.
   Repeat after the indicated next-attempt time while the asynchronous read query is
   pending. Unconfigured activity sources remain unavailable. This helper uses the
   separate audit certificate, never the mailbox collector's Graph identity.

## Fresh environment

First establish the approved mailbox/Azure access baseline. Compile infrastructure
with `python scripts/validate-infrastructure.py`. Run
`python scripts/configure-notification-transport.py` for its guarded what-if; apply
only the accepted dedicated transport with `--apply`. Existing shared partner
configurations require preservation and an owner review; this script refuses to
overwrite them. The Graph partner authorization expires after one day.

Read-only folder discovery must save the selected folder IDs in the private
`pilot-folders.private.json`. `scripts/prepare-ingestion-sandbox.py` creates protected
local encryption/content keys and preserves an existing configuration. Enroll using
`python -m agenttrace_ingestion.cli enroll --configuration <private-config>` under the
local migration owner, create the subscription with `subscribe`, and connect its exact
Graph-created partner topic with `python scripts/connect-notification-delivery.py`.
These setup operations create only detection transport resources and subscription
metadata. The partner-topic-specific REST API is required for managed-identity delivery.

## Outages, dead letters and replay

- A retryable Microsoft error preserves the cursor and schedules the next attempt;
  honor `Retry-After`. Authentication gets one refresh. Persistent 403 requires an
  administrator to inspect effective access, not a new broad grant or policy bypass.
- A missed/removed/expired subscription degrades health. `renew` or the watch loop
  renews/recreates it and delta reconciliation recovers observable current state.
  Inspect and retain the historical gap even after current-state recovery.
- Delta expiry resets just the affected folder. If a folder is no longer authorized,
  re-enrollment requires explicit scope review. Archive moves can change immutable IDs.
- Inbox poison is visible in health. After fixing its source/access issue, use
  `replay --event-ref <exact-ref> --configuration <private-config>`. Expired ciphertext
  cannot be replayed. Corrupt encrypted events are durably poisoned rather than retried
  indefinitely. Reconciliation is still required.
- Invalid native notifications remain unacknowledged initially. After five dequeues,
  persist a keyed payload fingerprint and safe reason, mark the gap unrecoverable,
  then delete the receipt. Invalid raw payloads are not retained or trusted for replay.
  Reconcile authorized messages; do not republish forged data. Event Grid delivery
  failures use its separate seven-day dead-letter blob container, 30 attempts and
  24-hour event delivery TTL. Queue messages have seven-day TTL.
- After content input expires, preserve the version metadata but do not claim exact
  model re-execution. Later inference integration must recollect the authorized current
  version or use an approved retained test snapshot; it must not score a different version.

## Retention and validation

Run `purge --configuration <private-config>` under the local migration owner as
regular maintenance. It removes expired capsules, seven-day inbox/audit/transport
poison records, thirty-day versions/dependent work, stale orphan copy locators and gaps.
Optional snapshot retention is handled by `SnapshotStore.purge`; snapshots are off in
the live configuration. No cleanup command removes a source app, mailbox or cloud
resource. Native transport retirement is a separately reviewed operation.

Run `python scripts/verify-foundation.py` for all five local gates. Targeted recovery
tests are in `tests/integration/test_mail_ingestion.py`; real role tests in
`test_ingestion_access.py`; audit tests in `test_audit_ingestion.py`. The native queue
test verifies persistence occurs before receipt deletion. Review the extraction
contract tests before changing segmentation, language or length thresholds.
