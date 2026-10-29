# Historical sender-attribution acceptance contract

**Superseded scope:** The later 29 October Outlook-native revision makes [implementation.md, acceptance gates](../implementation.md#4-acceptance-and-production-readiness-gates) authoritative for the new monitor. It preserves the numeric agent/human accuracy targets, replaces the old no-mail-write rule with a separately scoped category-only writer, and defers the standalone UI/Gmail-receiving route requirements below. These older rows remain historical evidence, not new feature obligations or a permission grant.

Revision 2.0, 29 October 2026. The owner's sender-only change removes C1–C7 and all content-scoring obligations from the active release. Preserve the earlier numeric agent gates rather than weakening them. Historical exit evidence is not certification of new populations, human attribution or Gmail. Targets below are unmeasured release requirements, not achieved accuracy.

## Required outcome semantics

- **Sent by AI Agent:** qualified evidence of agent execution, completed send and a trustworthy unambiguous link to this observed message.
- **Sent by Human:** a separately qualified human-action source with a completed send and exact-message link; no unresolved contradictory executor evidence.
- **Unable to determine:** missing, conflicting, unsupported or unavailable evidence, including non-AI automation outside both affirmative actor labels.
- **Analysis pending:** collection is incomplete within the declared observation window. At the evaluation deadline, pending agent positives count as misses.

Neither absence of an AI flag nor the legacy negative `no_agent_observed_in_monitored_path` establishes a human. Application identity, a user session, ordinary authentication and writing style cannot certify the actor. The human label is a qualified observed interaction under stated source assumptions, not biological-human proof.

## Agent and platform gates

| Gate | Frozen requirement |
| --- | --- |
| G1 | One-sided 95% upper false-positive bound ≤0.1% for the union of all enabled positive agent flags, including suspicion if ever enabled. Zero errors among at least 3,000 independent representative non-agent sends is one sufficient binomial case. Report component errors separately |
| G2 | ≥99% observed recall on at least 1,000 independently labeled supported-path agent sends, with intervals, multiple available sources and both externally approved/autonomous sends. Publish all-path recall and unknowns too |
| G3 | No agent accusation for agent-draft/human-send, manual copied AI text, recipient reads or conventional automation in mandatory controls. Text origin is not scored |
| G4 | No unsupported badge from forged/replayed/revoked/expired/wrong-scope/message evidence, conflicting executors or ambiguous links. Identical legitimate replay is idempotent |
| G5 | P95 <5 seconds from arrival of the last required action evidence to persisted sender decision at the declared load |
| G6 | Report action-to-source, source-to-collector, collector-to-decision and decision-to-UI separately. Delayed audit is not synchronous detection |
| G7 | Outage/replay recovery accounts for all observable events or explicitly unrecoverable gaps; no silent loss or duplicate logical decisions |
| G8 | Zero successful unauthorized reads/decisions/exports; no mail-send/write or source-agent execution permission and no email execution/approval UI/API |
| G9 | Ten consecutive business days after the last material fix without an unresolved critical/high issue or unexplained loss |

G1 negatives include human sends and non-AI automated sends. Unknown ground truth is not assumed negative. Ground-truth agent positives that finish unknown/pending after the declared window remain missed positives. Copies, templates, retries and clustered executions do not automatically constitute independent samples. Pooled evidence cannot establish each subgroup's error bound. Report prevalence, precision, false alerts per thousand, unknowns and review workload.

The initial protocol collects pending evidence for two hours and late reassessment for twenty-four hours. These are bounded test assumptions, not source-delivery guarantees. Revise the protocol explicitly before qualification if measured lag requires it; preserve earlier and late outcome counts.

## Human, provider and explanation gates

| Gate | Required qualification |
| --- | --- |
| H1 | Every enabled human rule has credible human-action semantics, completed-send evidence and exact-message linkage. No default-human fallback, including for alerts/scripts or clean authentication |
| H2 | For the population receiving a human badge, the one-sided 95% upper false-human bound is ≤0.1% on representative actual-agent and non-AI-automation negatives. Report actual-human recall, unknowns and class counts separately; insufficient evidence keeps the rule disabled |
| P1 | Real end-to-end collection/decision/display tests cover Google → Outlook, Outlook → Google, Outlook → Outlook and Google → Google. Actual sender-evidence availability is reported for each route |
| P2 | Equal supported evidence yields equal verdicts across providers. Provider-domain identity never supplies the actor label. Personal Gmail/Workspace capabilities are qualified separately |
| U1 | Inbox rows, filters, counts and details show the same versioned backend result. Unknown/pending mail remains visible |
| U2 | Readable/raw headers preserve order, duplicates, malformed/missing states and source/trust context. Header values are inert and exports obey redaction/entitlements |
| U3 | Explanations distinguish authentication/transport hints from real action evidence. No fabricated percentages, source identities or screenshot-derived badges |
| M1 | Versioned sender-only migration preserves old records, maps legacy nonpositive results to indeterminate and disables new content-job production/deployment |

For H2, zero false-human badges in 3,000 independent representative nonhuman sends is one sufficient binomial case; report per-source/route power and clustered uncertainty. This is a new release safeguard, not evidence already obtained. Browser automation and shared sessions that defeat a proposed human source must be included, not excluded for convenience. If no source qualifies, retain unknown for those messages and disclose that the requested human badge is not available for that path.

## Required evidence before release

Freeze the final rule/source versions, population, routes, observation windows, labels, split protocol and thresholds before locked evaluation. Test ground truth comes from independent action records/credible operator history, not textual guesses or the detector's own inference. Sample source-quality reviews and adjudicate ambiguous actor evidence. Public human/AI prose datasets are not evidence of an email's send executor.

The accepted synthetic data/retention/access baseline remains in force. All route tests use externally prepared synthetic mail; AgentTrace itself never sends. Any ordinary customer inbox data requires a recorded policy revision before processing.

See [the current implementation plan](../implementation.md), [baseline review](outlook-production-baseline.md) and [Outlook-native revision](adr/outlook-native-categorization.md). Earlier Phase 0–4 reports and `config/poc-baseline.json` describe historical v1 behavior. The owner's newer inferred-manual Human policy supersedes the older source-proof requirement below the historical heading; its accuracy still requires qualification. Current production runner/writer work remains in the new roadmap.
