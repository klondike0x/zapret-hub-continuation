from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "prune_windows_runtime",
    _ROOT / "scripts" / "prune_windows_runtime.py",
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
prune_windows_runtime = _MOD.prune_windows_runtime


def _write(path: Path, data: bytes = b"x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_prune_removes_foreign_binaries_keeps_windows_x64(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    keep = runtime / "zapret2" / "binaries" / "windows-x86_64" / "winws2.exe"
    drop_linux = runtime / "zapret2" / "binaries" / "linux-x86_64" / "nfqws2"
    drop_android = runtime / "zapret2" / "binaries" / "android-arm64" / "mdig"
    drop_x86 = runtime / "zapret2" / "binaries" / "windows-x86" / "winws2.exe"
    sources = runtime / "zapret2" / "nfq2" / "desync.c"
    workflow = runtime / "tg-ws-proxy" / ".github" / "workflows" / "build.yml"
    _write(keep, b"MZ")
    _write(drop_linux, b"\x7fELF\x02")
    _write(drop_android, b"\x7fELF\x01")
    _write(drop_x86, b"MZ")
    _write(sources, b"int main(){}")
    _write(workflow, b"name: build")

    stats = prune_windows_runtime(runtime)
    assert keep.is_file()
    assert not drop_linux.exists()
    assert not drop_android.exists()
    assert not drop_x86.exists()
    assert not sources.exists()
    assert not workflow.exists()
    assert stats["removed_dirs"] >= 5


def test_prune_safety_net_deletes_stray_elf(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    stray = runtime / "misc" / "weird_tool"
    _write(stray, b"\x7fELF\x02\x01")
    stats = prune_windows_runtime(runtime)
    assert not stray.exists()
    assert stats["removed_elf"] == 1
