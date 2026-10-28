# Secure-access permission matrix

Review state: accepted on 28 October 2026. The user explicitly replied, "Accept as project owner, Microsoft 365 administrator and security owner" to the concrete matrix and data flow, including broader Exchange audit exposure. Implementation and effective tests are recorded separately in the secure-access report; acceptance alone is not technical proof.

## Selected deployment and scope

The sandbox uses the already designated operator mailbox, synthetic marked messages, East US, seven-day raw retention and thirty-day decision retention. Actual tenant, mailbox, principal and resource identifiers stay in ignored private configuration. A dedicated, disabled-sign-in shared mailbox is the negative scope control; it is never enrolled for collection. No other person's message content is used in tests.

Compute and PostgreSQL remain local. Create dedicated Standard LRS Storage and Standard Key Vault resources in kb-agentdemo; do not reconfigure shared resources. Permit only the operator's current IPv4 address on those public service endpoints, require TLS and Entra authorization, disable shared-key and anonymous storage access, and deny other network sources. These are authenticated, firewall-restricted public endpoints, not Private Link. No hosted inference, GPU, VM, cloud PostgreSQL, registry, public webhook, premium tier or new tenant-wide diagnostic destination is needed for this milestone. Re-evaluate networking before cloud-hosted processing.

## Identities

| Identity | Allowed operations | Authorization boundary | Explicit exclusions | Consent and owner |
| --- | --- | --- | --- | --- |
| Mail collector | Read marked approved-mailbox message metadata, MIME/headers and authorized bodies | Exchange Application RBAC Application Mail.Read on the exact approved mailbox; no parallel Entra Mail.Read grant | No other mailbox; no send, draft, edit, move or delete; no prompt history | Microsoft 365 administrator; project owner accepts body access |
| Exchange audit collector | Query/read Exchange audit records needed for send attribution | Separate AuditLogsQuery-Exchange.Read.All application permission; filtering and minimization in the collector | No mailbox-body permission or other workload audit scope; no mail write/send | Explicit administrator/security-owner acceptance of broader Exchange audit exposure |
| Attribution worker | Consume agent-evidence queue; read approved raw evidence; persist agent decisions; sign evidence digests | Exact Azure queue/container/key role assignments; local database role | No Microsoft 365 rights, content queue, other storage containers, key export or key administration | Platform owner |
| Content worker | Consume content-analysis references and authorized transient text | Exact content queue; local minimal database role; isolated network | No Microsoft 365/history access, retained raw-evidence container, signing, agent queue, public model/API or internet egress | Platform/security owner |
| Detection API | Read authorized decisions and verification material | Local database read role; API audience/tenant/roles plus server-side mailbox/message entitlement | No source mailbox access, collection, signing, queue administration or mail execution | Application/security owner |
| Access-test client | Call API with Detection.Viewer application role | Dedicated certificate principal and exact API audience | No Microsoft 365, Azure data, signing or administrator role | Platform owner; synthetic verification only |
| Human Viewer | Read detection findings within server-assigned mailbox scope | Entra Detection.Viewer role; valid access token and delegated API scope | No implied collector access or mail operation | Microsoft 365 administrator assigns; security owner accepts |
| Human Investigator | Inspect authorized supporting detection evidence within scope | Entra Detection.Investigator role; same tenant/message checks | No unrestricted history, mailbox administration or mail operation | Same |
| Human Administrator | Read access/health configuration within assigned scope | Entra Detection.Administrator role; explicit API checks | This application role grants no Azure/Exchange administrator or mail execution rights | Same |

Workload registrations use distinct short-lived certificate credentials for this local hybrid sandbox. Private credentials are protected outside source and routine logs. Hosted managed identity migration is required when Azure runtime is introduced; no external agent credential is held. The API registration itself receives no Graph application permission. Application role IDs are stable project definitions; tenant-specific app IDs are private deployment data.

## Broad audit access and denied features

Exchange Application RBAC and Entra application permissions are additive. The collector must have no Entra mailbox role or other assignment that bypasses its Exchange scope. Test both live Graph reads and both grant inventories; a successful Test-ServicePrincipalAuthorization alone is insufficient. See [Microsoft's Application RBAC guidance](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac).

AuditLogsQuery-Exchange.Read.All exposes Exchange audit information across the tenant. A mailbox/user/date filter is a data-minimization control, not an OAuth or Exchange mailbox authorization boundary. This broader access belongs only to the separate audit collector and must be accepted explicitly. Other workloads cannot acquire its credential. Do not claim audit scoping to one mailbox. See the [audit search API](https://learn.microsoft.com/en-us/graph/api/security-auditcoreroot-post-auditlogqueries?view=graph-rest-1.0).

Optional Copilot/Claude/ChatGPT generation-history connectors are disabled and receive no permissions. Their absence is an explicit coverage gap. The content worker has no direct mailbox/history credential and cannot silently use an external model service. Basic corrections and AI content remain independent of agent attribution.

## Effective tests and acceptance

Test allowed/denied mailbox reads with the actual collector token; inspect all effective Entra and Exchange grants; reject mail mutations through the product boundary without delivering email. Test API signature, issuer, audience, tenant, expiry, role, subject and message/mailbox authorization. Exercise queue/blob/signing denials with the wrong actual principal and database denials through separate SQL logins. Test content egress and expired/raw-data access. Failed, unavailable or configuration-only checks stay open and cannot satisfy a live exit.

Acceptance covers this matrix and [the data flow](data-flow.md), including authorized synthetic body processing, broader Exchange audit exposure, disabled optional histories, firewall-restricted public Azure endpoints, local private processing and the 7/30-day retention boundary. It grants no sender/approval capability, real customer-data use, public text upload or tenant security-policy exception.

## Notification transport addition

The owner accepted a dedicated East US Standard LRS metadata account and Event Grid
partner topic for live Graph delivery, plus the later destination-account role
amendment after narrower grants failed Azure validation. Event Grid's system identity
has Message Sender and Blob Data Contributor only on this new single-purpose account.
The mail collector has Message Processor only on its notification queue. The original
raw-evidence account and Key Vault retain their no-bypass firewalls. No tenant mail
write/send role or broader mailbox read role was added. See
[the review and amendment](notification-transport-proposal.md) and
[owner acceptance](evidence/notification-transport-acceptance.json).

## Graph activity source addition

The owner subsequently authorized enabling Microsoft Graph activity logging, checking licensing/permissions, minimizing cost, and testing the source end to end. A dedicated pay-as-you-go East US workspace/DCR in kb-agentdemo keeps a filtered seven-day Graph table. The existing audit collector receives only a workspace-scoped Log Analytics Data Reader assignment conditioned on that table. This adds no Microsoft 365 mailbox/send/write permissions. Tenant-wide source export is minimized downstream and remains broader than a mailbox authorization boundary. Shared workspaces and existing evidence firewalls stay unchanged. See [the design and cost controls](graph-activity-logging.md).
