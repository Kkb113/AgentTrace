# Scoped Outlook category access proposal

Status: accepted by the owner/administrator in this chat on 30 October 2026: “Approve the scoped setup, probes and temporary-app retirement.” Private deployment data is recorded in `work/private/outlook-categories/proposal.private.json`; identifiers and credentials never enter Git.

Implementation note: Exchange rejected a duplicate scope with the identical exact-mailbox filter. The existing `AgentTrace-Synthetic-Mailbox` scope is reused after verifying the canonical filter and exactly one member. Its definition and reader assignments are not changed; category roles are assigned only to the two new principals. This changes no approved mailbox boundary or privilege.

## Exact scope and identities

Use the already enrolled operator mailbox and the existing dedicated disabled-sign-in shared mailbox solely as the negative authorization control. A new Exchange management scope, `AgentTrace-Category-Mailbox`, must resolve to exactly the enrolled mailbox by `ExternalDirectoryObjectId`. It must exclude the control mailbox and all others.

| Identity | Exchange Application RBAC roles | Lifetime/purpose |
| --- | --- | --- |
| AgentTrace Outlook Category Writer | Application Mail.ReadWrite; Application MailboxSettings.Read | Dedicated local non-exportable certificate, 30 days; read definitions and later update message categories in the exact mailbox |
| AgentTrace Outlook Category Setup | Application MailboxSettings.ReadWrite | Separate non-exportable certificate, at most one day; one-time creation of the three master categories only |

Both registrations are single-tenant, dedicated and tagged for this setup. No Graph application/delegated consent, client secret, Mail.Send, advanced mail-write, EWS/SMTP, directory role, full-access role or Azure role is assigned. Exchange-scoped grants are used alone; existing readers/audit applications are unchanged. Entra registrations are tenant objects, not resource-group resources. No billable Azure resource, licensing purchase or compute deployment is proposed.

Microsoft documents independent/additive Entra and Exchange permissions; unscoped Entra mailbox grants would defeat this boundary. Exact membership, both identities' role inventories and real allowed/denied calls must be checked. [Exchange Application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).

## Allowed setup and tests

Create only missing master categories: **AI Agent / preset0 (red)**, **Human-capable / preset4 (green)**, **Unknown / preset3 (yellow)**. Record IDs, exact names/colors, mailbox, setup identity and creation receipts in a private ownership registry. An existing unowned name is a conflict: do not adopt, recolor, rename or delete it. A previously recorded owned ID must still match the current provider definition. [Category model](https://learn.microsoft.com/en-us/graph/api/resources/outlookcategory?view=graph-rest-1.0).

The setup transport permits only listing/creating those definitions in the enrolled mailbox. Microsoft requires MailboxSettings.ReadWrite for creation; the runtime writer receives only settings read access. [Create categories](https://learn.microsoft.com/en-us/graph/api/outlookuser-post-mastercategories?view=graph-rest-1.0), [list categories](https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories?view=graph-rest-1.0).

For the effective write check, read one existing designated synthetic received message, then PATCH only its existing categories back unchanged with its current version condition and read it back. This tests real authorization without assigning a detection label. Send no message, create no draft, and change no body, subject, recipient, flag, folder or read state. Test access denial on the existing negative mailbox; the negative PATCH uses the same no-op array and a known valid synthetic item reference. Do not read another person's content or create test messages. Record the exact meaning of each denial, rather than treating a 404 or local rejection as proof of server authorization denial.

## Residual privilege and retirement

Mail.ReadWrite can technically read/create/delete mail and change permitted message properties in the scoped mailbox; code restricts it to the reviewed category operation. It does not include sending. MailboxSettings.ReadWrite likewise permits more settings changes than category creation. Scope and guards reduce exposure but do not turn these permissions into field-level credentials. [Message update permission](https://learn.microsoft.com/en-us/graph/api/message-update?view=graph-rest-1.0).

After provisioning and verification, retire only the dedicated temporary setup identity: remove its exact Exchange role assignment and pointer, disable/delete its Entra service principal and application, and remove its exact local certificate/private key. Preserve ownership and audit receipts. This retirement is part of this proposal's requested authorization. Do not remove the writer, existing readers, category definitions or unrelated identities. Verify registration/grant removal and inability to mint a new setup token; report any already issued token/cache expiry honestly. Exchange permission caches can outlive assignment changes.

The persistent writer must have no category-provisioning grant. Phase 5 produces ownership/setup evidence and a dry-run preview only. The main monitor continues rejecting category application; automatic classification writes remain Phase 6 work with its own concurrency and rollback gates.
