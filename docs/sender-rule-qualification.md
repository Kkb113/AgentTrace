# Sender-rule qualification review

This review applies to the owner-approved **corroborated POC AI / Human / Unknown** policy, not the earlier forensic-receipt/human-controller target. [Policy revision](adr/human-capable-classification.md), [machine policy](../config/outlook-detection-policy.json), [operations](runbooks/sender-detection-rules.md).

## Exit review

| Exit | Qualification evidence | Result |
| --- | --- | --- |
| Enrolled agent route works with authenticated evidence and precise coverage | Fresh certificate/API reads of a prior synthetic Claude Send, current publisher pins and provider copies produce AI Agent under the registered corroborated rule | Pass for the bounded POC route |
| Declaration/API-only and missing required evidence remain Unknown | Known MCP marker without audit/copy corroboration, generic Gmail API, partial queries, malformed headers, unsupported scopes and failed sources | Pass |
| Human compatibility semantics are supported | Actual manually sent Outlook example plus complete-inspection tests; the same observable browser message is intentionally Human for either controller | Pass for compatibility, not human identity |
| Outage/conflict/revocation cannot create an unsupported affirmative | Expiry, wrong tenant/mailbox/app context, failed/read/draft events, publisher mismatch/revocation, stale generation and source failure controls; current evidence rechecked transactionally before a positive preview | Pass |
| Observable copy attacks are rejected and residual risk accepted | Duplicate/colliding provider copies and contradictory events reject; the unobservable full-replacement counterexample remains explicitly accepted for this POC and is not claimed solved | Pass under the revised POC exit |

[Executed validation](evidence/sender-rule-validation.json) records the source digest, exact checks/counts, actual versus simulated cases and production-readiness limits. Green engineering/semantic gates do not qualify statistical accuracy or enable Outlook writes.

## Engineering review

Review traced authenticated source creation/read → query-scope validation → full pagination → exact enrolled Send semantics → matching-copy checks → versioned assessment → guarded local preview. Publisher verification pins app ID, owner tenant, enabled state and verified publisher; token/tenant/subscription context is explicit. The audit identity remains separate from mailbox reading. The only new network POST is the fixed bounded analytical search; AST and transport tests reject other write routes. No send/draft/approval operation exists.

The Human revision changes the green label and its meaning explicitly. Schema migration preserves earlier rows, scopes and activation; legacy Human input is compatibility-only. The rules never inspect message text origin or use a review label, current category, test subject or filename as actor evidence. Header folding, bounds, singleton identity fields, metadata hashes and shape checks are deterministic and bounded.

The decision transaction recomputes each affirmative rule from the current snapshot/source, compares exact rule/reasons/references, and stores its assessment together with the version/preview/work acknowledgement. Experimental or asserted-qualified imports remain ineligible. Identical reassessment is idempotent; source freshness/conflict changes create a new version and supersede old previews. Source job generations fence asynchronous progress, while the existing OS lock/lease keeps state single-host and single-worker.

Enrollment changes fail explicitly instead of reinterpreting old source receipts under a new principal or publisher. Certificate rotation preserves the semantic enrollment. Malformed publisher responses produce a source failure and block affirmative inference. Offline inspection identifies itself as a stored view without refreshed evidence.

Tests distinguish three important outcomes: a validated enrolled source action; the separately accepted POC receipt association; and a final category. An audit action without the marker/copy conditions does not become AI Agent. A normal browser-compatible message does not become a verified human. Observed collisions reject, but the deliberately constructed full-replacement counterexample demonstrates the admitted forensic limitation. No authored test is presented as an independent accuracy sample.

## Scope and outstanding release gates

Qualified AI coverage is the enrolled own-mailbox Claude/Microsoft 365 MCP route with available Send evidence and retained unique Sent/received context. External senders, generic Gmail APIs, other agents, absent markers, missing Sent copies and unavailable audit evidence can remain Unknown or be Human when the current compatibility policy actually applies. Browser-driven agents are deliberately included in Human, so physical-actor recall and policy-class recall are different measurements.

Live qualification includes both a retrospective authenticated replay and the fresh Claude/manual Outlook pair through the production rule pipeline. The fresh Claude case changed from Unknown to AI Agent after audit evidence arrived; manual Outlook mail produced Human. Audit delivery lag is not eliminated by this implementation. The earlier ID conversion probes are diagnostic history, not a qualified identifier mapping. The [redacted live record](evidence/sender-rule-live-validation.json) retains actual decision timestamps and private capture digests.

The owner subsequently selected [controlled actual-email POC tests](adr/live-email-poc-validation.md) for Phase 4. Independent G1/G2 measurements and representative holdout coverage remain future broad accuracy qualification rather than a POC prerequisite. Category credentials/ownership, safe writes, Outlook color visibility, unattended hosting, physical retention/backup and pilot gates remain later phases. No new Azure resource or permission is required here. The archived demo and unrelated evaluation/client-workbook changes remain preserved.
