param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$PayloadDir = "installer_payload",
    [string]$OutputDir = "dist_installer",
    [string]$ReleaseDir = "release_3.0.2",
    [string]$Version = "3.0.2",
    [string]$X64Source = "",
    [string]$Arm64Source = "",
    [string]$UninstallerX64Source = "",
    [string]$UninstallerArm64Source = "",
    [switch]$SkipPrepareRelease,
    [switch]$Standalone,
    # Default: do NOT embed another EXE inside the installer (PE-in-PE → Defender Bearfoos/Wacatac ML).
    # Opt in only when you explicitly need a self-contained uninstaller payload.
    [switch]$EmbedUninstaller,
    # Kept for CI/scripts that already pass -SkipUninstaller (now the default behavior).
    [switch]$SkipUninstaller,
    [switch]$UninstallerOnly,
    [switch]$RequireInnerSignature,
    [ValidateSet("zig", "msvc", "mingw")]
    [string]$Compiler = "msvc"
)

# Slim installer: downloads runtime from goshkow.com; does NOT embed installer_payload/*.zip.
# Prefer exit-code checks over treating Nuitka stderr progress as terminating errors.
$ErrorActionPreference = "Continue"
if (Test-Path variable:PSNativeCommandUseErrorActionPreference) {
  $PSNativeCommandUseErrorActionPreference = $false
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ([string]::IsNullOrWhiteSpace($Version)) {
  $Version = "3.0.2"
}
$versionParts = $Version.Split(".")
while ($versionParts.Count -lt 4) { $versionParts += "0" }
$fileVersion = ($versionParts[0..3] -join ".")

& $Python scripts\sync_app_icon.py
if ($LASTEXITCODE -ne 0) { throw "sync_app_icon.py failed with exit code $LASTEXITCODE" }
if (-not $SkipPrepareRelease -and -not $UninstallerOnly -and $X64Source -and $Arm64Source) {
    $prepareArgs = @(
        "scripts\prepare_nuitka_release.py",
        "--payload-dir",
        $PayloadDir,
        "--release-dir",
        $ReleaseDir,
        "--version",
        $Version,
        "--skip-installer-payload-zips"
    )
    if ($X64Source) {
        $prepareArgs += @("--x64-source", $X64Source)
    }
    if ($Arm64Source) {
        $prepareArgs += @("--arm64-source", $Arm64Source)
    }
    & $Python @prepareArgs
    if ($LASTEXITCODE -ne 0) { throw "prepare_nuitka_release.py failed with exit code $LASTEXITCODE" }
}

$compilerArg = switch ($Compiler) {
    "zig" { "--zig" }
    "mingw" { "--mingw64" }
    default { "--msvc=latest" }
}

# Installer packaging: build exactly one custom graphical installer.
# - Use Nuitka onefile with a stable cached unpack path (no per-PID temp layout).
# - QtWebEngine + --onefile-no-compression balloons to ~450-530MB with NO app payload.
# Uninstaller (no WebEngine) may still use --onefile-no-compression below.
$modeArgs = @()
if ($Standalone) {
  $modeArgs += "--standalone"
} else {
  # Stable CACHE_DIR unpack (no {PID}) + cached mode → less "dropper extracts to %TEMP%" heuristic.
  Write-Host "Building a single Nuitka onefile installer (cached unpack)."
  $modeArgs += @(
    "--onefile",
    "--onefile-as-archive",
    "--onefile-cache-mode=cached",
    "--onefile-tempdir-spec={CACHE_DIR}/goshkow/zapret-hub-installer/{VERSION}"
  )
}

$bundledUninstallerDir = Join-Path $root "bundled_uninstaller"
New-Item -ItemType Directory -Force -Path $bundledUninstallerDir | Out-Null
$uninstallerPath = Join-Path $OutputDir "uninstall_zaprethub.exe"

function Build-Uninstaller {
  param([string]$OutDir)
  $uninstallModeArgs = @()
  if ($Standalone) {
    $uninstallModeArgs += "--standalone"
  } else {
    $uninstallModeArgs += @(
      "--onefile",
      "--onefile-as-archive",
      "--onefile-no-compression",
      "--onefile-cache-mode=cached",
      "--onefile-tempdir-spec={CACHE_DIR}/goshkow/zapret-hub-uninstaller/{VERSION}"
    )
  }
  $uninstallNuitkaArgs = @(
    "-m",
    "nuitka"
  ) + $uninstallModeArgs + @(
    "--assume-yes-for-downloads",
    "--no-deployment-flag=self-execution",
    $compilerArg,
    "--enable-plugin=pyside6",
    "--windows-console-mode=disable",
    "--windows-uac-admin",
    "--deployment",
    "--windows-icon-from-ico=ui_assets\icons\app_shell.ico",
    "--company-name=goshkow",
    "--product-name=Zapret Hub Uninstaller",
    "--file-version=$fileVersion",
    "--product-version=$fileVersion",
    "--file-description=Zapret Hub Uninstaller",
    "--copyright=goshkow",
    "--output-dir=$OutDir",
    "--output-filename=uninstall_zaprethub.exe",
    # The uninstaller only resolves these icon files at runtime. Shipping the
    # full UI asset tree here needlessly added unrelated application artwork.
    "--include-data-files=ui_assets\icons\installer_runtime_icon.png=ui_assets\icons\installer_runtime_icon.png",
    "--include-data-files=ui_assets\icons\app.png=ui_assets\icons\app.png",
    "--include-data-files=ui_assets\icons\app.ico=ui_assets\icons\app.ico",
    "--include-package=installer",
    "--nofollow-import-to=tkinter",
    "--nofollow-import-to=PySide6.QtWebEngineCore",
    "--nofollow-import-to=PySide6.QtWebEngineWidgets",
    "--nofollow-import-to=PySide6.QtWebChannel",
    "--remove-output",
    "installer\uninstall_zaprethub.py"
  )
  Write-Host "Building standalone uninstaller..."
  & $Python @uninstallNuitkaArgs
  if ($LASTEXITCODE -ne 0) { throw "Nuitka uninstaller build failed with exit code $LASTEXITCODE" }

  $builtUninstaller = Get-ChildItem $OutDir -Recurse -File -Filter "uninstall_zaprethub.exe" |
      Select-Object -First 1
  if (-not $builtUninstaller) {
      throw "Built uninstaller not found in $OutDir"
  }
  return $builtUninstaller.FullName
}

if ($UninstallerOnly) {
  $built = Build-Uninstaller -OutDir $OutputDir
  $bundledTarget = Join-Path $bundledUninstallerDir "uninstall_zaprethub.exe"
  Copy-Item -LiteralPath $built -Destination $bundledTarget -Force
  $sidecar = Join-Path $OutputDir "uninstall_zaprethub.exe"
  if ((Resolve-Path $built).Path -ne (Resolve-Path $sidecar -ErrorAction SilentlyContinue).Path) {
    Copy-Item -LiteralPath $built -Destination $sidecar -Force
  }
  Write-Host "UninstallerOnly: $built"
  exit 0
}

$embedBundledUninstaller = $false
if ($EmbedUninstaller -and -not $SkipUninstaller) {
  $uninstallerPath = Build-Uninstaller -OutDir $OutputDir
  $bundledTarget = Join-Path $bundledUninstallerDir "uninstall_zaprethub.exe"
  Copy-Item -LiteralPath $uninstallerPath -Destination $bundledTarget -Force
  if (-not (Test-Path $bundledTarget) -or ((Get-Item $bundledTarget).Length -lt 1MB)) {
    throw "Failed to stage bundled_uninstaller\uninstall_zaprethub.exe"
  }
  $embedBundledUninstaller = $true
  Write-Host "Uninstaller: $uninstallerPath ($([math]::Round((Get-Item $bundledTarget).Length/1MB,1)) MB)"
} else {
  $bundledTarget = Join-Path $bundledUninstallerDir "uninstall_zaprethub.exe"
  if ($UninstallerX64Source -and (Test-Path -LiteralPath $UninstallerX64Source)) {
    Copy-Item -LiteralPath $UninstallerX64Source -Destination $bundledTarget -Force
    Copy-Item -LiteralPath $UninstallerX64Source -Destination (Join-Path $bundledUninstallerDir "uninstall_zaprethub_x64.exe") -Force
  }
  if ($UninstallerArm64Source -and (Test-Path -LiteralPath $UninstallerArm64Source)) {
    Copy-Item -LiteralPath $UninstallerArm64Source -Destination (Join-Path $bundledUninstallerDir "uninstall_zaprethub_arm64.exe") -Force
  }
  Write-Host "Slim installer: uninstaller EXE is not embedded (reduces PE-in-PE AV false positives). Portable payload provides uninstall_zaprethub.exe."
}

$installerDataFiles = @()
if ($embedBundledUninstaller -and (Test-Path (Join-Path $bundledUninstallerDir "uninstall_zaprethub.exe"))) {
  $installerDataFiles += "--include-data-files=bundled_uninstaller/uninstall_zaprethub.exe=bundled_uninstaller/uninstall_zaprethub.exe"
}
if ($embedBundledUninstaller -and (Test-Path (Join-Path $bundledUninstallerDir "uninstall_zaprethub_x64.exe"))) {
  $installerDataFiles += "--include-data-files=bundled_uninstaller/uninstall_zaprethub_x64.exe=bundled_uninstaller/uninstall_zaprethub_x64.exe"
}
if ($embedBundledUninstaller -and (Test-Path (Join-Path $bundledUninstallerDir "uninstall_zaprethub_arm64.exe"))) {
  $installerDataFiles += "--include-data-files=bundled_uninstaller/uninstall_zaprethub_arm64.exe=bundled_uninstaller/uninstall_zaprethub_arm64.exe"
}

# Slim path must never ship leftover portable payload zips from a prior fat build.
$payloadZipHits = @()
if (Test-Path -LiteralPath $PayloadDir) {
  $payloadZipHits = @(Get-ChildItem -LiteralPath $PayloadDir -Filter "*.zip" -File -ErrorAction SilentlyContinue)
}
if ($payloadZipHits.Count -gt 0) {
  throw "Refusing slim installer build: '$PayloadDir' still contains payload zip(s): $($payloadZipHits.Name -join ', '). Remove them (runtime download is from the mirror)."
}

$installerName = "install_zaprethub_${Version}_universal.exe"
$nuitkaArgs = @(
  "-m",
  "nuitka"
) + $modeArgs + @(
  "--assume-yes-for-downloads",
  "--no-deployment-flag=self-execution",
  $compilerArg,
  "--enable-plugin=pyside6",
  "--windows-console-mode=disable",
  "--windows-uac-admin",
  "--deployment",
  "--windows-icon-from-ico=ui_assets\icons\app_shell.ico",
  "--company-name=goshkow",
  "--product-name=Zapret Hub Installer",
  "--file-version=$fileVersion",
  "--product-version=$fileVersion",
  "--file-description=Zapret Hub Installer",
  "--copyright=goshkow",
  "--output-dir=$OutputDir",
  "--output-filename=$installerName",
  "--include-data-dir=ui_assets=ui_assets",
  "--include-data-dir=installer_web=installer_web",
  "--include-data-files=docs\legal\ZAPRET_HUB_TERMS_RU.txt=docs\legal\ZAPRET_HUB_TERMS_RU.txt"
) + $installerDataFiles + @(
  "--include-package=installer",
  "--nofollow-import-to=tkinter",
  "--nofollow-import-to=zapret_hub",
  "--nofollow-import-to=nuitka",
  "--remove-output",
  "installer\install_zaprethub.py"
)
if ($embedBundledUninstaller) {
  Write-Host "Building installer with bundled standalone uninstaller..."
} elseif ($Standalone) {
  Write-Host "Building standalone installer folder (QtWebEngine UI; no portable zips; no embedded uninstaller EXE)..."
} else {
  Write-Host "Building compressed slim onefile installer (QtWebEngine UI; no portable zips; no embedded uninstaller EXE)..."
}
& $Python @nuitkaArgs
if ($LASTEXITCODE -ne 0) { throw "Nuitka installer build failed with exit code $LASTEXITCODE" }

$builtInstaller = Get-ChildItem $OutputDir -Recurse -File -Filter $installerName |
    Select-Object -First 1

if (-not $builtInstaller) {
    throw "Built installer not found in $OutputDir"
}

$installerMb = [math]::Round($builtInstaller.Length / 1MB, 1)
Write-Host "Built slim installer size: $installerMb MB"
# Compressed WebEngine installer is ~100-180MB. Uncompressed (~450-530MB) or
# embedded portable payloads (~500MB+) must fail the build.
if ($builtInstaller.Length -gt (220MB)) {
  throw "Slim installer too large ($installerMb MB > 220 MB). Expected ~100-180 MB without portable payload."
}
if ($builtInstaller.Length -lt (5MB)) {
  throw "Slim installer suspiciously small ($installerMb MB < 5 MB)."
}

# Keep a sidecar only when this build intentionally embedded an uninstaller.
$bundledExe = Join-Path $bundledUninstallerDir "uninstall_zaprethub.exe"
$sidecarUninstaller = Join-Path $builtInstaller.DirectoryName "uninstall_zaprethub.exe"
if ($embedBundledUninstaller -and (Test-Path $bundledExe)) {
  Copy-Item -LiteralPath $bundledExe -Destination $sidecarUninstaller -Force
  $uninstallerPath = $sidecarUninstaller
} else {
  $uninstallerPath = ""
}

Write-Host "Installer: $($builtInstaller.FullName)"
Write-Host "Uninstaller: $uninstallerPath"

$prepareUninstallerArgs = @()
if ($UninstallerX64Source -and (Test-Path -LiteralPath $UninstallerX64Source)) {
  $prepareUninstallerArgs += @("--uninstaller-x64", $UninstallerX64Source)
} elseif (Test-Path (Join-Path $bundledUninstallerDir "uninstall_zaprethub_x64.exe")) {
  $prepareUninstallerArgs += @("--uninstaller-x64", (Join-Path $bundledUninstallerDir "uninstall_zaprethub_x64.exe"))
} elseif ($sidecarUninstaller -and (Test-Path $sidecarUninstaller)) {
  $prepareUninstallerArgs += @("--uninstaller-source", $sidecarUninstaller)
}
if ($UninstallerArm64Source -and (Test-Path -LiteralPath $UninstallerArm64Source)) {
  $prepareUninstallerArgs += @("--uninstaller-arm64", $UninstallerArm64Source)
} elseif (Test-Path (Join-Path $bundledUninstallerDir "uninstall_zaprethub_arm64.exe")) {
  $prepareUninstallerArgs += @("--uninstaller-arm64", (Join-Path $bundledUninstallerDir "uninstall_zaprethub_arm64.exe"))
}

if ($X64Source -and $Arm64Source -and (Test-Path $X64Source) -and (Test-Path $Arm64Source)) {
    & $Python scripts\prepare_nuitka_release.py `
        --payload-dir $PayloadDir `
        --release-dir $ReleaseDir `
        --x64-source $X64Source `
        --arm64-source $Arm64Source `
        --version $Version `
        --skip-installer-payload-zips `
        @prepareUninstallerArgs
    if ($LASTEXITCODE -ne 0) { throw "portable release refresh with uninstaller failed with exit code $LASTEXITCODE" }
} elseif (-not $SkipPrepareRelease) {
    Write-Host "Skipping portable release packaging (pass -X64Source and -Arm64Source to include uninstall_zaprethub.exe in portable builds)."
}
