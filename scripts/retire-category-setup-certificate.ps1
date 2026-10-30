param([Parameter(Mandatory)][string]$Directory)
$ErrorActionPreference='Stop'
try {
    $root=[IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $PSScriptRoot) 'work/private/outlook-categories'))
    if ((Resolve-Path -LiteralPath $Directory).Path -ne $root) { throw 'exact_category_directory_required' }
    $identities=Get-Content -LiteralPath (Join-Path $root 'identities.private.json') -Raw -Encoding utf8 | ConvertFrom-Json
    $setup=$identities.'category-setup'
    if (-not $setup.retired_at -or $setup.certificate.thumbprint -notmatch '^[A-Fa-f0-9]{40}$') { throw 'retired_setup_registration_required' }
    $path='Cert:\CurrentUser\My\'+$setup.certificate.thumbprint
    $certificate=Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    if ($certificate) {
        if ($certificate.FriendlyName -ne 'AgentTrace Sandbox category-setup' -or [Convert]::ToBase64String($certificate.RawData) -ne $setup.certificate.certificate) { throw 'setup_certificate_target_mismatch' }
        Remove-Item -LiteralPath $path -DeleteKey -Force
    }
    if (Test-Path -LiteralPath $path) { throw 'setup_certificate_not_removed' }
    @{temporary_setup_certificate_removed=$true;writer_certificate_unchanged=$true} | ConvertTo-Json -Compress
} catch {
    [Console]::Error.Write('category_setup_certificate_retirement_failed')
    exit 2
}
