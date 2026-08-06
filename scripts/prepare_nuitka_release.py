from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

VERSION = "3.0.2"


def _load_prune():
    import importlib.util

    script = Path(__file__).resolve().parent / "prune_windows_runtime.py"
    spec = importlib.util.spec_from_file_location("prune_windows_runtime", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load prune helper: {script}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.prune_windows_runtime


def _should_skip_path(path: Path, source_dir: Path) -> bool:
    try:
        rel = path.relative_to(source_dir)
    except Exception:
        return False
    parts = rel.parts
    if any(part.startswith("tg-ws-proxy.bak.") for part in parts):
        return True
    lowered = tuple(part.lower() for part in parts)
    if "docs" in lowered and rel.name.lower() == "readme.md":
        return True
    return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _zip_with_root(source_dir: Path, zip_path: Path, root_name: str = "zapret_hub") -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(source_dir.rglob("*")):
            if item.is_dir():
                continue
            if not item.exists():
                continue
            if _should_skip_path(item, source_dir):
                continue
            rel = item.relative_to(source_dir)
            try:
                archive.write(item, Path(root_name) / rel)
            except (PermissionError, FileNotFoundError):
                continue


def _copy_uninstaller(source: Path | None, destination_dir: Path) -> None:
    if source is None or not source.exists():
        return
    destination_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination_dir / "uninstall_zaprethub.exe")


def _write_identity_files(portable_dir: Path, *, version: str, digest: str) -> dict[str, str]:
    """Embed archive SHA256 so the extracted app knows its own build identity."""
    payload = {
        "version": str(version),
        "digest": str(digest).strip().lower().removeprefix("sha256:"),
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    for path in (
        portable_dir / "build_info.json",
        portable_dir / "data" / "app_release_identity.json",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def _clear_identity_files(portable_dir: Path) -> None:
    for path in (
        portable_dir / "build_info.json",
        portable_dir / "data" / "app_release_identity.json",
    ):
        if path.exists():
            path.unlink()


def _package_portable(
    *,
    source: Path,
    release_dir: Path,
    version: str,
    arch: str,
    uninstaller: Path | None,
) -> dict[str, object]:
    """Build portable zip and record its SHA256 for the mirror + local identity stamp.

    The published digest is SHA256 of the portable zip bytes (same field the app
    downloads and verifies). A zip cannot contain its own matching SHA256, so the
    release zip stays free of identity files; ``build_info.json`` /
    ``app_release_identity.json`` are written next to the zip and into the unpacked
    portable folder for tooling. Installer and in-app updater embed the verified
    archive digest into the live install so hotfix checks can compare local vs remote.
    """
    portable_dir = release_dir / f"zapret_hub_{version}_portable_win_{arch}"
    zip_name = f"zapret_hub_{version}_portable_win_{arch}.zip"
    zip_path = release_dir / zip_name
    if portable_dir.exists():
        shutil.rmtree(portable_dir, ignore_errors=True)
    shutil.copytree(source, portable_dir, dirs_exist_ok=True)
    _copy_uninstaller(uninstaller, portable_dir)
    runtime_dir = portable_dir / "runtime"
    if runtime_dir.is_dir():
        prune = _load_prune()
        stats = prune(runtime_dir)
        print(
            f"pruned runtime for {arch}: dirs={stats['removed_dirs']} "
            f"files={stats['removed_files']} elf={stats['removed_elf']}"
        )
    for backup_dir in portable_dir.rglob("tg-ws-proxy.bak.*"):
        if backup_dir.is_dir():
            shutil.rmtree(backup_dir, ignore_errors=True)

    _clear_identity_files(portable_dir)
    _zip_with_root(portable_dir, zip_path)
    published_digest = _sha256_file(zip_path)

    identity = _write_identity_files(portable_dir, version=version, digest=published_digest)
    # Sidecar copy for mirror sync (do not re-zip — that would change the digest).
    (release_dir / f"{zip_name}.build_info.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (release_dir / f"{zip_name}.sha256").write_text(f"{published_digest}  {zip_name}\n", encoding="utf-8")
    meta = {
        "architecture": arch,
        "name": zip_name,
        "digest": f"sha256:{published_digest}",
        "size": zip_path.stat().st_size,
        "version": version,
        "note": (
            "Mirror assets.*.digest MUST equal this sha256. "
            "Installer/in-app updater write the same digest into the install as build identity."
        ),
    }
    (release_dir / f"zapret_hub_{version}_portable_win_{arch}.asset.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"portable {arch}: {zip_name} sha256={published_digest}")
    return meta


def _parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Prepare GitHub/mirror release assets for the slim installer model. "
            "Portable zips are published for goshkow.com; the installer downloads them later "
            "and does not embed these archives."
        )
    )
    parser.add_argument(
        "--x64-source",
        default="",
        help="Nuitka main.dist for win-x64 (optional if only packaging arm64).",
    )
    parser.add_argument(
        "--arm64-source",
        default="",
        help="Nuitka main.dist for win-arm64 (optional if only packaging x64).",
    )
    parser.add_argument("--payload-dir", default=str(root / "installer_payload"))
    parser.add_argument("--release-dir", default=str(root / f"release_{VERSION}"))
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--uninstaller-source", default="")
    parser.add_argument("--uninstaller-x64", default="")
    parser.add_argument("--uninstaller-arm64", default="")
    parser.add_argument(
        "--write-installer-payload-zips",
        action="store_true",
        help=(
            "Dev/local only: also write installer_payload/*.zip. "
            "Slim installer does NOT embed these; default is to skip."
        ),
    )
    parser.add_argument(
        "--skip-installer-payload-zips",
        action="store_true",
        default=True,
        help=argparse.SUPPRESS,  # kept for older callers; slim is the default
    )
    parser.add_argument(
        "--no-skip-installer-payload-zips",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    version = str(args.version)
    x64_source = Path(args.x64_source).resolve() if args.x64_source else None
    arm64_source = Path(args.arm64_source).resolve() if args.arm64_source else None
    payload_dir = Path(args.payload_dir).resolve()
    release_dir = Path(args.release_dir).resolve()
    shared_uninstaller = Path(args.uninstaller_source).resolve() if args.uninstaller_source else None
    uninstaller_x64 = Path(args.uninstaller_x64).resolve() if args.uninstaller_x64 else shared_uninstaller
    uninstaller_arm64 = Path(args.uninstaller_arm64).resolve() if args.uninstaller_arm64 else shared_uninstaller

    if x64_source is None and arm64_source is None:
        raise SystemExit("Provide at least one of --x64-source or --arm64-source")
    if x64_source is not None and not x64_source.exists():
        raise FileNotFoundError(f"x64 Nuitka source not found: {x64_source}")
    if arm64_source is not None and not arm64_source.exists():
        raise FileNotFoundError(f"arm64 source not found: {arm64_source}")

    write_payload = bool(args.write_installer_payload_zips) or bool(getattr(args, "no_skip_installer_payload_zips", False))
    if write_payload:
        if x64_source is None or arm64_source is None:
            raise SystemExit("--write-installer-payload-zips requires both --x64-source and --arm64-source")
        payload_dir.mkdir(parents=True, exist_ok=True)
        _zip_with_root(x64_source, payload_dir / "win_x64.zip")
        _zip_with_root(arm64_source, payload_dir / "win_arm64.zip")
    else:
        print("Skipping installer_payload zips (slim download-from-mirror installer).")

    release_dir.mkdir(parents=True, exist_ok=True)

    assets: dict[str, object] = {}
    if x64_source is not None:
        assets["x64"] = _package_portable(
            source=x64_source,
            release_dir=release_dir,
            version=version,
            arch="x64",
            uninstaller=uninstaller_x64,
        )
    if arm64_source is not None:
        assets["arm64"] = _package_portable(
            source=arm64_source,
            release_dir=release_dir,
            version=version,
            arch="arm64",
            uninstaller=uninstaller_arm64,
        )

    mirror_snippet = {
        "product": "Zapret Hub",
        "version": version,
        "tag": f"v{version}",
        "assets": {
            key: {
                "name": value["name"],
                "download_url": f"https://goshkow.com/zapret-hub/{key}",
                "digest": value["digest"],
                "size": value["size"],
            }
            for key, value in assets.items()
            if isinstance(value, dict)
        },
    }
    (release_dir / "mirror-update-assets.example.json").write_text(
        json.dumps(mirror_snippet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    note = release_dir / "README_RELEASE.txt"
    note.write_text(
        "Slim installer release model\n"
        "============================\n"
        "1) Publish portable_win_x64.zip and portable_win_arm64.zip to the goshkow.com mirror\n"
        "   (and/or keep them as GitHub release assets).\n"
        "2) install_zaprethub_*_universal.exe is a slim installer: at runtime it downloads the\n"
        "   matching arch build from https://goshkow.com/zapret-hub/update — it does NOT embed\n"
        "   the portable archives.\n"
        "3) Each portable folder includes arch-matching uninstall_zaprethub.exe.\n"
        "4) Standalone uninstallers may also be published as separate release assets.\n"
        "\n"
        "Mirror update JSON (https://goshkow.com/zapret-hub/update)\n"
        "----------------------------------------------------------\n"
        "Required fields for same-version hotfix detection:\n"
        "  - version / tag  (product version, e.g. 3.0.1 — may stay unchanged for hotfixes)\n"
        "  - assets.x64.digest     = sha256:<portable x64 zip bytes on the mirror>\n"
        "  - assets.arm64.digest   = sha256:<portable arm64 zip bytes on the mirror>\n"
        "  - assets.x64.download_url / assets.arm64.download_url\n"
        "  - assets.x64.size / assets.arm64.size (optional but verified when present)\n"
        "Optional: assets.installer.digest for the slim setup exe.\n"
        "\n"
        "After each hotfix re-upload of the same version, UPDATE the digest values to the new\n"
        "zip SHA256 (see *.sha256 and mirror-update-assets.example.json in this folder).\n"
        "The app treats: newer semver OR (same version AND remote digest != local digest)\n"
        "as an update. Matching digests => no prompt. Do not rely on binary_updated_at.\n",
        encoding="utf-8",
    )

    print(f"Prepared release folder in: {release_dir}")
    if write_payload:
        print(f"Prepared optional local payloads in: {payload_dir}")
    if x64_source is not None:
        if uninstaller_x64 and uninstaller_x64.exists():
            print(f"Portable x64 includes uninstaller: {uninstaller_x64}")
        else:
            print("WARNING: portable x64 has no uninstall_zaprethub.exe")
    if arm64_source is not None:
        if uninstaller_arm64 and uninstaller_arm64.exists():
            print(f"Portable arm64 includes uninstaller: {uninstaller_arm64}")
        else:
            print("WARNING: portable arm64 has no uninstall_zaprethub.exe")


if __name__ == "__main__":
    main()
