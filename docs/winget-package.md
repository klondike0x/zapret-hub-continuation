# WinGet package

The release workflow generates a multi-file WinGet manifest from the final x64 and ARM64 portable archives. WinGet selects the compatible archive, verifies its SHA-256 hash, extracts the complete application directory, and registers the portable package without launching the graphical installer.

For a local manifest test, extract `winget-manifests-<version>.zip`, enable local manifests in WinGet settings, and run:

```powershell
winget install --manifest . --accept-package-agreements --accept-source-agreements
```

Public installation with `winget install --id Goshkow.ZapretHub` becomes available after the generated manifest directory is accepted into [microsoft/winget-pkgs](https://github.com/microsoft/winget-pkgs).
