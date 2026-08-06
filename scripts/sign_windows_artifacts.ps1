param(
    [Parameter(Mandatory = $true)]
    [string[]]$Files,
    [string]$PfxPath = $env:WINDOWS_SIGNING_PFX_PATH,
    [string]$PfxPassword = $env:WINDOWS_SIGNING_PFX_PASSWORD,
    [string]$Thumbprint = $env:WINDOWS_SIGNING_CERT_THUMBPRINT,
    [string]$TimestampUrl = "http://timestamp.acs.microsoft.com",
    [switch]$RequireSignature,
    [switch]$AllowUntrustedSelfSigned
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $candidate = Get-ChildItem $kitsRoot -Recurse -File -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
        Sort-Object FullName -Descending |
        Select-Object -First 1
    if ($candidate) {
        return $candidate.FullName
    }
    throw "signtool.exe was not found. Install the Windows SDK signing tools."
}

$resolvedFiles = foreach ($file in $Files) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Signing target does not exist: $file"
    }
    (Resolve-Path -LiteralPath $file).Path
}

$hasPfx = -not [string]::IsNullOrWhiteSpace($PfxPath)
$hasThumbprint = -not [string]::IsNullOrWhiteSpace($Thumbprint)
if (-not $hasPfx -and -not $hasThumbprint) {
    if ($RequireSignature) {
        throw "No Authenticode certificate configured. Set WINDOWS_SIGNING_PFX_PATH or WINDOWS_SIGNING_CERT_THUMBPRINT."
    }
    Write-Warning "Authenticode certificate is not configured; artifacts remain unsigned."
    exit 0
}

$signTool = Find-SignTool
$allowSelfSigned = $AllowUntrustedSelfSigned -or ($env:WINDOWS_SIGNING_ALLOW_SELF_SIGNED -eq "true")
foreach ($file in $resolvedFiles) {
    $arguments = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $TimestampUrl)
    if ($hasPfx) {
        if (-not (Test-Path -LiteralPath $PfxPath -PathType Leaf)) {
            throw "PFX file does not exist: $PfxPath"
        }
        $arguments += @("/f", (Resolve-Path -LiteralPath $PfxPath).Path)
        if (-not [string]::IsNullOrEmpty($PfxPassword)) {
            $arguments += @("/p", $PfxPassword)
        }
    }
    else {
        $arguments += @("/sha1", ($Thumbprint -replace "\s", ""))
    }
    $arguments += $file

    & $signTool @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "signtool failed for $file with exit code $LASTEXITCODE"
    }
    & $signTool verify /pa /all $file
    if ($LASTEXITCODE -ne 0) {
        if (-not $allowSelfSigned) {
            throw "Authenticode verification failed for $file"
        }
        $signature = Get-AuthenticodeSignature -FilePath $file
        $certificate = $signature.SignerCertificate
        if ($signature.SignatureType -ne "Authenticode" -or $null -eq $certificate) {
            throw "The fallback verification found no Authenticode signature on $file"
        }
        if ($certificate.Subject -ne $certificate.Issuer) {
            throw "The untrusted-signature fallback only accepts a self-signed certificate for $file"
        }
        Write-Warning "Using an untrusted self-signed signature for $file. Windows will not treat it as a trusted publisher."
    }
}

# signtool verify returns 1 for a valid self-signed certificate that is not in
# the runner's trusted-root store. Once the fallback above has checked that an
# Authenticode signature is actually present, do not leak that stale native
# exit code to callers such as the installer build script.
$global:LASTEXITCODE = 0
