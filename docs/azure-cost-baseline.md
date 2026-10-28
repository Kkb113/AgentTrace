# Azure cost and deployment baseline

This is the historical Phase 0 snapshot. The later secure-access milestone provisions minimal Storage/Key Vault resources and resource diagnostics; its incremental usage boundary is in [secure-access cost](secure-access-cost.md). The zero-resource statements below describe the original feasibility run.

Date: 28 October 2026. Region: East US, accepted for synthetic tests only. Currency: USD retail, excluding tax, negotiated subscription discounts and unverified grants. Sources are Microsoft's [Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices) and [Container Apps billing guidance](https://learn.microsoft.com/en-us/azure/container-apps/billing). Public price snapshots were retrieved from `prices.azure.com`; a selected, reproducible meter snapshot accompanies this document.

**Current incremental provisioned compute cost: $0.** No Azure resource, diagnostic setting or role assignment was created. The project owner separately authorized a temporary tenant-scoped Entra application, its service principal and operator-only delegated consent, which were created for the read-only exercise; these do not provision billable Azure compute. See `access-remediation.md`. Existing-resource charges are not attributed to this project. Local CPU work and existing licensing are used for this stage; internet egress, subscription-specific billing and operator labor are not measured by that $0 compute-creation statement.

## Initial cloud pilot scenario

Sizing assumptions: one test mailbox, 100 synthetic messages/day, one small continuously available webhook/API replica, bounded attribution and content workers, PostgreSQL stopped outside 160 working hours, 32 GB database storage, five GB evidence storage and one GB incremental diagnostic ingestion. CPU sizing is a benchmark starting point, not a capacity guarantee. All free grants are ignored in this conservative arithmetic scenario.

| Item | Meter / assumption | Estimated month |
| --- | --- | ---: |
| Webhook/API/UI | 0.25 vCPU + 0.5 GiB, 730 hours at active rates: $0.000024/vCPU-second + $0.000003/GiB-second | $19.71 |
| Attribution worker | 0.5 vCPU + 1 GiB, 20 active hours | $1.08 |
| Content worker | 1 vCPU + 2 GiB, 20 active hours | $2.16 |
| PostgreSQL B1MS | $0.017/hour × 160 hours; no HA/read replica | $2.72 |
| PostgreSQL storage | $0.115/GB-month × 32 GB | $3.68 |
| ACR Basic, if needed | $0.1666/day × 30 days; base included storage only | $5.00 |
| Hot LRS evidence | $0.0208/GB-month × 5 GB; non-hierarchical namespace | $0.10 |
| Log Analytics | $2.30/GB × 1 GB using paid ingestion tier, with no free allowance assumed | $2.30 |
| Key Vault operations | $0.03 per 10,000 operations × 10,000 | $0.03 |
| Queue/blob operations allowance | Explicit planning allowance, not a quoted meter or measured bill | $1.00 |
| **Illustrative subtotal** | Rounded sum; see exclusions below | **$37.78** |

This is an estimate, not a spending ceiling or approved bill. A local-only path creates no new cloud resources. Reusing suitable existing registry/storage/secrets/logging can reduce incremental fixed cost but does not make shared usage free. If PostgreSQL runs 730 hours rather than 160, compute increases by $9.69. Stopped database storage/backup charges continue, and a stopped Flexible Server automatically restarts after seven days. [PostgreSQL stop behavior](https://learn.microsoft.com/en-us/azure/postgresql/configure-maintain/how-to-stop-server).

Excluded until a concrete deployment decision: outbound networking, extra backups/storage/IOPS, registry builds/overage, private endpoints/DNS/network appliances, tenant-wide Graph activity ingestion, additional license purchases, and unfamiliar-model experiments. These are not assumed zero. In the retrieved East US price response, Container Apps Environment Private Endpoint and Environment Management Hour each appear at $0.10/hour; billable applicability and additional Private Link charges must be checked for the chosen topology. A private configuration can therefore materially exceed the illustrative subtotal. No standing GPU, AKS, dedicated plan, vector/Search service or managed LLM deployment is proposed.

## Scope and controls

All new project resources must target `kb-agentdemo` and an explicitly selected subscription. Keep actual IDs in ignored local configuration. Group metadata location is East US; do not assume existing resources in other regions meet the accepted boundary. Reuse only isolated, suitable resources without changing another workload's permissions, retention, network or SKU. Never delete the shared resource group as cleanup.

Use local development first, Storage Queues with application idempotency/poison handling, the smallest adequate Burstable database, ACR Basic only if a registry is necessary, Key Vault Standard, and Container Apps Consumption. Max replicas start at two for ingress and one for content; a zero-minimum worker needs a real wake-up trigger. Keep ingress warm if Graph response deadlines require it. Private-endpoint requirements can require higher tiers; do not weaken required controls to hit a price target.

Before provisioning, run a group-scoped Bicep what-if and recompute prices/usage for the actual topology. The project spending ceiling remains a project-owner decision; the estimate is not authorization to consume that amount. Proposed budget notifications are 50%, 80% and 100%, with replica/time caps and an exact-resource stop runbook. [Budgets notify but do not stop consumption](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets). No spending ceiling is needed to run the already authorized, zero-provisioning local feasibility checks.
