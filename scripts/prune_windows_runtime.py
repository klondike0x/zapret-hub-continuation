"""Prune non-Windows / non-runtime junk from a staged Hub runtime tree.

Windows portable and installer payloads must not ship Linux/Android/FreeBSD ELF
binaries — VirusTotal tags those as LINUX.Agent / ELF:Agent-DIY. WinDivert and
windows-x86_64 stay (expected RiskTool detections).
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

# Platform folders under runtime/zapret2/binaries that are useless on Windows Hub.
_FOREIGN_BINARY_DIR_PREFIXES = (
    "linux-",
    "android-",
    "freebsd-",
)

# Always drop 32-bit Windows zapret2 binaries from Hub packages (x64/ARM64 only).
_DROP_WINDOWS_X86 = True

# Source / build trees never needed at Windows runtime.
_DROP_RELATIVE_DIRS = (
    Path("zapret2") / "nfq2",
    Path("zapret2") / "docs" / "compile",
    Path("zapret2") / "ip2net",
    Path("zapret2") / "mdig",
)


def _is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"\x7fELF"
    except OSError:
        return False


def _should_drop_binary_dir(name: str) -> bool:
    lowered = name.lower()
    if any(lowered.startswith(prefix) for prefix in _FOREIGN_BINARY_DIR_PREFIXES):
        return True
    if _DROP_WINDOWS_X86 and lowered in {"windows-x86", "win32", "windows-x86_32"}:
        return True
    return False


def prune_windows_runtime(runtime_root: Path, *, dry_run: bool = False) -> dict[str, int]:
    """Remove foreign binaries and build junk from ``runtime_root``.

    ``runtime_root`` is the directory that contains ``zapret2``, etc.
    Returns counters for logging/tests.
    """
    runtime_root = Path(runtime_root)
    removed_dirs = 0
    removed_files = 0
    removed_elf = 0

    if not runtime_root.is_dir():
        return {"removed_dirs": 0, "removed_files": 0, "removed_elf": 0}

    binaries_root = runtime_root / "zapret2" / "binaries"
    if binaries_root.is_dir():
        for child in list(binaries_root.iterdir()):
            if not child.is_dir():
                continue
            if not _should_drop_binary_dir(child.name):
                continue
            removed_dirs += 1
            if not dry_run:
                shutil.rmtree(child, ignore_errors=True)

    for relative in _DROP_RELATIVE_DIRS:
        target = runtime_root / relative
        if target.is_dir():
            removed_dirs += 1
            if not dry_run:
                shutil.rmtree(target, ignore_errors=True)

    # Safety net: any leftover ELF under runtime/ (should be none after dir prune).
    for path in list(runtime_root.rglob("*")):
        if not path.is_file():
            continue
        if not _is_elf(path):
            continue
        removed_elf += 1
        removed_files += 1
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                pass

    # Drop common compile leftovers if present.
    for pattern in ("*.o", "*.a", "*.obj", "*.lib"):
        for path in list(runtime_root.rglob(pattern)):
            if not path.is_file():
                continue
            removed_files += 1
            if not dry_run:
                try:
                    path.unlink()
                except OSError:
                    pass

    return {
        "removed_dirs": removed_dirs,
        "removed_files": removed_files,
        "removed_elf": removed_elf,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_root", type=Path, help="Path to staged runtime/ directory")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stats = prune_windows_runtime(args.runtime_root, dry_run=bool(args.dry_run))
    mode = "dry-run" if args.dry_run else "pruned"
    print(
        f"{mode}: dirs={stats['removed_dirs']} files={stats['removed_files']} "
        f"elf={stats['removed_elf']} root={args.runtime_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
