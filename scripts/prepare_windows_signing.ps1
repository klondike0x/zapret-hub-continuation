param(
    [string]$CertificatePath = (Join-Path $env:RUNNER_TEMP "zapret-hub-signing.pfx"),
    [string]$Subject = "CN=goshkow, O=Goshkow, C=RU"
)

$ErrorActionPreference = "Stop"

if (-not [string]::IsNullOrWhiteSpace($env:WINDOWS_SIGNING_PFX_BASE64)) {
    [IO.File]::WriteAllBytes($CertificatePath, [Convert]::FromBase64String($env:WINDOWS_SIGNING_PFX_BASE64))
    $env:WINDOWS_SIGNING_PFX_PATH = $CertificatePath
    return
}

# The fallback key exists only inside the ephemeral GitHub Actions runner.
# It is never written to Git, a release asset or an update archive. A stable
# PFX from Actions Secrets takes precedence whenever it is configured.
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 32
$rng.GetBytes($bytes)
$rng.Dispose()
$password = [Convert]::ToBase64String($bytes)
$securePassword = ConvertTo-SecureString -String $password -AsPlainText -Force
$certificate = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -FriendlyName "Zapret Hub build signing (goshkow)" `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -KeyAlgorithm RSA `
    -KeyLength 3072 `
    -HashAlgorithm SHA256 `
    -KeyExportPolicy Exportable `
    -NotAfter (Get-Date).AddYears(2)
Export-PfxCertificate -Cert $certificate -FilePath $CertificatePath -Password $securePassword | Out-Null

$env:WINDOWS_SIGNING_PFX_PATH = $CertificatePath
$env:WINDOWS_SIGNING_PFX_PASSWORD = $password
$env:WINDOWS_SIGNING_ALLOW_SELF_SIGNED = "true"
Write-Warning "No trusted PFX secret is configured. Using an ephemeral self-signed goshkow certificate for this build."
