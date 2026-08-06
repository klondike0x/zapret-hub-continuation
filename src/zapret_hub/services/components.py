from __future__ import annotations

import base64
import ctypes
import ipaddress
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError

from zapret_hub.domain import ComponentDefinition, ComponentState
from zapret_hub.runtime_env import is_packaged_runtime
from zapret_hub.services.github_network import GitHubNetworkClient, is_recoverable_github_error
from zapret_hub.services.logging_service import LoggingManager
from zapret_hub.services.service_catalog import prioritize_generals_for_services
from zapret_hub.services.service_rules import SERVICE_RULES
from zapret_hub.services.settings import SettingsManager
from zapret_hub.services.storage import StorageManager

# Hub ships / prefers the latest Flowseal Zapret release as the default binary.
PINNED_ZAPRET_VERSION = "1.10.0"
PINNED_ZAPRET_TAG = "1.10.0"
PINNED_ZAPRET_ZIP_URL = (
    "https://github.com/Flowseal/zapret-discord-youtube/releases/download/"
    f"{PINNED_ZAPRET_TAG}/zapret-discord-youtube-{PINNED_ZAPRET_VERSION}.zip"
)
PINNED_ZAPRET_ZIPBALL_URL = (
    f"https://codeload.github.com/Flowseal/zapret-discord-youtube/zip/refs/tags/{PINNED_ZAPRET_TAG}"
)
DISCORD_VOICE_UDP_PORTS = "3478-3497,19294-19344,50000-50100"
DISCORD_MEDIA_TCP_PORTS = "2053,2083,2087,2096,8443"

_VPN_PROCESS_PATTERNS = (
    "nekobox",
    "nekoray",
    "v2rayn",
    "xray",
    "xrayw",
    "sing-box",
    "singbox",
    "clash",
    "mihomo",
    "hiddify",
    "outline",
    "wireguard",
    "openvpn",
    "amnezia",
    "warp",
)

_VPN_ADAPTER_PATTERNS = (
    "wintun",
    "wireguard",
    "openvpn",
    "tap-",
    "tap_windows",
    "vpn",
    "v2ray",
    "xray",
    "nekobox",
    "nekoray",
    "sing-box",
    "clash",
    "mihomo",
    "tun",
)

_ZAPRET_DRIVER_SERVICE_NAMES = ("zapret", "WinDivert", "WinDivert14")
_TORRENT_PROCESS_NAMES = (
    "qbittorrent.exe",
    "qbittorrent",
    "transmission-qt.exe",
    "transmission.exe",
    "utorrent.exe",
    "bittorrent.exe",
    "deluge.exe",
    "aria2c.exe",
    "biglybt.exe",
    "vuze.exe",
    "tixati.exe",
    "webtorrent.exe",
)

_XBOX_DNS_URL = "https://xbox-dns.ru/"
_XBOX_DNS_FALLBACK_IPV4 = ("111.88.96.50", "111.88.96.51")
_XBOX_DNS_FALLBACK_IPV6 = ("2a00:ab00:1233:26::50", "2a00:ab00:1233:26::51")
_DNS_PROFILES: dict[str, dict[str, Any]] = {
    "dhcp": {"ipv4": [], "ipv6": [], "source": "system-dhcp"},
    "cloudflare": {
        "ipv4": ["1.1.1.1", "1.0.0.1"],
        "ipv6": ["2606:4700:4700::1111", "2606:4700:4700::1001"],
        "source": "cloudflare",
    },
    "adguard": {
        "ipv4": ["94.140.14.14", "94.140.15.15"],
        "ipv6": ["2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff"],
        "source": "adguard",
    },
    "google": {
        "ipv4": ["8.8.8.8", "8.8.4.4"],
        "ipv6": ["2001:4860:4860::8888", "2001:4860:4860::8844"],
        "source": "google",
    },
    "yandex": {
        "ipv4": ["77.88.8.8", "77.88.8.1"],
        "ipv6": ["2a02:6b8::feed:0ff", "2a02:6b8:0:1::feed:0ff"],
        "source": "yandex",
    },
}


class _WindowsJob:
    """Kill all assigned children when the UI process exits (incl. Task Manager End task)."""

    # PROCESS_SET_QUOTA | PROCESS_TERMINATE — enough for AssignProcessToJobObject
    _PROCESS_JOB_ACCESS = 0x0100 | 0x0001

    def __init__(self) -> None:
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.job = self.kernel32.CreateJobObjectW(None, None)
        if not self.job:
            return

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        JobObjectExtendedLimitInformation = 9

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        self.kernel32.SetInformationJobObject(
            self.job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )

    def assign_pid(self, pid: int) -> bool:
        if not self.job or not pid:
            return False
        handle = self.kernel32.OpenProcess(self._PROCESS_JOB_ACCESS, False, int(pid))
        if not handle:
            # Fallback: some environments still require a wider mask.
            handle = self.kernel32.OpenProcess(0x1F0FFF, False, int(pid))
        if not handle:
            return False
        try:
            ok = bool(self.kernel32.AssignProcessToJobObject(self.job, handle))
            return ok
        finally:
            self.kernel32.CloseHandle(handle)


class ProcessManager:
    def __init__(
        self,
        storage: StorageManager,
        logging: LoggingManager,
        settings: SettingsManager,
    ) -> None:
        self.storage = storage
        self.logging = logging
        self.settings = settings
        self._processes: dict[str, subprocess.Popen[Any]] = {}
        self._process_lock = threading.RLock()
        self._states: dict[str, ComponentState] = {}
        self._current_zapret_runtime: Path | None = None
        self._state_cache: list[ComponentState] = []
        self._state_cache_at = 0.0
        self._hub_runtime_token = secrets.token_urlsafe(24)
        self._log_streams: dict[str, Any] = {}
        self._diagnostic_runtime_override = False
        self._diagnostic_abort = threading.Event()
        self._diagnostic_token = 0
        self._image_running_cache: dict[str, tuple[float, bool]] = {}
        self._port_listening_cache: dict[tuple[str, int], tuple[float, bool]] = {}
        self._telegram_proxy_launch_info: dict[str, Any] | None = None
        self._github_recovery_profile: dict[str, str] | None = None
        self._component_releases_mem: dict[str, tuple[float, list[dict[str, str]]]] = {}
        self._zapret_runtime_lock = threading.RLock()
        self._job = _WindowsJob() if sys.platform.startswith("win") else None
        self.github = GitHubNetworkClient(logging, recovery_runner=self.with_github_connectivity_recovery)
        # Optional UI hook: (component_id, status, last_error) after optimistic starts fail.
        self._status_listener: Callable[[str, str, str], None] | None = None
        self._creationflags = 0
        self._startupinfo: subprocess.STARTUPINFO | None = None
        if sys.platform.startswith("win"):
            # No DETACHED_PROCESS — keep children in the same job tree so Task Manager
            # "End task" on Zapret Hub also kills winws / TG / VPN / backend workers.
            self._creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            self._startupinfo = startup
            self._repair_zapret_driver_paths_on_startup()

    def set_status_listener(self, listener: Callable[[str, str, str], None] | None) -> None:
        self._status_listener = listener

    def _emit_component_status(self, component_id: str, status: str, last_error: str = "") -> None:
        listener = self._status_listener
        if listener is None:
            return
        try:
            listener(str(component_id), str(status), str(last_error or ""))
        except Exception:
            pass

    def assign_pid_to_job(self, pid: int | None) -> bool:
        """Attach an external process (e.g. backend worker) to the UI kill-on-close job."""
        if not self._job or not pid:
            return False
        try:
            return bool(self._job.assign_pid(int(pid)))
        except Exception:
            return False

    def reap_orphaned_bypass_images(self) -> None:
        """Best-effort cleanup if a previous Hub was force-killed before job assign."""
        if not sys.platform.startswith("win"):
            return
        for image in (
            "winws.exe",
            "winws2.exe",
        ):
            try:
                if self._is_image_running(image):
                    self._kill_image(image)
            except Exception:
                pass

    def list_components(self) -> list[ComponentDefinition]:
        raw_items = self.storage.read_json(self.storage.paths.data_dir / "components.json", default=[])
        settings = self.settings.get()
        components = [ComponentDefinition(**item) for item in raw_items]
        for component in components:
            component.enabled = component.id in settings.enabled_component_ids
            component.autostart = component.id in settings.autostart_component_ids
        return components

    def list_zapret_generals(self) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []
        bundles = self._get_zapret_bundles(enabled_only=True, include_hidden_generals=True)
        selected_services = {str(item) for item in list(self.settings.get().selected_service_ids or [])}
        for bundle in bundles:
            bundle_id = bundle["id"]
            bundle_title = bundle["title"]
            root = bundle["path"]
            for script in sorted(root.glob("*.bat")):
                name = script.name.lower()
                if name.startswith("service"):
                    continue
                if bundle_id == "unified-general" and name == "general (ubisoft).bat" and "ubisoft" not in selected_services:
                    continue
                option_id = f"{bundle_id}|{script.name}"
                options.append(
                    {
                        "id": option_id,
                        "name": script.name,
                        "bundle": bundle_title,
                        "bundle_id": bundle_id,
                        "path": str(script),
                    }
                )
        return sorted(options, key=self._general_option_sort_key)

    def prompt_telegram_proxy_link(self) -> None:
        settings = self.settings.get()
        secret = (settings.tg_proxy_secret or "").strip().lower()
        if secret.startswith("dd") and len(secret) > 2:
            secret = secret[2:]
        if not secret:
            secret = secrets.token_hex(16)
            settings = self.settings.update(tg_proxy_secret=secret)
        signature = (
            f"{settings.tg_proxy_host}:{int(settings.tg_proxy_port)}:{secret}:"
            f"{settings.tg_proxy_dc_ip}:{settings.tg_proxy_cfproxy_enabled}:"
            f"{settings.tg_proxy_cfproxy_priority}:{settings.tg_proxy_cfproxy_domain}:"
            f"{settings.tg_proxy_fake_tls_domain}:{settings.tg_proxy_buf_kb}:{settings.tg_proxy_pool_size}"
        )
        self._ensure_telegram_and_open_proxy_link(
            host=settings.tg_proxy_host,
            port=int(settings.tg_proxy_port),
            secret=secret,
        )
        if signature != str(settings.tg_proxy_link_prompt_signature or ""):
            self.settings.update(tg_proxy_link_prompt_signature=signature)

    def consume_telegram_proxy_launch_info(self) -> dict[str, Any] | None:
        info = self._telegram_proxy_launch_info
        self._telegram_proxy_launch_info = None
        return dict(info) if isinstance(info, dict) else None

    def abort_diagnostics(self, *, kill_winws: bool = True) -> None:
        """Stop general/settings diagnostics immediately.

        Never kill a normal user-powered winws session. Only tear down the
        temporary diagnostic runtime (onboarding / general test).
        """
        self._diagnostic_token += 1
        self._diagnostic_abort.set()
        owned_by_diagnostics = bool(self._diagnostic_runtime_override)
        self._diagnostic_runtime_override = False
        if kill_winws and owned_by_diagnostics:
            try:
                self.stop_component("zapret")
            except Exception:
                pass
            try:
                self._kill_image("winws.exe")
            except Exception:
                pass
        self._invalidate_state_cache()

    def reset_diagnostic_abort(self) -> None:
        self._diagnostic_abort.clear()

    def diagnostics_aborted(self) -> bool:
        return self._diagnostic_abort.is_set()

    def prepare_user_power_start(self) -> None:
        """Cancel leftover diagnostics so an explicit power-on is not fought."""
        self._diagnostic_token += 1
        self._diagnostic_abort.set()
        self._diagnostic_runtime_override = False
        self._invalidate_state_cache()

    def list_states(self) -> list[ComponentState]:
        if self._state_cache and (time.time() - self._state_cache_at) < 0.25:
            return [
                ComponentState(
                    component_id=state.component_id,
                    status=state.status,
                    pid=state.pid,
                    last_error=state.last_error,
                )
                for state in self._state_cache
            ]
        states = self._compute_states()
        self._state_cache = [
            ComponentState(
                component_id=state.component_id,
                status=state.status,
                pid=state.pid,
                last_error=state.last_error,
            )
            for state in states
        ]
        self._state_cache_at = time.time()
        return states

    def _compute_states(self) -> list[ComponentState]:
        states: list[ComponentState] = []
        settings = self.settings.get()
        for component in self.list_components():
            state = self._states.get(component.id, ComponentState(component_id=component.id))
            if component.id == "zapret":
                # Prefer owned Popen — image scan cache can lag right after kill/start.
                owned = self._processes.get(component.id)
                if owned is not None and owned.poll() is None:
                    state.status = "running"
                    state.pid = owned.pid
                else:
                    if owned is not None:
                        self._processes.pop(component.id, None)
                    alive = self._is_image_running("winws.exe")
                    if alive:
                        state.status = "running"
                    elif str(getattr(state, "status", "") or "") == "error":
                        state.status = "error"
                    else:
                        state.status = "stopped"
                    state.pid = None
            elif component.id == "zapret2":
                owned = self._processes.get(component.id)
                if owned is not None and owned.poll() is None:
                    state.status = "running"
                    state.pid = owned.pid
                else:
                    if owned is not None:
                        self._processes.pop(component.id, None)
                    alive = self._is_image_running("winws2.exe")
                    # Never keep a stale optimistic "running" when the image is gone.
                    if alive:
                        state.status = "running"
                    elif str(getattr(state, "status", "") or "") == "error":
                        state.status = "error"
                    else:
                        state.status = "stopped"
                    state.pid = None
            elif component.id == "xbox-dns":
                dns_state = self._read_xbox_dns_state()
                state.status = "running" if bool(dns_state.get("active", False)) else "stopped"
                state.pid = None
                state.last_error = str(dns_state.get("last_error", "") or "")
            elif component.id == "tg-ws-proxy":
                # Prefer owned Popen — never pay a socket timeout while Hub owns the process.
                worker = self._processes.get(component.id)
                if worker is not None and worker.poll() is None:
                    state.status = "running"
                    state.pid = worker.pid
                elif self._is_port_listening(settings.tg_proxy_host, int(settings.tg_proxy_port)):
                    state.status = "running"
                    state.pid = None
                else:
                    state.status = "stopped"
                    state.pid = None
            else:
                process = self._processes.get(component.id)
                if process and process.poll() is None:
                    state.status = "running"
                    state.pid = process.pid
                else:
                    state.status = "stopped"
                    state.pid = None
            states.append(state)
        return states

    def _invalidate_state_cache(self) -> None:
        self._state_cache = []
        self._state_cache_at = 0.0
        self._port_listening_cache.clear()

    def stop_running_bypass_copies(self, runtime_id: str) -> None:
        """Find already-running copies of the selected bypass and stop them.

        Power-on always clears foreign/orphan instances first, then starts a
        Hub-owned process that list_states can track.
        """
        runtime_id = str(runtime_id or "").strip()
        if runtime_id == "zapret":
            owned = self._processes.get("zapret")
            owned_alive = owned is not None and owned.poll() is None
            image_alive = self._is_image_running("winws.exe")
            if not owned_alive and not image_alive:
                return
            if image_alive:
                self.logging.log("info", "Found running winws.exe; stopping before power-on")
            try:
                self.stop_component("zapret")
            except Exception:
                pass
            if self._is_image_running("winws.exe"):
                self._kill_image("winws.exe")
                self._wait_for_image_exit("winws.exe", attempts=8, delay=0.12)
            self._invalidate_state_cache()
            return
        if runtime_id == "zapret2":
            owned = self._processes.get("zapret2")
            owned_alive = owned is not None and owned.poll() is None
            image_alive = self._is_image_running("winws2.exe")
            if not owned_alive and not image_alive:
                return
            if image_alive:
                self.logging.log("info", "Found running winws2.exe; stopping before power-on")
            try:
                self.stop_component("zapret2")
            except Exception:
                pass
            if self._is_image_running("winws2.exe"):
                self._kill_image("winws2.exe")
                self._wait_for_image_exit("winws2.exe", attempts=8, delay=0.12)
            self._invalidate_state_cache()
            return
    def start_component(self, component_id: str) -> ComponentState:
        with self._process_lock:
            return self._start_component_unlocked(component_id)

    def _start_component_unlocked(self, component_id: str) -> ComponentState:
        component = next(item for item in self.list_components() if item.id == component_id)
        if component.id == "zapret":
            # Never let a stale Auto cutover flip Quick Access back after the user
            # already selected another mode.
            if not self._diagnostic_runtime_override:
                selected = str(self.settings.get().selected_runtime_mode or "zapret")
                if selected not in {"zapret", ""}:
                    state = ComponentState(
                        component_id=component_id,
                        status="stopped",
                        last_error="runtime_mode_mismatch",
                    )
                    self._states[component_id] = state
                    self.logging.log(
                        "info",
                        "Skipping zapret start — selected runtime is not zapret",
                        selected=selected,
                    )
                    return state
            self.stop_component("zapret2")
            state = self._start_zapret(component_id)
            self._invalidate_state_cache()
            return state
        if component.id == "zapret2":
            if not self._diagnostic_runtime_override:
                selected = str(self.settings.get().selected_runtime_mode or "zapret")
                if selected != "zapret2":
                    state = ComponentState(
                        component_id=component_id,
                        status="stopped",
                        last_error="runtime_mode_mismatch",
                    )
                    self._states[component_id] = state
                    self.logging.log(
                        "info",
                        "Skipping zapret2 start — selected runtime is not zapret2",
                        selected=selected,
                    )
                    return state
            self.stop_component("zapret")
            state = self._start_zapret2(component_id)
            self._invalidate_state_cache()
            return state
        if component.id == "xbox-dns":
            state = self._start_xbox_dns(component_id)
            self._invalidate_state_cache()
            return state
        if component.id == "tg-ws-proxy":
            state = self._start_tg_ws_proxy(component_id)
            self._invalidate_state_cache()
            return state
        current = self._processes.get(component_id)
        if current and current.poll() is None:
            return self._states.get(component_id, ComponentState(component_id=component_id, status="running", pid=current.pid))

        process = subprocess.Popen(
            component.command,
            text=True,
            errors="replace",
            creationflags=self._creationflags,
            startupinfo=self._startupinfo,
        )
        if self._job:
            self._job.assign_pid(process.pid)
        state = ComponentState(component_id=component_id, status="running", pid=process.pid)
        self._processes[component_id] = process
        self._states[component_id] = state
        self.logging.log("info", "Component started", component_id=component_id, pid=process.pid)
        self._invalidate_state_cache()
        return state

    def stop_component(self, component_id: str) -> ComponentState:
        with self._process_lock:
            return self._stop_component_unlocked(component_id)

    def _stop_component_unlocked(self, component_id: str) -> ComponentState:
        state = self._states.get(component_id, ComponentState(component_id=component_id))

        if component_id == "zapret":
            active_runtime = self._current_zapret_runtime
            self._force_stop_zapret_runtime()
            self._close_source_log_stream("zapret")
            self._processes.pop(component_id, None)
            if active_runtime is not None:
                self._reset_active_runtime_dir(active_runtime)
            state.status = "stopped" if not self._is_image_running("winws.exe") else "running"
            state.pid = None
            if state.status != "stopped":
                state.last_error = "Failed to stop winws.exe"
            self._states[component_id] = state
            self.logging.log("info", "Zapret stopped")
            self._invalidate_state_cache()
            return state

        if component_id == "zapret2":
            process = self._processes.get(component_id)
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
            if process and process.pid:
                self._run_quiet(["taskkill", "/PID", str(process.pid), "/F", "/T"])
            self._processes.pop(component_id, None)
            self._kill_image("winws2.exe")
            self._close_source_log_stream(component_id)
            state.status = "stopped" if not self._is_image_running("winws2.exe") else "running"
            state.pid = None
            state.last_error = "Failed to stop winws2.exe" if state.status != "stopped" else ""
            self._states[component_id] = state
            self.logging.log("info", "Zapret2 stopped")
            self._invalidate_state_cache()
            return state
        if component_id == "xbox-dns":
            state = self._stop_xbox_dns(component_id)
            self._invalidate_state_cache()
            return state
        if component_id == "tg-ws-proxy":
            settings = self.settings.get()
            self._kill_image("TgWsProxy_windows.exe")
            self._close_source_log_stream("tg-ws-proxy")
            still_listening = self._is_port_listening(settings.tg_proxy_host, int(settings.tg_proxy_port))
            state.status = "running" if still_listening else "stopped"
            state.pid = None
            if still_listening:
                state.last_error = "Failed to stop TgWsProxy_windows.exe"
            self._states[component_id] = state
            self.logging.log("info", "TG WS Proxy stopped")
            self._invalidate_state_cache()
            return state
        process = self._processes.get(component_id)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        self._processes.pop(component_id, None)
        state.status = "stopped"
        state.pid = None
        self._states[component_id] = state
        self.logging.log("info", "Component stopped", component_id=component_id)
        self._close_source_log_stream(component_id)
        self._invalidate_state_cache()
        return state

    def _bypass_ids_allowed_for_autostart(self) -> set[str]:
        """Only the selected Quick Access mode may autostart as a bypass."""
        mode = str(self.settings.get().selected_runtime_mode or "zapret")
        if mode == "none":
            return set()
        if mode in {"zapret", "zapret2"}:
            return {mode}
        return {"zapret"}

    def _should_autostart_component(self, component_id: str, *, require_autostart_flag: bool) -> bool:
        components = {item.id: item for item in self.list_components()}
        component = components.get(component_id)
        if component is None or not component.enabled:
            return False
        if require_autostart_flag and not component.autostart:
            return False
        # Bypass duo is mutually exclusive — never start Zapret2 because it stayed "enabled"
        # while the user selected Zapret.
        if component_id in {"zapret", "zapret2"}:
            return component_id in self._bypass_ids_allowed_for_autostart()
        return True

    def start_enabled_components(self) -> list[ComponentState]:
        started = []
        for component in self.list_components():
            if not self._should_autostart_component(component.id, require_autostart_flag=False):
                continue
            try:
                started.append(self.start_component(component.id))
            except Exception as error:
                state = ComponentState(
                    component_id=component.id,
                    status="error",
                    last_error=str(error),
                )
                self._states[component.id] = state
                self.logging.log("error", "Enabled component failed to start", component_id=component.id, error=str(error))
                started.append(state)
        return started

    def start_autostart_components(self) -> list[ComponentState]:
        started = []
        for component in self.list_components():
            if not self._should_autostart_component(component.id, require_autostart_flag=True):
                continue
            try:
                started.append(self.start_component(component.id))
            except Exception as error:
                state = ComponentState(
                    component_id=component.id,
                    status="error",
                    last_error=str(error),
                )
                self._states[component.id] = state
                self.logging.log("error", "Autostart component failed to start", component_id=component.id, error=str(error))
                started.append(state)
        return started

    def stop_all(self) -> list[ComponentState]:
        stopped = [self.stop_component(component.id) for component in self.list_components()]
        self._cleanup_merged_runtime()
        return stopped

    def toggle_component_enabled(self, component_id: str) -> ComponentDefinition:
        components = self.list_components()
        target = next(component for component in components if component.id == component_id)
        target.enabled = not target.enabled
        enabled_ids = sorted(component.id for component in components if component.enabled)
        self.settings.update(enabled_component_ids=enabled_ids)
        if target.id == "xbox-dns":
            if target.enabled:
                if self._xbox_dns_should_apply_now():
                    self.start_component(component_id)
                else:
                    self._prepare_xbox_dns(component_id)
            else:
                self.stop_component(component_id)
        elif target.enabled:
            # Service toggles must behave the same as the component buttons when
            # the master switch is already on. Previously only Xbox DNS started
            # immediately, leaving Zapret/VPN in a misleading partial state.
            if any(item.status == "running" for item in self._compute_states()):
                self.start_component(component_id)
        elif not target.enabled:
            self.stop_component(component_id)
        self.logging.log("info", "Component enabled state changed", component_id=component_id, enabled=target.enabled)
        self._invalidate_state_cache()
        return target

    def _xbox_dns_state_path(self) -> Path:
        return self.storage.paths.data_dir / "xbox_dns_state.json"

    def _read_xbox_dns_state(self) -> dict[str, Any]:
        raw = self.storage.read_json(self._xbox_dns_state_path(), default={}) or {}
        return raw if isinstance(raw, dict) else {}

    def _write_xbox_dns_state(self, state: dict[str, Any]) -> None:
        self.storage.write_json(self._xbox_dns_state_path(), state)

    def _xbox_dns_should_apply_now(self) -> bool:
        for state in self._compute_states():
            if state.component_id == "xbox-dns":
                continue
            if state.status == "running":
                return True
        return False

    def _parse_xbox_dns_servers(self, html: str) -> dict[str, list[str]]:
        ipv4: list[str] = []
        ipv6: list[str] = []
        seen: set[str] = set()
        for token in re.findall(r"[0-9A-Fa-f:.]{3,}", html or ""):
            candidate = token.strip().strip(".,;:()[]{}<>`'\"")
            if not candidate or candidate in seen:
                continue
            try:
                parsed = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if parsed.is_loopback or parsed.is_unspecified:
                continue
            seen.add(candidate)
            if parsed.version == 4:
                ipv4.append(candidate)
            elif parsed.version == 6:
                ipv6.append(candidate)
        return {"ipv4": ipv4[:2], "ipv6": ipv6[:2]}

    def _fetch_xbox_dns_servers(self) -> dict[str, Any]:
        try:
            request = urllib.request.Request(
                _XBOX_DNS_URL,
                headers={"User-Agent": "Zapret-Hub/2.0 xbox-dns"},
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                html = response.read().decode("utf-8", errors="ignore")
            parsed = self._parse_xbox_dns_servers(html)
            if parsed["ipv4"] and parsed["ipv6"]:
                return {**parsed, "source": "remote"}
            raise ValueError("Xbox DNS page did not contain both IPv4 and IPv6 DNS addresses")
        except Exception as error:
            self.logging.log("warning", "Xbox DNS remote fetch failed, using fallback", component_id="xbox-dns", error=str(error))
            return {
                "ipv4": list(_XBOX_DNS_FALLBACK_IPV4),
                "ipv6": list(_XBOX_DNS_FALLBACK_IPV6),
                "source": "fallback",
                "last_error": str(error),
            }

    def _selected_dns_servers(self) -> dict[str, Any]:
        profile = str(getattr(self.settings.get(), "dns_profile", "xbox") or "xbox")
        if profile == "xbox":
            return {**self._fetch_xbox_dns_servers(), "profile": "xbox"}
        selected = dict(_DNS_PROFILES.get(profile, _DNS_PROFILES["dhcp"]))
        selected["profile"] = profile if profile in _DNS_PROFILES else "dhcp"
        return selected

    def _snapshot_windows_dns(self) -> list[dict[str, Any]]:
        script = r"""
$rows = @()
function Test-HubIgnoredAdapter($adapter) {
  $name = (([string]$adapter.Name) + ' ' + ([string]$adapter.InterfaceDescription)).ToLowerInvariant()
  if ($name.Contains('loopback')) { return $true }
  if ($name.Contains('wintun')) { return $true }
  if ($name.Contains('wireguard')) { return $true }
  if ($name.Contains('openvpn')) { return $true }
  if ($name.Contains('tap')) { return $true }
  if ($name.Contains('vpn')) { return $true }
  if ($name.Contains('v2ray')) { return $true }
  if ($name.Contains('xray')) { return $true }
  if ($name.Contains('sing-box')) { return $true }
  if ($name.Contains('clash')) { return $true }
  if ($name.Contains('tun')) { return $true }
  return $false
}
function Get-HubRegistryDns($guid, $family) {
  if (-not $guid) { return "" }
  $root = if ($family -eq "ipv6") { "Tcpip6" } else { "Tcpip" }
  $path = "HKLM:\SYSTEM\CurrentControlSet\Services\$root\Parameters\Interfaces\$guid"
  try {
    $value = (Get-ItemProperty -LiteralPath $path -Name NameServer -ErrorAction Stop).NameServer
    return [string]$value
  } catch {
    return ""
  }
}
function Split-HubDnsList($value) {
  @([string]$value -split "[,\s]+" | Where-Object { [string]$_ -ne "" })
}
$adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' -and $_.HardwareInterface -and -not (Test-HubIgnoredAdapter $_) })
if ($adapters.Count -eq 0) {
  $adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq 'Up' -and -not (Test-HubIgnoredAdapter $_) })
}
$adapters | ForEach-Object {
  $ifIndex = [int]$_.ifIndex
  $alias = [string]$_.Name
  $guid = [string]$_.InterfaceGuid
  $v4 = Get-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue
  $v6 = Get-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily IPv6 -ErrorAction SilentlyContinue
  $v4Manual = Get-HubRegistryDns $guid "ipv4"
  $v6Manual = Get-HubRegistryDns $guid "ipv6"
  $rows += [pscustomobject]@{
    interface_index = $ifIndex
    interface_alias = $alias
    interface_guid = $guid
    ipv4 = if ($v4Manual) { @(Split-HubDnsList $v4Manual) } else { @($v4.ServerAddresses) }
    ipv6 = if ($v6Manual) { @(Split-HubDnsList $v6Manual) } else { @() }
    ipv4_manual = [bool]$v4Manual
    ipv6_manual = [bool]$v6Manual
  }
}
if ($rows.Count -eq 0) {
  $dnsRows = @(Get-DnsClientServerAddress -ErrorAction SilentlyContinue | Where-Object { $_.ServerAddresses.Count -gt 0 })
  $groups = @{}
  foreach ($dns in $dnsRows) {
    $ifIndex = [int]$dns.InterfaceIndex
    $alias = [string]$dns.InterfaceAlias
    $probe = [pscustomobject]@{ Name = $alias; InterfaceDescription = $alias }
    if ($ifIndex -le 0 -or (Test-HubIgnoredAdapter $probe)) { continue }
    if (-not $groups.ContainsKey($ifIndex)) {
      $adapter = Get-NetAdapter -InterfaceIndex $ifIndex -ErrorAction SilentlyContinue
      $guid = if ($adapter) { [string]$adapter.InterfaceGuid } else { "" }
      $v4Manual = Get-HubRegistryDns $guid "ipv4"
      $v6Manual = Get-HubRegistryDns $guid "ipv6"
      $groups[$ifIndex] = [pscustomobject]@{
        interface_index = $ifIndex
        interface_alias = $alias
        interface_guid = $guid
        ipv4 = @()
        ipv6 = @()
        ipv4_manual = [bool]$v4Manual
        ipv6_manual = [bool]$v6Manual
      }
      if ($v4Manual) { $groups[$ifIndex].ipv4 = @(Split-HubDnsList $v4Manual) }
      if ($v6Manual) { $groups[$ifIndex].ipv6 = @(Split-HubDnsList $v6Manual) }
    }
    if ([string]$dns.AddressFamily -eq 'IPv4' -and -not $groups[$ifIndex].ipv4_manual) {
      $groups[$ifIndex].ipv4 = @($dns.ServerAddresses)
    }
    if ([string]$dns.AddressFamily -eq 'IPv6' -and -not $groups[$ifIndex].ipv6_manual) {
      $groups[$ifIndex].ipv6 = @($dns.ServerAddresses)
    }
  }
  foreach ($entry in $groups.Values) {
    $rows += $entry
  }
}
@($rows) | ConvertTo-Json -Compress -Depth 4
"""
        raw = self._run_powershell_json(script)
        if not raw:
            return []
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return []
        adapters: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            alias = str(item.get("interface_alias", "") or "").strip()
            if not alias:
                continue
            adapters.append(
                {
                    "interface_index": int(item.get("interface_index", 0) or 0),
                    "interface_alias": alias,
                    "interface_guid": str(item.get("interface_guid", "") or "").strip(),
                    "ipv4": [str(value) for value in self._ensure_list(item.get("ipv4", [])) if str(value).strip()],
                    "ipv6": [str(value) for value in self._ensure_list(item.get("ipv6", [])) if str(value).strip()],
                    "ipv4_manual": bool(item.get("ipv4_manual", False)),
                    "ipv6_manual": bool(item.get("ipv6_manual", False)),
                }
            )
        return adapters

    def _prepare_xbox_dns(self, component_id: str = "xbox-dns") -> ComponentState:
        state_payload = self._read_xbox_dns_state()
        previous_adapters = state_payload.get("previous_adapters", [])
        if not bool(state_payload.get("active", False)):
            previous_adapters = self._snapshot_windows_dns()
        elif not isinstance(previous_adapters, list) or not previous_adapters:
            previous_adapters = self._snapshot_windows_dns()
        servers = self._selected_dns_servers()
        new_payload = dict(state_payload)
        new_payload.update(
            {
                "active": False,
                "previous_adapters": previous_adapters,
                "servers": servers,
                "last_error": "",
                "prepared_at": datetime.utcnow().isoformat(),
            }
        )
        self._write_xbox_dns_state(new_payload)
        state = ComponentState(component_id=component_id, status="stopped", pid=None, last_error="")
        self._states[component_id] = state
        self._invalidate_state_cache()
        return state

    def _ensure_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [value]

    def _apply_windows_dns(self, adapters: list[dict[str, Any]], ipv4: list[str], ipv6: list[str]) -> None:
        payload = json.dumps({"adapters": adapters, "ipv4": ipv4, "ipv6": ipv6}, ensure_ascii=False)
        script = """
$payload = @'
__PAYLOAD__
'@ | ConvertFrom-Json
function Clear-HubRegistryDns($guid, $family) {
  if (-not $guid) { return }
  $root = if ($family -eq "ipv6") { "Tcpip6" } else { "Tcpip" }
  $path = "HKLM:\SYSTEM\CurrentControlSet\Services\$root\Parameters\Interfaces\$guid"
  if (Test-Path -LiteralPath $path) {
    try { Set-ItemProperty -LiteralPath $path -Name NameServer -Value "" -ErrorAction Stop } catch {}
  }
}
function Set-HubDnsServers($ifIndex, $guid, $ipv4, $ipv6) {
  $serverList = @(@($ipv4) + @($ipv6) | Where-Object { [string]$_ -ne '' })
  if ($ifIndex -le 0) { return }
  try {
    if ($serverList.Count -gt 0) {
      Set-DnsClientServerAddress -InterfaceIndex $ifIndex -ServerAddresses $serverList -ErrorAction Stop | Out-Null
    } else {
      Set-DnsClientServerAddress -InterfaceIndex $ifIndex -ResetServerAddresses -ErrorAction Stop | Out-Null
    }
  } catch {
    throw $_
  }
}
foreach ($adapter in @($payload.adapters)) {
  $ifIndex = [int]$adapter.interface_index
  if ($ifIndex -le 0) { continue }
  $guid = [string]$adapter.interface_guid
  Set-HubDnsServers $ifIndex $guid @($payload.ipv4) @($payload.ipv6)
}
""".replace("__PAYLOAD__", payload)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=self._startupinfo,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "Failed to apply DNS.").strip())

    def _restore_windows_dns(self, adapters: list[dict[str, Any]]) -> None:
        payload = json.dumps({"adapters": adapters}, ensure_ascii=False)
        script = """
$payload = @'
__PAYLOAD__
'@ | ConvertFrom-Json
function Clear-HubRegistryDns($guid, $family) {
  if (-not $guid) { return }
  $root = if ($family -eq "ipv6") { "Tcpip6" } else { "Tcpip" }
  $path = "HKLM:\SYSTEM\CurrentControlSet\Services\$root\Parameters\Interfaces\$guid"
  if (Test-Path -LiteralPath $path) {
    try { Set-ItemProperty -LiteralPath $path -Name NameServer -Value "" -ErrorAction Stop } catch {}
  }
}
function Reset-HubDnsServers($ifIndex, $guid) {
  if ($ifIndex -le 0) { return }
  try {
    Set-DnsClientServerAddress -InterfaceIndex $ifIndex -ResetServerAddresses -ErrorAction Stop | Out-Null
  } catch {
    throw $_
  }
  Clear-HubRegistryDns $guid "ipv4"
  Clear-HubRegistryDns $guid "ipv6"
}
function Set-HubDnsServers($ifIndex, $guid, $ipv4, $ipv6) {
  $serverList = @(@($ipv4) + @($ipv6) | Where-Object { [string]$_ -ne '' })
  if ($ifIndex -le 0) { return }
  if ($serverList.Count -eq 0) {
    Reset-HubDnsServers $ifIndex $guid
    return
  }
  try {
    Set-DnsClientServerAddress -InterfaceIndex $ifIndex -ServerAddresses $serverList -ErrorAction Stop | Out-Null
  } catch {
    throw $_
  }
}
foreach ($adapter in @($payload.adapters)) {
  $ifIndex = [int]$adapter.interface_index
  if ($ifIndex -le 0) { continue }
  $guid = [string]$adapter.interface_guid
  $ipv4Manual = if ($null -ne $adapter.ipv4_manual) { [bool]$adapter.ipv4_manual } else { @($adapter.ipv4).Count -gt 0 }
  $ipv6Manual = if ($null -ne $adapter.ipv6_manual) { [bool]$adapter.ipv6_manual } else { @($adapter.ipv6).Count -gt 0 }
  if (-not $ipv4Manual -and -not $ipv6Manual) {
    Reset-HubDnsServers $ifIndex $guid
    continue
  }
  $restoreV4 = if ($ipv4Manual) { @($adapter.ipv4) } else { @() }
  $restoreV6 = if ($ipv6Manual) { @($adapter.ipv6) } else { @() }
  Set-HubDnsServers $ifIndex $guid $restoreV4 $restoreV6
}
""".replace("__PAYLOAD__", payload)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=self._startupinfo,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "Failed to restore DNS.").strip())

    def _start_xbox_dns(self, component_id: str = "xbox-dns") -> ComponentState:
        state_payload = self._read_xbox_dns_state()
        was_active = bool(state_payload.get("active", False))
        previous_adapters = state_payload.get("previous_adapters", [])
        if not was_active and not state_payload.get("prepared_at"):
            previous_adapters = self._snapshot_windows_dns()
        elif not isinstance(previous_adapters, list) or not previous_adapters:
            previous_adapters = self._snapshot_windows_dns()
        if not isinstance(previous_adapters, list):
            previous_adapters = []
        if not previous_adapters:
            state = ComponentState(component_id=component_id, status="error", last_error="Failed to read current Windows DNS settings.")
            self._states[component_id] = state
            self._write_xbox_dns_state({"active": False, "last_error": state.last_error})
            return state
        servers = self._selected_dns_servers()
        try:
            self._apply_windows_dns(previous_adapters, list(servers.get("ipv4", []) or []), list(servers.get("ipv6", []) or []))
        except Exception as error:
            if not was_active:
                try:
                    self._restore_windows_dns(previous_adapters)
                except Exception:
                    pass
            message = str(error)
            state = ComponentState(component_id=component_id, status="error", last_error=message)
            self._states[component_id] = state
            self._write_xbox_dns_state(
                {
                    "active": was_active,
                    "previous_adapters": previous_adapters if was_active else [],
                    "servers": servers,
                    "last_error": message,
                    "updated_at": datetime.utcnow().isoformat(),
                }
            )
            self.logging.log("error", "Xbox DNS failed to apply", component_id=component_id, error=message)
            return state
        self._write_xbox_dns_state(
            {
                "active": True,
                "previous_adapters": previous_adapters,
                "servers": servers,
                "last_error": "",
                "updated_at": datetime.utcnow().isoformat(),
            }
        )
        state = ComponentState(component_id=component_id, status="running", pid=None, last_error="")
        self._states[component_id] = state
        self.logging.log("info", "DNS profile applied", component_id=component_id, source=str(servers.get("source", "")))
        return state

    def _stop_xbox_dns(self, component_id: str = "xbox-dns") -> ComponentState:
        state_payload = self._read_xbox_dns_state()
        previous_adapters = state_payload.get("previous_adapters", [])
        if not bool(state_payload.get("active", False)):
            state = ComponentState(component_id=component_id, status="stopped", pid=None, last_error="")
            self._states[component_id] = state
            return state
        if not isinstance(previous_adapters, list) or not previous_adapters:
            message = "No saved DNS snapshot to restore."
            state = ComponentState(component_id=component_id, status="error", last_error=message)
            self._states[component_id] = state
            self._write_xbox_dns_state({**state_payload, "active": True, "last_error": message})
            return state
        try:
            self._restore_windows_dns(previous_adapters)
        except Exception as error:
            message = str(error)
            state = ComponentState(component_id=component_id, status="error", last_error=message)
            self._states[component_id] = state
            self._write_xbox_dns_state({**state_payload, "active": True, "last_error": message})
            self.logging.log("error", "Xbox DNS failed to restore", component_id=component_id, error=message)
            return state
        new_payload = dict(state_payload)
        new_payload["active"] = False
        new_payload["last_error"] = ""
        new_payload["restored_at"] = datetime.utcnow().isoformat()
        self._write_xbox_dns_state(new_payload)
        state = ComponentState(component_id=component_id, status="stopped", pid=None, last_error="")
        self._states[component_id] = state
        self.logging.log("info", "Xbox DNS restored previous DNS settings", component_id=component_id)
        return state

    def refresh_xbox_dns(self) -> dict[str, Any]:
        settings = self.settings.get()
        enabled = "xbox-dns" in {str(item) for item in list(settings.enabled_component_ids or [])}
        state_payload = self._read_xbox_dns_state()
        servers = self._selected_dns_servers()
        if bool(state_payload.get("active", False)) or (enabled and self._xbox_dns_should_apply_now()):
            state = self._start_xbox_dns("xbox-dns")
            return {"status": state.status, "error": state.last_error, "servers": self._read_xbox_dns_state().get("servers", servers)}
        if enabled:
            self._prepare_xbox_dns("xbox-dns")
            state_payload = self._read_xbox_dns_state()
        state_payload.update({"servers": servers, "last_error": "", "updated_at": datetime.utcnow().isoformat()})
        self._write_xbox_dns_state(state_payload)
        return {"status": "stopped", "error": "", "servers": servers}

    def select_dns_profile(self, profile: str) -> dict[str, Any]:
        normalized = profile if profile in {"dhcp", "xbox", "cloudflare", "adguard", "google", "yandex"} else "xbox"
        self.settings.update(dns_profile=normalized)
        state_payload = self._read_xbox_dns_state()
        if bool(state_payload.get("active", False)):
            state = self._start_xbox_dns("xbox-dns")
            return {"status": state.status, "profile": normalized, "error": state.last_error}
        self._prepare_xbox_dns("xbox-dns")
        return {"status": "prepared", "profile": normalized}

    def toggle_component_autostart(self, component_id: str) -> ComponentDefinition:
        components = self.list_components()
        target = next(component for component in components if component.id == component_id)
        target.autostart = not target.autostart
        autostart_ids = sorted(component.id for component in components if component.autostart)
        self.settings.update(autostart_component_ids=autostart_ids)
        self.logging.log("info", "Component autostart state changed", component_id=component_id, autostart=target.autostart)
        return target

    def _start_zapret(self, component_id: str) -> ComponentState:
        if self._diagnostic_runtime_override and self._diagnostic_abort.is_set():
            state = ComponentState(
                component_id=component_id,
                status="stopped",
                last_error="cancelled",
            )
            self._states[component_id] = state
            return state
        if not self._diagnostic_runtime_override:
            # Explicit user start — don't stay blocked by a stale diagnostic abort.
            self._diagnostic_abort.clear()
        # Never rewrite Quick Access mode here — Auto/start must not flip Zapret↔Zapret2.
        # Always clear existing winws copies, then start a Hub-owned instance.
        # When already running, prefer seamless cutover (stage B → start new → kill old).
        if self._is_image_running("winws.exe") and not self._diagnostic_runtime_override:
            try:
                return self.seamless_restart_zapret()
            except Exception as error:
                self.logging.log("warning", "Seamless zapret restart failed, falling back", error=str(error))
        if self._is_image_running("winws.exe"):
            self.logging.log("info", "Stopping existing winws copies before zapret start")
        self.stop_component(component_id)
        if not self._purge_stale_zapret_runtime():
            state = ComponentState(
                component_id=component_id,
                status="error",
                last_error="Не удалось выгрузить прежний драйвер WinDivert Zapret Hub. Перезапустите Windows и повторите попытку.",
            )
            self._states[component_id] = state
            self.logging.log("error", "Zapret start blocked by stale WinDivert runtime")
            return state
        selected_option = self._resolve_selected_general_option()
        if selected_option is None:
            state = ComponentState(component_id=component_id, status="error", last_error="No general script found.")
            self._states[component_id] = state
            return state

        selected_script = Path(selected_option["path"])
        selected_bundle_root = Path(selected_script).parent
        stable_driver_path: Path | None = None
        try:
            stable_driver_path = self._ensure_stable_windivert_driver(selected_bundle_root / "bin")
        except Exception:
            stable_driver_path = None
        self._repair_windivert_image_paths(preferred_driver_path=stable_driver_path)
        self._repair_stale_zapret_driver_paths(selected_bundle_root, preferred_driver_path=stable_driver_path)
        active_root: Path | None = None
        process: subprocess.Popen[Any] | None = None
        try:
            active_root = self._prepare_active_zapret_runtime(
                selected_bundle_root=selected_bundle_root,
                selected_bundle_id=selected_option["bundle_id"],
                selected_script_name=selected_script.name,
            )
            self._current_zapret_runtime = active_root
            self._apply_zapret_runtime_switches(active_root)
            active_script = active_root / selected_script.name
            self._ensure_zapret_user_lists(active_root / "lists")
            self._materialize_visible_merged_runtime(active_root)
            bin_dir = active_root / "bin"
            lists_dir = active_root / "lists"
            if not active_script.exists():
                raise FileNotFoundError(f"Selected general was not materialized: {active_script}")
            if not (bin_dir / "winws.exe").exists():
                raise FileNotFoundError(f"winws.exe was not materialized: {bin_dir / 'winws.exe'}")
            stable_driver_path = self._ensure_stable_windivert_driver(bin_dir)
            winws_command = self._extract_winws_command(active_script, bin_dir=bin_dir, lists_dir=lists_dir)
            if winws_command:
                winws_command[0] = str(stable_driver_path.parent / "winws.exe")
            allow_service_command_extensions = str(selected_option.get("bundle_id", "")) == "base"
            winws_command = self._apply_selected_service_command_extensions(
                winws_command,
                lists_dir=lists_dir,
                bin_dir=bin_dir,
                enabled=allow_service_command_extensions,
            )
            winws_command = self._apply_vpn_priority_to_command(winws_command, lists_dir=lists_dir)
            winws_command = self._apply_udp_port_exclusions_to_command(winws_command)
            if not winws_command:
                state = ComponentState(
                    component_id=component_id,
                    status="error",
                    last_error="Failed to parse winws command from selected general file.",
                )
                self._states[component_id] = state
                self.logging.log("error", "Zapret command parse failed", script=str(active_script))
                return state
            self._repair_windivert_image_paths(active_root, preferred_driver_path=stable_driver_path)
            process = subprocess.Popen(
                winws_command,
                cwd=str(stable_driver_path.parent),
                creationflags=self._creationflags,
                startupinfo=self._startupinfo,
                stdout=self._open_source_log_stream("zapret"),
                stderr=subprocess.STDOUT,
            )
            if self._job:
                self._job.assign_pid(process.pid)
            self._processes[component_id] = process
            # Optimistic: process spawned → report running immediately; confirm in background.
            if process.poll() is not None:
                log_hint = self._recent_source_log_error("zapret")
                error_message = log_hint or "winws did not start. Run app as Administrator and check antivirus exclusions for WinDivert."
                state = ComponentState(
                    component_id=component_id,
                    status="error",
                    last_error=error_message,
                )
                self.logging.log("error", "Zapret failed to start", script=str(active_script), error=error_message)
            else:
                # Do NOT seed a positive image-running cache here: a dying winws can
                # leave UI/"on" lit via a 1.5s True cache after poll() flips.
                self._image_running_cache.pop("winws.exe", None)
                state = ComponentState(component_id=component_id, status="running", pid=process.pid)
                self._states[component_id] = state
                self._invalidate_state_cache()
                self.logging.log("info", "Zapret started", script=str(active_script), command=winws_command[0])
                self._schedule_bypass_start_confirm(
                    component_id,
                    process,
                    image_name="winws.exe",
                    active_root=active_root,
                    stable_driver_path=stable_driver_path,
                )
                return state
        except OSError as error:
            if getattr(error, "winerror", 0) == 740:
                state = ComponentState(
                    component_id=component_id,
                    status="error",
                    last_error="Administrator rights are required for winws/WinDivert.",
                )
                self.logging.log("error", "Zapret start failed: admin required")
            else:
                state = ComponentState(component_id=component_id, status="error", last_error=str(error))
                self.logging.log("error", "Zapret start failed", error=str(error))
        except shutil.Error as error:
            state = ComponentState(component_id=component_id, status="error", last_error=str(error))
            self.logging.log("error", "Zapret runtime build failed", error=str(error))
        except Exception as error:
            state = ComponentState(component_id=component_id, status="error", last_error=str(error))
            self.logging.log("error", "Zapret start crashed", error=str(error))
        if state.status != "running":
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
            self._force_stop_zapret_runtime()
            if active_root is not None:
                self._reset_active_runtime_dir(active_root)
            self._current_zapret_runtime = None
        self._states[component_id] = state
        return state

    def _start_zapret2(self, component_id: str) -> ComponentState:
        if self._is_image_running("winws2.exe"):
            self.logging.log("info", "Stopping existing winws2 copies before zapret2 start")
        self.stop_component(component_id)
        if not self._purge_stale_zapret_runtime():
            state = ComponentState(
                component_id=component_id,
                status="error",
                last_error="Не удалось выгрузить прежний драйвер WinDivert Zapret Hub. Перезапустите Windows и повторите попытку.",
            )
            self._states[component_id] = state
            self.logging.log("error", "Zapret2 start blocked by stale WinDivert runtime")
            return state
        try:
            runtime_root = self._ensure_zapret2_runtime()
            winws2_path = self._find_zapret2_winws(runtime_root)
            if winws2_path is None:
                raise FileNotFoundError("winws2.exe was not found in the Zapret2 runtime.")
            command = self._build_zapret2_command(winws2_path, runtime_root)
            try:
                from zapret_hub.services.orchestrator import zapret2_hub

                zapret2_hub.sanitize_classic_discord_pollution(Path(self.storage.paths.configs_dir))
                zapret2_hub.sanitize_zapret2_discord_ipset(
                    Path(self.storage.paths.configs_dir),
                    runtime_dir=Path(self.storage.paths.runtime_dir),
                )
            except Exception:
                pass
            process = subprocess.Popen(
                command,
                # winws2 resolves cygwin1.dll / WinDivert next to the exe
                cwd=str(winws2_path.parent),
                creationflags=self._creationflags,
                startupinfo=self._startupinfo,
                stdout=self._open_source_log_stream(component_id),
                stderr=subprocess.STDOUT,
            )
            if self._job:
                self._job.assign_pid(process.pid)
            self._processes[component_id] = process
            if process.poll() is not None:
                log_hint = self._recent_source_log_error(component_id)
                self._close_source_log_stream(component_id)
                state = ComponentState(
                    component_id=component_id,
                    status="error",
                    last_error=log_hint or "winws2 did not start. Run app as Administrator and check WinDivert access.",
                )
                self.logging.log("error", "Zapret2 failed to start", error=state.last_error)
            else:
                # Never cache "running" before confirm — false "on" with no winws2.
                self._image_running_cache.pop("winws2.exe", None)
                state = ComponentState(component_id=component_id, status="running", pid=process.pid)
                self._states[component_id] = state
                self._invalidate_state_cache()
                self.logging.log("info", "Zapret2 started", command=str(winws2_path))
                self._schedule_bypass_start_confirm(component_id, process, image_name="winws2.exe")
                return state
        except OSError as error:
            if getattr(error, "winerror", 0) == 740:
                state = ComponentState(
                    component_id=component_id,
                    status="error",
                    last_error="Administrator rights are required for winws2/WinDivert.",
                )
            else:
                state = ComponentState(component_id=component_id, status="error", last_error=str(error))
            self.logging.log("error", "Zapret2 failed to start", error=state.last_error)
        except Exception as error:
            state = ComponentState(component_id=component_id, status="error", last_error=str(error))
            self.logging.log("error", "Zapret2 failed to start", error=str(error))
        self._states[component_id] = state
        self._invalidate_state_cache()
        return state

    def _ensure_zapret2_runtime(self) -> Path:
        runtime_root = self.storage.paths.runtime_dir / "zapret2"
        if self._zapret2_runtime_is_ready(runtime_root):
            return runtime_root
        return self._install_zapret2_archive()

    def _zapret2_runtime_is_ready(self, runtime_root: Path) -> bool:
        """True when a real bol-van/zapret2 release tree (or stamped valid install) is present."""
        winws = self._find_zapret2_winws(runtime_root)
        if winws is None:
            return False
        if (runtime_root / "binaries" / "windows-x86_64" / "winws2.exe").is_file():
            return True
        if (runtime_root / "lua" / "zapret-lib.lua").is_file() and (runtime_root / "zapret-winws" / "winws2.exe").is_file():
            return True
        version = ""
        try:
            version = (runtime_root / ".zapret-hub-version").read_text(encoding="utf-8").strip().lstrip("vV")
        except OSError:
            version = ""
        # Nested zapret-win-bundle-master without a semver stamp is the old wrong install.
        if "zapret-win-bundle" in str(winws).replace("\\", "/").lower():
            return bool(version) and version not in {"master", "unknown"} and any(ch.isdigit() for ch in version)
        return bool(version) and version not in {"master", "unknown"}

    def _install_zapret2_archive(self, *, archive_url: str = "", version: str = "") -> Path:
        runtime_root = self.storage.paths.runtime_dir / "zapret2"
        # Prefer bol-van/zapret2 release archives; win-bundle is a Windows binary fallback.
        if not archive_url:
            try:
                release = self.fetch_latest_zapret2_release()
                archive_url = str(
                    release.get("asset_url")
                    or release.get("source_url")
                    or release.get("zipball_url")
                    or ""
                ).strip()
                version = version or str(release.get("latest_version") or "").strip()
            except Exception:
                archive_url = ""
        archive_url = archive_url or "https://codeload.github.com/bol-van/zapret-win-bundle/zip/refs/heads/master"
        temp_root = Path(tempfile.mkdtemp(prefix="zapret_hub_zapret2_"))
        try:
            zip_path = temp_root / "zapret2-release.zip"
            self._download_to_file(archive_url, zip_path, timeout=90)
            extract_root = temp_root / "extract"
            extract_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as archive:
                archive.extractall(extract_root)
            source_root = self._find_extracted_zapret2_root(extract_root)
            if source_root is None and "zapret-win-bundle" not in archive_url:
                bundle_zip = temp_root / "zapret2-win-bundle.zip"
                bundle_url = "https://codeload.github.com/bol-van/zapret-win-bundle/zip/refs/heads/master"
                self._download_to_file(bundle_url, bundle_zip, timeout=90)
                bundle_extract = temp_root / "bundle_extract"
                bundle_extract.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(bundle_zip, "r") as archive:
                    archive.extractall(bundle_extract)
                source_root = self._find_extracted_zapret2_root(bundle_extract)
            if source_root is None:
                raise FileNotFoundError("Downloaded Zapret2 archive does not contain winws2.exe.")
            backup = self.storage.create_backup(runtime_root, "pre-update-zapret2") if runtime_root.exists() else None
            if runtime_root.exists():
                shutil.rmtree(runtime_root, ignore_errors=True)
            shutil.copytree(source_root, runtime_root, dirs_exist_ok=True)
            if version:
                (runtime_root / ".zapret-hub-version").write_text(version.lstrip("vV"), encoding="utf-8")
            self.storage.ensure_layout()
            self.logging.log(
                "info",
                "Zapret2 runtime installed",
                version=version,
                backup=str(backup or ""),
                source=archive_url,
            )
            return runtime_root
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def _find_extracted_zapret2_root(self, extract_root: Path) -> Path | None:
        """Prefer official release tree root (binaries/windows-x86_64 + lua), then win-bundle."""
        candidates: list[Path] = [extract_root]
        try:
            candidates.extend(path for path in extract_root.iterdir() if path.is_dir())
        except OSError:
            pass
        for candidate in candidates:
            if (candidate / "binaries" / "windows-x86_64" / "winws2.exe").is_file():
                return candidate
            if (candidate / "zapret-winws" / "winws2.exe").is_file():
                return candidate
        for candidate in candidates:
            if self._find_zapret2_winws(candidate) is not None:
                return candidate
        for candidate in extract_root.rglob("*"):
            if candidate.is_dir() and self._find_zapret2_winws(candidate) is not None:
                return candidate
        return None

    def _find_zapret2_winws(self, runtime_root: Path) -> Path | None:
        if not runtime_root.exists():
            return None
        preferred = [
            runtime_root / "binaries" / "windows-x86_64" / "winws2.exe",
            runtime_root / "binaries" / "win64" / "winws2.exe",
            runtime_root / "zapret-winws" / "winws2.exe",
            runtime_root / "zapret-win-bundle-master" / "zapret-winws" / "winws2.exe",
            runtime_root / "bin" / "winws2.exe",
            runtime_root / "winws2.exe",
        ]
        for candidate in preferred:
            if candidate.is_file():
                return candidate
        with_dll: list[Path] = []
        without_dll: list[Path] = []
        for candidate in runtime_root.rglob("winws2.exe"):
            if not candidate.is_file():
                continue
            # blockcheck ships a bare winws2 without cygwin1.dll — never launch that copy
            if "blockcheck" in {part.lower() for part in candidate.parts}:
                continue
            if (candidate.parent / "cygwin1.dll").is_file():
                with_dll.append(candidate)
            else:
                without_dll.append(candidate)
        if with_dll:
            return with_dll[0]
        if without_dll:
            return without_dll[0]
        return None

    def _build_zapret2_command(self, winws2_path: Path, runtime_root: Path) -> list[str]:
        from zapret_hub.services.orchestrator import zapret2_hub

        settings = self.settings.get()
        configs_dir = Path(self.storage.paths.configs_dir)
        mod_profile = zapret2_hub.active_mod_profile(configs_dir)
        if mod_profile is not None:
            profile_args = zapret2_hub.build_mod_profile_args(mod_profile)
            self.logging.log(
                "info",
                "Using full Zapret2 modification profile",
                profile=str(mod_profile),
            )
            return [str(winws2_path), *profile_args]

        tcp_ports = self._normalize_zapret2_ports(settings.zapret2_tcp_ports, "80,443")
        udp_ports = self._normalize_zapret2_ports(settings.zapret2_udp_ports, "443")
        control_mode = str(getattr(settings, "zapret2_control_mode", "manual") or "manual")
        selected_services = {str(item) for item in (settings.selected_service_ids or [])}
        # Match Flowseal general.bat: Discord media TCP + voice UDP must be in WinDivert capture.
        discord_capture = "discord" in selected_services
        if discord_capture:
            tcp_ports = self._merge_zapret2_ports(tcp_ports, DISCORD_MEDIA_TCP_PORTS)
            udp_ports = self._merge_zapret2_ports(udp_ports, DISCORD_VOICE_UDP_PORTS)
        bundle_root = zapret2_hub.bundle_winws_root(winws2_path)
        asset_roots = zapret2_hub.zapret2_asset_roots(winws2_path, runtime_root)
        lua_lib = self._zapret2_lua_arg(runtime_root, "zapret-lib.lua", winws2_path=winws2_path)
        lua_antidpi = self._zapret2_lua_arg(runtime_root, "zapret-antidpi.lua", winws2_path=winws2_path)
        # bol-van preset2_example: randomize built-in TLS fake SNI once at start.
        # Keep as a tiny file — inline lua-init with spaces is fragile on Windows argv.
        fake_tls_init = zapret2_hub.zapret2_lists_dir(Path(self.storage.paths.configs_dir)) / "hub-fake-tls-init.lua"
        try:
            desired = "fake_default_tls = tls_mod(fake_default_tls,'rnd,rndsni')\n"
            if not fake_tls_init.is_file() or fake_tls_init.read_text(encoding="utf-8", errors="ignore") != desired:
                fake_tls_init.parent.mkdir(parents=True, exist_ok=True)
                fake_tls_init.write_text(desired, encoding="utf-8")
        except Exception:
            fake_tls_init = None
        command = [
            str(winws2_path),
            f"--wf-tcp-out={tcp_ports}",
            f"--wf-udp-out={udp_ports}",
            f"--lua-init=@{lua_lib}",
            f"--lua-init=@{lua_antidpi}",
        ]
        if fake_tls_init is not None and fake_tls_init.is_file():
            command.append(f"--lua-init=@{fake_tls_init}")

        auto_lua = zapret2_hub.find_bundle_lua(asset_roots, "zapret-auto.lua")
        if auto_lua is not None:
            command.append(f"--lua-init=@{auto_lua}")

        raw_filter = str(settings.zapret2_raw_filter or "").strip()
        if raw_filter:
            command.append(f"--wf-raw-part={raw_filter}")

        strategy_id = str(getattr(settings, "zapret2_strategy_id", "balanced") or "balanced")
        lists = zapret2_hub.prepare_zapret2_runtime_files(configs_dir, strategy_id)
        include_hostlist_auto = control_mode == "auto"
        try:
            selected = [str(item) for item in (settings.selected_service_ids or [])]
            # Append-only: never wipe; seed only what is still missing.
            if selected:
                zapret2_hub.seed_service_lists(configs_dir, selected, only_missing=True)
            if control_mode == "auto" and not zapret2_hub.hub_lists_initialized(configs_dir):
                zapret2_hub.seed_bypass_catalog(configs_dir, only_missing=True)
        except Exception:
            pass
        if include_hostlist_auto:
            # Auto: runtime copy with overlay/diff applied — battle hub files stay intact.
            auto_root = Path(self.storage.paths.runtime_dir) / "zapret2" / "lists_auto"
            lists = {
                **lists,
                **zapret2_hub.materialize_auto_lists(configs_dir, auto_root),
            }
        else:
            # Manual: same hub/mod/user merge, but without Auto-learned overlays and
            # never pass winws2 hostlist-auto.
            manual_root = Path(self.storage.paths.runtime_dir) / "zapret2" / "lists_manual"
            lists = {
                **lists,
                **zapret2_hub.materialize_manual_lists(configs_dir, manual_root),
            }

        # Discord must stay hostlist-only: Cloudflare 162.158.0.0/15 covers Discord CDN
        # and a second 443 ipset desync kills updates/login. Scrub after every seed/materialize.
        try:
            zapret2_hub.sanitize_zapret2_discord_ipset(
                configs_dir,
                runtime_dir=Path(self.storage.paths.runtime_dir),
            )
            zapret2_hub.strip_discord_breaking_ipsets(Path(lists["ipset"]))
        except Exception:
            pass

        mod_lua_root = zapret2_hub.zapret2_lists_dir(configs_dir) / "mod_lua"
        if mod_lua_root.is_dir():
            for mod_lua in sorted(mod_lua_root.glob("*.lua")):
                command.append(f"--lua-init=@{mod_lua}")

        strategy = str(settings.zapret2_lua_strategy or "").strip()
        command.append(f"--lua-init=@{lists['lua_targets']}")
        command.append(f"--lua-init=@{lists['lua_orch']}")
        command.append(f"--lua-init=@{lists['lua_strategy']}")
        # Always keep Hub default profiles (Discord media/voice, TLS, QUIC). Custom
        # args are appended after so they cannot drop Discord capture.
        flowseal_bin = Path(self.storage.paths.runtime_dir) / "zapret-discord-youtube" / "bin"
        command.extend(
            zapret2_hub.build_default_profile_args(
                lists=lists,
                asset_roots=asset_roots,
                tcp_ports=tcp_ports,
                strategy_id=strategy_id,
                include_hostlist_auto=include_hostlist_auto,
                flowseal_bin=flowseal_bin if flowseal_bin.is_dir() else None,
            )
        )
        if strategy and control_mode != "auto":
            command.extend(shlex.split(strategy, posix=False))
        return command

    def _normalize_zapret2_ports(self, value: str, fallback: str) -> str:
        normalized: list[str] = []
        for token in re.split(r"[\s,;]+", str(value or "")):
            match = re.fullmatch(r"(\d{1,5})(?:-(\d{1,5}))?", token.strip())
            if not match:
                continue
            start = int(match.group(1))
            end = int(match.group(2) or start)
            if start > end:
                start, end = end, start
            if start < 1 or end > 65535:
                continue
            normalized.append(str(start) if start == end else f"{start}-{end}")
        return ",".join(dict.fromkeys(normalized)) or fallback

    def _merge_zapret2_ports(self, *values: str) -> str:
        return self._normalize_zapret2_ports(",".join(values), "443")

    def _zapret2_lua_arg(self, runtime_root: Path, filename: str, *, winws2_path: Path | None = None) -> str:
        """Return absolute path to a zapret2 Lua file (works for release + win-bundle layouts)."""
        from zapret_hub.services.orchestrator import zapret2_hub

        roots = zapret2_hub.zapret2_asset_roots(winws2_path, runtime_root) if winws2_path is not None else [Path(runtime_root)]
        found = zapret2_hub.find_bundle_lua(roots, filename)
        if found is not None:
            return str(found.resolve())
        return str((Path(runtime_root) / "lua" / filename).resolve())

    def _zapret_log_indicates_capture_started(self, text: str | None) -> bool:
        normalized = str(text or "").lower()
        return "capture is started" in normalized or "windivert initialized" in normalized

    def _is_admin_windows(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _parse_vmess(self, raw: str) -> dict[str, str] | None:
        try:
            payload = raw.split("://", 1)[1].strip()
            padded = payload + "=" * (-len(payload) % 4)
            data = json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
            if not isinstance(data, dict):
                return None
            return {
                "host": str(data.get("add", "") or ""),
                "uuid": str(data.get("id", "") or ""),
                "port": str(data.get("port", "") or ""),
            }
        except Exception:
            return None

    def _extract_winws_command(self, script_path: Path, bin_dir: Path, lists_dir: Path) -> list[str]:
        game_filter, game_filter_tcp, game_filter_udp = self._get_game_filter_values(script_path.parent)
        lines = self._read_batch_logical_lines(script_path)
        for line in lines:
            if "winws.exe" not in line.lower():
                continue
            try:
                parts = shlex.split(line, posix=False)
            except ValueError:
                continue
            if not parts:
                continue
            winws_idx = next((i for i, item in enumerate(parts) if "winws.exe" in item.lower()), -1)
            if winws_idx < 0:
                continue

            executable = self._expand_batch_value(
                parts[winws_idx],
                script_dir=script_path.parent,
                bin_dir=bin_dir,
                lists_dir=lists_dir,
                game_filter=game_filter,
                game_filter_tcp=game_filter_tcp,
                game_filter_udp=game_filter_udp,
            ).strip().strip('"')
            if not executable:
                continue
            exe_path = Path(executable)
            if not exe_path.is_absolute():
                script_relative = script_path.parent / executable
                if script_relative.exists():
                    exe_path = script_relative
                elif exe_path.name.lower() == "winws.exe":
                    exe_path = bin_dir / "winws.exe"
                else:
                    exe_path = bin_dir / exe_path.name
            args: list[str] = []
            for raw_arg in parts[winws_idx + 1 :]:
                arg = self._expand_batch_value(
                    raw_arg,
                    script_dir=script_path.parent,
                    bin_dir=bin_dir,
                    lists_dir=lists_dir,
                    game_filter=game_filter,
                    game_filter_tcp=game_filter_tcp,
                    game_filter_udp=game_filter_udp,
                ).strip()
                if not arg or arg == "^":
                    continue
                # кавычки из bat тут только мешают
                if arg.startswith('"') and arg.endswith('"') and len(arg) >= 2:
                    arg = arg[1:-1]
                if '="' in arg and arg.endswith('"'):
                    key, value = arg.split('="', 1)
                    arg = f"{key}={value[:-1]}"
                args.append(arg)
            return [str(exe_path), *args]
        return []

    def _apply_vpn_priority_to_command(self, command: list[str], *, lists_dir: Path) -> list[str]:
        if not command or not sys.platform.startswith("win"):
            return command
        try:
            vpn_data = self._detect_vpn_priority_context()
        except Exception as error:
            self.logging.log("warning", "Failed to detect VPN priority context", error=str(error))
            return command

        adapter_indexes = [int(item) for item in vpn_data.get("adapter_indexes", []) if str(item).isdigit()]
        remote_ips = [str(item).strip() for item in vpn_data.get("remote_ips", []) if str(item).strip()]
        if not adapter_indexes and not remote_ips:
            return command

        updated = list(command)
        raw_parts: list[str] = []
        if adapter_indexes:
            raw_filter = " and ".join(f"(ifIdx != {index} and subIfIdx != {index})" for index in sorted(set(adapter_indexes)))
            raw_parts.append(raw_filter)

        if remote_ips:
            vpn_exclude_path = lists_dir / "ipset-vpn-exclude.txt"
            vpn_exclude_path.write_text("\n".join(sorted(set(remote_ips))) + "\n", encoding="utf-8")
            updated.append(f"--ipset-exclude={vpn_exclude_path}")

        if raw_parts:
            combined_filter = " and ".join(f"({part})" for part in raw_parts)
            updated.append(f"--wf-raw-part={combined_filter}")

        self.logging.log(
            "info",
            "Applied VPN priority safeguards to zapret",
            adapter_indexes=sorted(set(adapter_indexes)),
            remote_ips=sorted(set(remote_ips)),
        )
        return updated

    def _apply_udp_port_exclusions_to_command(self, command: list[str]) -> list[str]:
        excluded_udp_ports = self._parse_port_ranges(self.settings.get().zapret_udp_exclude_ports)
        if not excluded_udp_ports:
            return command
        updated = self._exclude_udp_ports_from_command(command, excluded_udp_ports)
        self.logging.log(
            "info",
            "Applied UDP port exclusions to zapret",
            excluded_udp_ports=self._format_port_ranges(excluded_udp_ports),
        )
        return updated

    def _exclude_udp_ports_from_command(self, command: list[str], excluded_ranges: list[tuple[int, int]]) -> list[str]:
        if not command:
            return command
        executable = command[0]
        prefix: list[str] = []
        segments: list[list[str]] = []
        current: list[str] = []
        in_segments = False
        for arg in command[1:]:
            if arg == "--new":
                in_segments = True
                if current:
                    segments.append(current)
                current = []
                continue
            if in_segments:
                current.append(arg)
            else:
                prefix.append(arg)
        if current:
            segments.append(current)

        filtered_prefix, _drop_prefix = self._filter_udp_args_in_segment(
            prefix,
            excluded_ranges,
            drop_empty_filter_segment=True,
        )
        filtered_segments: list[list[str]] = []
        for segment in segments:
            filtered_segment, drop_segment = self._filter_udp_args_in_segment(
                segment,
                excluded_ranges,
                drop_empty_filter_segment=True,
            )
            if drop_segment or not filtered_segment:
                continue
            filtered_segments.append(filtered_segment)

        updated = [executable, *filtered_prefix]
        for segment in filtered_segments:
            updated.append("--new")
            updated.extend(segment)
        return updated

    def _filter_udp_args_in_segment(
        self,
        args: list[str],
        excluded_ranges: list[tuple[int, int]],
        *,
        drop_empty_filter_segment: bool,
    ) -> tuple[list[str], bool]:
        updated: list[str] = []
        for arg in args:
            if arg.startswith("--wf-udp=") or arg.startswith("--filter-udp="):
                key, value = arg.split("=", 1)
                ranges = self._parse_port_ranges(value)
                if ranges:
                    filtered = self._subtract_port_ranges(ranges, excluded_ranges)
                    value = self._format_port_ranges(filtered)
                    if not value:
                        if key == "--filter-udp" and drop_empty_filter_segment:
                            preserved_globals = [item for item in updated if item.startswith("--wf-") or item.startswith("--wf-raw")]
                            return preserved_globals, True
                        continue
                    arg = f"{key}={value}"
            updated.append(arg)
        return updated, False

    def _subtract_port_ranges(
        self,
        ranges: list[tuple[int, int]],
        excluded_ranges: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for start, end in ranges:
            segments = [(start, end)]
            for ex_start, ex_end in excluded_ranges:
                next_segments: list[tuple[int, int]] = []
                for seg_start, seg_end in segments:
                    if ex_end < seg_start or ex_start > seg_end:
                        next_segments.append((seg_start, seg_end))
                        continue
                    if seg_start < ex_start:
                        next_segments.append((seg_start, ex_start - 1))
                    if ex_end < seg_end:
                        next_segments.append((ex_end + 1, seg_end))
                segments = next_segments
            result.extend(segment for segment in segments if segment[0] <= segment[1])
        return result

    def _format_port_ranges(self, ranges: list[tuple[int, int]]) -> str:
        return ",".join(str(start) if start == end else f"{start}-{end}" for start, end in ranges)

    def _parse_port_ranges(self, value: str) -> list[tuple[int, int]]:
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
        return ranges

    def _detect_vpn_priority_context(self) -> dict[str, list[str]]:
        script = r"""
$patterns = @('nekobox','nekoray','v2rayn','xray','xrayw','sing-box','singbox','clash','mihomo','hiddify','outline','wireguard','openvpn','amnezia','warp')
$adapterPatterns = @('wintun','wireguard','openvpn','tap-','tap_windows','vpn','v2ray','xray','nekobox','nekoray','sing-box','clash','mihomo','tun')

$procById = @{}
Get-CimInstance Win32_Process | ForEach-Object {
  $name = ([string]$_.Name).ToLowerInvariant()
  $path = ([string]$_.ExecutablePath).ToLowerInvariant()
  $cmd = ([string]$_.CommandLine).ToLowerInvariant()
  foreach ($pattern in $patterns) {
    if ($name.Contains($pattern) -or $path.Contains($pattern) -or $cmd.Contains($pattern)) {
      $procById[[int]$_.ProcessId] = $true
      break
    }
  }
}

$remoteIps = New-Object System.Collections.Generic.HashSet[string]
Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue | ForEach-Object {
  $pid = [int]$_.OwningProcess
  if (-not $procById.ContainsKey($pid)) { return }
  $ip = ([string]$_.RemoteAddress).Trim()
  if (-not $ip) { return }
  if ($ip -in @('127.0.0.1','0.0.0.0','::','::1')) { return }
  [void]$remoteIps.Add($ip)
}

$adapterIndexes = New-Object System.Collections.Generic.HashSet[int]
Get-NetAdapter -ErrorAction SilentlyContinue | ForEach-Object {
  $joined = (([string]$_.Name) + ' ' + ([string]$_.InterfaceDescription)).ToLowerInvariant()
  foreach ($pattern in $adapterPatterns) {
    if ($joined.Contains($pattern)) {
      [void]$adapterIndexes.Add([int]$_.ifIndex)
      break
    }
  }
}

[pscustomobject]@{
  adapter_indexes = @($adapterIndexes | Sort-Object)
  remote_ips = @($remoteIps | Sort-Object)
} | ConvertTo-Json -Compress
"""
        proc = self._run_powershell_json(script)
        if not proc:
            return {"adapter_indexes": [], "remote_ips": []}
        try:
            payload = json.loads(proc)
        except json.JSONDecodeError:
            return {"adapter_indexes": [], "remote_ips": []}
        adapter_indexes = payload.get("adapter_indexes", []) if isinstance(payload, dict) else []
        remote_ips = payload.get("remote_ips", []) if isinstance(payload, dict) else []
        if not isinstance(adapter_indexes, list):
            adapter_indexes = [adapter_indexes] if adapter_indexes not in (None, "") else []
        if not isinstance(remote_ips, list):
            remote_ips = [remote_ips] if remote_ips not in (None, "") else []
        return {
            "adapter_indexes": [str(item) for item in adapter_indexes if str(item).strip()],
            "remote_ips": [str(item) for item in remote_ips if self._looks_like_ip_address(str(item))],
        }

    def _run_powershell_json(self, script: str) -> str:
        startup = self._startupinfo
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            startupinfo=startup,
        )
        if proc.returncode != 0:
            self.logging.log("warning", "PowerShell helper failed", stderr=(proc.stderr or "").strip()[-1000:])
            return ""
        return (proc.stdout or "").strip()

    def _looks_like_ip_address(self, value: str) -> bool:
        candidate = value.strip()
        if not candidate:
            return False
        if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", candidate):
            return True
        return ":" in candidate and re.fullmatch(r"[0-9a-fA-F:]+", candidate) is not None

    def _read_batch_logical_lines(self, script_path: Path) -> list[str]:
        raw_lines = script_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        logical_lines: list[str] = []
        current = ""
        for raw in raw_lines:
            line = raw.strip()
            if not line or line.startswith("::") or line.lower().startswith("rem "):
                continue
            if current:
                current = f"{current} {line}"
            else:
                current = line
            if current.endswith("^"):
                current = current[:-1].rstrip()
                continue
            logical_lines.append(current)
            current = ""
        if current:
            logical_lines.append(current)
        return logical_lines

    def _expand_batch_value(
        self,
        value: str,
        *,
        script_dir: Path,
        bin_dir: Path,
        lists_dir: Path,
        game_filter: str,
        game_filter_tcp: str,
        game_filter_udp: str,
    ) -> str:
        result = value
        script_prefix = str(script_dir) + os.sep
        replacements = {
            "%~dp0": script_prefix,
            "%CD%": str(script_dir),
            "%BIN%": str(bin_dir) + os.sep,
            "%LISTS%": str(lists_dir) + os.sep,
            "%GameFilter%": game_filter,
            "%GameFilterTCP%": game_filter_tcp,
            "%GameFilterUDP%": game_filter_udp,
        }
        for key, replacement in replacements.items():
            result = result.replace(key, replacement).replace(key.lower(), replacement).replace(key.upper(), replacement)
        return result

    def _fortnite_service_selected(self) -> bool:
        return "fortnite" in {str(item) for item in list(self.settings.get().selected_service_ids or [])}

    def _should_force_fortnite_runtime_modes(self) -> bool:
        return self._fortnite_service_selected() and not self._diagnostic_runtime_override

    def _warframe_service_selected(self) -> bool:
        try:
            return "warframe" in {str(item) for item in (self.settings.get().selected_service_ids or [])}
        except Exception:
            return False

    def _get_game_filter_values(self, runtime_root: Path) -> tuple[str, str, str]:
        mode_from_settings = (self.settings.get().zapret_game_filter_mode or "").strip().lower()
        if self._should_force_fortnite_runtime_modes() or self._warframe_service_selected():
            mode_from_settings = "tcpudp"
        if mode_from_settings == "auto":
            mode_from_settings = ""
        if mode_from_settings in {"all", "tcpudp"}:
            return ("1024-65535", "1024-65535", "1024-65535")
        if mode_from_settings == "tcp":
            return ("1024-65535", "1024-65535", "12")
        if mode_from_settings == "udp":
            return ("1024-65535", "12", "1024-65535")
        if mode_from_settings == "disabled":
            return ("12", "12", "12")
        mode_file = runtime_root / "utils" / "game_filter.enabled"
        if not mode_file.exists():
            return ("12", "12", "12")
        mode = mode_file.read_text(encoding="utf-8", errors="ignore").strip().lower()
        if mode in {"all", "tcpudp"}:
            return ("1024-65535", "1024-65535", "1024-65535")
        if mode == "tcp":
            return ("1024-65535", "1024-65535", "12")
        if mode == "udp":
            return ("1024-65535", "12", "1024-65535")
        return ("12", "12", "12")

    def _apply_zapret_runtime_switches(self, runtime_root: Path) -> None:
        settings = self.settings.get()
        lists_dir = runtime_root / "lists"
        utils_dir = runtime_root / "utils"
        lists_dir.mkdir(parents=True, exist_ok=True)
        utils_dir.mkdir(parents=True, exist_ok=True)

        # Drop classic pollution from older Auto Discord seeds (CDN CIDR + excludes).
        try:
            from zapret_hub.services.orchestrator import zapret2_hub

            zapret2_hub.sanitize_classic_discord_pollution(Path(self.storage.paths.configs_dir))
        except Exception:
            pass

        ipset_mode = (settings.zapret_ipset_mode or "loaded").strip().lower()
        if self._should_force_fortnite_runtime_modes():
            ipset_mode = "any"
        ipset_all = lists_dir / "ipset-all.txt"
        if ipset_mode == "none":
            ipset_all.write_text("203.0.113.113/32\n", encoding="utf-8")
        elif ipset_mode == "any":
            ipset_all.write_text("", encoding="utf-8")
        elif not ipset_all.exists():
            ipset_all.write_text("", encoding="utf-8")
        elif ipset_mode == "loaded" and ipset_all.is_file():
            # If Discord /20 was merged into the stub file, strip hostlist-only seeds.
            try:
                from zapret_hub.services.orchestrator import zapret2_hub

                ban = {str(x).strip().lower() for x in zapret2_hub.BYPASS_SEED_NETWORKS}
                ban.add("162.159.128.0/20")
                lines = ipset_all.read_text(encoding="utf-8", errors="ignore").splitlines()
                kept = [row for row in lines if row.strip().lower() not in ban]
                if len(kept) != len(lines):
                    ipset_all.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            except Exception:
                pass

        game_mode = (settings.zapret_game_filter_mode or "disabled").strip().lower()
        if self._should_force_fortnite_runtime_modes() or self._warframe_service_selected():
            game_mode = "tcpudp"
        game_flag = utils_dir / "game_filter.enabled"
        if game_mode in ("all", "tcp", "udp", "tcpudp"):
            game_flag.write_text(game_mode, encoding="utf-8")
        elif game_flag.exists():
            game_flag.unlink(missing_ok=True)

    def _start_tg_ws_proxy(self, component_id: str) -> ComponentState:
        # перезапуск без споров со старыми процессами
        self.stop_component(component_id)

        settings = self.settings.get()
        secret = (settings.tg_proxy_secret or "").strip().lower()
        if secret.startswith("dd") and len(secret) > 2:
            secret = secret[2:]
        if not secret:
            secret = secrets.token_hex(16)
        if secret != settings.tg_proxy_secret:
            settings = self.settings.update(tg_proxy_secret=secret)
        # старый процесс мог остаться в трее
        self._kill_image("TgWsProxy_windows.exe")
        listen_host = settings.tg_proxy_host
        listen_port = int(settings.tg_proxy_port)
        self._port_listening_cache.pop((str(listen_host or ""), int(listen_port)), None)
        if self._is_port_listening(listen_host, listen_port):
            state = ComponentState(component_id=component_id, status="running", pid=None, last_error="")
            self._states[component_id] = state
            self._invalidate_state_cache()
            self.logging.log("info", "TG WS Proxy already listening", host=listen_host, port=listen_port)
            return state
        try:
            (self.storage.paths.logs_dir / "tg_worker_error.log").unlink(missing_ok=True)
        except Exception:
            pass
        command = self._build_worker_command(
            "tg-ws-proxy",
            tg_host=settings.tg_proxy_host,
            tg_port=int(settings.tg_proxy_port),
            tg_secret=secret,
            tg_dc_ip=self._parse_tg_dc_ip_settings(settings.tg_proxy_dc_ip),
            tg_cfproxy_enabled=bool(settings.tg_proxy_cfproxy_enabled),
            tg_cfproxy_priority=bool(settings.tg_proxy_cfproxy_priority),
            tg_cfproxy_domain=settings.tg_proxy_cfproxy_domain,
            tg_fake_tls_domain=settings.tg_proxy_fake_tls_domain,
            tg_buf_kb=int(settings.tg_proxy_buf_kb or 256),
            tg_pool_size=int(settings.tg_proxy_pool_size or 4),
        )
        process = subprocess.Popen(
            command,
            cwd=str(self.storage.paths.install_root),
            creationflags=self._creationflags,
            startupinfo=self._startupinfo,
            env=self._build_worker_env(),
            stdout=self._open_source_log_stream("tg-ws-proxy"),
            stderr=subprocess.STDOUT,
        )
        # Assign to kill-on-close job immediately (before listen wait).
        if self._job and process.pid:
            if not self._job.assign_pid(process.pid):
                self.logging.log("warning", "Failed to assign TG WS Proxy to job object", pid=process.pid)
        ready = False
        for _ in range(16):
            if process.poll() is not None:
                break
            self._port_listening_cache.pop((str(listen_host or ""), int(listen_port)), None)
            if self._is_port_listening(listen_host, listen_port):
                ready = True
                break
            time.sleep(0.35)
        if not ready:
            error_hint = "TG WS Proxy worker did not open listening port."
            worker_error_log = self.storage.paths.logs_dir / "tg_worker_error.log"
            if worker_error_log.exists():
                error_hint = worker_error_log.read_text(encoding="utf-8")[-1000:]
            try:
                if process.poll() is None:
                    process.kill()
            except Exception:
                pass
            try:
                self._kill_image("TgWsProxy_windows.exe")
            except Exception:
                pass
            state = ComponentState(
                component_id=component_id,
                status="error",
                last_error=error_hint,
            )
            self._states[component_id] = state
            self._invalidate_state_cache()
            self.logging.log("error", "TG WS Proxy worker failed to start", error=error_hint)
            return state
        state = ComponentState(component_id=component_id, status="running", pid=process.pid)
        self._processes[component_id] = process
        self._states[component_id] = state
        self._port_listening_cache[(str(listen_host or ""), int(listen_port))] = (time.time(), True)
        self._invalidate_state_cache()
        self.logging.log("info", "TG WS Proxy worker started", pid=process.pid)
        if not str(settings.tg_proxy_link_prompt_signature or "").strip():
            self.prompt_telegram_proxy_link()
        return state

    def _parse_tg_dc_ip_settings(self, value: str) -> list[str]:
        result: list[str] = []
        for raw in re.split(r"[\n,;]+", str(value or "")):
            item = raw.strip()
            if item:
                result.append(item)
        if not result:
            # без этого tg-ws-proxy сам подставляет дефолтные dc
            return ["__empty__"]
        return result

    def _ensure_telegram_and_open_proxy_link(self, host: str, port: int, secret: str) -> dict[str, Any]:
        self.logging.log("info", "TG WS Proxy auto-connect requested", component_id="tg-ws-proxy", host=host, port=port)
        running_before = self._is_telegram_running()
        candidate_found = any(candidate.exists() for candidate in self._telegram_desktop_candidates())
        launch_requested = False
        if not running_before:
            self.logging.log("info", "Telegram Desktop is not running, opening proxy link without forced launch", component_id="tg-ws-proxy")
        running_after = self._is_telegram_running()
        self.logging.log("info", "Sending proxy link to Telegram", component_id="tg-ws-proxy")
        link_opened = self._open_telegram_proxy_link(host=host, port=port, secret=secret)
        info = {
            "running_before": running_before,
            "running_after": running_after,
            "desktop_candidate_found": candidate_found,
            "launch_requested": launch_requested,
            "link_opened": link_opened,
            "missing": not running_after and not link_opened,
        }
        self._telegram_proxy_launch_info = info
        if not running_after and not link_opened:
            self.logging.log("warning", "Telegram was not detected after proxy start", component_id="tg-ws-proxy")
        return info

    def _open_telegram_proxy_link(self, host: str, port: int, secret: str) -> bool:
        link = f"tg://proxy?server={host}&port={port}&secret=dd{secret}"
        try:
            if sys.platform.startswith("win"):
                os.startfile(link)  # type: ignore[attr-defined]
            else:
                webbrowser.open(link)
            self.logging.log("info", "Telegram proxy link opened", link=link)
            return True
        except Exception as error:
            self.logging.log("warning", "Failed to open Telegram proxy link", link=link, error=str(error))
            return False

    def _build_worker_command(self, worker: str, **kwargs: Any) -> list[str]:
        cmd: list[str]
        if is_packaged_runtime():
            cmd = [sys.executable, "--worker", worker]
        else:
            cmd = [self._worker_python_executable(), "-m", "zapret_hub.worker_entry", "--worker", worker]

        for key, value in kwargs.items():
            option = "--" + key.replace("_", "-")
            if isinstance(value, (list, tuple)):
                for item in value:
                    cmd.extend([option, str(item)])
                continue
            cmd.extend([option, str(value)])
        return cmd

    def _get_zapret_bundles(self, enabled_only: bool, *, include_hidden_generals: bool = False) -> list[dict[str, Any]]:
        bundles: list[dict[str, Any]] = []
        base = self.storage.paths.runtime_dir / "zapret-discord-youtube"
        unified_root = self.storage.paths.mods_dir / "unified-by-goshkow"
        index_map = {
            str(item.get("id", "")): str(item.get("name", "")).strip()
            for item in (self.storage.read_json(self.storage.paths.cache_dir / "mods_index.json", default=[]) or [])
            if isinstance(item, dict)
        }
        installed_raw = self.storage.read_json(self.storage.paths.data_dir / "installed_mods.json", default=[]) or []
        for raw in installed_raw:
            if raw.get("source_type") != "zapret_bundle":
                continue
            if enabled_only and not raw.get("enabled"):
                continue
            path = Path(raw.get("path", ""))
            if not path.exists():
                continue
            mod_id = str(raw.get("id", "bundle"))
            if mod_id == "unified-by-goshkow":
                continue
            title = str(raw.get("name") or "").strip() or index_map.get(mod_id) or mod_id
            bundles.append({
                "id": mod_id,
                "title": title,
                "path": path,
            })
        if include_hidden_generals and unified_root.exists():
            bundles.insert(0, {"id": "unified-general", "title": "Hub", "path": unified_root})
        if base.exists():
            bundles.append({"id": "base", "title": "", "path": base})
        return bundles

    def _general_option_sort_key(self, item: dict[str, str]) -> tuple[int, int, str]:
        bundle_id = str(item.get("bundle_id", ""))
        name = str(item.get("name", ""))
        lowered = name.lower()
        number = -1
        match = re.search(r"alt\s*(\d+)", lowered)
        if match:
            number = int(match.group(1))
        elif lowered == "general.bat":
            number = 0
        modified_rank = 1 if bundle_id == "unified-general" else 2 if bundle_id != "base" else 0
        return (modified_rank, -number, lowered)

    def _resolve_selected_general_option(self) -> dict[str, str] | None:
        options = self.list_zapret_generals()
        if not options:
            return None
        settings = self.settings.get()
        selected = settings.selected_zapret_general
        picked = next((item for item in options if item["id"] == selected), None)
        if picked is None:
            preferred = options[0]
            selected = preferred["id"]
            self.settings.update(selected_zapret_general=selected)
            picked = preferred
        return picked

    def _prepare_active_zapret_runtime(self, selected_bundle_root: Path, selected_bundle_id: str, selected_script_name: str) -> Path:
        self._cleanup_inactive_zapret_runtimes()
        return self._materialize_zapret_runtime(
            selected_bundle_root=selected_bundle_root,
            selected_bundle_id=selected_bundle_id,
            selected_script_name=selected_script_name,
        )

    def stage_zapret_candidate_runtime(self) -> Path:
        """Materialize candidate slot B without deleting live A (orchestrator cutover)."""
        with self._zapret_runtime_lock:
            selected_option = self._resolve_selected_general_option()
            if selected_option is None:
                raise RuntimeError("No general script found.")
            selected_script = Path(selected_option["path"])
            selected_bundle_root = Path(selected_script).parent
            # Preserve live + any explicitly pinned roots; only prune other orphans.
            self._cleanup_inactive_zapret_runtimes(preserve_extra=getattr(self, "_orchestrator_preserve_runtimes", None))
            return self._materialize_zapret_runtime(
                selected_bundle_root=selected_bundle_root,
                selected_bundle_id=str(selected_option["bundle_id"]),
                selected_script_name=selected_script.name,
            )

    def pin_orchestrator_runtime(self, root: Path | None) -> None:
        """Keep an extra runtime directory alive during A/B cutover."""
        preserve = getattr(self, "_orchestrator_preserve_runtimes", None)
        if preserve is None:
            preserve = set()
            self._orchestrator_preserve_runtimes = preserve
        preserve.clear()
        if root is not None and Path(root).exists():
            preserve.add(Path(root).resolve())

    def _soft_stop_zapret_image(self) -> None:
        """Kill live winws without deleting staged/pinned runtime directories."""
        owned = self._processes.pop("zapret", None)
        if owned is not None and owned.poll() is None:
            try:
                owned.terminate()
            except Exception:
                pass
            try:
                owned.wait(timeout=0.35)
            except Exception:
                try:
                    owned.kill()
                except Exception:
                    pass
            if getattr(owned, "pid", None):
                self._run_quiet(["taskkill", "/PID", str(owned.pid), "/F", "/T"])
        if self._is_image_running("winws.exe"):
            self._kill_image("winws.exe")
            self._wait_for_image_exit("winws.exe", attempts=4, delay=0.05)
        try:
            self._close_source_log_stream("zapret")
        except Exception:
            pass
        self._invalidate_state_cache()

    def _soft_stop_zapret2_image(self) -> None:
        """Kill live winws2 without wiping the Zapret2 runtime tree."""
        owned = self._processes.pop("zapret2", None)
        if owned is not None and owned.poll() is None:
            try:
                owned.terminate()
            except Exception:
                pass
            try:
                owned.wait(timeout=0.8)
            except Exception:
                try:
                    owned.kill()
                except Exception:
                    pass
            if getattr(owned, "pid", None):
                self._run_quiet(["taskkill", "/PID", str(owned.pid), "/F", "/T"])
        if self._is_image_running("winws2.exe"):
            self._kill_image("winws2.exe")
            self._wait_for_image_exit("winws2.exe", attempts=6, delay=0.08)
        try:
            self._close_source_log_stream("zapret2")
        except Exception:
            pass
        self._invalidate_state_cache()

    def hot_replace_zapret_runtime(self, active_root: Path) -> ComponentState:
        """Orchestrator cutover: start staged B first, then close old winws PIDs.

        Never stop A until B is confirmed running. If B cannot start, keep A.
        """
        return self._cutover_to_zapret_runtime(Path(active_root))

    def seamless_restart_zapret(self) -> ComponentState:
        """Rebuild candidate runtime while live, then cut over with minimal downtime."""
        slot_b = self.stage_zapret_candidate_runtime()
        return self._cutover_to_zapret_runtime(slot_b)

    def _cutover_to_zapret_runtime(self, active_root: Path) -> ComponentState:
        """Replace live winws with a staged runtime.

        winws refuses a second copy with the same WinDivert filter
        (``A copy of winws is already running with the same filter``), so a true
        warm A→B overlap is impossible. The candidate runtime is already staged
        before this method is called, therefore the only visible downtime is the
        driver hand-off. A failed hand-off is retried after a full cleanup and,
        as a last resort, restores the previous known runtime instead of leaving
        Zapret stopped.
        """
        active_root = Path(active_root)
        with self._zapret_runtime_lock:
            previous_runtime = getattr(self, "_current_zapret_runtime", None)
            if previous_runtime is not None:
                previous_runtime = Path(previous_runtime)
                if not previous_runtime.exists() or previous_runtime.resolve() == active_root.resolve():
                    previous_runtime = None
            previous_script_name = str(getattr(self, "_current_zapret_script_name", "") or "")
            old_pids = self._list_image_pids("winws.exe")
            owned = self._processes.get("zapret")
            owned_pid = int(getattr(owned, "pid", 0) or 0) if owned is not None else 0
            if owned_pid:
                old_pids.add(owned_pid)

            if old_pids or self._is_image_running("winws.exe"):
                self._soft_stop_zapret_image()
                self._image_running_cache.pop("winws.exe", None)
                if not self._wait_for_image_exit("winws.exe", attempts=30, delay=0.08):
                    self.logging.log("warning", "Zapret cutover: winws did not exit cleanly; forcing cleanup")
                    self._purge_stale_zapret_runtime()
                    self._image_running_cache.pop("winws.exe", None)
                    self._wait_for_image_exit("winws.exe", attempts=20, delay=0.1)
                # Let WinDivert release its filter before the candidate binds it.
                time.sleep(0.35)

            if self._managed_zapret_driver_services():
                if not self._purge_stale_zapret_runtime():
                    err = ComponentState(
                        component_id="zapret",
                        status="error",
                        last_error="Не удалось выгрузить прежний драйвер WinDivert Zapret Hub.",
                    )
                    self._states["zapret"] = err
                    return err

            last_state: ComponentState | None = None
            for attempt in range(2):
                state = self.start_zapret_from_runtime(active_root, assume_clean=(attempt == 0))
                last_state = state
                new_proc = self._processes.get("zapret")
                new_pid = int(getattr(new_proc, "pid", 0) or 0) if new_proc is not None else 0
                if (
                    str(getattr(state, "status", "") or "") == "running"
                    and new_pid
                    and new_proc is not None
                    and self._zapret_process_stable(new_proc)
                ):
                    self.logging.log(
                        "info",
                        "Zapret cutover: candidate runtime is stable",
                        new_pid=new_pid,
                        old_pids=sorted(old_pids - {new_pid}),
                        attempt=attempt + 1,
                    )
                    return state

                self.logging.log(
                    "warning",
                    "Zapret cutover: candidate did not become stable",
                    attempt=attempt + 1,
                    error=str(getattr(state, "last_error", "") or "start_b_failed"),
                )
                self._soft_stop_zapret_image()
                self._image_running_cache.pop("winws.exe", None)
                self._purge_stale_zapret_runtime()
                self._wait_for_image_exit("winws.exe", attempts=20, delay=0.1)
                time.sleep(0.4)

            if previous_runtime is not None:
                restored = self.start_zapret_from_runtime(
                    previous_runtime,
                    assume_clean=False,
                    selected_script_name=previous_script_name or None,
                )
                restored_proc = self._processes.get("zapret")
                if (
                    str(getattr(restored, "status", "") or "") == "running"
                    and restored_proc is not None
                    and self._zapret_process_stable(restored_proc)
                ):
                    self.logging.log(
                        "warning",
                        "Zapret cutover: restored previous runtime after candidate failure",
                        runtime=str(previous_runtime),
                    )
                    return restored

            self.logging.log(
                "error",
                "Zapret cutover failed after recovery attempts",
                error=str(getattr(last_state, "last_error", "") or "start_b_failed"),
            )
            return last_state or ComponentState(component_id="zapret", status="error", last_error="Zapret restart failed")

    def _zapret_process_stable(self, process: subprocess.Popen[Any], *, attempts: int = 8, delay: float = 0.15) -> bool:
        """Confirm that the exact candidate PID survived the WinDivert hand-off."""
        pid = int(getattr(process, "pid", 0) or 0)
        if not pid:
            return False
        for _ in range(max(1, int(attempts))):
            if self._processes.get("zapret") is not process or process.poll() is not None:
                return False
            if not self._pid_running(pid):
                return False
            time.sleep(max(0.02, float(delay)))
        return self._processes.get("zapret") is process and process.poll() is None and self._pid_running(pid)

    def start_zapret_from_runtime(
        self,
        active_root: Path,
        *,
        assume_clean: bool = False,
        selected_script_name: str | None = None,
    ) -> ComponentState:
        """Start winws from an already-materialized runtime (no rebuild / no A wipe)."""
        component_id = "zapret"
        active_root = Path(active_root)
        if not assume_clean:
            if self._is_image_running("winws.exe"):
                self._soft_stop_zapret_image()
            if not self._purge_stale_zapret_runtime():
                state = ComponentState(
                    component_id=component_id,
                    status="error",
                    last_error="Не удалось выгрузить прежний драйвер WinDivert Zapret Hub.",
                )
                self._states[component_id] = state
                return state
        selected_option = self._resolve_selected_general_option()
        if selected_option is None:
            state = ComponentState(component_id=component_id, status="error", last_error="No general script found.")
            self._states[component_id] = state
            return state
        requested_script_name = str(selected_script_name or Path(selected_option["path"]).name)
        try:
            self._current_zapret_runtime = active_root
            self._apply_zapret_runtime_switches(active_root)
            active_script = active_root / requested_script_name
            if not active_script.exists():
                # Fall back to any general*.bat in the slot.
                bats = sorted(active_root.glob("general*.bat"))
                if not bats:
                    raise FileNotFoundError(f"No general script in staged runtime: {active_root}")
                active_script = bats[0]
            self._current_zapret_script_name = active_script.name
            self._ensure_zapret_user_lists(active_root / "lists")
            self._materialize_visible_merged_runtime(active_root)
            bin_dir = active_root / "bin"
            lists_dir = active_root / "lists"
            stable_driver_path = self._ensure_stable_windivert_driver(bin_dir)
            winws_command = self._extract_winws_command(active_script, bin_dir=bin_dir, lists_dir=lists_dir)
            if winws_command:
                winws_command[0] = str(stable_driver_path.parent / "winws.exe")
            allow_service_command_extensions = str(selected_option.get("bundle_id", "")) == "base"
            winws_command = self._apply_selected_service_command_extensions(
                winws_command,
                lists_dir=lists_dir,
                bin_dir=bin_dir,
                enabled=allow_service_command_extensions,
            )
            winws_command = self._apply_vpn_priority_to_command(winws_command, lists_dir=lists_dir)
            winws_command = self._apply_udp_port_exclusions_to_command(winws_command)
            if not winws_command:
                raise RuntimeError("Failed to parse winws command from staged runtime.")
            self._repair_windivert_image_paths(active_root, preferred_driver_path=stable_driver_path)
            process = subprocess.Popen(
                winws_command,
                cwd=str(stable_driver_path.parent),
                creationflags=self._creationflags,
                startupinfo=self._startupinfo,
                stdout=self._open_source_log_stream("zapret"),
                stderr=subprocess.STDOUT,
            )
            if self._job:
                self._job.assign_pid(process.pid)
            self._processes[component_id] = process
            # Require THIS pid to stay alive — any other winws (old A) must not count.
            alive = False
            for _ in range(12):
                if process.poll() is not None:
                    alive = False
                    break
                if self._pid_running(int(process.pid)):
                    alive = True
                    break
                time.sleep(0.08)
            if process.poll() is not None or not alive:
                log_hint = self._recent_source_log_error("zapret")
                self._close_source_log_stream("zapret")
                state = ComponentState(
                    component_id=component_id,
                    status="error",
                    last_error=log_hint or "winws did not start from staged runtime",
                )
                self._states[component_id] = state
                return state
            self._image_running_cache.pop("winws.exe", None)
            state = ComponentState(component_id=component_id, status="running", pid=process.pid)
            self._states[component_id] = state
            self._invalidate_state_cache()
            self.logging.log("info", "Zapret started from staged runtime", runtime=str(active_root), pid=process.pid)
            self._schedule_bypass_start_confirm(
                component_id,
                process,
                image_name="winws.exe",
                active_root=active_root,
                stable_driver_path=stable_driver_path,
            )
            return state
        except Exception as error:
            state = ComponentState(component_id=component_id, status="error", last_error=str(error))
            self._states[component_id] = state
            self.logging.log("error", "Zapret staged start failed", error=str(error), runtime=str(active_root))
            return state

    def _materialize_zapret_runtime(
        self,
        *,
        selected_bundle_root: Path,
        selected_bundle_id: str,
        selected_script_name: str,
    ) -> Path:
        active_root = self._next_active_runtime_dir()
        base_root = self.storage.paths.runtime_dir / "zapret-discord-youtube"
        if base_root.exists():
            shutil.copytree(base_root, active_root, dirs_exist_ok=True, ignore=self._runtime_copy_ignore)
        else:
            shutil.copytree(selected_bundle_root, active_root, dirs_exist_ok=True, ignore=self._runtime_copy_ignore)

        lists_target = active_root / "lists"
        bin_target = active_root / "bin"
        utils_target = active_root / "utils"
        lists_target.mkdir(parents=True, exist_ok=True)
        bin_target.mkdir(parents=True, exist_ok=True)
        utils_target.mkdir(parents=True, exist_ok=True)

        layered_bundles = self._get_zapret_bundles(enabled_only=True)
        bin_overlay_applied = False
        for bundle in layered_bundles:
            bundle_id = bundle["id"]
            bundle_root = Path(bundle["path"])
            include_bin_overlay = not bin_overlay_applied and self._bundle_has_bin_overlay(bundle_root)
            if bundle_id != "base":
                # Match 2.1.2: every enabled bundle is a complete runtime layer.
                self._overlay_zapret_bundle_runtime(active_root, bundle_root, include_bin_overlay=include_bin_overlay)
                bin_overlay_applied = bin_overlay_applied or include_bin_overlay
            lists_source = bundle_root / "lists"
            if not lists_source.exists():
                continue
            self._merge_lists_into_target(lists_target, lists_source)

        self._apply_selected_service_rules(active_root, allow_bin_overlay=not bin_overlay_applied)

        # Discord > Cloudflare: after service merge, always strip Discord CDN parent
        # ranges from the live ipset so hostlist-only Discord cannot be double-desynced.
        try:
            selected = {str(x) for x in (self.settings.get().selected_service_ids or [])}
            if "discord" in selected:
                self._strip_discord_cdn_from_ipset(lists_target)
        except Exception:
            pass

        selected_script = selected_bundle_root / selected_script_name
        if selected_script.exists():
            shutil.copy2(selected_script, active_root / selected_script.name)
        if selected_bundle_id == "unified-general":
            self._overlay_zapret_bundle_runtime(active_root, selected_bundle_root, include_bin_overlay=False)
            if selected_script.exists():
                shutil.copy2(selected_script, active_root / selected_script.name)

        self._apply_user_collection_overrides(lists_target)
        self._apply_gaming_set_list_overlays(lists_target)
        # After every overlay: restore any critical Flowseal bins a mod may have skipped.
        self._ensure_flowseal_critical_bins(active_root)
        # Guarantee the selected general bat is present (overlays / races must not leave an empty slot).
        if not (active_root / selected_script_name).is_file():
            if selected_script.is_file():
                shutil.copy2(selected_script, active_root / selected_script_name)
            else:
                bats = sorted(active_root.glob("general*.bat"))
                if not bats and base_root.exists():
                    for src in sorted((base_root).glob("general*.bat")):
                        shutil.copy2(src, active_root / src.name)
        self._materialize_visible_merged_runtime(active_root)
        return active_root

    def _overlay_zapret_bundle_runtime(self, active_root: Path, bundle_root: Path, *, include_bin_overlay: bool = True) -> None:
        for script in bundle_root.glob("*.bat"):
            if script.name.lower().startswith("service"):
                continue
            shutil.copy2(script, active_root / script.name)

        bin_source = bundle_root / "bin"
        if include_bin_overlay and bin_source.exists():
            self._replace_runtime_bin_data(active_root / "bin", bin_source)

        for folder_name in ("utils",):
            source_dir = bundle_root / folder_name
            target_dir = active_root / folder_name
            if not source_dir.exists():
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            for source in source_dir.glob("*"):
                if source.is_file():
                    shutil.copy2(source, target_dir / source.name)

    def _replace_runtime_bin_data(self, target_dir: Path, source_dir: Path) -> None:
        """Overlay ``source_dir`` *.bin onto ``target_dir`` without wiping base bins.

        Older Hub wiped every ``*.bin`` then copied the overlay. A partial mod/service
        overlay (missing ACTIVE_DISCORD_UDP.bin) made winws exit immediately with
        ``could not read ...ACTIVE_DISCORD_UDP.bin``. Merge keeps Flowseal base fakes.
        """
        if not source_dir.exists() or not source_dir.is_dir():
            return
        target_dir.mkdir(parents=True, exist_ok=True)
        for source in source_dir.glob("*.bin"):
            if source.is_file():
                shutil.copy2(source, target_dir / source.name)

    def _ensure_flowseal_critical_bins(self, active_root: Path) -> None:
        """Guarantee Discord/voice fake bins exist in the active runtime bin/."""
        base_bin = self.storage.paths.runtime_dir / "zapret-discord-youtube" / "bin"
        target = Path(active_root) / "bin"
        if not base_bin.is_dir():
            return
        target.mkdir(parents=True, exist_ok=True)
        for name in (
            "ACTIVE_DISCORD_UDP.bin",
            "ACTIVE_GAME_UDP.bin",
            "quic_initial_www_google_com.bin",
            "tls_clienthello_www_google_com.bin",
            "tls_clienthello_4pda_to.bin",
            "stun.bin",
        ):
            dest = target / name
            src = base_bin / name
            if dest.is_file() or not src.is_file():
                continue
            try:
                shutil.copy2(src, dest)
            except OSError:
                pass

    def _bundle_has_bin_overlay(self, bundle_root: Path) -> bool:
        bin_dir = bundle_root / "bin"
        if not bin_dir.exists() or not bin_dir.is_dir():
            return False
        return self._bin_dir_has_modified_data(bin_dir)

    def _bin_dir_has_modified_data(self, bin_dir: Path) -> bool:
        base_bin = self.storage.paths.runtime_dir / "zapret-discord-youtube" / "bin"
        for item in bin_dir.glob("*.bin"):
            if not item.is_file():
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

    def _materialize_visible_merged_runtime(self, active_root: Path) -> None:
        merged_root = self.storage.paths.merged_runtime_dir
        merged_root.mkdir(parents=True, exist_ok=True)
        target_root = merged_root / "zapret"
        temp_root = merged_root / f".zapret_sync_{int(time.time() * 1000)}"
        old_root = merged_root / f".zapret_old_{int(time.time() * 1000)}"
        shutil.rmtree(temp_root, ignore_errors=True)
        shutil.copytree(active_root, temp_root, dirs_exist_ok=True, ignore=self._runtime_copy_ignore)
        if not self._replace_visible_runtime_dir(temp_root, target_root, old_root):
            self.logging.log(
                "warning",
                "Visible merged runtime refresh skipped because Windows denied access",
                source=str(active_root),
                target=str(target_root),
            )
        shutil.rmtree(old_root, ignore_errors=True)
        shutil.rmtree(temp_root, ignore_errors=True)

    def _replace_visible_runtime_dir(self, temp_root: Path, target_root: Path, old_root: Path) -> bool:
        for attempt in range(6):
            try:
                if target_root.exists():
                    try:
                        target_root.replace(old_root)
                    except PermissionError:
                        self._force_stop_zapret_runtime()
                        self._move_or_quarantine_runtime_dir(target_root)
                    except OSError:
                        self._move_or_quarantine_runtime_dir(target_root)
                temp_root.replace(target_root)
                return True
            except PermissionError:
                self._force_stop_zapret_runtime()
                time.sleep(0.08 + attempt * 0.08)
            except OSError:
                time.sleep(0.08 + attempt * 0.08)
        try:
            if not target_root.exists():
                shutil.copytree(temp_root, target_root, dirs_exist_ok=True, ignore=self._runtime_copy_ignore)
                return True
        except OSError:
            pass
        return target_root.exists()

    def _move_or_quarantine_runtime_dir(self, target_root: Path) -> None:
        if not target_root.exists():
            return
        quarantine_root = Path(tempfile.gettempdir()) / "zapret_hub_runtime_cleanup"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        quarantine_target = quarantine_root / f"{target_root.name}_{int(time.time() * 1000)}"
        try:
            shutil.move(str(target_root), str(quarantine_target))
            shutil.rmtree(quarantine_target, ignore_errors=True)
            return
        except Exception:
            pass
        try:
            shutil.rmtree(target_root, ignore_errors=True)
        except Exception:
            pass

    def _runtime_copy_ignore(self, directory: str, names: list[str]) -> set[str]:
        ignored_names = {".git", ".github", "__pycache__", ".mypy_cache", ".pytest_cache"}
        ignored_suffixes = {".pyc", ".pyo"}
        return {name for name in names if name in ignored_names or Path(name).suffix.lower() in ignored_suffixes}

    def _merge_lists_into_target(self, target_lists: Path, source_lists: Path) -> None:
        for source in source_lists.glob("*.txt"):
            target = target_lists / source.name
            existing = self._read_list_lines(target)
            incoming = self._read_list_lines(source)
            merged = self._merge_with_conflict_resolution(target_lists, target.name.lower(), existing, incoming)
            target.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")

    def _merge_with_conflict_resolution(
        self,
        target_lists: Path,
        filename: str,
        existing: list[str],
        incoming: list[str],
    ) -> list[str]:
        conflict_map = {
            "list-general.txt": "list-exclude.txt",
            "list-exclude.txt": "list-general.txt",
            "ipset-all.txt": "ipset-exclude.txt",
            "ipset-exclude.txt": "ipset-all.txt",
            "list-general-user.txt": "list-exclude-user.txt",
            "list-exclude-user.txt": "list-general-user.txt",
            "ipset-all-user.txt": "ipset-exclude-user.txt",
            "ipset-exclude-user.txt": "ipset-all-user.txt",
        }
        merged: list[str] = []
        seen: set[str] = set()
        for line in [*existing, *incoming]:
            if not line or line in seen:
                continue
            seen.add(line)
            merged.append(line)
        opposite = conflict_map.get(filename)
        if not opposite:
            return merged
        opposite_path = target_lists / opposite
        if not opposite_path.exists():
            return merged
        opposite_values = set(self._read_list_lines(opposite_path))
        return [line for line in merged if line not in opposite_values]

    def _apply_user_collection_overrides(self, lists_dir: Path) -> None:
        overrides_path = self.storage.paths.data_dir / "file_overrides.json"
        raw = self.storage.read_json(overrides_path, default={}) or {}
        mapping = {
            "domains": "list-general.txt",
            "exclude_domains": "list-exclude.txt",
            "all_ips": "ipset-all.txt",
            "ips": "ipset-exclude.txt",
        }
        for kind, filename in mapping.items():
            target = lists_dir / filename
            values = self._read_list_lines(target)
            override = raw.get(kind, {}) if isinstance(raw, dict) else {}
            removed = {str(item).strip() for item in list((override or {}).get("removed", []) or []) if str(item).strip()}
            added = [str(item).strip() for item in list((override or {}).get("added", []) or []) if str(item).strip()]
            result = [item for item in values if item not in removed]
            seen = set(result)
            for item in added:
                if item in seen:
                    continue
                seen.add(item)
                result.append(item)
            target.write_text("\n".join(result) + ("\n" if result else ""), encoding="utf-8")

    def _promote_selected_catalog_domains_from_exclude(
        self,
        lists_dir: Path,
        selected_ids: list[str],
    ) -> None:
        """Remove selected-service catalog hosts from exclude lists so hostlist DPI applies."""
        protected: set[str] = set()
        for service_id in selected_ids:
            rule = SERVICE_RULES.get(str(service_id))
            if rule is None:
                continue
            for item in (*rule.list_general, *rule.list_google, *rule.health_hosts):
                host = str(item).strip().lower().rstrip(".")
                if host:
                    protected.add(host)
        if not protected:
            return

        def _matches(host: str) -> bool:
            return host in protected or any(host == p or host.endswith("." + p) for p in protected if p)

        for filename in ("list-exclude.txt", "list-exclude-user.txt"):
            path = lists_dir / filename
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            kept: list[str] = []
            changed = False
            for line in lines:
                host = line.strip().lower().rstrip(".")
                if host and not host.startswith("#") and _matches(host):
                    changed = True
                    continue
                kept.append(line.rstrip())
            if changed:
                path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        # Also scrub persistent user exclude in configs so the next materialize stays clean.
        try:
            from zapret_hub.services.orchestrator import zapret2_hub

            zapret2_hub.sanitize_classic_discord_pollution(Path(self.storage.paths.configs_dir))
        except Exception:
            pass

    def _strip_discord_cdn_from_ipset(self, lists_dir: Path) -> None:
        """Keep Discord hostlist-only: drop CDN parent ranges from ipset-all*."""
        ban = {
            "162.158.0.0/15",  # Cloudflare parent that covers Discord
            "162.159.128.0/20",  # Discord identity network
        }
        try:
            from zapret_hub.services.orchestrator import zapret2_hub

            ban |= {str(x).strip().lower() for x in zapret2_hub.BYPASS_SEED_NETWORKS}
        except Exception:
            pass
        for filename in ("ipset-all.txt", "ipset-all-user.txt"):
            path = lists_dir / filename
            if not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue
            kept = [row for row in lines if row.strip().lower() not in ban]
            if len(kept) != len(lines):
                path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")

    def _apply_selected_service_rules(self, active_root: Path, *, allow_bin_overlay: bool = True) -> None:
        selected_ids = list(self.settings.get().selected_service_ids or [])
        if not selected_ids:
            return
        lists_dir = active_root / "lists"
        lists_dir.mkdir(parents=True, exist_ok=True)
        # If Auto previously excluded Discord/YouTube catalog hosts, promote them
        # back before hostlist merge — otherwise conflict resolution drops them
        # from list-general and Discord never gets DPI (looks like "Zapret on but dead").
        self._promote_selected_catalog_domains_from_exclude(lists_dir, selected_ids)
        mapping = {
            "list-general.txt": "list_general",
            "list-exclude.txt": "list_exclude",
            "list-google.txt": "list_google",
            "ipset-all.txt": "ipset_all",
            "ipset-exclude.txt": "ipset_exclude",
        }
        for filename, attr in mapping.items():
            incoming: list[str] = []
            for service_id in selected_ids:
                rule = SERVICE_RULES.get(str(service_id))
                if rule is None:
                    continue
                values = list(getattr(rule, attr) or ())
                # Discord must stay hostlist-only. Cloudflare's 162.158.0.0/15 covers
                # Discord's 162.159.128.0/20 — a second 443 ipset desync kills Discord.
                if (
                    attr == "ipset_all"
                    and service_id == "cloudflare"
                    and "discord" in {str(x) for x in selected_ids}
                ):
                    values = [
                        item
                        for item in values
                        if str(item).strip().lower()
                        not in {"162.158.0.0/15", "162.159.128.0/20"}
                    ]
                incoming.extend(values)
            if not incoming:
                continue
            target = lists_dir / filename
            existing = self._read_list_lines(target)
            merged = self._merge_with_conflict_resolution(lists_dir, filename, existing, incoming)
            target.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
        if "discord" in {str(x) for x in selected_ids}:
            self._strip_discord_cdn_from_ipset(lists_dir)
        for service_id in selected_ids:
            rule = SERVICE_RULES.get(str(service_id))
            if rule is None:
                continue
            for filename, lines in rule.extra_lists:
                safe_name = Path(filename).name
                if not safe_name.endswith(".txt"):
                    continue
                target = lists_dir / safe_name
                existing = self._read_list_lines(target)
                merged = self._merge_with_conflict_resolution(lists_dir, safe_name.lower(), existing, list(lines))
                target.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
            for filename, relative_source in getattr(rule, "extra_list_files", ()):
                safe_name = Path(filename).name
                if not safe_name.endswith(".txt"):
                    continue
                source = (self.storage.paths.install_root / str(relative_source)).resolve()
                if not source.exists() or not source.is_file():
                    continue
                incoming = self._read_list_lines(source)
                if not incoming:
                    continue
                target = lists_dir / safe_name
                existing = self._read_list_lines(target)
                merged = self._merge_with_conflict_resolution(lists_dir, safe_name.lower(), existing, incoming)
                target.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
            bin_overlay_dir = str(getattr(rule, "bin_overlay_dir", "") or "").strip()
            if allow_bin_overlay and bin_overlay_dir:
                source_dir = (self.storage.paths.install_root / bin_overlay_dir).resolve()
                if source_dir.exists() and source_dir.is_dir() and self._bin_dir_has_modified_data(source_dir):
                    self._replace_runtime_bin_data(active_root / "bin", source_dir)
                    allow_bin_overlay = False
        self._merge_selected_service_hosts(active_root)

    def _apply_gaming_set_list_overlays(self, lists_dir: Path) -> None:
        variant = str(getattr(self.settings.get(), "zapret_gaming_set", "stun-wide-base") or "stun-wide-base")
        if variant != "stun-wide-base-local-exclude":
            return
        source = self.storage.paths.install_root / "sample_data" / "default_services" / "gaming" / "lists" / "ipset-local-exclude.txt"
        if not source.exists():
            return
        target = lists_dir / "ipset-exclude.txt"
        existing = self._read_list_lines(target)
        incoming = self._read_list_lines(source)
        merged: list[str] = []
        seen: set[str] = set()
        for line in [*existing, *incoming]:
            if not line or line in seen:
                continue
            seen.add(line)
            merged.append(line)
        target.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")

    def _merge_selected_service_hosts(self, active_root: Path) -> None:
        selected_ids = list(self.settings.get().selected_service_ids or [])
        incoming: list[str] = []
        for service_id in selected_ids:
            rule = SERVICE_RULES.get(str(service_id))
            if rule is None:
                continue
            incoming.extend(rule.hosts)
        if not incoming:
            return
        service_dir = active_root / ".service"
        service_dir.mkdir(parents=True, exist_ok=True)
        target = service_dir / "hosts"
        existing = self._read_hosts_lines(target)
        merged: list[str] = []
        seen: set[str] = set()
        for line in [*existing, *incoming]:
            if not line.strip() or line.lstrip().startswith("#"):
                merged.append(line)
                continue
            key = " ".join(line.split()).lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(line)
        target.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")

    def _read_hosts_lines(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return [raw.rstrip() for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines()]

    def _apply_selected_service_command_extensions(
        self,
        command: list[str],
        *,
        lists_dir: Path,
        bin_dir: Path,
        enabled: bool = True,
    ) -> list[str]:
        if not command or not enabled:
            return command
        selected_ids = list(self.settings.get().selected_service_ids or [])
        _game_filter, game_filter_tcp, game_filter_udp = self._get_game_filter_values(lists_dir.parent)
        if "fortnite" in {str(item) for item in selected_ids}:
            command = self._inject_fortnite_ping_ttl(command, game_filter_udp)
        extra_args: list[str] = []
        seen_segments: set[tuple[str, ...]] = set()
        for service_id in selected_ids:
            rule = SERVICE_RULES.get(str(service_id))
            if rule is None or not rule.winws_args:
                continue
            segment = tuple(self._gaming_set_args() if str(service_id) == "gaming" else rule.winws_args)
            if segment in seen_segments:
                continue
            seen_segments.add(segment)
            for arg in segment:
                extra_args.append(
                    str(arg)
                    .replace("{lists}", str(lists_dir))
                    .replace("{bin}", str(bin_dir))
                    .replace("{game_tcp}", game_filter_tcp)
                    .replace("{game_udp}", game_filter_udp)
                )
        if not extra_args:
            return command
        return [*command, *extra_args]

    def _gaming_set_args(self) -> tuple[str, ...]:
        rule = SERVICE_RULES.get("gaming")
        if rule is None:
            return ()
        segments = self._split_winws_arg_segments(rule.winws_args)
        if len(segments) < 6:
            return tuple(rule.winws_args)
        base_tcp, base_udp, wide_udp, wide_tcp, stun_udp, stun_tcp = segments[:6]
        variants: dict[str, list[list[str]]] = {
            "base": [base_tcp, base_udp],
            "base-wide-stun": [base_tcp, base_udp, wide_udp, wide_tcp, stun_udp, stun_tcp],
            "wide-stun-base": [wide_udp, wide_tcp, stun_udp, stun_tcp, base_tcp, base_udp],
            "stun-wide-base": [stun_udp, stun_tcp, wide_udp, wide_tcp, base_tcp, base_udp],
            "stun-wide-base-local-exclude": [stun_udp, stun_tcp, wide_udp, wide_tcp, base_tcp, base_udp],
            "udp-first": [base_udp, wide_udp, stun_udp, base_tcp, wide_tcp, stun_tcp],
            "tcp-first": [base_tcp, wide_tcp, stun_tcp, base_udp, wide_udp, stun_udp],
            "stun-between": [base_tcp, stun_tcp, wide_tcp, base_udp, stun_udp, wide_udp],
        }
        variant = str(getattr(self.settings.get(), "zapret_gaming_set", "stun-wide-base") or "stun-wide-base")
        ordered = variants.get(variant)
        if not ordered:
            ordered = variants["stun-wide-base"]
        return self._join_winws_arg_segments(ordered)

    def _split_winws_arg_segments(self, args: tuple[str, ...]) -> list[list[str]]:
        segments: list[list[str]] = []
        current: list[str] = []
        for arg in args:
            if arg == "--new":
                if current:
                    segments.append(current)
                current = []
                continue
            current.append(arg)
        if current:
            segments.append(current)
        return segments

    def _join_winws_arg_segments(self, segments: list[list[str]]) -> tuple[str, ...]:
        result: list[str] = []
        for segment in segments:
            if not segment:
                continue
            result.append("--new")
            result.extend(segment)
        return tuple(result)

    def _inject_fortnite_ping_ttl(self, command: list[str], game_filter_udp: str) -> list[str]:
        if "--dpi-desync-ttl=10" in command:
            return command
        udp_values = {game_filter_udp, "%GameFilter%", "%GameFilterUDP%"}
        result = list(command)
        segment_start = 0
        for index, arg in enumerate(result):
            if index == 0 or arg == "--new":
                segment_start = index + (1 if arg == "--new" else 0)
                continue
            if not arg.startswith("--filter-udp="):
                continue
            ports = arg.split("=", 1)[1]
            if ports not in udp_values and game_filter_udp not in {item.strip() for item in ports.split(",")}:
                continue
            segment_end = next((pos for pos in range(index + 1, len(result)) if result[pos] == "--new"), len(result))
            segment = result[segment_start:segment_end]
            if "--dpi-desync=fake" not in segment:
                continue
            insert_at = segment_start + segment.index("--dpi-desync=fake") + 1
            result.insert(insert_at, "--dpi-desync-ttl=10")
            return result
        return result

    def _read_list_lines(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        lines: list[str] = []
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line:
                continue
            lines.append(line)
        return lines

    def _capture_diagnostic_settings(self) -> dict[str, object]:
        settings = self.settings.get()
        return {
            "selected_zapret_general": settings.selected_zapret_general,
            "zapret_ipset_mode": settings.zapret_ipset_mode,
            "zapret_game_filter_mode": settings.zapret_game_filter_mode,
            "zapret_udp_exclude_ports": settings.zapret_udp_exclude_ports,
        }

    def _restore_diagnostic_settings(self, snapshot: dict[str, object]) -> None:
        self.settings.update(
            selected_zapret_general=str(snapshot.get("selected_zapret_general", "") or ""),
            zapret_ipset_mode=str(snapshot.get("zapret_ipset_mode", "loaded") or "loaded"),
            zapret_game_filter_mode=str(snapshot.get("zapret_game_filter_mode", "disabled") or "disabled"),
            zapret_udp_exclude_ports=str(snapshot.get("zapret_udp_exclude_ports", "")),
        )

    def _prepare_diagnostic_runtime(self, *, general_id: str, ipset_mode: str, game_mode: str) -> bool:
        original_running = self._is_image_running("winws.exe")
        if original_running:
            self.stop_component("zapret")
        self.settings.update(
            selected_zapret_general=general_id,
            zapret_ipset_mode=ipset_mode,
            zapret_game_filter_mode=game_mode,
        )
        return original_running

    def run_single_general_diagnostic(
        self,
        general_id: str,
        *,
        ipset_mode: str = "loaded",
        game_mode: str = "tcpudp",
        progress_callback: callable | None = None,
        stop_callback: callable | None = None,
    ) -> dict[str, object]:
        options = {item["id"]: item for item in self.list_zapret_generals()}
        option = options.get(general_id)
        if option is None:
            return {"status": "error", "error": "general not found", "passed_targets": 0, "total_targets": 0}
        settings_snapshot = self._capture_diagnostic_settings()
        self._diagnostic_runtime_override = True
        original_running = self._prepare_diagnostic_runtime(
            general_id=general_id,
            ipset_mode=ipset_mode,
            game_mode=game_mode,
        )
        try:
            outcome = self._run_general_connectivity_check(
                general_id,
                stop_callback=stop_callback,
                targets=self._load_standard_test_targets(),
                progress_callback=progress_callback,
            )
            return {
                "id": option["id"],
                "name": option["name"],
                "bundle": option["bundle"],
                "status": str(outcome["status"]),
                "error": str(outcome.get("error", "")),
                "passed_targets": int(outcome.get("passed_targets", 0)),
                "total_targets": int(outcome.get("total_targets", 0)),
                "failed_targets": list(outcome.get("failed_targets", []) or []),
                "ipset_mode": ipset_mode,
                "game_mode": game_mode,
            }
        finally:
            self.stop_component("zapret")
            self._restore_diagnostic_settings(settings_snapshot)
            self._diagnostic_runtime_override = False
            if original_running and str(settings_snapshot.get("selected_zapret_general", "")):
                self.start_component("zapret")

    def run_general_diagnostics(
        self,
        progress_callback: callable | None = None,
        stop_callback: callable | None = None,
    ) -> list[dict[str, str]]:
        options = self.list_zapret_generals()
        options = prioritize_generals_for_services(options, self.settings.get().selected_service_ids)
        if not options:
            return []

        self.reset_diagnostic_abort()
        settings_snapshot = self._capture_diagnostic_settings()
        original_running = self._is_image_running("winws.exe")
        results: list[dict[str, str]] = []
        targets = self._load_standard_test_targets()
        per_general_steps = max(2, len(targets) + 1)
        total_steps = len(options) * per_general_steps
        diagnostic_token = self._diagnostic_token

        def _should_stop() -> bool:
            if self._diagnostic_abort.is_set():
                return True
            if diagnostic_token != self._diagnostic_token:
                return True
            if stop_callback is not None and bool(stop_callback()):
                return True
            return False

        try:
            self._diagnostic_runtime_override = True
            if original_running:
                self.stop_component("zapret")
            for index, option in enumerate(options, start=1):
                if _should_stop():
                    break
                self.settings.update(
                    selected_zapret_general=option["id"],
                    zapret_ipset_mode=str(option.get("ipset_mode", "loaded") or "loaded"),
                    zapret_game_filter_mode=str(option.get("game_mode", "tcpudp") or "tcpudp"),
                )
                base_step = (index - 1) * per_general_steps
                if progress_callback is not None:
                    progress_callback(base_step + 1, total_steps, option["name"])
                outcome = self._run_general_connectivity_check(
                    option["id"],
                    stop_callback=_should_stop,
                    targets=targets,
                    progress_callback=(
                        lambda completed, total, target_name, *, _base=base_step, _steps=per_general_steps, _option=option: (
                            progress_callback(
                                min(_base + 1 + completed, _base + _steps),
                                total_steps,
                                f"{_option['name']} - {target_name} ({completed}/{total})",
                            )
                            if progress_callback is not None
                            else None
                        )
                    ),
                )
                if progress_callback is not None:
                    progress_callback(base_step + per_general_steps, total_steps, option["name"])
                results.append(
                    {
                        "id": option["id"],
                        "name": option["name"],
                        "bundle": option["bundle"],
                        "status": str(outcome["status"]),
                        "error": str(outcome.get("error", "")),
                        "passed_targets": str(outcome.get("passed_targets", 0)),
                        "total_targets": str(outcome.get("total_targets", 0)),
                        "failed_targets": list(outcome.get("failed_targets", []) or []),
                        "ipset_mode": str(option.get("ipset_mode", "loaded") or "loaded"),
                        "game_mode": str(option.get("game_mode", "tcpudp") or "tcpudp"),
                    }
                )
                try:
                    self.stop_component("zapret")
                except Exception:
                    pass
                try:
                    self._kill_image("winws.exe")
                except Exception:
                    pass
                # Stop after the first working general — probing every script looks endless.
                if str(outcome.get("status") or "") == "ok":
                    break
                if _should_stop():
                    break
        finally:
            cancelled = _should_stop()
            self._diagnostic_runtime_override = False
            try:
                self.stop_component("zapret")
            except Exception:
                pass
            try:
                self._kill_image("winws.exe")
            except Exception:
                pass
            self._restore_diagnostic_settings(settings_snapshot)
            # Never leave diagnostic winws running. Restore user power only if
            # diagnostics finished cleanly and zapret was already on before.
            if (not cancelled) and original_running and str(settings_snapshot.get("selected_zapret_general", "")):
                try:
                    self.start_component("zapret")
                except Exception:
                    pass
            self._invalidate_state_cache()

        return results

    def run_settings_diagnostics(
        self,
        progress_callback: callable | None = None,
        stop_callback: callable | None = None,
    ) -> dict[str, object]:
        original = self.settings.get()
        general_id = str(original.selected_zapret_general or "").strip()
        if not general_id:
            return {"results": [], "status": "error", "error": "No selected general"}
        ipset_modes = ["loaded", "none", "any"]
        game_modes = ["disabled", "tcpudp", "tcp", "udp"]
        combinations = [(ipset, game) for ipset in ipset_modes for game in game_modes]
        targets = self._load_standard_test_targets()
        results: list[dict[str, object]] = []
        total = max(1, len(combinations))
        original_running = self._is_image_running("winws.exe")
        try:
            if original_running:
                self.stop_component("zapret")
            for index, (ipset_mode, game_mode) in enumerate(combinations, start=1):
                if stop_callback is not None and stop_callback():
                    break
                self.settings.update(
                    selected_zapret_general=general_id,
                    zapret_ipset_mode=ipset_mode,
                    zapret_game_filter_mode=game_mode,
                )
                started_at = time.time()
                outcome = self._run_general_connectivity_check(general_id, stop_callback=stop_callback, targets=targets)
                elapsed = round(time.time() - started_at, 2)
                passed = int(outcome.get("passed_targets", 0))
                total_targets = int(outcome.get("total_targets", 0))
                results.append(
                    {
                        "ipset_mode": ipset_mode,
                        "game_mode": game_mode,
                        "status": str(outcome.get("status", "error")),
                        "passed_targets": passed,
                        "total_targets": total_targets,
                        "elapsed": elapsed,
                    }
                )
                if progress_callback is not None:
                    progress_callback(index, total, f"{ipset_mode} / {game_mode}")
                self.stop_component("zapret")
        finally:
            self.settings.update(
                selected_zapret_general=original.selected_zapret_general,
                zapret_ipset_mode=original.zapret_ipset_mode,
                zapret_game_filter_mode=original.zapret_game_filter_mode,
            )
            if original_running and general_id:
                self.start_component("zapret")

        ranked = sorted(
            results,
            key=lambda item: (-int(item.get("passed_targets", 0)), float(item.get("elapsed", 999999.0))),
        )
        best = ranked[0] if ranked else None
        return {"results": ranked, "best": best, "status": "ok" if ranked else "error"}

    def with_github_connectivity_recovery(self, operation: Callable[[], Any], purpose: str) -> Any:
        """Run a GitHub network op; on timeout/block briefly lift via classic Zapret+GitHub only.

        Must always restore the previous bypass (including Zapret2). Starting classic
        Zapret stops winws2 — previous recovery forgot to bring Zapret2 back.
        """
        snapshot = self._capture_github_recovery_snapshot()
        errors: list[str] = []
        try:
            result = self._try_github_operation(operation, errors, f"{purpose}: current")
            if result[0]:
                return result[1]

            # Timed out / blocked: one temporary profile only — classic zapret + github
            # service list. No general roulette, no extra knobs.
            self.logging.log(
                "info",
                "GitHub blocked — temporary Zapret+GitHub for recovery",
                purpose=purpose,
                was_zapret2=bool(snapshot.get("was_zapret2_running")),
                runtime=str(snapshot.get("selected_runtime_mode") or ""),
            )
            self._arm_github_only_zapret_profile(snapshot)
            time.sleep(1.0)
            result = self._try_github_operation(operation, errors, f"{purpose}: zapret+github")
            if result[0]:
                return result[1]
        finally:
            self._restore_github_recovery_snapshot(snapshot)
        raise RuntimeError("; ".join(errors) or "GitHub request failed after Zapret recovery")

    def _try_github_operation(self, operation: Callable[[], Any], errors: list[str], label: str) -> tuple[bool, Any]:
        try:
            return True, operation()
        except Exception as error:
            errors.append(f"{label}: {error}")
            self.logging.log("warning", "GitHub recovery attempt failed", attempt=label, error=str(error))
            if not is_recoverable_github_error(error):
                raise
            time.sleep(0.8)
            return False, None

    def _capture_github_recovery_snapshot(self) -> dict[str, object]:
        settings = self.settings.get()
        return {
            "selected_zapret_general": settings.selected_zapret_general,
            "zapret_ipset_mode": settings.zapret_ipset_mode,
            "zapret_game_filter_mode": settings.zapret_game_filter_mode,
            "zapret_udp_exclude_ports": settings.zapret_udp_exclude_ports,
            "selected_service_ids": list(settings.selected_service_ids or []),
            "selected_runtime_mode": str(settings.selected_runtime_mode or "zapret"),
            "was_zapret_running": self._is_image_running("winws.exe"),
            "was_zapret2_running": self._is_image_running("winws2.exe"),
            # Legacy key kept for any external callers.
            "was_running": self._is_image_running("winws.exe"),
        }

    def _arm_github_only_zapret_profile(self, snapshot: dict[str, object]) -> None:
        """Start classic Zapret with only the GitHub service selected (ipset any)."""
        general_id = str(snapshot.get("selected_zapret_general", "") or "").strip()
        if not general_id:
            generals = self.list_zapret_generals()
            general_id = str((generals[0] if generals else {}).get("id", "") or "")
        # Keep current general if known — only swap services/ipset for GitHub reachability.
        self.settings.update(
            selected_zapret_general=general_id,
            zapret_ipset_mode="any",
            zapret_game_filter_mode="disabled",
            selected_service_ids=["github"],
            selected_runtime_mode="zapret",
        )
        try:
            # start_component("zapret") stops zapret2 — intentional for the brief window.
            self.start_component("zapret")
        except Exception as error:
            self.logging.log("warning", "Failed to start temporary Zapret+GitHub profile", error=str(error))

    def _restore_github_recovery_snapshot(self, snapshot: dict[str, object], *, restart: bool | None = None) -> None:
        del restart  # always restore from snapshot flags
        self.settings.update(
            selected_zapret_general=str(snapshot.get("selected_zapret_general", "") or ""),
            zapret_ipset_mode=str(snapshot.get("zapret_ipset_mode", "loaded") or "loaded"),
            zapret_game_filter_mode=str(snapshot.get("zapret_game_filter_mode", "disabled") or "disabled"),
            zapret_udp_exclude_ports=str(snapshot.get("zapret_udp_exclude_ports", "")),
            selected_service_ids=list(snapshot.get("selected_service_ids") or []),
            selected_runtime_mode=str(snapshot.get("selected_runtime_mode") or "zapret"),
        )
        want_zapret2 = bool(snapshot.get("was_zapret2_running"))
        want_zapret = bool(snapshot.get("was_zapret_running")) or bool(snapshot.get("was_running"))
        try:
            if want_zapret2:
                self.stop_component("zapret")
                self.start_component("zapret2")
            elif want_zapret:
                self.stop_component("zapret2")
                self.start_component("zapret")
            else:
                self.stop_component("zapret")
                if self._is_image_running("winws2.exe"):
                    self.stop_component("zapret2")
        except Exception as error:
            self.logging.log("warning", "Failed to restore bypass after GitHub recovery", error=str(error))

    def _apply_github_recovery_settings(self, **changes: str) -> None:
        current = self.settings.get()
        for key, value in changes.items():
            setattr(current, key, value)

    def _github_recovery_candidates(self, snapshot: dict[str, object]) -> list[dict[str, str]]:
        del snapshot
        # Kept as an empty stub — recovery no longer iterates generals.
        return []

    def fetch_latest_zapret_release(self) -> dict[str, str]:
        """Resolve the newest Flowseal release (for update checks / install latest)."""
        releases = self.list_zapret_releases(limit=1)
        if releases:
            item = releases[0]
            return {
                "latest_version": str(item.get("version") or ""),
                "asset_url": str(item.get("asset_url") or ""),
                "asset_name": str(item.get("asset_name") or ""),
                "zipball_url": str(item.get("zipball_url") or ""),
                "tag": str(item.get("tag") or ""),
            }
        # Offline / API failure: fall back to Hub default pin.
        return {
            "latest_version": PINNED_ZAPRET_VERSION,
            "asset_url": PINNED_ZAPRET_ZIP_URL,
            "asset_name": f"zapret-discord-youtube-{PINNED_ZAPRET_VERSION}.zip",
            "zipball_url": PINNED_ZAPRET_ZIPBALL_URL,
            "tag": PINNED_ZAPRET_TAG,
            "pinned": "1",
        }

    def _component_releases_cache_path(self, key: str) -> Path | None:
        try:
            return self.storage.paths.cache_dir / f"component_releases_{key}.json"
        except Exception:
            return None

    def _releases_mem(self) -> dict[str, tuple[float, list[dict[str, str]]]]:
        mem = getattr(self, "_component_releases_mem", None)
        if not isinstance(mem, dict):
            mem = {}
            self._component_releases_mem = mem
        return mem

    def _load_component_releases_cache(self, key: str, *, max_age_s: float = 6 * 3600) -> list[dict[str, str]]:
        now = time.time()
        mem = self._releases_mem()
        cached = mem.get(key)
        if cached is not None and (now - float(cached[0])) <= max_age_s and cached[1]:
            return [dict(item) for item in cached[1]]
        path = self._component_releases_cache_path(key)
        if path is None:
            return []
        try:
            payload = self.storage.read_json(path, default=None)
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            return []
        saved_at = float(payload.get("saved_at") or 0)
        items = payload.get("items")
        if saved_at <= 0 or (now - saved_at) > max_age_s or not isinstance(items, list) or not items:
            return []
        out = [dict(item) for item in items if isinstance(item, dict)]
        if out:
            mem[key] = (saved_at, out)
        return [dict(item) for item in out]

    def _save_component_releases_cache(self, key: str, items: list[dict[str, str]]) -> None:
        clean = [dict(item) for item in items if isinstance(item, dict)]
        if not clean:
            return
        now = time.time()
        self._releases_mem()[key] = (now, clean)
        path = self._component_releases_cache_path(key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.storage.write_json(path, {"saved_at": now, "items": clean})
        except Exception as error:
            try:
                self.logging.log("warning", "Failed to cache component releases", key=key, error=str(error))
            except Exception:
                pass

    def _fetch_release_atom_entries(self, repository: str, *, limit: int = 30) -> list[dict[str, str]]:
        """Parse GitHub releases.atom (unauthenticated) into version tags newest-first."""
        feed_url = f"https://github.com/{repository}/releases.atom"
        payload = self.github.github_bytes(feed_url, timeout=20, purpose=f"{repository}-release-feed")
        root = ET.fromstring(payload)
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        out: list[dict[str, str]] = []
        marker = "/releases/tag/"
        for entry in root.findall("atom:entry", namespace):
            if len(out) >= max(1, int(limit)):
                break
            link = entry.find("atom:link[@rel='alternate']", namespace)
            href = str(link.get("href") if link is not None else "")
            tag = urllib.parse.unquote(href.split(marker, 1)[1]).strip() if marker in href else ""
            if not tag:
                title = entry.findtext("atom:title", default="", namespaces=namespace).strip()
                tag = title.rsplit(" ", 1)[-1].strip()
            version = tag.lstrip("vV")
            if not version:
                continue
            published = entry.findtext("atom:updated", default="", namespaces=namespace) or entry.findtext(
                "atom:published", default="", namespaces=namespace
            )
            out.append(
                {
                    "version": version,
                    "tag": tag or version,
                    "published_at": str(published or ""),
                    "prerelease": "0",
                    "recommended": "1" if not out else "0",
                }
            )
        return out

    def list_zapret_releases(self, *, limit: int = 25) -> list[dict[str, str]]:
        """List Flowseal zapret-discord-youtube releases (newest first)."""
        repository = "Flowseal/zapret-discord-youtube"
        capped = max(1, min(int(limit), 40))
        cache_key = "zapret"
        api_url = f"https://api.github.com/repos/{repository}/releases?per_page={capped}"
        try:
            payload = self.github.github_json(api_url, timeout=25, purpose="zapret-releases")
        except Exception as error:
            self.logging.log("warning", "Zapret releases API failed", error=str(error))
            cached = self._load_component_releases_cache(cache_key)
            if cached:
                self.logging.log("info", "Using cached Zapret releases after API failure", count=len(cached))
                return cached[:capped]
            try:
                atom_items = self._fetch_release_atom_entries(repository, limit=capped)
            except Exception as atom_error:
                self.logging.log("warning", "Zapret releases atom fallback failed", error=str(atom_error))
                atom_items = []
            if atom_items:
                out: list[dict[str, str]] = []
                for item in atom_items:
                    version = str(item.get("version") or "")
                    tag = str(item.get("tag") or version)
                    out.append(
                        {
                            "version": version,
                            "tag": tag,
                            "asset_url": (
                                f"https://github.com/{repository}/releases/download/"
                                f"{urllib.parse.quote(tag)}/zapret-discord-youtube-{urllib.parse.quote(version)}.zip"
                            ),
                            "asset_name": f"zapret-discord-youtube-{version}.zip",
                            "zipball_url": (
                                f"https://codeload.github.com/{repository}/zip/refs/tags/{urllib.parse.quote(tag)}"
                            ),
                            "published_at": str(item.get("published_at") or ""),
                            "prerelease": "0",
                            "recommended": "1" if version == PINNED_ZAPRET_VERSION else "0",
                        }
                    )
                if out:
                    # Prefer Hub pin as recommended when present.
                    for item in out:
                        item["recommended"] = "1" if item.get("version") == PINNED_ZAPRET_VERSION else "0"
                    if not any(item.get("recommended") == "1" for item in out):
                        out[0]["recommended"] = "1"
                    self._save_component_releases_cache(cache_key, out)
                    return out[:capped]
            return [
                {
                    "version": PINNED_ZAPRET_VERSION,
                    "tag": PINNED_ZAPRET_TAG,
                    "asset_url": PINNED_ZAPRET_ZIP_URL,
                    "asset_name": f"zapret-discord-youtube-{PINNED_ZAPRET_VERSION}.zip",
                    "zipball_url": PINNED_ZAPRET_ZIPBALL_URL,
                    "published_at": "",
                    "prerelease": "0",
                    "recommended": "1",
                }
            ]
        if not isinstance(payload, list):
            cached = self._load_component_releases_cache(cache_key)
            return cached[:capped] if cached else []
        out = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if bool(item.get("draft")):
                continue
            tag = str(item.get("tag_name") or "").strip()
            version = tag.lstrip("vV") or str(item.get("name") or "").strip().lstrip("vV")
            if not version:
                continue
            assets = [a for a in list(item.get("assets") or []) if isinstance(a, dict)]
            zip_asset = next(
                (
                    a
                    for a in assets
                    if str(a.get("name") or "").lower().endswith(".zip")
                    and "zapret-discord-youtube" in str(a.get("name") or "").lower()
                ),
                None,
            )
            if zip_asset is None:
                zip_asset = next(
                    (a for a in assets if str(a.get("name") or "").lower().endswith(".zip")),
                    None,
                )
            asset_url = str((zip_asset or {}).get("browser_download_url") or "").strip()
            asset_name = str((zip_asset or {}).get("name") or "").strip() or f"zapret-discord-youtube-{version}.zip"
            if not asset_url:
                asset_url = (
                    f"https://github.com/{repository}/releases/download/"
                    f"{urllib.parse.quote(tag)}/zapret-discord-youtube-{urllib.parse.quote(version)}.zip"
                )
            zipball = str(item.get("zipball_url") or "").strip() or (
                f"https://codeload.github.com/{repository}/zip/refs/tags/{urllib.parse.quote(tag)}"
            )
            out.append(
                {
                    "version": version,
                    "tag": tag or version,
                    "asset_url": asset_url,
                    "asset_name": asset_name,
                    "zipball_url": zipball,
                    "published_at": str(item.get("published_at") or item.get("created_at") or ""),
                    "prerelease": "1" if bool(item.get("prerelease")) else "0",
                    "recommended": "1" if version == PINNED_ZAPRET_VERSION else "0",
                }
            )
        if out:
            self._save_component_releases_cache(cache_key, out)
        return out

    def ensure_pinned_zapret_runtime(self, *, force: bool = False) -> dict[str, str]:
        """Install Hub default Zapret only when runtime is missing (never overwrite user choice)."""
        current = str(self.storage._detect_zapret_version() or "").strip()
        runtime_root = self.storage.paths.runtime_dir / "zapret-discord-youtube"
        has_bin = (runtime_root / "bin").exists()
        if not force and current and has_bin:
            return {"status": "up-to-date", "version": current}
        if not force and has_bin and not current:
            # Runtime present but version unknown — leave it alone.
            return {"status": "up-to-date", "version": current or "unknown"}
        self.logging.log(
            "info",
            "Ensuring pinned Zapret runtime",
            current=current,
            pinned=PINNED_ZAPRET_VERSION,
        )
        return self._install_zapret_archive(
            version=PINNED_ZAPRET_VERSION,
            candidates=[
                (PINNED_ZAPRET_ZIP_URL, f"zapret-discord-youtube-{PINNED_ZAPRET_VERSION}.zip"),
                (PINNED_ZAPRET_ZIPBALL_URL, "zapret-source.zip"),
            ],
        )

    def install_zapret_version(self, version: str) -> dict[str, str]:
        """Download and install a specific Flowseal Zapret release (upgrade or rollback)."""
        wanted = str(version or "").strip().lstrip("vV")
        if not wanted:
            return {"status": "error", "error": "Version is required"}
        current = str(self.storage._detect_zapret_version() or "").strip()
        if current and current == wanted:
            return {"status": "up-to-date", "version": current}

        release: dict[str, str] | None = None
        for item in self.list_zapret_releases(limit=40):
            if str(item.get("version") or "").strip() == wanted or str(item.get("tag") or "").strip().lstrip("vV") == wanted:
                release = item
                break
        if release is None and wanted == PINNED_ZAPRET_VERSION:
            release = {
                "version": PINNED_ZAPRET_VERSION,
                "tag": PINNED_ZAPRET_TAG,
                "asset_url": PINNED_ZAPRET_ZIP_URL,
                "asset_name": f"zapret-discord-youtube-{PINNED_ZAPRET_VERSION}.zip",
                "zipball_url": PINNED_ZAPRET_ZIPBALL_URL,
            }
        if release is None:
            # Best-effort direct URLs when the release list missed the tag.
            tag = wanted
            release = {
                "version": wanted,
                "tag": tag,
                "asset_url": (
                    "https://github.com/Flowseal/zapret-discord-youtube/releases/download/"
                    f"{urllib.parse.quote(tag)}/zapret-discord-youtube-{urllib.parse.quote(wanted)}.zip"
                ),
                "asset_name": f"zapret-discord-youtube-{wanted}.zip",
                "zipball_url": (
                    f"https://codeload.github.com/Flowseal/zapret-discord-youtube/zip/refs/tags/{urllib.parse.quote(tag)}"
                ),
            }
        candidates = [
            (str(release.get("asset_url") or "").strip(), str(release.get("asset_name") or f"zapret-discord-youtube-{wanted}.zip")),
            (str(release.get("zipball_url") or "").strip(), "zapret-source.zip"),
        ]
        candidates = [(url, name) for url, name in candidates if url]
        return self._install_zapret_archive(version=wanted, candidates=candidates)

    def _fetch_latest_release_atom(self, repository: str) -> dict[str, str]:
        feed_url = f"https://github.com/{repository}/releases.atom"
        payload = self.github.github_bytes(feed_url, timeout=20, purpose=f"{repository}-release-feed")
        root = ET.fromstring(payload)
        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", namespace)
        if entry is None:
            raise ValueError(f"GitHub release feed is empty: {repository}")
        link = entry.find("atom:link[@rel='alternate']", namespace)
        href = str(link.get("href") if link is not None else "")
        marker = "/releases/tag/"
        tag = urllib.parse.unquote(href.split(marker, 1)[1]).strip() if marker in href else ""
        if not tag:
            title = entry.findtext("atom:title", default="", namespaces=namespace).strip()
            tag = title.rsplit(" ", 1)[-1].strip()
        if not tag:
            raise ValueError(f"GitHub release feed has no tag: {repository}")
        return {"tag": tag, "latest_version": tag.lstrip("vV")}

    def fetch_latest_zapret2_release(self) -> dict[str, str]:
        releases = self.list_zapret2_releases(limit=1)
        if releases:
            item = releases[0]
            return {
                "latest_version": str(item.get("version") or ""),
                "source_url": str(item.get("asset_url") or item.get("source_url") or item.get("zipball_url") or ""),
                "tag": str(item.get("tag") or ""),
                "asset_url": str(item.get("asset_url") or ""),
                "asset_name": str(item.get("asset_name") or ""),
                "zipball_url": str(item.get("zipball_url") or ""),
            }
        # Offline fallback: still try the tagged zipball naming for a known pin.
        return {
            "latest_version": "1.0.4",
            "tag": "v1.0.4",
            "source_url": "https://github.com/bol-van/zapret2/releases/download/v1.0.4/zapret2-v1.0.4.zip",
            "asset_url": "https://github.com/bol-van/zapret2/releases/download/v1.0.4/zapret2-v1.0.4.zip",
            "asset_name": "zapret2-v1.0.4.zip",
            "zipball_url": "https://codeload.github.com/bol-van/zapret2/zip/refs/tags/v1.0.4",
        }

    def list_zapret2_releases(self, *, limit: int = 25) -> list[dict[str, str]]:
        """List bol-van/zapret2 GitHub releases (newest first)."""
        repository = "bol-van/zapret2"
        capped = max(1, min(int(limit), 40))
        cache_key = "zapret2"
        api_url = f"https://api.github.com/repos/{repository}/releases?per_page={capped}"
        try:
            payload = self.github.github_json(api_url, timeout=25, purpose="zapret2-releases")
        except Exception as error:
            self.logging.log("warning", "Zapret2 releases API failed", error=str(error))
            cached = self._load_component_releases_cache(cache_key)
            if cached:
                self.logging.log("info", "Using cached Zapret2 releases after API failure", count=len(cached))
                return cached[:capped]
            try:
                atom_items = self._fetch_release_atom_entries(repository, limit=capped)
            except Exception as atom_error:
                self.logging.log("warning", "Zapret2 releases atom fallback failed", error=str(atom_error))
                atom_items = []
            if not atom_items:
                return []
            out: list[dict[str, str]] = []
            for item in atom_items:
                version = str(item.get("version") or "")
                tag = str(item.get("tag") or f"v{version}")
                if not tag.startswith("v"):
                    tag = f"v{version}"
                asset_url = (
                    f"https://github.com/{repository}/releases/download/"
                    f"{urllib.parse.quote(tag)}/zapret2-{urllib.parse.quote(tag)}.zip"
                )
                out.append(
                    {
                        "version": version,
                        "tag": tag,
                        "asset_url": asset_url,
                        "asset_name": f"zapret2-{tag}.zip",
                        "source_url": asset_url,
                        "zipball_url": f"https://codeload.github.com/{repository}/zip/refs/tags/{urllib.parse.quote(tag)}",
                        "published_at": str(item.get("published_at") or ""),
                        "prerelease": "0",
                        "recommended": "1" if not out else "0",
                    }
                )
            if out:
                self._save_component_releases_cache(cache_key, out)
            return out[:capped]
        if not isinstance(payload, list):
            cached = self._load_component_releases_cache(cache_key)
            return cached[:capped] if cached else []
        out = []
        for item in payload:
            if not isinstance(item, dict) or bool(item.get("draft")):
                continue
            tag = str(item.get("tag_name") or "").strip()
            version = tag.lstrip("vV") or str(item.get("name") or "").strip().lstrip("vV")
            if not version:
                continue
            assets = [a for a in list(item.get("assets") or []) if isinstance(a, dict)]
            zip_asset = next(
                (
                    a
                    for a in assets
                    if str(a.get("name") or "").lower().endswith(".zip")
                    and "openwrt" not in str(a.get("name") or "").lower()
                    and "zapret2" in str(a.get("name") or "").lower()
                ),
                None,
            )
            if zip_asset is None:
                zip_asset = next(
                    (
                        a
                        for a in assets
                        if str(a.get("name") or "").lower().endswith(".zip")
                        and "openwrt" not in str(a.get("name") or "").lower()
                    ),
                    None,
                )
            asset_url = str((zip_asset or {}).get("browser_download_url") or "").strip()
            asset_name = str((zip_asset or {}).get("name") or "").strip() or f"zapret2-v{version}.zip"
            if not asset_url:
                asset_url = (
                    f"https://github.com/{repository}/releases/download/"
                    f"{urllib.parse.quote(tag)}/zapret2-{urllib.parse.quote(tag)}.zip"
                )
            zipball = str(item.get("zipball_url") or "").strip() or (
                f"https://codeload.github.com/{repository}/zip/refs/tags/{urllib.parse.quote(tag)}"
            )
            out.append(
                {
                    "version": version,
                    "tag": tag or f"v{version}",
                    "asset_url": asset_url,
                    "asset_name": asset_name,
                    "source_url": asset_url or zipball,
                    "zipball_url": zipball,
                    "published_at": str(item.get("published_at") or item.get("created_at") or ""),
                    "prerelease": "1" if bool(item.get("prerelease")) else "0",
                    "recommended": "1" if not out else "0",
                }
            )
        if out:
            self._save_component_releases_cache(cache_key, out)
        return out

    def install_zapret2_version(self, version: str) -> dict[str, str]:
        """Download and install a specific bol-van/zapret2 release (upgrade or rollback)."""
        wanted = str(version or "").strip().lstrip("vV")
        if not wanted:
            return {"status": "error", "error": "Version is required"}
        current = str(self.storage._detect_zapret2_version() or "").strip().lstrip("vV")
        if current and current == wanted:
            return {"status": "up-to-date", "version": current}

        release: dict[str, str] | None = None
        for item in self.list_zapret2_releases(limit=40):
            item_version = str(item.get("version") or "").strip().lstrip("vV")
            item_tag = str(item.get("tag") or "").strip().lstrip("vV")
            if wanted in {item_version, item_tag}:
                release = item
                break
        if release is None:
            tag = f"v{wanted}"
            release = {
                "version": wanted,
                "tag": tag,
                "asset_url": (
                    f"https://github.com/bol-van/zapret2/releases/download/"
                    f"{urllib.parse.quote(tag)}/zapret2-{urllib.parse.quote(tag)}.zip"
                ),
                "asset_name": f"zapret2-{tag}.zip",
                "source_url": (
                    f"https://github.com/bol-van/zapret2/releases/download/"
                    f"{urllib.parse.quote(tag)}/zapret2-{urllib.parse.quote(tag)}.zip"
                ),
                "zipball_url": f"https://codeload.github.com/bol-van/zapret2/zip/refs/tags/{urllib.parse.quote(tag)}",
            }

        candidates = [
            str(release.get("asset_url") or "").strip(),
            str(release.get("source_url") or "").strip(),
            str(release.get("zipball_url") or "").strip(),
            # Windows winws2 lives in the binary bundle; keep as last-resort fallback.
            "https://codeload.github.com/bol-van/zapret-win-bundle/zip/refs/heads/master",
        ]
        last_error = ""
        was_running = self._is_image_running("winws2.exe")
        if was_running:
            self.stop_component("zapret2")
        runtime_root: Path | None = None
        for archive_url in candidates:
            if not archive_url:
                continue
            try:
                runtime_root = self._install_zapret2_archive(archive_url=archive_url, version=wanted)
                last_error = ""
                break
            except Exception as error:
                last_error = str(error)
                self.logging.log("warning", "Zapret2 archive install failed", url=archive_url, error=last_error)
        if runtime_root is None:
            if was_running:
                try:
                    self.start_component("zapret2")
                except Exception:
                    pass
            return {"status": "error", "error": last_error or "Zapret2 install failed"}
        if was_running:
            self.start_component("zapret2")
        return {"status": "updated", "version": wanted, "path": str(runtime_root)}

    def update_zapret_runtime(self) -> dict[str, str]:
        release = self.fetch_latest_zapret_release()
        latest_version = str(release.get("latest_version", "")).strip()
        current_version = self.storage._detect_zapret_version()
        if latest_version and current_version == latest_version:
            return {"status": "up-to-date", "version": current_version}
        candidates = [
            (
                str(release.get("asset_url", "")).strip(),
                str(release.get("asset_name", "") or "zapret-release.zip"),
            ),
            (
                str(release.get("zipball_url", "")).strip(),
                "zapret-source.zip",
            ),
        ]
        candidates = [(url, name) for url, name in candidates if url]
        if not candidates:
            return {"status": "error", "error": "No zapret archive URL found"}
        return self._install_zapret_archive(version=latest_version or current_version, candidates=candidates)

    def _install_zapret_archive(self, *, version: str, candidates: list[tuple[str, str]]) -> dict[str, str]:
        current_version = self.storage._detect_zapret_version()
        if version and current_version == version:
            return {"status": "up-to-date", "version": current_version}
        runtime_root = self.storage.paths.runtime_dir / "zapret-discord-youtube"
        was_running = self._is_image_running("winws.exe")
        temp_root = Path(tempfile.mkdtemp(prefix="zapret_hub_zapret_update_"))
        try:
            last_error = ""
            source_root: Path | None = None
            for index, (archive_url, archive_name) in enumerate(candidates):
                try:
                    zip_path = temp_root / f"{index}_{Path(archive_name).name or 'zapret.zip'}"
                    self._download_to_file(archive_url, zip_path, timeout=75)
                    extract_root = temp_root / f"extract_{index}"
                    extract_root.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(zip_path, "r") as archive:
                        archive.extractall(extract_root)
                    source_root = self._find_extracted_zapret_root(extract_root)
                    if source_root is not None:
                        break
                    last_error = f"Invalid zapret archive structure: {archive_name}"
                except (HTTPError, URLError, TimeoutError, zipfile.BadZipFile, OSError) as error:
                    last_error = str(error)
                    self.logging.log("warning", "Zapret archive download failed", url=archive_url, error=last_error)
            if source_root is None:
                return {"status": "error", "error": last_error or "Invalid zapret archive"}
            if was_running:
                self.stop_component("zapret")
            backup = self.storage.create_backup(runtime_root, "pre-update-zapret")
            if runtime_root.exists():
                shutil.rmtree(runtime_root, ignore_errors=True)
            shutil.copytree(source_root, runtime_root, dirs_exist_ok=True)
            if version:
                self._patch_zapret_local_version(runtime_root, version)
            self.storage._ensure_default_bundled_mod("unified-by-goshkow", {
                "name": "Hub",
                "author": "goshkow",
                "description": "Bundled unified pack",
                "version": "1.9.9a-unified4",
                "source_url": "bundled://unified-by-goshkow",
            }, force_refresh=True)
            self.storage.ensure_layout()
            self._rebuild_visible_zapret_runtime_snapshot()
            if was_running:
                self.start_component("zapret")
            self.logging.log("info", "Zapret updated", version=version, backup=str(backup or ""))
            return {"status": "updated", "version": version or current_version}
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def update_zapret2_runtime(self) -> dict[str, str]:
        release = self.fetch_latest_zapret2_release()
        latest_version = str(release.get("latest_version") or "").strip().lstrip("vV")
        current_version = str(self.storage._detect_zapret2_version() or "").strip().lstrip("vV")
        if latest_version and current_version == latest_version:
            return {"status": "up-to-date", "version": current_version}
        return self.install_zapret2_version(latest_version or current_version)

    def fetch_latest_tg_ws_proxy_release(self) -> dict[str, str]:
        api_url = "https://api.github.com/repos/Flowseal/tg-ws-proxy/releases/latest"
        try:
            payload = self.github.github_json(api_url, timeout=20, purpose="tg-ws-proxy-release-metadata")
            if not isinstance(payload, dict):
                raise ValueError("Invalid tg-ws-proxy release metadata")
        except Exception as error:
            self.logging.log("warning", "TG WS Proxy release metadata fallback", error=str(error))
            fallback = self._fetch_latest_release_atom("Flowseal/tg-ws-proxy")
            tag = str(fallback.get("tag") or "")
            version = str(fallback.get("latest_version") or "")
            return {
                "latest_version": version,
                "source_url": (
                    f"https://codeload.github.com/Flowseal/tg-ws-proxy/zip/refs/tags/{urllib.parse.quote(tag)}"
                    if tag
                    else "https://codeload.github.com/Flowseal/tg-ws-proxy/zip/refs/heads/main"
                ),
                "exe_url": (
                    f"https://github.com/Flowseal/tg-ws-proxy/releases/download/"
                    f"{urllib.parse.quote(tag)}/TgWsProxy_windows.exe"
                    if tag
                    else "https://github.com/Flowseal/tg-ws-proxy/releases/latest/download/TgWsProxy_windows.exe"
                ),
                "exe_name": "TgWsProxy_windows.exe",
            }
        latest_version = str(payload.get("tag_name") or payload.get("name") or "").strip().lstrip("v")
        assets = [item for item in list(payload.get("assets") or []) if isinstance(item, dict)]
        windows_asset = next(
            (
                item
                for item in assets
                if str(item.get("name", "")).strip().lower() == "tgwsproxy_windows.exe"
            ),
            None,
        )
        return {
            "latest_version": latest_version,
            "source_url": str(payload.get("zipball_url") or "").strip(),
            "exe_url": str((windows_asset or {}).get("browser_download_url", "")).strip(),
            "exe_name": str((windows_asset or {}).get("name", "")).strip() or "TgWsProxy_windows.exe",
        }

    def list_tg_ws_proxy_releases(self, *, limit: int = 25) -> list[dict[str, str]]:
        """List Flowseal/tg-ws-proxy GitHub releases (newest first)."""
        repository = "Flowseal/tg-ws-proxy"
        capped = max(1, min(int(limit), 40))
        cache_key = "tg-ws-proxy"
        api_url = f"https://api.github.com/repos/{repository}/releases?per_page={capped}"
        try:
            payload = self.github.github_json(api_url, timeout=25, purpose="tg-ws-proxy-releases")
        except Exception as error:
            self.logging.log("warning", "TG WS Proxy releases API failed", error=str(error))
            cached = self._load_component_releases_cache(cache_key)
            if cached:
                self.logging.log("info", "Using cached TG WS Proxy releases after API failure", count=len(cached))
                return cached[:capped]
            try:
                atom_items = self._fetch_release_atom_entries(repository, limit=capped)
            except Exception as atom_error:
                self.logging.log("warning", "TG WS Proxy releases atom fallback failed", error=str(atom_error))
                atom_items = []
            if atom_items:
                out: list[dict[str, str]] = []
                for item in atom_items:
                    version = str(item.get("version") or "")
                    tag = str(item.get("tag") or f"v{version}")
                    if not str(tag).startswith("v"):
                        tag = f"v{version}"
                    out.append(
                        {
                            "version": version,
                            "tag": tag,
                            "source_url": (
                                f"https://codeload.github.com/{repository}/zip/refs/tags/{urllib.parse.quote(tag)}"
                            ),
                            "zipball_url": (
                                f"https://codeload.github.com/{repository}/zip/refs/tags/{urllib.parse.quote(tag)}"
                            ),
                            "exe_url": (
                                f"https://github.com/{repository}/releases/download/"
                                f"{urllib.parse.quote(tag)}/TgWsProxy_windows.exe"
                            ),
                            "exe_name": "TgWsProxy_windows.exe",
                            "published_at": str(item.get("published_at") or ""),
                            "prerelease": "0",
                            "recommended": "1" if not out else "0",
                        }
                    )
                if out:
                    self._save_component_releases_cache(cache_key, out)
                return out[:capped]
            try:
                latest = self.fetch_latest_tg_ws_proxy_release()
                version = str(latest.get("latest_version") or "")
                if not version:
                    return []
                return [
                    {
                        "version": version,
                        "tag": f"v{version}",
                        "source_url": str(latest.get("source_url") or ""),
                        "exe_url": str(latest.get("exe_url") or ""),
                        "exe_name": str(latest.get("exe_name") or "TgWsProxy_windows.exe"),
                        "zipball_url": str(latest.get("source_url") or ""),
                        "published_at": "",
                        "prerelease": "0",
                        "recommended": "1",
                    }
                ]
            except Exception as latest_error:
                self.logging.log("warning", "TG WS Proxy latest fallback failed", error=str(latest_error))
                return []
        if not isinstance(payload, list):
            return []
        result: list[dict[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("tag_name") or "").strip()
            version = tag.lstrip("vV")
            assets = [a for a in list(item.get("assets") or []) if isinstance(a, dict)]
            windows_asset = next(
                (
                    a
                    for a in assets
                    if str(a.get("name", "")).strip().lower() == "tgwsproxy_windows.exe"
                ),
                None,
            )
            result.append(
                {
                    "version": version,
                    "tag": tag,
                    "source_url": str(item.get("zipball_url") or "").strip(),
                    "zipball_url": str(item.get("zipball_url") or "").strip(),
                    "exe_url": str((windows_asset or {}).get("browser_download_url", "")).strip(),
                    "exe_name": str((windows_asset or {}).get("name", "")).strip() or "TgWsProxy_windows.exe",
                    "published_at": str(item.get("published_at") or ""),
                    "prerelease": "1" if bool(item.get("prerelease")) else "0",
                    "recommended": "1" if not result else "0",
                }
            )
        if result:
            self._save_component_releases_cache(cache_key, result)
        return result[:capped]

    def install_tg_ws_proxy_version(self, version: str) -> dict[str, str]:
        wanted = str(version or "").strip().lstrip("vV")
        if not wanted:
            return {"status": "error", "error": "Version is required"}
        current = str(self.storage._detect_tgws_version() or "").strip()
        if current and current == wanted:
            return {"status": "up-to-date", "version": current}
        release: dict[str, str] | None = None
        for item in self.list_tg_ws_proxy_releases(limit=40):
            if str(item.get("version") or "").strip() == wanted or str(item.get("tag") or "").strip().lstrip("vV") == wanted:
                release = item
                break
        if release is None:
            tag = f"v{wanted}" if not str(version).startswith("v") else str(version)
            release = {
                "latest_version": wanted,
                "version": wanted,
                "tag": tag,
                "source_url": f"https://codeload.github.com/Flowseal/tg-ws-proxy/zip/refs/tags/{urllib.parse.quote(tag)}",
                "exe_url": (
                    "https://github.com/Flowseal/tg-ws-proxy/releases/download/"
                    f"{urllib.parse.quote(tag)}/TgWsProxy_windows.exe"
                ),
                "exe_name": "TgWsProxy_windows.exe",
            }
        else:
            release = {
                "latest_version": str(release.get("version") or wanted),
                "source_url": str(release.get("source_url") or ""),
                "exe_url": str(release.get("exe_url") or ""),
                "exe_name": str(release.get("exe_name") or "TgWsProxy_windows.exe"),
            }
        return self._install_tg_ws_proxy_release(release)

    def update_tg_ws_proxy_runtime(self) -> dict[str, str]:
        return self._install_tg_ws_proxy_release(self.fetch_latest_tg_ws_proxy_release())

    def _install_tg_ws_proxy_release(self, release: dict[str, str]) -> dict[str, str]:
        latest_version = str(release.get("latest_version") or release.get("version") or "").strip()
        current_version = self.storage._detect_tgws_version()
        if latest_version and current_version == latest_version:
            return {"status": "up-to-date", "version": current_version}
        source_url = str(release.get("source_url", "")).strip()
        exe_url = str(release.get("exe_url", "")).strip()
        if not source_url or not exe_url:
            return {"status": "error", "error": "No tg-ws-proxy source or Windows asset found"}

        runtime_root = self.storage.paths.runtime_dir / "tg-ws-proxy"
        was_running = False
        try:
            tg_state = next((item for item in self.list_states() if item.component_id == "tg-ws-proxy"), None)
            was_running = bool(tg_state and tg_state.status == "running")
        except Exception:
            was_running = False
        temp_root = Path(tempfile.mkdtemp(prefix="zapret_hub_tgws_update_"))
        try:
            source_zip = temp_root / "tg-ws-proxy.zip"
            self._download_to_file(source_url, source_zip, timeout=75)
            extract_root = temp_root / "extract"
            extract_root.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(source_zip, "r") as archive:
                archive.extractall(extract_root)
            source_root = next((p for p in extract_root.iterdir() if p.is_dir() and (p / "proxy").exists()), None)
            if source_root is None:
                return {"status": "error", "error": "Invalid tg-ws-proxy source archive"}

            windows_exe_path = temp_root / str(release.get("exe_name", "TgWsProxy_windows.exe"))
            self._download_to_file(exe_url, windows_exe_path, timeout=75)

            if was_running:
                self.stop_component("tg-ws-proxy")

            backup = self.storage.create_backup(runtime_root, "pre-update-tg-ws-proxy")
            staging_root = temp_root / "runtime_new"
            shutil.copytree(source_root, staging_root, dirs_exist_ok=True)
            (staging_root / "bin").mkdir(parents=True, exist_ok=True)
            shutil.copy2(windows_exe_path, staging_root / "bin" / "TgWsProxy_windows.exe")

            if runtime_root.exists():
                shutil.rmtree(runtime_root, ignore_errors=True)
            shutil.copytree(staging_root, runtime_root, dirs_exist_ok=True)
            init_py = runtime_root / "proxy" / "__init__.py"
            if latest_version and init_py.exists():
                try:
                    content = init_py.read_text(encoding="utf-8", errors="ignore")
                    content = re.sub(r'__version__\s*=\s*["\'].*?["\']', f'__version__ = "{latest_version}"', content, count=1)
                    init_py.write_text(content, encoding="utf-8")
                except Exception:
                    pass
            self.storage.ensure_layout()
            if was_running:
                self.start_component("tg-ws-proxy")
            self.logging.log(
                "info",
                "TG WS Proxy updated",
                version=latest_version,
                backup=str(backup or ""),
            )
            return {"status": "updated", "version": latest_version or current_version}
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    def _download_to_file(self, url: str, destination: Path, timeout: int = 60) -> None:
        self.github.github_download(url, destination, timeout=timeout, purpose=f"download:{Path(destination).name}", min_bytes=1024)

    def _find_extracted_zapret_root(self, extract_root: Path) -> Path | None:
        candidates = [extract_root]
        candidates.extend(path for path in extract_root.iterdir() if path.is_dir())
        for candidate in candidates:
            if (candidate / "bin").exists() and (candidate / "lists").exists():
                return candidate
        for candidate in extract_root.rglob("*"):
            if candidate.is_dir() and (candidate / "bin").exists() and (candidate / "lists").exists():
                return candidate
        return None

    def _patch_zapret_local_version(self, runtime_root: Path, version: str) -> None:
        service_bat = runtime_root / "service.bat"
        if not service_bat.exists():
            return
        try:
            content = service_bat.read_text(encoding="utf-8", errors="ignore")
            updated = re.sub(
                r'(?im)^(\s*set\s+"?LOCAL_VERSION\s*=\s*)[^"\r\n]+("?\s*)$',
                rf"\g<1>{version}\2",
                content,
                count=1,
            )
            if updated != content:
                service_bat.write_text(updated, encoding="utf-8")
        except Exception:
            pass

    def _rebuild_visible_zapret_runtime_snapshot(self) -> None:
        selected = self._resolve_selected_general_option()
        if selected is not None:
            active_root = self._prepare_active_zapret_runtime(
                selected_bundle_root=Path(selected["path"]).parent,
                selected_bundle_id=str(selected.get("bundle_id", "")),
                selected_script_name=Path(selected["path"]).name,
            )
            self._apply_zapret_runtime_switches(active_root)
            self._ensure_zapret_user_lists(active_root / "lists")
            self._materialize_visible_merged_runtime(active_root)
            self._reset_active_runtime_dir(active_root)
            return
        base_root = self.storage.paths.runtime_dir / "zapret-discord-youtube"
        if base_root.exists():
            target_root = self.storage.paths.merged_runtime_dir / "zapret"
            if target_root.exists():
                shutil.rmtree(target_root, ignore_errors=True)
            shutil.copytree(base_root, target_root, dirs_exist_ok=True, ignore=self._runtime_copy_ignore)

    def rebuild_zapret_runtime_snapshot(self) -> None:
        self._rebuild_visible_zapret_runtime_snapshot()

    def _cleanup_merged_runtime(self) -> None:
        self._cleanup_inactive_zapret_runtimes()
        current_root = self._current_zapret_runtime
        if current_root and current_root.exists():
            self._reset_active_runtime_dir(current_root)
        self._current_zapret_runtime = None

    def _run_general_connectivity_check(
        self,
        general_id: str,
        stop_callback: callable | None = None,
        targets: list[dict[str, str]] | None = None,
        progress_callback: callable | None = None,
    ) -> dict[str, object]:
        if stop_callback is not None and stop_callback():
            return {
                "status": "cancelled",
                "error": "cancelled",
                "passed_targets": 0,
                "total_targets": 0,
                "failed_targets": [],
            }
        self.settings.update(selected_zapret_general=general_id)
        state = self._start_zapret("zapret")
        if stop_callback is not None and stop_callback():
            try:
                self.stop_component("zapret")
            except Exception:
                pass
            return {
                "status": "cancelled",
                "error": "cancelled",
                "passed_targets": 0,
                "total_targets": 0,
                "failed_targets": [],
            }
        if state.status != "running":
            return {
                "status": "error",
                "error": state.last_error or "failed to start",
                "passed_targets": 0,
                "total_targets": 0,
                "failed_targets": [],
            }

        targets = list(targets or self._load_standard_test_targets())
        if not targets:
            return {
                "status": "ok",
                "error": "",
                "passed_targets": 0,
                "total_targets": 0,
                "failed_targets": [],
            }

        if stop_callback is not None and stop_callback():
            return {
                "status": "cancelled",
                "error": "cancelled",
                "passed_targets": 0,
                "total_targets": len(targets),
                "failed_targets": [str(target.get("name", "")) for target in targets],
            }

        passed_targets = 0
        failed_names: list[str] = []
        completed_targets = 0
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(targets)))) as executor:
            future_map = {executor.submit(self._target_is_reachable, target): target for target in targets}
            for future in as_completed(future_map):
                if stop_callback is not None and stop_callback():
                    executor.shutdown(wait=False, cancel_futures=True)
                    return {
                        "status": "cancelled",
                        "error": "cancelled",
                        "passed_targets": passed_targets,
                        "total_targets": len(targets),
                        "failed_targets": failed_names,
                    }
                target = future_map[future]
                try:
                    ok = future.result()
                except Exception:
                    ok = False
                if ok:
                    passed_targets += 1
                else:
                    failed_names.append(str(target["name"]))
                completed_targets += 1
                if progress_callback is not None:
                    progress_callback(completed_targets, len(targets), str(target.get("name", "")))

        if failed_names:
            return {
                "status": "error",
                "error": f"failed targets: {', '.join(failed_names[:6])}",
                "passed_targets": passed_targets,
                "total_targets": len(targets),
                "failed_targets": failed_names,
            }
        return {
            "status": "ok",
            "error": "",
            "passed_targets": passed_targets,
            "total_targets": len(targets),
            "failed_targets": [],
        }

    def _load_standard_test_targets(self) -> list[dict[str, str]]:
        targets_file = self.storage.paths.runtime_dir / "zapret-discord-youtube" / "utils" / "targets.txt"
        targets: list[dict[str, str]] = []
        if targets_file.exists():
            pattern = re.compile(r'^\s*(.+?)\s*=\s*"(.+)"\s*$')
            for raw in targets_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                match = pattern.match(raw.strip())
                if not match:
                    continue
                name = match.group(1).strip()
                value = match.group(2).strip()
                targets.append(self._convert_test_target(name, value))
        if targets:
            return self._append_selected_service_test_targets(targets)

        defaults = [
            ("Google Main", "https://www.google.com"),
            ("Google DNS 8.8.8.8", "PING:8.8.8.8"),
        ]
        return self._append_selected_service_test_targets([self._convert_test_target(name, value) for name, value in defaults])

    def _append_selected_service_test_targets(self, targets: list[dict[str, str]]) -> list[dict[str, str]]:
        result = self._filter_unselected_service_test_targets(targets)
        seen: set[tuple[str, str]] = set()
        for target in result:
            marker = (
                str(target.get("type", "")),
                str(target.get("url") or target.get("host") or target.get("name") or ""),
            )
            seen.add(marker)
        for service_id in self.settings.get().selected_service_ids or []:
            rule = SERVICE_RULES.get(str(service_id))
            if rule is None:
                continue
            for name, value in rule.test_targets:
                converted = self._convert_test_target(name, value)
                marker = (
                    str(converted.get("type", "")),
                    str(converted.get("url") or converted.get("host") or converted.get("name") or ""),
                )
                if marker in seen:
                    continue
                seen.add(marker)
                result.append(converted)
        return result

    def _filter_unselected_service_test_targets(self, targets: list[dict[str, str]]) -> list[dict[str, str]]:
        selected = {str(item) for item in self.settings.get().selected_service_ids or []}
        service_domains: dict[str, set[str]] = {}
        for service_id, rule in SERVICE_RULES.items():
            domains = {item.lower().lstrip(".") for item in rule.list_general if "/" not in item and "*" not in item}
            for _name, value in rule.test_targets:
                converted = self._convert_test_target(_name, value)
                host = str(converted.get("host", "")).lower().lstrip(".")
                if host:
                    domains.add(host)
            service_domains[service_id] = domains

        filtered: list[dict[str, str]] = []
        for target in targets:
            host = str(target.get("host", "")).lower().lstrip(".")
            name = str(target.get("name", "")).lower()
            matched_service = ""
            if host:
                for service_id, domains in service_domains.items():
                    if any(host == domain or host.endswith(f".{domain}") for domain in domains):
                        matched_service = service_id
                        break
            if not matched_service:
                for service_id, domains in service_domains.items():
                    title_token = service_id.replace("-desktop", "").replace("-", " ")
                    if title_token and title_token in name:
                        matched_service = service_id
                        break
                    if any(domain.split(".", 1)[0] in name for domain in domains):
                        matched_service = service_id
                        break
            if matched_service and matched_service not in selected:
                continue
            filtered.append(target)
        return filtered

    def _convert_test_target(self, name: str, value: str) -> dict[str, str]:
        if value.upper().startswith("PING:"):
            host = value.split(":", 1)[1].strip()
            return {"name": name, "type": "ping", "host": host}
        host = value.replace("https://", "").replace("http://", "").split("/", 1)[0].strip()
        return {"name": name, "type": "url", "url": value, "host": host}

    def _target_is_reachable(self, target: dict[str, str]) -> bool:
        target_type = target.get("type", "url")
        if target_type == "ping":
            return self._ping_target(target.get("host", ""))

        url = target.get("url", "").strip()
        if not url:
            return False
        tests = [
            ["--http1.1"],
            ["--tlsv1.2", "--tls-max", "1.2"],
            ["--tlsv1.3", "--tls-max", "1.3"],
        ]
        for extra in tests:
            if self._curl_target(url, extra):
                return True
        return False

    def _curl_target(self, url: str, extra_args: list[str]) -> bool:
        curl_path = shutil.which("curl.exe") or shutil.which("curl")
        if not curl_path:
            return False
        proc = self._run_quiet(
            [
                curl_path,
                "-I",
                "-s",
                "--connect-timeout",
                "2",
                "-m",
                "3",
                "-o",
                "NUL",
                "-w",
                "%{http_code}",
                "--show-error",
                *extra_args,
                url,
            ]
        )
        code = (proc.stdout or "").strip()
        return proc.returncode == 0 and bool(code)

    def _ping_target(self, host: str) -> bool:
        if not host:
            return False
        proc = self._run_quiet(["ping", "-n", "1", "-w", "1200", host])
        return proc.returncode == 0

    def _ensure_zapret_user_lists(self, lists_dir: Path) -> None:
        from zapret_hub.services.orchestrator.auto_overlay import (
            AutoOverlayStore,
            migrate_legacy_markers_into_overlay,
        )
        from zapret_hub.services.orchestrator.learner import strip_auto_overlay
        from zapret_hub.services.orchestrator import zapret2_hub

        # Migrate any legacy in-file Auto blocks into overlay.json, then keep battle files clean.
        try:
            migrate_legacy_markers_into_overlay(Path(self.storage.paths.configs_dir))
        except Exception:
            pass
        try:
            zapret2_hub.sanitize_classic_discord_pollution(Path(self.storage.paths.configs_dir))
        except Exception:
            pass

        defaults = {
            "ipset-all-user.txt": "",
            "ipset-exclude-user.txt": "",
            "list-general-user.txt": "",
            "list-exclude-user.txt": "",
        }
        auto_on = False
        try:
            mode = str(self.settings.get().selected_runtime_mode or "zapret")
            field = "zapret2_control_mode" if mode == "zapret2" else "zapret_control_mode"
            auto_on = str(getattr(self.settings.get(), field, "manual") or "manual") == "auto"
        except Exception:
            auto_on = False
        for filename, content in defaults.items():
            source = self.storage.paths.configs_dir / filename
            target = lists_dir / filename
            if source.exists():
                try:
                    # Always strip legacy markers — Auto now lives in overlay.json only.
                    text = strip_auto_overlay(source.read_text(encoding="utf-8", errors="ignore"))
                    target.write_text(text, encoding="utf-8")
                    continue
                except Exception:
                    pass
            if not target.exists():
                target.write_text(content, encoding="utf-8")
        # Auto: apply overlay/diff onto the runtime copy only (never source configs).
        if auto_on:
            try:
                AutoOverlayStore(Path(self.storage.paths.configs_dir)).apply_to_lists_dir(lists_dir)
            except Exception:
                pass
        # Discord always wins over Cloudflare CDN parent ranges in the live ipset.
        try:
            selected = {str(x) for x in (self.settings.get().selected_service_ids or [])}
            if "discord" in selected:
                self._strip_discord_cdn_from_ipset(lists_dir)
        except Exception:
            pass

    def _is_image_running(self, image_name: str) -> bool:
        now = time.time()
        cached = self._image_running_cache.get(image_name)
        # Longer TTL: tasklist/toolhelp must never run on a hot GUI path (tray / build_state).
        if cached is not None and (now - cached[0]) < 1.5:
            return cached[1]
        running = self._query_image_running(image_name)
        self._image_running_cache[image_name] = (now, running)
        return running

    def _query_image_running(self, image_name: str) -> bool:
        """Fast process presence check. Prefer Win32 snapshot over spawning tasklist.exe."""
        target = str(image_name or "").strip().lower()
        if not target:
            return False
        if sys.platform.startswith("win"):
            try:
                return self._toolhelp_image_running(target)
            except Exception:
                pass
        proc = self._run_quiet(["tasklist", "/FI", f"IMAGENAME eq {image_name}"])
        output = (proc.stdout or "").lower()
        return target in output

    def _toolhelp_image_running(self, image_name_lower: str) -> bool:
        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == INVALID_HANDLE_VALUE:
            raise OSError("CreateToolhelp32Snapshot failed")
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return False
            while True:
                if str(entry.szExeFile or "").lower() == image_name_lower:
                    return True
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    return False
        finally:
            kernel32.CloseHandle(snapshot)

    def _kill_image(self, image_name: str) -> None:
        self._image_running_cache.pop(image_name, None)
        self._run_quiet(["taskkill", "/IM", image_name, "/F", "/T"])
        self._image_running_cache[image_name] = (time.time(), False)

    def _pid_running(self, pid: int) -> bool:
        try:
            value = int(pid)
        except Exception:
            return False
        if value <= 0:
            return False
        try:
            # Windows: OpenProcess succeeds while the PID is still alive.
            handle = self.kernel32.OpenProcess(0x1000, False, value)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                self.kernel32.CloseHandle(handle)
                return True
        except Exception:
            pass
        try:
            os.kill(value, 0)
            return True
        except Exception:
            return False

    def _list_image_pids(self, image_name: str) -> set[int]:
        pids: set[int] = set()
        try:
            proc = self._run_quiet(
                ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"]
            )
            raw = str(getattr(proc, "stdout", "") or "")
            for line in raw.splitlines():
                # "winws.exe","1234","Session Name","Session#","Mem Usage"
                parts = [part.strip().strip('"') for part in line.split(",")]
                if len(parts) >= 2 and parts[0].lower() == image_name.lower():
                    try:
                        pids.add(int(parts[1]))
                    except Exception:
                        continue
        except Exception:
            pass
        return pids

    def _kill_image_pids(self, image_name: str, *, keep_pids: set[int] | None = None) -> None:
        keep = {int(pid) for pid in (keep_pids or set()) if int(pid) > 0}
        for pid in self._list_image_pids(image_name):
            if pid in keep:
                continue
            self._run_quiet(["taskkill", "/PID", str(pid), "/F", "/T"])
        # Refresh cache after selective kill.
        alive = bool(self._list_image_pids(image_name))
        self._image_running_cache[image_name] = (time.time(), alive)

    def _wait_for_process_image(
        self,
        image_name: str,
        process: subprocess.Popen[Any] | None,
        *,
        attempts: int = 12,
        delay: float = 0.1,
    ) -> bool:
        """Poll until the owned PID is alive (not merely any copy of the image)."""
        for _ in range(max(1, int(attempts))):
            if process is not None and process.poll() is not None:
                return False
            if process is not None and getattr(process, "pid", None):
                if self._pid_running(int(process.pid)):
                    return True
            elif self._is_image_running(image_name):
                return True
            time.sleep(max(0.02, float(delay)))
        if process is not None and process.poll() is None and getattr(process, "pid", None):
            return self._pid_running(int(process.pid))
        return process is None and self._is_image_running(image_name)

    def _schedule_bypass_start_confirm(
        self,
        component_id: str,
        process: subprocess.Popen[Any],
        *,
        image_name: str | None = None,
        active_root: Path | None = None,
        stable_driver_path: Path | None = None,
    ) -> None:
        """Finish non-critical start work and flip to error if the process dies early."""

        def worker() -> None:
            try:
                if active_root is not None and component_id == "zapret":
                    try:
                        self._repair_windivert_image_paths(active_root, preferred_driver_path=stable_driver_path)
                    except Exception:
                        pass
                    try:
                        (active_root / ".driver_path_in_use").write_text(datetime.utcnow().isoformat(), encoding="utf-8")
                    except Exception:
                        pass
                # Watch long enough for winws/winws2 to parse args and die on bad
                # --blob / missing bins. Success only if Popen stays alive the whole window.
                for _ in range(24):  # ~3.6s
                    owned = self._processes.get(component_id)
                    if owned is not process:
                        return
                    if process.poll() is not None:
                        # Intentional stop/replace: Hub already tore down or swapped the Popen.
                        owned = self._processes.get(component_id)
                        if owned is not process:
                            return
                        state_now = self._states.get(component_id)
                        if state_now is not None and str(getattr(state_now, "status", "") or "") in {
                            "stopped",
                            "starting",
                        }:
                            return
                        # Owned pid may still be running even if Popen handle looks dead
                        # (or a sibling image is still healthy after a false poll).
                        pid = int(getattr(process, "pid", 0) or 0)
                        if pid and self._pid_running(pid):
                            continue
                        if image_name and self._is_image_running(image_name):
                            # Another Hub-managed copy survived — do not false-error.
                            log_tail = ""
                            try:
                                path = Path(self.logging.source_log_path(component_id))
                                if path.exists():
                                    log_tail = path.read_text(encoding="utf-8", errors="ignore")[-1200:]
                            except Exception:
                                log_tail = ""
                            if self._zapret_log_indicates_capture_started(log_tail):
                                self._image_running_cache[image_name] = (time.time(), True)
                                return
                        log_hint = self._recent_source_log_error(component_id)
                        error_message = log_hint or f"{component_id} exited right after start"
                        try:
                            self._close_source_log_stream(component_id)
                        except Exception:
                            pass
                        self._processes.pop(component_id, None)
                        state = ComponentState(
                            component_id=component_id,
                            status="error",
                            last_error=error_message,
                        )
                        self._states[component_id] = state
                        self._invalidate_state_cache()
                        if image_name:
                            self._image_running_cache.pop(image_name, None)
                        self.logging.log("error", "Bypass exited after optimistic start", component_id=component_id, error=error_message)
                        self._emit_component_status(component_id, "error", error_message)
                        return
                    if image_name:
                        self._image_running_cache.pop(image_name, None)
                    time.sleep(0.15)
                # Still alive after the watch window — cache a positive hit only now.
                if image_name and process.poll() is None:
                    self._image_running_cache[image_name] = (time.time(), True)
            except Exception as error:
                try:
                    self.logging.log("warning", "Bypass start confirm failed", component_id=component_id, error=str(error))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True, name=f"zapret-hub-confirm-{component_id}").start()

    def _wait_for_image_exit(self, image_name: str, *, attempts: int = 8, delay: float = 0.12) -> bool:
        for _ in range(max(1, int(attempts))):
            if not self._is_image_running(image_name):
                return True
            time.sleep(max(0.02, float(delay)))
        return not self._is_image_running(image_name)

    def _force_stop_zapret_runtime(self) -> None:
        process = self._processes.get("zapret")
        if process and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        if process and process.pid:
            self._run_quiet(["taskkill", "/PID", str(process.pid), "/F", "/T"])
        if self._is_image_running("winws.exe"):
            for _ in range(6):
                self._kill_image("winws.exe")
                if self._wait_for_image_exit("winws.exe", attempts=2, delay=0.12):
                    break
        for _ in range(3):
            self._cleanup_zapret_driver_services(self._current_zapret_runtime)
            self._cleanup_orphaned_zapret_driver_services()
            if not any(self._service_exists(name) for name in _ZAPRET_DRIVER_SERVICE_NAMES):
                break
            time.sleep(0.2)
        self._processes.pop("zapret", None)
        self._current_zapret_runtime = None

    def _purge_stale_zapret_runtime(self) -> bool:
        """Terminate old Zapret Hub captures and unload their WinDivert driver."""
        owned = self._processes.get("zapret")
        owned_alive = owned is not None and owned.poll() is None
        image_alive = self._is_image_running("winws.exe")
        managed = self._managed_zapret_driver_services()
        if not owned_alive and not image_alive and not managed:
            self._processes.pop("zapret", None)
            return True
        self._force_stop_zapret_runtime()
        for _ in range(8):
            if self._is_image_running("winws.exe"):
                self._kill_image("winws.exe")
            self._cleanup_orphaned_zapret_driver_services()
            lingering = self._managed_zapret_driver_services()
            if not lingering and not self._is_image_running("winws.exe"):
                return True
            for service_name, image_path in lingering:
                self._delete_zapret_service(service_name, image_path=image_path)
            time.sleep(0.15)
        return not self._managed_zapret_driver_services() and not self._is_image_running("winws.exe")

    def _managed_zapret_driver_services(self) -> list[tuple[str, str]]:
        managed: list[tuple[str, str]] = []
        for service_name in _ZAPRET_DRIVER_SERVICE_NAMES:
            if not self._service_exists(service_name):
                continue
            image_path = self._service_image_path(service_name)
            if image_path and self._is_managed_or_stale_zapret_service_path(image_path):
                managed.append((service_name, image_path))
        return managed

    def _reset_active_runtime_dir(self, active_root: Path) -> None:
        driver_marker = active_root / ".driver_path_in_use"
        driver_path = active_root / "bin" / "WinDivert64.sys"
        if driver_marker.exists() or driver_path.exists():
            self._cleanup_zapret_driver_services(active_root)
            if self._driver_service_references_runtime(active_root):
                self.logging.log(
                    "info",
                    "Keeping Zapret active runtime path because a driver service still references it",
                    path=str(active_root),
                )
                return
        for _ in range(6):
            try:
                shutil.rmtree(active_root, ignore_errors=False)
                return
            except PermissionError:
                self._force_stop_zapret_runtime()
                self._cleanup_zapret_driver_services(active_root)
                time.sleep(0.35)
            except Exception:
                shutil.rmtree(active_root, ignore_errors=True)
                if not active_root.exists():
                    return
        quarantine_root = Path(tempfile.gettempdir()) / "zapret_hub_runtime_cleanup"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        quarantine_target = quarantine_root / f"active_zapret_{int(time.time() * 1000)}"
        try:
            shutil.move(str(active_root), str(quarantine_target))
            shutil.rmtree(quarantine_target, ignore_errors=True)
        except Exception:
            shutil.rmtree(active_root, ignore_errors=True)

    def _next_active_runtime_dir(self) -> Path:
        self.storage.paths.merged_runtime_dir.mkdir(parents=True, exist_ok=True)
        return self.storage.paths.merged_runtime_dir / f"active_zapret_{int(time.time() * 1000)}"

    def _cleanup_inactive_zapret_runtimes(self, preserve_extra: set[Path] | None = None) -> None:
        """Keep only live + (optional) last-good / cutover pin. Drop orphan active_zapret_* copies."""
        merged_root = self.storage.paths.merged_runtime_dir
        if not merged_root.exists():
            return
        preserve: set[Path] = set()
        if self._current_zapret_runtime and self._current_zapret_runtime.exists():
            try:
                preserve.add(self._current_zapret_runtime.resolve())
            except Exception:
                pass
        extras = set(preserve_extra or ())
        extras |= set(getattr(self, "_orchestrator_preserve_runtimes", None) or set())
        # Last known-good from Auto memory (separate from runtime trees).
        try:
            knowledge = getattr(getattr(self, "_orchestrator_engine", None), "knowledge", None)
            if knowledge is None:
                # Fall back: processes may not hold engine; check settings auto + knowledge path via settings owner.
                pass
            last_good_path = getattr(self, "_last_good_runtime_path", None)
            if last_good_path:
                extras.add(Path(last_good_path))
        except Exception:
            pass
        auto_on = False
        try:
            auto_on = str(self.settings.get().zapret_control_mode or "") == "auto"
        except Exception:
            auto_on = False
        if auto_on:
            try:
                # Prefer explicit last-good path recorded on the process manager.
                stored = getattr(self, "_auto_last_good_runtime", None)
                if stored:
                    extras.add(Path(stored))
            except Exception:
                pass
        for item in extras:
            try:
                path = Path(item)
                if path.exists():
                    preserve.add(path.resolve())
            except Exception:
                continue
        # Never keep more than current + one rollback slot when Auto is on.
        if auto_on and len(preserve) > 2 and self._current_zapret_runtime:
            try:
                current = self._current_zapret_runtime.resolve()
                others = sorted(
                    (p for p in preserve if p != current),
                    key=lambda p: p.stat().st_mtime if p.exists() else 0,
                    reverse=True,
                )
                preserve = {current, *others[:1]}
            except Exception:
                pass
        if not auto_on and self._current_zapret_runtime:
            try:
                preserve = {self._current_zapret_runtime.resolve()}
            except Exception:
                pass
        for candidate in merged_root.glob("active_zapret*"):
            try:
                if candidate.resolve() in preserve:
                    continue
            except Exception:
                pass
            self._reset_active_runtime_dir(candidate)

    def remember_auto_runtime(self, root: Path | None) -> None:
        """Remember last merged/running runtime for Auto retention (not a useless copy pile)."""
        if root is None:
            self._auto_last_good_runtime = None
            return
        try:
            self._auto_last_good_runtime = Path(root).resolve()
        except Exception:
            self._auto_last_good_runtime = Path(root)

    def _stable_windivert_dir(self) -> Path:
        return self.storage.paths.merged_runtime_dir / "drivers" / "windivert"

    def _repair_zapret_driver_paths_on_startup(self) -> None:
        try:
            base_bin = self.storage.paths.runtime_dir / "zapret-discord-youtube" / "bin"
            stable_driver_path = self._ensure_stable_windivert_driver(base_bin) if base_bin.exists() else None
            self._repair_windivert_image_paths(preferred_driver_path=stable_driver_path)
            self._repair_stale_zapret_driver_paths(self.storage.paths.merged_runtime_dir, preferred_driver_path=stable_driver_path)
        except Exception as error:
            self.logging.log("warning", "Failed to repair WinDivert paths on startup", error=str(error))

    def _ensure_stable_windivert_driver(self, bin_dir: Path) -> Path:
        source_path = bin_dir / "WinDivert64.sys"
        if not source_path.exists():
            raise FileNotFoundError(f"WinDivert64.sys was not materialized: {source_path}")
        target_dir = self._stable_windivert_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        for source in bin_dir.glob("*"):
            if not source.is_file():
                continue
            name = source.name
            target = target_dir / name
            try:
                if not target.exists() or source.stat().st_size != target.stat().st_size:
                    shutil.copy2(source, target)
            except Exception:
                shutil.copy2(source, target)
        return target_dir / "WinDivert64.sys"

    def _cleanup_zapret_driver_services(self, runtime_root: Path | None = None) -> None:
        for service_name in _ZAPRET_DRIVER_SERVICE_NAMES:
            if not self._service_exists(service_name):
                continue
            image_path = self._service_image_path(service_name)
            if service_name.lower() != "zapret":
                if not image_path:
                    continue
                if runtime_root is not None and not self._path_mentions_runtime(image_path, runtime_root):
                    continue
                if runtime_root is None and not self._is_managed_or_stale_zapret_service_path(image_path):
                    continue
            self._delete_zapret_service(service_name, image_path=image_path)

    def _driver_service_references_runtime(self, runtime_root: Path) -> bool:
        for service_name in _ZAPRET_DRIVER_SERVICE_NAMES:
            if not self._service_exists(service_name):
                continue
            image_path = self._service_image_path(service_name)
            if image_path and self._path_mentions_runtime(image_path, runtime_root):
                return True
        return False

    def _service_exists(self, service_name: str) -> bool:
        proc = self._run_quiet(["sc", "query", service_name])
        return proc.returncode == 0

    def _service_image_path(self, service_name: str) -> str:
        return self._normalize_driver_image_path(self._service_image_path_raw(service_name))

    def _service_image_path_raw(self, service_name: str) -> str:
        proc = self._run_quiet(["sc", "qc", service_name])
        if proc.returncode != 0:
            return ""
        for line in (proc.stdout or "").splitlines():
            if "BINARY_PATH_NAME" not in line:
                continue
            return line.split(":", 1)[-1].strip().strip('"')
        return ""

    def _normalize_driver_image_path(self, image_path: str) -> str:
        raw = str(image_path or "").strip().strip('"')
        for prefix in ("\\??\\", "??\\", "\\\\?\\"):
            if raw.startswith(prefix):
                raw = raw[len(prefix):]
                break
        return raw.strip().strip('"')

    def _repair_windivert_image_paths(self, runtime_root: Path | None = None, preferred_driver_path: Path | None = None) -> None:
        for service_name in ("WinDivert", "WinDivert14"):
            if not self._service_exists(service_name):
                continue
            raw_path = self._service_image_path_raw(service_name)
            normalized_path = self._normalize_driver_image_path(raw_path)
            if not raw_path or not normalized_path:
                continue
            if "windivert64.sys" not in normalized_path.lower():
                continue
            repair_target = normalized_path
            preferred_text = ""
            if preferred_driver_path is not None:
                try:
                    preferred_text = str(preferred_driver_path.resolve())
                except Exception:
                    preferred_text = str(preferred_driver_path)
                if preferred_driver_path.exists():
                    repair_target = preferred_text
            should_repair = raw_path.strip().strip('"') != normalized_path
            if preferred_text and normalized_path.lower() != preferred_text.lower():
                should_repair = True
            managed_current_path = self._is_managed_or_stale_zapret_service_path(normalized_path)
            if runtime_root is not None and not self._path_mentions_runtime(normalized_path, runtime_root) and not managed_current_path:
                should_repair = False
            elif runtime_root is None and not managed_current_path:
                should_repair = False
            if not should_repair:
                continue
            if not Path(repair_target).exists():
                continue
            if self._set_service_image_path(service_name, repair_target):
                self.logging.log(
                    "info",
                    "WinDivert service ImagePath normalized",
                    service=service_name,
                    old_path=raw_path,
                    new_path=repair_target,
                )

    def _set_service_image_path(self, service_name: str, image_path: str) -> bool:
        updated = False
        keys = [
            f"HKLM\\SYSTEM\\CurrentControlSet\\Services\\{service_name}",
            f"HKLM\\SYSTEM\\ControlSet001\\Services\\{service_name}",
        ]
        for key in keys:
            if self._run_quiet(["reg", "query", key]).returncode != 0:
                continue
            proc = self._run_quiet(
                [
                    "reg",
                    "add",
                    key,
                    "/v",
                    "ImagePath",
                    "/t",
                    "REG_EXPAND_SZ",
                    "/d",
                    image_path,
                    "/f",
                ]
            )
            updated = updated or proc.returncode == 0
        return updated

    def _repair_stale_zapret_driver_paths(self, selected_bundle_root: Path, preferred_driver_path: Path | None = None) -> None:
        for service_name in _ZAPRET_DRIVER_SERVICE_NAMES:
            if not self._service_exists(service_name):
                continue
            image_path = self._service_image_path(service_name)
            if not image_path:
                continue
            raw_target = image_path.strip().strip('"')
            if "windivert64.sys" not in raw_target.lower():
                continue
            target_path = Path(raw_target)
            if target_path.exists():
                continue
            if service_name.lower() in {"windivert", "windivert14"} and preferred_driver_path is not None and preferred_driver_path.exists():
                if not self._is_image_running("winws.exe"):
                    self._run_quiet(["sc", "stop", service_name])
                    time.sleep(0.25)
                if self._set_service_image_path(service_name, str(preferred_driver_path)):
                    self.logging.log(
                        "info",
                        "Repaired stale WinDivert service path",
                        service=service_name,
                        old_path=raw_target,
                        new_path=str(preferred_driver_path),
                    )
                    continue
            self.logging.log(
                "warning",
                "Removing stale WinDivert service with missing driver file",
                service=service_name,
                path=str(target_path),
            )
            self._delete_zapret_service(service_name, image_path=raw_target)

    def _cleanup_orphaned_zapret_driver_services(self) -> None:
        for service_name in _ZAPRET_DRIVER_SERVICE_NAMES:
            if not self._service_exists(service_name):
                continue
            image_path = self._service_image_path(service_name)
            if not image_path:
                continue
            if not self._is_managed_or_stale_zapret_service_path(image_path):
                continue
            self._delete_zapret_service(service_name, image_path=image_path)

    def _delete_zapret_service(self, service_name: str, *, image_path: str = "") -> None:
        self._run_quiet(["sc", "stop", service_name])
        time.sleep(0.2)
        self._run_quiet(["sc", "delete", service_name])
        for _ in range(12):
            if not self._service_exists(service_name):
                return
            time.sleep(0.35)
        if image_path and self._is_managed_or_stale_zapret_service_path(image_path):
            for control_set in ("CurrentControlSet", "ControlSet001"):
                self._run_quiet(
                    [
                        "reg",
                        "delete",
                        f"HKLM\\SYSTEM\\{control_set}\\Services\\{service_name}",
                        "/f",
                    ]
                )
            time.sleep(0.2)
        if self._service_exists(service_name):
            self.logging.log(
                "warning",
                "Zapret driver service still exists after cleanup attempt",
                service=service_name,
                path=image_path,
            )

    def _is_managed_or_stale_zapret_service_path(self, image_path: str) -> bool:
        raw = self._normalize_driver_image_path(str(image_path or ""))
        if not raw:
            return False
        lowered = raw.lower()
        try:
            target = Path(raw)
            target_exists = target.exists()
        except Exception:
            target_exists = False
        roots = [
            self.storage.paths.install_root,
            self.storage.paths.merged_runtime_dir,
            Path(tempfile.gettempdir()) / "zapret_hub_runtime_cleanup",
        ]
        if any(self._path_mentions_runtime(raw, root) for root in roots):
            return True
        if "windivert64.sys" in lowered and not target_exists:
            return True
        return False

    def _path_mentions_runtime(self, image_path: str, runtime_root: Path) -> bool:
        raw = self._normalize_driver_image_path(image_path).lower()
        if not raw:
            return False
        try:
            runtime_text = str(runtime_root.resolve()).lower()
        except Exception:
            runtime_text = str(runtime_root).lower()
        return runtime_text in raw

    def _run_quiet(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            creationflags=self._creationflags,
            startupinfo=self._startupinfo,
        )

    def _is_port_listening(self, host: str, port: int) -> bool:
        """Cheap listen probe. Old 0.8s timeout froze the GUI whenever TG was down."""
        key = (str(host or ""), int(port))
        now = time.time()
        cached = self._port_listening_cache.get(key)
        if cached is not None and (now - cached[0]) < 2.0:
            return cached[1]
        try:
            with socket.create_connection((key[0], key[1]), timeout=0.05):
                result = True
        except OSError:
            result = False
        self._port_listening_cache[key] = (now, result)
        return result

    def _open_source_log_stream(self, source: str):
        self._close_source_log_stream(source)
        path = Path(self.logging.source_log_path(source))
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8", errors="ignore")
        handle.write(f"\n[{datetime.utcnow().isoformat()}] session-start\n")
        handle.flush()
        self._log_streams[source] = handle
        return handle

    def _recent_source_log_error(self, source: str) -> str:
        path = Path(self.logging.source_log_path(source))
        if not path.exists():
            return ""
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return ""
        success_markers = (
            "capture is started",
            "windivert initialized",
            "loading plain text list",
            "loaded ",
            "session-start",
            "github version",
            "we have ",
            "lua v",
            "jit:",
        )
        failure_markers = (
            "could not read",
            "bad identifier",
            "already running",
            "failed",
            "error",
            "cannot",
            "unable",
            "access is denied",
            "permission",
            "not found",
            "fatal",
        )
        for line in reversed(lines[-80:]):
            text = line.strip()
            if not text or text.startswith("["):
                continue
            lowered = text.lower()
            if any(marker in lowered for marker in success_markers):
                continue
            if any(marker in lowered for marker in failure_markers):
                return text
        return ""

    def _close_source_log_stream(self, source: str) -> None:
        handle = self._log_streams.pop(source, None)
        if handle is None:
            return
        try:
            handle.flush()
            handle.close()
        except Exception:
            pass

    def _is_telegram_running(self) -> bool:
        for image_name in ("Telegram.exe", "telegram.exe", "Telegram Desktop.exe"):
            if self._is_image_running(image_name):
                return True
        # Store / renamed builds: any process whose image contains "telegram".
        try:
            return self._toolhelp_image_contains("telegram")
        except Exception:
            return False

    def _toolhelp_image_contains(self, needle: str) -> bool:
        token = str(needle or "").strip().lower()
        if not token or not sys.platform.startswith("win"):
            return False
        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == INVALID_HANDLE_VALUE:
            raise OSError("CreateToolhelp32Snapshot failed")
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return False
            while True:
                name = str(entry.szExeFile or "").lower()
                if token in name and not name.startswith("tgws"):
                    return True
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    return False
        finally:
            kernel32.CloseHandle(snapshot)

    def _telegram_desktop_candidates(self) -> list[Path]:
        candidates = [
            Path(os.environ.get("APPDATA", "")) / "Telegram Desktop" / "Telegram.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Telegram Desktop" / "Telegram.exe",
            Path(os.environ.get("ProgramFiles", "")) / "Telegram Desktop" / "Telegram.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Telegram Desktop" / "Telegram.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "Telegram.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "Telegram Desktop.exe",
        ]
        for image_name in ("Telegram.exe", "telegram.exe", "Telegram Desktop.exe"):
            resolved = shutil.which(image_name)
            if resolved:
                candidates.append(Path(resolved))
        unique: list[Path] = []
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(candidate)
        return unique

    def _start_telegram_desktop(self) -> tuple[bool, bool]:
        candidates = self._telegram_desktop_candidates()
        candidate_found = False
        for candidate in candidates:
            if candidate.exists():
                candidate_found = True
                try:
                    subprocess.Popen(
                        [str(candidate)],
                        creationflags=self._creationflags,
                        startupinfo=self._startupinfo,
                    )
                    self.logging.log("info", "Telegram launch requested", path=str(candidate))
                    return candidate_found, True
                except Exception as error:
                    self.logging.log("warning", "Failed to start Telegram", path=str(candidate), error=str(error))
        return candidate_found, False

