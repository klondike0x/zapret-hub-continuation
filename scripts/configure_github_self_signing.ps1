param(
    [string]$Repository = "goshkow/Zapret-Hub",
    [string]$CertificatePath = ".\\local-dev\\goshkow-zapret-hub-self-signed.pfx",
    [string]$PasswordPath = ".\\local-dev\\goshkow-zapret-hub-self-signed-password.txt"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI is required. Install it and authenticate with 'gh auth login'."
}
if (-not (Test-Path -LiteralPath $CertificatePath -PathType Leaf)) {
    throw "Certificate not found: $CertificatePath"
}
if (-not (Test-Path -LiteralPath $PasswordPath -PathType Leaf)) {
    throw "Certificate password file not found: $PasswordPath"
}

$pfxBase64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $CertificatePath)))
$password = [IO.File]::ReadAllText((Resolve-Path $PasswordPath)).Trim()
if ([string]::IsNullOrWhiteSpace($password)) {
    throw "The certificate password is empty."
}

$pfxBase64 | gh secret set WINDOWS_SIGNING_PFX_BASE64 --repo $Repository
$password | gh secret set WINDOWS_SIGNING_PFX_PASSWORD --repo $Repository
gh variable set WINDOWS_SIGNING_ALLOW_SELF_SIGNED --body "true" --repo $Repository

Write-Host "GitHub Actions self-signing configuration updated for $Repository."
Write-Warning "A self-signed certificate does not establish public publisher trust and does not guarantee antivirus reputation."
