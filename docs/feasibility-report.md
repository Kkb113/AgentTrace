# Initial feasibility implementation and exit review

Review date: 28 October 2026. **Phase 0 complete: all nine exit criteria have recorded evidence.** This establishes one narrowly supported agent-send evidence path. It does not qualify the finished MVP, its false-positive rate, universal agent coverage or statistical content detection.

## Delivered

- Owner-accepted synthetic-only scope, East US region, seven-day raw/thirty-day decision retention, two independent targets, threat model and frozen acceptance criteria.
- Tenant/source capability matrices, a content-labeling rubric, a bounded content acquisition/comparison protocol and an illustrative minimal Azure deployment estimate.
- A reproducible Python CLI for existing-environment inspection, authored signed-contract replay, synthetic EML/transcript inspection and a live authenticated Exchange audit read probe. No mail-send, draft, approval, scheduling or agent-execution operation exists in AgentTrace.
- Bounded MIME/JSON parsing, strict scope/binding checks, source enrollment, Ed25519 validation for the separate signed-contract route, replay/conflict handling, independent findings and explicit unknowns.
- Offline semantic/security tests, actual subprocess CLI tests, and a real three-message Microsoft 365 exercise. Reproduce local checks with `python scripts/verify-feasibility.py`; the reviewed outputs are under `docs/evidence/`. The same 67 tests also passed from a Git-index export with exact MIME fixture bytes preserved; see `docs/evidence/staged-validation.json`.

## Live result

The owner operated Claude outside AgentTrace to send the synthetic self-test, then independently prepared two manual Outlook controls. Actual email and source data remain in ignored private capture directories. The copied-text control was checked against the supplied AI-generated passage. Labels and creation histories were held separately from detector inputs.

| Independently prepared case | Agent-send truth | Agent finding | Content truth / finding |
| --- | --- | --- | --- |
| Claude executes the send | Positive | `verified_agent`, flagged | Text creation not independently established; content unknown |
| Owner types and manually sends a sentence | Negative | Unknown, no positive agent flag | Human original according to owner; content unknown |
| Owner manually pastes the supplied AI text and sends | Negative | Unknown, no positive agent flag | Known generated passage present; content unknown |

Unknown is an abstention, not proof of human execution. The two negative controls received no agent accusation. Three live cases cannot establish the frozen false-positive or recall targets. Conventional non-AI application sends have authored semantic counterexamples here; an independent live population for them remains later qualification work. The statistical content experiment has not run and is not represented as a completed classifier.

The initial EML/transcript-only inspection correctly remained unknown: Claude's original send result had no message/request ID or timestamp, and `x-ai-generated: mcp-office365` was only an unsigned declaration. Additional effective read access was explicitly authorized before creating the temporary reader and operator-only consent. Device-code authentication was blocked with 53003. Microsoft's supported browser PKCE flow subsequently succeeded with the same scopes and no Conditional Access change.

The authenticated Exchange search returned a successful **Send** event for the Claude message. Its tenant/mailbox, item Internet Message-ID, client request and consistent application context provide an item-specific action record. The client ID matches Anthropic's published M365 MCP Server for Claude and the tenant's publisher-verified application. The collector matched a unique non-draft Sent Items copy within that authenticated mailbox and verified its captured MIME Message-ID. The final shipped CLI reproduced the positive and both non-accusations. See `docs/evidence/live-audit-validation.json`.

This route uses the scoped unique Internet Message-ID join. Audit/store-to-Graph immutable-ID equivalence was not established by the attempted conversions and is not claimed. MIME hashes protect captured snapshots; Microsoft did not sign a body digest for AgentTrace. Trust depends on authenticated Microsoft records and the enrolled connector operating as documented. Generic/shared app IDs, header declarations, subject/time similarity, pending or incomplete captures and conflicting message candidates cannot create a positive.

Graph returned a legacy Exchange DN for the live Sent Items sender in one run. The resulting conservative unknown exposed an implementation issue; a tested fix resolves only that legacy form against the same item's captured MIME From address. Mismatched SMTP senders remain unknown. Earlier captures remain preserved; the final run reused existing searches only after revalidating their exact filters against the server.

## Source availability and access

The earliest successful audit collection occurred at 14:31:33 UTC for the 13:34:24 UTC event: **available by 3,429.482 seconds after the send**. Access remediation preceded that first read, so this is an availability upper bound, not exact ingestion latency. Searches for the newer manual controls completed with no matching Send record at collection time. That absence does not establish a human sender. Production polling, delay distributions and outage recovery are later-stage work.

Relevant Exchange/Entra plans and the operator's administrator role were observed. Effective `Mail.Read` and `AuditLogsQuery-Exchange.Read.All` were demonstrated by actual calls. This is evidence for this tenant/test, not a claim about every SKU or audit entitlement. Optional Graph activity logging was not configured; the existing workspace's narrow send-request query returned no rows. Those optional gaps do not prevent the demonstrated Exchange route.

No Azure compute, new logging destination, paid license or Azure role assignment was created. The separately authorized Entra registration/service principal and operator-only consent are tenant-scoped. No client secret/certificate or token cache was persisted. After the owner explicitly approved retirement, its grant, service principal and application were removed and their absence verified. No unrelated application or Conditional Access policy was changed. See `access-remediation.md` for the access/retirement record. A future product collector needs its separately approved identity in the planned identity stage.

## Exit criteria

The machine-readable record is `config/feasibility-exits.json`.

| Exit | State | Evidence |
| --- | --- | --- |
| Owner acceptance of scope, terminology, threat model and gates | Met | Explicit acceptance in chat; scope/threat/acceptance review pack |
| Administrator confirmation of required access/licenses | Met | Owner-authorized reader, observed plans/role and successful live mailbox/audit calls |
| Demonstrated exact-message agent evidence path, with gaps documented | Met | Authenticated Exchange Send, enrolled connector, unique scoped Sent Items join; native-ID limits disclosed |
| Accepted synthetic policy and external test sources | Met | Owner-selected Claude self-test and independently prepared manual controls |
| Exactly two findings; no execution/approval/automation features | Met | CLI/code boundaries and semantic/end-to-end checks |
| No unresolved dependency prevents the minimum end-to-end path | Met | Shipped read probe reproduces one supported agent-positive path; optional feeds and unknown cases explicit |
| Content policy, English boundary, criteria, private processing and acquisition plan | Met | Baseline, acceptance, content policy and protocol |
| Defined and resourced bounded secondary experiment | Met | Ten engineer-days, forty CPU-hours, zero default GPU/paid API; acquisition and promotion protocol |
| Required Azure scope, reuse boundaries, basic sizing and incremental cost | Met | Explicit subscription/group checks, retail snapshot, illustrative $37.78/month pilot; no compute provisioned |

The later G1Ã¢â‚¬â€œG9 and C1Ã¢â‚¬â€œC7 release obligations remain frozen and unmeasured. They are not Phase 0 exit claims. The next implementation work is the repository/product foundation and production-grade identity/collection design, followed by the separately bounded content experiment and independent qualification populations.
