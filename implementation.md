# AgentTrace implementation plan

- **Workspace:** C:\AgentDetection
- **Repository:** [Kkb113/AgentTrace](https://github.com/Kkb113/AgentTrace)
- **Revision:** 30 October 2026 — Outlook-native production POC.
- **Deliverable:** A new, maintainable Python monitor that classifies received email and applies native Outlook color categories.
- **Outlook categories:** **AI Agent** (red), **Human-capable** (green), **Unknown** (yellow).
- **Scope:** Sender/action detection only; no AI-written-text detection.
- **Interface:** Outlook itself, plus a terminal and local operational reports. No standalone application, web dashboard, custom backend API, Office.js add-in or custom icon framework.
- **Deployment:** One designated Microsoft 365 mailbox, one supervised worker on a suitable always-on Windows host initially. Outlook can be closed; the monitor host must remain available.
- **Azure constraint:** No new cloud resource is required initially. Any justified new Azure resource must use kb-agentdemo, an explicit subscription and the smallest suitable configuration.
- **Roadmap:** Ten phases, Phase 0 through Phase 9. This replaces the previous fifteen-phase application roadmap.
- **Change record:** [Outlook-native categorization decision](docs/adr/outlook-native-categorization.md).

## What has changed and what is already proven

The owner now wants the successful terminal demonstration refined into a reliable Outlook component, with three native categories and no separate application. This authorizes planning category annotation as the one permitted mailbox mutation. It does not mean that category-write permissions have already been granted or that category updates have been implemented.

Preserve the existing demo, its command and its tests. The demo intentionally uses a binary experimental rule: the Office365 MCP declaration or Gmail API trace produces an AI label; other messages produce a human label. The latest targeted suite passed 51 tests and 65 subtests, and an existing Outlook capture reproduced the declaration match. These are engineering/demo results, not a measured production false-positive rate.

The production monitor must be a separate entry point with **AI Agent / Human-capable / Unknown** decisions. The latest owner policy classifies fully inspected normal-client-compatible mail as Human-capable, including a browser controlled by either a person or an agent, independently of text origin. Incomplete inspection, unavailable headers, observed automation clues and conflicts remain Unknown. Existing demo shortcuts and results are not production qualification.

A [recorded authenticated Claude test](docs/evidence/agent-audit-fallback-validation.json) separately demonstrated the narrow enrolled Microsoft 365 connector route using successful Exchange Send audit evidence and a unique scoped message link. Reuse its verified collection/rule components where appropriate. It is not universal Claude attribution, and sender-to-received-copy linkage still needs its own collision and transformation tests. Graph activity-log delivery remains unqualified and must not be a hidden prerequisite.

Earlier repository Phases 0–4 and their reports remain historical evidence under the previous baseline. The **new phase numbering below is a replanned delivery sequence**, not a claim that the first five phases of this sequence are already complete. Existing incomplete evaluation work and legacy v1 contracts must be preserved; migrate only what the new monitor actually needs.

The owner-approved [Human-capable and corroborated-indicator revision](docs/adr/human-capable-classification.md) supersedes the earlier Human/controller and independent receipt-identity requirements for this POC. Historical Phase 0 reports remain records of their prior baseline.

## 1. Product contract and coverage

The current POC detects corroborated AI-agent submission indicators and normal-client compatibility. An enrolled agent tool sending after human approval is an AI-agent case; manually sending an AI-written draft is Human-capable when inspection shows no automation indicators. An agent controlling a normal browser/client also falls under Human-capable by the owner's explicit policy. These labels do not establish a biological controller or independent forensic item identity.

| Outlook category | Color / Graph preset | Production meaning |
| --- | --- | --- |
| AI Agent | Red / preset0 | The qualified POC rule corroborates the known MCP marker with authenticated enrolled Send evidence, current publisher and unique matching provider-copy context; accepted residual replacement risk remains |
| Human-capable | Green / preset4 | Complete supported-field inspection is compatible with a normal client, including a human-controlled or agent-controlled browser; no observed automation indicators or conflicts. This does not prove the controller |
| Unknown | Yellow / preset3 | Required inspection or AI corroboration is missing, conflicting, failed or outside coverage; includes known conventional automation. Healthy pending audit checks do not establish a controller |

Pending source evidence is an internal state/reason within Unknown, not a fourth Outlook category. A database/source failure is an operational failure, not evidence of either actor. If an initial message cannot be read or a category write fails, report it as unprocessed/apply-pending; do not claim that Unknown was successfully applied.

Use native Outlook categories rather than custom icons or an add-in. The category name remains readable without color, and the worker applies names from the mailbox's master category list. Actual shades and placement vary by Outlook client; test the web and new Windows clients rather than promising identical rendering. [Microsoft category model and colors](https://learn.microsoft.com/en-us/graph/api/resources/outlookcategory?view=graph-rest-1.0).

Default visible names are AI Agent, Human-capable and Unknown. Provision them only when absent or explicitly enrolled as AgentTrace-owned. If those names already belong to the user, stop setup with a conflict; use an explicitly configured namespaced alternative rather than silently adopting, recoloring or deleting user categories. Record category IDs, names, presets and ownership in private configuration.

Record annotation lifetime explicitly. Start with the thirty-day decision window: expire or remove the unchanged service-owned label when its supporting decision expires, unless a separately accepted annotation policy permits a longer lifetime. Do not silently retain authoritative-looking native labels forever after deleting their evidence. Failed expiry cleanup is a visible operational backlog; it must not reset the original retention deadline.

### Receiving coverage

- Initial production POC: incoming mail to the designated Exchange Online mailbox from any sender domain, including **Gmail → Outlook** and **Outlook → Outlook**.
- Monitor the enrolled receiving folders, including rule-routed folders/Junk when readable; discover new folders and report exclusions. Sent Items, Drafts and Outbox are outside incoming coverage.
- Outlook → Gmail and Gmail → Gmail receiving integration is deferred. Those routes require a Gmail-receiving component and are not needed for this Outlook-native release.
- External sender evidence can remain unavailable even though the email is readable. Connecting the receiving Outlook mailbox does not grant access to Gmail send logs or another Microsoft tenant's audit records.
- Start with new arrivals from a recorded activation point. Historical backfill is an explicit bounded operator operation, never an unannounced rewrite of the whole mailbox.
- Sender categories are observations under the enrolled sources' trust assumptions. They do not certify a biological human or detect every browser-controlled agent.

### Features excluded from this release

No frontend, custom application UI, public backend API, custom Outlook extension, full Gmail mailbox integration, AI-content scorer, LLM, GPU, email composition/sending/replying/forwarding, draft creation, approval management, source-agent execution, mailbox routing/quarantine or body/subject modification. Native category annotation is the only new mail-write feature.

## 2. Production detection policy

| Input or observation | Allowed production treatment |
| --- | --- |
| Known MCP declaration corroborated by authenticated enrolled Claude Send, scope/time/Message-ID, current publisher and unique observed copies | AI Agent under the approved indicator-based POC rule; residual replacement risk disclosed |
| x-ai-generated: mcp-office365 alone | Retain as an agent-origin declaration/hint; Unknown until a rule qualifies its trust and execution link |
| Received trace containing gmailapi.google.com and HTTPREST alone | API-submission hint; Unknown because ordinary applications can use the same API |
| Complete supported-field inspection with no observed MCP/API/other automation indicators or conflicts | Human-capable; includes a human- or agent-controlled normal browser/client |
| Missing/unavailable header inspection, source failure or merely absent audit records | Unknown; absence caused by collection failure cannot imply Human |
| Ordinary Outlook/Gmail session, client header, SPF/DKIM/DMARC pass or sender certificate alone | Context, not send-executor proof |
| Normal-client/browser-compatible evidence | Human-capable with compatibility basis; no human-controller identity assertion |
| Non-AI script, alert, rule or auto-reply | Unknown, with conventional-automation context in the decision record |
| Agent draft manually sent in a normal client, without observed automation indicators | Human-capable; text origin does not establish send execution |
| Conflicting executors, duplicate/forged IDs, revoked issuer or incomplete source pages | Unknown with explicit reasons |

The Office365 declaration is useful and remains supported as evidence; it cannot become a universal authenticated detector just because the demo matched it. A domain signature alone does not establish that a particular AI workflow created a header. Qualify any stronger declaration route with independently verified source semantics, tamper protection and actual negative tests before enabling a positive category.

The owner revised the active Human policy to **Human-capable**: normal-client/browser-compatible sending is accepted whether a human or an agent controls the client. Complete inspection without automation indicators may produce this bounded compatibility label; it does not establish a human controller. Browser-agent indistinguishability is therefore a supported policy case, not a blocker. Failures, incomplete inspection, known automation and conflicts remain Unknown. See the [accepted policy revision](docs/adr/human-capable-classification.md).

For the POC AI lane, the owner explicitly accepted the known MCP declaration corroborated by an authenticated enrolled Claude Send event, current publisher pin, matching tenant/mailbox/Message-ID/time and a unique observed copy pair. This is a corroborated-indicator rule; it does not claim an independent forensic received-item ID link. Declaration-only and generic-API-only cases remain Unknown. Observable collisions/conflicts are rejected; a carefully forged replacement that leaves no observable difference remains an accepted residual POC risk. No statistical accuracy claim is implied.

Keep the following distinct: independent test ground truth, vendor/source observations, hints, correlation candidates and qualified verdicts. Do not feed operator A/B labels, test subjects, filenames or existing Outlook categories back into prediction. Approximate subject/time/body similarity is not a verified join. Internet Message-ID and provider-local immutable IDs are not interchangeable or universally unique.

## 3. Small implementation and operational design

The separate runner is scripts/monitor-outlook-mail.py (also installed as agenttrace-outlook), backed by src/agenttrace_outlook/. Phase 1 implements validated synthetic fixture replay and durable Unknown previews; Phase 2 adds read-only mailbox synchronization; qualified actor rules and category writes remain later deliverables. See the [runtime runbook](docs/runbooks/outlook-runtime.md). Keep modules focused on configuration, authentication, mailbox synchronization, header parsing, evidence adapters, decisions, durable state, category updates and process supervision. Reuse the existing transport/authentication/audit code only after reviewing its production assumptions; do not copy the entire demo loop into a new filename.

| Area | Minimal design |
| --- | --- |
| Runtime | Pinned Python dependencies, typed configuration and strict decision records; no new web server |
| Reader | Existing mailbox-scoped read identity and metadata/header-only Graph reads |
| Audit | Existing separate authorized audit reader; bounded message/actor/time queries and asynchronous reassessment |
| Verdict | Versioned AI Agent / Human-capable / Unknown with reason codes, evidence references, source freshness and qualification |
| State | SQLite transactions/WAL on an encrypted, ACL-protected local disk for one host/worker; use the existing isolated PostgreSQL only if an actual deployment need justifies it |
| Checkpoints | Durable per-mailbox/per-folder delta cursors, pending-page state, deduplication and activation/backfill boundary |
| Work | Transactional decision plus category-write intent, bounded retries and separate observed/decided/apply-pending/applied/dead-letter states |
| Writer | Separate mailbox-scoped credential/process boundary, fixed Graph routes and categories-only PATCH payloads |
| Operation | Terminal status, sanitized structured logs, local health/diagnostic commands and small operational reports |
| Supervision | Built-in Windows Task Scheduler/startup supervision under a dedicated least-privilege account, with restart-on-failure, single-instance locking and graceful shutdown |
| Validation | Existing pytest/security/contract tooling, real Graph read/write tests on synthetic fixtures and actual Outlook category visibility checks |

Avoid concurrent writers to the same mailbox/message. A single-instance lease plus per-message serialization is required even with process restarts. SQLite is a local single-host store, not a shared/network database; do not place it on an ephemeral cloud filesystem or assume WAL provides encryption.

### Collection and recovery

Use Graph's folder-scoped delta synchronization, not repeated session-wide listing until a 10,000-message limit. Persist each page's observations and next cursor atomically; do not advance the checkpoint before durable work is recorded. Enumerate the folder hierarchy and maintain individual cursors. Request immutable IDs consistently, track same-mailbox moves and distinguish deletion from a move; archive/export/reimport boundaries remain explicit. [Message delta](https://learn.microsoft.com/en-us/graph/delta-query-messages), [immutable IDs](https://learn.microsoft.com/en-us/graph/outlook-immutable-id).

Default to economical scheduled delta polling, initially evaluate 30 seconds for receiving folders and five minutes for pending audit checks. These are tuning assumptions, not source-delivery guarantees. Reuse existing approved notification infrastructure only if lower latency is required; notifications never replace reconciliation. Persist pagination across cycles, bound each cycle's work fairly, honor Retry-After, apply jitter/backoff and expose backlog age. Invalid cursors trigger a recorded scoped resynchronization rather than silent loss.

Initial synchronization may enumerate older metadata, but only the activation/backfill population is eligible for category changes. No fixed page cap may silently discard observable work. Process missing/deleted/protected items as explicit gaps, and leave unsupported folders visible in coverage.

### Decisions and late evidence

Persist the decision/rule/source version and exact evidence references before writing. Record source-event, observation, decision and category-confirmation times separately. Unknown may later become AI Agent or Human-capable when sufficient evidence arrives; invalidated positive evidence can downgrade a result. Do not use the demo's two-hour timeout as proof of a human sender. Retain a configurable pending window and late reassessment protocol; record the initial and final result for measurement.

Only a qualified, versioned production decision can enter the live category outbox. Experimental demo verdicts and legacy no-agent-observed negatives must be rejected by the writer. Legacy records can remain historical; no full migration of obsolete content APIs/workers is required to ship this small monitor.

### Safe Outlook category updates

1. Provision or manually create the three approved master categories once, recording identity/color/name ownership. Avoid carrying category-provisioning permissions in the routine process.
2. Read the current message categories and version, then calculate the desired set as: existing categories excluding **only enrolled AgentTrace categories**, plus the current target category. Preserve every unrelated category.
3. Validate optimistic concurrency for the actual message endpoint: test ETag/If-Match behavior, require stale writes to be rejected, re-read/re-merge on conflict and cap retries. A local lock alone cannot protect against a user editing categories concurrently. If the endpoint/path cannot supply a validated safe update strategy, block automatic write enablement rather than promise preservation.
4. Send only the categories property to the exact allowlisted mailbox/message endpoint. Never send body, subject, recipients, flags or read-state fields. Skip the PATCH when the desired set already matches.
5. Confirm the resulting categories with a read before marking the outbox intent applied. A timeout after the server wrote must be recovered by reading and deduplicating, not by assuming failure or success.
6. Category changes can appear in subsequent delta results. Exclude service-owned display/category changes from actor features and decision triggers; acknowledge their delta state without causing write loops.
7. Track before/after sets, decision version and the last applied owned label for recovery. User changes are not actor evidence. Unexpected changes to owned category definitions or manually edited managed labels become a drift/conflict state with an explicit operator reconciliation policy.
8. Rollback removes only categories this service can establish it applied, preserves later unrelated user changes and never deletes mail or blindly restores an old full category array. Rollback/cleanup of master categories is a separate exact-scope operation.

The Graph update API supports the categories property and requires Mail.ReadWrite. It does not provide a categories-only OAuth permission. The writer's credential therefore has broader technical capability than its allowed code path; document that residual privilege and test the guard. [Message category updates](https://learn.microsoft.com/en-us/graph/api/message-update?view=graph-rest-1.0).

### Identity and category provisioning

- Keep the collector read-only and the audit reader separate. Do not convert an existing collector into a general mail editor.
- Use a dedicated category writer with Application Mail.ReadWrite restricted to the exact mailbox through supported Exchange application RBAC. Do not grant Mail.Send, full-access roles or advanced content-write privileges.
- Avoid additive unscoped Entra grants that defeat mailbox RBAC. Verify effective access with real allowed and denied calls; an assignment simulator alone is insufficient. [Exchange application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).
- Master-category creation through Graph needs MailboxSettings.ReadWrite. Prefer owner/manual creation or a temporary separate setup identity; the runtime writer does not need that ongoing scope merely to assign known category names. Any temporary setup grant needs an exact retirement plan. [Create master categories](https://learn.microsoft.com/en-us/graph/api/outlookuser-post-mastercategories?view=graph-rest-1.0).
- Before any new app/grant, prepare the concrete identity, mailbox filter, operations and residual-permission proposal. The feature request establishes category-annotation intent; existing read-only grants do not magically permit writes.
- Default to dry-run. Actual category-write rollout begins only after the scoped grant, category ownership and concurrency checks pass.
- Use non-exportable certificates under the actual scheduled-task runtime account and test access while the interactive operator is signed out. Existing CurrentUser certificates are not automatically accessible to another account. Tokens/assertions stay out of files/logs. Test renewal/rotation/revocation.
- If later hosted on Azure, prefer managed identity and an approved durable state design. Do not move this SQLite-based worker into ephemeral containers unchanged.

### Data and minimal cost

The initial qualification dataset and write tests remain synthetic. The owner authorized mailbox-wide incoming metadata for the live diagnostic; that does not authorize storing real customer bodies, training on mail or broad source history. Record the final production data/retention/access boundary before unattended live deployment.

Request the minimum fields and necessary headers; no body/attachment processing by default. Keep raw captures optional, protected and limited to the accepted seven-day window. Retain decision metadata for thirty days. Put no raw bodies, subjects, addresses, tokens or full headers into general logs. Protected local raw evidence follows deletion deadlines; backup retention must not resurrect expired raw records. Store durable references/digests with the decision and disclose when full replay is no longer possible after source deletion.

Use encrypted host storage, restrictive ACLs, consistent encrypted backups and a tested restore under the real service identity. SQLite does not encrypt data itself. Prefer the existing suitable Windows host and no new Azure compute for this POC. An ordinary sleeping laptop is not a reliable always-on deployment. If no suitable host exists, evaluate the cheapest appropriate Azure job/service in kb-agentdemo with explicit subscription, durable state, lease semantics and a reviewed cost estimate; defer deployment selection until that need is established.

## 4. Acceptance and production-readiness gates

Operational hardening and classification accuracy are different gates. Reliable retries and colored categories cannot establish AI attribution. Preserve the earlier low-false-positive requirements rather than silently lowering them for the POC.

| Gate | Required evidence |
| --- | --- |
| G1 — Agent false positives | One-sided 95% upper bound ≤0.1% for the union of every enabled positive agent rule. At least 3,000 independent representative zero-error non-agent sends is one sufficient binomial case; ordinary automation is included |
| G2 — Supported-path recall | ≥99% observed recall on ≥1,000 independent agent sends across qualified available sources and approval/autonomy cases, with intervals; report all-path recall and unknowns separately |
| H1/H2 — Human-capable semantics | Complete supported-field inspection and no observed automation/conflicts. Human- and agent-controlled browser cases are policy-positive for compatibility; do not report this label as proof of a human executor. Evaluate marker bypass and unsupported coverage separately |
| S1 — Semantic safety | No AI category from drafting/recipient reads, generic API use, an untrusted declaration or text origin alone; no Human fallback after incomplete inspection, collection errors or conflicting/automation evidence |
| O1 — Durable processing | No silent observable-event loss or duplicate logical decisions across pagination, crashes, moves, expired cursors, restarts or throttling |
| O2 — Classification latency | P95 <5 seconds after the last required evidence is available to the worker; separately measure polling, source lag, outbox and Outlook display delay |
| W1 — Controlled writes | Exact mailbox scope, categories-only payloads, no send path, no unrelated-category loss, tested concurrency and zero duplicate-loop amplification |
| W2 — Correct display | Exactly one service-managed category after a successful uncontested apply; correct red/green/yellow mapping in supported Outlook clients; apply failures remain visible |
| R1 — Reproducibility | Rule/source/config versions, credible independent truth, no label leakage, protected holdout and a traceable decision-to-applied-category chain |
| P1 — Pilot | Ten consecutive business days after the last material fix without an unresolved critical/high defect, unexplained event loss or unsafe category mutation |

Unknown and pending known-agent positives at the frozen deadline are recall misses. Unknown ground truth is not an assumed human/non-agent negative. Report class/source/route counts, correlated-template handling, intervals, precision, false alerts per thousand, source availability and unknown coverage. A pooled bound does not establish each source/subgroup's error rate.

Use a representative pilot dataset first to find defects; call that a pilot, not a passed 0.1% claim if underpowered. The general production release remains gated by the above evidence. Freeze the observation window before qualification: initially retain the earlier two-hour pending and twenty-four-hour late-observation protocol, revising it explicitly if measured feed lag requires it. Keep initial versus late results visible rather than waiting indefinitely to improve recall.

The three labels follow the accepted POC semantics. Human-capable is not a human-identity result; browser-driven agents intentionally share that compatibility label. Independent AI false-positive/recall measurements remain unqualified until Phase 4. Report blind spots and accepted copied-ID/replacement risk alongside measured results.

## 5. Phase-wise implementation

Every phase has an objective, implementation scope, expected outcomes, validation criteria and exit criteria. Historical components may be reused, but all new exits remain unpassed until tested against this monitor. Category writes are deliberately scheduled after source policy/accuracy work.

| Phase | Deliverable | Current status |
| --- | --- | --- |
| 0 | Freeze Outlook-native production scope and source feasibility | Complete; [review](docs/outlook-production-baseline.md), [exit evidence](docs/evidence/outlook-production-baseline-validation.json) |
| 1 | Separate production runner, contracts and durable state foundation | Complete; [review](docs/outlook-runtime-review.md), [exit evidence](docs/evidence/outlook-runtime-validation.json) |
| 2 | Reliable incoming-mail synchronization and restart recovery | Complete; [review](docs/outlook-sync-review.md), [exit evidence](docs/evidence/outlook-sync-validation.json) |
| 3 | Corroborated POC AI / Human-capable rules and conservative Unknown policy | Complete under the owner-approved POC semantics; [review](docs/sender-rule-qualification.md), [exit evidence](docs/evidence/sender-rule-validation.json) |
| 4 | Independent accuracy and adversarial validation in dry-run | Not complete |
| 5 | Scoped category permissions, ownership and setup preview | Not started; no new grants |
| 6 | Safe category writer, idempotency and rollback | Not started |
| 7 | Supervised operation, credential lifecycle and retention | Not started |
| 8 | Full Outlook end-to-end and failure validation | Not started |
| 9 | Shadow pilot, controlled enablement and production POC handover | Not started |

## Phase 0 — Establish the production contract and evidence baseline

**Objective:** Make the small Outlook-native deliverable and its achievable claims concrete before changing permissions or promoting demo logic.

**Implementation work**

- Inventory the existing demo rules, authentic audit path, current permissions, supported mailbox/folders and real source gaps.
- Freeze the three category meanings/colors, activation/backfill policy, default Unknown behavior, supported clients and minimum-data boundary.
- Establish feasibility of the owner's inferred-manual Human policy using complete message/header inspection; record its observability limits and the distinction between policy feasibility and validated three-class accuracy.
- Record required category-write exception to the former read-only boundary, separate runtime/setup identities, category-name collision policy, ownership, host and quantitative gates.
- Keep the existing demo available as a demonstration; archive its tested baseline separately from the new production profile.

**Expected outcomes:** Versioned production contract, source/trust matrix, scope/risk revision and an exact list of open feasibility dependencies.

**Validation criteria:** Trace existing A/B and Outlook examples to their real evidence; demonstrate why untrusted marker/no-marker rules are insufficient for qualified decisions. Confirm no permission or deployment change is implied by a plan.

**Exit criteria**

- [x] Current scope, names/colors, ownership, data boundary and source/coverage assumptions are recorded without contradictions.
- [x] Demo shortcuts are explicitly excluded from production classification.
- [x] Human-policy feasibility has an actual conclusion and tracked qualification/coverage blockers where unresolved.
- [x] Technical owner can identify the minimal remaining work and any source/access dependency before live category writes.

Executed evidence: [four-exit checklist](config/outlook-baseline-exits.json), [fresh read-only inventory](docs/evidence/outlook-baseline-live-validation.json) and [clean-source verification](docs/evidence/outlook-production-baseline-validation.json). This closes requirements/feasibility only; it does not enable the production monitor, qualified Human labels or category writes.

## Phase 1 — Build the separate production runner and state foundation

**Objective:** Create maintainable code with strict production contracts and durable work, without introducing an application server.

**Implementation work**

- Add the new descriptive entry point and small typed package; pin dependencies and integrate the existing quality/security gates. Extend boundary checks only for the named category-writer operations; keep send/write prohibitions in the other readers/tools intact.
- Validate mailbox/tenant/configuration, evidence eligibility, category mapping and dry-run/apply mode. No imported demo flag may activate live writes.
- Implement SQLite migrations, transactions, process lease, decision versions, pending work and category outbox; separate message decisions from category-application success.
- Reuse reviewed transport/authentication/parser helpers with bounded input, safe errors and no raw-secret logging.

**Expected outcomes:** Installable runner, strict AI Agent/Human/Unknown contract, durable schema and a deterministic dry-run command.

**Validation criteria:** Start from a clean checkout; test invalid configuration, migration/restart, disk errors, experimental-verdict rejection, multiple instances and interrupted transactions. A bad record must not cause an invented Human decision.

**Exit criteria**

- [x] New runner starts independently of dashboard/API/content-worker services.
- [x] State/migrations/leases pass crash and restart tests.
- [x] Dry-run causes zero mailbox mutations; the writer interface rejects non-production verdicts.
- [x] Relevant formatting/types/security/unit/contract checks pass the exact revision.

Executed evidence: [engineering review](docs/outlook-runtime-review.md), [validation record](docs/evidence/outlook-runtime-validation.json) and [runtime commands/recovery](docs/runbooks/outlook-runtime.md). This closes the standalone foundation only; mailbox synchronization, qualified AI/Human decisions and category application remain later phases.

## Phase 2 — Implement reliable mailbox synchronization

**Objective:** Observe new receiving-mail copies continuously without session caps or hidden checkpoint loss.

**Implementation work**

- Add per-folder delta state, folder discovery, immutable IDs, pagination continuation, activation/backfill eligibility and move/deletion handling.
- Persist observations/work/cursors transactionally; resume partially processed pages and avoid ID collisions across accounts/copies.
- Add throttling/Retry-After, transient backoff, permanent-access health states, cursor recovery, dead-letter accounting and bounded fair scheduling.
- Suppress service-only category updates as reclassification triggers while retaining the sync checkpoint.

**Expected outcomes:** Durable mailbox inventory, operational coverage state and restart-safe collection.

**Validation criteria:** Send externally prepared synthetic mail into Inbox, rules folders and Junk; exercise new folders, duplicates, out-of-order pages, moves, >10,000 fixture messages, missed polls and expired cursors. Test a crash before/after each checkpoint transaction.

**Exit criteria**

- [x] Controlled scenarios account for all observable messages or explicit unrecoverable gaps.
- [x] No fixed page/session cap silently skips mail; backlogs remain durable and visible.
- [x] Restart/move/replay tests yield one logical message decision per relevant version.
- [x] Category-generated delta events do not create decision/write loops.

Executed evidence: [engineering review](docs/outlook-sync-review.md), [clean-source validation](docs/evidence/outlook-sync-validation.json), [live move/restart evidence](docs/evidence/outlook-sync-live-validation.json) and [operations](docs/runbooks/outlook-mailbox-sync.md). This closes read-only synchronization; qualified actor rules and category writes remain later phases.

## Phase 3 — Qualify sender-evidence rules

**Objective:** Qualify the approved corroborated AI-agent rule and Human-capable compatibility rule, with Unknown for incomplete, conflicting or unsupported evidence.

**Implementation work**

- Adapt the enrolled Claude/Exchange Send rule with authenticated capture, publisher/source enrollment, completed-send semantics and exact scoped joins.
- Implement the owner-approved corroborated POC copy-context checks; reject observable collisions and contradictions. Document the unobservable copied-ID/replacement risk; do not claim independent forensic item identity.
- Parse Office365 MCP and Gmail API hints as context; positive promotion requires a separately documented qualified trust rule.
- Implement Human-capable after complete supported-field inspection without observed automation/conflicts. Human- and agent-controlled normal browsers share this compatibility label; ordinary automation and incomplete/error cases remain explicit.
- Add source freshness, revocation, pending/late reassessment and deterministic versioned downgrade behavior.

**Expected outcomes:** Source-specific rules, evidence explanations and actual qualified/unavailable capability states.

**Validation criteria:** Continuously test human-sent AI drafts, agent-sent human text, approved/autonomous sends, recipient reads, drafts, failures, generic API apps, forged declarations, wrong scopes and incomplete audit. Never use the current Outlook category as ground truth.

**Exit criteria**

- [x] Qualified agent routes work with actual authenticated evidence and precise coverage limits.
- [x] Declaration/API-only and missing-evidence cases return Unknown.
- [x] Human-capable behavior is qualified for the approved compatibility semantics, with real manual-client evidence and browser-controller equivalence tests.
- [x] Source outages/conflicts/revocations cannot create an unsupported affirmative label.
- [x] Observable copy-collision/conflict attacks are rejected; unobservable replacement risk is explicitly accepted and recorded before POC preview enablement. Category writes remain disabled.

Executed evidence: [engineering/semantic review](docs/sender-rule-qualification.md), [validation record](docs/evidence/sender-rule-validation.json), [real synthetic manual/Claude evidence](docs/evidence/sender-rule-live-validation.json) and [operations](docs/runbooks/sender-detection-rules.md). The fresh Claude test progressed from Unknown to AI Agent after audit evidence arrived; the manual Outlook control produced Human-capable. These exits qualify the explicitly revised POC semantics and engineering behavior. Independent numeric accuracy remains Phase 4; category writes and production pilot qualification remain later gates.

## Phase 4 — Validate accuracy and lock the decision policy

**Objective:** Establish detection quality before attaching authoritative-looking colors to mail.

**Implementation work**

- Import permitted independently prepared synthetic emails and actual send/action histories; keep ground-truth labels outside detector input.
- Cross identical text with human, agent and ordinary automated senders; include current Outlook/Gmail-to-Outlook paths and uninstrumented positives.
- Separate development/calibration/locked evaluation by sender/workflow/thread/template/source/time; sample source quality and adjudicate ambiguous history.
- Freeze enabled rules, trust scope, thresholds if any, observation windows and independent sample accounting; compute G1/G2/H1/H2 and unknown coverage.

**Expected outcomes:** Reproducible independent accuracy report, regression corpus and a versioned policy eligible for deployment.

**Validation criteria:** Measure every enabled positive rule's union, not just the strongest rule; include false-human errors and known positives left Unknown. Authored tests and the two-message A/B demo cannot satisfy independent sample requirements.

**Exit criteria**

- [ ] Mandatory semantic/forgery/source counterexamples pass.
- [ ] Independent labels, leakage checks and actual locked-set access controls are evidenced.
- [ ] Accuracy gates are met for the population to be enabled; underpowered results remain pilot-only.
- [ ] Any unavailable Human-capable inspection capability or external-source blind spot remains an explicit release blocker/limitation, never a default label.

## Phase 5 — Establish minimal category permissions and ownership

**Objective:** Prepare exact-scope Outlook annotation without broadening collector or agent-execution rights.

**Implementation work**

- Produce the concrete writer registration/RBAC proposal, allowlisted mailbox, operations and residual Mail.ReadWrite risk.
- Prefer manual/temporary provisioning of the three master categories; record ownership/color mappings and avoid recurring MailboxSettings.ReadWrite.
- Configure separate writer credentials only after the concrete scope is authorized. Preserve existing source identities and unrelated tenant settings.
- Prepare a dry-run plan showing the messages/categories that would change, without exposing customer content.

**Expected outcomes:** Reviewed access/configuration, effective mailbox scope and conflict-free category definitions.

**Validation criteria:** Verify actual read/write allowance on designated synthetic items and denial outside the mailbox. Test absent/conflicting category definitions and wrong writer credentials. Do not use destructive message operations as permission probes.

**Exit criteria**

- [ ] Exact writer/setup scope and residual privilege are accepted before grant/use.
- [ ] Effective allowed/denied calls prove mailbox isolation; no Mail.Send/full-access role is granted.
- [ ] Runtime lacks unnecessary category-provisioning rights and temporary setup access has an exact retirement plan.
- [ ] Category ownership and preview checks pass; no category application is silently enabled.

## Phase 6 — Implement the idempotent category writer

**Objective:** Apply the correct color category while preserving user data and handling concurrent changes.

**Implementation work**

- Implement categories-only route/payload validation, decision-version checks, per-message serialization and a transactional write-intent outbox.
- Merge only owned category names, preserve unrelated categories, condition updates on a validated message version and re-merge after conflicts.
- Read back confirmation, recover ambiguous timeout outcomes and expose apply-pending/failure states independently of classification.
- Add category drift detection and exact service-owned rollback without deleting messages/master categories or reverting unrelated user edits.

**Expected outcomes:** Safe apply/verify/retry/rollback commands and a traceable decision-to-Outlook mutation record.

**Validation criteria:** Test concurrent user edits, stale ETags, duplicate retries, crashes before/after PATCH, timeouts after successful writes, deleted/moved items and manual label changes. Prove category-only changes do not retrigger predictions.

**Exit criteria**

- [ ] At most one owned category remains after a successful uncontested apply; all unrelated categories survive.
- [ ] Real endpoint concurrency behavior is verified; unsupported unsafe paths cannot enable automatic writes.
- [ ] Repeated identical intents produce no unnecessary PATCH and no notification/delta loop.
- [ ] No source/prod decision failure can be mistaken for successful category application.
- [ ] Rollback preserves later user changes and removes only demonstrably service-owned labels.

## Phase 7 — Deploy supervised low-cost operation

**Objective:** Keep the script running safely without an open terminal, logged-in Outlook session or new application stack.

**Implementation work**

- Configure startup supervision on a suitable existing always-on Windows host under a dedicated account; prevent overlapping tasks and restart on failure.
- Validate certificate/profile access under that exact runtime, key rotation, token refresh/revocation, graceful stop and bounded network retry.
- Add local health/diagnostic reports for collector lag, evidence lag, decision counts, Unknown rate, category-write backlog, disk space and failure streaks.
- Enforce encrypted/ACL-protected state, 7/30-day retention, sanitized logs, consistent backups and tested restore. Keep broad raw captures off by default.
- Estimate incremental cost. Consider small Azure hosting only if the available host cannot meet operation needs, with a different durable-state design where required.

**Expected outcomes:** Reproducible deployment, supervision/retention/credential runbooks and a bounded cost baseline.

**Validation criteria:** Reboot/sign out, interrupt network, revoke/renew credentials, fill/test disk-error conditions and restore state on the designated runtime. Check no secrets or raw headers leak to logs.

**Exit criteria**

- [ ] Worker resumes independently of Outlook/interactive terminal with durable pending work intact.
- [ ] Runtime identity, restart/lease, certificate rotation and restore are demonstrated.
- [ ] Retention/log protection and resource bounds pass checks.
- [ ] Hosting assumptions/costs are recorded; no unapproved Azure resource or premium infrastructure is introduced.

## Phase 8 — Verify the complete Outlook experience

**Objective:** Demonstrate the real incoming-message → evidence → decision → native category path.

**Implementation work**

- Run externally prepared synthetic agent/human/Unknown/ordinary-automation scenarios across Outlook → Outlook and Gmail → Outlook.
- Exercise qualified and unavailable evidence, initial Unknown, delayed reassessment, category drift, failures and service restart.
- Verify exact category names/colors in Outlook on the web and new Outlook for Windows, preserving existing categories, unread state, content and delivery.
- Review changed code and run the relevant shared security/contract/integration checks against the exact candidate revision.

**Expected outcomes:** Sanitized end-to-end report, captured category verification and a defect/coverage review.

**Validation criteria:** Trace each applied category to the production rule/evidence/version. Show non-AI API senders and unsigned declarations do not automatically turn red. Verify client display separately from confirmed server write time.

**Exit criteria**

- [ ] Real synthetic mailbox category application/readback and supported-client display tests pass.
- [ ] Unknown/pending and source-unavailable cases remain honest; no demo binary fallback enters production.
- [ ] Concurrency/preservation/loop/restart/access/rollback regressions pass.
- [ ] No unresolved critical/high safety or correctness defect remains; source limitations are documented.

## Phase 9 — Complete the pilot and production POC handover

**Objective:** Release only the measured, bounded monitor, with clear operations and claims.

**Implementation work**

- Run dry-run/shadow collection first, then enable category writes for the allowlisted synthetic pilot after detector and writer gates pass.
- Observe ten consecutive business days after the last material fix; track errors, Unknowns, source lag, apply failures, unsafe edits and recovery.
- Deliver exact run/install/stop/rollback commands, scope/source matrix, retention/credential runbooks, tests and accuracy/coverage evidence.
- Tag/review/commit/push the approved release, excluding credentials, raw captures and unrelated workbook changes. Ordinary customer-data deployment requires its own recorded boundary.

**Expected outcomes:** Accepted Outlook-native production POC with a reproducible release and an operational owner.

**Validation criteria:** A fresh authorized operator can reproduce deployment and explain the displayed colors from actual evidence. No release document presents demo heuristics, missing Human support or low-volume tests as production accuracy.

**Exit criteria**

- [ ] Production-quality gates and the intended accuracy/source capabilities pass with recorded evidence.
- [ ] Pilot completes without unexplained loss, unsafe category writes or unresolved critical/high issues.
- [ ] Handover/rollback/recovery and operating cost are accepted and reproducible.
- [ ] Any restricted capability is explicitly accepted as a limited pilot; full three-class completion is not claimed when required inspection/source evidence is unavailable.
- [ ] Exact release source and required CI evidence are pushed; secrets/private mail/unrelated changes remain excluded.

## 6. Continuous improvement and implementation boundaries

For each phase: state the assumption, add meaningful counterexamples, implement a small vertical slice, test immediately, inspect real failures and add regression coverage before expanding. Tune only on development data; do not repeatedly expose a locked set and then reuse it as independent validation. Material policy/source changes require fresh qualification and, where appropriate, a restarted pilot window.

Prefer understandable deterministic source rules to an unexplained score. Do not train on mailbox content, use public detector uploads, infer model brands from prose or silently lower thresholds to reduce Unknowns. Software reliability does not eliminate an upstream visibility gap.

Each phase review records tested revision, run IDs, actual versus simulated data, open defects, category-write status, accuracy/coverage, latency and cost. Freeze no claim from a green authored suite alone. Use descriptive file/module names and preserve prior evidence/demo behavior. No extra frontend, API, LLM, Gmail-receiving integration or cloud platform is needed to satisfy this roadmap.

Phase 0 now has a frozen validated baseline, an archived demo and recorded feasibility/exit evidence. The running demo, mailbox permissions and Outlook categories remain unchanged. The separate runner supports synthetic fixture replay and durable read-only incoming-mail synchronization. Qualified actor rules and category writes remain gated by later phases.
