param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$resolved = (Resolve-Path -LiteralPath $Path).Path
$acl = Get-Acl -LiteralPath $resolved
$owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
$allowed = @($identity, 'S-1-5-18', 'S-1-5-32-544')
$unexpected = @($acl.Access | Where-Object {
    $_.AccessControlType -eq 'Allow' -and
    $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -notin $allowed
})
@{
    principal = $identity
    owner = $owner
    private_access = ($owner -eq $identity -and $unexpected.Count -eq 0)
    inheritance_protected = $acl.AreAccessRulesProtected
} | ConvertTo-Json -Compress
