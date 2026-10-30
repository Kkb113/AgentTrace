param([Parameter(Mandatory)][string]$ConfigurationPath, [ValidateSet('Configure','Inspect','RetireSetup')][string]$Operation='Inspect')
$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$privateRoot = [IO.Path]::GetFullPath((Join-Path $repositoryRoot 'work/private/outlook-categories'))
$exchangeConnected = $false
try {
    $configuration = (Resolve-Path -LiteralPath $ConfigurationPath).Path
    if (-not $configuration.StartsWith($privateRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'private_category_configuration_required' }
    $settings = Get-Content -LiteralPath $configuration -Raw -Encoding utf8 | ConvertFrom-Json
    $identities = Get-Content -LiteralPath (Join-Path $privateRoot 'identities.private.json') -Raw -Encoding utf8 | ConvertFrom-Json
    if ($Operation -eq 'Configure' -and $identities.'category-setup'.retired_at) { throw 'retired_setup_requires_new_review' }
    if ($settings.management_scope -ne 'AgentTrace-Category-Mailbox') { throw 'unexpected_scope_name' }
    Import-Module (Join-Path $repositoryRoot 'work/tools/ExchangeOnlineManagement/3.9.2/ExchangeOnlineManagement.psd1')
    $cliPython = Join-Path (Split-Path -Parent (Split-Path -Parent (Get-Command az).Source)) 'python.exe'
    $token = & $cliPython -IBm azure.cli account get-access-token --resource https://outlook.office365.com --subscription $settings.subscription --only-show-errors -o json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'administrator_token_unavailable' }
    Connect-ExchangeOnline -AccessToken $token.accessToken -UserPrincipalName $settings.mailbox -ShowBanner:$false -SkipLoadingFormatData -CommandName Get-Mailbox,Get-Recipient,Get-ManagementScope,New-ManagementScope,Get-ServicePrincipal,New-ServicePrincipal,Remove-ServicePrincipal,Get-ManagementRoleAssignment,New-ManagementRoleAssignment,Remove-ManagementRoleAssignment,Test-ServicePrincipalAuthorization -ErrorAction Stop
    $exchangeConnected = $true
    $mailbox = Get-Mailbox -Identity ([string]$settings.mailbox)
    if ([string]$mailbox.ExternalDirectoryObjectId -ne [string]$settings.mailbox_id) { throw 'mailbox_identity_changed' }
    $mailboxId = [Guid]::Parse([string]$settings.mailbox_id)
    $controlId = [Guid]::Parse([string]$settings.control_mailbox_id)
    if ($mailboxId -eq $controlId) { throw 'distinct_negative_mailbox_required' }
    $control = Get-Mailbox -Identity ([string]$settings.control_mailbox)
    if ([string]$control.ExternalDirectoryObjectId -ne [string]$controlId -or $control.RecipientTypeDetails -ne 'SharedMailbox' -or $control.DisplayName -ne 'AgentTrace Scope Control') { throw 'dedicated_negative_control_required' }
    $filter = "ExternalDirectoryObjectId -eq '$mailboxId'"
    $scope = Get-ManagementScope -Identity $settings.management_scope -ErrorAction SilentlyContinue
    if (-not $scope) {
        $existing = Get-ManagementScope -Identity 'AgentTrace-Synthetic-Mailbox' -ErrorAction SilentlyContinue
        if ($existing -and $existing.RecipientFilter.Trim([char[]]' ()') -eq $filter) { $scope = $existing }
    }
    if (-not $scope -and $Operation -eq 'Configure') { $scope = New-ManagementScope -Name $settings.management_scope -RecipientRestrictionFilter $filter }
    if (-not $scope -or $scope.RecipientFilter.Trim([char[]]' ()') -ne $filter) { throw 'exact_scope_filter_required' }
    $effectiveScope = [string]$scope.Name
    $members = @(Get-Recipient -Filter $scope.RecipientFilter -ResultSize 3)
    if ($members.Count -ne 1 -or [string]$members[0].ExternalDirectoryObjectId -ne [string]$settings.mailbox_id) { throw 'exact_one_mailbox_scope_required' }
    $report = @{}
    foreach ($alias in @('category-writer','category-setup')) {
        $entry = $identities.$alias
        if (-not $entry.application.appId -or -not $entry.service_principal.id) { throw 'registration_required' }
        $principal = [string]$entry.service_principal.id
        $pointer = Get-ServicePrincipal -Identity $principal -ErrorAction SilentlyContinue
        if ($entry.retired_at) {
            if ($pointer) { throw 'retired_exchange_pointer_still_present' }
            $report[$alias] = @{retired=$true;exchange_pointer_removed=$true;exchange_assignments_removed=$true}
            continue
        }
        if (-not $pointer -and $Operation -eq 'Configure') { $pointer = New-ServicePrincipal -AppId $entry.application.appId -ObjectId $principal -DisplayName $entry.application.displayName }
        if (-not $pointer) { throw 'expected_exchange_pointer_missing' }
        if ($pointer -and ([string]$pointer.AppId -ne [string]$entry.application.appId)) { throw 'exchange_pointer_mismatch' }
        $roles = if ($alias -eq 'category-writer') { @('Application Mail.ReadWrite','Application MailboxSettings.Read') } else { @('Application MailboxSettings.ReadWrite') }
        $assignments = if ($pointer) { @(Get-ManagementRoleAssignment -RoleAssignee $principal) } else { @() }
        foreach ($assignment in $assignments) {
            if ([string]$assignment.Role -notin $roles -or [string]$assignment.CustomResourceScope -ne $effectiveScope) { throw 'unexpected_existing_role_assignment' }
        }
        if ($Operation -eq 'RetireSetup' -and $alias -eq 'category-setup') {
            foreach ($assignment in $assignments) { Remove-ManagementRoleAssignment -Identity $assignment.Identity -Confirm:$false }
            if ($pointer) { Remove-ServicePrincipal -Identity $principal -Confirm:$false }
            $report[$alias] = @{exchange_assignments_removed=$true;exchange_pointer_removed=$true}
            continue
        }
        if ($Operation -eq 'Configure') {
            foreach ($role in $roles) {
                if (-not ($assignments | Where-Object { [string]$_.Role -eq $role })) {
                    $suffix = $role.Replace('Application ','').Replace('.','-')
                    New-ManagementRoleAssignment -Name "AgentTrace-$alias-$suffix" -App $principal -Role $role -CustomResourceScope $effectiveScope | Out-Null
                }
            }
        }
        if ($pointer) {
            $allowed = @(Test-ServicePrincipalAuthorization -Identity $principal -Resource $settings.mailbox)
            $denied = @(Test-ServicePrincipalAuthorization -Identity $principal -Resource $settings.control_mailbox)
            if ($allowed.Count -ne $roles.Count -or $denied.Count -ne $roles.Count) { throw 'authorization_role_count_mismatch' }
            if ($allowed | Where-Object { -not [bool]::Parse([string]$_.InScope) }) { throw 'approved_mailbox_not_in_scope' }
            if ($denied | Where-Object { [bool]::Parse([string]$_.InScope) }) { throw 'control_mailbox_in_scope' }
            $report[$alias] = @{assignments=@(Get-ManagementRoleAssignment -RoleAssignee $principal | Select-Object Name,Role,CustomResourceScope);allowed=$allowed;denied=$denied}
        }
    }
    $report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $privateRoot ('exchange-' + $Operation.ToLowerInvariant() + '.private.json')) -Encoding utf8
    @{operation=$Operation;scope_member_count=1;existing_identical_scope_reused=($effectiveScope -ne [string]$settings.management_scope);exchange_configuration_verified=$true;live_graph_verification_required=$true} | ConvertTo-Json -Compress
} catch {
    $_.Exception.ToString() | Set-Content -LiteralPath (Join-Path $privateRoot 'exchange-error.private.txt') -Encoding utf8
    [Console]::Error.Write('category_exchange_configuration_failed_see_private_diagnostic')
    exit 2
} finally {
    $token=$null
    if ($exchangeConnected) { Disconnect-ExchangeOnline -Confirm:$false -ErrorAction SilentlyContinue }
}
