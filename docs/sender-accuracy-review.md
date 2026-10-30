# Sender accuracy validation review

**Current POC scope, 30 October 2026:** The owner selected [testing actual emails ourselves](adr/live-email-poc-validation.md). Phase 4 is complete under the revised controlled-POC criteria. Verification uses operator-recorded send actions and received-message evidence; no external corpus, independent curator, AI-text dataset or prose judgment is required. Population-level accuracy remains unqualified.

The active implementation validates the owner-approved corroborated Claude/Microsoft 365 AI rule and Human-capable compatibility policy. It evaluates send actions; AI text authorship and prose-style judgments are outside scope.

## Delivered software

The detection/source controls support the current POC. Dataset/curator/holdout functions listed below remain optional future statistical-qualification tools; they do not block current self-testing.

- Strict sender-only dataset, packet, action-review, source-capture and enrollment contracts; generated schemas and frozen code/dependency/policy fingerprints.
- Label-blind replay of the actual rule evaluator and shared enrolled-sender/copy checks; raw source semantics and publisher/query/copy conditions are revalidated, without importing an asserted trusted verdict.
- Retention/hash/path/source-review validation, chronological group-disjoint splits, duplicate provider/action/input checks and exact/bounded near-text screening. Bodies are optional private evaluation assets for leakage checks only.
- Conservative independent-cluster counts, exact binomial intervals and G1/G2 gates, all-path and supported-route recall, ordinary-automation negatives, unknown coverage, and per-route/source/approval/population reporting. Physical nonhuman Human-capable results remain visible without changing that label's accepted meaning.
- Frozen two-hour initial and twenty-four-hour late results. Future/absent frames, late source delivery, stale captures and unresolved labels cannot quietly improve an initial score.
- Curator OS access checks, a separate key, authenticated encrypted holdout, code/policy-bound grant and atomic one-use dataset receipts. A same-operator control drill never counts as independent access. Developer exports omit held-out cases/assets.
- New source-backed collection instructions/templates, private reports, safe CLI errors and authored adversarial/control tests. No send/category operation, live body download, new Azure resource, permission or dependency.

Review found and fixed two live-rule edge cases: conflicting repeated provider IDs could be overwritten during copy correlation; malformed header values could escape the conservative inspection path. The live collector and offline replay now share the copy and source-enrollment predicates. Existing Phase 3 cases remain regression controls.

Final review also binds reviewed cohort/source/group metadata, checks observed From identities rather than only declared sender groups, and binds the actual ACL-helper source into the frozen code identity. The real Windows control drill found a legacy PowerShell module-loading failure; the helper now uses installed PowerShell 7 without changing execution or tenant policies. Local semantic, access, encryption/tamper, split, deadline and process-level tests verify these fixes.

## Actual-email verification

Three existing operator-prepared synthetic emails were reprocessed through authenticated mailbox reads, the production synchronizer/source collector, guarded decision persistence and rule-output inspection. Existing actual completed query IDs were resumed only as provider references; their scope and all required records/publisher/copy conditions were rechecked through current APIs. Test subjects selected the known examples for comparison and never entered the classifier.

| Recorded actual send action | Observed result | Outcome |
| --- | --- | --- |
| Manual Outlook send, using the same supplied wording as the agent control | Human-capable | Pass |
| Manual Gmail → Outlook send | Human-capable | Pass |
| Claude Microsoft 365 connector Send | AI Agent with authenticated enrolled Send and corroborated copy context | Pass |

The two manual examples received no AI badge. [Redacted executed evidence](evidence/controlled-email-poc-validation.json) records all three results and private capture digests. These are fresh authenticated rereads of existing sends, not newly generated emails or a new-message latency benchmark. No body was requested, no email/category was changed, and no resource or permission was added.

## Phase 4 exit assessment

| Exit | State | Evidence |
| --- | --- | --- |
| Actual manual and supported agent emails | Pass | Three actual-email cases match the owner's recorded send actions; neither manual case receives an AI badge |
| Read-only end-to-end processing and explanations | Pass | Actual mailbox inspection, authenticated agent evidence, guarded persisted decision and output verified; action labels/wording are not predictors |
| Semantic/forgery/source controls | Pass under the accepted POC policy | Prior engineering gates cover declarations/API-only clues, wrong scopes/actors, incomplete/failed/stale sources and observable collisions; unobservable replacement remains an explicit accepted counterexample |
| Coverage and claim limits | Pass | Narrow enrolled Claude route, unsupported Gmail/external attribution, Human-capable compatibility, audit delays and sample limits remain explicit |

All four revised POC exits pass. This is owner-operated functional validation and engineering self-review, not independent population-accuracy qualification. G1/G2 remain unmeasured and require a separate future exercise if those numeric claims are needed. Earlier test counts and source hash remain in the [historical engineering record](evidence/sender-accuracy-validation.json); its two unmet former exits are superseded only for the controlled POC. Category permission/setup, safe writes and unattended operation retain their subsequent phase gates. See [actual-email test instructions](runbooks/controlled-email-tests.md).
