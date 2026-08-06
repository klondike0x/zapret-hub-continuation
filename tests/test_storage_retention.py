from __future__ import annotations

import os
import time
from dataclasses import fields
from pathlib import Path

from zapret_hub.domain import AppPaths
from zapret_hub.services.logging_service import LoggingManager
from zapret_hub.services.storage import StorageManager


def _storage(tmp_path: Path) -> StorageManager:
    root = tmp_path / "hub"
    paths = AppPaths(
        install_root=root,
        core_dir=root / "core",
        runtime_dir=root / "runtime",
        configs_dir=root / "configs",
        default_packs_dir=root / "default_packs",
        mods_dir=root / "mods",
        mods_zapret2_dir=root / "mods_zapret2",
        merged_runtime_dir=root / "merged_runtime",
        backups_dir=root / "backups",
        cache_dir=root / "cache",
        logs_dir=root / "logs",
        data_dir=root / "data",
        ui_assets_dir=root / "ui_assets",
    )
    for path in (getattr(paths, item.name) for item in fields(paths)):
        path.mkdir(parents=True, exist_ok=True)
    return StorageManager(paths)


def test_retention_keeps_only_bounded_recent_backups(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.MAX_BACKUP_BYTES = 10
    storage.MAX_BACKUP_GENERATIONS = 2
    now = time.time()
    for index in range(4):
        folder = storage.paths.backups_dir / f"backup-{index}"
        folder.mkdir()
        (folder / "payload.bin").write_bytes(b"12345")
        os.utime(folder, (now + index, now + index))

    storage.prune_retained_data()

    assert sorted(item.name for item in storage.paths.backups_dir.iterdir()) == ["backup-2", "backup-3"]


def test_process_logs_are_preserved_and_zapret2_has_own_source(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    zapret2_log = storage.paths.logs_dir / "zapret2.log"
    zapret2_log.write_text("existing zapret2 diagnostic\n", encoding="utf-8")

    logging = LoggingManager(storage)

    assert zapret2_log.read_text(encoding="utf-8") == "existing zapret2 diagnostic\n"
    assert logging.source_log_path("zapret2").endswith("zapret2.log")
    assert "existing zapret2 diagnostic" in logging.read_source_lines("zapret2")
