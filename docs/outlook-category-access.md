# Outlook category access and ownership

The later [three-label migration](adr/simple-classification-labels.md) replaced the owned Human-capable definition with Human through Outlook's owner UI and recorded the new ID/provenance without additional application permissions. Historical provisioning evidence retains the original name and ID; the current ownership registry uses Human.

Phase 5 prepares the native Outlook labels without enabling automatic classification writes. The owner accepted the [concrete proposal](category-access-proposal.md) before registration/grant use. The existing mailbox and audit collectors retain their credentials and read-only mail permissions. No Azure resource or paid service was added.

## Effective access

| Principal | Exchange Application RBAC | Boundary and current state |
| --- | --- | --- |
| Category Writer | Application Mail.ReadWrite; Application MailboxSettings.Read | Exactly one enrolled mailbox; dedicated non-exportable certificate with 30-day validity |
| Category Setup | Application MailboxSettings.ReadWrite | Same mailbox; temporary registration, Exchange assignment/pointer and one-day certificate retired after setup |

Exchange rejected a duplicate management scope. Setup reused `AgentTrace-Synthetic-Mailbox` only after verifying its exact `ExternalDirectoryObjectId` filter and single member; its filter and reader assignments were unchanged. The dedicated disabled-sign-in shared control mailbox is outside that scope. Both new principals had zero Entra application/delegated grants and directory memberships. The writer's remaining inventory has the same exclusions. Scope/role simulation was followed by actual Graph calls.

Mail.ReadWrite allows more operations than changing categories. MailboxSettings.ReadWrite similarly exceeds category creation. There is no categories-only application permission. These are accepted residual privileges, constrained by mailbox RBAC, separate credentials and reviewed adapters. Neither app received Mail.Send, advanced mail-write, EWS, SMTP, full-access, directory or Azure roles. No send operation was attempted. Microsoft describes the [Exchange and Entra authorization boundaries](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac) and [message update requirements](https://learn.microsoft.com/en-us/graph/api/message-update?view=graph-rest-1.0).

## Ownership and operations

| Owned definition | Outlook color | Provider preset |
| --- | --- | --- |
| AI Agent | Red | preset0 |
| Human | Green | preset4 |
| Unknown | Yellow | preset3 |

Names and colors follow the [Outlook category model](https://learn.microsoft.com/en-us/graph/api/resources/outlookcategory?view=graph-rest-1.0). Human retains the accepted normal-client-compatible meaning, including browser-controlled agents; category setup does not improve or widen the detector's AI coverage.

The private atomic ownership registry pins each provider ID, exact name/color, mailbox, writer, setup identity, creation time and normalized response digest. The digest is an operator-held integrity receipt, not an independent Microsoft signature. Name equality alone never grants ownership. Setup preflights all name collisions, including case/whitespace/Unicode variants, before creating anything. Existing unowned categories are never adopted, recolored or deleted. Confirmed partial creation can resume from its receipts; an ambiguous POST with no receipt requires operator reconciliation, not automatic adoption. ID replacement, renaming, deletion, color drift or ambiguous names block verification and preview.

`setup-outlook-categories.py` exposes only `provision`, `verify`, `preview` and the explicitly approved no-op `probe`. Runtime credentials cannot create master categories. The schema accepts only `automatic_application_enabled: false`; the monitor still rejects application. Provisioning uses a separate settings writer because [creation](https://learn.microsoft.com/en-us/graph/api/outlookuser-post-mastercategories?view=graph-rest-1.0) requires more access than [listing](https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories?view=graph-rest-1.0).

The preview reads current master definitions and synthetic message categories, then rechecks decision eligibility, the persisted observation's scope/version, expiry and current rule outcome/reasons. It reports the intended label, preserves unrelated category names and models exactly one owned label. It emits no write intent and performs no message PATCH. Private message/category IDs stay in private reports. An evidence mismatch is a skipped row, not a successful proposed change. A preview is not a concurrent-apply guarantee; Phase 6 must revalidate the actual message/evidence version before writing.

## Executed checks and retirement

The live writer read the category catalog and one existing synthetic message. A conditional PATCH sent that message's existing categories array unchanged; readback confirmed identical membership. This can update provider change metadata, so it is not represented as a zero-request test. No prediction category was assigned. Actual out-of-scope mail and category GETs returned authorization denial. A PATCH routed through the negative mailbox also returned authorization denial before resolving the enrolled synthetic item; this tests the negative route, not a write against an item read from that mailbox. A read-only collector token could read the enrolled synthetic item but its unchanged-array PATCH was denied.

After setup, the exact Exchange assignment and pointer, Entra service principal/application and local certificate/private key were removed. A new setup token request was denied before key deletion, and writer verification succeeded afterward. Runtime configuration now has `setup_identity: null`. Retired setup cannot be recreated by rerunning the configure commands; new provisioning requires a new review.

An already-issued setup token still succeeded on a category read immediately after retirement. Its recorded expiry was **30 October 2026, 04:26:28 UTC (09:56:28 IST)**. It remained only in process memory and was discarded. Do not describe cleanup as immediate revocation of every issued token or permission cache; neither an expired-token recheck nor instantaneous old-token write denial is claimed. The persistent writer has no provisioning grant.

The [executed validation record](evidence/category-access-validation.json) records the four exits, software gates and private proof digests. Actual master definitions and two eligible label previews were verified; one changed-evidence decision was correctly blocked. This is permission/setup qualification, not automatic category application, a new classification accuracy claim or a client rendering test. Phase 6 implements the durable concurrency-safe writer; later phases qualify continuous operation and Outlook display.

## Engineering review

Review covered additive grants, exact-target cleanup, registration replay after retirement, Unicode collisions, ID drift, ambiguous creation, unchanged-array capture, conditional PATCH, pagination boundaries and preview freshness. A replay gap in Exchange configuration was corrected: a retired setup manifest blocks configuration and inspection requires the persistent writer pointer. A regression exercises the actual PowerShell early-failure path without an Exchange module or credentials, verifying cleanup does not mask the sanitized denial. The constrained adapters and AST boundary checks have no send/delete/draft or arbitrary message-write path. These code guards do not reduce the underlying OAuth/RBAC privilege or protect against a compromised operator/private registry.

Use the [operations runbook](runbooks/outlook-categories.md) for verification and failure handling. Certificate rotation and unattended write operation remain later deployment work; the 30-day writer certificate is not a perpetual credential.
