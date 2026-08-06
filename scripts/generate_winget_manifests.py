from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


PACKAGE_IDENTIFIER = "Goshkow.ZapretHub"
MANIFEST_VERSION = "1.12.0"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write(path: Path, content: str) -> None:
    path.write_text(content.rstrip() + "\n", encoding="utf-8", newline="\n")


def generate_manifests(
    *,
    version: str,
    x64_archive: Path,
    arm64_archive: Path | None = None,
    output_dir: Path,
    release_base_url: str,
) -> list[Path]:
    for archive in (x64_archive, arm64_archive):
        if archive is None:
            continue
        if not archive.is_file():
            raise FileNotFoundError(f"Portable archive not found: {archive}")

    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = release_base_url.rstrip("/")
    common = f"PackageIdentifier: {PACKAGE_IDENTIFIER}\nPackageVersion: {version}\n"

    installers = f"""- Architecture: x64
  InstallerUrl: {base_url}/{x64_archive.name}
  InstallerSha256: {_sha256(x64_archive)}
"""
    if arm64_archive is not None:
        installers += f"""- Architecture: arm64
  InstallerUrl: {base_url}/{arm64_archive.name}
  InstallerSha256: {_sha256(arm64_archive)}
"""

    files = {
        f"{PACKAGE_IDENTIFIER}.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.version.{MANIFEST_VERSION}.schema.json
{common}DefaultLocale: en-US
ManifestType: version
ManifestVersion: {MANIFEST_VERSION}
""",
        f"{PACKAGE_IDENTIFIER}.installer.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.installer.{MANIFEST_VERSION}.schema.json
{common}InstallerType: zip
NestedInstallerType: portable
NestedInstallerFiles:
- RelativeFilePath: zapret_hub\\Zapret_Hub.exe
  PortableCommandAlias: zapret-hub
ArchiveBinariesDependOnPath: true
UpgradeBehavior: install
Installers:
{installers.rstrip()}
ManifestType: installer
ManifestVersion: {MANIFEST_VERSION}
""",
        f"{PACKAGE_IDENTIFIER}.locale.en-US.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.defaultLocale.{MANIFEST_VERSION}.schema.json
{common}PackageLocale: en-US
Publisher: goshkow
PublisherUrl: https://goshkow.com/
PublisherSupportUrl: https://github.com/goshkow/Zapret-Hub/issues
PackageName: Zapret Hub
PackageUrl: https://github.com/goshkow/Zapret-Hub
License: MIT
LicenseUrl: https://github.com/goshkow/Zapret-Hub/blob/main/LICENSE
ShortDescription: Windows application for managing censorship-circumvention components.
Moniker: zapret-hub
Tags:
- dpi
- vpn
- windows
ManifestType: defaultLocale
ManifestVersion: {MANIFEST_VERSION}
""",
        f"{PACKAGE_IDENTIFIER}.locale.ru-RU.yaml": f"""# yaml-language-server: $schema=https://aka.ms/winget-manifest.locale.{MANIFEST_VERSION}.schema.json
{common}PackageLocale: ru-RU
Publisher: goshkow
PackageName: Zapret Hub
ShortDescription: Приложение для управления компонентами обхода блокировок в Windows.
ManifestType: locale
ManifestVersion: {MANIFEST_VERSION}
""",
    }

    written: list[Path] = []
    for name, content in files.items():
        path = output_dir / name
        _write(path, content)
        written.append(path)
    return written


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate WinGet manifests for portable release archives.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--x64-archive", required=True, type=Path)
    parser.add_argument("--arm64-archive", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--release-base-url", required=True)
    parser.add_argument("--bundle", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifests = generate_manifests(
        version=args.version,
        x64_archive=args.x64_archive,
        arm64_archive=args.arm64_archive,
        output_dir=args.output_dir,
        release_base_url=args.release_base_url,
    )
    if args.bundle:
        args.bundle.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for manifest in manifests:
                archive.write(manifest, manifest.name)
    for manifest in manifests:
        print(manifest)


if __name__ == "__main__":
    main()
