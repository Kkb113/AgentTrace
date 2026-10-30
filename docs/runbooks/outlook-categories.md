# Outlook category setup and preview

Use the approved private configuration in `C:\AgentDetection\work\private\outlook-categories`. Never commit actual mailbox/tenant/application identifiers, certificates, tokens or message references. These commands require the designated Windows operator profile and its non-exportable writer certificate. They do not send email.

The completed deployment has three owned master definitions and a retired setup identity. The monitor still does not apply categories. Do not rerun provisioning or the permission probe during routine monitoring.

## Verify and preview

Choose a fresh private report filename for every execution. Existing report files are not overwritten.

```powershell
Set-Location C:\AgentDetection
& .venv\Scripts\python.exe scripts\setup-outlook-categories.py verify `
  --settings work\private\outlook-categories\settings.private.json `
  --output work\private\outlook-categories\verification-new.private.json

& .venv\Scripts\python.exe scripts\setup-outlook-categories.py preview `
  --settings work\private\outlook-categories\settings.private.json `
  --runtime-config work\private\sender-rules-live\runtime.private.json `
  --output work\private\outlook-categories\preview-new.private.json
```

Preview reads the runtime's latest persisted synthetic decisions and current category inventory/message metadata. It may require stopping the runtime to obtain its exclusive state lease. Inspect `preview_rows` in the private report: `would_change` is a proposal, not a completed write; `skipped` needs investigation or fresh evidence. Console output contains only sanitized summary fields. Keep private reports under the existing operator-only ACL/retention controls. The ownership registry is durable configuration: preserve it in the protected runtime backup and do not expire it as raw mail evidence.

## Administrator-only inventory

```powershell
& .venv\Scripts\python.exe scripts\configure-category-access.py inspect `
  --directory work\private\outlook-categories
pwsh -NoProfile -File scripts\configure-category-access.ps1 `
  -ConfigurationPath work\private\outlook-categories\proposal.private.json -Operation Inspect
```

Inspect both Entra and Exchange records. Expect two writer roles in the exact one-member scope, no additive Entra grants, no setup Exchange pointer, and a retired setup manifest. An authorization simulator alone is insufficient for new scope changes. Fail closed on unexpected permissions and pause use until corrected; never broaden a scope to fix a 403.

## Setup lifecycle and recovery

For a fresh approved deployment, the operator prepares `proposal.private.json` containing explicit tenant/subscription, approved mailbox and negative-control UUID/address pairs, and `management_scope: AgentTrace-Category-Mailbox`. Review the exact [proposal](../category-access-proposal.md) before `register` or Exchange `Configure`. Python registration creates only the two fixed tagged single-tenant principals and non-exportable certificates; PowerShell creates their exact Exchange assignments. Build private `settings.private.json` against [the settings schema](../../packages/contracts/schemas/outlook-category-settings.schema.json), using distinct writer/setup client IDs and certificate thumbprints, an absolute private local ownership directory and `automatic_application_enabled: false`. No generic example includes tenant identifiers or a credential.

While the short-lived setup credential is valid, `provision` creates only missing, conflict-free master definitions and saves confirmed ownership after each response. `verify` uses the writer. The one-shot `probe --message-id <immutable-synthetic-id>` uses the writer to PATCH only a captured current categories array unchanged, with If-Match, read it back and check out-of-scope denials. This is an explicitly authorized diagnostic operation and is not the runtime writer. Recheck a separate collector's denial and the absence of send/full-access grants. Do not treat 404, 401, throttling or local validation as proof of server scope denial.

Retirement order after successful setup:

1. `configure-category-access.ps1 -Operation RetireSetup` removes the exact temporary Exchange assignments/pointer and preserves its receipt.
2. `configure-category-access.py retire-setup --directory work\private\outlook-categories` requires that receipt, validates the tagged registration, disables/deletes only its Entra principal/application and records retirement.
3. Verify new setup-token issuance is denied while its exact key still exists. Record any issued-token/cache window without saving the token.
4. `retire-category-setup-certificate.ps1 -Directory work\private\outlook-categories` validates the manifest, certificate thumbprint, public bytes and friendly name before deleting only that certificate/private key. Then set `setup_identity` to null and verify with the writer.

The executed deployment completed all four steps. See [retirement evidence and token-cache caveat](../outlook-category-access.md). Reconfiguration with the retired manifest is blocked; deletion is not automatic permission to recreate an app.

If setup loses a POST response, do not adopt the now-existing name or delete it blindly. Inspect the private receipt/provider inventory and obtain a concrete recovery decision. A confirmed partial registry can resume without recreating recorded IDs. Missing/renamed/recolored/replaced categories block use; do not silently fix or claim ownership of replacements. Preserve registry backups, unrelated categories and user changes. A crashed atomic save leaves the previous committed registry intact; an unrecorded create remains a conflict requiring reconciliation.

A 403 can reflect scope, grant or propagation errors. Inspect authorization and wait for documented permission caching when justified; do not change tenant policy or add Entra mail permissions. Expired writer credentials need a reviewed rotation before use. The writer can technically modify other permitted mail properties in its scope; code restrictions are not field-level Microsoft credentials. Phase 6 must qualify write-intent recovery, concurrency, readback and rollback before classification application is available.
