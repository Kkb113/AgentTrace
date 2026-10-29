# AgentTrace Outlook-native scope

Current POC policy revision: [Human-capable and corroborated indicators](adr/human-capable-classification.md). This supersedes earlier Human/controller and independent received-item-proof definitions for this POC; historical evidence below retains its original scope.


Current revision: 29 October 2026. The owner's latest change replaces the standalone application roadmap with a production-quality Python monitor and native Outlook color categories. [Decision record](adr/outlook-native-categorization.md), [current implementation plan](../implementation.md).

## Product

Determine who executed each observed email's completed send action. Apply **AI Agent** (red), **Human** (green) or **Unknown** (yellow) as an Outlook category. Per the owner's latest clarification, Human may be inferred after complete inspection finds no MCP/API/other automation indicators, regardless of content authorship. This is a policy inference, not proof of the executor. Unknown includes incomplete/unavailable inspections, pending/conflicting/unsupported evidence and known non-AI automation. The Human rule still requires accuracy qualification against untagged/browser agents.

An agent send remains an agent send after external human approval. Manual sending of AI-written text is a human-send scenario when that action is established. Writing origin, draft creation and recipient-side agent reads do not determine the executor. AI-generated-content detection is excluded.

Outlook itself provides the visible experience; the script also offers terminal/operational diagnostics. No separate frontend, public backend API, custom Outlook icon/add-in, Gmail-receiving connector or AI model is required.

## Initial coverage

One designated Exchange Online mailbox, with incoming Gmail → Outlook and Outlook → Outlook messages in enrolled receiving folders. New-arrival activation/backfill boundaries are explicit. Gmail-recipient routes are deferred, not claimed as supported by connecting Outlook.

Mail from any sender domain can be inspected where authorized, but arbitrary external send executors may remain unobservable. Receiver access does not grant another tenant's audit or Gmail/Claude tool history.

## Detection and evidence

Retain the working terminal demo as a demo. Its explicitly requested binary header heuristic must not become the production policy. The new entry point is separate, with qualified decisions and Unknown by default.

The Office365 MCP declaration and Gmail HTTPREST trace remain visible evidence hints. They require a qualified trust/execution/message-link rule before supporting a production AI Agent category. Human uses the owner's inferred-manual rule after complete inspection; ordinary authentication or a user session alone does not prove the executor. Failed/missing inspection must remain Unknown.

The enrolled Claude/Microsoft Exchange Send audit path has one demonstrated authenticated route. Its trust scope and received-copy correlation limits remain explicit. General Human attribution, quantitative production accuracy and Graph activity-log delivery remain unqualified. Do not mark them complete from the demo.

## Permitted mailbox annotation

Mail reading and audit collection stay separate from a dedicated category writer. The only requested mailbox mutation is the categories collection on exact allowlisted messages. Preserve unrelated categories, use validated concurrency protection, verify writes and retain an exact owned-label rollback record.

Graph Mail.ReadWrite is broader than category updates; effective mailbox scope and strict categories-only code guards are required. Provision master categories manually or with separately approved temporary setup permissions. This documentation creates no permission, category or live annotation.

Do not compose, draft, send, reply, forward, schedule, manage approvals, operate agents, route/block/quarantine, alter subject/body/read state or change unrelated mailbox settings. Category annotation is a detection output, not an email execution platform.

## Data and hosting

Preserve the synthetic-only qualification/write-test baseline, East US where Azure is used, seven-day raw evidence and thirty-day decision metadata. The owner separately authorized mailbox-wide incoming metadata for the live diagnostic; unattended deployment needs its precise data/access/annotation-lifetime configuration recorded before enablement. No real-customer body collection, model training, public detector uploads or clipboard surveillance.

Keep private messages, headers, account IDs, source transcripts, credentials and reviewer records outside Git. Use minimum fields, sanitized logs, encrypted host storage and protected backups. A suitable always-on Windows host with supervised execution is the initial low-cost deployment; Outlook can be closed while the host remains available. New Azure resources, if justified later, use only kb-agentdemo and explicit subscription selection.

## Status and history

Earlier Phases 0–4 passed their historical Microsoft/dual-target criteria; their reports are unchanged. The new ten-phase sequence is a replanned production-monitor roadmap, not inherited completion. Existing v1 dual-target APIs and unfinished evaluation work remain legacy components; migrate/reuse only what this small monitor needs.

The demo currently runs and has targeted test evidence. The new production runner, Human evidence qualification, category permissions/writer, unattended deployment and production accuracy gates are open. No application UI is pending within this scope.
