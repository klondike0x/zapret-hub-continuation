from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from zapret_hub.domain import MergeState
from zapret_hub.services.logging_service import LoggingManager
from zapret_hub.services.settings import SettingsManager
from zapret_hub.services.storage import StorageManager


class MergeEngine:
    def __init__(
        self,
        storage: StorageManager,
        logging: LoggingManager,
        settings: SettingsManager,
    ) -> None:
        self.storage = storage
        self.logging = logging
        self.settings = settings
        self._state_path = self.storage.paths.data_dir / "merge_state.json"

    def rebuild(self) -> MergeState:
        settings = self.settings.get()
        active_profile = settings.active_profile_id
        merged_dir = self.storage.paths.merged_runtime_dir
        visible_runtime = merged_dir / "zapret"
        if visible_runtime.exists():
            self.storage.create_backup(visible_runtime, "pre-rebuild-visible-runtime")
        merged_config = merged_dir / "config.json"
        if merged_config.exists():
            self.storage.create_backup(merged_config, "pre-rebuild-config")

        base_config = self.storage.read_json(self.storage.paths.default_packs_dir / "base_config.json", default={})
        merged = deepcopy(base_config)
        active_layers = ["base"]

        installed = self.storage.read_json(self.storage.paths.data_dir / "installed_mods.json", default=[]) or []
        if not isinstance(installed, list):
            installed = []
        for mod in installed:
            if not isinstance(mod, Mapping):
                continue
            if not mod.get("enabled"):
                continue
            mod_path = str(mod.get("path", "") or "").strip()
            if not mod_path:
                continue
            mod_config_path = Path(mod_path) / "payload.json"
            payload = self.storage.read_json(mod_config_path, default={}) or {}
            if not isinstance(payload, Mapping):
                self.logging.log("warning", "Mod payload ignored because it is not a JSON object", mod_id=str(mod.get("id", "")), path=str(mod_config_path))
                continue
            merged = self._merge_dicts(merged, payload)
            active_layers.append(str(mod.get("id", mod_path)))

        merged_path = merged_dir / "config.json"
        self.storage.write_json(merged_path, merged)
        state = MergeState(
            profile_id=active_profile,
            merged_path=str(merged_path),
            active_layers=active_layers,
        )
        self.storage.write_json(self._state_path, state)
        self.logging.log("info", "Merged runtime rebuilt", layers=active_layers, merged_path=str(merged_path))
        return state

    def get_state(self) -> MergeState | None:
        raw = self.storage.read_json(self._state_path, default=None)
        return MergeState(**raw) if raw else None

    def _merge_dicts(self, base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
        result = deepcopy(base)
        for key, value in override.items():
            if isinstance(value, Mapping) and isinstance(result.get(key), dict):
                result[key] = self._merge_dicts(result[key], value)
            elif isinstance(value, list) and isinstance(result.get(key), list):
                result[key] = list(dict.fromkeys([*result[key], *value]))
            else:
                result[key] = deepcopy(value)
        return result
