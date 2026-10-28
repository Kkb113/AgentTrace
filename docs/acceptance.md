# Frozen acceptance contract

Contract version 1.0, 28 October 2026. Basis: the project owner accepted the agent-first implementation plan and the synthetic-only POC baseline. Changes to targets or populations must be recorded before locked evaluation. These are proposed release targets, not achieved performance. Local contract tests do not qualify release accuracy.

## Primary release gates

| Gate | Frozen definition |
| --- | --- |
| G1 | One-sided 95% upper false-positive bound ≤0.1% for the union of all enabled positive agent flags, including suspicion. Zero errors over at least 3,000 independent representative non-agent-send negatives is one sufficient case. Report verified and suspected errors separately |
| G2 | ≥99% observed recall on at least 1,000 independently labeled supported-path agent sends, with intervals, multiple sources and both externally approved/autonomous cases. Also report recall and unknowns on uninstrumented paths |
| G3 | No agent accusation for draft-only AI, recipient reads, human-sent copied text, or conventional automation in mandatory counterexamples |
| G4 | No unsupported verified verdict from forged, replayed, revoked, expired, wrong-scope/message or mismatched-content evidence. Identical legitimate replay is idempotent |
| G5 | P95 <5 seconds after the last required agent evidence arrives at the agreed load; content cannot delay it |
| G6 | Report event-to-source, source-to-collector, collector-to-decision and decision-to-UI separately; no synchronous-audit claim |
| G7 | Outage/replay recovery accounts for all observable events or explicit unrecoverable gaps; no silent loss or duplicate decisions |
| G8 | No unauthorized reads/exports/decisions; product identity has no mail send/write or source-agent execution permission; no execution/approval UI or API |
| G9 | Ten consecutive business days after the last material fix, with no unresolved critical/high issue or unexplained loss |

G1 denominator is all assessed non-agent sends in the declared population, not just easy cases. Include human-written and AI-written human sends, non-AI applications, shared identities and failed attempts. A positive with unknown/pending detector result after the observation window counts as a miss in recall. Pooled evidence cannot establish every subgroup's error bound. Templates, copies, retries and related executions are not automatically independent samples. Report prevalence, precision, false alerts per thousand, unknown coverage and review burden.

The initial protocol observes pending agent evidence for two hours and late reassessment for twenty-four hours. This is a bounded test assumption, not an audit-delivery guarantee. Measure actual feed lag and revise the protocol explicitly before qualification if needed.

## Secondary content criteria

| Criterion | Frozen obligation |
| --- | --- |
| C1 | Evaluate trustworthy generation/inclusion records where available; no verified claims from echoes, similarity or wrong-message receipts. An unavailable optional source is a declared gap |
| C2 | Proposed advisory-flag budget: one-sided 95% upper FPR bound ≤1%, with 0.1% stretch. Size independent negatives for the actual claim; 300 zero-error negatives supports 1%, 3,000 supports 0.1%. Evaluate eligible and all-assessed populations separately |
| C3 | Actually compare at least two licensed scoring candidates with provenance disabled; report each positive family and uncertainty. Seek 60% eligible recall without making it a primary release gate |
| C4 | Report readable/eligible/scored/unknown counts, length bins and all-length recall. Initial 50% coverage and 30% all-length recall are research goals |
| C5 | Isolate content outages/backlogs from primary decisions. Measure latency, cold start, memory and cost; aim for P95 ≤30 seconds or disclose a bounded economical alternative |
| C6 | Preserve independent flags, unsupported-language unknowns, grammar distinction, inherited regions and no invented provider/word-percentage claims |
| C7 | Pin/reproduce artifacts, normalization, calibration, thresholds and scope. No online self-training or threshold lowering from pilot flags |

Positive statistical content flags require C2 evidence. Otherwise retain real experimental scores in a clearly labeled investigator/evaluation view, with unsupported findings unknown. The required actual scoring attempt cannot be replaced with a stub or provenance-only demo. Content recall failures do not invalidate independently passing G gates. Measure the final combined review policy's workload and error rate rather than adding component “accuracy” claims.

## Initial-stage evidence versus release qualification

The initial stage must deliver scope/policy/threat documents, tenant/source capability evidence, a real test-message exercise, a source-link feasibility decision, a bounded content protocol and costed deployment choices. Its acceptance checklist is in `feasibility-report.md`. Release gates G1–G9/C1–C7 are frozen now but are measured in later implementation stages. Source/operator sign-off is recorded as actual acceptance or pending; the implementation cannot approve its own missing external evidence.
