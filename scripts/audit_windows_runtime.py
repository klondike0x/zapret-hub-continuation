"""Fail a Windows packaging build when known non-runtime artifacts remain."""
from __future__ import annotations

import argparse
from pathlib import Path


_FORBIDDEN_DIR_NAMES = {".git", ".github", "__pycache__", ".pytest_cache", ".mypy_cache"}
_FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".o", ".obj", ".a"}
_FOREIGN_BINARY_PREFIXES = ("linux-", "android-", "freebsd-")


def find_unwanted_artifacts(root: Path) -> list[Path]:
    root = Path(root)
    findings: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part.lower() in _FORBIDDEN_DIR_NAMES for part in relative.parts):
            findings.append(relative)
            continue
        if path.is_file() and path.suffix.lower() in _FORBIDDEN_SUFFIXES:
            findings.append(relative)
            continue
        if path.is_dir() and len(relative.parts) >= 3:
            parent = relative.parts[-2].lower()
            if parent == "binaries" and path.name.lower().startswith(_FOREIGN_BINARY_PREFIXES):
                findings.append(relative)
    return sorted(set(findings), key=lambda item: str(item).lower())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime_root", type=Path)
    args = parser.parse_args()
    findings = find_unwanted_artifacts(args.runtime_root)
    if not findings:
        print(f"runtime audit passed: {args.runtime_root}")
        return 0
    print("runtime audit failed; remove these non-runtime artifacts:")
    for item in findings:
        print(f"  - {item}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
