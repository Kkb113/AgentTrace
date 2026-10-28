param([Parameter(Mandatory)][string]$ConfigurationPath, [switch]$Apply)
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$privateDirectory = Join-Path $repositoryRoot 'work\private\secure-access'

if (-not $Apply) {
    @{mode='plan';role='Application Mail.Read';mailbox_count=1;negative_control='dedicated_disabled_shared_mailbox';mail_send_or_write=$false} | ConvertTo-Json -Compress
    exit 0
}

try {
    $configFile = (Resolve-Path -LiteralPath $ConfigurationPath).Path
    if (-not $configFile.StartsWith($privateDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'private_sandbox_configuration_required' }
    $settings = Get-Content -LiteralPath $configFile -Raw -Encoding utf8 | ConvertFrom-Json
    $identities = Get-Content -LiteralPath (Join-Path $privateDirectory 'workload-identities.private.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $modulePath = Join-Path $repositoryRoot 'work\tools\ExchangeOnlineManagement\3.9.2\ExchangeOnlineManagement.psd1'
    Import-Module $modulePath
    $cliPython = Join-Path (Split-Path -Parent (Split-Path -Parent (Get-Command az).Source)) 'python.exe'
    $tokenResult = & $cliPython -IBm azure.cli account get-access-token --resource https://outlook.office365.com --subscription $settings.subscription --only-show-errors -o json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'exchange_administrator_token_unavailable' }
    Connect-ExchangeOnline -AccessToken $tokenResult.accessToken -UserPrincipalName $settings.mailbox -ShowBanner:$false -SkipLoadingFormatData -CommandName Get-EXOMailbox,Get-Mailbox,New-Mailbox,Get-Recipient,Get-ManagementScope,New-ManagementScope,Get-ServicePrincipal,New-ServicePrincipal,Get-ManagementRoleAssignment,New-ManagementRoleAssignment,Test-ServicePrincipalAuthorization,Get-AdminAuditLogConfig -ErrorAction Stop
    $approved = Get-Mailbox -Identity ([string]$settings.mailbox)
    $mailboxId = [Guid]::Parse($approved.ExternalDirectoryObjectId)
    $controlAddress = $settings.control_alias + '@' + $settings.mailbox.Split('@')[1]
    $control = Get-Mailbox -Identity $controlAddress -ErrorAction SilentlyContinue
    if (-not $control) {
        $control = New-Mailbox -Shared -Name 'AgentTrace Scope Control' -Alias $settings.control_alias -PrimarySmtpAddress $controlAddress
    }
    if ($control.RecipientTypeDetails -ne 'SharedMailbox' -or $control.DisplayName -ne 'AgentTrace Scope Control') { throw 'unexpected_existing_scope_control' }
    $scopeName = 'AgentTrace-Synthetic-Mailbox'
    $scope = Get-ManagementScope -Identity $scopeName -ErrorAction SilentlyContinue
    if (-not $scope) { $scope = New-ManagementScope -Name $scopeName -RecipientRestrictionFilter "ExternalDirectoryObjectId -eq '$mailboxId'" }
    $members = @(Get-Recipient -Filter $scope.RecipientFilter -ResultSize 10)
    if ($members.Count -ne 1 -or $members[0].ExternalDirectoryObjectId -ne $mailboxId) { throw 'mailbox_scope_does_not_match_exact_approved_mailbox' }
    $collector = $identities.'mail-collector'
    $appId = $collector.application.appId
    $principalId = $collector.service_principal.id
    $pointer = Get-ServicePrincipal -Identity $principalId -ErrorAction SilentlyContinue
    if (-not $pointer) { $pointer = New-ServicePrincipal -AppId $appId -ObjectId $principalId -DisplayName 'AgentTrace Sandbox mail-collector' }
    $assignments = @(Get-ManagementRoleAssignment -RoleAssignee $principalId)
    if ($assignments | Where-Object {$_.Role -ne 'Application Mail.Read' -or $_.CustomResourceScope -ne $scopeName}) { throw 'unexpected_existing_exchange_assignment' }
    if ($assignments.Count -eq 0) {
        New-ManagementRoleAssignment -Name 'AgentTrace-Synthetic-Mail-Read' -App $principalId -Role 'Application Mail.Read' -CustomResourceScope $scopeName | Out-Null
    }
    $allowed = @(Test-ServicePrincipalAuthorization -Identity $principalId -Resource $settings.mailbox)
    $denied = @(Test-ServicePrincipalAuthorization -Identity $principalId -Resource $controlAddress)
    $allowed | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $privateDirectory 'exchange-allowed-authorization.private.json')
    $denied | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 (Join-Path $privateDirectory 'exchange-denied-authorization.private.json')
    if ($allowed.Count -ne 1 -or $denied.Count -ne 1 -or $allowed[0].RoleName -ne 'Application Mail.Read' -or -not [bool]::Parse([string]$allowed[0].InScope) -or [bool]::Parse([string]$denied[0].InScope)) { throw 'exchange_scope_simulation_failed' }
    $settings | Add-Member -NotePropertyName mailbox_id -NotePropertyValue "$mailboxId" -Force
    $settings | Add-Member -NotePropertyName control_mailbox -NotePropertyValue $controlAddress -Force
    $settings | Add-Member -NotePropertyName control_mailbox_id -NotePropertyValue "$($control.ExternalDirectoryObjectId)" -Force
    $settings | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $configFile -Encoding utf8
    Get-AdminAuditLogConfig | Select-Object UnifiedAuditLogIngestionEnabled | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $privateDirectory 'exchange-audit-configuration.private.json')
    @{exchange_setup='complete';scope_member_count=$members.Count;allowed_simulation=$true;denied_simulation=$true;live_graph_checks_still_required=$true} | ConvertTo-Json -Compress
} catch {
    @{exception=$_.Exception.ToString();category=$_.CategoryInfo.ToString()} | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $privateDirectory 'exchange-configuration-error.private.json')
    [Console]::Error.Write('exchange_configuration_failed_see_private_diagnostic')
    exit 2
} finally {
    $tokenResult=$null
    Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue
}
