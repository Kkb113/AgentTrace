# Local POC operating cost

Pricing checked on 30 October 2026. The simplified Phase 7 uses the existing PC, operator session and local monitor. It adds no Windows service, dedicated account, publisher-reader registration, Azure VM, database, paid host or premium service. Existing Microsoft 365/Entra licensing remains an assumed existing entitlement.

Incremental Phase 7 Azure resource cost: **₹0/month**. Electricity, existing licences and host ownership are excluded.

For the existing AgentTrace resources in `kb-agentdemo`, use **₹1,000/month before taxes as a planning budget**, not a hard spending limit. The following low-volume scenario is an estimate, not a billed-cost report:

| Existing component | Assumption | Monthly estimate |
| --- | --- | ---: |
| East US Log Analytics, PerGB2018 | 3 GB ingestion, 30-day retention | ₹0–₹662.33 |
| Three Standard LRS storage accounts | Up to 5 GB combined storage and light transactions | ₹10–₹100 |
| Event Grid and standard Key Vault | Light notification/secret operations | ₹0–₹20 |
| Existing operator-run Python monitor | Existing PC; no Azure compute | ₹0 |

Microsoft's INR retail feed returned ₹220.7756 per GB for East US Analytics Logs ingestion after the free allowance, ₹1.9966 per GB-month for Hot LRS blob storage, ₹4.7995 per 10,000 Hot LRS writes, ₹2.8797 per 10,000 standard Key Vault operations and ₹57.5936 per million Event Grid event operations. Actual eligible free tiers, storage transaction mix, diagnostic export, volume, bandwidth, tax and subscription discounts can change the bill. The workspace's existing 0.1 GB/day daily quota is a collection safeguard, not a guaranteed invoice cap. Tenant-wide diagnostic export is not bounded by the number of synthetic email tests.

The first 5 GB/month of Analytics Logs ingestion is free **per billing account**, and another workload may consume that allowance. The retained 30 days are within the included Analytics retention period. [Azure Monitor pricing](https://azure.microsoft.com/en-in/pricing/details/monitor/), [Storage pricing](https://azure.microsoft.com/en-in/pricing/details/storage/blobs/), [Key Vault pricing](https://azure.microsoft.com/en-in/pricing/details/key-vault/), [Event Grid pricing](https://azure.microsoft.com/en-in/pricing/details/event-grid/).

The inventory also contains unrelated AI/search/Fabric resources. Their charges are excluded from the AgentTrace estimate. A read-only month-to-date Cost Management query returned HTTP 429, so no exact historical invoice amount is claimed. Public retail prices are estimates; the subscription's billing agreement determines actual charges. Recheck usage after the pilot begins and before enabling any additional Azure resource.
