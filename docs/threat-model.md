# Sender-attribution threat model

**Current Outlook-native extension:** [The production plan](../implementation.md) supersedes the earlier absolute read-only boundary solely for managed category annotation. New risks are broad Mail.ReadWrite capability, wrong-message labels, user-category loss during concurrent edits, stale labels and write/delta loops. A dedicated exact-mailbox writer, categories-only route/payload guards, validated concurrency, confirmed/idempotent outbox updates, annotation expiry and owned-label rollback are required. The owner's subsequent Human policy permits inferred manual sending after complete inspection finds no automation indicators. Untagged/browser agents can defeat that inference and must be included in false-human evaluation. Failed/incomplete inspection stays Unknown; marker-only AI remains unqualified. The earlier model below remains useful history; no permission is granted by this extension.

Historical revision 2.0, 29 October 2026. The owner's earlier baseline/security acceptance remains historical; this revision introduces no mailbox access, Google consent or tenant-policy exception. [Current scope change](adr/outlook-native-categorization.md).

Protect mailbox/account boundaries, messages/headers, source identity, evidence integrity, classification history, tokens and the accuracy of customer claims. Trust boundaries are receiving-provider observations, sender execution sources, authenticated evidence ingestion, the shared sender policy, investigators/exports and private storage versus the public repository.

| Threat | Required control and verification | Residual limit |
| --- | --- | --- |
| Missing AI evidence treated as human | Separate qualified human rule; test legacy negative-to-unknown mapping and outages | Some legitimate human mail remains unclassified |
| Non-AI application, alert or rule forced into human/agent | Preserve conventional automation as context under indeterminate status | Requested two affirmative labels cannot exhaust all real send mechanisms |
| App/display name, AI prose or screenshot label mistaken for actor proof | Require source-qualified execution plus completed action and message linkage | Generic/shared applications cannot identify executor |
| Forged AI, X-Mailer, Auto-Submitted or Authentication-Results fields | Preserve header provenance/duplicates; trust only validated receiving-boundary assertions; forged-header tests | Transport authentication still cannot prove actor |
| Browser agent or remote control mimics human interaction | Qualify human source against these cases; disable rules unable to distinguish them | No ordinary email protocol proves biological human presence |
| Wrong-message/tenant/account join or duplicate Internet Message-ID | Scoped IDs, ambiguity rejection, exact action link and sender/recipient-copy mapping tests | Transport changes and missing sender records can prevent attribution |
| Accepted/failed/draft/read action promoted to completed send | Source-specific outcome semantics and independent observed-message corroboration | Upstream source truthfulness remains a trust assumption |
| Compromised issuer, key or connector backend | Enrollment, key validity/revocation, execution-specific claims, conflict handling and reassessment | Signatures do not make a lying issuer truthful |
| Receipt replay or altered scope | Event uniqueness, digest/scope binding, idempotent legitimate replay and append-only history | Historical raw evidence may expire before full re-execution |
| OAuth/account confusion, token theft or excess scope | State/PKCE/account binding, protected token storage, least privilege and revocation tests | Microsoft/Google tenant policies and verification can limit access |
| Cross-account message/header/export enumeration | Server-owned entitlements on every route and separate raw/export privileges | Broader consent does not justify broader investigator access |
| Header/MIME injection or resource exhaustion | Bounded offline parser, inert output, CSP, size/time caps, malformed/oversized tests and no remote fetch | Ambiguous or protected inputs may remain unavailable |
| Headers leak addresses, IPs, hosts or query data | Private retention, redacted share mode, export auditing and sanitized logs | Hashing alone does not anonymize predictable values |
| Delayed/missing audit or expired Gmail history | Health/freshness states, bounded reconciliation and honest pending/unknowns | A recipient mailbox cannot recover unavailable sender execution evidence |
| Biased/poisoned labels or test leakage | Independent execution records, grouped locked evaluation, source-quality sampling and no labels in detector input | Creator attestations and reviewers can still be mistaken |
| Misleading universal coverage/accuracy claims | Per-route/source counts, intervals, all-path misses and explicit unavailable human rules | Four transport integrations do not imply universal attribution |
| Cost escalation/shared resource damage | Explicit subscription, new Azure resources only in kb-agentdemo, what-if, caps and exact owned-resource operations | Budgets notify; they do not stop spending |

## Existing Claude route

Authenticated Exchange Send audit can establish a message-specific action link even if Claude's send response returns no message ID. The demonstrated route requires the enrolled vendor-published connector identity/publisher, successful Send semantics, consistent tenant/mailbox/app context and a unique scoped Sent Items match to the Internet Message-ID. Incomplete/conflicting results fail closed.

This trusts Microsoft services, the authenticated collector and the enrolled connector's qualified behavior. A generic shared app ID does not qualify. Audit/store-to-Graph immutable-ID equivalence remains unproven; capture hashes do not imply a Microsoft-signed body. The recorded one-message success proves neither latency nor an error rate. [Actual recorded test](evidence/agent-audit-fallback-validation.json).

## Legacy and data boundaries

Keep original reports and signatures intact. Existing v1 content fields/components are historical until the sender-only migration retires active processing. No text-origin inference or model training is required. Body preview, if later enabled, is separately authorized and safely rendered.

Retain synthetic-only use, East US and 7/30-day raw/decision retention. Google credentials/permissions are not inferred from Microsoft access. No sending/approval capability, customer-data use, public detector upload, clipboard surveillance or security-policy bypass is authorized by this document.
