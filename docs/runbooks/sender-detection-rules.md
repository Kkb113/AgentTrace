# Sender detection rules in the Outlook POC

The active labels are **AI Agent**, **Human-capable** and **Unknown** under the [owner-approved policy](../adr/human-capable-classification.md). The [machine-readable policy](../../config/outlook-detection-policy.json) is checked in CI. These are registered POC rules, not a measured production accuracy claim. The earlier Phase 0 frozen contract and binary terminal demo remain historical/separate.

## Rules and evidence

**AI Agent** is currently limited to the enrolled own-mailbox Claude/Microsoft 365 route. It requires a complete supported-field inspection, exactly one `x-ai-generated: mcp-office365` declaration, a certificate-authenticated completed Exchange Send query, matching tenant/mailbox/Message-ID/time, one consistent enrolled Claude application in both actor contexts, a current verified-publisher pin, and a unique provider-observed Sent/received-copy pair containing the actual observed received ID. Failed, draft/read, ambiguous, wrong-scope, mismatching-publisher or partial results cannot qualify. Scope/time/copy checks corroborate indicators; they do not establish independent forensic equivalence between an Exchange audit store ID and a Graph received ID.

The registered connector ID is verified against [Anthropic's connector documentation](https://support.claude.com/en/articles/12542951-set-up-the-microsoft-365-connector). The audit item fields describe a store item; their names do not make them interchangeable with Graph identifiers. [Microsoft audit schema](https://learn.microsoft.com/en-us/office/office-365-management-api/office-365-management-activity-api-schema). A bounded live ID-format probe did not establish that equivalence, so the owner explicitly selected corroborated indicators for this POC instead.

**Human-capable** means complete configured message inspection is compatible with a normal email client and has no observed automation indicator/conflict. It includes a browser controlled by a human or by an agent. It is not a claim that a human wrote the body, clicked Send or exclusively controlled the session. Normal-client contexts and healthy pending audit checks do not establish controller identity. Known agent/automation evidence, source failures and conflicts suppress this inference.

**Unknown** covers incomplete or mismatched snapshots, malformed/ambiguous required headers, known automation without qualified AI corroboration, generic Gmail API traces, declaration-only cases, unsupported source coverage, expired source evidence, conflicts and source failures. A known source action associated only by candidate fields cannot silently upgrade an uncorroborated received copy.

Inspection binds the selected metadata/header snapshot to the observation digest, checks required singleton From/Date/Message-ID, Received trace, consistent message ID, timestamp shape, completed/non-draft state, header shape/size/folding and known MCP/API/ordinary-automation context. Subjects, bodies, current Outlook categories, operator A/B labels and review truth do not enter prediction. The synthetic subject prefix remains solely the approved collection-boundary selector.

## Configure and run

The existing read-only mailbox identity remains separate from the existing audit identity. `sender_source` in private runtime configuration supplies the mailbox address, Exchange mailbox GUID, audit certificate reference, explicit Azure subscription and publisher pins. It does not grant permissions. The Graph audit identity already has its accepted tenant-wide Exchange audit visibility; the runtime searches one enrolled principal and a four-minute Send window, retaining only records for the selected synthetic Message-ID. Publisher lookup uses the existing operator Azure CLI identity and validates its tenant/subscription context; unattended registry identity selection remains deployment work.

Prepared private configurations:

- `work/private/sender-rules-live/runtime.private.json`: current incoming synthetic tests, using the existing mailbox-sync state and activation boundary.
- `work/private/sender-rule-qualification/runtime.private.json`: isolated retrospective qualification case with explicit bounded backfill; not the default incoming monitor.

```powershell
uv sync --frozen --all-groups
uv run agenttrace-outlook --config work/private/sender-rules-live/runtime.private.json --check
uv run agenttrace-outlook --config work/private/sender-rules-live/runtime.private.json
```

Ctrl+C stops the monitor. `--once` advances one bounded cycle; it cannot guarantee that an asynchronous audit search has completed or that Microsoft has ingested the event. An audit analytical-search POST creates only a security search object; it is not a mail send, draft, approval or mailbox mutation. All mail requests remain fixed-scope GETs. No new Azure resource, identity or permission is created by this phase.

Read current explanations without connecting to Microsoft:

```powershell
uv run agenttrace-outlook --config work/private/sender-rules-live/runtime.private.json --inspect-rules
```

Inspection takes the same process lock, so stop a running monitor first. It explicitly reports `view=stored_assessments` and `evidence_refreshed=false`: it does not refresh or requalify cached results. Output uses hashed message references, categories, reasons, compatibility flags, source-action state, correlation basis and hashed evidence references. No subject/address/header/token is printed. `verified_enrolled_send` describes the audit action; `corroborated_indicators` describes the POC association, not forensic received-item identity. `human_candidate` is the compatibility-inference flag, not a human identity assertion.

## Recovery, freshness and state

Migrations verify the exact prior schema before adding durable source jobs/receipts/assessments, then transactionally preserve preview rows while adding the Human-capable category. Legacy Human records remain readable for compatibility but are not emitted or admitted as an active rule. Registered positive previews are recomputed against the current scoped observation, snapshot and source inside the decision transaction; naming a rule and forging evidence-reference strings cannot bypass that check. Assessment, decision version, preview and work acknowledgement commit together.

State also pins the source enrollment: subscription, principal/mailbox, audit application and publisher pins. Changing or removing that enrollment stops with `sender_enrollment_changed_requires_review` rather than reusing previously qualified receipts under different settings. After reviewing a new enrollment, use a separate state directory with an explicit approved backfill boundary. Audit certificate rotation and refresh-interval changes do not change the semantic enrollment or discard pending work.

Source jobs persist query ID, stage, continuation, filtered records, due time, retry count and generation. Only complete audit pagination may qualify an action; only complete matching-copy pagination may qualify the POC correlation. Generation fences reject stale responses. A crash may repeat an analytical read/search, but cannot manufacture a completed source or duplicate the same logical assessment. Replaying unchanged results does not extend the decision lifetime or insert another logical version. Receipt history is retained within the original observation's seven-day raw deadline; decisions retain their original thirty-day deadline.

The source/publisher freshness window is five minutes. Source changes, conflicts, revocation/mismatching pins and expiry trigger reassessment; an earlier affirmative result can downgrade to Unknown. Initial pending time is two hours, with explicit late reassessment up to twenty-four hours after observation. A deadline never proves Human-capable or a non-agent executor. Query failures and retry exhaustion remain blocked and visible; an hour-or-longer clipped Retry-After requires operator review rather than an early retry. Fix the cause before requeuing:

```powershell
uv run agenttrace-outlook --config work/private/sender-rules-live/runtime.private.json --retry-failed-sources --once
```

Blocked source jobs make a one-cycle run unsuccessful. Pending healthy searches are reported separately. Source receipts contain only the selected synthetic events and publisher/copy context, never bodies or attachments. Automatic physical purge, encrypted backup/restore, Windows ACL provisioning and unattended supervision remain later gates.

## Qualification limits

Live qualification includes fresh owner-prepared Claude/manual Outlook sends and a retrospective Claude case. Current authenticated APIs supply audit and mailbox-copy evidence; the production rule/copy checks create local previews. The fresh Claude example initially remained Unknown and later became AI Agent after its audit evidence arrived. The manual Outlook example produced Human-capable. The retrospective case is not a real-time feed-latency measurement. Neither case establishes an ingestion SLA; source lag is a real coverage/latency limit, not a reason to promote the declaration alone. See the [redacted live record](../evidence/sender-rule-live-validation.json).

Observable copied-ID collisions, changed actors, wrong scopes, malformed data, generic APIs, source failures and revoked publishers are negative controls. An unobservable forged replacement preserving every correlation field can still be classified AI Agent under the accepted POC policy. The suite records that counterexample explicitly; it is not falsely counted as a correctly rejected negative. Phase 4 must measure the enabled rules' false positives/recall and retain this risk in release claims. Native Outlook category writes and color rendering are still unimplemented/gated by later phases.
