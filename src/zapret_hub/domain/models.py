from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AppSettings:
    theme: str = "night"
    ui_scale: str = "1"
    language: str = "ru"
    start_in_tray: bool = False
    autostart_windows: bool = False
    auto_run_components: bool = False
    check_updates_on_start: bool = True
    check_mod_updates_on_start: bool = True
    check_component_updates_on_start: bool = True
    windows_notifications_enabled: bool = True
    notifications_enabled: bool = True
    show_tray_hide_notification: bool = True
    hardware_acceleration_enabled: bool = True
    sounds_enabled: bool = True
    sounds_click_enabled: bool = True
    sounds_volume: str = "normal"
    sidebar_collapsed: bool = False
    quick_access_widget: str = "analysis"
    runtime_scroll_switch_enabled: bool = True
    work_root: str = ""
    active_profile_id: str = "default"
    enabled_component_ids: list[str] = field(default_factory=list)
    autostart_component_ids: list[str] = field(default_factory=list)
    component_selection_initialized: bool = False
    enabled_mod_ids: list[str] = field(default_factory=list)
    enabled_zapret2_mod_ids: list[str] = field(default_factory=list)
    mods_index_url: str = ""
    app_update_url: str = ""
    tg_proxy_host: str = "127.0.0.1"
    tg_proxy_port: int = 1443
    tg_proxy_secret: str = ""
    tg_proxy_dc_ip: str = "4:149.154.167.220"
    tg_proxy_cfproxy_enabled: bool = True
    tg_proxy_cfproxy_priority: bool = True
    tg_proxy_cfproxy_domain: str = ""
    tg_proxy_fake_tls_domain: str = ""
    tg_proxy_buf_kb: int = 256
    tg_proxy_pool_size: int = 4
    tg_proxy_link_prompt_signature: str = ""
    selected_zapret_general: str = ""
    favorite_zapret_generals: list[str] = field(default_factory=list)
    general_autotest_done: bool = False
    zapret_control_mode: str = "manual"
    zapret2_control_mode: str = "manual"
    trusted_general: str = ""
    selected_service_ids: list[str] = field(default_factory=list)
    selected_runtime_mode: str = "zapret"
    runtime_mode_order: list[str] = field(
        default_factory=lambda: ["zapret", "zapret2", "none"]
    )
    no_bypass_power_enabled: bool = False
    zapret_ipset_mode: str = "loaded"
    zapret_game_filter_mode: str = "disabled"
    zapret_gaming_set: str = "stun-wide-base"
    zapret_udp_exclude_ports: str = ""
    zapret2_tcp_ports: str = "80,443"
    zapret2_udp_ports: str = "443"
    zapret2_raw_filter: str = ""
    zapret2_lua_strategy: str = ""
    zapret2_strategy_id: str = "balanced"
    # Deprecated compatibility field; the switch is no longer exposed or applied.
    zapret2_youtube_discord_bypass: bool = True
    zapret_was_running_before_zapret2: bool = False
    zapret_was_enabled_before_zapret2: bool = False
    xbox_dns_was_enabled_before_zapret2: bool = False
    dns_profile: str = "xbox"
    apply_update_on_next_launch: bool = False
    # Discord Rich Presence (Application ID from Discord Developer Portal).
    discord_rpc_enabled: bool = True
    discord_rpc_client_id: str = "1530470595710685314"


@dataclass(slots=True)
class ComponentDefinition:
    id: str
    name: str
    description: str
    version: str
    source: str
    command: list[str]
    enabled: bool = True
    autostart: bool = True


@dataclass(slots=True)
class ComponentState:
    component_id: str
    status: str = "stopped"
    pid: int | None = None
    last_error: str = ""


@dataclass(slots=True)
class ConfigProfile:
    id: str
    name: str
    description: str
    base_config_path: str


@dataclass(slots=True)
class ModIndexItem:
    id: str
    name: str
    description: str
    author: str
    version: str
    source_url: str
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    changelog: str = ""


@dataclass(slots=True)
class InstalledMod:
    id: str
    version: str
    path: str
    name: str = ""
    author: str = ""
    description: str = ""
    source_url: str = ""
    enabled: bool = False
    source_type: str = "generic"
    general_scripts: list[str] = field(default_factory=list)
    emoji: str = ""
    icon_url: str = ""
    installed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass(slots=True)
class MergeState:
    profile_id: str
    merged_path: str
    active_layers: list[str]
    rebuilt_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass(slots=True)
class BackupSnapshot:
    id: str
    created_at: str
    reason: str
    path: str


@dataclass(slots=True)
class UpdateInfo:
    target: str
    current_version: str
    latest_version: str
    status: str
    changelog: str = ""


@dataclass(slots=True)
class ReleaseEntry:
    version: str
    body: str
    html_url: str
    is_latest: bool = False


@dataclass(slots=True)
class DiagnosticResult:
    name: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LogEntry:
    timestamp: str
    level: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class NotificationEntry:
    id: str
    level: str
    title: str
    message: str
    source: str = "app"
    created_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat())
    read: bool = False
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AppPaths:
    install_root: Path
    core_dir: Path
    runtime_dir: Path
    configs_dir: Path
    default_packs_dir: Path
    mods_dir: Path
    mods_zapret2_dir: Path
    merged_runtime_dir: Path
    backups_dir: Path
    cache_dir: Path
    logs_dir: Path
    data_dir: Path
    ui_assets_dir: Path


@dataclass(slots=True)
class FileRecord:
    path: str
    relative_path: str
    size: int
