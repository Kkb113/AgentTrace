# AgentTrace implementation plan

- **Project:** AgentTrace
- **Primary workspace:** `C:\AgentDetection`
- **Repository:** [Kkb113/AgentTrace](https://github.com/Kkb113/AgentTrace)
- **Plan date:** 28 October 2026
- **Status:** Revised delivery plan; product implementation and performance validation have not started.
- **Delivery scope:** 15 phases, numbered Phase 0 through Phase 14.
- **Scope revision:** Detect AI-generated email content as well as agent actions. English first; flag generated drafts and substantial rewrites/translations, and distinguish basic spelling/grammar assistance.

AgentTrace will answer two independent questions about Outlook and Exchange Online email: **did an AI agent act in the email workflow, and does the message contain AI-generated content?** It will identify observed actions, responsible applications or agents, approval, content provenance or statistical suspicion, and the evidence supporting each result. A person manually pasting an AI-written draft into Outlook is now a positive content-detection scenario, while remaining outside agent involvement unless an agent also operates the email workflow. Low false positives, explicit coverage limits, reproducible decisions, and protection of sensitive email data remain the priorities.

The strongest attribution will be available for instrumented internal workflows and cooperating senders. For untracked copy/paste, content detection is an inference, not proof of authorship. Short messages, substantial editing, unfamiliar generators, and ordinary human writing can make the distinction unreliable. The product must preserve unknown results and must not promise detection of every AI-written email. No phase authorizes a claim of universal detection or production regulatory compliance.

## 1. Product definition and scope

### What counts as agent involvement

An AI system participates when it executes an email-workflow action on behalf of a user or organization: reading relevant mailbox content, creating or modifying a draft, selecting recipients, scheduling, forwarding, replying, or sending. Human approval does not remove agent involvement.

A person asking ChatGPT, Copilot, Claude, or another assistant to write text, manually copying it into Outlook, and manually sending it is outside the **agent-action** definition but inside the **AI-content** scope. Generated wording alone is not evidence that an agent operated the mailbox. Conventional rules, scheduled scripts, and business applications without an AI workflow are separate automation categories; their messages can still contain AI-generated text.

Agent participation and send execution are distinct. The primary product question is whether an agent executed the sending action; broader workflow participation is a separate result. An agent-created draft sent by a person is an agent-involved workflow, but it must not be presented as an agent-executed send. A read of a conversation must not automatically attribute every past or future message in that conversation to the agent. An agent reading an incoming message on the recipient side provides no evidence that its external sender used an agent.

| Scenario | Agent-action result | Content treatment |
| --- | --- | --- |
| Human writes and sends manually | Record observed interaction; do not certify human-only operation | Content-policy negative in independently verified ground truth; no signal is not proof of human authorship |
| Human pastes an AI-written draft and sends | No agent verdict based on the text or paste event | Content-policy positive; verified only with sufficient provenance, otherwise inferred or unknown |
| Human uses AI for a substantial rewrite or translation into English | No mailbox-agent claim without action evidence | Content-policy positive, including human edits after generation |
| Human uses only basic spelling/grammar correction | No agent claim from corrected wording | Separate assistance category; do not raise the targeted AI-content flag solely for this assistance |
| Non-AI script sends an AI-written template | Conventional automation if verified | Content-policy positive independently of send mechanism |
| Agent sends a pre-existing human-written template | Agent send if linked | Agent action alone does not establish generated content |
| Agent generates a draft, then a person sends | Workflow involvement if linked; human send recorded separately | Assess generated content independently |
| Agent sends after human approval or under standing authorization | Agent send if linked; approval recorded separately | Generated wording is assessed independently; approval does not remove either type of involvement |
| Unknown application calls an email API | Operation observed; AI status unknown without stronger evidence | API use says nothing about text origin |
| External email asserts AI origin in an unsigned header | Unverified declaration | Unverified declaration; ordinary authentication does not prove content origin |
| Uninstrumented browser agent or external sender | Preserve unknown where attribution is unsupported | Statistical assessment only within validated language/length/domain coverage |

### Content policy and achievable claims

- **Confirmed policy:** flag AI-written drafts and substantial AI rewrites/translations. Treat basic spelling/grammar correction separately. Define examples of substantial rewriting versus surface correction in Phase 0 and label original/revised pairs independently. An origin score cannot reliably identify which editing operation occurred; unknown assistance type stays unknown.
- **Confirmed language scope:** English first. Non-English and mixed-language text outside the validated scope returns `unknown` with an unsupported-language reason for content detection. Agent-action attribution can still operate. Translation into English is an in-scope positive, even when the original was in another language.
- Analyze newly authored body text and quoted/forwarded material as separate regions. A message containing flagged inherited text can carry an inherited-content notice; do not accuse the forwarding person of generating it. Signatures and repetitive disclaimers are separate regions and must not inflate an author's score. Subject-only text, attachments, images, and text hidden inside attachments are not content-classified in this POC; show those exclusions.
- Preserve mixed human/AI content as a test family. A window score is not proof that every word in that window was generated. Do not display an invented percentage of AI-written words or name ChatGPT, Claude, Copilot, or a model from prose style alone.
- Approved generation integrations can provide evidence even when a person later copies the output manually. Unmanaged personal assistants and arbitrary external senders often provide no usable provenance. They remain important statistical evaluation cases, not silently excluded requirements.
- The POC flags for review and records evidence. Post-send detection cannot undo disclosure that already occurred when someone pasted sensitive information into an external assistant; prevention of that disclosure requires separate approved controls at the generation boundary.

### Initial deployment boundary

- One customer-controlled Microsoft 365 tenant and Azure subscription, both already available.
- Exchange Online, Outlook on the web, and new Outlook for Windows as the initial supported clients.
- A small, explicitly allowlisted set of test mailboxes, including a shared mailbox if supported by the validated permission design.
- Internal inbound and outbound messages, plus external inbound messages to those mailboxes.
- One instrumented test agent with human-approved and autonomous modes, one non-AI sender, and an independent external test sender where available.
- An approved generation-only test workflow for manual copy/paste, plus unmanaged assistant examples produced with synthetic inputs. No consumer account history or clipboard surveillance is assumed.
- Synthetic business data during development; any pilot use of real email requires the customer-approved access and retention configuration established in Phase 0.
- Customer-hosted Azure deployment. Detection is observation-only by default. Optional prevention is limited to actions passing through the controlled agent tool boundary.

### Explicitly deferred scope

- Phone calls, voice analysis, consumer Outlook.com, Exchange on-premises, and comprehensive mobile or classic Outlook support.
- Universal detection of undisclosed external agents or browser-controlled agents.
- AI-written-text classification as an input to an agent verdict.
- Non-English content classification, universal provider/model identification, and guaranteed detection of short or heavily transformed AI text.
- Attachment/OCR content classification, covert clipboard monitoring, browser surveillance, and general-purpose pre-send interception.
- Enterprise-wide mail routing changes, automatic quarantine, and production blocking based on statistical suspicion.
- Full DLP, malware filtering, or replacement of Microsoft identity and information-protection controls.
- Broad multi-tenant SaaS operation, high-availability certification, and jurisdiction-specific compliance certification.

## 2. Architecture and technology decisions

| Component | Baseline choice | Responsibility |
| --- | --- | --- |
| Outlook add-in | Office.js, React, TypeScript, Fluent UI | Display evidence for the selected message and supported approval interactions |
| Investigator dashboard | React, TypeScript, Fluent UI | Search, timelines, review, coverage, and authorized evidence exports |
| API and contracts | Python, FastAPI, Pydantic | Authenticated ingestion, queries, schema validation, and decision APIs |
| Attribution workers | Python; versioned deterministic rules initially | Correlate evidence and produce auditable results |
| Content normalization | Python MIME/HTML parsing with bounded, offline extraction | Separate authored text, quotes, signatures, language, and eligibility while retaining source offsets |
| Content detectors | PyTorch, Hugging Face Transformers, scikit-learn; candidate encoder classifier plus Fast-DetectGPT and Binoculars benchmarks | Private inference, calibration, abstention, and evaluation of generated/revised text |
| Content model artifacts | Versioned manifests and private Blob Storage; experiment tracking without message text | Pin code, weights, tokenizer, normalization, calibration, thresholds, and evaluation lineage |
| Generation provenance | Controlled generation adapter; optional approved enterprise history connectors | Link actual generated output to included message text without inferring agent sending |
| Mail integration | Microsoft Graph v1.0 | Scoped message reads, subscriptions, delta reconciliation, and test-agent draft/send operations |
| Audit integration | Office 365 Management Activity API; Graph activity logs where licensed | Independent Microsoft evidence and application activity |
| Identity | Entra ID, MSAL, managed identities | User sign-in, workload authentication, and least-privilege access |
| Agent inventory | Entra Agent ID where available, plus a controlled local registry | Resolve agents, owners, applications, and trusted workflow integrations |
| Queue | Azure Service Bus | Durable asynchronous work, retries, and dead-letter handling |
| Operational database | Azure Database for PostgreSQL | Message references, actors, actions, approvals, correlations, and decision versions |
| Evidence objects | Azure Blob Storage | Encrypted, access-controlled evidence; retention and optional immutability policies |
| Keys and secrets | Azure Key Vault | Signing keys and required credentials; rotation and access auditing |
| Hosting | Azure Container Apps and Azure Container Registry; isolated Azure GPU compute only if benchmarks justify it | API/workers and private detector inference with independently sized queues |
| Observability | OpenTelemetry, Azure Monitor, Log Analytics | Sanitized traces, connector health, latency, and operational alerts |
| Infrastructure and CI | Bicep and Azure DevOps pipelines, connected to GitHub | Repeatable deployment, secret-free CI, rollback, and artifact versioning |
| Test tooling | pytest, Playwright, integration and scenario harnesses | Unit, contract, UI, adversarial, and end-to-end validation |

Pin supported dependency versions during Phase 1. Keep one backend codebase, with separate attribution and content-worker processes and queues so slow model inference cannot delay agent evidence. Deterministic attribution requires no GPU. The content classifier may require supervised training and GPU inference; benchmark a small encoder on CPU first and measure larger candidates before selecting Azure capacity. No vector database is required. Model-based detection is itself AI processing and needs approval under the customer's data policy, even when self-hosted. Use approved generation endpoints only for instrumented generation and synthetic test scenarios; do not send real email to public detector demos or consumer AI services.

```mermaid
flowchart TD
    A[Exchange Online test mailboxes] --> B[Graph collector and reconciliation]
    C[Agent tools, approvals and approved generation] --> D[Authenticated action and output evidence]
    E[Microsoft audit and identity sources] --> F[Audit collector]
    B --> G[Service Bus]
    D --> G
    F --> G
    G --> H[Correlation and agent attribution]
    B --> N[Private text normalization and content queue]
    N --> O[Eligibility, provenance matching and content inference]
    D --> O
    H --> P[Independent results and review policy]
    O --> P
    P --> I[PostgreSQL and protected evidence]
    I --> J[Authorized backend API]
    J --> K[Outlook add-in]
    J --> L[Investigator and coverage dashboard]
```

### Microsoft constraints that affect the design

- Outlook notifications support mailbox change monitoring, but ingestion must manage subscription renewal, duplicates, outages, and reconciliation. Message delta synchronization is per folder. [Microsoft change notifications](https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview) and [message delta queries](https://learn.microsoft.com/en-us/graph/delta-query-messages).
- Graph webhooks require a reachable HTTPS endpoint. Validate notifications and durably queue work before acknowledging successful receipt; keep private data stores behind their access boundaries. [Webhook delivery guidance](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks).
- Request immutable message IDs consistently. They are stable within a mailbox, not global identifiers shared between sender and recipient copies. Archive moves and export/re-import can change them. [Immutable identifiers](https://learn.microsoft.com/en-us/graph/outlook-immutable-id).
- A send API response of `202 Accepted` confirms request acceptance, not completed sending or delivery. [Graph sendMail](https://learn.microsoft.com/en-us/graph/api/user-sendmail?view=graph-rest-1.0).
- Microsoft audit evidence is asynchronous. Core-service records are typically available after 60–90 minutes, with no guaranteed availability time. This evidence supports later corroboration; it is not the synchronous authorization path. [Audit availability](https://learn.microsoft.com/en-us/purview/audit-search).
- Graph activity logs require Entra ID P1 or P2 and expose request metadata. A request URI such as `/sendMail` may not identify a particular message, so it must not be joined to a message using only subject and approximate time. [Graph activity logs](https://learn.microsoft.com/en-us/graph/microsoft-graph-activity-logs-overview).
- Exchange Application RBAC grants and Entra application permissions are additive. An unscoped Entra grant can defeat an intended mailbox restriction. Test effective access, including negative cases. [Application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).
- The add-in is not a universal interception layer. Supported client events do not cover arbitrary server-side sends, and a send-button interaction does not prove human operation. [Smart Alerts](https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/onmessagesend-onappointmentsend-events).
- Use current MSAL/nested app authentication on supported clients. Legacy Exchange Online identity and callback tokens are unsupported. The backend must validate access tokens for its own audience and enforce mailbox-level authorization. [Outlook authentication](https://learn.microsoft.com/en-us/office/dev/add-ins/outlook/faq-nested-app-auth-outlook-legacy-tokens).
- Entra Agent ID can supply useful registered identity metadata. Availability, licensing, and integration behavior must be checked in the actual tenant; absence of that identity type is not evidence of human origin. [Agent identities](https://learn.microsoft.com/en-us/entra/agent-id/agent-identities).
- Copilot interaction export can expose supported enterprise prompts/responses, subject to licensing, permissions, and the particular experiences recorded. The reviewed API documentation marks the endpoint as beta; it is an optional POC adapter, not a production dependency. It excludes personal-account interactions and experiences that do not write to that history. A recorded response must still be linked to actual included email text. [Interaction history coverage](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/interaction-export/resources/aiinteractionhistory) and [export endpoint](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/interaction-export/aiinteractionhistory-getallenterpriseinteractions).

### Content-detection strategy and open-source adaptations

Use two complementary paths. **Provenance** establishes what a trusted generation workflow produced and what material was included in the email. **Statistical detection** evaluates eligible text with no reliable generation record, including manual copy/paste from personal assistants. Keep the evidence types visible. A paste event, a visit to an AI website, or an interaction log without a message link is insufficient to prove origin.

| Approach | Planned adaptation | Release boundary |
| --- | --- | --- |
| Controlled generation receipts | Record authenticated generation output, operation type, tenant/user, time, approved transformations, and an inclusion link to the outgoing message | Can support verified content provenance only for material actually linked; generation-only use must not create a mailbox-agent claim |
| Supervised encoder baseline | Fine-tune an appropriately licensed RoBERTa-class encoder on independently labeled business email; calibrate on separate data | First candidate for private, economical inference; must pass unseen-generator and domain tests |
| [Fast-DetectGPT](https://github.com/baoguangsheng/fast-detect-gpt) | Benchmark its probability-curvature method on email; wrap inference, modernize dependencies, recalibrate, and pin scoring models | MIT code; model licenses are separate. Research scores and published benchmark results are not Outlook accuracy guarantees |
| [Binoculars](https://github.com/ahans30/Binoculars) | Benchmark its paired-model scoring; replace the supplied threshold only through calibration and held-out validation | BSD-3-Clause code; model licenses are separate. Its documented fixed threshold depends on the chosen scoring models; do not reuse it as an email guarantee |
| Optional generator-side watermark research | Evaluate only when we control generation and the watermark configuration | Does not detect arbitrary ChatGPT/Claude/Copilot output. [SynthID Text](https://github.com/google-deepmind/synthid-text) is a research reference implementation explicitly not intended for production use; keep it outside required POC dependencies |

Select the simplest candidate that meets the gates. An ensemble is optional and must improve held-out performance at the same false-positive budget; agreement between correlated detectors is not independent proof. A prompted LLM saying that text looks AI-written is not ground truth or the default classifier.

The research supports testing robustness rather than importing headline accuracy. RAID found substantial weaknesses under unseen generators and text transformations. A July 2026 preprint found a strong supervised baseline competitive in-domain but vulnerable to confident errors after domain/generator changes. These findings motivate the evaluation design; they do not establish AgentTrace's performance. [RAID, ACL 2024](https://aclanthology.org/2024.acl-long.674/) and [Rethinking AI-Generated Text Detection, 2026 preprint](https://arxiv.org/abs/2607.03680).

For content provenance, record both the generation event and evidence of inclusion. A signed hash proves integrity of a particular record, not authorship or causality. A model echoing a human prompt, a common greeting, or a shared legal template cannot become verified generated content merely through a string match. Require an authenticated transfer/edit lineage for a verified claim; a distinctive output match without that lineage is corroborating evidence with its ambiguity disclosed. Material changes without a trustworthy transformation record break verified inclusion for the changed region. Do not search other users' private generation histories to resolve a message.

Normalize HTML safely, preserve an offset map, separate regions, check language and minimum useful length, then score bounded text windows. Calibrate the final **message-level** flag after window aggregation; a per-window false-positive rate does not control the error rate of a long email. Production extraction, redaction, truncation, and quantization must match the evaluated pipeline. A failed extractor, unavailable model, unsupported language, or short unprovenanced message yields unknown, not human.

## 3. Evidence, decisions, and acceptance rules

### Required record structure

Each message assessment should include:

- Tenant and mailbox scope, mailbox-local immutable ID, `internetMessageId` where present, and explicit links between different copies. Email-provided identifiers are untrusted inputs and are not unique proof by themselves.
- Direction, observed message state, event time, ingestion time, and observation coverage.
- Actor identity, application/service-principal identity, agent/workflow identity where established, workflow version, and delegated user or owner where available.
- Exact action, affected object, execution ID, validated correlation links, and source request/response references. Record the actor side as sender, recipient, intermediary, or unknown.
- Approval status, approver identity, authority, expiry, and the exact content/recipient version approved.
- Evidence source, issuer, trust status, signature/key reference if applicable, schema version, canonicalization version, and evidence digest.
- Attribution result, send-executor result, evidence completeness, applicable policy, reason codes, decision version, and superseded decision references.
- Independent content assessment for authored and inherited regions: language, extraction/normalization version, eligible length, evaluated scope, provenance references, inference model/weights/tokenizer, calibration and threshold versions, result, and abstention reason.
- Assistance category where evidenced (`draft_generation`, `substantial_rewrite`, `translation`, `basic_correction`, `none_observed`, or `unknown`), generation provider only when established, and any mapped inclusion spans. A statistical score cannot establish these operation/provider fields.
- Content-processing authorization, retention class, restricted source references, and flags identifying omitted attachments, protected text, or incomplete extraction. Do not persist raw text, prompts, or model inputs in ordinary logs.

Store two attribution results: `agent_send_attribution` for the primary sender-side question and `agent_participation` for the broader observed workflow. Each uses `verified_agent`, `suspected_agent`, `unknown`, or `no_agent_observed_in_monitored_path`. The last value is a bounded observation, not proof of a human-only origin. A recipient-side agent read cannot promote `agent_send_attribution`. Keep observed human interaction and verified conventional automation as separate evidence/mechanism fields.

Send executor is separately recorded as `agent`, `human_interaction_observed`, `conventional_automation`, or `unknown`. Human approval is separately recorded as `per_message_verified`, `standing_authorization_verified`, `no_per_message_approval_in_complete_workflow`, or `unknown`. Missing approval telemetry never means that approval did not occur.

Evidence completeness is `pending`, `sufficient_for_stated_claim`, `incomplete`, or `conflicting`. A verified workflow event may support attribution before Microsoft corroboration arrives; the interface must identify that basis and the pending source. Contradictions trigger a new assessment instead of silently preserving certainty.

Store `content_assessment` independently of the agent results. The following states refer to the confirmed draft/rewrite/translation policy, not every use of an AI spelling tool:

| Content state | Meaning and display treatment |
| --- | --- |
| `verified_ai_content` | Trusted generation and inclusion evidence establishes that an identified region contains in-scope AI output; label the evidence scope, not the entire email as AI-authored |
| `suspected_ai_content` | Eligible text crosses a frozen, validated inference threshold; show “AI content suspected — review” and its limitations, never “confirmed” |
| `no_ai_signal_detected` | The supported analysis completed without a qualifying signal; this does not certify human writing |
| `unknown` | Insufficient text, unsupported language, conflicting evidence, extraction failure, unavailable inference, or another named limitation |
| `pending` | Required content processing or evidence is still within its declared observation window |
| `not_evaluated` | Outside authorized scope or disabled by policy; do not represent this as a negative result |

Record authored and inherited region results separately and aggregate them into a message-level content flag without changing `agent_send_attribution`. A verified region does not upgrade unrelated regions. Basic correction, when established, is shown as assistance and does not itself trigger the in-scope content flag. Without provenance, the system may be unable to distinguish correction from substantial rewriting; this uncertainty is tested rather than resolved by inventing an operation label.

The review policy can act on either axis, but it cannot merge their meanings. For example, manual copy/paste can be “agent sending unknown/no agent observed in monitored path; AI content suspected”; an agent sending an existing human template can be “agent send verified; no AI-content signal.” Policy disposition, reviewer correction, and evidence are separate records. A dismissal is not automatically a training label.

### Trust rules

1. Verified attribution requires a trusted agent/workflow identity and a reliable link to the specific action and message. An application name, registration entry, or header alone is insufficient.
2. The controlled execution service, not the model output, creates action evidence. Authentication, runtime access controls, signed records, and independent send observations establish the trust boundary.
3. A signature proves that an issuer signed a claim. It does not prove the claim's truth, that a model was invoked on every execution, or that the issuer is uncompromised.
4. Body style, copied AI text, generic API usage, SPF/DKIM/DMARC success, a fast reply, or an `Auto-Submitted` header must never individually establish agent involvement.
5. Treat untrusted email content and declarations as data. They cannot change policy, invoke tools, update trust, or instruct the detector.
6. Do not convert absent evidence into a human verdict. Do not propagate agent involvement across an entire conversation without action-specific links.
7. Record conflicts and late evidence. Reassessment is append-only and reproducible against a pinned rule version.
8. Scope all claims to the observed path. Compromised trusted signing services or agents using unobserved human sessions remain explicit threat-model limits.
9. Content inference never creates verified agent or verified content status. Verified content requires trusted generation and message-inclusion evidence, with original human material and echoed input distinguished from generated contributions.
10. A score is neither a percentage of AI-authored words nor proof of a provider, intent, misconduct, or absence of human approval. Multiple agreeing detectors do not remove their shared failure modes.
11. Preserve the declared English-only content boundary and separate inherited text from current authorship. Content that cannot be analyzed remains visible as a coverage gap.

### Agent and platform quality gates

These are proposed acceptance targets, not achieved performance or contractual service levels. Phase 0 may tighten them. Any relaxation requires a documented rationale and project-owner decision before the locked evaluation begins.

| Gate | Required target |
| --- | --- |
| G1 Verified-verdict false positives | One-sided 95% upper confidence bound on the false-positive rate no greater than 0.1%, evaluated separately for verified agent sending and verified workflow participation against their respective negative populations; zero errors in at least 3,000 independent negatives is one sufficient binomial case |
| G2 Supported-path agent-send recall | At least 99% observed recall on at least 1,000 independently labeled agent-executed sends spanning approved and autonomous modes, multiple workflows, and varied content; publish the confidence interval and scenario counts; report broader participation recall separately |
| G3 Send-executor correctness | No agent-send verdict for the mandatory agent-draft/human-send, copy-and-paste, or non-AI-automation counterexamples |
| G4 Evidence integrity | No verified verdict from forged, replayed, expired-for-use, wrong-tenant, wrong-message, or mismatched-approval evidence in the mandatory attack suite |
| G5 Agent processing latency | P95 under five seconds from arrival of the last required action evidence to persisted agent result, at the agreed pilot workload; content inference has its own C5 budget and cannot delay this result |
| G6 End-to-end visibility | Report action-to-observation, source lag, observation-to-decision, and decision-to-UI latency independently; no real-time claim for delayed Microsoft audit feeds |
| G7 Reconciliation | All observable events/messages in controlled outage and replay fixtures recovered or explicitly accounted for as unrecoverable coverage gaps; no silent loss or duplicate logical decisions |
| G8 Access isolation | Zero successful cross-mailbox or cross-tenant unauthorized reads, decisions, exports, or approval actions in the authorization suite |
| G9 Pilot operation | At least ten consecutive business days after the last material fix, with no unresolved critical/high release-blocking issue or unexplained data loss |

For the primary agent-send result, a false positive is a message not sent by an agent receiving a verified agent-send verdict. An agent-created draft manually sent by a person is negative for agent sending and positive for workflow participation. For participation, a false positive is a workflow without agent actions receiving a verified participation verdict. Use separate confusion matrices and negative denominators; examples may contribute to both when their labels justify it. Include recipient-side agent reads among the counterexamples for sender attribution. Report `suspected_agent` false alerts and reviewer burden separately; do not hide a noisy suspicion channel behind a low verified-verdict error rate. Overall precision must be reported at observed deployment prevalence and, where useful, at explicitly labeled prevalence scenarios.

For supported-path recall, unknown and pending results after the declared observation window count as misses. Also report recall across all labeled agent scenarios, including uninstrumented paths, so high registered-path recall cannot be marketed as universal recall. Report attribution coverage, unknown rate, and source availability with all headline metrics.

Repeated templates, multiple copies of one email, and correlated executions are not automatically independent observations. Split evaluation by sender, workflow, thread, and time; use grouped or cluster-aware uncertainty estimates when necessary. Do not claim the same bound for a subgroup that lacks adequate evidence. Review samples of unflagged messages as well as alerts.

### Content quality gates and feasibility decision

These are **proposed engineering acceptance targets, not measured results or claims supported by a public benchmark**. The stricter false-positive budget deliberately trades recall for caution. Phase 0 fixes the workload, length eligibility, negative population, and business-usefulness targets before model selection; Phase 8 establishes development feasibility; Phase 12 qualifies a frozen pipeline on untouched data. If the targets cannot be met, report the expanded content requirement as unmet and keep inference in research mode. Do not call a provenance-only or all-unknown result completion of the requested untracked copy/paste detector.

| Gate | Required target |
| --- | --- |
| C1 Controlled content provenance | At least 99% observed recall on at least 1,000 independent, in-scope controlled generation-and-inclusion cases; publish its interval. Zero false verified claims in the mandatory forged/echoed/common-template/wrong-message/cross-user attack suite. Untracked copy/paste is evaluated separately in C3/C4 |
| C2 Content false positives | One-sided 95% upper confidence bound at most 0.1% for the union of user-visible positive content flags on representative content-policy negatives. Evaluate all-assessed and statistically eligible populations separately; zero errors among at least 3,000 independent negatives per claimed population is one sufficient case. Include genuine human writing, basic-correction-only text, and human-written automation templates |
| C3 Useful untracked-content recall | At least 60% observed recall separately for copied original drafts, substantial rewrites, translations into English, and mixed human/AI passages, using at least 500 independent eligible positives per family and publishing 95% intervals. Disable generation provenance for this evaluation. Initial proposed eligibility is at least 100 authored English words, with the mixed family containing a material AI contribution labeled from its creation history. Freeze that definition before the holdout |
| C4 Coverage and all-length usefulness | Complete statistical assessment on at least 50% of readable English authored-body messages in a frozen representative workload, and flag at least 30% of at least 1,000 independent untracked in-scope AI-content positives across all lengths using its predeclared mix/weights. Short/edited/ineligible positives count as misses in this all-length recall. Also report coverage across all mail, including protected and unsupported-language messages. These are minimum usefulness floors, not aspirational marketing accuracy |
| C5 Content latency and failure behavior | P95 at most 30 seconds from readable body availability at ingestion to persisted content result at the agreed load, including queue and inference time. Publish cold-start/burst performance and subsequent provenance-enrichment lag. Timeout/error produces a visible unknown or pending result, never a silent negative |
| C6 Semantic separation | Mandatory cases preserve both axes, grammar-only policy, inherited-content attribution, unsupported-language unknowns, and no provider/word-percentage claims from inference. No content score can produce a verified agent or verified content result |
| C7 Release reproducibility and review | Pin and reproduce extraction, model, weights, tokenizer, thresholds, scope, and decisions. Freeze drift/rollback rules and reviewer workload limits before the pilot. No auto-blocking, disciplinary conclusion, or automatic retraining from detector flags |

The C3/C4 figures are provisional product-usefulness hypotheses to test early, not predictions that current open-source models will achieve them at C2. Report short-message bins (1–49, 50–99, 100–199, and 200+ authored words), source families, editing levels, English writing varieties, domains, and internal/external paths separately. English is a language scope, not a claim to cover every writing style. Treat a materially failing subgroup as a release issue; restrict its supported inference scope or obtain more evidence before making a performance claim. Do not claim a per-subgroup 0.1% bound from a pooled sample that cannot establish it.

False-positive rate is not the probability that a flag is correct. As an illustration, 60% recall and 0.1% false positives imply about 85.8% positive predictive value when 1% of eligible messages contain in-scope AI text, but only about 37.5% when prevalence is 0.1%. These are arithmetic scenarios, not AgentTrace measurements. Publish observed prevalence, precision with uncertainty, false alerts per 1,000 messages, and review time alongside recall. Use probability wording only if calibration is validated for the relevant population; the default UI uses evidence labels rather than an apparent “AI certainty” percentage.

Evaluate the final message-level union of provenance and statistical flags, not merely each detector separately. Include grammar-only examples in the policy-negative evaluation and report their error rate separately from strictly human originals. Repeated windows, templates, forwarded copies, and variants of one prompt are correlated; they cannot inflate the independent sample count. Sample unflagged mail with known sampling probabilities, obtain independent labels, and account for sampling when estimating pilot precision and missed positives. Unresolved real-world labels remain unknown ground truth, not assumed human negatives.

## 4. Phase overview

All phases start as **Not started**. A phase is complete only when its exit criteria have recorded evidence. A plan, implementation, and test result are distinct artifacts.

| Phase | Focus | Primary dependency | Principal exit artifact |
| --- | --- | --- | --- |
| 0 | Both detection scopes, tenant/content feasibility, acceptance contract | None | Approved baseline, capability matrix, and content feasibility decision |
| 1 | Repository, architecture, contracts, local environment, CI | 0 | Reproducible project foundation |
| 2 | Tenant identity, permissions, secure connectivity | 0–1 | Tested access and telemetry configuration |
| 3 | Graph/audit ingestion and private text extraction | 2 | Reliable collection and measured extraction coverage |
| 4 | Evidence ledger, action correlation, content lineage | 1–3 | Reproducible evidence chains for both axes |
| 5 | Independent action/content labels and scenario harness | 0–4 | Versioned corpus with leakage-controlled splits |
| 6 | Agent tools, approvals, controlled generation provenance | 2–5 | Instrumented workflows and output-inclusion evidence |
| 7 | Passive and external evidence adapters | 3–6 | Measured coverage beyond instrumented sends |
| 8 | Content detector benchmarking, adaptation, calibration | 3–7 | Versioned candidate passing development feasibility gates |
| 9 | Independent attribution/content outcomes and review policy | 4–8 | Versioned decision engine with abstention |
| 10 | Outlook and investigator experiences | 9 | Authorized UI showing both results and their basis |
| 11 | Adversarial, privacy, model, and reliability hardening | 2–10 | Closed release-blocking findings |
| 12 | Locked evaluation of both detection tracks | 5, 8–11 | Reproducible evaluation report against G and C gates |
| 13 | Azure shadow pilot, drift monitoring, operations | 12 | Completed pilot and operational evidence |
| 14 | Stakeholder demonstration and release handover | 13 | Tagged POC release and acceptance pack |

## Phase 0 — Establish scope, risk boundaries, and feasibility

**Objective:** Fix both detection definitions, demonstrate usable Microsoft evidence, and assess content-detection feasibility before committing to a full implementation.

**Implementation work**

- Confirm industry, jurisdiction, data classifications, permitted Azure region, retention requirements, and approval owners. Treat these as requirements to resolve, not assumed compliance claims.
- Record target clients, test mailboxes, external test paths, pilot volume, and intended use of results. Define agent sending, broader participation, generated/revised content, inherited material, and basic-correction exceptions independently. Record the confirmed English-first scope and explicit unknown behavior for other languages.
- Inventory Microsoft 365, Entra, Purview, and Azure capabilities and licenses. Verify audit enablement, Graph activity-log eligibility, Entra Agent ID availability, and supported add-in authentication.
- Run a minimal synthetic feasibility spike: manual send, non-AI application send, and agent-tool send. Inspect actual event schemas, identifiers, field availability, and observed lag. Test whether a message/action correlation can be demonstrated without subject/time guessing.
- Time-box an initial content feasibility study to two weeks: use a legally usable, independently labeled development sample, compare an encoder baseline and at least one open-source scorer, measure writing-length distribution and runtime, and test copied drafts, rewrites, English translations, and grammar-only controls. A small spike cannot establish a 0.1% false-positive bound; record learning curves and the corpus still required.
- Check whether approved enterprise generation history or a controlled generation adapter is available. Document exact coverage, licensing, API maturity, content permissions, and whether inclusion can be observed. An unavailable Copilot connector cannot remove unmanaged copy/paste from the statistical requirements.
- Define threats including forged evidence, shared/stolen credentials, compromised issuers, browser automation, delayed logs, detector evasion, model supply-chain changes, poisoned labels, prompt echoes, and misleading self-declarations.
- Freeze metric definitions G1–G9 and C1–C7, the initial minimum-length rule, material-rewrite/mixed-content labeling rubric, supported domains, pilot workload, observation windows, and review capacity. Budget for independent negative samples and a held-out generator/version. Define a separate approval route for any future production enforcement.
- Confirm permitted body processing, model hosting/training, retention, and whether production email may ever become evaluation data. Default to transient inference in the customer's boundary, no training on pilot mail, and no public detector/API uploads.

**Expected outcomes**

- `docs/scope.md`, `docs/threat-model.md`, `docs/acceptance.md`, and a tenant capability matrix using sanitized identifiers.
- A concrete list of supported sources, known blind spots, and unavailable prerequisites.
- A small evidence sample showing a viable exact-message attribution path.
- `docs/content-policy.md`, `docs/content-feasibility.md`, and a costed data/model experiment plan with explicit go/no-go conditions.

**Validation criteria**

- Reproduce at least one send and its associated mailbox evidence in the test tenant.
- Confirm that manual copied AI text is negative for agent participation/sending and positive for content; conventional automation and text origin receive independent labels.
- Review original/corrected/rewritten examples to ensure annotators can apply the confirmed grammar exception. Record ambiguous cases separately.
- Demonstrate a feasible path to obtaining the required human negatives and untracked AI positives without label leakage, unapproved disclosure, or treating model-generated text as human data.
- Measure available audit latency rather than assuming synchronous logs.
- Verify the proposed region, data handling, and access model with the customer technical owner.

**Exit criteria**

- [ ] Project owner accepts the scope, terminology, threat model, and quantitative gates.
- [ ] Microsoft administrator confirms required access and available licenses.
- [ ] An exact-message evidence path is demonstrated, with unresolved gaps documented.
- [ ] Synthetic-data policy and test recipients are approved for the pilot environment.
- [ ] No unresolved dependency prevents the minimum end-to-end path; unavailable optional feeds have explicit fallback/coverage behavior.
- [ ] Content-policy rubric, English boundary, proposed numeric gates, private-processing permissions, and data acquisition plan are recorded.
- [ ] The content feasibility review authorizes a bounded implementation experiment or records a no-go; it does not claim accuracy from the small spike. Any changed usefulness target is documented before model selection and locked evaluation.

## Phase 1 — Create the repository and reproducible foundation

**Objective:** Establish a maintainable codebase in `C:\AgentDetection` that can be built, tested, and deployed from a clean checkout.

**Implementation work**

- Continue the existing working checkout and supplied GitHub repository without overwriting unrelated work. Keep this plan at the repository root.
- Establish the directory structure below, dependency lockfiles, formatting, type checks, unit-test runners, and documented developer commands.
- Define API/event contracts and architecture decisions, including independent action/content results, separate sender/collector/model identities, and minimum-retention content processing.
- Configure local PostgreSQL and a documented development queue adapter. Integration CI must also exercise actual Azure Service Bus semantics before release.
- Add Bicep modules and Azure DevOps CI with workload identity federation where supported. Never commit cloud credentials or real message fixtures.
- Configure secret scanning, dependency and license checks, protected main-branch workflow where available, and pull-request validation. Add a documented alternative if repository-plan features are unavailable.
- Record licenses and hashes separately for research code, model weights, tokenizers, and datasets. Package inference behind a stable adapter and keep model downloads/build steps outside runtime processing of email.

**Expected outcomes**

```text
C:\AgentDetection\
  implementation.md
  apps\api\
  apps\worker\
  apps\content-worker\
  apps\dashboard\
  apps\outlook-addin\
  packages\contracts\
  packages\attribution\
  packages\agent-tools\
  packages\content-detection\
  packages\content-provenance\
  packages\text-normalization\
  experiments\
  tests\unit\
  tests\integration\
  tests\scenarios\
  tests\security\
  tests\e2e\
  tests\evaluation\
  infra\bicep\
  scripts\
  docs\adr\
  docs\runbooks\
```

Large datasets, raw evidence, model weights/checkpoints, production logs, and sensitive test artifacts belong in approved artifact storage, not Git. Commit only safe manifests, synthetic fixtures, and sanitized reports. This repository is public; dataset names, examples, exported prompts, and experiment metadata require the same disclosure review as other committed content.

**Validation criteria**

- A second clean checkout can install pinned dependencies, start local services, run health checks, and execute the baseline test commands.
- CI fails for a deliberately invalid contract, a failing test, and a synthetic secret-scanning fixture.
- Infrastructure validation runs without provisioning unapproved production resources.

**Exit criteria**

- [ ] Repository foundation and architecture decisions are reviewed and committed.
- [ ] Clean-checkout setup and CI are reproducible.
- [ ] Required checks run on a pull request.
- [ ] No credentials, real email, or tenant-specific sensitive values are present in tracked files.
- [ ] Model/data artifacts are versioned outside Git with a documented reproducibility and licensing procedure.

## Phase 2 — Configure tenant access and secure identities

**Objective:** Connect to Microsoft 365 and Azure with explicitly scoped, testable permissions.

**Implementation work**

- Create separate identities for mailbox collection, audit collection, the demo sender, backend workloads, and interactive users as appropriate to the tenant design.
- Scope collector access to approved mailboxes. Grant sender write/send capabilities only to the test-agent identity and mailboxes that require them.
- Validate effective Exchange Application RBAC and Entra permissions together. Remove redundant unscoped grants that defeat the intended restriction.
- Configure Graph notification ingress, Service Bus, PostgreSQL, Blob Storage, Key Vault, managed identities, and controlled network access.
- Enable required audit feeds through approved administrator configuration. Document that audit feeds can expose broader tenant information and restrict collection, processing, and investigator access accordingly.
- Configure Entra application roles for viewer, investigator, and administrator. Plan selected-message authorization for the add-in independently of the collector's broader service permissions.
- Document the additional body-content access needed for detection; metadata-only reads cannot supply it. The content worker receives only authorized scoped text and has no send/delete permission. Separate inference access from access to retained prompts and generation histories.
- Enable an optional enterprise history connector only after its effective permission scope is accepted and tested. Broad tenant history access is not implicitly authorized by mailbox access; use the controlled adapter when narrow access cannot be established.
- Restrict model/data endpoints and outbound traffic. Provision GPU capacity only after the agreed benchmark and budget justify it; inference must not silently fall back to a public service.

**Expected outcomes**

- `docs/permissions-matrix.md` mapping every identity to operations, resources, scopes, consent, and owner.
- Deployable sandbox configuration with access logs and credential rotation procedures.
- Verified connectivity to the selected evidence sources.

**Validation criteria**

- Collector can read an allowed mailbox and cannot read an out-of-scope mailbox.
- Collector cannot send, alter, or delete messages.
- Demo sender cannot operate on an unapproved mailbox.
- Backend rejects expired tokens, wrong audiences, wrong tenants, and unauthorized roles.
- Database, queue, object storage, and signing operations reject unauthorized identities.
- Content workers and optional history connectors cannot read out-of-scope messages or other users' generation records, and cannot upload text to an unapproved endpoint.

**Exit criteria**

- [ ] Positive and negative permission tests pass using effective API calls, not configuration screenshots alone.
- [ ] No tenant-wide mail grant unintentionally bypasses the pilot scope.
- [ ] Signing keys and credentials are absent from application code and routine logs.
- [ ] Microsoft administrator and security owner accept the permission matrix and data flow.
- [ ] Body processing, optional history access, private inference, and retention boundaries have effective negative-access tests.

## Phase 3 — Implement reliable mailbox and audit ingestion

**Objective:** Collect the observable email and Microsoft events with explicit freshness, completeness, and failure states.

**Implementation work**

- Implement mailbox subscriptions with immutable-ID preference, notification validation, lifecycle handling, renewal, and durable queue acknowledgment.
- Add incremental reconciliation for every supported folder. Track checkpoints, folder moves, deleted items, and invalid/expired delta state; document cases where a full scoped resynchronization is required.
- Fetch only required fields. Read authorized bodies for content assessment and retrieve headers/MIME where the evidence need justifies it. Process body text transiently by default; retain an encrypted snapshot only under the agreed evaluation/evidence policy. Handle protected, encrypted, inaccessible, or deleted messages as explicit gaps without bypassing their protections.
- Add Office 365 audit collection and eligible Graph activity-log collection with source-specific checkpoints, rate limits, and lookback overlap.
- Implement idempotency, retries with backoff, `Retry-After` handling, dead-letter queues, queue-age monitoring, and replay tools.
- Store source-event time and ingestion time separately. Identify and exclude the collector's own actions from agent-attribution signals while preserving them for access auditing.
- Do not equate a Sent Items creation notification with proof of the initiating actor. Preserve the observation for later correlation.
- Implement offline HTML/plain-text normalization, Unicode handling, language identification, quote/forward/signature segmentation, source-offset maps, and length eligibility. Do not fetch remote images/links or execute active content. Treat ambiguous segmentation as a limitation rather than silently assigning inherited prose to the author.
- Maintain separate work queues and completion states for agent evidence and content inference. Record the exact content version analyzed and supersede stale results after edits; deduplicate across delivery copies without confusing the sender and recipient.

**Expected outcomes**

- Working collectors, sanitized normalized events, source health endpoints, and reconciliation runbooks.
- An ingestion inventory showing which messages/events were observed, retried, or unavailable.
- A versioned extraction contract and coverage report for body regions, languages, short text, protected content, and omitted attachments.

**Validation criteria**

- Exercise normal sends, replies, forwards, mailbox moves, shared-mailbox behavior, duplicate notifications, and out-of-order updates.
- Simulate subscription expiry, service restart, webhook outage, token expiry, throttling, and malformed notifications.
- Reconcile deliberately missed observable messages without duplicating logical records.
- Verify that a source gap changes coverage state instead of implying no agent activity.
- Test HTML/plain-text equivalents, nested quotes, long disclaimers, mixed languages, short replies, malformed/large bodies, and content updates. Review extraction correctness against a labeled fixture set and measure inference on the actual production-normalized text.

**Exit criteria**

- [ ] Controlled outage/replay fixtures pass G7 with explicit accounting for unrecoverable gaps.
- [ ] Subscription, checkpoint, and dead-letter health are visible.
- [ ] Notification handlers persist accepted work before acknowledgment.
- [ ] Content access and retention follow the approved minimum-data policy.
- [ ] Authored/inherited regions, excluded content, version changes, and extraction failures are represented correctly; raw bodies do not leak into logs or queue diagnostics.

## Phase 4 — Build the evidence ledger and correlation model

**Objective:** Link actions and generated content to the correct message while preserving their different evidence requirements.

**Implementation work**

- Implement the record structure in Section 3, schema migrations, tenant/mailbox boundaries, and append-only decision history.
- Separate sender/recipient mailbox copies and maintain explicit mappings. Do not treat immutable IDs or `internetMessageId` as universally unique across all sources.
- Implement exact identifier joins where supported. Mark time/subject/recipient similarity as candidate correlation only, never sufficient for a verified attribution.
- Define a versioned canonical representation of approved content, recipients, and attachment digests. Hash that representation; preserve transport observations separately because Exchange can transform MIME.
- Implement trusted issuer enrollment, authenticated evidence submission, signature verification, key rotation, revocation handling, event uniqueness, and replay detection.
- Protect persisted evidence against application-level modification using least privilege, append-only writes, audit trails, and tested storage policies. A database hash by itself is not an immutable ledger.
- Define conflict handling, evidence invalidation, and historical reassessment when an issuer or key becomes untrusted.
- Store generation receipts, optional before/after references, operation category, output digest, authenticated insertion/transfer records where available, and mapped inclusion regions separately from mailbox action events. A user generating text outside Outlook and copying it manually must not acquire an agent-send label through this schema.
- Use versioned normalization and matching rules. Exact matches, trusted edit lineage, fuzzy similarity, and unsupported links must remain distinguishable. A common phrase or semantic similarity alone never establishes verified content provenance; replayed output can be legitimately reused only with new message-inclusion evidence.
- Protect content fingerprints and matches as sensitive data. Consider tenant-keyed digests where appropriate; hashing does not anonymize short or predictable email. Do not perform global cross-user matching without separately authorized access.
- Document replay limits: exact model re-execution requires an approved retained input snapshot and pinned artifacts. After input deletion, retain authorized decision metadata and digests, but do not claim full re-execution is possible. Release evaluation uses retained, permitted test inputs for reproducibility.

**Expected outcomes**

- `docs/evidence-schema.md`, `docs/correlation-rules.md`, and a versioned evidence API.
- A retrievable chain from a synthetic workflow event to a specific message and decision input.
- Separate content-lineage records and a retention/replay matrix distinguishing auditable metadata from re-executable model inputs.

**Validation criteria**

- Test identical subjects, identical bodies, concurrent sends, copied messages, forward chains, duplicate message IDs, mailbox moves, and archive boundaries.
- Verify that wrong-message, wrong-tenant, altered, stale-for-use, and replayed evidence is rejected or downgraded.
- Reconstruct the same evidence view from stored events after a service restart.
- Test echoed human prompts, common greetings, copied disclaimers, altered output, AI templates reused in different messages, and forged generation receipts. Content overlap without sufficient lineage must not become verified origin.

**Exit criteria**

- [ ] Exact joins and uncertain candidate joins are distinguishable in storage and APIs.
- [ ] Signature and replay tests pass without promoting untrusted declarations.
- [ ] Canonicalization and transport-mapping limitations are documented and tested.
- [ ] Every persisted decision input has a traceable source and schema version.
- [ ] Content-lineage and action-lineage tests pass independently; snapshot retention and replay limits are explicit.

## Phase 5 — Establish independent ground truth and scenario generation

**Objective:** Create independently labeled action and content datasets before optimizing either detector.

**Implementation work**

- Build a controlled harness that runs human-operated, copied-text, conventional-automation, human-approved-agent, and autonomous-agent scenarios against test mailboxes.
- Record ground truth through a separate test controller and scenario manifest. Test labels must not be supplied to the detector or inferred from its output.
- Cross action and content labels deliberately: human/AI wording sent by humans, agents, and conventional automation. Use matching text and overlapping infrastructure across actor classes. Include AI and non-AI executions through the same application identity where practical; style, headers, and app names must not leak the target label.
- Add agent-draft/human-send, sender-side and recipient-side agent-read-only actions, human-edited agent drafts, failed sends, canceled approvals, shared mailboxes, and external unknown cases. Label send execution and participation independently.
- Plan a browser-operated uninstrumented-agent case to demonstrate the visibility boundary; do not omit difficult positives from overall recall reporting.
- Create development/training, calibration, and locked evaluation splits separated by writer, workflow, sender, thread, template/prompt family, and time. Hold out a generating model/version or family and a business domain to test shift. Near-duplicate and source-corpus checks must span all splits.
- Obtain genuine human-written English email with permitted use and credible creation history, including current business writing, formal/templates, non-native English varieties, concise replies, and technical/legal language. Public historical corpora can supplement but cannot alone represent current pilot mail. Never label model paraphrases or “humanized” synthetic text as human originals.
- Generate independently documented examples from ChatGPT, Copilot, Claude, and at least one additional model family using synthetic inputs. Record provider, exposed model/version, generation time, prompt family, and edit history. Do not infer an unexposed underlying model. Include manual copy/paste with every provenance source disabled for its statistical test.
- Add substantive rewrites, translations into English, grammar-only corrections, mixed passages, multiple editing levels, quoted AI content, human-written template echoes, and short-text bins. Native Copilot modifying an Outlook draft is evaluated for observed workflow participation separately from text-only assistant use followed by manual paste.
- Have two independent reviewers apply the policy rubric to a sample of original/output pairs and adjudicate disagreements. Label exact generation/inclusion spans only where creation history supports them; an uncertain label stays outside definitive truth sets.
- Keep non-English/mixed-language, attachment-bearing, protected, and uninstrumented cases to test explicit unknowns and overall coverage, even though their unsupported text is not scored as English.

**Expected outcomes**

- Versioned scenario matrix, safe fixture manifests, label definitions, and a reproducible execution harness.
- A dataset expansion plan sufficient for G1/G2 and C1–C4, with licensing, independence, subgroup coverage, and acquisition effort recorded. Some independently valid scenarios can serve multiple metrics, but denominators remain separate.

**Validation criteria**

- A reviewer can verify the action provenance of sampled labels without consulting AgentTrace decisions.
- A reviewer can verify content-generation/edit history independently of detector scores, marker headers, and provenance connectors being tested.
- Identical text sent through different workflows receives different ground truth where appropriate.
- No filenames, hidden headers, synthetic domains, scenario names, or evaluation labels leak the target class into the detector.
- Ambiguous labels are quarantined for adjudication instead of forced into the test set.
- The short-message and edited-positive families remain in the all-length denominator; quote removal and label definitions do not hide difficult copy/paste cases.

**Exit criteria**

- [ ] All mandatory scenario families have executable cases and reviewed expected outcomes.
- [ ] Ground truth is independent of detector rules and self-reported email headers.
- [ ] Split and leakage checks pass.
- [ ] Locked evaluation data is access-controlled and not used for rule tuning.
- [ ] Required content families, human/grammar-only negatives, writer diversity, and source/version holdouts have a documented acquisition and review path.
- [ ] The policy rubric and independent review resolve the distinction between basic corrections and substantial rewriting for the definitive labels.

## Phase 6 — Instrument agent actions, approvals, and content provenance

**Objective:** Produce trustworthy action evidence and controlled generation/inclusion evidence without confusing generation-only assistance with mailbox-agent execution.

**Implementation work**

- Implement an authenticated tool boundary for mailbox reads, draft creation, recipient changes, approval requests, and sends.
- Associate each execution with a registered workflow, actor identity, owner, workflow version, and permitted mailbox scope. Shared applications require per-execution context; an app ID alone cannot select the agent verdict.
- Record events in the execution service after validating the caller and observed operation. Do not accept a model-generated `is_agent` flag as proof.
- Bind per-message approval to the exact payload version, recipient set, mailbox, operation, approver authority, and validity period. Any relevant mutation invalidates approval.
- Distinguish standing authorization from per-message approval. Autonomous test sends must still operate within their approved scope and test recipient allowlist.
- Prefer create-draft-then-send with retained immutable identifiers for the instrumented path. Correlate the later Sent Items observation and Microsoft request identifiers.
- Handle ambiguous send outcomes safely. Do not blindly retry a timed-out send and produce duplicate real email; reconcile or require explicit recovery. Do not promise exactly-once delivery from an API that does not provide it.
- Authenticate the approval action, protect against CSRF/replay, and separate the agent identity from the human approver. Approval records attest an authorized interaction, not absolute biological-human proof.
- Add a generation-only adapter using approved model access and synthetic test inputs. Capture authenticated generation receipts separately from email actions, with model identity only when exposed, operation category, original-input references, output version, and retention controls.
- Implement a controlled insertion/transfer path that can bind material generated output to a draft and later observed message. Exclude echoed prompt material and boilerplate from generated-content claims. Preserve approved transformations and invalidate lineage for unobserved substantive edits.
- Demonstrate both monitored insertion and ordinary manual copy/paste. If manual paste has no authenticated transfer lineage, an output match is corroboration rather than verified origin; the statistical path still assesses eligible text. A generation-only helper must have no mailbox send rights.

**Expected outcomes**

- A reusable agent-tool package, protected approval service, and two working demo workflows.
- Complete execution records for approved and autonomous sends, plus rejected or canceled operations.
- A generation-only workflow and separate examples of verified inclusion, corroborating matches, and untracked copy/paste.

**Validation criteria**

- Run genuine AI workflows using synthetic data and an approved model endpoint.
- Change recipients, attachments, and body after approval and verify that prior approval cannot authorize the changed send.
- Test repeated approval, expired approval, wrong approver, failed send, timeout, and replay.
- Verify that agent-created drafts sent manually remain distinct from agent-executed sends.
- Verify that generation outside Outlook followed by manual paste has no agent-action verdict merely because generation was logged. Test unchanged, partially copied, edited, and entirely replaced output.
- Verify that a generated reply which simply echoes human input or a common template does not establish newly generated authorship through matching alone.

**Exit criteria**

- [ ] Both approved and autonomous workflows produce an exact-message evidence chain.
- [ ] Mandatory approval attacks and duplicate-send recovery cases pass.
- [ ] API acceptance, observed sent state, and delivery confirmation are separate states.
- [ ] Collected evidence supports only the actions actually observed.
- [ ] Content-provenance integrity tests pass and trusted inclusion is separated from plain output similarity.
- [ ] Generation-only, agent-draft/human-send, and agent-send workflows retain their independent content and action labels.

## Phase 7 — Add passive attribution and external evidence handling

**Objective:** Expand visibility beyond the controlled tool path without overstating what recipient-side evidence can establish.

**Implementation work**

- Import registered agent/application metadata from approved tenant sources, including Entra Agent ID when available, and maintain owner-reviewed mappings.
- Correlate application and mailbox audit activity only where a reliable object/action link exists. Keep unmatched or ambiguous API activity available for investigation without assigning it to a guessed email.
- Support a cooperating external sender through a documented trust profile: issuer enrollment, keys, signed statement format, message binding, replay handling, and revocation.
- Parse automation and attribution headers as declarations with provenance. Verify any relevant signature coverage and trusted issuer before elevating a claim.
- Treat SPF, DKIM, and DMARC as authentication context, not AI-agent proof. Inspect only authentication results from established trusted sources.
- Record browser/session automation, SMTP paths, shared connectors, unsupported integrations, and protected messages as measured coverage limits.
- Keep any experimental anomaly features behind flags; they may support a suspicion workflow only after separate validation and cannot create verified status.
- Spike optional Copilot enterprise interaction export only within the approved POC scope. Verify actual returned experiences, user scoping, retention, lag, API version, and license behavior in the tenant. Keep it disabled where broad permissions are unacceptable; record that personal assistants remain outside this source.
- Require an explicit inclusion link before promoting generation-history evidence to verified content. A time-nearby AI interaction, a matching user account, a website visit, or an untrusted “AI-generated” header is not sufficient.
- External content can receive a statistical assessment within the validated English scope even when actor attribution is unknown. Evaluate external and internal populations separately; trustworthy external content claims require an enrolled issuer and verified message/region binding.

**Expected outcomes**

- Passive telemetry adapters, external declaration parser, trusted-partner test integration, and source-specific coverage matrix.
- Visible distinctions between verified workflow evidence, declared evidence, candidate correlations, and unknowns.
- A per-source table separating content-history coverage from mailbox-action coverage, with unsupported and optional connectors clearly marked.

**Validation criteria**

- Send forged, stripped, duplicated, forwarded, and modified declarations through the external test path.
- Confirm that a known application identity used by non-AI automation does not become an automatic agent verdict.
- Demonstrate an undisclosed external or browser-operated agent case and report its actual detection limit.
- Confirm that third-party declarations cannot enroll their own issuer or change trust policy.
- Confirm that a recorded assistant conversation never labels an unrelated email and that external text scoring does not create an external-agent claim.

**Exit criteria**

- [ ] Untrusted declarations cannot produce verified attribution.
- [ ] Passive correlations expose their exact scope and ambiguity.
- [ ] At least one cooperating external case works, or its unavailable prerequisite is explicitly excluded from release claims.
- [ ] Coverage documentation includes unsupported and evasive paths, not only successful examples.
- [ ] Optional enterprise history is either validated within its scope or disabled with an explicit limitation; neither outcome removes untracked copy/paste from required testing.

## Phase 8 — Build, adapt, and calibrate the content detector

**Objective:** Determine whether private statistical detection can usefully flag untracked AI content at the required false-positive rate, and produce a reproducible candidate if it can.

**Implementation work**

- Benchmark a small supervised encoder against Fast-DetectGPT and Binoculars using identical development splits and production text extraction. Include a no-inference/provenance-only baseline to show what statistical detection adds. Record licenses, model sizes, hardware, memory, throughput, and cost per 1,000 messages.
- Fine-tune only on approved training data. Keep generator families, prompt/template families, writers, and time partitions separated as specified in Phase 5. Do not use the locked evaluation set to select a model, minimum length, threshold, or ensemble.
- Implement language/length/domain eligibility and explicit abstention. Evaluate the proposed 100-word minimum against shorter bins, but retain every short in-scope positive in C4 reporting. A longer threshold requires an explicit revised coverage claim before the final holdout, not a hidden filter.
- Test substantive rewriting, human editing, AI rewriting of human prose, English translation, small AI insertions, formal human templates, and grammar-only controls. A high score cannot by itself distinguish a rewrite from a grammar operation or identify the source assistant.
- Calibrate on held-out calibration data and choose a high-precision threshold subject to C2, then evaluate C3/C4 usefulness on separate development validation data. If using multiple windows/models, calibrate their final message-level combination; do not multiply supposed confidences or reuse research defaults.
- Assess reliability and base-rate sensitivity. Retain raw scores for authorized analysis, with model/threshold versions; expose a probability only if independently calibrated for the claimed population. Measure source/domain/language-style subgroups and held-out generator performance.
- Package the selected model as an isolated, bounded inference worker with private model artifacts, token/size/time limits, batching, timeouts, and explicit unavailable states. Keep weights cached under approved controls and prevent runtime downloads driven by message content.
- Test numerical effects of quantization, ONNX conversion, tokenizer changes, and HTML/redaction preprocessing before adopting them. Any change that affects predictions requires recalibration and fresh validation.
- Define a model card and drift procedure: monitor length/language/score distributions and independently reviewed errors; investigate changes rather than declaring drift from scores alone. No self-training from inferred labels and no automatic threshold lowering to improve recall.

**Expected outcomes**

- `docs/content-benchmark.md`, `docs/content-model-card.md`, pinned candidate artifacts, inference contracts, and a calibration report showing recall versus false positives and coverage.
- A documented selection or no-go decision, including cases where no tested candidate meets the requested low-false-positive usefulness tradeoff.

**Validation criteria**

- Reproduce development predictions and runtime measurements from pinned artifacts using permitted retained test inputs.
- Meet the development targets corresponding to C2–C5 on independent development validation data, with confidence/sample-size limits visible; this does not replace Phase 12 qualification.
- Demonstrate statistical assessment of manual copy/paste with all generation provenance disabled. Show basic-correction-only controls and unknown behavior for unsupported/too-short inputs.
- Verify that neither model failures nor malformed inputs produce a negative default or block the agent-attribution worker.

**Exit criteria**

- [ ] A selected candidate meets the recorded development feasibility gates, including useful recall and coverage at the low false-positive threshold.
- [ ] Code, weights, tokenizer, calibration, preprocessing, aggregation, eligibility, and runtime configuration are pinned and licensed for the proposed use.
- [ ] Known subgroup, length, editing, and generator limitations are recorded with matching abstention and release-claim boundaries.
- [ ] Private inference, timeout handling, and independent worker operation pass integration checks.
- [ ] If no candidate qualifies, this phase stays incomplete for the expanded MVP. Findings and any revised proposal are recorded; provenance-only delivery is not presented as solving untracked copy/paste.

## Phase 9 — Implement independent outcomes and review policy

**Objective:** Convert evidence into stable, explainable outcomes while preserving uncertainty and minimizing false accusations.

**Implementation work**

- Implement the status model, trust rules, and versioned reason codes defined in Section 3.
- Use deterministic rules for verified action/content provenance. Use the selected calibrated content detector for eligible untracked text; keep optional agent-anomaly scoring separate and unable to create verified status. Content detection is now a required MVP track, not an optional scoring experiment.
- Separate agent participation, send executor, human approval, authored/inherited content assessments, assistance category, evidence completeness, and business-policy disposition.
- Define pending-evidence windows using measured source behavior. Missing evidence after a window becomes incomplete/unknown, not a human verdict.
- Add conflict resolution and append-only reassessment. Preserve the original decision, evidence set, and rule version.
- Keep observation and enforcement separate. Optional tool-boundary prevention uses explicit authorization rules; suspicion alone does not block ordinary Outlook delivery.
- Return evidence references and bounded explanations through the API. Avoid unsupported numerical confidence and any biological-human certification.
- Define review priority and notification behavior independently of detection truth. A verified agent event, verified included AI output, and statistical content suspicion need different explanations. A basic-correction event does not erase other evidence that the underlying draft was generated.
- Bind assessments to content versions and pipeline versions. Publish agent results without waiting for inference; update content results and inherited-region notices independently as evidence arrives.
- Measure false alerts and burden for the final combined review policy, including any optional suspicion channel. Do not advertise its error rate as 0.1% merely because each component has a separate gate; freeze the combined alert budget and reviewer capacity in Phase 0.

**Expected outcomes**

- A reproducible decision engine, policy configuration, and machine-readable decision API.
- An explanation for each result that states what is established and what remains unresolved.

**Validation criteria**

- Replay the development scenario suite, including conflicting sources and late corroboration.
- Verify that text changes alone cannot change actor attribution when workflow evidence is unchanged.
- Verify that non-AI app sends, forged headers, and human-sent AI text cannot independently produce verified-agent results.
- Verify that the same versioned evidence and rules reproduce the same result.
- Verify manual AI copy/paste can produce a content flag without agent attribution, and agent-sent human wording can produce agent attribution without a content-positive inference.
- Verify basic correction, quoted AI text, conflicting provenance, detector timeout, and unsupported-language cases preserve their distinctions through API round trips.

**Exit criteria**

- [ ] Mandatory semantic and trust-rule tests pass.
- [ ] Every verdict includes reason codes, source references, and decision version.
- [ ] Unknown, pending, conventional automation, and approval distinctions survive API round trips.
- [ ] Enforcement is disabled by default outside the explicitly controlled test-agent boundary.
- [ ] C6 passes and the combined review policy exposes its own error/burden measurements without collapsing the two detection axes.

## Phase 10 — Build Outlook, investigator, and coverage experiences

**Objective:** Show separate agent-action and content-origin assessments in Outlook and the investigator dashboard, with clear evidence and uncertainty.

**Implementation work**

- Build an Outlook read-pane add-in with two independent result cards: agent actions/send/approval, and AI-content assessment with provenance or inference basis. Show the analyzed text scope, unsupported language/length reasons, and basic-assistance observations. Flags are product UI/review records; mailbox categories, subject modifications, and universal pre-send blocking are not required.
- Use MSAL with supported nested app authentication and a tested fallback where required by the selected client. Authorize backend access with an access token for the backend audience.
- Map the selected item to the correct mailbox/message context. Validate access server-side; never trust a mailbox or message ID supplied by the browser as authorization.
- Build dashboard views for message search, action timeline, source evidence, review/correction, registered integrations, and operational coverage.
- Add filters for content-only, agent-only, both, inherited AI content, unknown, pending, and correction-only observations. Show model/threshold versions to authorized investigators and distinguish exact provenance spans from merely scored windows.
- Add role-controlled evidence exports with data minimization and export auditing. Avoid arbitrary recipient access to internal approver names or sensitive workflow details.
- Show pending Microsoft corroboration, unavailable sources, and unknown outcomes without labeling the message as safe, human, or malicious.
- Explain “suspected” in plain language, support reviewer dismissal/correction and reasons, and preserve the original assessment. Do not show model scores as percentages of AI-written words. Review decisions enter a curated adjudication process before any later training use.
- Design accessible keyboard navigation, readable status text, and non-color-only indicators. Sanitize message-derived HTML and links.

**Expected outcomes**

- An admin-deployable add-in manifest, working Outlook panel, and investigator/coverage dashboard.
- A coherent product demonstration based on actual backend evidence.

**Validation criteria**

- Test Outlook on the web and new Outlook for Windows against the declared supported versions.
- Exercise cross-mailbox guessing, wrong-tenant tokens, revoked access, stale decisions, empty results, and evidence delays.
- Confirm UI results match backend decision records and distinguish agent drafting from agent sending.
- Confirm content-only copy/paste flags are visible without agent accusations; short/non-English inputs display unknown, and inherited AI content does not label the current author as its generator.
- Run accessibility and end-to-end tests for all principal user journeys.

**Exit criteria**

- [ ] Authorized users can inspect a real test message end to end in both supported clients.
- [ ] Unauthorized users cannot retrieve its assessment or evidence.
- [ ] No UI wording converts unknown into human or approval into absence of agent activity.
- [ ] Every displayed demo status is backed by a retrievable decision record.
- [ ] Users can distinguish verified provenance, statistical suspicion, basic corrections, and unknown content without reading an engineering document.

## Phase 11 — Harden security, models, evidence integrity, and reliability

**Objective:** Test the system against mistakes and adversaries before measuring release performance.

**Implementation work**

- Exercise the threat model with forged headers, injected instructions, altered receipts, signer substitution, replay, cross-tenant IDs, approval mutation, malicious HTML, and ambiguous message correlation.
- Test key rotation, key compromise/revocation procedures, issuer removal, and historical decision reassessment.
- Test database migration, backup restoration, queue replay, poison messages, expired subscriptions, prolonged source lag, and interrupted deployments.
- Validate egress controls: email content may enter only the configured private inference pipeline, and cannot select arbitrary models/endpoints, invoke tools, alter trust, fetch URLs, or override detector instructions. No external detector fallback is allowed.
- Test model/weight/tokenizer tampering, unsafe artifact loading, cache isolation, content leakage in exceptions, excessive input sizes, GPU/CPU exhaustion, and cross-tenant reuse of generated-output fingerprints. Pin trusted artifact digests and avoid executing unreviewed remote model code.
- Run content evasion and false-positive stress cases: paraphrasing, editing, translation, Unicode changes, mixed passages, repeated boilerplate, and human text deliberately matching common AI style. Report statistical misses/errors honestly; such inputs must never escalate suspicion to verified provenance.
- Scan dependencies, container images, infrastructure configuration, secrets, and permissions. Record findings and remediation evidence.
- Perform sustained load testing at the Phase 0 pilot workload and a documented burst level; measure source lag separately from application processing.
- Run data-retention deletion tests and verify that backup/evidence retention behavior matches the agreed policy.
- Inspect prompts, raw/normalized bodies, generation outputs, model traces, experiment artifacts, and exports for unintended persistence. Document how deletion affects exact decision re-execution; preserve permitted release-test inputs separately from live-mail retention.

**Expected outcomes**

- Security test report, reliability report, incident procedures, and a closed release-blocking issue list.
- Tested backup, restore, replay, revocation, and rollback procedures.

**Validation criteria**

- G3, G4, G7, and G8 pass across the mandatory suite.
- No content injection or malformed evidence can escalate trust or execute operations.
- Restore a representative environment and reproduce selected decisions from retained evidence.
- Meet G5 at the agreed workload and publish any performance bottlenecks.
- Meet C5 independently, including queue wait; verify inference outages leave agent processing responsive and content state explicit. C6/C7 semantic and artifact controls must survive attack and recovery cases.

**Exit criteria**

- [ ] All critical/high release-blocking security and reliability findings are resolved.
- [ ] Restore, replay, key rotation, and rollback have been executed successfully.
- [ ] Log and export review finds no prohibited secrets or message content.
- [ ] Residual limitations have an owner, mitigation, and explicit release-claim impact.
- [ ] Model artifact, content egress, retention/deletion, and inference-isolation tests pass.

## Phase 12 — Qualify both detection tracks on locked evaluation data

**Objective:** Establish credible, reproducible performance evidence for the supported deployment scope.

**Implementation work**

- Freeze rules, correlation configuration, observation windows, content policy, normalization, language/length eligibility, model/weights/tokenizer, calibration, aggregation, thresholds, and dataset manifests before evaluation. Commit a signed-off evaluation protocol before accessing held-out labels.
- Evaluate at least 3,000 representative independently labeled negatives for each verified attribution target and 1,000 agent-executed sends, subject to the independence and scenario requirements in Section 3. Keep participation and send-execution labels and denominators separate.
- Include human text, copied AI text, non-AI automation, shared applications, approved agents, autonomous agents, draft-only participation, and uninstrumented positives.
- Evaluate C1's controlled inclusion cases and C2's human/grammar-only negatives separately from untracked content. Evaluate at least 500 independent eligible positives per C3 family, and at least 1,000 independently labeled all-length content positives for C4 using the predeclared workload mix/weights. Do not substitute long generated essays for short business emails.
- Run an explicit provenance-disabled copy/paste test so managed generation receipts cannot mask weak statistical detection. Publish new-generator/domain results, internal versus external results, length bins, edited/mixed text, and grammar-only errors.
- Measure verified-verdict false positives, suspicion false alerts, supported-path agent-send recall, broader participation recall, overall scenario recall, send-executor errors, precision, abstention, and source coverage. Recipient-side agent processing must not inflate sender-side recall.
- Publish independent action/content confusion matrices and the final combined review-policy false-alert rate. Measure content-policy errors at message level after region/window aggregation, conditional recall on eligible content, all-length recall, abstention, all-mail coverage, latency, memory, cost, and reviewer workload. A missed supported positive remains a miss even if the pipeline abstains.
- Publish one-sided confidence bounds for false positives and confidence intervals for recall/precision using justified binomial or cluster-aware methods.
- Evaluate key subgroups and out-of-scope paths separately. Do not average away a failure in a required counterexample class.
- Investigate all verified false positives and a representative sample of false negatives, unknowns, and unflagged messages. A fix after examining the holdout requires a new held-out evaluation or a clearly labeled exploratory result.
- Publish ablations for provenance-only, statistical-only, and combined content assessment. Verify that receipt/header availability, provider identifiers, template families, or sender metadata did not leak statistical labels.

**Expected outcomes**

- `docs/evaluation-report.md`, a sanitized release scorecard, exact dataset/run manifests, and reproducible analysis commands.
- A precise statement of supported detection coverage and non-supported claims.

**Validation criteria**

- G1 and G2 pass with their required denominators and uncertainty reporting.
- G3 and G4 remain satisfied on the locked suite.
- C1–C7 pass for the declared English content scope, including useful untracked copy/paste recall and coverage at the accepted false-positive budget.
- Unknown/pending supported positives after the fixed window are counted as misses.
- Results can be recomputed from the stored predictions and independent labels.

**Exit criteria**

- [ ] G1–G8 are supported by recorded evidence for the declared scope.
- [ ] C1–C7 and the combined review-policy budget have supporting evidence, with all-length copy/paste results presented alongside eligible-only results.
- [ ] No holdout leakage, hidden exclusions, or unsupported independence assumptions remain.
- [ ] Required scenario failures are resolved and re-evaluated on uncontaminated data.
- [ ] If a numerical gate is unmet, qualification remains incomplete; results are not relabeled as a pass.
- [ ] Project owner accepts the measured scope and the exact wording of performance claims.
- [ ] Agent qualification and content qualification are reported separately; success in one cannot turn a failure in the other into full MVP acceptance.

## Phase 13 — Run the Azure shadow pilot and establish operations

**Objective:** Demonstrate sustained behavior in the customer environment while keeping ordinary email delivery unaffected.

**Implementation work**

- Deploy the pinned release candidate through Bicep and CI to the agreed Azure region and pilot resource group.
- Enable only the approved mailbox and investigator groups. Keep general mail blocking and quarantine disabled.
- Run the shadow pilot for at least ten consecutive business days after the last material correction. Collect representative alerts, unflagged samples, unknowns, and source-health observations.
- Monitor source lag, both queues, subscription renewal, retries, agent/content coverage, length/language/score distributions, decision revisions, investigator workload, model runtime, and cloud cost.
- Set Azure budget alerts, log retention, evidence retention, and capacity limits. Document the tested workload and compute/storage sizing.
- Exercise operational ownership: connector outage, dead-letter recovery, permission revocation, agent disablement in the controlled test environment, and customer support escalation.
- Validate whether delayed attribution remains useful to the target business workflow. Separately assess any demand for pre-action control at the agent boundary.
- Review content false positives and missed positives with independent evidence where available, including grammar-only and short-copy cases. A reviewer guessing authorship or agreeing with a score does not establish ground truth. Report unresolved labels and sampling uncertainty.
- Detect material shifts in message mix or generation tools; investigate with a fresh labeled sample. Suspend user-visible inference for affected unsupported cohorts if quality cannot be defended, without inventing human verdicts. Roll back models and thresholds independently of the action engine.
- Keep inference flags in investigator shadow review until qualification and customer acceptance support exposing them to pilot users. No online training on pilot email and no threshold changes without renewed validation. A ten-day run alone does not establish a 0.1% error bound if its labeled sample is too small.

**Expected outcomes**

- Pilot report, operational dashboards, runbooks, cost baseline, and a customer-reviewed known-limitations register.
- An evidence-backed decision on whether the POC is ready for stakeholder acceptance or needs another iteration.

**Validation criteria**

- G9 passes, and observed pilot behavior does not invalidate G1–G8, C1–C7, the combined alert budget, or the stated scope.
- All pilot findings are reproducible or explicitly recorded as unresolved.
- Reviewer workload and unknown coverage are visible; unflagged sampling supports detection-quality assessment.
- Restore and rollback procedures remain valid in the deployed environment.

**Exit criteria**

- [ ] Ten-business-day observation period is complete after the last material fix.
- [ ] No unresolved critical/high issue, unexplained loss, or unauthorized access remains.
- [ ] Pilot data handling, retention, cost, and operational ownership are accepted.
- [ ] Any changes to supported scope or performance claims are reflected in the release documentation.
- [ ] Model drift/reversion procedures, review capacity, unknown coverage, and content-specific costs are measured and accepted; a material content regression reopens qualification.

## Phase 14 — Deliver the demonstration and accepted POC release

**Objective:** Provide a convincing, honest demonstration and a reproducible handover package.

**Implementation work**

- Prepare a short presentation covering the two independent product questions, private evidence/inference architecture, live Outlook workflows, separate quality scorecards, unknown coverage, and deployment permissions.
- Demonstrate matching text across different send mechanisms, plus human-written and AI-written text through the same mechanism. Include manual AI copy/paste with no provenance, approved-generation insertion, substantial rewrite, English translation, grammar-only assistance, agent-sent human wording, approved agent send, and autonomous agent send.
- Include a short copied message, mixed passage, inherited AI quote, unsupported language, forged external claim, uninstrumented agent, and detector/source outage. Show measured outcomes even when they are unknown or a statistical miss; do not cherry-pick only long detectable drafts.
- Use real test-mailbox operations for the live demonstration. Any replay used to illustrate delayed audit enrichment must be clearly labeled and linked to its original test evidence.
- Publish the source, infrastructure templates, add-in manifest, permission matrix, schema documentation, runbooks, evaluation report, and sanitized demo artifacts.
- Create a versioned release tag and document the exact commit, build, rules, schemas, infrastructure, model/weights/tokenizer, extraction/calibration/threshold versions, and evaluation manifests. Distribute model artifacts only under their applicable licenses and approved access controls.
- Record customer acceptance and a separate production-readiness backlog for broader integrations, jurisdiction-specific controls, operational scale, and any enforcement capability.

**Expected outcomes**

- A deployable, demonstrable AgentTrace MVP/POC with a documented acceptance pack.
- A clear separation between achieved capabilities, measured limitations, and future work.

**Validation criteria**

- Rehearse the complete demonstration from a clean seeded environment.
- A reviewer can trace each displayed result to the actual message, evidence, and decision version.
- A second engineer can deploy the tagged release and reproduce the principal scenarios and evaluation analysis.
- Every numerical slide claim matches the final evaluation report and scope.
- A stakeholder can explain why content suspicion is not proof of an agent send, why correction-only assistance is distinct, and why unknown does not mean human.

**Exit criteria**

- [ ] All earlier phase exits have linked evidence and recorded acceptance.
- [ ] Stakeholder demo succeeds, including uncertainty and attack cases.
- [ ] Source, deployment assets, documentation, and sanitized validation reports are committed and released.
- [ ] Customer technical owner accepts the POC against the agreed gates.
- [ ] Remaining production work is explicit; POC acceptance is not represented as regulatory certification, universal external-agent detection, or guaranteed AI-text detection.
- [ ] The content track meets the agreed gates; a provenance-only demonstration cannot substitute for required untracked copy/paste performance.

## 5. Delivery ownership and working practices

| Responsibility | Accountable role |
| --- | --- |
| Scope, priorities, acceptance, performance claims | Product/project owner |
| Graph integration, evidence, rules, backend | Backend/integration engineer |
| Content modeling, calibration, model cards, drift | ML/content-detection engineer |
| Outlook add-in, investigator UI, accessibility | Frontend/Outlook engineer |
| Tenant configuration, permissions, Microsoft licensing | Microsoft 365/Entra administrator |
| Threat model, access controls, privacy, release findings | Security/privacy reviewer |
| Independent labels, test design, uncertainty analysis | QA/evaluation owner |
| Azure deployment, monitoring, costs, recovery | Platform/operations owner |

One person may hold several roles, but the individual who changes attribution rules or trains/calibrates content models should not be the sole approver of evaluation labels and release claims. Required reviews are milestone gates, not repeated permission requests for routine implementation already within the agreed scope.

Maintain a phase checklist with status, evidence links, test/run identifiers, open defects, owner, and exit decision. Use feature branches and reviewed pull requests after repository bootstrap. Keep changes small enough to assess and deploy safely. When a later phase exposes an earlier assumption as false, reopen the affected gate and record the correction.

Use test accounts and explicit test-recipient allowlists. Never send test messages to real customers or unrelated addresses. Do not provision broad production permissions, change tenant-wide mail routing, or enable enforcement merely to make a demonstration easier.

## 6. Schedule, cost, and release boundaries

The expanded scope has an initial planning allowance of twelve to sixteen weeks with two application/integration engineers, dedicated ML/evaluation capacity, and part-time Microsoft administration, security, and operations support. This is an estimate, not a delivery commitment. Refine it after the bounded Phase 0 feasibility study; obtaining independently labeled human email or failing the content gates can extend the work or produce a no-go. The ten-business-day shadow period and statistically meaningful evaluation must not be compressed into a scripted demo. Independent work may overlap, but a dependent exit cannot pass before its prerequisite evidence exists.

Primary costs are Azure application/model compute, PostgreSQL, Service Bus, storage, logs, and any missing Microsoft licensing. The expanded scope adds human labeling/adjudication, model benchmarking/training, possible GPU capacity, private artifact storage, and synthetic generation usage. Record Phase 0 estimates using region, hardware/quota, message volume and lengths, retention, data acquisition, and licensing; compare candidate cost per 1,000 messages in Phase 8 and validate actual consumption in Phase 13. No fixed cloud-cost claim is made before those inputs are known.

The release must answer all of the following with evidence:

- Which supported email actions can be attributed to agents, and at what observed recall?
- How often are non-agent workflows incorrectly assigned a verified-agent result?
- What share of traffic is unknown, pending, or outside observed coverage?
- Which identities and evidence sources support each verdict?
- Can human-approved and autonomous actions be distinguished without conflating approval with agent absence?
- Can manual AI copy/paste receive an appropriate content assessment without an agent accusation?
- What are content precision, false-positive bounds, eligible recall, and all-length recall with provenance disabled?
- Can basic grammar-only assistance remain separate from generated drafts and substantial rewrites/translations?
- Which short, edited, mixed, inherited, external, and non-English cases remain unknown or are missed?
- Can an agent send human-written text without that action alone creating a generated-content claim?
- Can forged or replayed evidence create a verified result?
- How long do agent attribution and content analysis take separately, including queues and source delays?
- Can the customer deploy, inspect, recover, and operate the POC without exposing sensitive mail unnecessarily?

Completion means a measured, reproducible Outlook POC that qualifies **both** agent attribution and the agreed AI-content detection scope, including untracked manual copy/paste. If useful content recall cannot coexist with the false-positive budget, record that requirement as unmet, retain the validated capabilities, and present a concrete scope/controls proposal for review. Do not weaken the gates silently or claim universal authorship detection. Additional channels and production enforcement start from the measured evidence.
