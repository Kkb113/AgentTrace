param([switch]$Apply)
$ErrorActionPreference = 'Stop'
$repositoryRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$targets = @('work\private', 'work\local')
if (-not $Apply) {
    @{mode='plan';directories=$targets;allowed='current Windows operator, SYSTEM, local administrators'} | ConvertTo-Json -Compress
    exit 0
}
if (-not $IsWindows) { throw 'windows_acl_configuration_required' }
$operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$allowed = @($operatorSid, [Security.Principal.SecurityIdentifier]::new('S-1-5-18'), [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach ($relative in $targets) {
    $target = [IO.Path]::GetFullPath((Join-Path $repositoryRoot $relative))
    if (-not $target.StartsWith($repositoryRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'sandbox_path_escape' }
    if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'sandbox_directory_missing' }
    $acl = [Security.AccessControl.DirectorySecurity]::new()
    $acl.SetOwner($operatorSid)
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in $allowed) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $target -AclObject $acl
    $verified = Get-Acl -LiteralPath $target
    if (-not $verified.AreAccessRulesProtected) { throw 'private_acl_not_enforced' }
}
@{private_evidence_and_local_credentials='operator_restricted';directories_protected=$targets.Count;secret_values_logged=$false} | ConvertTo-Json -Compress
