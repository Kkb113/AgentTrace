# Scoped Outlook category writer

Phase 6 implements explicit synthetic-pilot apply, verify, retry and rollback commands. The existing reader and detector remain separate. The native labels are **AI Agent** (red), **Human-capable** (green) and **Unknown** (yellow), with the meanings already approved in the sender policy. No sending capability, content detector, application UI, permission expansion or new Azure resource was added.

## Write boundary

The dedicated Phase 5 writer still has exactly one mailbox scope. Code uses a fixed Graph mailbox/message route and a PATCH body containing only `categories`. GETs select the current header evidence, categories, receiving folder, read state and provider version; PATCH responses select only ID, change key and categories. The underlying Microsoft permission remains broader than these code guards. Credentials never enter the decision state or routine output.

Before a new write, the worker verifies the owned master IDs/names/colors, current decision and observation versions, qualification, expiry, exact evidence references/reasons, receiving-folder eligibility and the current message's canonical sender-evidence digest. Experimental decisions and missing/stale/conflicting support cannot become successful positive writes. A changed decision requires reassessment and a new intent. Category/read-state/provider-version changes are excluded from the sender-evidence hash; changing labels alone does not produce another classification.

An endpoint qualification receipt pins the mailbox, writer identity, route and a validity window of at most seven days. `qualify` performs an unchanged-array conditional update, confirms a new provider version, then requires an actual stale-version `412` rejection and unchanged categories. A local rejection, 404, fabricated ETag or documentation assumption does not qualify the endpoint. Unsupported, expired or mismatched qualification blocks writes. The receipt is protected operator configuration, not a Microsoft-signed attestation.

Microsoft documents [categories as an updatable message property](https://learn.microsoft.com/en-us/graph/api/message-update) and [message delta changes](https://learn.microsoft.com/en-us/graph/api/message-delta). Live testing, rather than assuming every Graph endpoint implements identical preconditions, established the conditional behavior used here.

## Durable intent and failure handling

Runtime schema version 5 adds `category_intents` and `category_attempts` in the existing SQLite database. Its transactional migration verifies the previous schema/scope and preserves existing synchronization/evidence/decision data. Process locking and fenced transactions serialize this single-host worker; it is not a distributed multi-host writer.

Planning atomically binds a unique intent to a persisted decision. General planning skips existing intents so older entries cannot starve new decisions; an explicit message plan returns its existing intent for idempotency. Before network IO, an attempt commits the exact before/after category arrays, ETag and evidence digest. Category mutation status is separate from the classification. Lease and evidence freshness are rechecked before sending.

The merge preserves every unrelated category name and leaves at most one owned label. The conditional PATCH uses the ETag from the inspected message. A definitive `412` schedules a bounded retry that reads again, revalidates evidence and merges current user categories. It never blindly replays an old array after a conflict. A new message version, category-definition drift, excluded/missing item, wrong credentials or unsupported decision blocks application. Explicit `retry` retains all receipts and repeats these checks; it does not bypass a protection.

Readback checks the resulting categories, evidence digest and location. A matching response ETag plus readback establishes an attributed apply. A crash/timeout after a possible write is uncertain. Recovery reads before doing anything else: a still-current unchanged pre-write version can be retried conditionally; a correct observed result without a response receipt becomes `reconciled`, not an attributed write. Any incompatible later edit blocks automatic recovery. A persisted response receipt permits confirmation after a readback interruption. None of these states rewrites the detector's verdict or claims success from a failed source.

| Status | Meaning |
| --- | --- |
| pending / prepared / uncertain | Work remains; no successful apply may be claimed |
| applied | Response/version and readback confirmed the apply at that time |
| unchanged | Desired category was already present; no PATCH and no added-label ownership |
| reconciled | Desired result observed after uncertain IO; origin is unproven and rollback is unavailable |
| blocked / superseded | Failed guard, exhausted retries or replaced decision; investigate/reassess |
| rollback_pending / rollback_blocked | Cleanup remains unfinished or could not be proved safe |
| rolled_back | Absence of the added label verified; inspect `rollback_attributed` for response attribution |

Status describes the recorded operation, not a promise that users cannot subsequently edit the email. `verify` separately reports current category presence and current classification evidence. `write_attributed` and `rollback_attributed` distinguish confirmed receipts from presence-only reconciliation.

## Conservative rollback

Rollback requires an attributed apply that actually added its label. It removes only that owned addition and preserves unrelated categories. It does not restore earlier owned labels. If the message/provider version changed after confirmation, rollback refuses to act, including when an unrelated category, read state or the same label was removed/re-added. This protects later user intent when email metadata cannot establish continuous ownership. A conflict during rollback is rechecked, not forced. Existing/reconciled labels are never adopted for removal.

Rollback is terminal for that intent; repeated apply/rollback does not recreate the label. A material new decision can create another intent. There is no force-rollback or arbitrary category-edit option. Master definitions and email content are never deleted by this worker.

## Executed evidence and review

The [executed record](evidence/category-writer-validation.json) maps all five exits to software and live evidence. Actual synthetic tests verified Unknown with the audit connector absent in an isolated copy of real header state, authenticated Claude AI Agent, and manual Human-capable application. The normal runtime's audit records were preserved. The real endpoint rejected a concurrent-edit stale PATCH; retry retained the unrelated category. Attributed rollback removed only the added label, later-edit rollback was blocked, duplicate apply left the provider version unchanged, and category-only synchronization produced no extra decisions. Headers and read state were unchanged. Unrelated-category control edits were confined to two synthetic messages and deliberately preserved.

Continuous testing caught a stale-explanation scheduling gap: non-enrolled senders were not reassessed when the two-hour and twenty-four-hour evidence-window explanations changed. The writer correctly refused the stale decision. The scheduler now reassesses each crossed boundary once, without a message edit or relaxed eligibility checks. Regression tests cover this fix, conflicts, missing/deleted/moved messages, crashes before/after writes, ambiguous timeouts, response/readback interruption, Unknown, drift, scope, retry limits and later user changes.

Review also checked fixed routes/payloads, metadata-only responses, schema migration/downgrade rejection, atomic preparation, credential separation, source binding, lease fencing, exact rollback ownership and sanitized interruptions. Local/hosted quality, privacy, secrets, dependency, infrastructure, guard and integration checks validate the candidate revision. Authored fault tests are software controls; they do not establish population detection accuracy.

Explicit pilot writes are implemented. The monitor's `--apply-categories` path, unattended write scheduling and automatic activation remain disabled. Phase 7 qualifies supervised operation; Phase 8 verifies the Outlook client display; Phase 9 gates the continuous pilot. The frozen Phase 0 baseline verifier remains a historical requirement/archive check, not a claim that these explicit commands do not exist. See the [writer runbook](runbooks/outlook-category-writer.md).
