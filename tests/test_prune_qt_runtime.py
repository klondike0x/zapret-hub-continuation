from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("prune_qt_runtime", ROOT / "scripts" / "prune_qt_runtime.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
prune_qt_runtime = MODULE.prune_qt_runtime


def test_prune_keeps_production_webengine_files_and_ru_en_locales(tmp_path: Path) -> None:
    root = tmp_path / "main.dist"
    translations = root / "PySide6" / "translations"
    locales = translations / "qtwebengine_locales"
    locales.mkdir(parents=True)
    (root / "qtwebengine_resources.pak").write_bytes(b"production")
    (root / "qtwebengine_resources.debug.pak").write_bytes(b"debug")
    (translations / "qtbase_ru.qm").write_bytes(b"keep")
    (translations / "designer_ru.qm").write_bytes(b"drop")
    (locales / "ru.pak").write_bytes(b"keep")
    (locales / "en-US.pak").write_bytes(b"keep")
    (locales / "de.pak").write_bytes(b"drop")

    stats = prune_qt_runtime(root)

    assert stats["removed_files"] == 3
    assert (root / "qtwebengine_resources.pak").exists()
    assert not (root / "qtwebengine_resources.debug.pak").exists()
    assert (translations / "qtbase_ru.qm").exists()
    assert not (translations / "designer_ru.qm").exists()
    assert (locales / "ru.pak").exists()
    assert (locales / "en-US.pak").exists()
    assert not (locales / "de.pak").exists()
