from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, fields, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from zapret_hub.domain import AppPaths


class StorageManager:
    # Retained diagnostic data must never silently grow without a bound. Runtime,
    # user settings and installed modifications are deliberately not part of this
    # budget: they are application data rather than disposable cache.
    MAX_BACKUP_BYTES = 30 * 1024 * 1024
    MAX_BACKUP_GENERATIONS = 3
    MAX_CACHE_BYTES = 12 * 1024 * 1024

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths

    def ensure_layout(self) -> None:
        for field_info in fields(self.paths):
            path = getattr(self.paths, field_info.name)
            if isinstance(path, Path):
                path.mkdir(parents=True, exist_ok=True)
        self._ensure_sample_files()
        self.prune_retained_data()

    @staticmethod
    def _tree_size(path: Path) -> int:
        if not path.exists():
            return 0
        if path.is_file():
            try:
                return path.stat().st_size
            except OSError:
                return 0
        total = 0
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    try:
                        total += item.stat().st_size
                    except OSError:
                        continue
        except OSError:
            return total
        return total

    @staticmethod
    def _remove_empty_parents(path: Path, stop_at: Path) -> None:
        current = path.parent
        while current != stop_at:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def prune_retained_data(self) -> None:
        """Apply bounded retention to disposable backups and cache files.

        This is intentionally best-effort. A locked file should never prevent the
        application from starting, and no user modification/runtime is removed.
        """
        self._prune_backups()
        self._prune_cache()

    def _prune_backups(self) -> None:
        root = self.paths.backups_dir
        if not root.exists():
            return
        try:
            entries = sorted(
                (item for item in root.iterdir() if item.is_dir()),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        retained_size = 0
        for index, entry in enumerate(entries):
            size = self._tree_size(entry)
            keep = index < self.MAX_BACKUP_GENERATIONS and retained_size + size <= self.MAX_BACKUP_BYTES
            if keep:
                retained_size += size
                continue
            try:
                shutil.rmtree(entry)
            except OSError:
                continue

    def _prune_cache(self) -> None:
        root = self.paths.cache_dir
        if not root.exists():
            return
        protected = {"mods_index.json", "app_releases_cache.json"}
        try:
            files = sorted(
                (item for item in root.rglob("*") if item.is_file() and item.name not in protected),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        retained_size = sum(self._tree_size(root / name) for name in protected)
        for item in files:
            try:
                size = item.stat().st_size
            except OSError:
                continue
            if retained_size + size <= self.MAX_CACHE_BYTES:
                retained_size += size
                continue
            try:
                item.unlink()
                self._remove_empty_parents(item, root)
            except OSError:
                continue

    def _ensure_sample_files(self) -> None:
        components_file = self.paths.data_dir / "components.json"
        zapret_version = self._detect_zapret_version()
        zapret2_version = self._detect_zapret2_version()
        default_components = [
            {
                "id": "zapret",
                "name": "Zapret",
                "description": "Основной модуль локальной обработки сетевого трафика.",
                "version": zapret_version,
                "source": "https://github.com/Flowseal/zapret-discord-youtube",
                "command": ["cmd.exe", "/c", "general.bat"],
                "enabled": True,
                "autostart": False,
            },
            {
                "id": "zapret2",
                "name": "Zapret2",
                "description": "Новое поколение zapret от bol-van с winws2/nfqws2 и Lua-стратегиями.",
                "version": zapret2_version,
                "source": "https://github.com/bol-van/zapret2",
                "command": [],
                "enabled": False,
                "autostart": False,
            },
            {
                "id": "xbox-dns",
                "name": "XBox DNS",
                "description": "DNS-серверы для доступа к нейросетям, играм и полезным инструментам без VPN.",
                "version": "",
                "source": "https://xbox-dns.ru/",
                "command": [],
                "enabled": False,
                "autostart": False,
            },
        ]
        existing = self.read_json(components_file, default=[]) or []
        by_id = {item.get("id"): item for item in existing if isinstance(item, dict)}
        normalized_components: list[dict[str, Any]] = []
        for default_item in default_components:
            merged = dict(default_item)
            current = by_id.get(default_item["id"])
            if isinstance(current, dict):
                merged["enabled"] = bool(current.get("enabled", merged["enabled"]))
                merged["autostart"] = bool(current.get("autostart", merged["autostart"]))
            normalized_components.append(merged)
        if existing != normalized_components:
            self.write_json(components_file, normalized_components)

        profiles_file = self.paths.data_dir / "profiles.json"
        if not profiles_file.exists():
            self.write_json(
                profiles_file,
                [
                    {
                        "id": "default",
                        "name": "Default",
                        "description": "Default operational profile",
                        "base_config_path": str(self.paths.default_packs_dir),
                    }
                ],
            )

        settings_file = self.paths.data_dir / "settings.json"
        if not settings_file.exists():
            self.write_json(settings_file, {})

        self._ensure_default_bundled_mod_and_index(settings_file)

        base_config = self.paths.default_packs_dir / "base_config.json"
        if not base_config.exists():
            self.write_json(
                base_config,
                {
                    "rules": ["base-rule-1", "base-rule-2"],
                    "dns": {"primary": "1.1.1.1", "secondary": "8.8.8.8"},
                },
            )

        readme_hint = self.paths.configs_dir / "README.txt"
        if not readme_hint.exists():
            readme_hint.write_text(
                "This folder contains editable user configuration files for Zapret Hub.\n",
                encoding="utf-8",
            )

        for filename in ("list-general-user.txt", "list-exclude-user.txt", "ipset-all-user.txt", "ipset-exclude-user.txt"):
            path = self.paths.configs_dir / filename
            if not path.exists():
                path.write_text("", encoding="utf-8")

        self._ensure_icon_assets()

    def _detect_zapret_version(self) -> str:
        service_bat = self.paths.runtime_dir / "zapret-discord-youtube" / "service.bat"
        if not service_bat.exists():
            return "unknown"
        try:
            for line in service_bat.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "LOCAL_VERSION" not in line:
                    continue
                value = line.split("=", 1)[-1].strip().strip('"').strip()
                value = value.replace("set", "").replace("LOCAL_VERSION", "").replace("=", "").strip('" ').strip()
                if value:
                    return value
        except Exception:
            return "unknown"
        return "unknown"

    def _detect_zapret2_version(self) -> str:
        version_file = self.paths.runtime_dir / "zapret2" / ".zapret-hub-version"
        try:
            value = version_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            pass
        return "master"

    def _ensure_default_bundled_mod_and_index(self, settings_file: Path) -> None:
        legacy_mod_id = "gaming-by-goshkow"
        default_mod_id = "unified-by-goshkow"
        default_mod_meta = {
            "id": default_mod_id,
            "name": "Hub",
            "description": "Позволяет обойти блокировки самых популярных сервисов, включая игровые сервисы, социальные сети и другие платформы.",
            "author": "goshkow",
            "version": "1.9.9a-unified4",
            "source_url": "bundled://unified-by-goshkow",
            "category": "gaming",
            "tags": ["gaming", "social", "cloudflare", "ubisoft", "arc-raiders"],
            "dependencies": [],
            "conflicts": [],
            "changelog": "Default unified bundle included.",
        }

        installed_path = self.paths.data_dir / "installed_mods.json"
        installed = self.read_json(installed_path, default=[]) or []
        if not isinstance(installed, list):
            installed = []
        existing_default = next(
            (
                item
                for item in installed
                if isinstance(item, dict) and item.get("id") == default_mod_id
            ),
            None,
        )
        desired_version = str(default_mod_meta.get("version", "1.9.9a-unified4"))
        default_bundle = self._ensure_default_bundled_mod(
            default_mod_id,
            default_mod_meta,
            force_refresh=not isinstance(existing_default, dict) or str(existing_default.get("version", "")) != desired_version,
        )

        mods_index_path = self.paths.cache_dir / "mods_index.json"
        mods_index = self.read_json(mods_index_path, default=[]) or []
        if not isinstance(mods_index, list):
            mods_index = []
        filtered_index: list[dict[str, Any]] = []
        for item in mods_index:
            if not isinstance(item, dict):
                continue
            if item.get("id") in {"sample-hosts-pack", legacy_mod_id}:
                continue
            filtered_index.append(item)
        if not any(isinstance(item, dict) and item.get("id") == default_mod_id for item in filtered_index):
            filtered_index.append(default_mod_meta)
        if mods_index != filtered_index:
            self.write_json(mods_index_path, filtered_index)

        cleaned_installed: list[dict[str, Any]] = []
        legacy_enabled = False
        for item in installed:
            if not isinstance(item, dict):
                continue
            if item.get("id") == "sample-hosts-pack":
                continue
            if item.get("id") == legacy_mod_id:
                legacy_enabled = bool(item.get("enabled"))
                continue
            cleaned_installed.append(item)
        if default_bundle is not None:
            existing_default = next((item for item in cleaned_installed if item.get("id") == default_mod_id), None)
            if existing_default is None:
                default_bundle["enabled"] = legacy_enabled
                cleaned_installed.append(default_bundle)
            else:
                existing_default.update(
                    {
                        "path": default_bundle["path"],
                        "version": default_bundle["version"],
                        "name": default_bundle.get("name", ""),
                        "author": default_bundle.get("author", ""),
                        "description": default_bundle.get("description", ""),
                        "source_url": default_bundle.get("source_url", ""),
                        "source_type": default_bundle.get("source_type", "zapret_bundle"),
                        "general_scripts": default_bundle.get("general_scripts", []),
                    }
                )
        if installed != cleaned_installed:
            self.write_json(installed_path, cleaned_installed)

        settings_data = self.read_json(settings_file, default={}) or {}
        if isinstance(settings_data, dict):
            enabled_mods = settings_data.get("enabled_mod_ids", [])
            if isinstance(enabled_mods, list):
                normalized_enabled = [m for m in enabled_mods if m not in {"sample-hosts-pack", legacy_mod_id}]
                if legacy_mod_id in enabled_mods and default_mod_id not in normalized_enabled:
                    normalized_enabled.append(default_mod_id)
                if normalized_enabled != enabled_mods:
                    settings_data["enabled_mod_ids"] = normalized_enabled
                    self.write_json(settings_file, settings_data)

        legacy_dir = self.paths.mods_dir / legacy_mod_id
        if legacy_dir.exists():
            shutil.rmtree(legacy_dir, ignore_errors=True)

    def _ensure_default_bundled_mod(
        self,
        mod_id: str,
        meta: dict[str, Any],
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        sample_root = self.paths.install_root / "sample_data" / "default_mods" / mod_id
        source_candidates = [
            sample_root,
            self.paths.runtime_dir / "zapret-discord-youtube",
            Path(r"C:\zapret-discord-youtube-1.9.7"),
        ]
        source_root = next((path for path in source_candidates if self._looks_like_zapret_bundle(path)), None)
        if source_root is None:
            return None

        target_dir = self.paths.mods_dir / mod_id
        if force_refresh or not self._looks_like_materialized_mod_bundle(target_dir):
            self._copy_filtered_zapret_bundle(source_root, target_dir, skip_base_duplicates=source_root != sample_root)
        legacy_gaming_general = target_dir / "general (Gaming).bat"
        if legacy_gaming_general.exists():
            try:
                legacy_gaming_general.unlink()
            except OSError:
                pass
        allowed_hidden_generals = {"general (ubisoft).bat"}
        for legacy_general in target_dir.glob("*.bat"):
            lowered_name = legacy_general.name.lower()
            if lowered_name.startswith("service") or lowered_name in allowed_hidden_generals:
                continue
            try:
                legacy_general.unlink()
            except OSError:
                pass

        general_scripts = sorted(
            script.name
            for script in target_dir.glob("*.bat")
            if not script.name.lower().startswith("service")
        )
        return {
            "id": mod_id,
                "version": str(meta.get("version", "1.9.9a-unified4")),
            "path": str(target_dir),
            "enabled": False,
            "name": str(meta.get("name", "")),
            "author": str(meta.get("author", "")),
            "description": str(meta.get("description", "")),
            "source_url": str(meta.get("source_url", "")),
            "source_type": "zapret_bundle",
            "general_scripts": general_scripts,
            "emoji": "🪄",
        }

    def _looks_like_materialized_mod_bundle(self, path: Path) -> bool:
        if not path.exists():
            return False
        has_general = any(
            script.is_file() and not script.name.lower().startswith("service")
            for script in path.glob("*.bat")
        )
        return has_general and (path / "lists").is_dir()

    def _looks_like_zapret_bundle(self, path: Path) -> bool:
        return (path / "bin").is_dir() and (path / "lists").is_dir()

    def _copy_filtered_zapret_bundle(self, source_root: Path, target_dir: Path, *, skip_base_duplicates: bool = True) -> None:
        base_general_names = set()
        if skip_base_duplicates:
            base_general_names = {
                item.name.lower()
                for item in (self.paths.runtime_dir / "zapret-discord-youtube").glob("*.bat")
                if not item.name.lower().startswith("service")
            }
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        for script in source_root.glob("*.bat"):
            if script.name.lower().startswith("service"):
                continue
            if script.name.lower() in base_general_names:
                continue
            shutil.copy2(script, target_dir / script.name)

        for folder in ("lists", "utils"):
            (target_dir / folder).mkdir(parents=True, exist_ok=True)

        bin_suffixes = {".bin"}
        if self._bin_dir_differs_from_base(source_root / "bin", suffixes=bin_suffixes):
            for item in (source_root / "bin").glob("*"):
                if not item.is_file():
                    continue
                if item.suffix.lower() in bin_suffixes:
                    (target_dir / "bin").mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target_dir / "bin" / item.name)

        for item in (source_root / "lists").glob("*.txt"):
            (target_dir / "lists").mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target_dir / "lists" / item.name)

        base_utils = self.paths.runtime_dir / "zapret-discord-youtube" / "utils"
        if base_utils.exists():
            for item in base_utils.glob("*"):
                if item.is_file():
                    (target_dir / "utils").mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target_dir / "utils" / item.name)

        source_utils = source_root / "utils"
        if source_utils.exists():
            for item in source_utils.glob("*"):
                if item.is_file():
                    (target_dir / "utils").mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target_dir / "utils" / item.name)

    def _bin_dir_differs_from_base(self, bin_dir: Path, *, suffixes: set[str]) -> bool:
        if not bin_dir.exists() or not bin_dir.is_dir():
            return False
        base_bin = self.paths.runtime_dir / "zapret-discord-youtube" / "bin"
        if not base_bin.exists():
            return any(item.is_file() and item.suffix.lower() in suffixes for item in bin_dir.glob("*"))
        for item in bin_dir.glob("*"):
            if not item.is_file() or item.suffix.lower() not in suffixes:
                continue
            base_file = base_bin / item.name
            if not base_file.exists():
                return True
            try:
                if item.stat().st_size != base_file.stat().st_size:
                    return True
                if item.read_bytes() != base_file.read_bytes():
                    return True
            except Exception:
                return True
        return False

    def _ensure_icon_assets(self) -> None:
        icons_dir = self.paths.ui_assets_dir / "icons"
        icons_dir.mkdir(parents=True, exist_ok=True)
        icon_map: dict[str, str] = {
            "app.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><defs><linearGradient id="bg" x1="0.06" y1="0.08" x2="0.92" y2="0.86"><stop offset="0%" stop-color="#c02cff"/><stop offset="46%" stop-color="#5632ff"/><stop offset="100%" stop-color="#1ba0ff"/></linearGradient><clipPath id="clip"><path d="M58 51l63-34c13-7 29-10 44-9h40c31 0 51 7 64 20c14 14 20 33 20 64v70c0 32-6 51-20 65c-14 14-33 20-65 20h-91c-28 0-46-7-60-21c-14-14-20-31-21-60V116c0-27 7-48 26-65z"/></clipPath></defs><path d="M58 51l63-34c13-7 29-10 44-9h40c31 0 51 7 64 20c14 14 20 33 20 64v70c0 32-6 51-20 65c-14 14-33 20-65 20h-91c-28 0-46-7-60-21c-14-14-20-31-21-60V116c0-27 7-48 26-65z" fill="url(#bg)"/><g clip-path="url(#clip)" transform="matrix(1 -0.22 0 1 30 0)"><rect x="62" y="34" width="56" height="190" rx="10" fill="#ffffff"/><rect x="164" y="34" width="56" height="190" rx="10" fill="#ffffff"/><rect x="104" y="112" width="94" height="42" rx="8" fill="#ffffff"/></g></svg>',
            "home.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#7ea1cf" d="M3 10.5L12 3l9 7.5v9a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 19.5z"/><path fill="#d5e0f3" d="M9 21v-6h6v6"/></svg>',
            "components.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="3" y="3" width="8" height="8" rx="2" fill="#6fae9a"/><rect x="13" y="3" width="8" height="8" rx="2" fill="#5a9b87"/><rect x="3" y="13" width="8" height="8" rx="2" fill="#8abcae"/><rect x="13" y="13" width="8" height="8" rx="2" fill="#4f8777"/></svg>',
            "component_zapret.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#67b68f" d="M12 2l8 3v6c0 5-3.6 9.2-8 11c-4.4-1.8-8-6-8-11V5z"/></svg>',
            "component_zapret2.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#2563eb" d="M12 2l8 3v6c0 5-3.6 9.2-8 11c-4.4-1.8-8-6-8-11V5z"/><path fill="#ffffff" d="M8.4 9.2C8.8 7 10.3 5.8 12.5 5.8c2.1 0 3.6 1.2 3.6 3.1c0 1.4-.7 2.4-2.2 3.5l-2.4 1.8h4.8v2.5H8.2v-2.1l3.9-2.9c1-.8 1.4-1.3 1.4-2.1c0-.8-.5-1.3-1.3-1.3c-.9 0-1.4.6-1.6 1.6z"/></svg>',
            "component_xbox_dns.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path fill="#22c55e" d="M15 12h11l6.2 10.6L38.7 12H49L38.2 31.1L50 52H38.9L31.8 39.7L24.6 52H14l11.9-20.5z"/></svg>',
            "mods.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#8f7f60" d="M2.5 7.2L12 2.5l9.5 4.7v9.6L12 21.5l-9.5-4.7z"/><path fill="#a59270" d="M12 2.5v19M2.5 7.2L12 12l9.5-4.8"/><path fill="none" stroke="#d9ceb6" stroke-width="1.1" stroke-linejoin="round" d="M2.5 7.2L12 2.5l9.5 4.7v9.6L12 21.5l-9.5-4.7z"/><circle cx="12" cy="12" r="2.1" fill="#d7c7a2"/><path fill="#c6b18b" d="M10.8 9.2h2.4v1.4h-2.4zm0 4.2h2.4v1.4h-2.4zM9.2 10.8h1.4v2.4H9.2zm4.2 0h1.4v2.4h-1.4z"/></svg>',
            "files.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#7fa9c9" d="M4 3h9l5 5v13H4z"/><path fill="#c8d9ea" d="M13 3v5h5"/></svg>',
            "logs.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="2" fill="#9083bd"/><rect x="7" y="7" width="10" height="2" fill="#e1dbf3"/><rect x="7" y="11" width="10" height="2" fill="#e1dbf3"/><rect x="7" y="15" width="6" height="2" fill="#e1dbf3"/></svg>',
            "power.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path fill="#ffffff" d="M29 6h6v26h-6z"/><path fill="#ffffff" d="M32 58C18.7 58 8 47.3 8 34c0-8.4 4.4-16.2 11.5-20.6l3.1 5.1A18 18 0 1 0 41.4 18l3.1-5.1A24 24 0 0 1 32 58z"/></svg>',
            "power_dark.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path fill="#ffffff" d="M29 6h6v26h-6z"/><path fill="#ffffff" d="M32 58C18.7 58 8 47.3 8 34c0-8.4 4.4-16.2 11.5-20.6l3.1 5.1A18 18 0 1 0 41.4 18l3.1-5.1A24 24 0 0 1 32 58z"/></svg>',
            "power_light.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path fill="#1f2a3d" d="M29 6h6v26h-6z"/><path fill="#1f2a3d" d="M32 58C18.7 58 8 47.3 8 34c0-8.4 4.4-16.2 11.5-20.6l3.1 5.1A18 18 0 1 0 41.4 18l3.1-5.1A24 24 0 0 1 32 58z"/></svg>',
            "status_ok.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#22c55e"/><path d="M7 12l3 3l7-7" stroke="#fff" stroke-width="2" fill="none"/></svg>',
            "status_warn.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#f59e0b"/><path d="M12 7v6" stroke="#fff" stroke-width="2"/><circle cx="12" cy="16.5" r="1.2" fill="#fff"/></svg>',
            "status_off.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#64748b"/><path d="M8 8l8 8M16 8l-8 8" stroke="#fff" stroke-width="2"/></svg>',
            "status_mod.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#8b5cf6" d="M4 7l8-4l8 4v10l-8 4l-8-4z"/></svg>',
            "status_theme.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#0ea5e9" d="M12 3a9 9 0 1 0 9 9a7 7 0 1 1-9-9z"/></svg>',
            "chevron_down.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M6 9l6 6l6-6" stroke="#9fb3d4" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            "edit.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#9fb3d4" d="M3 17.25V21h3.75L19.81 7.94l-3.75-3.75z"/><path fill="#c7d7f2" d="M20.71 6.04a1 1 0 0 0 0-1.41L19.37 3.29a1 1 0 0 0-1.41 0l-1.13 1.13l3.75 3.75z"/></svg>',
            "tool.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="#9fb3d4" stroke-width="1.9" stroke-linecap="round"><path d="M6 7.5h12"/><circle cx="9" cy="7.5" r="2.1" fill="#9fb3d4" stroke="none"/><path d="M6 12h12"/><circle cx="15" cy="12" r="2.1" fill="#9fb3d4" stroke="none"/><path d="M6 16.5h12"/><circle cx="11" cy="16.5" r="2.1" fill="#9fb3d4" stroke="none"/></g></svg>',
            "bell.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="#9fb3d4" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M18 9.5a6 6 0 0 0-12 0c0 5-2 6-2 6h16s-2-1-2-6z"/><path d="M9.8 19a2.4 2.4 0 0 0 4.4 0"/></g></svg>',
            "settings.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="none" stroke="#9fb3d4" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3.2l1 .3l.6 1.9l1.6.7l1.8-.7l1.4 1.4l-.7 1.8l.7 1.6l1.9.6l.3 1l-.3 1l-1.9.6l-.7 1.6l.7 1.8l-1.4 1.4l-1.8-.7l-1.6.7l-.6 1.9l-1 .3l-1-.3l-.6-1.9l-1.6-.7l-1.8.7l-1.4-1.4l.7-1.8l-.7-1.6l-1.9-.6l-.3-1l.3-1l1.9-.6l.7-1.6l-.7-1.8l1.4-1.4l1.8.7l1.6-.7l.6-1.9z"/><circle cx="12" cy="12" r="2.7"/></g></svg>',
            "check.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.2 8.6l2.4 2.5l7.2-6.2" fill="none" stroke="#ffffff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/></svg>',
            "plus.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" fill="none" stroke="#9fb3d4" stroke-width="2" stroke-linecap="round"/></svg>',
            "window_min_dark.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 12h14" stroke="#e7edf9" stroke-width="2.2" stroke-linecap="round"/></svg>',
            "window_close_dark.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M7 7l10 10M17 7L7 17" stroke="#e7edf9" stroke-width="2.2" stroke-linecap="round"/></svg>',
            "window_min_light.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 12h14" stroke="#1f2a3d" stroke-width="2.2" stroke-linecap="round"/></svg>',
            "window_close_light.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M7 7l10 10M17 7L7 17" stroke="#1f2a3d" stroke-width="2.2" stroke-linecap="round"/></svg>',
            "window_min.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M5 12h14" stroke="#e7edf9" stroke-width="2.2" stroke-linecap="round"/></svg>',
            "window_close.svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M7 7l10 10M17 7L7 17" stroke="#e7edf9" stroke-width="2.2" stroke-linecap="round"/></svg>',
        }
        for filename, content in icon_map.items():
            icon_path = icons_dir / filename
            if icon_path.exists():
                continue
            icon_path.write_text(content, encoding="utf-8")

    def read_json(self, path: Path, default: Any | None = None) -> Any:
        self._promote_pending_json(path)
        if not path.exists():
            return default
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError:
            return default
        if not content.strip():
            self._backup_invalid_json(path, "empty")
            return default
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            self._backup_invalid_json(path, "invalid")
            return default

    def write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(payload) if is_dataclass(payload) else payload
        temp_path = path.with_name(f"{path.name}.tmp-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}")
        try:
            with temp_path.open("w", encoding="utf-8") as file:
                json.dump(data, file, indent=2, ensure_ascii=False)
                file.write("\n")
            last_error: OSError | None = None
            for attempt in range(12):
                try:
                    os.replace(temp_path, path)
                    return
                except PermissionError as error:
                    last_error = error
                    time.sleep(0.05 + attempt * 0.04)
                except OSError as error:
                    last_error = error
                    time.sleep(0.05 + attempt * 0.04)
            fallback_path = path.with_name(f"{path.name}.pending-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}")
            try:
                shutil.copy2(temp_path, fallback_path)
            except OSError:
                fallback_path = None
            try:
                path.write_text(temp_path.read_text(encoding="utf-8"), encoding="utf-8")
                return
            except OSError:
                if fallback_path is not None:
                    return
            if last_error is not None:
                raise last_error
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _backup_invalid_json(self, path: Path, reason: str) -> None:
        if not path.exists():
            return
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = path.with_name(f"{path.name}.{reason}-{stamp}.bak")
        try:
            shutil.copy2(path, backup_path)
        except OSError:
            pass

    def create_backup(self, source: Path, reason: str) -> Path:
        self._prune_backups()
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        backup_dir = self.paths.backups_dir / f"{stamp}-{reason}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        destination = backup_dir / source.name
        if source.is_dir():
            self._copytree_resilient(source, destination)
        elif source.exists():
            try:
                shutil.copy2(source, destination)
            except OSError:
                pass
        self._prune_backups()
        return backup_dir

    def _promote_pending_json(self, path: Path) -> None:
        try:
            candidates = sorted(
                path.parent.glob(f"{path.name}.pending-*"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return
        for candidate in candidates[:3]:
            try:
                content = candidate.read_text(encoding="utf-8-sig")
                if not content.strip():
                    continue
                json.loads(content)
                for attempt in range(6):
                    try:
                        os.replace(candidate, path)
                        return
                    except OSError:
                        time.sleep(0.04 + attempt * 0.04)
                try:
                    path.write_text(content, encoding="utf-8")
                    candidate.unlink(missing_ok=True)
                    return
                except OSError:
                    return
            except OSError:
                return
            except json.JSONDecodeError:
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    pass

    def _copytree_resilient(self, source: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(source, topdown=True):
            root_path = Path(root)
            try:
                relative = root_path.relative_to(source)
            except ValueError:
                relative = Path()
            target_root = destination / relative
            target_root.mkdir(parents=True, exist_ok=True)
            dirs[:] = [item for item in dirs if item not in {".git", "__pycache__", ".mypy_cache", ".pytest_cache"}]
            for name in files:
                if Path(name).suffix.lower() in {".pyc", ".pyo"}:
                    continue
                src = root_path / name
                dst = target_root / name
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    continue
