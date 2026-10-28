# AgentTrace POC scope

Baseline date: 28 October 2026. Machine-readable choices are in `config/poc-baseline.json`.

The project owner accepted an industry-neutral, synthetic-data-only POC in Azure East US, retaining raw synthetic evidence for seven days and detection decisions for thirty days. No client-specific regulatory certification, production-data processing, or legal retention rule is assumed. The project owner is the decision owner; the signed-in test operator has an administrator role, but that does not grant the future AgentTrace application mailbox permissions.

The primary question is **whether an AI agent executed the email send**. External human approval does not change that target. AI drafting, recipient-side reading, API use, an application name, or AI-looking wording alone cannot establish it. The independent secondary question is **whether the body contains generated drafts or substantial AI rewriting/translation**. Untracked manual copy/paste is in scope for the later statistical experiment. Basic spelling and grammar corrections are distinct.

Initial clients are Outlook on the web and new Outlook for Windows with Exchange Online. Begin with the project owner's designated test mailbox; its actual address and tenant/subscription identifiers remain in ignored local configuration. Internal inbound/outbound and external inbound mail are in scope when observable. Start sizing at one mailbox and 100 messages/day; these are test assumptions, not measured demand or a capacity promise.

The externally operated Claude/Microsoft 365 connection supplies the first live positive test. AgentTrace never runs Claude, prepares an outbound draft, sends a test message, or manages its approval. The test owner performs those external operations. Only the marked synthetic message is exported for the feasibility exercise.

Exactly two finding objects are exposed: `agent_send_attribution` and `content_assessment`. Each includes status, a nullable flag, reason codes, and evidence references. Unknown is null, not false. Evidence, coverage and model qualification are supporting fields. Analyst review concerns findings, not permission to send.

Non-goals include agent execution, authoring, approvals, scheduling, routing, quarantine, blocking, mailbox modification, voice, attachments/OCR, arbitrary endpoint monitoring, and non-English statistical content classification. Unobservable external agents remain an explicit coverage gap.

## Data boundaries

Use synthetic text and self-addressed tests only. Keep received EML, actual IDs, source transcripts, and raw tenant responses under `work/private/`; they are excluded from Git. Commit only reviewed aliases, public pricing, test contracts, and sanitized reports. Delete private raw captures at seven days using a reviewed, exact-file cleanup process; decisions expire after thirty days. Retention is the accepted operational policy; this feasibility CLI is not a hosted retention service. Static fictional contract examples have no customer content and may remain as repository test assets.

Inference stays inside the approved customer boundary. No public detector upload, model training on pilot mail, clipboard monitoring, or broad prompt logging is authorized. The later content study may use permitted public datasets and separately obtained synthetic examples. Changing region, real-data scope, retention, permission scope, or performance claims requires a recorded baseline revision.

## Decision register

| Decision | Basis | State |
| --- | --- | --- |
| Two independent findings; agent first | Repeated explicit user instructions and accepted implementation plan | Accepted |
| Synthetic-only, industry-neutral, East US, 7/30-day retention | Explicit answer to baseline question on 28 October | Accepted |
| Claude as external test sender | Explicit user instruction replacing Dot; user reports execution and provides tool results | Selected; integration evidence being assessed |
| English drafts/rewrites/translations; grammar separate | Earlier explicit policy answers | Accepted |
| Primary G gates and secondary C criteria | Accepted plan at commit `92723da`; frozen details in `acceptance.md` | Baseline recorded; release results unmeasured |
| New threat-model and residual-risk review | Project owner explicitly accepted the concrete scope/threat/acceptance pack in chat on 28 October | Accepted; technical evidence gaps remain open |
| Read-only mailbox/audit application access | Actual approved-reader calls, not inferred from administrator title | Effective marked-message reads and Exchange audit search demonstrated |
| Temporary feasibility reader and operator-only delegated consent | Explicit owner authorization after review of `access-remediation.md` | Created and verified; live validation completed; grant and dedicated identity retired after explicit owner approval |
