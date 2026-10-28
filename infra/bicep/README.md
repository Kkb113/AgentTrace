# Infrastructure validation boundary

Run python scripts/validate-infrastructure.py after bootstrapping the pinned Bicep validator. All six modules and the no-provisioning parameter file compile locally. No deployment is performed.

The root defaults to enableProvisioning=false, location eastus and the allowed group kb-agentdemo. Even opt-in provisioning requires the caller's actual group to match. Potential components use Standard LRS storage, Standard Key Vault, Burstable PostgreSQL B1ms, distinct managed identities and bounded Container Apps CPU/replicas. Mail/agent execution grants are absent. Public storage/database/vault access is disabled.

These templates do not make a production deployment ready: actual identity/RBAC, private connectivity, secrets, image registry/digest, application configuration and cost what-if must be reviewed in the identity/deployment milestones. The foundation API fails closed for non-local configuration. Do not set provisioning true merely to test compilation, and do not deploy into or remove unrelated shared resources.
