# Evidence and content threat model

Version 1.0, 28 October 2026. Scope: the accepted synthetic POC. Review state: the project owner explicitly accepted this concrete scope/threat/acceptance pack in chat on 28 October. This acceptance does not create new access or resolve the documented technical evidence gaps.

Protect message content, mailbox/tenant boundaries, source identity, evidence integrity, verdict history, credentials, model artifacts, and the accuracy of client claims. Threat actors include an external sender forging declarations, an ordinary application sharing an AI application's identity, a compromised evidence issuer, an attacker injecting instructions into email, and an operator accidentally pairing the wrong source record with a message.

Trust boundaries are (1) Exchange exports/Graph observations, (2) independently operated agent sources, (3) authenticated evidence ingestion, (4) the two independent decision paths, (5) restricted investigators/exports, and (6) public repository versus private captures. Administrator CLI diagnostics use an existing human identity; they are not proof that a least-privilege AgentTrace identity has been configured.

| Threat | Control and verification | Residual limit / owner |
| --- | --- | --- |
| Forged `x-ai-generated`, `Auto-Submitted`, app names or DKIM claims | Never promote from headers alone; dedicated header-forgery test | External origin may remain unknown; attribution engineer |
| Wrong-message, cross-mailbox or cross-tenant join | Source-scoped IDs, exact MIME digest in the spike, authorized mailbox list; negative tests | Audit ID namespaces and transport transformations need real adapters; integration engineer |
| Accepted/failed send reported as completed | Require completed execution plus observed sent/received message; test accepted/failed/cancelled/draft/read cases | A source can lie about its own operation; source owner |
| Replayed or conflicting records | Idempotent identical receipt; reject conflicting evidence-ID reuse; unknown for conflicting executors | Production append-only ledger is later work; backend owner |
| Forged, revoked, expired or future evidence | Ed25519 public-key verification, validity and scope checks; adversarial tests | Signatures prove issuer/integrity, not truthful authorship; compromised trusted issuer remains a threat |
| Shared identity mistaken for AI | Require an explicitly established agent actor and execution-specific send evidence | Registration/app identity alone cannot close a source gap; integration owner |
| Pasted AI text falsely accuses an agent | Separate findings and labels; no content score input to agent rules | Human interaction is not biological-human certification; product owner |
| Prompt echo/common templates falsely verify content | Require supported material origin and inclusion lineage; echo/similarity controls | Source truthfulness and mixed-region extraction need later validation; content owner |
| Prompt injection, malicious MIME or resource exhaustion | Treat text as data, no tools/network from parsing; bounded input/record sizes, path/scope checks, strict JSON | Full HTML/protected/attachment extraction is outside the spike; backend owner |
| Sensitive data leaks into Git/logs/public detectors | Ignored private captures, sanitized CLI errors, no raw body in report; review tracked files | Shared operator workspace is not a production vault; security owner |
| Model/label poisoning and false confidence | Frozen splits/thresholds, independent labels, artifact/license review, explicit experimental state | Text detectors remain vulnerable to shift; content/evaluation owner |
| Cost exhaustion or damaging shared resources | Read-only preflight, fixed RG, explicit subscription, no provisioning in this stage | Future deployment needs caps and what-if review; platform owner |

The local spike's keys and signed examples are test assets, not an enrolled production trust root. Never sign an operator-written reconstruction and describe it as a Claude- or Microsoft-issued execution receipt. User-supplied tool transcripts are useful ground-truth evidence but are not cryptographic attestations.

The live Claude connector's send result contains no message/request ID. Its later search result can identify a sent copy, but a same-subject lookup does not create a causal send-response binding. Until a trustworthy additional link exists, the primary detector must preserve unknown. The POC must report that miss rather than change the low-false-positive rule to make the test pass.

## Authenticated audit evidence for an enrolled connector

The separately authorized reader obtained a Microsoft Exchange `Send` event for the marked message. A direct authenticated audit event can supply the missing item-specific action link even when Claude's own response omits IDs. The route enrolls the exact vendor-published connector client application ID, corroborated against tenant service-principal publisher metadata, rather than trusting an application name. The rule requires a successful send, consistent actor/tenant/mailbox/client context and a unique scoped Sent Items candidate matching the event's Internet Message-ID. Incomplete pages and conflicting candidates fail closed. This implements the accepted audit-evidence option; it does not turn an unverified transcript into a vendor receipt.

Residual assumptions: Microsoft audit/Graph services and the authenticated collector are trusted; the enrolled Anthropic connector operates as documented; its credentials/backend are not compromised. A dedicated connector send establishes the supported agent execution path, not whether the wording was generated or whether a person approved it. A generic/shared app ID cannot establish this route. The scoped Internet Message-ID join can fail or become ambiguous when identifiers are reused or messages are unavailable; it is not a globally trusted primary key. The observed audit/store immutable ID has not been shown equivalent to the Graph immutable ID, and the MIME digest protects the captured snapshot rather than claiming Microsoft signed the body at send time. Production enrollment, immutable-identifier handling, multiple-source counterexamples, tamper-resistant capture storage and quantitative false-positive qualification remain later-stage obligations.
