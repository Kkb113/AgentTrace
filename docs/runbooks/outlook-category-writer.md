# Scoped category write operations

The current output names are **AI Agent**, **Human** and **Unknown**. Old Human-capable records are readable history; they cannot authorize a new write under the retired rule. Run the detector to obtain a fresh current-rule assessment after the naming migration. The [migration decision](../adr/simple-classification-labels.md) records the owner-UI category replacement and cleanup; no setup app needs recreating.

Use PowerShell under the designated Windows operator profile in `C:\AgentDetection`. The existing category writer certificate and private configuration are required. This is an explicit synthetic-pilot command workflow; the continuous monitor still runs read-only. No new Azure deployment or mail permission is needed.

All operations need a fresh private `--output` filename; reports are never overwritten. Actual IDs, addresses, headers, category inventory and certificates must stay outside Git. Protect the existing private parent directory and state backup. Stop another runtime before accessing its exclusively locked state; do not copy or edit its live WAL files.

## Qualify the actual endpoint

Use only an existing approved non-draft synthetic received message. Qualification sends its categories back unchanged and tests a genuinely stale ETag. It changes provider version metadata but assigns no label. If it fails, investigate the exact reason; do not fabricate a receipt or relax concurrency guards.

```powershell
Set-Location C:\AgentDetection
$syntheticMessageId = '<private immutable synthetic message ID>'
& .venv\Scripts\python.exe scripts\write-outlook-categories.py qualify `
  --settings work\private\outlook-categories\settings.private.json `
  --message-id $syntheticMessageId `
  --output work\private\outlook-categories\endpoint-new.private.json
```

The qualification JSON is itself the private receipt supplied to later commands. Its scope/writer and seven-day maximum validity are checked each time. Requalification never authorizes additional mailboxes or bypasses definition drift.

## Plan, apply and verify

First run the read-only monitor/source collector to obtain a current persisted decision. A detector explanation/evidence change needs reassessment, not an edited JSON label. Plan writes only a local intent; it does not alter Outlook. Omit `--message-id` to enqueue a bounded batch of new current decisions.

```powershell
& .venv\Scripts\python.exe scripts\write-outlook-categories.py plan `
  --settings work\private\outlook-categories\settings.private.json `
  --runtime-config work\private\sender-rules-live\runtime.private.json `
  --message-id $syntheticMessageId `
  --output work\private\outlook-categories\plan-new.private.json
```

Use a returned integer intent ID. Apply performs all current evidence/ownership/version checks and a conditional categories-only update. Verify independently reads the actual endpoint without writing.

```powershell
$intentId = 1 # Replace with an actual ID from your private plan report.
& .venv\Scripts\python.exe scripts\write-outlook-categories.py apply `
  --settings work\private\outlook-categories\settings.private.json `
  --runtime-config work\private\sender-rules-live\runtime.private.json `
  --qualification work\private\outlook-categories\endpoint-new.private.json `
  --intent-id $intentId --output work\private\outlook-categories\apply-new.private.json

& .venv\Scripts\python.exe scripts\write-outlook-categories.py verify `
  --settings work\private\outlook-categories\settings.private.json `
  --runtime-config work\private\sender-rules-live\runtime.private.json `
  --qualification work\private\outlook-categories\endpoint-new.private.json `
  --intent-id $intentId --output work\private\outlook-categories\verify-new.private.json
```

Repeated `apply` on a completed intent makes no additional PATCH. Read the status and attribution flags; `reconciled` means the result is present but write origin is uncertain. It is not a confirmed AgentTrace-owned mutation. `verify` can show stale evidence or a later user change even after a historically confirmed apply. The owner-approved meaning of Human includes browser-controlled agents; a green category is not forensic proof of a person.

## Retry, status and rollback

Use the same arguments as `apply`, changing the operation to `status`, `retry` or `rollback` and choosing a new output filename. Status is local and needs no qualification. Pending work observes bounded backoff. Repeating `apply` after its due time resumes work, including uncertain-outcome readback. `retry` explicitly resets a failed/unfinished intent's attempt budget after its cause is fixed; it retains receipts and all guards. It cannot revive an obsolete decision or override a later user edit. Do not use ad hoc SQL to reset a status.

`rollback` requires an attributed, confirmed addition and no later provider-version change. It removes only that addition, never user categories or prior label history. If anyone edited the email afterward, expect `rollback_blocked`; there is no force mode. An existing desired category (`unchanged`) or uncertain-attribution result (`reconciled`) has no removable ownership. A rolled-back intent stays terminal. Replacing a rule/source outcome must go through the detector and a new decision version.

Exit 0 means the command completed or its requested operation reached a finished state; always inspect the returned status/verification fields. Exit 1 reports unfinished/blocked/superseded application. Exit 2 reports invalid input or an unavailable command boundary. Exit 130 is an operator interruption; inspect the durable intent before any retry. Do not equate a successful classification, CLI exit code or a stored historical status with a freshly verified mailbox write.

## Recovery and limits

Schema version 5 migrates the existing runtime transactionally. Back up private state using SQLite's backup API under the runtime lock before a deployment; preserve the ownership registry separately. Older code rejects the new schema rather than performing an unsafe downgrade. A consistent pre-migration backup is required for code/state downgrade; never delete the journal to hide uncertain writes. The later deployment phase qualifies full backup/restore, retention enforcement and certificate rotation.

A crash after prepare or a timeout after send leaves uncertain work. Restart with the same state and inspect/apply the same intent; a new state directory loses mutation ownership. If a later edit or an excluded/deleted location prevents safe confirmation, keep the unresolved record and investigate. Permission/source failures must never become applied status. An expired qualification can be renewed using the same narrow no-op test; an unexpected grant, scope or definition requires correction and review.

The live acceptance used existing synthetic messages and an isolated no-audit copy to exercise Unknown; it did not disable the normal audit collector. Existing unrelated category definitions were used as deliberate concurrent user controls on two synthetic items and preserved. No ordinary message, email body, recipient, read state, folder, send setting or category definition was modified by the writer. Outlook visual display and unattended operation are subsequent gates, not demonstrated by server readback alone.
