# Infrastructure validation boundary

Run python scripts/validate-infrastructure.py after bootstrapping the pinned Bicep validator. All seven templates/modules and the no-provisioning parameter file compile locally. Validation performs no deployment.

Both roots default to enableProvisioning=false, location eastus and the allowed group kb-agentdemo. Even opt-in provisioning requires the caller's actual group to match. The earlier main.bicep future-stack template keeps public storage/database/vault access disabled and its managed identities/cloud compute undeployed.

The accepted access-sandbox.bicep deployment creates only dedicated Standard LRS Storage, Standard Key Vault, exact data roles and resource access diagnostics. It uses authenticated public endpoints with default-deny operator-IP firewalls and no bypass. Signing-key bootstrap uses the operator data endpoint; the second deployment binds exact key roles. Compute/PostgreSQL stay local. Mail/agent execution grants are absent. See the secure-access runbook and cost boundary before operator-only what-if/apply.

These templates do not make a production deployment ready: actual identity/RBAC, private connectivity, secrets, image registry/digest, application configuration and cost what-if must be reviewed in the identity/deployment milestones. The foundation API fails closed for non-local configuration. Do not set provisioning true merely to test compilation, and do not deploy into or remove unrelated shared resources.
