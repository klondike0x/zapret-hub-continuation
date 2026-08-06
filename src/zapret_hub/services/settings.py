from __future__ import annotations

import locale
import re
import sys
import threading
from dataclasses import asdict

from zapret_hub.domain import AppSettings
from zapret_hub.services.service_catalog import SERVICE_PRESET_IDS
from zapret_hub.services.storage import StorageManager

if sys.platform.startswith("win"):
    import winreg


class SettingsManager:
    def __init__(self, storage: StorageManager) -> None:
        self.storage = storage
        self._settings_path = self.storage.paths.data_dir / "settings.json"
        self._lock = threading.RLock()
        self._settings = self.load()

    def load(self) -> AppSettings:
        raw = self.storage.read_json(self._settings_path, default={}) or {}
        allowed = {field.name for field in AppSettings.__dataclass_fields__.values()}
        raw = {key: value for key, value in raw.items() if key in allowed}
        settings = AppSettings(**raw)
        changed = False

        # первый запуск берёт дефолты из components.json
        if not bool(raw.get("component_selection_initialized", False)):
            components_raw = self.storage.read_json(self.storage.paths.data_dir / "components.json", default=[]) or []
            if isinstance(components_raw, list):
                enabled_defaults: list[str] = []
                autostart_defaults: list[str] = []
                for item in components_raw:
                    if not isinstance(item, dict):
                        continue
                    cid = str(item.get("id", "")).strip()
                    if not cid:
                        continue
                    if bool(item.get("enabled", False)):
                        enabled_defaults.append(cid)
                    if bool(item.get("autostart", False)):
                        autostart_defaults.append(cid)
                settings.enabled_component_ids = enabled_defaults
                settings.autostart_component_ids = autostart_defaults
            if not settings.selected_service_ids:
                from zapret_hub.services.service_rules import merge_auto_default_services

                settings.selected_service_ids = merge_auto_default_services([])
                if "gaming" in settings.selected_service_ids and str(
                    settings.zapret_game_filter_mode or "disabled"
                ) == "disabled":
                    settings.zapret_game_filter_mode = "tcpudp"
            # New clients: TG WS Proxy on; stock services selected (CF/Discord/YT/Gaming/Clouds).
            enabled = {str(item) for item in (settings.enabled_component_ids or [])}
            if "tg-ws-proxy" not in enabled:
                settings.enabled_component_ids = sorted([*enabled, "tg-ws-proxy"])
            settings.component_selection_initialized = True
            changed = True

        if not raw.get("language"):
            settings.language = self._detect_system_language()
            changed = True

        theme_defaults_marker = self.storage.paths.data_dir / ".theme_defaults_v4"
        initialize_theme_defaults = not theme_defaults_marker.exists()
        if initialize_theme_defaults:
            # Theme names and palettes from the legacy UI are intentionally not
            # migrated. Pick the initial v4 theme from Windows exactly once.
            settings.theme = "light" if self._detect_system_theme() == "light" else "night"
            changed = True
        elif raw.get("theme") not in {"night", "oled", "light"}:
            settings.theme = "light" if self._detect_system_theme() == "light" else "night"
            changed = True

        if str(getattr(settings, "ui_scale", "") or "") not in {"0.75", "1", "1.25"}:
            settings.ui_scale = "1"
            changed = True

        if not str(getattr(settings, "discord_rpc_client_id", "") or "").strip():
            settings.discord_rpc_client_id = "1530470595710685314"
            changed = True

        if raw.get("zapret_ipset_mode") not in {"loaded", "none", "any"}:
            settings.zapret_ipset_mode = "loaded"
            changed = True

        if raw.get("zapret_game_filter_mode") == "all":
            settings.zapret_game_filter_mode = "tcpudp"
            changed = True
        elif raw.get("zapret_game_filter_mode") == "auto":
            settings.zapret_game_filter_mode = "disabled"
            changed = True
        elif raw.get("zapret_game_filter_mode") not in {"disabled", "tcp", "udp", "tcpudp"}:
            settings.zapret_game_filter_mode = "disabled"
            changed = True

        normalized_udp_exclude = self._normalize_port_ranges(raw.get("zapret_udp_exclude_ports", settings.zapret_udp_exclude_ports))
        if normalized_udp_exclude != str(settings.zapret_udp_exclude_ports or ""):
            settings.zapret_udp_exclude_ports = normalized_udp_exclude
            changed = True

        if raw.get("zapret_gaming_set") not in {
            "base",
            "base-wide-stun",
            "wide-stun-base",
            "stun-wide-base",
            "stun-wide-base-local-exclude",
            "udp-first",
            "tcp-first",
            "stun-between",
        }:
            settings.zapret_gaming_set = "stun-wide-base"
            changed = True

        if raw.get("selected_runtime_mode") not in {"zapret", "zapret2", "none"}:
            settings.selected_runtime_mode = "zapret"
            changed = True

        if raw.get("zapret_control_mode") not in {"manual", "auto"}:
            settings.zapret_control_mode = "manual"
            changed = True

        if raw.get("zapret2_control_mode") not in {"manual", "auto"}:
            settings.zapret2_control_mode = "manual"
            changed = True

        strategy_id = str(raw.get("zapret2_strategy_id", getattr(settings, "zapret2_strategy_id", "balanced")) or "balanced")
        if strategy_id not in {"balanced", "fake_heavy", "multisplit"}:
            settings.zapret2_strategy_id = "balanced"
            changed = True

        if not isinstance(raw.get("trusted_general", settings.trusted_general), str):
            settings.trusted_general = ""
            changed = True

        if raw.get("dns_profile") not in {"dhcp", "xbox", "cloudflare", "adguard", "google", "yandex"}:
            settings.dns_profile = "xbox"
            changed = True

        runtime_modes = ("zapret", "zapret2", "none")
        raw_runtime_order = raw.get("runtime_mode_order", settings.runtime_mode_order)
        if not isinstance(raw_runtime_order, list):
            raw_runtime_order = []
        normalized_runtime_order = [
            mode for mode in raw_runtime_order if isinstance(mode, str) and mode in runtime_modes
        ]
        normalized_runtime_order.extend(mode for mode in runtime_modes if mode not in normalized_runtime_order)
        if normalized_runtime_order != list(settings.runtime_mode_order):
            settings.runtime_mode_order = normalized_runtime_order
            changed = True

        if raw.get("sounds_volume") not in {"normal", "louder", "quieter"}:
            settings.sounds_volume = "normal"
            changed = True

        selected_service_ids = raw.get("selected_service_ids", None)
        if selected_service_ids is None:
            # Key missing: keep first-init YouTube/Discord defaults (or seed now).
            if not list(settings.selected_service_ids or []):
                from zapret_hub.services.service_rules import merge_auto_default_services

                settings.selected_service_ids = merge_auto_default_services([])
                changed = True
        elif not isinstance(selected_service_ids, list):
            settings.selected_service_ids = []
            changed = True
        else:
            service_migrations = {
                "steam": "clouds",
                "twitch": "fortnite",
                "roblox": "gaming",
                "tiktok": "ai",
                "instagram": "ubisoft",
            }
            migrated_service_ids = [
                service_migrations.get(str(item).strip(), str(item).strip())
                for item in selected_service_ids
            ]
            normalized_service_ids = [item for item in migrated_service_ids if item in SERVICE_PRESET_IDS]
            if normalized_service_ids != list(settings.selected_service_ids):
                settings.selected_service_ids = normalized_service_ids
                changed = True

        if changed:
            self.storage.write_json(self._settings_path, asdict(settings))
        if initialize_theme_defaults:
            theme_defaults_marker.write_text("1", encoding="utf-8")
        return settings

    def get(self) -> AppSettings:
        with self._lock:
            return self._settings

    def reload(self) -> AppSettings:
        with self._lock:
            self._settings = self.load()
            return self._settings

    def update(self, **changes: object) -> AppSettings:
        with self._lock:
            if "zapret_udp_exclude_ports" in changes:
                changes["zapret_udp_exclude_ports"] = self._normalize_port_ranges(changes.get("zapret_udp_exclude_ports", ""))
            if "zapret_control_mode" in changes:
                mode = str(changes.get("zapret_control_mode") or "manual").strip().lower()
                changes["zapret_control_mode"] = "auto" if mode == "auto" else "manual"
            if "trusted_general" in changes:
                changes["trusted_general"] = str(changes.get("trusted_general") or "").strip()
            for key, value in changes.items():
                setattr(self._settings, key, value)
            self.save()
            return self._settings

    def save(self) -> None:
        with self._lock:
            self.storage.write_json(self._settings_path, asdict(self._settings))

    def _detect_system_language(self) -> str:
        try:
            locale_name = (locale.getdefaultlocale()[0] or "").lower()  # type: ignore[call-arg]
        except Exception:
            locale_name = ""
        return "ru" if locale_name.startswith("ru") else "en"

    def _normalize_port_ranges(self, value: object) -> str:
        ranges: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for raw in re.split(r"[\s,;]+", str(value or "")):
            token = raw.strip()
            if not token:
                continue
            if "-" in token:
                left, right = token.split("-", 1)
            else:
                left = right = token
            try:
                start = int(left)
                end = int(right)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            if start < 1 or end > 65535:
                continue
            item = (start, end)
            if item in seen:
                continue
            seen.add(item)
            ranges.append(item)
        return ",".join(str(start) if start == end else f"{start}-{end}" for start, end in ranges)

    def _detect_system_theme(self) -> str:
        if not sys.platform.startswith("win"):
            return "dark"
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                0,
                winreg.KEY_READ,
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "light" if int(value) == 1 else "dark"
        except Exception:
            return "dark"
