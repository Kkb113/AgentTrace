# Optional independent Graph archive test — owner acceptance required

State: the user, acting as owner/administrator/security owner, accepted this isolated
exception on 29 October 2026. Execution and delivery results are recorded separately
in `evidence/graph-archive-diagnostic-validation.json`. The existing filtered Graph
destination stays in place.
The purpose is to test whether native Graph records reach a separate Blob Storage
destination, bypassing Log Analytics query authorization and workspace transformations.
This can identify an alternate transport if Microsoft publishes records but that
particular delivery path fails. It cannot force Microsoft to emit unavailable records.

## Concrete resources and access

- Create one new East US `Standard_LRS` StorageV2 account in `kb-agentdemo`, with
  purpose `owner-approved-raw-graph-diagnostic`. Reuse neither the original evidence
  account nor the notification account.
- HTTPS/TLS 1.2, anonymous blob access off, shared-key access off, operator-IP
  firewall with default deny, and a trusted-Azure-services network exception for
  Azure Monitor's native archive delivery. The exception is new and account-specific.
- Grant only the designated operator `Storage Blob Data Reader` on the single
  `insights-logs-microsoftgraphactivitylogs` container. Product identities receive
  no archive access and no Microsoft 365 permission changes.
- Disable versioning and soft deletion so those features do not prolong the raw
  retention window. Configure seven-day blob lifecycle expiry, with application
  age checks on reads; lifecycle execution is asynchronous, not an instant erase SLA.
- After acceptance, create only the separate Entra setting
  `AgentTraceGraphArchiveProbe`, enabling `MicrosoftGraphActivityLogs` to that new
  account. Preserve every existing tenant setting. The prepared storage template is
  `infra/bicep/graph-archive-diagnostic.bicep`; provisioning defaults off.

This uses storage/transaction billing without always-on compute, Event Hubs, Sentinel,
new licenses or a commitment tier. Native archival does not have the workspace's
post-filter daily cap; volume-dependent costs cannot be guaranteed in advance.

## Why this needs another decision

The accepted POC stores only enrolled pilot/collector contexts after transformation.
Native Blob archival cannot apply that workspace transformation before storing logs.
It can therefore retain **tenant-wide raw API request metadata**, including request
URIs/query strings, IP addresses, user/application/session/token identifiers, and
permission/scope metadata. The log schema does not normally include API message
bodies, but URI/query values can themselves contain sensitive information.

Approval would explicitly extend the filtered/synthetic-only baseline for this
isolated diagnostic archive and approve its trusted-services firewall exception.
Do not approve this route if retaining that broader metadata is prohibited. No raw
archive will be created or enabled without that acceptance. If Azure requires an
additional authentication exception, stop for a reviewed amendment rather than
silently enabling shared keys or changing existing storage firewalls.

## Test and stop criteria

1. Verify the new account's controls and exact operator grant before enabling export.
2. Generate only synthetic read-only control requests with unique request IDs.
3. Read bounded archive objects privately and find those exact IDs. Retain only
   approved diagnostic references in local protected captures; publish counts/flags.
4. If archive records arrive while the workspace remains empty, investigate the
   workspace/transform/access branch and qualify a corrected or alternate read path.
   If neither destination yields records, keep the result unknown and take the
   combined evidence to Microsoft for tenant/category provisioning checks.
5. Disable only this archive setting when the foreground diagnostic test ends.
   Leaving capture enabled for a longer observation interval requires an explicit
   owner instruction. Keep the data under its expiry policy; resource deletion is
   a separate cleanup decision.

Acceptance is for this diagnostic exception, not a claim of successful Graph
delivery, production compliance, AI-agent detection accuracy, or permission to send email.

[Graph destinations and filtering limits](https://learn.microsoft.com/en-us/graph/microsoft-graph-activity-logs-overview),
[Azure Monitor trusted storage access](https://learn.microsoft.com/en-us/azure/storage/common/storage-network-security-trusted-azure-services).
