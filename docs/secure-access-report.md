# Secure-access implementation review

Status: Phase 2 complete with all six technical/acceptance exits met. Review date: 29 October 2026. All five local gates passed; the final PR remains subject to the existing required checks before merge. This is a synthetic-access milestone, not a production or detector-accuracy qualification.

## Implemented boundary

Six distinct Entra registrations separate mailbox collection, Exchange audit collection, attribution, content, API and the access-test client. Their certificates are non-exportable 3072-bit Windows CNG keys with ninety-day validity; no private key, client secret or token is committed. The exact-mailbox collector has only Exchange Application RBAC Application Mail.Read, with no parallel Entra mailbox role. A dedicated disabled-sign-in shared mailbox is the negative scope control. The former temporary feasibility reader remains retired.

The owner explicitly accepted the concrete [permission matrix](permissions-matrix.md) and [data flow](data-flow.md) as project owner, Microsoft 365 administrator and security owner. This includes broader tenant-wide Exchange audit visibility for the separate audit identity; query filters minimize processing and do not scope that permission to one mailbox. No source agent credential or mail mutation grant exists.

The API validates RS256 signature, trusted tenant-specific keys/issuer, audience, tenant, time claims, caller, access-token type, role and server-owned mailbox/message entitlement. Human viewer/investigator/administrator roles are configured in Entra. Machine access is limited to the enrolled viewer client. ID tokens cannot substitute for API access tokens. Missing configuration fails closed; readiness includes authorization. A real Entra-issued API token was exercised over TCP, and security events were emitted without tokens/body text.

Local PostgreSQL uses individual API, attribution, content and collector logins. SQL grants and row security separate queues and health writes; the API cannot access jobs or mutate decisions, and content cannot read agent decisions. Direct SQL rejects body-bearing queue payloads and retention extensions. Only migration holds the local database owner credential. Runtime containers get individual secrets; content has no external route, Windows key-store access or other workload credential. Windows private evidence/local credentials are restricted to the operator, SYSTEM and administrators.

## Azure and evidence-source verification

The accepted minimal hybrid design keeps compute and PostgreSQL local. Dedicated East US Standard LRS Storage and Standard Key Vault resources are deployed in kb-agentdemo. Azure data-plane roles target exact queues, the raw container and the signing key. Custom signer/verifier roles contain only the required cryptographic data actions. Actual grant inventories show no inherited broad/control-plane or directory-administrator role for a workload. See [the cost boundary](secure-access-cost.md).

Storage disables shared-key and anonymous blob access. Storage/Key Vault require Entra authorization and exact operator-IP firewalls with default deny and no trusted-service bypass. The first ARM key-create request was rejected by that firewall; key creation was moved to the operator data endpoint rather than opening the firewall. Both deployment previews reject deletion, shared-resource modification and changes outside the required group. The signing key is reused on repeat provisioning.

Live Graph calls succeeded for the enrolled mailbox and its already approved synthetic Claude-test body. The collector received 403 for the known, disabled control mailbox. Content, attribution and audit identities received 403 for direct mailbox reads. Effective Entra app-role and delegated-grant inventories match the approved design exactly. Exchange scope simulation is supporting evidence; it is not substituted for these live calls.

Live Azure calls verified allowed raw-evidence reads, reference enqueues, queue reads, signing and verification. Wrong workloads received 403 on the opposite queue, raw/other container and signing operation. The API verified a signature while being denied signing. Public-key retrieval returned no private key material. Resource-specific access and denial events were actually ingested into the existing approved workspace, queried using only the new project resource IDs.

The separate application audit identity created a tightly bounded read query, waited for completion and retrieved the existing synthetic send evidence. No email was sent, drafted, edited, moved or deleted by AgentTrace or its test harness. All source responses/real identifiers remain in protected ignored storage; published evidence contains reviewed aliases, statuses and booleans.

## Retention, content and remaining limits

Raw blobs have effective seven-day lifecycle deletion with versioning/soft-delete disabled. Application raw reads reject expired/out-of-scope references before obtaining data. Azure lifecycle cleanup is asynchronous; Blob Reader itself has no timestamp condition, so a compromised reader credential remains a residual risk until physical deletion. SQL row security hides expired decisions at thirty days even through a direct API database login. Physical decision purge, backups/restore and executed credential-rotation/revocation qualification remain later milestones; the procedures are documented in [the access runbook](runbooks/secure-access.md).

Optional generation histories have no grants or enabled connector. Content/body capabilities require an enrolled synthetic message, version and current authorization. Content egress is denied in policy and by the running internal container network. No content model or external inference fallback is configured, and content remains unknown. Statistical content scoring, continuous ingestion/reconciliation, cloud runtime/managed identities, add-in UI/selected-message sign-in and production rollout remain later work.

This Windows hybrid sandbox trusts its host administrator, who can invoke all six local credentials. It uses authenticated, IP-restricted public Azure endpoints and makes no Private Link claim. The narrow Claude evidence path remains the original feasibility basis; access tests and authored fixtures do not establish false-positive rates, universal external-agent coverage, AI-text accuracy or regulatory certification.

## Validation

All 79 live access/configuration checks passed across mailbox, effective grants, Azure data operations, Exchange audit retrieval, actual Entra API authentication and ingested access logs. The full local run passed 135 unit/security tests, 24 integration/end-to-end tests and 52 subtests (211 JUnit cases including subtests), with zero errors, failures or skips. Strict typing, formatting, locks/contracts, secret/privacy/license/vulnerability review and all seven Bicep templates/modules passed. Invalid-contract, failing-test and synthetic-secret controls each returned exit 1 as required. PostgreSQL statements, parameters and error row details are disabled in the running server and verified through actual settings.

## Exit evidence

The six Phase 2 exits are tracked in config/secure-access-exits.json. Sanitized live evidence, local validation and explicit acceptance are under docs/evidence. Tests found and corrected FastAPI dependency-annotation handling, Windows CLI encodings/string-valued results, authenticated fixture enrollment and the firewall-preserving signing-key bootstrap. Local socket tests require loopback access; a restricted Windows tool sandbox could not create its socket pair, so tests were rerun with appropriate local execution access.

The existing client workbook is outside this implementation and remains unstaged. GitHub Actions remains the active protected-PR provider, with equivalent Azure Pipelines YAML retained. Cloud setup and live probes are operator-only and are not run with cloud credentials inside public PR CI.
