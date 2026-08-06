[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = "Stop"
$workspace = [IO.Path]::GetFullPath($Root).TrimEnd('\')
$workspacePrefix = "$workspace\"
$directoryNames = @("bundled_uninstaller", "_tmp_mod_inspect", ".ruff_cache", ".pytest_cache")
$fileNames = @("_tmp_openapi.json", ".build_outdir.txt", "nuitka-crash-report.xml")

$targets = @(
    Get-ChildItem -LiteralPath $workspace -Directory -Force |
        Where-Object {
            $_.Name -in $directoryNames -or
            $_.Name -like "dist_*" -or $_.Name -like "release_*" -or $_.Name -like "backup_before_*"
        }
) + @(
    Get-ChildItem -LiteralPath $workspace -File -Force |
        Where-Object { $_.Name -in $fileNames }
)

$removed = 0
foreach ($target in $targets) {
    $path = [IO.Path]::GetFullPath($target.FullName)
    if (-not $path.StartsWith($workspacePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the workspace: $path"
    }
    if ($PSCmdlet.ShouldProcess($path, "Remove obsolete Zapret Hub build artifact")) {
        Remove-Item -LiteralPath $path -Recurse -Force
        $removed++
    }
}

Write-Host "Removed obsolete Zapret Hub build artifacts: $removed"
