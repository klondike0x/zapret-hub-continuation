"""Remove QtWebEngine debug data and unused locales from a packaged Windows app.

Zapret Hub has its own RU/EN interface and never installs Qt's broad translation
catalogue.  Keeping the full catalogue and Chromium debug resources inflated
the x64 portable archive without changing runtime behaviour.
"""
from __future__ import annotations

import argparse
from pathlib import Path


_DEBUG_RESOURCE_GLOBS = ("qtwebengine*_resources*.debug.pak",)
_UNUSED_QM_PREFIXES = (
    "assistant_",
    "designer_",
    "linguist_",
    "qt_help_",
    "qtconnectivity_",
    "qtlocation_",
    "qtmultimedia_",
    "qtserialport_",
    "qtwebsockets_",
)
_KEEP_WEBENGINE_LOCALES = {"ru.pak", "en-US.pak", "en-GB.pak"}


def _remove(path: Path, *, dry_run: bool) -> int:
    if not path.is_file():
        return 0
    size = path.stat().st_size
    if not dry_run:
        path.unlink(missing_ok=True)
    return size


def prune_qt_runtime(dist_root: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Prune optional debug and locale payload from a Nuitka ``*.dist`` folder."""
    dist_root = Path(dist_root)
    removed_files = 0
    removed_bytes = 0

    for pattern in _DEBUG_RESOURCE_GLOBS:
        for path in dist_root.glob(pattern):
            removed_bytes += _remove(path, dry_run=dry_run)
            removed_files += 1

    translations = dist_root / "PySide6" / "translations"
    if translations.is_dir():
        for path in translations.glob("*.qm"):
            if path.name.startswith(_UNUSED_QM_PREFIXES):
                removed_bytes += _remove(path, dry_run=dry_run)
                removed_files += 1
        locales = translations / "qtwebengine_locales"
        if locales.is_dir():
            for path in locales.glob("*.pak"):
                if path.name not in _KEEP_WEBENGINE_LOCALES:
                    removed_bytes += _remove(path, dry_run=dry_run)
                    removed_files += 1

    return {"removed_files": removed_files, "removed_bytes": removed_bytes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_root", type=Path, help="Path to Nuitka *.dist folder")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stats = prune_qt_runtime(args.dist_root, dry_run=bool(args.dry_run))
    print(
        f"{'dry-run' if args.dry_run else 'pruned'} Qt runtime: "
        f"files={stats['removed_files']} bytes={stats['removed_bytes']} root={args.dist_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
