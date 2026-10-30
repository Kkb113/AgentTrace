param([ValidateSet('Create', 'Sign')][string]$Operation)
$ErrorActionPreference = 'Stop'

function ConvertTo-Base64Url([byte[]]$Value) {
    return [Convert]::ToBase64String($Value).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

try {
    $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($Operation -eq 'Create') {
        if ($request.alias -notin @('mail-collector', 'audit-collector', 'attribution', 'content', 'api', 'access-test', 'category-writer', 'category-setup')) {
            throw 'unknown_workload'
        }
        $days = if ($request.alias -eq 'category-setup') { 1 } elseif ($request.alias -eq 'category-writer') { 30 } else { 90 }
        $certificate = New-SelfSignedCertificate -Subject "CN=AgentTrace Sandbox $($request.alias)" -FriendlyName "AgentTrace Sandbox $($request.alias)" -CertStoreLocation Cert:\CurrentUser\My -Provider 'Microsoft Software Key Storage Provider' -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 -KeyUsage DigitalSignature -KeyExportPolicy NonExportable -NotAfter (Get-Date).AddDays($days)
        @{
            thumbprint = $certificate.Thumbprint
            certificate = [Convert]::ToBase64String($certificate.RawData)
            not_before = $certificate.NotBefore.ToUniversalTime().ToString('o')
            not_after = $certificate.NotAfter.ToUniversalTime().ToString('o')
        } | ConvertTo-Json -Compress
    } else {
        if ($request.thumbprint -notmatch '^[0-9A-Fa-f]{40}$') { throw 'invalid_certificate_reference' }
        $tenant = [Guid]::Parse($request.tenant)
        $client = [Guid]::Parse($request.client)
        $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$($request.thumbprint)"
        if (-not $certificate.HasPrivateKey -or -not $certificate.FriendlyName.StartsWith('AgentTrace Sandbox ') -or $certificate.NotAfter.ToUniversalTime() -le [DateTime]::UtcNow) { throw 'credential_unavailable' }
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $header = @{ alg='RS256'; typ='JWT'; x5t=(ConvertTo-Base64Url $certificate.GetCertHash()) } | ConvertTo-Json -Compress
        $claims = @{ aud="https://login.microsoftonline.com/$tenant/oauth2/v2.0/token"; iss="$client"; sub="$client"; jti=[Guid]::NewGuid().ToString(); nbf=($now-5); iat=$now; exp=($now+300) } | ConvertTo-Json -Compress
        $unsigned = (ConvertTo-Base64Url ([Text.Encoding]::UTF8.GetBytes($header))) + '.' + (ConvertTo-Base64Url ([Text.Encoding]::UTF8.GetBytes($claims)))
        $privateKey = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($certificate)
        try {
            $signature = $privateKey.SignData([Text.Encoding]::UTF8.GetBytes($unsigned), [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
            [Console]::Out.Write($unsigned + '.' + (ConvertTo-Base64Url $signature))
        } finally { $privateKey.Dispose() }
    }
} catch {
    [Console]::Error.Write('workload_certificate_operation_failed')
    exit 2
}
