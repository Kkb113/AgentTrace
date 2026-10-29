# Outlook-native production POC

Decision date: 29 October 2026. Basis: the owner's explicit request to replace the application roadmap with a production-quality script and colored labels inside Outlook.

## Deliverable

Build a separate production monitor that reads the designated Microsoft 365 mailbox, evaluates send-executor evidence and assigns native Outlook categories: **AI Agent** (red), **Human** (green) and **Unknown** (yellow). Use Outlook as the user interface. No dashboard, custom API server, Office.js add-in, AI-content model or Gmail-receiving integration is required for this release.

The ten-phase sequence in [implementation.md](../../implementation.md) replaces the earlier fifteen-phase roadmap. Existing phase reports retain their original meaning; none is backdated as completion of this new sequence. Previous sender-only scope decisions remain applicable except where this revision changes the interface, receiving-provider scope or permitted annotation operation.

Incoming Gmail → Outlook and Outlook → Outlook remain in scope. Gmail-recipient routes are deferred. Received-message visibility still does not grant sender-side audit access.

## Production versus demonstration

Keep the working terminal demo unchanged. Its binary header policy was explicitly requested for demonstration and is not qualified actor attribution. The new monitor must not inherit its forced Human fallback or treat a Gmail API trace/unsigned Office365 MCP declaration as a verified agent action.

Production categories require versioned qualified rules. The owner's subsequent clarification defines Human as an inferred manual-client send when complete inspection finds no MCP/API/other automation indicators, regardless of text authorship. This is an operational inference rather than proof of the executor. Unknown covers incomplete/unavailable inspections, pending/conflicting evidence and known non-AI automation. The Human rule is technically feasible with the existing reader but must be qualified against agents that omit markers or operate normal clients; it cannot be declared accurate merely because the rule executes.

The existing authenticated Exchange/Claude route is reusable only within its enrolled source and exact-message assumptions, including separate tests of association to the received copy. Existing demo tests and historical live captures remain useful evidence without becoming production accuracy measurements.

## Category-write exception

The owner now requests category annotation, so the earlier absolute read-only product boundary is revised for this operation. Readers remain read-only. A separate mailbox-scoped writer may update only the message categories property after concrete permissions, ownership and safety checks are approved and verified. No sending, drafting, content changes, routing, approvals or agent execution is added.

Graph category assignment requires Mail.ReadWrite, which is technically broader than category editing; a category-only OAuth scope is unavailable. Limit the mailbox through Exchange application RBAC, avoid additive unscoped grants, restrict allowed routes/payloads in code and record the residual credential risk. No permission has been granted by this document. [Microsoft update-message permissions](https://learn.microsoft.com/en-us/graph/api/message-update?view=graph-rest-1.0).

Master-category provisioning is a separate one-time concern. Prefer manual setup or a separately scoped temporary identity, rather than keeping MailboxSettings.ReadWrite in the running worker. [Category creation](https://learn.microsoft.com/en-us/graph/api/outlookuser-post-mastercategories?view=graph-rest-1.0).

Updates must preserve unrelated categories, reject stale decisions, validate actual concurrency behavior and avoid reacting endlessly to the service's own changes. Before/after write confirmation and exact service-owned rollback are required. User category edits are display changes, not actor evidence.

## Minimal operation and status

Use a small typed Python program, durable local state and native Windows supervision on an appropriate always-on host first. A terminal is optional during unattended operation; Outlook need not remain open. No new Azure resource is required merely to implement the POC. Any later justified Azure deployment stays in kb-agentdemo with explicit subscription, minimal cost and suitable durable state.

Keep minimum metadata/header reads, protected raw evidence for seven days and decision metadata for thirty days. Confirm the precise data and annotation-lifetime policy before unattended production use. Customer email bodies, model training and public detector uploads remain excluded.

This turn revises documentation only. The new production runner, category provisioning, write permissions and live Outlook annotation are still unimplemented. Existing source changes, demo behavior, raw evidence, client workbook and historical reports are preserved.
