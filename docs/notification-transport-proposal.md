# Synthetic notification transport review

The proposed live path is Microsoft Graph basic notifications → an East US Event
Grid partner topic → a dedicated Standard LRS Storage Queue → the local collector's
transactional inbox. No email bodies, subjects, attachments or recipient lists are
included in this transport. Opaque message identifiers, tenant/application and
subscription identifiers, timestamps, and the notification validation secret remain
sensitive. The receiver validates them and persists only encrypted locators before
deleting the queue receipt. This is background detection collection, not email automation.

All new Azure resources will be in `kb-agentdemo`. There is no always-on cloud
compute, premium tier or GPU. Event Grid operations, storage transactions/capacity,
and optional diagnostic ingestion are metered; free allowances are not a cost promise.
Use a two-day Graph subscription, a one-day Graph partner authorization and a
seven-day delivery TTL. Provisioning must inspect a what-if first and refuse changes
to unrelated resources. Resource cleanup is a separately explicit operation.

Microsoft documents that Event Grid delivery to a firewall-protected queue requires
a **system-assigned managed identity and the trusted Microsoft services network
exception**. Consequently this proposal uses a **new, metadata-only storage account**
with default-deny firewall, the operator's IPv4 allow rule, AzureServices bypass,
TLS 1.2, no anonymous access or shared keys, and exact queue-scoped RBAC. Event Grid
gets message-send only; the mail collector gets message-process only. Operator access
is for setup/testing. The existing raw-evidence account and Key Vault retain their
previous no-bypass policies. The trusted-services exception is a network exception;
it does not independently grant data-plane authorization to other services.

This differs from the accepted Phase 2 no-trusted-service-bypass baseline, so applying
this particular network design requires the project/security owner's acceptance.
No mailbox send/write permission, tenant-wide mailbox role, new content history
connector or Conditional Access exception is proposed. If declined, the tested local
webhook and scoped delta reconciliation remain usable, while native Azure delivery
is recorded as unvalidated rather than passed.

References checked 29 October 2026:

- [Graph via Event Grid](https://learn.microsoft.com/en-us/azure/event-grid/subscribe-to-graph-api-events?context=graph%2Fcontext)
- [Queue delivery and firewall requirements](https://learn.microsoft.com/en-us/azure/event-grid/handler-storage-queues)
- [Partner authorization](https://learn.microsoft.com/en-us/azure/event-grid/subscribe-to-partner-events)
- [Event Grid pricing](https://azure.microsoft.com/en-us/pricing/details/event-grid/)

## Live validation amendment: delivery-role scope

Actual Azure activity logs reported `Managed Identity Authorization Error` during
asynchronous event-subscription creation with queue/container-scoped grants. A later
retry after propagation failed identically. The Microsoft managed-identity delivery
guide specifies Storage Queue Data Message Sender and Storage Blob Data Contributor
on the **destination storage account**. The concrete amended setup script grants
those two existing data roles to the partner topic's identity at the new dedicated
metadata account, while the collector remains queue-scoped. This identity would be
able to add messages to any queue and manage blobs in any container subsequently
created in that account. It cannot read email, manage the account, grant roles or
access the separate raw-evidence account/Key Vault. Keep this account exclusively
for synthetic notification transport; do not add unrelated queues or body storage.

Because this is broader than the originally accepted queue/container role scope,
applying the amended script requires owner acceptance. The code is prepared but the
account-level grants must not be applied until that acceptance is received. This is
a service-authorization change, not an automatic-approval-review rejection.

- [Microsoft's documented destination-account roles](https://learn.microsoft.com/en-us/azure/event-grid/managed-service-identity)
