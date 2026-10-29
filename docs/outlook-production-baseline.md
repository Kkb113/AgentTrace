# Outlook production baseline review

Current POC policy revision: [Human-capable and corroborated indicators](adr/human-capable-classification.md). This supersedes earlier Human/controller and independent received-item-proof definitions for this POC; historical evidence below retains its original scope.


Status: Phase 0 complete, four of four exits evidenced. Production monitor and category writes remain disabled. This review covers the new ten-phase Outlook-native plan, not the earlier application roadmap.

## Frozen contract and ownership

The [versioned contract](../config/outlook-production-baseline.json), [JSON Schema](../packages/contracts/schemas/outlook-production-baseline.schema.json) and strict validator freeze AI Agent/red/preset0, Human/green/preset4 and Unknown/yellow/preset3. The project owner is the product/data decision owner; the designated Microsoft administrator controls mailbox grants; an always-on host/runtime account still needs enrollment. Category ownership is enrolled IDs/names/colors only, with setup stopped on unexplained name collisions. Existing categories have not been adopted, recolored or deleted.

Activation records UTC at first production start. Backfill requires an explicit bounded operator request. Scope is one Exchange mailbox receiving Gmail/Outlook mail, Outlook web and new Windows clients. No standalone application, content model, Gmail-receiving component or new Azure resource is required. Category lifetime and decision metadata are thirty days; optional raw evidence is seven days. Unattended data/host settings and any longer annotation lifetime must be recorded before enablement.

The [scope](scope.md), [risk extension](threat-model.md) and [decision record](adr/outlook-native-categorization.md) cover the sole future write exception: a separate exact-mailbox category writer, categories-only guards, conflict/preservation checks and owned-label rollback. Its broad technical Mail.ReadWrite capability is an acknowledged residual risk. No new grant is made by the baseline.

## Actual source inventory

[Fresh authenticated inspection](evidence/outlook-baseline-live-validation.json) re-read the owner's existing three synthetic examples, a saved completed audit query, non-hidden folder inventory and current Entra app-role assignments. It found nine visible folders, six candidate receiving folders, and a denied GET against the designated control mailbox. Folder names, addresses, actual IDs, source replies and credentials remain private. Hidden folders/protected items and production all-folder reconciliation are not qualified by this bounded inventory.

| Source | Observation | Production readiness |
| --- | --- | --- |
| Gmail manual example | Real received copy readable; demo says Human | Supports field-access feasibility; creator's action report is not independent accuracy evidence |
| Gmail Claude example | Real received copy readable; Gmail API trace triggers demo AI label | API hint is not authenticated AI execution; source attribution remains open |
| Outlook Claude example | Real received copy readable; Office365 MCP marker triggers demo AI label | Declaration is not independently trusted merely because it is present |
| Existing Exchange Send query | Fresh API reads reproduced the narrow enrolled Claude audit result | Reusable source route; received-copy collision/tampering and rule qualification are still Phase 3 work |
| Mail reader Entra Graph grants | None; actual allowed/denied mailbox reads succeeded as expected | Uses existing Exchange RBAC; fresh Entra assignment inventory alone is not a complete effective-rights proof |
| Audit reader Entra Graph grants | AuditLogsQuery-Exchange.Read.All | Existing audit access; tenant-wide visibility remains the accepted historical risk |
| General human-executor provenance | No configured authoritative source | Not required by the owner's inferred-manual definition, but no biological/manual-action proof is claimed |
| Category writer/setup | Not provisioned; no mutation probe attempted | Phase 5 dependency |

No mail was changed, audit search created, resource provisioned or permission added. The inspection uses only existing GET/read operations. Raw captures preserve source-limited expiry, no later than 4 November 2026 at 20:44:50 UTC for this combined packet. Historical reports are not edited to imply new tests passed.

## Human-policy feasibility conclusion

The owner explicitly clarified that manual client sending is Human independently of whether the text was written or copied from AI. After a successful complete inspection of the configured observable fields, no MCP/API/other automation indicators may therefore support an **inferred Human** result. The existing reader exposes the needed metadata/header fields, so implementing this policy is feasible. Stronger human-action telemetry is an optional improvement, not a newly imposed prerequisite.

Complete inspection means completion of the configured observable checks; it does not establish visibility into an external sender's entire workflow. Missing headers, read failures, conflicts or known automation must stay Unknown. The policy can misclassify browser-driven agents or API sends whose markers are absent/stripped. This is a real qualification dependency, not a solved evidence gap. The existing demo's broad unconditional fallback is not the future production rule.

| Dependency | Owner / next phase | Closure evidence |
| --- | --- | --- |
| HUMAN_RULE_QUALIFICATION_PENDING | Detection/evaluation owner; Phases 3–4 | Implement complete-inspection rule, independent human/nonhuman labels, false-human bound and all-path coverage |
| UNTAGGED_AUTOMATION_COVERAGE | Source/evaluation owner; Phases 3–4 | Browser/stripped-marker and conventional-automation tests; disclose measured misses or restrict supported scope |
| RECEIVED_COPY_LINK_QUALIFICATION | Integration owner; Phase 3 | Exact scoped linkage, duplicate-ID/forgery/forwarding/conflict attacks, no candidate-join promotion |
| CATEGORY_WRITE_ACCESS_AND_COLLISION_CHECK | Microsoft administrator; Phase 5 | Concrete mailbox writer/setup grant, actual scope tests and category ownership inventory |
| CATEGORY_CONCURRENCY_AND_ROLLBACK | Writer owner; Phase 6 | Actual stale-update rejection, preserved unrelated categories, loop/idempotency and owned-label rollback tests |
| UNATTENDED_HOST_AND_DATA_ENROLLMENT | Operations/data owner; Phase 7 | Runtime identity/certificate access, host uptime, encrypted state, retention and restore evidence |

Graph activity logs remain unavailable as an effective source, but are optional for the minimum Exchange-audit route. G1/G2/H1/H2 and the ten-business-day pilot remain unmeasured release gates. The numeric targets are not claimed achieved by three examples or authored tests.

## Verification and exit decision

The contract verifier runs in CI, rejects unsafe changes (wrong colors, forced Human after failed inspection, unverified AI promotion, enabled writes/grants and altered retention) and checks the committed schema. Tests exercise a real verifier subprocess, safe errors, Windows Azure CLI encoding, private-path rejection, demo/qualified-rule separation and the existing audit controls. [Verification runbook](runbooks/outlook-baseline-verification.md).

The existing demo is published as a separate diagnostic with its experimental qualification intact. The production baseline cannot enable its predictions for category writes. Repository code from the unfinished independent-evaluation track is not part of this change. A clean selected-source export is used for the complete shared gates before publication.

Phase 0 closes only the four documentation/feasibility exits in the plan. [Executed report](evidence/outlook-production-baseline-validation.json): clean-source quality/security/infrastructure/guard checks passed, 283 unit/security tests plus 97 subtests passed, and 123 integration/end-to-end tests passed on a separate synthetic database volume. Existing database credentials/project-name assumptions caused initial local setup failures, corrected without changing the product or deleting the old volume. The Windows CLI encoding issue was fixed with a regression test.

It does not implement the new production runner, decide live mail under a qualified policy, grant category access or apply colored labels. The [four-exit checklist](../config/outlook-baseline-exits.json) records scope, demo isolation, Human-policy feasibility and next-work/access dependencies separately from those later gates.
