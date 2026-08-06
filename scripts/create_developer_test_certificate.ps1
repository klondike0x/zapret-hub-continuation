param(
    [string]$OutputPath = ".\\local-dev\\zapret-hub-continuation-self-signed.pfx",
    [Parameter(Mandatory = $true)]
    [string]$Password,
    [string]$Subject = "CN=zapret-hub-continuation, O=zapret-hub-continuation, C=RU"
)

$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "This helper creates a Windows Authenticode certificate and must run on Windows."
}

$output = [IO.Path]::GetFullPath($OutputPath)
$directory = Split-Path -Parent $output
New-Item -ItemType Directory -Path $directory -Force | Out-Null

if (Test-Path -LiteralPath $output) {
    throw "Refusing to overwrite an existing certificate: $output"
}

# This certificate proves integrity only for people who explicitly trust its root.
# It is useful for local testing and a stable publisher identity, but is not a
# substitute for a CA-issued Authenticode certificate or Microsoft Trusted Signing.
$certificate = New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -FriendlyName "Zapret Hub developer signing (zapret-hub-continuation)" `
    -CertStoreLocation "Cert:\CurrentUser\My" `
    -KeyAlgorithm RSA `
    -KeyLength 3072 `
    -HashAlgorithm SHA256 `
    -KeyExportPolicy Exportable `
    -NotAfter (Get-Date).AddYears(2)

$securePassword = ConvertTo-SecureString -String $Password -AsPlainText -Force
Export-PfxCertificate -Cert $certificate -FilePath $output -Password $securePassword | Out-Null

Write-Host "Self-signed developer certificate created: $output"
Write-Host "Thumbprint: $($certificate.Thumbprint)"
Write-Host "Use only through a private GitHub Actions secret. Never commit the PFX or its password."
