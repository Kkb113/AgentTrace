# Outlook runtime foundation

The standalone runner is installable and runs without the historical web/API/content workers, Docker, Azure resources or mailbox credentials. Fixture mode validates configuration and processes **synthetic metadata fixtures** into durable **Unknown previews**. The [mailbox synchronization mode](outlook-mailbox-sync.md) now adds durable read-only Graph collection. Neither mode enables qualified AI Agent/Human rules or applies Outlook categories. The existing experimental terminal demo remains unchanged.

## Prepare and run

From the repository in PowerShell, use a new ignored directory:

```powershell
uv sync --frozen --all-groups
uv run python scripts/prepare-outlook-dry-run.py --directory work/outlook-dry-run
uv run agenttrace-outlook --config work/outlook-dry-run/runtime.json --check
uv run python scripts/monitor-outlook-mail.py --config work/outlook-dry-run/runtime.json --fixture work/outlook-dry-run/observations.json --once
```

Remove `--once` to keep processing until Ctrl+C. The installed `agenttrace-outlook` command and script invoke the same code. Replaying the same fixture creates no additional logical decision or preview. Configuration validation with `--check` opens neither state nor network. The preparation command refuses to overwrite an existing directory; choose a fresh one. Fixtures expire seven days after their observation time.

Output is newline-delimited JSON. `ready` states whether collection is disabled or uses read-only delta, and that actor rules remain unqualified. `cycle_completed` reports work counts and preview counts. A decision and its annotation preview are distinct records; **preview never means applied**. No record can be marked applied in this schema. Positive category contracts exist for later use, but no positive rule is enrolled. All fixture observations, including those marked fully inspected, remain Unknown with `sender_rules_not_qualified`.

## Configuration and safety

`config/outlook-runtime.example.json` is a template with fictional GUIDs and an intentionally invalid path placeholder. The preparation command creates an executable fictional configuration. Runtime configuration is separate from the frozen product baseline. Unknown fields, demo flags, positive-rule overrides, invalid category colors, unsafe paths and invalid lease timing fail validation. All fields are strict; string booleans and implicit number conversions are rejected.

The scope is a tenant UUID and mailbox UUID, not a display name or arbitrary URL. A state directory is permanently bound to that scope and schema. Do not repoint a state database to another mailbox. Optional reader credentials are certificate references, never secrets; startup/fixture processing does not instantiate an authentication provider. The reviewed adapter exposes fixed-mailbox metadata/header, folder and delta GET routes with immutable IDs, URL-encoded message IDs and strictly validated continuation links. Fixture startup remains offline; live collection is explicitly configured separately.

`--apply-categories` and configured `apply_categories` fail before state, credentials or network are opened. `--dry-run` can explicitly reduce configured apply mode to dry-run. No flag enables category application. Experimental decisions, stale decisions, mismatched scopes, unrecognized rules and asserted-but-unenrolled positive qualifications fail the pure annotation admission interface. The demo module is not imported. No new OAuth scopes, grants, Outlook changes or Azure resources are required.

## State and recovery

Use one worker on one host and a private local disk. SQLite uses WAL, FULL synchronization, foreign keys and explicit immediate transactions. An OS file lock is acquired **before opening SQLite**, held until the connection closes, and released by the OS after a crash. A durable owner/generation/expiry lease additionally fences stale operations. A competing worker fails visibly; after a crash a new owner increments the generation without waiting for the obsolete lease. An expired live lease stops processing rather than extending ownership silently.

The migrations atomically create the base schema and upgrade it to schema v2, recording/preserving the activation time and existing work. Restart verifies exact schema structure, digest and mailbox binding; unknown versions, drift or corrupt databases fail closed. Future schema upgrades require explicit migration code and tests. Do not manually edit the database or open a second connection while the runtime is running. Status queries go through the same lock and lease as processing.

Observation identity is mailbox scope + immutable message reference + source version. A repeated version with identical semantic metadata is idempotent; conflicting metadata aborts the whole batch. Re-observing does not extend the original expiry. Older observations are rejected. New versions supersede old queued work and previews immediately. Decision version allocation, decision insertion, preview insertion and work acknowledgement commit together. Failure rolls back all four; retry cannot create an orphan preview or acknowledge lost work. Transient processing failures have capped retries and dead-letter accounting; state/fence failures stop the process. Live mode adds Graph backoff, folder checkpoints and source reconciliation as described in the synchronization runbook.

Raw-observation and decision expiry deadlines are seven and thirty days from the original observation respectively. Expired observations cannot produce new decisions. Physical purge, encrypted backup/restore, host ACL provisioning and unattended supervision remain deployment-hardening work; this foundation does not claim to implement them. SQLite is not encrypted. On Windows the state directory inherits ACLs, so use a pre-provisioned operator-only encrypted directory. POSIX creation uses private modes. Symlink/junction and hard-linked state aliases are rejected. Mapped network drives must not be used.

SQLite 3.53.1 was tested locally. The upstream [WAL-reset bug](https://sqlite.org/wal.html#walreset) affects older versions and was fixed in 3.51.3 (also 3.44.6 and 3.50.7). This design excludes the documented simultaneous-connection race by locking before opening its sole connection. Require a patched SQLite build before extending this architecture to concurrent independent connections. Do not bypass the process lock with a separate database viewer.

## Failure handling and verification

General logs contain stable error codes, aggregate counts and timestamps; no body, subject, addresses, message IDs, full headers, certificate references or tokens. Input/driver exception text is suppressed. A failed migration, disk error or lost lease produces a nonzero exit, never a Human inference. Ctrl+C closes state and releases ownership. Investigation requiring private database access must occur after stopping the process; do not delete a corrupt database to make a failed run appear healthy.

```powershell
uv run python scripts/export-outlook-contracts.py --check
uv run python scripts/check-outlook-boundaries.py
uv run python -m pytest tests/unit/test_outlook_runtime.py -q
```

The boundary gate checks the new package's import/network surface, and a negative control proves demo imports and non-GET requests are rejected. Contract schemas are generated independently of the historical API schemas. Runtime validators additionally enforce cross-field chronology, eligibility and retention rules that JSON Schema alone cannot express. Tests exercise subprocess crashes before migration commit, after observation commit, before work commit and after decision commit, plus restart/deduplication, multiple processes, stale fencing, failure injection, safe errors and zero-network dry-runs.
