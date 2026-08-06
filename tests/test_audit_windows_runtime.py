from __future__ import annotations

import importlib.util
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("audit_windows_runtime", _ROOT / "scripts" / "audit_windows_runtime.py")
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_audit_flags_foreign_and_compiler_artifacts(tmp_path: Path) -> None:
    keep = tmp_path / "zapret2" / "binaries" / "windows-x86_64" / "winws2.exe"
    foreign = tmp_path / "zapret2" / "binaries" / "linux-x86_64" / "winws2"
    cache = tmp_path / "pkg" / "__pycache__" / "module.pyc"
    keep.parent.mkdir(parents=True)
    foreign.parent.mkdir(parents=True)
    cache.parent.mkdir(parents=True)
    keep.write_bytes(b"MZ")
    foreign.write_bytes(b"\x7fELF")
    cache.write_bytes(b"x")

    findings = {str(item).replace("\\", "/") for item in _MODULE.find_unwanted_artifacts(tmp_path)}

    assert "zapret2/binaries/linux-x86_64" in findings
    assert "pkg/__pycache__" in findings
    assert not any("windows-x86_64" in item for item in findings)
