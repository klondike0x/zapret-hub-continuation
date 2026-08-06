param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$OutputDir = "dist_nuitka",
    [string]$UninstallerSource = "",
    [string]$Version = "3.0.2",
    [ValidateSet("zig", "msvc", "mingw")]
    [string]$Compiler = "msvc"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$PythonExe = $Python
$srcRoot = Join-Path $root "src"
$versionParts = $Version.Split(".")
while ($versionParts.Count -lt 4) { $versionParts += "0" }
$fileVersion = ($versionParts[0..3] -join ".")
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($previousPythonPath)) { $srcRoot } else { "$srcRoot;$previousPythonPath" }
& $PythonExe scripts\sync_app_icon.py
if ($LASTEXITCODE -ne 0) { throw "sync_app_icon.py failed with exit code $LASTEXITCODE" }

$webUiRoot = Join-Path $root "web_ui"
if (-not (Test-Path (Join-Path $webUiRoot "node_modules"))) {
    & npm.cmd --prefix $webUiRoot ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci for web UI failed with exit code $LASTEXITCODE" }
}
& npm.cmd --prefix $webUiRoot run build
if ($LASTEXITCODE -ne 0) { throw "Web UI build failed with exit code $LASTEXITCODE" }
$stagingRoot = Join-Path $root ".nuitka_staging"
$runtimeStage = Join-Path $stagingRoot "runtime"
$webUiDistStage = Join-Path $stagingRoot "web_ui_dist"

if (Test-Path $stagingRoot) {
    Remove-Item $stagingRoot -Recurse -Force
}

New-Item -ItemType Directory -Path $runtimeStage -Force | Out-Null
# Freeze web_ui/dist so a concurrent vite rebuild cannot race Nuitka's data-file copy.
Copy-Item (Join-Path $webUiRoot "dist") $webUiDistStage -Recurse -Force

$excludeDirNames = @(".git", ".github", "__pycache__", ".mypy_cache", ".pytest_cache")
$excludeFilePatterns = @("*.pyc", "*.pyo")

Get-ChildItem (Join-Path $root "runtime") -Force | ForEach-Object {
    $name = $_.Name
    if ($excludeDirNames -contains $name) {
        return
    }
    $destination = Join-Path $runtimeStage $name
    if ($_.PSIsContainer) {
        Copy-Item $_.FullName $destination -Recurse -Force
    }
    else {
        Copy-Item $_.FullName $destination -Force
    }
}

foreach ($excludeDirName in $excludeDirNames) {
    Get-ChildItem $runtimeStage -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq $excludeDirName } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
}

foreach ($pattern in $excludeFilePatterns) {
    Get-ChildItem $runtimeStage -Recurse -File -Force -Filter $pattern -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

# runtime-конфиг vpn каждый раз собирается заново при запуске
$vpnGeneratedConfig = Join-Path $runtimeStage "v2rayN\goshkow-vpn"
if (Test-Path $vpnGeneratedConfig) {
    Remove-Item $vpnGeneratedConfig -Recurse -Force
}
$vpnSubscriptionHint = Join-Path $runtimeStage "v2rayN\goshkow-vpn-subscription.txt"
if (Test-Path $vpnSubscriptionHint) {
    Remove-Item $vpnSubscriptionHint -Force
}

# Drop Linux/Android/FreeBSD ELF + compile junk from Windows packages (keeps WinDivert).
& $PythonExe scripts\prune_windows_runtime.py $runtimeStage
if ($LASTEXITCODE -ne 0) { throw "prune_windows_runtime.py failed with exit code $LASTEXITCODE" }
& $PythonExe scripts\audit_windows_runtime.py $runtimeStage
if ($LASTEXITCODE -ne 0) { throw "audit_windows_runtime.py failed with exit code $LASTEXITCODE" }

$nuitkaArgs = @(
  "-m", "nuitka",
  # Prefer --standalone over --onefile for the main app: onefile self-extractors
  # are a common Defender ML false-positive (Bearfoos/Wacatac) trigger.
  "--standalone",
  "--assume-yes-for-downloads",
  "--no-deployment-flag=self-execution",
  "--enable-plugin=pyside6",
  "--windows-console-mode=disable",
  "--deployment",
  "--windows-icon-from-ico=ui_assets\icons\app_shell.ico",
  '--company-name=goshkow',
  '--product-name=Zapret Hub',
  "--file-version=$fileVersion",
  "--product-version=$fileVersion",
  '--file-description=Zapret Hub',
  '--copyright=goshkow',
  "--output-dir=$OutputDir",
  "--output-filename=Zapret_Hub.exe",
  "--include-data-dir=sample_data=sample_data",
  "--include-data-dir=ui_assets=ui_assets",
  "--include-data-files=docs\legal\ZAPRET_HUB_TERMS_RU.txt=docs\legal\ZAPRET_HUB_TERMS_RU.txt",
  "--include-data-dir=$webUiDistStage=web_ui\dist",
  "--include-package=zapret_hub",
  "--include-package=cryptography",
  "--include-package=certifi",
  "--include-package-data=certifi",
  "--nofollow-import-to=tkinter",
  "--lto=no",
  "--jobs=2",
  "--remove-output",
  "src\zapret_hub\main.py"
)

if ($Compiler -eq "zig") {
    $nuitkaArgs = @("-m", "nuitka", "--zig") + $nuitkaArgs[2..($nuitkaArgs.Length - 1)]
} elseif ($Compiler -eq "mingw") {
    $nuitkaArgs = @("-m", "nuitka", "--mingw64") + $nuitkaArgs[2..($nuitkaArgs.Length - 1)]
} else {
    $nuitkaArgs = @("-m", "nuitka", "--msvc=latest") + $nuitkaArgs[2..($nuitkaArgs.Length - 1)]
}

# Nuitka writes progress to stderr; do not treat that as a terminating error.
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $Python @nuitkaArgs
$nuitkaExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($nuitkaExit -ne 0) { throw "Nuitka app build failed with exit code $nuitkaExit" }

$distDir = Get-ChildItem -Path $OutputDir -Directory -Filter "*.dist" | Select-Object -First 1
if (-not $distDir) {
    throw "Nuitka output directory (*.dist) not found in $OutputDir"
}

# Keep only production WebEngine resources and the locales the application
# actually exposes. This runs after Nuitka, so it also covers bundled Qt files.
& $PythonExe scripts\prune_qt_runtime.py $distDir.FullName
if ($LASTEXITCODE -ne 0) { throw "prune_qt_runtime.py failed with exit code $LASTEXITCODE" }

$runtimeTarget = Join-Path $distDir.FullName "runtime"
if (Test-Path $runtimeTarget) {
    Remove-Item $runtimeTarget -Recurse -Force
}
Copy-Item $runtimeStage $runtimeTarget -Recurse -Force

# Keep the agreement visible at the root of every portable package as well.
Copy-Item -LiteralPath (Join-Path $root "docs\legal\ZAPRET_HUB_TERMS_RU.txt") `
  -Destination (Join-Path $distDir.FullName "ZAPRET_HUB_TERMS_RU.txt") -Force

$uninstallerCandidates = @()
if ($UninstallerSource) {
    $uninstallerCandidates += $UninstallerSource
}
$uninstallerCandidates += @(
    (Join-Path $root "bundled_uninstaller\uninstall_zaprethub.exe"),
    (Join-Path $root "dist_installer_3.0.2\uninstall_zaprethub.exe"),
    (Join-Path $root "dist_installer\uninstall_zaprethub.exe")
)
$uninstallerCopied = $false
foreach ($candidate in $uninstallerCandidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) {
        Copy-Item -LiteralPath $candidate -Destination (Join-Path $distDir.FullName "uninstall_zaprethub.exe") -Force
        Write-Host "Bundled uninstaller into portable dist: $(Join-Path $distDir.FullName 'uninstall_zaprethub.exe')"
        $uninstallerCopied = $true
        break
    }
}
if (-not $uninstallerCopied) {
    Write-Host "No uninstaller source found. Build the installer first or pass -UninstallerSource so portable packages include uninstall_zaprethub.exe."
}

if (Test-Path $stagingRoot) {
    Remove-Item $stagingRoot -Recurse -Force
}
