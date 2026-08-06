from __future__ import annotations

from dataclasses import asdict
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from typing import Any, Callable

from PySide6.QtCore import QObject, QPropertyAnimation, QEasingCurve, QRect, QTimer, Qt, QUrl, QUrlQuery, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMenu, QSystemTrayIcon

from zapret_hub.services.service_catalog import SERVICE_PRESETS
from zapret_hub.services.onboarding_state import onboarding_is_update
from zapret_hub.runtime_env import development_install_root, is_packaged_runtime, packaged_install_root


_COMPONENT_IDS = ("zapret", "zapret2", "xbox-dns")
_WINDOW_WIDTH = 860
_WINDOW_HEIGHT = 520

# Inline shell shown before the React bundle is available. Keep visually in sync with web_ui/index.html.
_STARTUP_PRELOADER_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="color-scheme" content="dark" />
  <style>
    html, body {
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      background: transparent;
      cursor: default !important;
    }
    #startup-boot, #startup-boot * {
      cursor: default !important;
    }
    #startup-boot {
      position: absolute;
      inset: 6px;
      display: grid;
      place-items: center;
      overflow: hidden;
      border: 1px solid rgba(255, 248, 240, 0.08);
      border-radius: 18px;
      background: #171614;
      opacity: 1;
      pointer-events: auto;
      user-select: none;
      -webkit-user-select: none;
    }
    .startup-chrome {
      position: absolute;
      inset: 0 0 auto 0;
      z-index: 2;
      height: 44px;
      display: flex;
      align-items: stretch;
      justify-content: flex-end;
      opacity: 0.55;
      transition: opacity .18s ease;
    }
    .startup-chrome.is-ready { opacity: 1; }
    .startup-drag { flex: 1; min-width: 0; }
    .startup-controls {
      display: flex;
      align-items: center;
      padding-right: 7px;
    }
    .startup-win-btn {
      display: grid;
      place-items: center;
      width: 36px;
      height: 36px;
      margin: 0;
      padding: 0;
      border: 0;
      border-radius: 9px;
      background: transparent;
      color: rgba(255, 248, 240, 0.55);
      transition: background-color .15s ease, color .15s ease;
    }
    .startup-win-btn:hover {
      background: rgba(255, 248, 240, 0.08);
      color: rgba(255, 248, 240, 0.92);
    }
    .startup-win-btn.is-close:hover {
      background: #e11d48;
      color: #fff;
    }
    .startup-bar {
      position: relative;
      width: 44px;
      height: 2px;
      border-radius: 999px;
      overflow: hidden;
      background: rgba(255, 248, 240, 0.10);
      pointer-events: none;
    }
    .startup-bar::after {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 42%;
      border-radius: inherit;
      background: linear-gradient(
        90deg,
        rgba(255, 248, 240, 0) 0%,
        rgba(255, 248, 240, 0.72) 50%,
        rgba(255, 248, 240, 0) 100%
      );
      animation: startup-shimmer 1.05s cubic-bezier(0.4, 0, 0.2, 1) infinite;
    }
    @keyframes startup-shimmer {
      0% { transform: translateX(-130%); }
      100% { transform: translateX(280%); }
    }
  </style>
</head>
<body>
  <div id="startup-boot" aria-busy="true">
    <div class="startup-chrome" id="startup-chrome">
      <div class="startup-drag" id="startup-drag" aria-hidden="true"></div>
      <div class="startup-controls">
        <button type="button" class="startup-win-btn" id="startup-minimize" aria-label="Minimize" title="Minimize">
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><rect x="2" y="6" width="8" height="1" fill="currentColor" /></svg>
        </button>
        <button type="button" class="startup-win-btn is-close" id="startup-close" aria-label="Close" title="Close">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true"><path d="M3 3l6 6M9 3l-6 6" /></svg>
        </button>
      </div>
    </div>
    <div class="startup-bar" aria-hidden="true"></div>
  </div>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script>
    (function () {
      var native = null;
      var chrome = document.getElementById("startup-chrome");
      var boot = document.getElementById("startup-boot");
      var minimizeBtn = document.getElementById("startup-minimize");
      var closeBtn = document.getElementById("startup-close");

      function call(command) {
        if (!native || typeof native.call !== "function") return;
        try {
          native.call(command, "null", function () {});
        } catch (e) {}
      }

      window.__zapretBootBridgeCall = call;

      function onNative(bridgeObj) {
        if (!bridgeObj) return;
        native = bridgeObj;
        window.__zapretNativeBridge = bridgeObj;
        if (chrome) chrome.classList.add("is-ready");
      }

      if (minimizeBtn) {
        minimizeBtn.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          call("window.minimize");
        });
      }
      if (closeBtn) {
        closeBtn.addEventListener("click", function (event) {
          event.preventDefault();
          event.stopPropagation();
          call("window.close");
        });
      }
      if (boot) {
        boot.addEventListener("pointerdown", function (event) {
          if (event.button !== 0) return;
          var target = event.target;
          if (target && target.closest && target.closest("button")) return;
          call("window.startDrag");
        });
      }

      function bindChannel() {
        if (window.__zapretNativeBridge) {
          onNative(window.__zapretNativeBridge);
          return;
        }
        if (!(window.qt && window.qt.webChannelTransport && window.QWebChannel)) {
          setTimeout(bindChannel, 40);
          return;
        }
        try {
          new window.QWebChannel(window.qt.webChannelTransport, function (channel) {
            onNative(channel.objects && channel.objects.bridge);
          });
        } catch (e) {
          setTimeout(bindChannel, 80);
        }
      }

      bindChannel();
    })();
  </script>
</body>
</html>
"""


def _bring_widget_to_front(widget: Any) -> None:
    widget.raise_()
    widget.activateWindow()
    if not sys.platform.startswith("win"):
        return
    try:
        hwnd = int(widget.winId())
        SW_RESTORE = 9
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)  # type: ignore[attr-defined]
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)  # type: ignore[attr-defined]
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)  # type: ignore[attr-defined]
        ctypes.windll.user32.SetForegroundWindow(hwnd)  # type: ignore[attr-defined]
    except Exception:
        return


def _disable_native_window_rounding(widget: Any) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        hwnd = int(widget.winId())
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        value = ctypes.c_int(DWMWCP_DONOTROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:
        return


class WebBridge(QObject):
    event = Signal(str, str)
    _emit_state_requested = Signal(bool)
    # Marshal arbitrary callables onto the GUI thread (workers must not QTimer.singleShot).
    _gui_call = Signal(object)

    # These must run inside the Slot (return value or immediate GUI action).
    _SYNC_COMMANDS = frozenset({
        "ui.ready",
        "state.get",
        "clipboard.read",
        "window.minimize",
        "window.startDrag",
        "window.close",
        "window.edit",
        "orchestrator.status",
        # Need a real result / dialog before the Promise resolves.
        "mods.import",
        "mods.export",
        "mods.create",
        "mods.files",
        "mods.file-read",
        "mods.file-write",
        "mods.file-delete",
        "mods2.import",
        "mods2.export",
        "mods2.create",
        "mods2.files",
        "mods2.file-read",
        "mods2.file-write",
        "mods2.file-delete",
        "files.save",
        "files.create",
        "files.rename",
        "files2.save",
        "files2.create",
        "files2.rename",
        "component.check-updates-all",
        "component.install-updates-all",
        "logs.export",
        "logs.copy",
        "logs.get",
    })
    _ASYNC_RESULT_COMMANDS = frozenset({
        "mods.delete",
        "mods2.delete",
    })

    def __init__(self, context: Any | None, window: QMainWindow, *, show_onboarding: bool) -> None:
        super().__init__(window)
        self.context = context
        self.window = window
        self.show_onboarding = show_onboarding
        self._onboarding_configuration_running = False
        self._onboarding_configuration_cancelled = False
        self._runtime_transition_status: str | None = None
        self._last_runtime_status = "off"
        self._runtime_action_lock = threading.Lock()
        self._onboarding_initial_mode = "zapret"
        self._component_toggle_lock = threading.Lock()
        self._component_toggle_desired: dict[str, bool] = {}
        self._component_toggle_running: set[str] = set()
        self._emit_state_scheduled = False
        self._cached_file_entries: list[dict[str, Any]] | None = None
        self._cached_file2_entries: list[dict[str, Any]] | None = None
        self._cached_log_entries: list[dict[str, Any]] | None = None
        self._cached_generals: list[dict[str, str]] | None = None
        self._last_state_payload: dict[str, Any] | None = None
        self._emit_state_build_gen = 0
        self._pending_emit_after_onboarding = False
        self._runtime_select_gen = 0
        self._services_set_lock = threading.Lock()
        self._services_set_desired: list[str] | None = None
        self._services_set_running = False
        self._runtime_reconfigure_lock = threading.Lock()
        self._mod_apply_lock = threading.Lock()
        self._mod_apply_pending: dict[str, dict[str, bool]] = {}
        self._mod_apply_refresh: set[str] = set()
        self._mod_apply_running: set[str] = set()
        self._power_lock = threading.Lock()
        self._power_desired: bool | None = None
        self._power_runtime_id = "zapret"
        self._power_running = False
        self._power_user_touched = False
        self._pending_app_release: dict[str, str] | None = None
        self._app_update_busy = False
        self._app_update_check_started = False
        self._app_update_check_busy = False
        self._component_update_check_started = False
        self._component_update_check_busy = False
        # Only the owner of this token may clear _runtime_transition_status.
        self._transition_token = 0
        # Thread-safe state push: workers must not call QTimer directly.
        self._emit_state_requested.connect(self._on_emit_state_requested)
        self._gui_call.connect(self._run_gui_call)
        self._discord_presence = None
        self._wire_orchestrator()
        self._wire_process_status()
        self._wire_discord_presence()

    def _wire_discord_presence(self) -> None:
        if self.context is None:
            return
        previous = getattr(self, "_discord_presence", None)
        if previous is not None:
            try:
                previous.stop()
            except Exception:
                pass
            self._discord_presence = None
        try:
            from zapret_hub.services.discord_presence import DiscordPresenceManager, PresenceSnapshot
            from zapret_hub import __version__ as hub_version
        except Exception as error:
            try:
                self.context.logging.log("warning", "Discord presence unavailable", error=str(error))
            except Exception:
                pass
            return

        def get_snapshot() -> PresenceSnapshot:
            settings = self.context.settings.get()
            mode = str(settings.selected_runtime_mode or "none")
            powered = False
            try:
                powered = bool(self._want_runtime_power()) and str(self._peek_runtime_status() or "") in {
                    "on",
                    "starting",
                }
            except Exception:
                powered = False
            general = str(settings.selected_zapret_general or settings.trusted_general or "")
            if "|" in general:
                general = general.split("|", 1)[-1]
            control = (
                str(settings.zapret2_control_mode or "manual")
                if mode == "zapret2"
                else str(settings.zapret_control_mode or "manual")
            )
            return PresenceSnapshot(
                enabled=bool(getattr(settings, "discord_rpc_enabled", True)),
                powered=powered,
                runtime_mode=mode,
                control_mode=control,
                general_name=general,
                strategy_id=str(getattr(settings, "zapret2_strategy_id", "balanced") or "balanced"),
                language=str(settings.language or "ru"),
                version=str(hub_version),
            )

        manager = DiscordPresenceManager(
            get_settings=lambda: self.context.settings.get(),
            get_snapshot=get_snapshot,
            log=lambda level, message, **ctx: self.context.logging.log(level, message, **ctx),
        )
        self._discord_presence = manager
        try:
            manager.start()
        except Exception as error:
            try:
                self.context.logging.log("warning", "Discord presence start failed", error=str(error))
            except Exception:
                pass

    def _discord_rpc_status_payload(self) -> dict[str, str]:
        manager = getattr(self, "_discord_presence", None)
        if manager is None:
            return {"state": "unavailable", "error": "", "connected": "0"}
        try:
            return dict(manager.status)
        except Exception:
            return {"state": "error", "error": "status_failed", "connected": "0"}

    def _refresh_discord_presence(self) -> None:
        manager = getattr(self, "_discord_presence", None)
        if manager is None:
            return
        try:
            manager.refresh()
        except Exception:
            pass

    def _wire_process_status(self) -> None:
        processes = getattr(self.context, "processes", None) if self.context is not None else None
        if processes is None or not hasattr(processes, "set_status_listener"):
            return

        def _on_status(component_id: str, status: str, last_error: str = "") -> None:
            try:
                runtime_id = str(self.context.settings.get().selected_runtime_mode or "zapret")
            except Exception:
                return
            if str(status) != "error":
                return
            # Mid power start/stop: the power worker reconciles the final status.
            # Do NOT swallow post-start deaths while UI already shows "on" — that left
            # Zapret2 looking enabled with no winws2.exe (bad --blob args, missing bins).
            if str(component_id) == runtime_id and self._runtime_transition_status not in {"starting", "stopping"}:
            # Optimistic start reported "on"; process died — correct the power button.
                self._runtime_transition_status = None
                self._emit_runtime_status("error")
                try:
                    self.emit_state(force=True)
                except Exception:
                    pass
            if last_error:
                try:
                    self.context.logging.log("error", "Active bypass failed after start", component_id=component_id, error=last_error)
                except Exception:
                    pass
            try:
                title = str(component_id or "Zapret Hub")
                message = str(last_error or ("Компонент завершился с ошибкой." if self._ru() else "The component stopped with an error."))
                self.context.notifications.add(
                    "error",
                    title,
                    message,
                    source=component_id or "app",
                    details={"dedupe_key": f"component-error:{component_id}"},
                )
                self.emit_state(force=True)
            except Exception:
                pass

        try:
            processes.set_status_listener(_on_status)
        except Exception:
            pass

    def _emit_toast(self, message: str, *, kind: str = "info", toast_id: str = "") -> None:
        payload = {
            "id": toast_id or f"toast-{int(time.time() * 1000)}",
            "message": message,
            "kind": kind if kind in {"info", "success", "error", "warn"} else "info",
        }
        try:
            self.event.emit("toast.show", json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    def _ru(self) -> bool:
        try:
            return str(self.context.settings.get().language or "ru").lower().startswith("ru")
        except Exception:
            return True


    def _maybe_schedule_startup_update_check(self) -> None:
        if self.context is None:
            return
        try:
            settings = self.context.settings.get()
        except Exception:
            settings = None
        if settings is None:
            return
        if not self._app_update_check_started and bool(settings.check_updates_on_start):
            self._app_update_check_started = True
            QTimer.singleShot(4800, lambda: self._start_app_update_check(manual=False))
        if not self._component_update_check_started and bool(getattr(settings, "check_component_updates_on_start", True)):
            self._component_update_check_started = True
            QTimer.singleShot(2600, lambda: self._start_component_updates_check(show_modal=True))

    def _start_component_updates_check(self, *, show_modal: bool = True) -> None:
        if self.context is None or self._component_update_check_busy:
            return
        self._component_update_check_busy = True

        def worker() -> None:
            updates: list[dict[str, Any]] = []
            try:
                for component_id in ("zapret", "zapret2"):
                    item = self._get_component_update_info(component_id)
                    if item["available"]:
                        updates.append(item)
            except Exception as error:
                self.context.logging.log("warning", "Component update check failed", error=str(error))
            finally:
                self._component_update_check_busy = False
            if show_modal and updates:
                self._schedule_on_gui(lambda: self.event.emit(
                    "component.updates-available", json.dumps({"updates": updates}, ensure_ascii=False)
                ))

        threading.Thread(target=worker, daemon=True, name="zapret-hub-component-updates").start()

    def _get_component_update_info(self, component_id: str) -> dict[str, Any]:
        definitions = {item.id: item for item in self.context.processes.list_components()}
        definition = definitions.get(component_id)
        current = str(getattr(definition, "version", "") or "")
        if component_id == "zapret":
            current = self.context.storage._detect_zapret_version() or current
            releases = self.context.processes.list_zapret_releases(limit=30)
        elif component_id == "zapret2":
            current = self.context.storage._detect_zapret2_version() or current
            releases = self.context.processes.list_zapret2_releases(limit=30)
        else:
            releases = []
        latest = str(releases[0].get("version") or "") if releases else ""
        return {
            "id": component_id,
            "name": str(getattr(definition, "name", component_id) or component_id),
            "currentVersion": current or "?",
            "latestVersion": latest or "?",
            "available": bool(latest and latest.lstrip("vV").lower() != current.lstrip("vV").lower()),
        }

    def _start_app_update_check(self, *, manual: bool) -> None:
        if self.context is None:
            return
        if self._app_update_check_busy:
            if manual:
                self._emit_toast(
                    "Проверка обновлений уже выполняется…" if self._ru() else "Update check is already running…",
                    kind="info",
                    toast_id="app-update-check",
                )
            return
        self._app_update_check_busy = True
        if manual:
            try:
                self.event.emit(
                    "app.update-progress",
                    json.dumps(
                        {
                            "phase": "check",
                            "percent": 1,
                            "downloadedBytes": 0,
                            "totalBytes": 0,
                            "messageRu": "Проверяем обновления…",
                            "messageEn": "Checking for updates…",
                        },
                        ensure_ascii=False,
                    ),
                )
            except Exception:
                pass

        def worker() -> None:
            release: dict[str, Any] = {
                "status": "error",
                "current_version": "",
                "latest_version": "",
                "error": "Не удалось проверить обновления." if self._ru() else "Failed to check for updates.",
            }
            try:
                release = self.context.updates.fetch_latest_application_release(force_refresh=manual)
            except Exception as error:
                try:
                    self.context.logging.log("error", "App update check failed", error=str(error))
                except Exception:
                    pass
                try:
                    release["error"] = self.context.updates._friendly_mirror_error(error)
                except Exception:
                    release["error"] = str(error) or release["error"]
            finally:
                self._app_update_check_busy = False
            self._schedule_on_gui(lambda: self._on_app_update_check_done(release, manual=manual))

        threading.Thread(target=worker, daemon=True, name="zapret-hub-app-update-check").start()

    def _on_app_update_check_done(self, release: dict[str, Any], *, manual: bool) -> None:
        status = str(release.get("status") or "")
        current = str(release.get("current_version") or "")
        latest = str(release.get("latest_version") or "")
        if status == "available":
            self._pending_app_release = {str(k): str(v) for k, v in release.items() if not isinstance(v, (list, dict))}
            # Preserve nested fields needed for apply.
            for key in ("asset_url", "asset_name", "asset_digest", "asset_size", "body", "html_url", "latest_version", "current_version", "status"):
                if key in release:
                    self._pending_app_release[key] = str(release.get(key) or "")
            def _short_digest(value: object) -> str:
                text = str(value or "").strip().lower().removeprefix("sha256:")
                return text[:12] if text else ""

            payload = {
                "currentVersion": current,
                "latestVersion": latest,
                "currentDigest": _short_digest(release.get("installed_build_digest")),
                "latestDigest": _short_digest(release.get("asset_digest")),
                "changelog": str(release.get("body") or ""),
                "htmlUrl": str(release.get("html_url") or ""),
                "isHotfix": bool(release.get("is_hotfix")),
                "demo": False,
            }
            try:
                self.event.emit("app.update-available", json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass
            # Auto-apply if user previously chose "on next launch".
            try:
                if (not manual) and bool(self.context.settings.get().apply_update_on_next_launch):
                    self.context.settings.update(apply_update_on_next_launch=False)
                    self._start_app_update_apply(schedule_only=False)
            except Exception:
                pass
            return
        if status == "up-to-date":
            self._pending_app_release = None
            if manual:
                self._emit_toast(
                    (f"У вас актуальная версия ({current})." if self._ru() else f"You are up to date ({current})."),
                    kind="success",
                    toast_id="app-update-check",
                )
            return
        # error
        self._pending_app_release = None
        if manual:
            error = str(release.get("error") or ("Не удалось проверить обновления." if self._ru() else "Failed to check for updates."))
            self._emit_toast(error, kind="error", toast_id="app-update-check")

    def _start_app_update_apply(self, *, schedule_only: bool = False) -> None:
        if self.context is None:
            return
        if schedule_only:
            self.context.settings.update(apply_update_on_next_launch=True)
            self._emit_toast(
                "Обновление будет установлено при следующем запуске." if self._ru() else "Update will install on next launch.",
                kind="success",
                toast_id="app-update-schedule",
            )
            return
        release = dict(self._pending_app_release or {})
        if not release.get("asset_url"):
            # Refresh metadata once before failing.
            try:
                fresh = self.context.updates.fetch_latest_application_release(force_refresh=True)
                if str(fresh.get("status")) == "available" and fresh.get("asset_url"):
                    release = {str(k): str(v) for k, v in fresh.items() if not isinstance(v, (list, dict))}
                    self._pending_app_release = dict(release)
            except Exception:
                pass
        if not release.get("asset_url"):
            self._emit_toast(
                "Нет доступного обновления для установки." if self._ru() else "No update is available to install.",
                kind="warn",
                toast_id="app-update-apply",
            )
            return
        if self._app_update_busy:
            return
        payload = dict(release)
        self._app_update_busy = True
        self._emit_toast(
            "Скачиваем обновление… Приложение перезапустится." if self._ru() else "Downloading update… The app will restart.",
            kind="info",
            toast_id="app-update-apply",
        )

        def worker() -> None:
            stopped: list[str] = []
            last_progress = {"phase": "", "percent": -1}
            try:
                try:
                    if self.context.settings.get().apply_update_on_next_launch:
                        self.context.settings.update(apply_update_on_next_launch=False)
                except Exception:
                    pass
                def progress(phase: str, current: int, total: int) -> None:
                    phase_ranges = {
                        "download": (2.0, 78.0),
                        "verify": (80.0, 84.0),
                        "extract": (85.0, 98.0),
                        "ready": (100.0, 100.0),
                    }
                    start, end = phase_ranges.get(phase, (0.0, 100.0))
                    ratio = (float(current) / float(total)) if total > 0 else 0.0
                    percent = int(round(start + max(0.0, min(1.0, ratio)) * (end - start)))
                    if last_progress["phase"] == phase and last_progress["percent"] == percent:
                        return
                    last_progress.update(phase=phase, percent=percent)
                    messages = {
                        "download": ("Скачивание обновления", "Downloading update"),
                        "verify": ("Проверка обновления", "Verifying update"),
                        "extract": ("Распаковка обновления", "Extracting update"),
                        "ready": ("Обновление готово к установке", "Update is ready to install"),
                    }
                    message_ru, message_en = messages.get(phase, ("Подготовка обновления", "Preparing update"))

                    def emit() -> None:
                        self.event.emit(
                            "app.update-progress",
                            json.dumps(
                                {
                                    "phase": phase,
                                    "percent": percent,
                                    "downloadedBytes": current if phase == "download" else 0,
                                    "totalBytes": total if phase == "download" else 0,
                                    "messageRu": message_ru,
                                    "messageEn": message_en,
                                },
                                ensure_ascii=False,
                            ),
                        )

                    self._schedule_on_gui(emit)

                prepared = self.context.updates.prepare_update(payload, progress_callback=progress)
                # Keep the active bypass online while the archive is downloaded.
                # Components only need to stop for the short file replacement step.
                states = {item.component_id: item for item in self.context.processes.list_states()}
                for component_id, state in states.items():
                    if str(getattr(state, "status", "") or "").strip().lower() != "running":
                        continue
                    try:
                        self.context.processes.stop_component(component_id)
                        stopped.append(component_id)
                    except Exception:
                        pass
                backend = getattr(self.context, "backend", None)
                if backend is not None:
                    try:
                        backend.request_shutdown_background()
                    except Exception:
                        pass
                    try:
                        process = getattr(backend, "_process", None)
                        if process is not None and process.is_alive():
                            process.join(timeout=1.5)
                            if process.is_alive():
                                process.terminate()
                                process.join(timeout=1.0)
                            if process.is_alive():
                                process.kill()
                    except Exception:
                        pass
                self.context.updates.launch_update(prepared)
                self._schedule_on_gui(self._quit_for_app_update)
            except Exception as error:
                for component_id in stopped:
                    try:
                        self.context.processes.start_component(component_id)
                    except Exception:
                        pass
                try:
                    message = self.context.updates._friendly_mirror_error(error)
                except Exception:
                    message = str(error) or (
                        "Не удалось подготовить обновление." if self._ru() else "Failed to prepare the update."
                    )
                if not message:
                    message = "Не удалось подготовить обновление." if self._ru() else "Failed to prepare the update."

                def _fail(msg: str = message) -> None:
                    self._app_update_busy = False
                    try:
                        self.event.emit(
                            "app.update-progress",
                            json.dumps(
                                {
                                    "phase": "error",
                                    "percent": 0,
                                    "downloadedBytes": 0,
                                    "totalBytes": 0,
                                    "messageRu": msg,
                                    "messageEn": msg,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    except Exception:
                        pass
                    self._emit_toast(msg, kind="error", toast_id="app-update-apply")

                self._schedule_on_gui(_fail)
                try:
                    self.context.logging.log("error", "App update apply failed", error=str(error))
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True, name="zapret-hub-app-update-apply").start()

    def _quit_for_app_update(self) -> None:
        self._app_update_busy = False
        try:
            # An update must terminate the process. fade_close() may hide an
            # apparently active runtime to tray and leave the updater blocked.
            quit_fn = getattr(self.window, "_exit_from_tray", None)
            if callable(quit_fn):
                quit_fn()
                return
        except Exception:
            pass
        try:
            QApplication.instance().quit()
        except Exception:
            pass

    def _wire_orchestrator(self) -> None:
        engine = getattr(self.context, "orchestrator", None) if self.context is not None else None
        if engine is None:
            return
        engine._on_status = self._on_orchestrator_status
        engine._on_toast = self._on_orchestrator_toast
        engine._on_notify = self._on_orchestrator_notify
        engine._on_conflict = self._on_orchestrator_conflict
        engine._on_long_pick = self._on_orchestrator_long_pick
        try:
            settings = self.context.settings.get()
            backend = "zapret2" if str(settings.selected_runtime_mode or "") == "zapret2" else "zapret"
            field = "zapret2_control_mode" if backend == "zapret2" else "zapret_control_mode"
            engine.set_mode(str(getattr(settings, field, "manual") or "manual"), backend=backend)
        except Exception:
            pass
        self._sync_orchestrator_lifecycle()

    def _on_orchestrator_toast(self, message: str, kind: str = "info") -> None:
        try:
            payload = {"id": f"orch-{int(time.time() * 1000)}", "message": message, "kind": kind}
            self.event.emit("toast.show", json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass

    def _on_orchestrator_notify(self, level: str, message_ru: str, message_en: str) -> None:
        try:
            lang = str(self.context.settings.get().language or "ru") if self.context else "ru"
            body = message_ru if lang == "ru" else message_en
            title = "Zapret Hub"
            self.context.notifications.add(level=level, title=title, message=body, source="orchestrator")
            payload = {
                "id": f"orch-n-{int(time.time() * 1000)}",
                "title": title,
                "body": body,
                "ts": int(time.time() * 1000),
                "read": False,
                "level": "warn" if level == "warn" else "info",
            }
            self.event.emit("notification.new", json.dumps(payload, ensure_ascii=False))
            self._on_orchestrator_toast(body, "warn" if level == "warn" else "info")
        except Exception:
            pass

    def _on_orchestrator_conflict(self, payload: dict[str, Any]) -> None:
        try:
            self.event.emit("orchestrator.conflict", json.dumps(payload or {}, ensure_ascii=False))
        except Exception:
            pass

    def _on_orchestrator_long_pick(self, payload: dict[str, Any]) -> None:
        try:
            self.event.emit("orchestrator.longPick", json.dumps(payload or {}, ensure_ascii=False))
        except Exception:
            pass

    def _on_orchestrator_status(self, snapshot: dict[str, Any]) -> None:
        # Thin event only — never build_state from the orchestrator loop.
        try:
            self.event.emit("orchestrator.status", json.dumps(snapshot, ensure_ascii=False))
        except Exception:
            pass

    def _orchestrator_snapshot(self) -> dict[str, Any]:
        engine = getattr(self.context, "orchestrator", None) if self.context is not None else None
        if engine is None:
            settings = self.context.settings.get() if self.context is not None else None
            if settings is not None:
                backend = str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret")
                field = "zapret2_control_mode" if backend == "zapret2" else "zapret_control_mode"
                mode = str(getattr(settings, field, "manual") or "manual")
            else:
                mode = "manual"
            return {
                "mode": mode,
                "status": "idle",
                "statusText": "Manual" if mode != "auto" else "Auto · idle",
                "detail": "",
                "isAuto": mode == "auto",
                "running": False,
                "zapretActive": False,
            }
        return engine.status_snapshot()

    def _zapret_runtime_active(self) -> bool:
        if self.context is None:
            return False
        try:
            settings = self.context.settings.get()
            mode = str(settings.selected_runtime_mode or "zapret")
            if mode not in {"zapret", "zapret2"}:
                return False
            if self._runtime_transition_status in {"on", "starting"}:
                return True
            if self._runtime_transition_status in {"off", "stopping"}:
                return False
            if self._last_runtime_status in {"on", "starting"}:
                return True
            return self._runtime_is_powered_fast()
        except Exception:
            return False

    def _sync_orchestrator_lifecycle(self) -> dict[str, Any]:
        engine = getattr(self.context, "orchestrator", None) if self.context is not None else None
        if engine is None:
            return self._orchestrator_snapshot()
        try:
            settings = self.context.settings.get()
            backend = (
                "zapret2"
                if str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret") == "zapret2"
                else "zapret"
            )
            field = "zapret2_control_mode" if backend == "zapret2" else "zapret_control_mode"
            configured = str(getattr(settings, field, "manual") or "manual")
            # Rebind live Auto to the selected bypass's own control flag.
            # Never starts the other bypass — set_mode is backend-isolated.
            if str(engine.get_mode() or "") != (
                "auto" if configured == "auto" else "manual"
            ) or str((engine.status_snapshot() or {}).get("backend") or "") != backend:
                engine.set_mode(configured, backend=backend)
            return engine.sync_lifecycle(zapret_active=self._zapret_runtime_active())
        except Exception:
            return self._orchestrator_snapshot()

    def _set_orchestrator_mode(
        self,
        mode: str,
        *,
        backend: str | None = None,
        emit_state: bool = True,
    ) -> dict[str, Any]:
        normalized = "auto" if str(mode or "").strip().lower() == "auto" else "manual"
        if self.context is None:
            return self._orchestrator_snapshot()
        settings_before = self.context.settings.get()
        # Quick Access mode is the source of truth. Never start Zapret2 just because
        # the settings panel toggled Zapret2 Auto while classic Zapret is selected.
        active_backend = str(settings_before.selected_runtime_mode or "zapret")
        if active_backend not in {"zapret", "zapret2"}:
            active_backend = "zapret"
        control_backend = str(backend or active_backend)
        if control_backend not in {"zapret", "zapret2"}:
            control_backend = active_backend

        setting_name = "zapret2_control_mode" if control_backend == "zapret2" else "zapret_control_mode"
        self.context.settings.update(**{setting_name: normalized})

        engine = getattr(self.context, "orchestrator", None)
        # Only drive the live orchestrator / restart when the control toggle belongs
        # to the currently selected Quick Access backend.
        affects_live = control_backend == active_backend
        was_running = False
        should_restart = False
        hold_token: int | None = None
        if affects_live:
            states = {item.component_id: item for item in self.context.processes.list_states()}
            component_state = states.get(active_backend)
            was_running = bool(component_state and getattr(component_state, "status", "") == "running")
            should_restart = was_running or self._want_runtime_power()
            if should_restart:
                # Silent hold — Manual↔Auto must not flash the power button.
                hold_token = self._hold_service_power()
                try:
                    orch = getattr(self.context, "orchestrator", None)
                    if orch is not None:
                        orch.sync_lifecycle(zapret_active=False)
                except Exception:
                    pass
            if was_running:
                # Zapret: keep process alive until after set_mode, then seamless cutover.
                if active_backend != "zapret":
                    self.context.processes.stop_component(active_backend)

        if engine is not None and affects_live:
            snapshot = engine.set_mode(normalized, backend=active_backend)
        else:
            snapshot = self._orchestrator_snapshot()

        if affects_live and should_restart:
            try:
                # Pin mode again — start_* must not flip Zapret ↔ Zapret2.
                self.context.settings.update(
                    selected_runtime_mode=active_backend,
                )
                if active_backend == "zapret":
                    try:
                        state = self.context.processes.seamless_restart_zapret()
                        ok = str(getattr(state, "status", "") or "") == "running"
                    except Exception:
                        ok = False
                    if not ok:
                        ok = self._start_component_with_retry(active_backend, show_transition_on_retry=True)
                else:
                    ok = self._start_component_with_retry(active_backend, show_transition_on_retry=True)
                if hold_token is not None:
                    self._release_service_power(hold_token, want_power=ok or self._want_runtime_power())
                    hold_token = None
                elif not ok:
                    self._emit_runtime_status("error")
            except Exception as error:
                try:
                    self.context.logging.log(
                        "error",
                        "Failed to restart bypass after control mode change",
                        error=str(error),
                        backend=active_backend,
                    )
                except Exception:
                    pass
                if hold_token is not None:
                    self._release_service_power(hold_token, want_power=True)
                    hold_token = None
                else:
                    self._emit_runtime_status("starting")
        elif hold_token is not None:
            self._release_service_power(hold_token, want_power=True)
            hold_token = None

        if engine is not None and affects_live:
            snapshot = engine.sync_lifecycle(zapret_active=self._zapret_runtime_active())
        try:
            self.event.emit("orchestrator.status", json.dumps(snapshot, ensure_ascii=False))
        except Exception:
            pass
        if emit_state:
            self._schedule_on_gui(lambda: self.emit_state())
        return snapshot

    def _run_gui_call(self, fn: Any) -> None:
        try:
            if callable(fn):
                fn()
        except Exception as error:
            if self.context is not None:
                try:
                    self.context.logging.log("error", "GUI marshalled call failed", error=str(error))
                except Exception:
                    pass

    def _schedule_on_gui(self, fn: Callable[[], Any], delay_ms: int = 0) -> None:
        """Run fn on the Qt GUI thread (optionally after delay_ms)."""
        if delay_ms <= 0:
            self._gui_call.emit(fn)
            return
        self._gui_call.emit(lambda: QTimer.singleShot(max(0, int(delay_ms)), fn))

    @Slot(str, str, result=str)
    def call(self, command: str, raw_payload: str) -> str:
        try:
            payload = json.loads(raw_payload or "null")
            if command in self._ASYNC_RESULT_COMMANDS:
                data = dict(payload or {}) if isinstance(payload, dict) else {}
                request_id = str(data.pop("__requestId", "") or uuid.uuid4())
                threading.Thread(
                    target=self._run_async_result_command,
                    args=(command, data, request_id),
                    daemon=True,
                    name=f"zapret-hub-async-{command}",
                ).start()
                return json.dumps({"value": {"pending": True, "requestId": request_id}}, ensure_ascii=False)
            # Return to WebEngine immediately for mutation commands. QWebChannel
            # Slots are synchronous — any work here freezes animations/clicks.
            if command not in self._SYNC_COMMANDS:
                QTimer.singleShot(0, lambda c=command, p=payload: self._dispatch_safe(c, p))
                return json.dumps({"value": None}, ensure_ascii=False)
            value = self._dispatch(command, payload)
            return json.dumps({"value": value}, ensure_ascii=False)
        except Exception as error:
            if self.context is not None:
                try:
                    self.context.logging.log("error", "Web UI command failed", command=command, error=str(error))
                except Exception:
                    pass
            return json.dumps({"error": str(error)}, ensure_ascii=False)

    def _run_async_result_command(self, command: str, payload: Any, request_id: str) -> None:
        try:
            value = self._dispatch(command, payload)
            out = {"requestId": request_id, "ok": True, "command": command, "value": value}
        except Exception as error:
            out = {"requestId": request_id, "ok": False, "command": command, "error": str(error)}
            if self.context is not None:
                try:
                    self.context.logging.log("error", "Web UI async command failed", command=command, error=str(error))
                except Exception:
                    pass
        try:
            encoded = json.dumps(out, ensure_ascii=False)
        except Exception:
            encoded = json.dumps({"requestId": request_id, "ok": False, "error": "encode_failed"}, ensure_ascii=False)
        self._schedule_on_gui(lambda e=encoded: self.event.emit("async.result", e))

    def _dispatch_safe(self, command: str, payload: Any) -> None:
        try:
            self._dispatch(command, payload)
        except Exception as error:
            if self.context is not None:
                try:
                    self.context.logging.log("error", "Web UI deferred command failed", command=command, error=str(error))
                except Exception:
                    pass

    def _dispatch(self, command: str, payload: Any) -> Any:
        if command == "ui.ready":
            ready = getattr(self.window, "mark_ui_ready", None)
            if callable(ready):
                ready()
            return None
        if command == "state.get":
            if self.context is None:
                return None
            # Prefer last emitted payload — sync build_state on the GUI freezes tray/menus.
            cached = getattr(self, "_last_state_payload", None)
            if isinstance(cached, dict) and cached:
                return cached
            return self.build_state()
        if command == "window.minimize":
            minimize = getattr(self.window, "fade_minimize", None)
            minimize() if callable(minimize) else self.window.showMinimized()
            return None
        if command == "window.startDrag":
            handle = self.window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
            return None
        if command == "window.close":
            close = getattr(self.window, "fade_close", None)
            close() if callable(close) else self.window.close()
            return None
        if self.context is None:
            raise RuntimeError("Application is still starting")
        if command == "clipboard.read":
            return QApplication.clipboard().text()
        if command == "runtime.select":
            runtime_id = str((payload or {}).get("id", "zapret"))
            keep_power = bool((payload or {}).get("keepPower"))
            previous_runtime_id = str(self.context.settings.get().selected_runtime_mode or "zapret")
            if runtime_id == previous_runtime_id:
                # Keep UI in sync even on no-op (clears optimistic preview).
                self._emit_runtime_status(self._peek_runtime_status())
                return None

            # Decide power BEFORE mutating selected mode. After update,
            # _runtime_is_powered_fast() would look at the NEW id (still stopped)
            # and skip the actual stop/start switch.
            # Treat "stopping" as still powered — process may still be alive and
            # select must queue a real switch, not settings-only.
            # keepPower: UI browse session started while powered — never leave off
            # just because an intermediate select briefly reported off.
            was_powered = False
            if keep_power:
                was_powered = True
            elif self._runtime_transition_status in {"on", "starting", "stopping"}:
                was_powered = True
            elif self._last_runtime_status in {"on", "starting", "stopping"}:
                was_powered = True
            else:
                try:
                    was_powered = self._runtime_is_powered_fast()
                except Exception:
                    was_powered = False

            # Sync enabled_component_ids so start_enabled_components / Auto cutover
            # cannot flip Quick Access back to the previous bypass.
            from zapret_hub.services.backend_worker import _sync_bypass_enabled_for_mode

            if runtime_id in {"zapret", "zapret2", "none"}:
                _sync_bypass_enabled_for_mode(self.context, runtime_id)
            else:
                self.context.settings.update(selected_runtime_mode=runtime_id)

            # Abort in-flight Auto cutover for the previous backend immediately.
            try:
                orch = getattr(self.context, "orchestrator", None)
                if orch is not None:
                    orch.stop()
                    orch.sync_lifecycle(zapret_active=False)
            except Exception:
                pass

            if self.show_onboarding:
                self._emit_runtime_status(self._peek_runtime_status())
                return None

            self._runtime_select_gen += 1
            gen = self._runtime_select_gen
            select_token = 0
            if was_powered:
                # Cancel a coalesced power-off so select can leave the new mode running.
                with self._power_lock:
                    if self._power_desired is False:
                        self._power_desired = None
                self._transition_token += 1
                select_token = self._transition_token
                self._runtime_transition_status = "starting"
                self._emit_runtime_status("starting")
            else:
                self._emit_runtime_status(self._peek_runtime_status())

            def _select_bg() -> None:
                if gen != self._runtime_select_gen:
                    return
                try:
                    if was_powered:
                        with self._runtime_action_lock:
                            if gen != self._runtime_select_gen:
                                return
                            self._switch_running_runtime(runtime_id, previous_runtime_id, True)
                    if gen != self._runtime_select_gen:
                        return
                    try:
                        alive = self._runtime_process_alive()
                        if alive:
                            status = "on"
                        elif was_powered and keep_power:
                            # Browse started while powered — don't leave the button off.
                            try:
                                if runtime_id == "none":
                                    self._set_no_bypass_power(True)
                                    status = "on"
                                else:
                                    ok = self._start_component_with_retry(
                                        runtime_id, show_transition_on_retry=True
                                    )
                                    status = "on" if ok else "error"
                            except Exception:
                                status = "starting"
                        elif was_powered:
                            # Switch intended power on — never snap to off on a brief gap.
                            status = "on" if self._runtime_process_alive() else "error"
                        else:
                            status = "off"
                    except Exception:
                        status = "on" if was_powered else "off"
                    if was_powered and self._transition_token == select_token:
                        self._runtime_transition_status = None
                    if (not was_powered) or self._transition_token == select_token:
                        self._emit_runtime_status(status)
                    try:
                        self._sync_orchestrator_lifecycle()
                    except Exception:
                        pass
                    self._schedule_on_gui(lambda g=gen: self._emit_state_if_select_gen(g))
                except Exception as error:
                    try:
                        self.context.logging.log("error", "runtime.select background failed", error=str(error))
                    except Exception:
                        pass
                    if gen == self._runtime_select_gen:
                        if was_powered and self._transition_token == select_token:
                            self._runtime_transition_status = None
                        try:
                            if (not was_powered) or self._transition_token == select_token:
                                fallback = (
                                    "starting"
                                    if (was_powered and keep_power)
                                    else ("on" if was_powered else self._peek_runtime_status())
                                )
                                self._emit_runtime_status(fallback)
                        except Exception:
                            pass
                        try:
                            self._sync_orchestrator_lifecycle()
                        except Exception:
                            pass
                        self._schedule_on_gui(lambda g=gen: self._emit_state_if_select_gen(g))

            threading.Thread(target=_select_bg, daemon=True, name="zapret-hub-runtime-select").start()
            return None
        if command == "runtime.power":
            enabled = bool((payload or {}).get("on"))
            self._power_user_touched = True
            if enabled:
                self._onboarding_configuration_cancelled = True
            runtime_now = str(self.context.settings.get().selected_runtime_mode or "zapret")
            with self._power_lock:
                self._power_desired = enabled
                self._power_runtime_id = runtime_now
                if self._power_running:
                    self._runtime_transition_status = "starting" if enabled else "stopping"
                    self._emit_runtime_status(self._runtime_transition_status)
                    return None
                self._power_running = True
            self._start_power_worker()
            return None
        if command == "component.toggle":
            component_id = str((payload or {}).get("id", ""))
            enabled = bool((payload or {}).get("on"))
            settings = self.context.settings.get()
            enabled_ids = {str(item) for item in settings.enabled_component_ids or []}
            enabled_ids.add(component_id) if enabled else enabled_ids.discard(component_id)
            self.context.settings.update(enabled_component_ids=sorted(enabled_ids))
            self._queue_component_toggle(component_id, enabled)
            return None
        if command == "services.set":
            selected = [str(item) for item in (payload or {}).get("selected", [])]
            emit = not self.show_onboarding
            with self._services_set_lock:
                self._services_set_desired = selected
                if self._services_set_running:
                    return None
                self._services_set_running = True

            def _services_bg() -> None:
                while True:
                    with self._services_set_lock:
                        desired = self._services_set_desired
                        self._services_set_desired = None
                        if desired is None:
                            self._services_set_running = False
                            return
                    try:
                        self._apply_selected_services(desired, emit=emit)
                    except Exception as error:
                        try:
                            self.context.logging.log("error", "services.set failed", error=str(error))
                        except Exception:
                            pass

            threading.Thread(target=_services_bg, daemon=True, name="zapret-hub-services-set").start()
            return None
        if command == "settings.apply":
            settings_patch = dict((payload or {}).get("patch") or {})
            patch_copy = dict(settings_patch)
            hw = "hardwareAcceleration" in patch_copy
            hw_enabled = bool(patch_copy.get("hardwareAcceleration")) if hw else False
            light_ui_keys = {"sidebarCollapsed"}
            light_only = bool(patch_copy) and set(patch_copy.keys()) <= light_ui_keys
            onboarding = self.show_onboarding

            def _apply_settings_bg() -> None:
                try:
                    self._apply_settings(patch_copy)
                except Exception as error:
                    try:
                        self.context.logging.log("error", "settings.apply failed", error=str(error))
                    except Exception:
                        pass
                    return
                if hw and hasattr(self.window, "view"):
                    def _hw() -> None:
                        self.window.view.settings().setAttribute(
                            QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, hw_enabled
                        )
                        self.window.view.settings().setAttribute(
                            QWebEngineSettings.WebAttribute.WebGLEnabled, hw_enabled
                        )
                    self._schedule_on_gui(_hw)
                refresh_tray = getattr(self.window, "_refresh_tray_menu", None)
                if callable(refresh_tray):
                    self._schedule_on_gui(refresh_tray)
                if onboarding:
                    return
                if light_only:
                    self._schedule_on_gui(lambda: self.emit_state(), delay_ms=380)
                else:
                    self._schedule_on_gui(lambda: self.emit_state())
                self._refresh_discord_presence()

            threading.Thread(target=_apply_settings_bg, daemon=True, name="zapret-hub-settings-apply").start()
            return None
        if command == "orchestrator.status":
            return self._orchestrator_snapshot()
        if command == "orchestrator.setMode":
            mode = str((payload or {}).get("mode", "manual"))
            backend = str((payload or {}).get("backend", ""))
            threading.Thread(
                target=self._set_orchestrator_mode,
                args=(mode,),
                kwargs={"backend": backend or None, "emit_state": True},
                daemon=True,
                name=f"zapret-hub-orchestrator-mode-{backend or 'active'}",
            ).start()
            return None
        if command == "orchestrator.resetAuto":
            engine = getattr(self.context, "orchestrator", None)

            def _reset_bg() -> None:
                result: dict[str, Any] = {"ok": False, "error": "no_orchestrator"}
                try:
                    if engine is not None:
                        result = engine.reset_auto_cache()
                    # Rematerialize live bypass so Manual/Auto lists drop cleared overlay.
                    try:
                        want = self._want_runtime_power()
                        active = str(self.context.settings.get().selected_runtime_mode or "zapret")
                        if want and active in {"zapret", "zapret2"}:
                            self._reconfigure_runtimes((active,), lambda: None)
                    except Exception:
                        pass
                    self._schedule_on_gui(lambda: self.emit_state(force=True))
                    ru = self._ru()
                    self._schedule_on_gui(
                        lambda: self._emit_toast(
                            "Кэш авто-режима сброшен." if ru else "Auto mode cache was reset.",
                            kind="success",
                            toast_id="orchestrator-reset-auto",
                        )
                    )
                except Exception as error:
                    result = {"ok": False, "error": str(error)}
                    try:
                        self.context.logging.log("error", "orchestrator.resetAuto failed", error=str(error))
                    except Exception:
                        pass
                try:
                    self.event.emit("orchestrator.resetAuto", json.dumps(result, ensure_ascii=False))
                except Exception:
                    pass

            threading.Thread(target=_reset_bg, daemon=True, name="zapret-hub-orchestrator-reset").start()
            return {"started": True}
        if command == "orchestrator.bootstrap":
            engine = getattr(self.context, "orchestrator", None)
            youtube = True if not isinstance(payload, dict) else bool(payload.get("youtube", True))
            discord = True if not isinstance(payload, dict) else bool(payload.get("discord", True))

            def _bootstrap_bg() -> None:
                result: dict[str, Any] = {"ok": False, "error": "bootstrap_failed"}
                try:
                    if engine is None:
                        result = {"ok": False, "error": "no_orchestrator"}
                    else:
                        result = engine.run_bootstrap(youtube=youtube, discord=discord)
                        try:
                            engine.sync_lifecycle(zapret_active=self._zapret_runtime_active())
                        except Exception:
                            pass
                    self._schedule_on_gui(lambda: self.emit_state(force=True))
                except Exception as error:
                    result = {"ok": False, "error": str(error), "mode": "auto"}
                    try:
                        self.context.logging.log("error", "orchestrator.bootstrap failed", error=str(error))
                    except Exception:
                        pass
                try:
                    self.event.emit("orchestrator.bootstrap", json.dumps(result, ensure_ascii=False))
                except Exception:
                    pass

            threading.Thread(target=_bootstrap_bg, daemon=True, name="zapret-hub-orch-bootstrap").start()
            return {"started": True}
        if command == "mods.toggle":
            mod_id = str((payload or {}).get("id", ""))
            enabled = bool((payload or {}).get("on"))
            self._queue_mod_toggle("zapret", mod_id, enabled)
            return None
        if command == "mods.create":
            item = self.context.mods.create_empty(name=str((payload or {}).get("name", "") or "Модификация"))
            self.emit_state()
            return asdict(item)
        if command == "mods.delete":
            mod_id = str((payload or {}).get("id", ""))
            self._discard_queued_mod_toggle("zapret", mod_id)
            self._reconfigure_runtimes(("zapret",), lambda: self.context.mods.remove(mod_id))
            self._cached_generals = None
            self._cached_file_entries = None
            self.emit_state(force=True)
            return self._mods_payload()
        if command == "mods.reorder":
            ordered = [str(item) for item in ((payload or {}).get("orderedIds") or [])]
            # Rebuilding merged runtime can touch many files. Persist the order
            # now and let the debounced worker apply it off the GUI thread.
            self.context.mods.reorder(ordered, rebuild=False)
            self._cached_generals = None
            self._queue_mod_runtime_refresh("zapret")
            self.emit_state(force=True)
            return None
        if command == "mods.edit":
            mod_id = str((payload or {}).get("id", ""))
            patch = dict((payload or {}).get("patch") or {})
            current = next(item for item in self.context.mods.list_installed() if item.id == mod_id)
            self.context.mods.update_metadata(
                mod_id,
                name=str(patch.get("name", current.name)),
                description=str(patch.get("description", current.description)),
                author=str(patch.get("author", current.author)),
                version=str(patch.get("version", current.version)),
                icon_url=str(patch["iconUrl"]) if "iconUrl" in patch else None,
                source_url=str(patch["sourceUrl"]) if "sourceUrl" in patch else None,
            )
            self.emit_state()
            return None
        if command in {"mods.files", "mods.file-read", "mods.file-write", "mods.file-delete"}:
            return self._handle_mod_file_command("zapret", command, dict(payload or {}))
        if command == "mods.import":
            source = str((payload or {}).get("source", ""))
            reference = str((payload or {}).get("ref", "") or "")
            if source == "github":
                item = self.context.mods.import_from_github(reference)
            elif source == "folder":
                selected = QFileDialog.getExistingDirectory(self.window, "Выберите папку модификации")
                if not selected:
                    return None
                item = self.context.mods.import_from_path(selected)
            elif source == "files":
                selected, _ = QFileDialog.getOpenFileNames(self.window, "Выберите файлы модификации")
                if not selected:
                    return None
                item = self.context.mods.import_from_paths(selected)
            else:
                selected, _ = QFileDialog.getOpenFileName(self.window, "Выберите архив модификации", "", "ZIP (*.zip)")
                if not selected:
                    return None
                item = self.context.mods.import_from_path(selected)
            self._cached_generals = None
            self._cached_file_entries = None
            self._queue_mod_runtime_refresh("zapret")
            self.emit_state(force=True)
            return asdict(item)
        if command == "mods.export":
            mod_id = str((payload or {}).get("id", ""))
            target, _ = QFileDialog.getSaveFileName(self.window, "Экспорт модификации", f"{mod_id}.zip", "ZIP (*.zip)")
            if target:
                self.context.mods.export_mod(mod_id, target)
            return None
        if command == "mods2.toggle":
            mod_id = str((payload or {}).get("id", ""))
            enabled = bool((payload or {}).get("on"))
            self._queue_mod_toggle("zapret2", mod_id, enabled)
            return None
        if command == "mods2.create":
            item = self.context.mods2.create_empty(name=str((payload or {}).get("name", "") or "Модификация Zapret 2"))
            self._cached_file2_entries = None
            self.emit_state()
            return asdict(item)
        if command == "mods2.delete":
            mod_id = str((payload or {}).get("id", ""))
            self._discard_queued_mod_toggle("zapret2", mod_id)
            self._reconfigure_runtimes(("zapret2",), lambda: self.context.mods2.remove(mod_id))
            self._cached_file2_entries = None
            self.emit_state(force=True)
            return self._mods_payload()
        if command == "mods2.reorder":
            ordered = [str(item) for item in ((payload or {}).get("orderedIds") or [])]
            self.context.mods2.reorder(ordered, rebuild=False)
            self._queue_mod_runtime_refresh("zapret2")
            self._cached_file2_entries = None
            self.emit_state(force=True)
            return None
        if command == "mods2.edit":
            mod_id = str((payload or {}).get("id", ""))
            patch = dict((payload or {}).get("patch") or {})
            current = next(item for item in self.context.mods2.list_installed() if item.id == mod_id)
            self.context.mods2.update_metadata(
                mod_id,
                name=str(patch.get("name", current.name)),
                description=str(patch.get("description", current.description)),
                author=str(patch.get("author", current.author)),
                version=str(patch.get("version", current.version)),
                icon_url=str(patch["iconUrl"]) if "iconUrl" in patch else None,
                source_url=str(patch["sourceUrl"]) if "sourceUrl" in patch else None,
            )
            self.emit_state()
            return None
        if command in {"mods2.files", "mods2.file-read", "mods2.file-write", "mods2.file-delete"}:
            return self._handle_mod_file_command("zapret2", command, dict(payload or {}))
        if command == "mods2.import":
            source = str((payload or {}).get("source", ""))
            if source == "folder":
                selected = QFileDialog.getExistingDirectory(self.window, "Выберите папку модификации Zapret 2")
                if not selected:
                    return None
                item = self.context.mods2.import_from_path(selected)
            elif source == "files":
                selected, _ = QFileDialog.getOpenFileNames(self.window, "Выберите файлы модификации Zapret 2")
                if not selected:
                    return None
                item = self.context.mods2.import_from_paths(selected)
            else:
                selected, _ = QFileDialog.getOpenFileName(
                    self.window, "Выберите архив модификации Zapret 2", "", "ZIP (*.zip);;Lua (*.lua);;Text (*.txt)"
                )
                if not selected:
                    return None
                item = self.context.mods2.import_from_path(selected)
            self._queue_mod_runtime_refresh("zapret2")
            self._cached_file2_entries = None
            self.emit_state()
            return asdict(item)
        if command == "mods2.export":
            mod_id = str((payload or {}).get("id", ""))
            target, _ = QFileDialog.getSaveFileName(
                self.window, "Экспорт модификации Zapret 2", f"{mod_id}.zip", "ZIP (*.zip)"
            )
            if target:
                self.context.mods2.export_mod(mod_id, target)
            return None
        if command in {"files.save", "files.create", "files.rename"}:
            self._handle_file_command(command, dict(payload or {}))
            self._queue_mod_runtime_refresh("zapret")
            self._cached_file_entries = None
            self.emit_state()
            return None
        if command in {"files2.save", "files2.create", "files2.rename"}:
            self._handle_file2_command(command, dict(payload or {}))
            self._queue_mod_runtime_refresh("zapret2")
            self._cached_file2_entries = None
            self.emit_state()
            return None
        if command == "logs.copy":
            source = str((payload or {}).get("source", "all") or "all")
            QApplication.clipboard().setText("\n".join(self.context.logging.read_source_lines(source, limit=1000)))
            return None
        if command == "logs.get":
            # Never force-rebuild on the sync WebChannel path — reading plain log
            # tails on the GUI thread stalls tray ПКМ while the Logs page polls.
            return self._get_log_entries(force=False)
        if command == "logs.clear":
            source = str((payload or {}).get("source", "") or "")
            targets = {
                "app": [self.context.logging.log_path],
                "zapret": [self.context.logging.zapret_log_path],
            }
            paths = targets.get(source, [
                self.context.logging.log_path,
                self.context.logging.zapret_log_path,
            ])
            for path in paths:
                Path(path).write_text("", encoding="utf-8")
            self._cached_log_entries = None
            self.emit_state()
            return None
        if command == "logs.export":
            source = str((payload or {}).get("source", "all") or "all")
            target, _ = QFileDialog.getSaveFileName(self.window, "Экспорт логов", f"zapret-hub-{source}.log", "Log (*.log);;Text (*.txt)")
            if target:
                Path(target).write_text("\n".join(self.context.logging.read_source_lines(source, limit=5000)), encoding="utf-8")
            return None
        if command == "notifications.markRead":
            self.context.notifications.mark_all_read()
            self.emit_state()
            return None
        if command == "notifications.dismiss":
            self.context.notifications.dismiss(str((payload or {}).get("id", "")))
            self.emit_state()
            return None
        if command == "onboarding.complete":
            payload = payload if isinstance(payload, dict) else {}
            dismiss = bool(payload.get("dismiss", True))
            selected = payload.get("selected")
            mode = payload.get("mode")
            selected_list = [str(item) for item in selected] if isinstance(selected, list) else None
            mode_str = str(mode) if mode else None
            # Return to JS immediately. Persist + abort diagnostics on a worker —
            # never block the WebEngine bridge / onboarding animations.
            self._onboarding_configuration_cancelled = True
            self._cached_generals = None
            self._onboarding_initial_mode = "zapret"
            if dismiss:
                self.show_onboarding = False
                if self._pending_emit_after_onboarding:
                    self._pending_emit_after_onboarding = False
                # Persist worker will force-emit after fade.

            def _persist_complete() -> None:
                try:
                    self._safe_abort_diagnostics()
                except Exception:
                    pass
                try:
                    if selected_list is not None:
                        self._apply_selected_services(selected_list, emit=False)
                    if mode_str:
                        self.context.settings.update(selected_runtime_mode=mode_str)
                    marker = self.context.paths.data_dir / ".services_onboarding_seen_v4"
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text("1", encoding="utf-8")
                    force_once = self.context.paths.install_root / ".force_onboarding_once"
                    if force_once.exists():
                        force_once.unlink(missing_ok=True)
                except Exception as error:
                    try:
                        self.context.logging.log("error", "onboarding.complete persist failed", error=str(error))
                    except Exception:
                        pass
                if dismiss:
                    # Caller already waits for the CSS fade before invoking complete.
                    # Small delay still avoids rebuilding state in the same tick as unmount.
                    self._schedule_on_gui(lambda: self.emit_state(force=True), delay_ms=80)

            threading.Thread(
                target=_persist_complete,
                daemon=True,
                name="zapret-hub-onboarding-complete",
            ).start()
            return None
        if command == "onboarding.open":
            self._onboarding_initial_mode = str((payload or {}).get("mode", "zapret") or "zapret")
            self.show_onboarding = True
            self.emit_state(force=True)
            return None
        if command == "onboarding.configure":
            selected = (payload or {}).get("selected") if isinstance(payload, dict) else None
            selected_list = [str(item) for item in selected] if isinstance(selected, list) else None
            self._start_onboarding_configuration(selected_services=selected_list)
            return None
        if command == "onboarding.cancel":
            self._onboarding_configuration_cancelled = True
            # Hard-abort so mid-check _start_zapret cannot keep spawning winws.
            def _stop() -> None:
                try:
                    self.context.processes.abort_diagnostics()
                except Exception:
                    pass

            threading.Thread(target=_stop, daemon=True, name="zapret-hub-onboarding-cancel").start()
            return None
        if command == "component.check-update":
            component_id = str((payload or {}).get("id", ""))
            request_id = str((payload or {}).get("requestId", ""))
            self._run_component_update_check(component_id, request_id)
            return None
        if command == "component.install-update":
            component_id = str((payload or {}).get("id", ""))
            version = str((payload or {}).get("version", "") or "").strip()
            self._run_component_update(component_id, version=version)
            return None
        if command == "component.check-updates-all":
            self._start_component_updates_check(show_modal=True)
            return None
        if command == "component.install-updates-all":
            ids = {str(item) for item in ((payload or {}).get("ids") or [])}
            for component_id in ("zapret", "zapret2"):
                if component_id in ids:
                    self._run_component_update(component_id)
            return None
        if command == "window.edit":
            action_name = str((payload or {}).get("action") or "").strip().lower()
            actions = {
                "cut": QWebEnginePage.WebAction.Cut,
                "copy": QWebEnginePage.WebAction.Copy,
                "paste": QWebEnginePage.WebAction.Paste,
                "select-all": QWebEnginePage.WebAction.SelectAll,
            }
            action = actions.get(action_name)
            view = getattr(self.window, "view", None)
            if action is not None and view is not None:
                view.page().triggerAction(action)
            return None
        if command == "dns.select-profile":
            profile = str((payload or {}).get("profile", "xbox"))
            self._run_background(lambda: self.context.processes.select_dns_profile(profile))
            return None
        if command == "app.check-updates":
            self._start_app_update_check(manual=True)
            return None
        if command == "app.apply-update":
            schedule_only = bool((payload or {}).get("scheduleNextLaunch"))
            self._start_app_update_apply(schedule_only=schedule_only)
            return None
        if command == "zapret.rebuild-runtime":
            self._run_background(self.context.processes.rebuild_zapret_runtime_snapshot)
            return None
        if command == "component.configure":
            if str((payload or {}).get("id", "")) == "zapret":
                self._start_onboarding_configuration()
            return None
        if command == "component.open-external":
            component_id = str((payload or {}).get("id", ""))
            definition = next((item for item in self.context.processes.list_components() if item.id == component_id), None)
            source = str(getattr(definition, "source", "") or "")
            if source.startswith(("http://", "https://")):
                QDesktopServices.openUrl(QUrl(source))
            return None
        if command == "ui.open-url":
            url = str((payload or {}).get("url", "") or "")
            if url.startswith(("http://", "https://")):
                QDesktopServices.openUrl(QUrl(url))
            return None
        raise ValueError(f"Unsupported web command: {command}")

    def _apply_selected_services(self, selected: list[str], *, emit: bool = True) -> None:
        selected_set = {str(item) for item in selected}
        ordered = [preset.id for preset in SERVICE_PRESETS if preset.id in selected_set]

        def apply() -> None:
            settings = self.context.settings.get()
            enabled_ids = {str(item) for item in settings.enabled_component_ids or []}
            autostart_ids = {str(item) for item in settings.autostart_component_ids or []}
            bypass_services = set(ordered) - {"ai"}
            active_backend = str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret")
            if bypass_services:
                if active_backend == "zapret2":
                    enabled_ids.add("zapret2")
                    enabled_ids.discard("zapret")
                else:
                    enabled_ids.add("zapret")
                    enabled_ids.discard("zapret2")
            else:
                enabled_ids.discard("zapret")
                enabled_ids.discard("zapret2")
                autostart_ids.discard("zapret")
                autostart_ids.discard("zapret2")
            if "ai" in ordered:
                enabled_ids.add("xbox-dns")
            else:
                enabled_ids.discard("xbox-dns")
                autostart_ids.discard("xbox-dns")
            changes: dict[str, Any] = {
                "selected_service_ids": ordered,
                "enabled_component_ids": sorted(enabled_ids),
                "autostart_component_ids": sorted(autostart_ids),
            }
            if "ai" in ordered:
                changes["dns_profile"] = "xbox"
            self.context.settings.update(**changes)
            self.context.merge.rebuild()
            self.context.files._invalidate_collection_cache()
            self.context.files.rebuild_materialized_collections()

        bypass_services = set(ordered) - {"ai"}
        active_backend = str(getattr(self.context.settings.get(), "selected_runtime_mode", "zapret") or "zapret")
        if active_backend not in {"zapret", "zapret2"}:
            active_backend = "zapret"
        # Only restart the selected Quick Access bypass — never the other one.
        # Also restart TG/DNS when their enable flags change under live power.
        self._reconfigure_runtimes(
            (active_backend, "xbox-dns"),
            apply,
            restart_allowed={
                active_backend: bool(bypass_services),
                "xbox-dns": "ai" in ordered,
            },
        )
        if emit:
            self.emit_state()

    def _want_runtime_power(self) -> bool:
        """True when Quick Access power should stay ON (user intent), even mid-stop."""
        if self._runtime_transition_status in {"on", "starting"}:
            return True
        if self._runtime_transition_status in {"off", "stopping"}:
            return False
        # "error" means start failed — do not treat as intended ON (that stuck Zapret2 "on").
        if self._last_runtime_status == "error":
            return False
        if self._last_runtime_status in {"on", "starting"}:
            return True
        try:
            return bool(self._runtime_is_powered_fast())
        except Exception:
            return False

    def _hold_service_power(self) -> int:
        """Pin power UI to lit 'on' during silent background restarts. Returns token."""
        self._transition_token += 1
        token = int(self._transition_token)
        # Hold "on" (not "starting") so the button does not flicker during service work.
        self._runtime_transition_status = "on"
        self._last_runtime_status = "on"
        return token

    def _release_service_power(self, token: int, *, want_power: bool) -> None:
        if token != int(getattr(self, "_transition_token", 0) or 0):
            return
        self._runtime_transition_status = None
        powered = False
        try:
            powered = bool(self._runtime_process_alive())
        except Exception:
            powered = False
        if want_power:
            # If the bypass is dead, show error — never leave a fake "on"/"starting".
            self._emit_runtime_status("on" if powered else "error")
        else:
            self._emit_runtime_status("on" if powered else "off")

    def _component_running(self, component_id: str) -> bool:
        return any(
            item.component_id == component_id and str(item.status or "") == "running"
            for item in self.context.processes.list_states()
        )

    def _runtime_process_alive(self) -> bool:
        """True when the selected bypass process is actually running (ignores UI transition)."""
        settings = self.context.settings.get()
        runtime_id = str(settings.selected_runtime_mode or "zapret")
        if runtime_id == "none":
            return bool(settings.no_bypass_power_enabled)
        try:
            return self._component_running(runtime_id)
        except Exception:
            return False

    def _start_component_with_retry(
        self,
        component_id: str,
        *,
        show_transition_on_retry: bool = True,
    ) -> bool:
        """Stop orphan copies → start. On failure, kill copies and start once more.

        Happy path stays silent (caller may hold power 'on'). The retry attempt
        shows starting/stopping so the power button reflects the transition.
        Never leaves two winws/winws2 copies running.
        """
        if component_id in {"zapret", "zapret2"}:
            try:
                self.context.processes.stop_running_bypass_copies(component_id)
            except Exception:
                pass

        def _is_stable() -> bool:
            # A spawned winws process can still exit a moment later because of a
            # malformed list/profile. Do not report a restart as successful until
            # the short confirmation window has passed.
            for image in ("winws.exe", "winws2.exe"):
                try:
                    cache = getattr(self.context.processes, "_image_running_cache", None)
                    if isinstance(cache, dict):
                        cache.pop(image, None)
                except Exception:
                    pass
            for _ in range(8):
                time.sleep(0.2)
                if not self._component_running(component_id):
                    return False
            return self._component_running(component_id)

        def _attempt() -> bool:
            try:
                state = self.context.processes.start_component(component_id)
            except Exception as error:
                try:
                    self.context.logging.log(
                        "error",
                        "Component start failed",
                        component=component_id,
                        error=str(error),
                    )
                except Exception:
                    pass
                return False
            if str(getattr(state, "status", "") or "") != "running":
                return False
            return _is_stable()

        if _attempt():
            return True

        if show_transition_on_retry:
            self._runtime_transition_status = "starting"
            self._emit_runtime_status("starting")

        if component_id in {"zapret", "zapret2"}:
            try:
                self.context.processes.stop_running_bypass_copies(component_id)
            except Exception:
                try:
                    self.context.processes.stop_component(component_id)
                except Exception:
                    pass
        else:
            try:
                self.context.processes.stop_component(component_id)
            except Exception:
                pass
            time.sleep(0.15)

        ok = _attempt()
        if not ok:
            try:
                self.context.logging.log(
                    "error",
                    "Component start failed after retry",
                    component=component_id,
                )
            except Exception:
                pass
        return ok

    def _reconfigure_runtimes(
        self,
        component_ids: tuple[str, ...],
        action: Callable[[], Any],
        *,
        restart_allowed: dict[str, bool] | None = None,
        force_process_restart: dict[str, bool] | None = None,
    ) -> Any:
        """Stop → mutate → start for live components.

        If Quick Access power is ON, the active bypass (and enabled aux in the
        list) always come back even when the process was already stopped.
        Happy-path Power UI stays lit — on start failure we show starting and retry once.
        """
        want_power = self._want_runtime_power()
        settings = self.context.settings.get()
        active = str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret")

        with self._runtime_reconfigure_lock:
            running = {component_id: self._component_running(component_id) for component_id in component_ids}
            should_restart: dict[str, bool] = {}
            for component_id in component_ids:
                allowed = restart_allowed is None or bool(restart_allowed.get(component_id, True))
                if not allowed:
                    should_restart[component_id] = False
                    continue
                if running[component_id]:
                    should_restart[component_id] = True
                elif want_power and component_id == active and component_id in {"zapret", "zapret2"}:
                    should_restart[component_id] = True
                elif want_power and component_id == "xbox-dns":
                    # restart_allowed already says whether DNS should be on after apply.
                    should_restart[component_id] = True
                else:
                    should_restart[component_id] = False

            will_touch = any(running[cid] or should_restart[cid] for cid in component_ids)
            token: int | None = None
            if want_power and will_touch:
                token = self._hold_service_power()

            orch_paused = False
            if want_power and any(
                should_restart.get(cid) for cid in component_ids if cid in {"zapret", "zapret2"}
            ):
                try:
                    orch = getattr(self.context, "orchestrator", None)
                    if orch is not None:
                        orch.sync_lifecycle(zapret_active=False)
                        orch_paused = True
                except Exception:
                    pass

            restart_ok = True
            try:
                for component_id, was_running in running.items():
                    if not was_running:
                        continue
                    # Keep live bypass processes until after mutation.
                    if component_id == "zapret" and should_restart.get("zapret"):
                        continue
                    if component_id == "zapret2" and should_restart.get("zapret2"):
                        # Hot-reload path: keep winws2. Forced CLI refresh stops later.
                        if not bool((force_process_restart or {}).get("zapret2")):
                            continue
                    try:
                        self.context.processes.stop_component(component_id)
                    except Exception as error:
                        try:
                            self.context.logging.log(
                                "warning",
                                "Runtime stop before reconfiguration failed",
                                component=component_id,
                                error=str(error),
                            )
                        except Exception:
                            pass
                try:
                    return action()
                finally:
                    for component_id, do_restart in should_restart.items():
                        if not do_restart:
                            continue
                        if component_id == "zapret":
                            try:
                                state = self.context.processes.seamless_restart_zapret()
                                ok = str(getattr(state, "status", "") or "") == "running"
                            except Exception:
                                ok = False
                            if ok:
                                # The seamless path returns immediately after
                                # spawning winws. Confirm that it did not die
                                # while Windows was releasing the old driver.
                                for _ in range(5):
                                    time.sleep(0.16)
                                    if not self._component_running("zapret"):
                                        ok = False
                                        break
                            if not ok:
                                ok = self._start_component_with_retry(
                                    component_id,
                                    show_transition_on_retry=want_power,
                                )
                        elif component_id == "zapret2":
                            force_z2 = bool((force_process_restart or {}).get("zapret2"))
                            if force_z2:
                                ok = self._start_component_with_retry(
                                    "zapret2",
                                    show_transition_on_retry=want_power,
                                )
                            else:
                                ok = self._finish_zapret2_reconfigure(
                                    was_running=bool(running.get("zapret2")),
                                    show_transition_on_retry=want_power,
                                )
                        else:
                            ok = self._start_component_with_retry(
                                component_id,
                                show_transition_on_retry=want_power,
                            )
                        if not ok and component_id in {"zapret", "zapret2"}:
                            restart_ok = False
                    if want_power and any(
                        should_restart.get(cid)
                        for cid in component_ids
                        if cid in {"zapret", "zapret2"}
                    ):
                        try:
                            self._set_auxiliary_components_power_async(True)
                        except Exception:
                            pass
            finally:
                if orch_paused:
                    try:
                        self._sync_orchestrator_lifecycle()
                    except Exception:
                        pass
                if token is not None:
                    if want_power and not restart_ok:
                        # Second start already failed — settle to error, not a stuck starting.
                        if token == int(getattr(self, "_transition_token", 0) or 0):
                            self._runtime_transition_status = None
                            self._emit_runtime_status("error")
                    else:
                        self._release_service_power(token, want_power=want_power)

    def _hot_reload_zapret2_files(self) -> None:
        """Rematerialize Zapret2 lists/strategy Lua so live winws2 picks changes without kill."""
        from pathlib import Path

        from zapret_hub.services.orchestrator import zapret2_hub

        configs = Path(self.context.paths.configs_dir)
        auto_root = Path(self.context.paths.runtime_dir) / "zapret2" / "lists_auto"
        try:
            self.context.mods2.rebuild_merge()
        except Exception:
            pass
        zapret2_hub.materialize_auto_lists(configs, auto_root)
        strategy_id = str(getattr(self.context.settings.get(), "zapret2_strategy_id", "balanced") or "balanced")
        zapret2_hub.write_hub_strategy_lua(configs, strategy_id)

    def _finish_zapret2_reconfigure(self, *, was_running: bool, show_transition_on_retry: bool) -> bool:
        """Prefer hot-reload when winws2 is already up; start only if it was down."""
        if was_running and self._component_running("zapret2"):
            try:
                self._hot_reload_zapret2_files()
                try:
                    self.context.logging.log("info", "Zapret2 reconfigure applied via hot-reload (no process restart)")
                except Exception:
                    pass
                return True
            except Exception as error:
                try:
                    self.context.logging.log("warning", "Zapret2 hot-reload failed; falling back to restart", error=str(error))
                except Exception:
                    pass
        return self._start_component_with_retry("zapret2", show_transition_on_retry=show_transition_on_retry)

    def _queue_mod_toggle(self, backend: str, mod_id: str, enabled: bool) -> None:
        if not mod_id:
            return
        self._queue_mod_runtime_apply(backend, {mod_id: enabled})

    def _queue_mod_runtime_refresh(self, backend: str) -> None:
        self._queue_mod_runtime_apply(backend, {}, force_refresh=True)

    def _discard_queued_mod_toggle(self, backend: str, mod_id: str) -> None:
        with self._mod_apply_lock:
            pending = self._mod_apply_pending.get(backend)
            if pending is not None:
                pending.pop(mod_id, None)

    def _queue_mod_runtime_apply(
        self,
        backend: str,
        changes: dict[str, bool],
        *,
        force_refresh: bool = False,
    ) -> None:
        normalized_backend = "zapret2" if backend == "zapret2" else "zapret"
        with self._mod_apply_lock:
            pending = self._mod_apply_pending.setdefault(normalized_backend, {})
            pending.update({str(mod_id): bool(enabled) for mod_id, enabled in changes.items() if str(mod_id)})
            if force_refresh:
                self._mod_apply_refresh.add(normalized_backend)
            if normalized_backend in self._mod_apply_running:
                return
            self._mod_apply_running.add(normalized_backend)

        def worker() -> None:
            while True:
                # Collect rapid UI changes into one registry write and one runtime restart.
                time.sleep(0.2)
                with self._mod_apply_lock:
                    desired = dict(self._mod_apply_pending.pop(normalized_backend, {}))
                    refresh = normalized_backend in self._mod_apply_refresh
                    self._mod_apply_refresh.discard(normalized_backend)
                    if not desired and not refresh:
                        self._mod_apply_running.discard(normalized_backend)
                        return
                try:
                    manager = self.context.mods2 if normalized_backend == "zapret2" else self.context.mods

                    def apply() -> None:
                        existing = {str(item.id) for item in manager.list_installed()}
                        valid = {mod_id: enabled for mod_id, enabled in desired.items() if mod_id in existing}
                        if valid:
                            manager.set_enabled_states(valid)
                        elif normalized_backend == "zapret2":
                            manager.rebuild_merge()
                        else:
                            self.context.merge.rebuild()
                            self.context.files._invalidate_collection_cache()
                            self.context.files.rebuild_materialized_collections()

                    self._reconfigure_runtimes(
                        (normalized_backend,),
                        apply,
                        # Full Zapret2 modifications can replace winws2 arguments,
                        # not just lists. One batched restart applies that command
                        # atomically after the debounce window.
                        force_process_restart={"zapret2": normalized_backend == "zapret2"},
                    )
                    if normalized_backend == "zapret2":
                        self._cached_file2_entries = None
                    else:
                        # Mod add/remove/toggle can change general*.bat catalogs.
                        self._cached_file_entries = None
                        self._cached_generals = None
                    self.emit_state(force=True)
                except Exception as error:
                    self.context.logging.log(
                        "error",
                        "Modification reconfiguration failed",
                        backend=normalized_backend,
                        mod_ids=sorted(desired),
                        error=str(error),
                    )

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"zapret-hub-{normalized_backend}-mod-apply",
        ).start()

    def _safe_abort_diagnostics(self) -> None:
        if self.context is None:
            return
        try:
            self.context.processes.abort_diagnostics()
        except Exception:
            pass

    def _run_background(self, action: Callable[[], Any]) -> None:
        def worker() -> None:
            try:
                action()
            except Exception as error:
                self.context.logging.log("error", "Web UI background action failed", error=str(error))
            finally:
                self.emit_state()

        threading.Thread(target=worker, daemon=True).start()

    def _queue_component_toggle(self, component_id: str, enabled: bool) -> None:
        """Apply only the latest requested on/off; coalesce rapid clicks."""
        with self._component_toggle_lock:
            self._component_toggle_desired[component_id] = enabled
            if component_id in self._component_toggle_running:
                return
            self._component_toggle_running.add(component_id)

        def worker() -> None:
            while True:
                with self._component_toggle_lock:
                    if component_id not in self._component_toggle_desired:
                        self._component_toggle_running.discard(component_id)
                        return
                    desired = self._component_toggle_desired.pop(component_id)
                try:
                    aux = component_id == "xbox-dns"
                    if desired:
                        # Optional components only start when the main power is on.
                        if aux and not self._runtime_aux_should_run():
                            pass
                        else:
                            self._start_component(component_id)
                    else:
                        self.context.processes.stop_component(component_id)
                except Exception as error:
                    self.context.logging.log(
                        "error",
                        "Component toggle failed",
                        component=component_id,
                        error=str(error),
                    )
                finally:
                    self.emit_state(force=True)

        threading.Thread(target=worker, daemon=True, name=f"zapret-hub-toggle-{component_id}").start()

    def _run_runtime_background(self, action: Callable[[], Any], transition_status: str) -> None:
        self._runtime_transition_status = transition_status
        # UI already paints optimistic pendingPower — avoid a full state rebuild
        # on the click path (files/logs/tasklist), which freezes WebEngine.
        self._emit_runtime_status(transition_status)

        def worker() -> None:
            try:
                with self._runtime_action_lock:
                    action()
            except Exception as error:
                self.context.logging.log("error", "Runtime action failed", error=str(error))
            finally:
                self._runtime_transition_status = None
                try:
                    powered = self._runtime_is_powered_fast()
                    self._emit_runtime_status("on" if powered else "off")
                except Exception:
                    pass
                try:
                    self._sync_orchestrator_lifecycle()
                except Exception:
                    pass
                # Heavy reconcile after the button has settled.
                self.emit_state(force=True)

        threading.Thread(target=worker, daemon=True, name="zapret-hub-runtime-power").start()

    def _start_power_worker(self) -> None:
        """Coalesce rapid power toggles — only the latest desired on/off runs."""

        def worker() -> None:
            while True:
                with self._power_lock:
                    if self._power_desired is None:
                        self._power_running = False
                        return
                    enabled = bool(self._power_desired)
                    runtime_id = str(self._power_runtime_id or "zapret")
                    self._power_desired = None
                transition = "starting" if enabled else "stopping"
                self._transition_token += 1
                power_token = self._transition_token
                self._runtime_transition_status = transition
                self._emit_runtime_status(transition)
                try:
                    with self._runtime_action_lock:
                        # Desire may have been cancelled by a mid-flight select.
                        with self._power_lock:
                            superseded = self._power_desired is not None
                        if superseded:
                            continue
                        if enabled:
                            try:
                                self.context.processes.prepare_user_power_start()
                            except Exception:
                                pass
                        self._set_runtime_power(runtime_id, enabled)
                except Exception as error:
                    try:
                        self.context.logging.log("error", "Runtime power failed", error=str(error))
                    except Exception:
                        pass
                finally:
                    # If a newer desire arrived, keep transition for the next loop.
                    with self._power_lock:
                        more = self._power_desired is not None
                    if more:
                        continue
                    if self._transition_token == power_token:
                        self._runtime_transition_status = None
                        try:
                            if enabled:
                                # Prefer component state right after start — owned Popen is enough for "on".
                                powered = self._runtime_process_alive()
                                if not powered and runtime_id != "none":
                                    try:
                                        # Plain loop: Nuitka 4.1.3 crashes on dictcomp clone in this try/finally.
                                        states = {}
                                        for state_item in self.context.processes.list_states():
                                            states[state_item.component_id] = state_item
                                        item = states.get(runtime_id)
                                        if item is not None and str(item.status) == "error":
                                            self._emit_runtime_status("error")
                                        else:
                                            self._emit_runtime_status("error")
                                    except Exception:
                                        self._emit_runtime_status("error")
                                else:
                                    self._emit_runtime_status("on" if powered else "off")
                            else:
                                powered = self._runtime_process_alive()
                                self._emit_runtime_status("on" if powered else "off")
                        except Exception:
                            pass
                    try:
                        self._sync_orchestrator_lifecycle()
                    except Exception:
                        pass
                    self.emit_state(force=True)

        threading.Thread(target=worker, daemon=True, name="zapret-hub-runtime-power").start()

    def _emit_runtime_status(self, status: str) -> None:
        try:
            self._last_runtime_status = str(status)
            runtime_id = str(self.context.settings.get().selected_runtime_mode or "zapret")
            self.event.emit(
                "runtime.status",
                json.dumps({"status": status, "active": runtime_id}, ensure_ascii=False),
            )
            # Keep tray "Turn on/off" label hot without touching aboutToShow.
            sync_tray = getattr(self.window, "_sync_tray_power_label", None)
            if callable(sync_tray):
                self._schedule_on_gui(sync_tray)
        except Exception:
            pass

    def _peek_runtime_status(self) -> str:
        if self._runtime_transition_status in {"starting", "stopping", "on", "off"}:
            return str(self._runtime_transition_status)
        # Avoid process scans on the click path — keep last known power label.
        return str(self._last_runtime_status or "off")

    def _emit_state_if_select_gen(self, gen: int) -> None:
        if gen != self._runtime_select_gen:
            return
        self.emit_state()

    def _start_component(self, component_id: str) -> Any:
        return self.context.processes.start_component(component_id)

    def _set_no_bypass_power(self, enabled: bool) -> None:
        self.context.settings.update(no_bypass_power_enabled=enabled)
        self._set_auxiliary_components_power(enabled)

    def _set_auxiliary_components_power(self, enabled: bool) -> None:
        """Start/stop optional components that follow the main power button."""
        settings = self.context.settings.get()
        enabled_ids = {str(item) for item in (settings.enabled_component_ids or [])}
        # DNS (xbox-dns) — follows power when enabled in Components.
        if enabled and "xbox-dns" in enabled_ids:
            try:
                self._start_component("xbox-dns")
            except Exception as error:
                try:
                    self.context.logging.log("error", "Failed to start xbox-dns with runtime", error=str(error))
                except Exception:
                    pass
        else:
            try:
                self.context.processes.stop_component("xbox-dns")
            except Exception:
                pass

    def _set_auxiliary_components_power_async(self, enabled: bool) -> None:
        """Do not block main bypass power/select on TG/DNS startup."""

        def worker() -> None:
            try:
                self._set_auxiliary_components_power(enabled)
            finally:
                # Power worker often emits before TG listen is ready — push final aux status.
                try:
                    self.emit_state(force=True)
                except Exception:
                    pass

        threading.Thread(
            target=worker,
            daemon=True,
            name="zapret-hub-aux-power",
        ).start()

    def _runtime_aux_should_run(self) -> bool:
        """Whether optional components should be running with the current power state."""
        try:
            return bool(self._want_runtime_power())
        except Exception:
            return False

    def _file_target(self, kind: str, name: str = "") -> Path:
        mapping = {
            "domains": self.context.paths.configs_dir / "list-general-user.txt",
            "exclusions": self.context.paths.configs_dir / "list-exclude-user.txt",
            "ip-lists": self.context.paths.configs_dir / "ipset-all-user.txt",
            "ip-exclusions": self.context.paths.configs_dir / "ipset-exclude-user.txt",
            "hosts": self.context.files.ensure_local_hosts_file(),
            "advanced": self.context.paths.configs_dir / "advanced-user.txt",
        }
        if kind == "general":
            selected = self.context.processes._resolve_selected_general_option()
            if selected and selected.get("path"):
                return Path(str(selected["path"]))
            return self.context.paths.configs_dir / (name or "general-user.bat")
        if kind not in mapping:
            raise ValueError(f"Unsupported file kind: {kind}")
        return mapping[kind]

    def _handle_file_command(self, command: str, payload: dict[str, Any]) -> None:
        kind = str(payload.get("kind", ""))
        target = self._file_target(kind, str(payload.get("name", "")))
        target.parent.mkdir(parents=True, exist_ok=True)
        if command == "files.save":
            self.context.files.write_text(str(target), str(payload.get("content", "")))
        elif command == "files.create":
            if not target.exists():
                target.write_text("", encoding="utf-8")
        elif command == "files.rename":
            new_name = Path(str(payload.get("to", "") or target.name)).name
            destination = target.with_name(new_name)
            self.context.files._guard(destination)
            target.rename(destination)

    def _handle_mod_file_command(self, runtime: str, command: str, payload: dict[str, Any]) -> Any:
        """Expose files inside one custom mod without ever touching generated runtime files."""
        manager = self.context.mods2 if runtime == "zapret2" else self.context.mods
        mod_id = str(payload.get("id", "") or "")
        if command.endswith(".files"):
            return manager.list_files(mod_id)
        relative_path = str(payload.get("path", "") or "")
        if command.endswith(".file-read"):
            return manager.read_file(mod_id, relative_path)
        if command.endswith(".file-write"):
            manager.write_file(mod_id, relative_path, str(payload.get("content", "")))
        elif command.endswith(".file-delete"):
            manager.delete_file(mod_id, relative_path)
        self._cached_file2_entries = None if runtime == "zapret2" else self._cached_file2_entries
        self._cached_file_entries = None if runtime == "zapret" else self._cached_file_entries
        self._queue_mod_runtime_refresh(runtime)
        self.emit_state(force=True)
        return None

    def _file2_target(self, kind: str, name: str = "") -> Path:
        from zapret_hub.services.orchestrator import zapret2_hub

        paths = zapret2_hub.ensure_zapret2_lists(Path(self.context.paths.configs_dir))
        mapping = {
            "domains": paths["hub"],
            "exclusions": paths["exclude"],
            "ip-lists": paths["ipset"],
            "advanced": paths["auto"],
            "general": paths["lua_strategy"],
            # The orchestrator Lua is generated on each start and must not be
            # exposed as a user file. Lua targets are the editable Zapret2 file.
            "hosts": paths["lua_targets"],
            "ip-exclusions": paths["exclude"],
        }
        if kind not in mapping:
            raise ValueError(f"Unsupported Zapret2 file kind: {kind}")
        if name and kind == "general":
            candidate = paths["hub"].parent / Path(name).name
            if candidate.suffix.lower() in {".lua", ".txt"}:
                return candidate
        return mapping[kind]

    def _handle_file2_command(self, command: str, payload: dict[str, Any]) -> None:
        kind = str(payload.get("kind", ""))
        target = self._file2_target(kind, str(payload.get("name", "")))
        target.parent.mkdir(parents=True, exist_ok=True)
        if command == "files2.save":
            self.context.files.write_text(str(target), str(payload.get("content", "")))
        elif command == "files2.create":
            if not target.exists():
                target.write_text("", encoding="utf-8")
        elif command == "files2.rename":
            new_name = Path(str(payload.get("to", "") or target.name)).name
            destination = target.with_name(new_name)
            target.rename(destination)

    def _get_file2_entries(self) -> list[dict[str, Any]]:
        if self._cached_file2_entries is None:
            self._cached_file2_entries = self._build_file2_entries()
        return self._cached_file2_entries

    def _build_file2_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for kind in ("domains", "exclusions", "ip-lists", "advanced", "general", "hosts"):
            try:
                target = self._file2_target(kind)
                content = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
                updated = int(target.stat().st_mtime * 1000) if target.exists() else 0
                entries.append({"kind": kind, "name": target.name, "content": content, "updatedAt": updated})
            except Exception as error:
                self.context.logging.log("warning", "Failed to expose Zapret2 editable file", kind=kind, error=str(error))
        return entries

    def _run_component_update_check(self, component_id: str, request_id: str) -> None:
        def worker() -> None:
            current = ""
            latest = ""
            error = ""
            versions: list[dict[str, Any]] = []
            recommended = ""
            try:
                definitions = {item.id: item for item in self.context.processes.list_components()}
                current = str(getattr(definitions.get(component_id), "version", "") or "")

                def fill_versions(releases: list[dict[str, str]], *, current_version: str) -> None:
                    nonlocal latest, recommended, versions
                    if not releases:
                        return
                    latest = str(releases[0].get("version") or "")
                    recommended = next(
                        (str(item.get("version") or "") for item in releases if str(item.get("recommended") or "") == "1"),
                        "",
                    ) or latest
                    for item in releases:
                        version = str(item.get("version") or "")
                        versions.append(
                            {
                                "version": version,
                                "tag": str(item.get("tag") or version),
                                "publishedAt": str(item.get("published_at") or ""),
                                "prerelease": str(item.get("prerelease") or "") == "1",
                                "recommended": str(item.get("recommended") or "") == "1",
                                "current": bool(
                                    version
                                    and current_version
                                    and version.lstrip("vV").lower() == current_version.lstrip("vV").lower()
                                ),
                            }
                        )

                if component_id == "zapret":
                    current = self.context.storage._detect_zapret_version() or current
                    fill_versions(self.context.processes.list_zapret_releases(limit=30), current_version=current)
                    if not versions:
                        latest = str(self.context.processes.fetch_latest_zapret_release().get("latest_version", "") or "")
                elif component_id == "zapret2":
                    current = self.context.storage._detect_zapret2_version() or current
                    fill_versions(self.context.processes.list_zapret2_releases(limit=30), current_version=current)
                    if not versions:
                        latest = str(self.context.processes.fetch_latest_zapret2_release().get("latest_version", "") or "")
                else:
                    latest = current
            except Exception as exception:
                error = str(exception)
            available = not error and bool(latest) and latest.lstrip("vV") != current.lstrip("vV")
            self.event.emit(
                "component.update-check",
                json.dumps(
                    {
                        "requestId": request_id,
                        "id": component_id,
                        "available": available,
                        "currentVersion": current or "не определена",
                        "latestVersion": latest or "не определена",
                        "recommendedVersion": recommended or latest or "",
                        "versions": versions,
                        "error": error,
                    },
                    ensure_ascii=False,
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _run_component_update(self, component_id: str, *, version: str = "") -> None:
        wanted = str(version or "").strip()

        def zapret_action() -> dict[str, str]:
            if wanted:
                return self.context.processes.install_zapret_version(wanted)
            return self.context.processes.update_zapret_runtime()

        def zapret2_action() -> dict[str, str]:
            if wanted:
                return self.context.processes.install_zapret2_version(wanted)
            return self.context.processes.update_zapret2_runtime()

        actions = {
            "zapret": zapret_action,
            "zapret2": zapret2_action,
        }
        action = actions.get(component_id)
        if action is None:
            return

        def emit(status: str, *, version: str = "", error: str = "") -> None:
            payload = {"id": component_id, "status": status, "version": version, "error": error}
            self.event.emit("component.update-result", json.dumps(payload, ensure_ascii=False))

        emit("started")

        def worker() -> None:
            try:
                result = action()
                result_status = str((result or {}).get("status") or "updated")
                installed_version = str((result or {}).get("version") or "")
                error = str((result or {}).get("error") or "")
                if result_status == "error":
                    raise RuntimeError(error or "Component update failed")
                final_status = "up-to-date" if result_status == "up-to-date" else "success"
                self._schedule_on_gui(lambda: emit(final_status, version=installed_version))
                if final_status == "up-to-date":
                    message = "Компонент уже на этой версии." if self._ru() else "The component is already on this version."
                elif wanted:
                    message = (
                        f"Установлена версия {installed_version or wanted}."
                        if self._ru()
                        else f"Installed version {installed_version or wanted}."
                    )
                else:
                    message = "Компонент успешно обновлён." if self._ru() else "The component was updated successfully."
                self._schedule_on_gui(
                    lambda text=message: self._emit_toast(
                        text,
                        kind="success",
                        toast_id=f"component-update-{component_id}",
                    )
                )
            except Exception as exception:
                error = str(exception)
                self.context.logging.log(
                    "error",
                    "Component update failed",
                    component_id=component_id,
                    error=error,
                )
                self._schedule_on_gui(lambda message=error: emit("error", error=message))
                self._schedule_on_gui(
                    lambda message=error: self._emit_toast(
                        message,
                        kind="error",
                        toast_id=f"component-update-{component_id}",
                    )
                )
            finally:
                self._schedule_on_gui(lambda: self.emit_state(force=True))

        threading.Thread(target=worker, daemon=True, name=f"zapret-hub-update-{component_id}").start()

    def _start_onboarding_configuration(self, *, selected_services: list[str] | None = None) -> None:
        if self._onboarding_configuration_running:
            return
        self._onboarding_configuration_running = True
        self._onboarding_configuration_cancelled = False
        # "Set up again" while powered: keep Quick Access on and restore after diagnostics.
        keep_power = False
        try:
            keep_power = self._runtime_is_powered_fast() or self._last_runtime_status in {
                "on",
                "starting",
            }
        except Exception:
            keep_power = False
        if keep_power:
            self._runtime_transition_status = "starting"
            self._emit_runtime_status("starting")

        def worker() -> None:
            restore_runtime = "zapret"
            try:
                restore_runtime = str(self.context.settings.get().selected_runtime_mode or "zapret")
                # Apply the service preset in the same worker before diagnostics.
                # Running this in a second thread raced list materialization and made
                # onboarding test an older selection intermittently.
                if selected_services is not None:
                    self._apply_selected_services(selected_services, emit=False)
                general_count = max(1, len(self.context.processes.list_zapret_generals()))

                def progress(current: int, total: int, name: str) -> None:
                    steps_per_general = max(1, total // general_count)
                    overall_current = min(general_count, max(1, ((max(1, current) - 1) // steps_per_general) + 1))
                    local_current = min(steps_per_general, ((max(1, current) - 1) % steps_per_general) + 1)
                    self.event.emit(
                        "onboarding.progress",
                        json.dumps(
                            {
                                "current": local_current,
                                "total": steps_per_general,
                                "name": name.split(" - ", 1)[0],
                                "overallCurrent": overall_current,
                                "overallTotal": general_count,
                            },
                            ensure_ascii=False,
                        ),
                    )

                results = self.context.processes.run_general_diagnostics(
                    progress_callback=progress,
                    stop_callback=lambda: self._onboarding_configuration_cancelled,
                )
                if self._onboarding_configuration_cancelled:
                    self.event.emit(
                        "onboarding.configuration",
                        json.dumps({"status": "error", "name": "", "cancelled": True}, ensure_ascii=False),
                    )
                    return
                candidates = [item for item in results if isinstance(item, dict) and item.get("id")]
                working = next((item for item in candidates if item.get("status") == "ok"), None)
                chosen = working or max(candidates, key=lambda item: int(str(item.get("passed_targets", 0)) or 0), default=None)
                if self._onboarding_configuration_cancelled:
                    self.event.emit(
                        "onboarding.configuration",
                        json.dumps({"status": "error", "name": "", "cancelled": True}, ensure_ascii=False),
                    )
                    return
                if chosen is not None:
                    current = self.context.settings.get()
                    self.context.settings.update(
                        selected_zapret_general=str(chosen.get("id", "")),
                        zapret_ipset_mode=str(chosen.get("ipset_mode", current.zapret_ipset_mode) or current.zapret_ipset_mode),
                        zapret_game_filter_mode=str(chosen.get("game_mode", current.zapret_game_filter_mode) or current.zapret_game_filter_mode),
                        general_autotest_done=True,
                    )
                self.event.emit(
                    "onboarding.configuration",
                    json.dumps(
                        {
                            "status": "success" if chosen is not None else "error",
                            "name": str((chosen or {}).get("name", "")),
                            "passed": int(str((chosen or {}).get("passed_targets", 0)) or 0),
                            "total": int(str((chosen or {}).get("total_targets", 0)) or 0),
                        },
                        ensure_ascii=False,
                    ),
                )
            except Exception as error:
                self.context.logging.log("error", "Onboarding configuration failed", error=str(error))
                self.event.emit(
                    "onboarding.configuration",
                    json.dumps({"status": "error", "name": "", "error": str(error)}, ensure_ascii=False),
                )
            finally:
                self._onboarding_configuration_running = False
                self._cached_generals = None
                try:
                    self.context.processes.abort_diagnostics()
                except Exception:
                    try:
                        self.context.processes.stop_component("zapret")
                    except Exception:
                        pass
                # Reconfigure-from-settings: restore the previously powered bypass in
                # the background so Quick Access stays on while diagnostics finish.
                # Also restore after cancel — abort_diagnostics must not leave power dead.
                if keep_power:
                    try:
                        if restore_runtime in {"zapret", "zapret2"}:
                            self.context.processes.start_component(restore_runtime)
                            self._set_auxiliary_components_power_async(True)
                            self._runtime_transition_status = None
                            self._emit_runtime_status("on")
                        elif restore_runtime == "none":
                            self._set_no_bypass_power(True)
                            self._runtime_transition_status = None
                            self._emit_runtime_status("on")
                    except Exception as error:
                        try:
                            self.context.logging.log(
                                "error",
                                "Failed to restore bypass after onboarding configure",
                                error=str(error),
                            )
                        except Exception:
                            pass
                        self._runtime_transition_status = None
                        self._emit_runtime_status("starting")
                else:
                    self._runtime_transition_status = None
                try:
                    self.emit_state(force=True)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True, name="zapret-hub-onboarding-config").start()

    def _switch_running_runtime(
        self,
        runtime_id: str,
        previous_runtime_id: str,
        was_powered: bool = True,
    ) -> None:
        if not was_powered:
            return
        # Always tear down the previous bypass (image + managed process) before
        # starting the newly selected one.
        if previous_runtime_id and previous_runtime_id != "none":
            try:
                self.context.processes.stop_running_bypass_copies(previous_runtime_id)
            except Exception:
                try:
                    self.context.processes.stop_component(previous_runtime_id)
                except Exception:
                    pass
        if runtime_id == "none":
            self._set_no_bypass_power(True)
            return
        self.context.settings.update(no_bypass_power_enabled=False)
        self._start_component_with_retry(runtime_id, show_transition_on_retry=True)
        self._set_auxiliary_components_power_async(True)

    def _set_runtime_power(self, runtime_id: str, enabled: bool) -> None:
        if enabled:
            if runtime_id == "none":
                # No bypass: clear any leftover winws copies first.
                try:
                    self.context.processes.stop_running_bypass_copies("zapret")
                    self.context.processes.stop_running_bypass_copies("zapret2")
                except Exception:
                    pass
                self._set_no_bypass_power(True)
            else:
                self.context.settings.update(no_bypass_power_enabled=False)
                # 1) find + stop already-running copies of this bypass
                # 2) start Hub-owned instance (retry once on failure)
                self._start_component_with_retry(runtime_id, show_transition_on_retry=True)
                self._set_auxiliary_components_power_async(True)
            return

        # Halt Auto tuning BEFORE stop so cutover cannot race a restart.
        try:
            orch = getattr(self.context, "orchestrator", None)
            if orch is not None:
                orch.sync_lifecycle(zapret_active=False)
        except Exception:
            pass
        if runtime_id != "none":
            try:
                self.context.processes.stop_component(runtime_id)
            except Exception:
                pass
            try:
                self.context.processes.stop_running_bypass_copies(runtime_id)
            except Exception:
                pass
        self._set_no_bypass_power(False)

    def _apply_settings(self, patch: dict[str, Any]) -> None:
        before = self.context.settings.get()
        zapret_before = (
            before.zapret_ipset_mode,
            before.zapret_game_filter_mode,
            getattr(before, "zapret_gaming_set", "stun-wide-base"),
            before.zapret_udp_exclude_ports,
            before.selected_zapret_general,
        )
        zapret2_before = (
            getattr(before, "zapret2_tcp_ports", ""),
            getattr(before, "zapret2_udp_ports", ""),
            getattr(before, "zapret2_raw_filter", ""),
            getattr(before, "zapret2_lua_strategy", ""),
            getattr(before, "zapret2_strategy_id", ""),
            bool(getattr(before, "zapret2_youtube_discord_bypass", True)),
        )
        zapret2_cli_before = zapret2_before[:4] + zapret2_before[5:]
        zapret2_strategy_before = zapret2_before[4]
        changes: dict[str, Any] = {}
        aliases = {
            "autoStart": "autostart_windows",
            "minimizeToTray": "start_in_tray",
            "autoRunComponents": "auto_run_components",
            "trayNotification": "show_tray_hide_notification",
            "checkUpdates": "check_updates_on_start",
            "checkModUpdates": "check_mod_updates_on_start",
            "checkComponentUpdates": "check_component_updates_on_start",
            "windowsNotifications": "windows_notifications_enabled",
            "notificationsEnabled": "notifications_enabled",
            "hardwareAcceleration": "hardware_acceleration_enabled",
            "soundsEnabled": "sounds_enabled",
            "soundsClickEnabled": "sounds_click_enabled",
            "soundsVolume": "sounds_volume",
            "sidebarCollapsed": "sidebar_collapsed",
            "quickAccessWidget": "quick_access_widget",
            "scrollModeSwitch": "runtime_scroll_switch_enabled",
            "locale": "language",
            "theme": "theme",
            "uiScale": "ui_scale",
            "modeOrder": "runtime_mode_order",
            "discordRpcEnabled": "discord_rpc_enabled",
            "discordRpcClientId": "discord_rpc_client_id",
        }
        for source, target in aliases.items():
            if source in patch:
                changes[target] = patch[source]
        zapret = patch.get("zapret")
        if isinstance(zapret, dict):
            zapret_aliases = {
                "ipsetMode": "zapret_ipset_mode",
                "gameFilterMode": "zapret_game_filter_mode",
                "gamingSet": "zapret_gaming_set",
                "udpExclusions": "zapret_udp_exclude_ports",
                "selectedGeneral": "selected_zapret_general",
                "trustedGeneral": "trusted_general",
            }
            for source, target in zapret_aliases.items():
                if source in zapret:
                    changes[target] = zapret[source]
            if "controlMode" in zapret:
                # Mode changes go through the engine so the daemon starts/stops.
                self._set_orchestrator_mode(
                    str(zapret.get("controlMode") or "manual"), backend="zapret", emit_state=False
                )
        zapret2 = patch.get("zapret2")
        if isinstance(zapret2, dict):
            for source, target in {
                "tcpPorts": "zapret2_tcp_ports",
                "udpPorts": "zapret2_udp_ports",
                "rawFilter": "zapret2_raw_filter",
                "luaStrategy": "zapret2_lua_strategy",
                "strategyId": "zapret2_strategy_id",
                "controlMode": "zapret2_control_mode",
                "youtubeDiscordBypass": "zapret2_youtube_discord_bypass",
            }.items():
                if source in zapret2:
                    changes[target] = zapret2[source]
            if "controlMode" in zapret2:
                self._set_orchestrator_mode(
                    str(zapret2.get("controlMode") or "manual"), backend="zapret2", emit_state=False
                )
        if changes:
            if "ui_scale" in changes and str(changes.get("ui_scale") or "") not in {"0.75", "1", "1.25"}:
                changes["ui_scale"] = "1"
            self.context.settings.update(**changes)
        if "autoStart" in patch:
            self.context.autostart.set_enabled(bool(patch["autoStart"]))

        want_power = self._want_runtime_power()
        after = self.context.settings.get()
        zapret_after = (
            after.zapret_ipset_mode,
            after.zapret_game_filter_mode,
            getattr(after, "zapret_gaming_set", "stun-wide-base"),
            after.zapret_udp_exclude_ports,
            after.selected_zapret_general,
        )
        zapret2_after = (
            getattr(after, "zapret2_tcp_ports", ""),
            getattr(after, "zapret2_udp_ports", ""),
            getattr(after, "zapret2_raw_filter", ""),
            getattr(after, "zapret2_lua_strategy", ""),
            getattr(after, "zapret2_strategy_id", ""),
            bool(getattr(after, "zapret2_youtube_discord_bypass", True)),
        )
        zapret2_cli_after = zapret2_after[:4] + zapret2_after[5:]
        zapret2_strategy_after = zapret2_after[4]
        active = str(getattr(after, "selected_runtime_mode", "zapret") or "zapret")
        enabled_ids = {str(item) for item in (after.enabled_component_ids or [])}
        # Background restart while Quick Access stays visually on.
        if zapret_before != zapret_after and active == "zapret" and (self._component_running("zapret") or want_power):
            self._reconfigure_runtimes(("zapret",), lambda: None)
        if active == "zapret2" and (self._component_running("zapret2") or want_power):
            if zapret2_cli_before != zapret2_cli_after:
                # Ports / raw filter / custom CLI / bypass init need a process refresh.
                self._reconfigure_runtimes(("zapret2",), lambda: None, force_process_restart={"zapret2": True})
            elif zapret2_strategy_before != zapret2_strategy_after:
                try:
                    self._hot_reload_zapret2_files()
                except Exception as error:
                    try:
                        self.context.logging.log("warning", "Zapret2 strategy hot-reload failed", error=str(error))
                    except Exception:
                        pass
                    self._reconfigure_runtimes(("zapret2",), lambda: None)
    def emit_state(self, *, force: bool = False) -> None:
        # During onboarding the UI uses local/event state. Pushing a full
        # state.changed mid-transition freezes step animations in WebEngine.
        if self.show_onboarding and not force:
            self._pending_emit_after_onboarding = True
            return
        # Never build/push state inside a WebChannel call — and never schedule
        # QTimer from a worker thread (silent drop). Route via queued Signal.
        self._emit_state_requested.emit(bool(force))

    def _on_emit_state_requested(self, force: bool) -> None:
        if self.show_onboarding and not force:
            self._pending_emit_after_onboarding = True
            return
        if self._emit_state_scheduled:
            return
        self._emit_state_scheduled = True
        QTimer.singleShot(0, self._flush_emit_state)

    def _flush_emit_state(self) -> None:
        self._emit_state_scheduled = False
        if self.context is None:
            return
        # build_state + json.dumps (files+logs can be large) must stay off the GUI thread.
        # Tray ПКМ shares that thread — serializing full state mid-click was a multi-second stall.
        # Keep json.dumps off GUI; tray menu stays hot via setContextMenu + empty aboutToShow.
        gen = int(getattr(self, "_emit_state_build_gen", 0) or 0) + 1
        self._emit_state_build_gen = gen

        def _build_and_publish() -> None:
            if self.context is None:
                return
            try:
                payload = self.build_state()
                encoded = json.dumps(payload, ensure_ascii=False)
            except Exception as error:
                try:
                    self.context.logging.log("error", "Failed to emit UI state", error=str(error))
                except Exception:
                    pass
                return
            if gen != getattr(self, "_emit_state_build_gen", 0):
                return

            def _publish() -> None:
                if gen != getattr(self, "_emit_state_build_gen", 0):
                    return
                try:
                    status = str((payload.get("runtime") or {}).get("status") or "")
                    if status:
                        self._last_runtime_status = status
                except Exception:
                    pass
                self._last_state_payload = payload
                self.event.emit("state.changed", encoded)
                window = self.window
                # Never rebuild tray while the native context menu is open —
                # clear()/rebuild on the GUI thread races paint and feels like lag.
                if getattr(window, "_tray_menu_is_open", lambda: False)():
                    sync_tray = getattr(window, "_sync_tray_power_label", None)
                    if callable(sync_tray):
                        sync_tray()
                    return
                refresh_tray = getattr(window, "_refresh_tray_menu", None)
                if callable(refresh_tray):
                    # Defer past WebChannel/React apply so ПКМ is not queued behind polish.
                    QTimer.singleShot(50, refresh_tray)

            self._schedule_on_gui(_publish)
            self._refresh_discord_presence()

        threading.Thread(
            target=_build_and_publish,
            daemon=True,
            name="zapret-hub-emit-state",
        ).start()

    def _get_generals_payload(self) -> list[dict[str, str]]:
        if self._cached_generals is None:
            try:
                self._cached_generals = [
                    {"id": str(item.get("id", "")), "name": str(item.get("name", ""))}
                    for item in self.context.processes.list_zapret_generals()
                    if item.get("id")
                ]
            except Exception:
                self._cached_generals = []
        return self._cached_generals

    def _get_log_entries(self, *, force: bool = False) -> list[dict[str, Any]]:
        # Brief cache so emit_state / state.get cannot monopolize the GUI thread
        # (tray menu waits on that same thread — previously ~2s when logs+tasklist+socket ran).
        now = time.time()
        cached_at = float(getattr(self, "_cached_log_entries_at", 0.0) or 0.0)
        if (
            not force
            and self._cached_log_entries is not None
            and (now - cached_at) < 2.5
        ):
            return self._cached_log_entries
        self._cached_log_entries = self._build_log_entries()
        self._cached_log_entries_at = now
        return self._cached_log_entries

    def _runtime_is_powered_fast(self) -> bool:
        if self._runtime_transition_status in {"on", "starting"}:
            return True
        if self._runtime_transition_status in {"off", "stopping"}:
            return False
        return self._runtime_process_alive()

    def _get_file_entries(self) -> list[dict[str, Any]]:
        if self._cached_file_entries is None:
            self._cached_file_entries = self._build_file_entries()
        return self._cached_file_entries

    def _build_file_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for kind in ("domains", "exclusions", "ip-lists", "ip-exclusions", "general", "hosts", "advanced"):
            try:
                target = self._file_target(kind)
                content = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
                updated = int(target.stat().st_mtime * 1000) if target.exists() else 0
                entries.append({"kind": kind, "name": target.name, "content": content, "updatedAt": updated})
            except Exception as error:
                self.context.logging.log("warning", "Failed to expose editable file", kind=kind, error=str(error))
        return entries

    def _build_log_entries(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for index, entry in enumerate(self.context.logging.read_entries()[-300:]):
            component_id = str(entry.context.get("component_id", "") or "")
            source = {
                "zapret": "zapret",
                "zapret2": "zapret2",
            }.get(component_id, "app")
            try:
                raw = str(entry.timestamp or "").strip()
                # Prefer aware ISO (local offset); fall back to naive local wall-clock.
                if raw.endswith("Z"):
                    stamp_dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()
                else:
                    stamp_dt = datetime.fromisoformat(raw)
                    if stamp_dt.tzinfo is not None:
                        stamp_dt = stamp_dt.astimezone()
                timestamp = int(stamp_dt.timestamp() * 1000)
            except Exception:
                timestamp = int(time.time() * 1000)
            level = str(entry.level or "info").lower()
            result.append(
                {
                    "id": f"{timestamp}-{index}",
                    "source": source,
                    "level": level if level in {"info", "warn", "error", "debug"} else "info",
                    "message": entry.message,
                    "ts": timestamp,
                }
            )

        # Merge process stdout/stderr tails (Zapret, Zapret2). These are plain
        # text files — never written into app.log JSON — so without this the UI is
        # empty when running "без обходов" (only hub lines would appear as "app").
        seen_messages: set[tuple[str, str]] = {(str(item.get("source")), str(item.get("message"))) for item in result}
        plain_sources = (
            ("zapret", "zapret.log", 180),
            ("zapret2", "zapret2.log", 180),
        )
        ordinal = len(result)
        for ui_source, filename, limit in plain_sources:
            try:
                records = self.context.logging._read_plain_log_tail_records(filename, limit=limit)
            except Exception:
                continue
            for stamp, line in records:
                message = str(line or "").strip()
                if not message or message.startswith("==="):
                    continue
                key = (ui_source, message)
                if key in seen_messages:
                    continue
                seen_messages.add(key)
                level = "error" if "error" in message.lower() or "traceback" in message.lower() else "info"
                if "warn" in message.lower():
                    level = "warn"
                ts_ms = int(stamp * 1000) if stamp else int(time.time() * 1000)
                result.append(
                    {
                        "id": f"plain-{ui_source}-{ts_ms}-{ordinal}",
                        "source": ui_source,
                        "level": level,
                        "message": message,
                        "ts": ts_ms,
                    }
                )
                ordinal += 1

        result.sort(key=lambda item: int(item.get("ts") or 0))
        return result[-400:]

    def _mod_cover_url(self, item: Any) -> str:
        """Prefer locally cached author cover (cropped square in UI); fall back to remote URL."""
        try:
            root = Path(str(getattr(item, "path", "") or ""))
            if root.is_dir():
                covers = sorted(root.glob("zapret-hub-cover.*"))
                for cover in covers:
                    if cover.is_file() and cover.stat().st_size > 0:
                        return cover.resolve().as_uri()
        except Exception:
            pass
        stored = str(getattr(item, "icon_url", "") or "").strip()
        if stored.startswith(("http://", "https://", "file:", "data:")):
            return stored
        return stored

    @staticmethod
    def _mod_disk_size(item: Any) -> int:
        try:
            root = Path(str(getattr(item, "path", "") or ""))
            if root.is_file():
                return int(root.stat().st_size)
            if root.is_dir():
                return sum(int(path.stat().st_size) for path in root.rglob("*") if path.is_file())
        except (OSError, ValueError):
            pass
        return 0

    def _installed_mods_payload(self, runtime: str) -> list[dict[str, Any]]:
        """Installed-mod data for the Mods pages (marketplace removed)."""
        manager = self.context.mods if runtime == "zapret" else self.context.mods2
        settings = self.context.settings.get()
        enabled_ids = {
            str(item)
            for item in (
                settings.enabled_mod_ids if runtime == "zapret" else getattr(settings, "enabled_zapret2_mod_ids", None) or []
            )
        }
        result: list[dict[str, Any]] = []
        for item in manager.list_installed():
            result.append(
                {
                    "id": item.id,
                    "name": item.name or item.id,
                    "author": item.author,
                    "description": item.description,
                    "createdAt": int(time.time() * 1000),
                    "iconUrl": self._mod_cover_url(item),
                    "sourceUrl": str(getattr(item, "source_url", "") or ""),
                    "version": item.version,
                    "enabled": bool(item.enabled or item.id in enabled_ids),
                    "diskSize": self._mod_disk_size(item),
                    "compatibility": "zapret" if runtime == "zapret" else "zapret2",
                }
            )
        return result

    def _mods_payload(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "mods": self._installed_mods_payload("zapret"),
            "mods2": self._installed_mods_payload("zapret2"),
        }

    def build_state(self) -> dict[str, Any]:
        settings = self.context.settings.get()
        definitions = {item.id: item for item in self.context.processes.list_components()}
        states = {item.component_id: item for item in self.context.processes.list_states()}
        components: dict[str, dict[str, Any]] = {}
        enabled_ids = {str(item) for item in (settings.enabled_component_ids or [])}
        component_descriptions = {
            "zapret": (
                "Основной модуль локальной обработки сетевого трафика.",
                "The primary local network traffic processing module.",
            ),
            "zapret2": (
                "Новое поколение zapret с winws2 и Lua-стратегиями.",
                "Next-generation zapret powered by winws2 and Lua strategies.",
            ),
            "xbox-dns": (
                "Системные DNS-серверы с выбором провайдера.",
                "System DNS servers with a selectable provider.",
            ),
        }
        for component_id in _COMPONENT_IDS:
            definition = definitions.get(component_id)
            state = states.get(component_id)
            raw_status = str(getattr(state, "status", "stopped"))
            status = {"running": "on", "stopped": "off", "failed": "error"}.get(raw_status, raw_status)
            components[component_id] = {
                "id": component_id,
                "name": getattr(definition, "name", component_id),
                "version": getattr(definition, "version", ""),
                "status": status if status in {"off", "on", "starting", "error", "updating"} else "off",
                "enabled": component_id in enabled_ids,
                "description": component_descriptions.get(
                    component_id,
                    (getattr(definition, "description", ""), getattr(definition, "description", "")),
                )[0 if settings.language == "ru" else 1],
                "config": getattr(state, "last_error", "") or "",
                "externalUrl": getattr(definition, "source", ""),
                "meta": {"PID": str(getattr(state, "pid", "") or "")},
            }
            if component_id == "xbox-dns":
                components[component_id].update(
                    {
                        "name": "DNS",
                        "description": component_descriptions["xbox-dns"][0 if settings.language == "ru" else 1],
                        "config": str(getattr(settings, "dns_profile", "xbox") or "xbox").upper(),
                    }
                )
            if component_id == "xbox-dns":
                components[component_id]["version"] = ""
            elif component_id == "zapret2" and str(components[component_id]["version"]).lower() in {"", "master"}:
                components[component_id]["version"] = "1.0.4"
        runtime_id = str(settings.selected_runtime_mode or "zapret")
        if runtime_id == "none":
            auxiliary = [components.get("xbox-dns", {}).get("status", "off")]
            runtime_status = (
                "error" if any(item == "error" for item in auxiliary)
                else "starting" if any(item == "starting" for item in auxiliary)
                else "on" if settings.no_bypass_power_enabled
                else "off"
            )
        else:
            runtime_status = str(components.get(runtime_id, {}).get("status", "off"))
        if self._runtime_transition_status is not None:
            runtime_status = self._runtime_transition_status
        elif (
            runtime_status == "off"
            and self._last_runtime_status in {"on", "starting"}
            and not (runtime_id == "none" and not bool(settings.no_bypass_power_enabled))
        ):
            # Brief gap while a powered bypass restarts — don't flicker the button off.
            runtime_status = self._last_runtime_status
        mods = self._installed_mods_payload("zapret")
        mods2 = self._installed_mods_payload("zapret2")
        notifications = [
            {
                "id": item.id,
                "title": item.title,
                "body": item.message,
                "ts": int(time.time() * 1000),
                "read": item.read,
                "level": item.level if item.level in {"info", "warn", "error", "success"} else "info",
            }
            for item in self.context.notifications.list()
        ]
        return {
            "runtime": {
                "active": runtime_id,
                "order": list(settings.runtime_mode_order or ["zapret", "zapret2", "none"]),
                "status": runtime_status,
            },
            "services": {
                "available": [
                    {
                        "id": item.id,
                        "name": item.title_ru if settings.language == "ru" else item.title_en,
                        "description": item.description_ru if settings.language == "ru" else item.description_en,
                    }
                    for item in SERVICE_PRESETS
                ],
                "selected": list(settings.selected_service_ids or []),
            },
            "components": components,
            "mods": mods,
            "mods2": mods2,
            "files": self._get_file_entries(),
            "files2": self._get_file2_entries(),
            "logs": self._get_log_entries(),
            "settings": {
                "autoStart": bool(settings.autostart_windows),
                "minimizeToTray": bool(settings.start_in_tray),
                "autoRunComponents": bool(settings.auto_run_components),
                "trayNotification": bool(settings.show_tray_hide_notification),
                "checkUpdates": bool(settings.check_updates_on_start),
                "checkModUpdates": bool(getattr(settings, "check_mod_updates_on_start", True)),
                "checkComponentUpdates": bool(getattr(settings, "check_component_updates_on_start", True)),
                "windowsNotifications": bool(settings.windows_notifications_enabled),
                "notificationsEnabled": bool(settings.notifications_enabled),
                "hardwareAcceleration": bool(settings.hardware_acceleration_enabled),
                "soundsEnabled": bool(settings.sounds_enabled),
                "soundsClickEnabled": bool(getattr(settings, "sounds_click_enabled", True)),
                "soundsVolume": str(settings.sounds_volume or "normal"),
                "sidebarCollapsed": bool(settings.sidebar_collapsed),
                "quickAccessWidget": str(settings.quick_access_widget or "analysis"),
                "scrollModeSwitch": bool(getattr(settings, "runtime_scroll_switch_enabled", True)),
                "uiScale": str(getattr(settings, "ui_scale", "1") or "1"),
                "discordRpcEnabled": bool(getattr(settings, "discord_rpc_enabled", True)),
                "discordRpcClientId": str(getattr(settings, "discord_rpc_client_id", "") or ""),
                "discordRpcStatus": self._discord_rpc_status_payload(),

                "zapret": {
                    "ipsetMode": settings.zapret_ipset_mode,
                    "gameFilterMode": settings.zapret_game_filter_mode,
                    "gamingSet": settings.zapret_gaming_set,
                    "udpExclusions": settings.zapret_udp_exclude_ports,
                    "selectedGeneral": settings.selected_zapret_general,
                    "controlMode": str(getattr(settings, "zapret_control_mode", "manual") or "manual"),
                    "trustedGeneral": str(getattr(settings, "trusted_general", "") or ""),
                    "generals": self._get_generals_payload(),
                },
                "zapret2": {
                    "controlMode": str(getattr(settings, "zapret2_control_mode", "manual") or "manual"),
                    "tcpPorts": settings.zapret2_tcp_ports,
                    "udpPorts": settings.zapret2_udp_ports,
                    "rawFilter": settings.zapret2_raw_filter,
                    "luaStrategy": settings.zapret2_lua_strategy,
                    "strategyId": str(getattr(settings, "zapret2_strategy_id", "balanced") or "balanced"),
                    "youtubeDiscordBypass": bool(getattr(settings, "zapret2_youtube_discord_bypass", True)),
                },
                "dns": {"profile": str(getattr(settings, "dns_profile", "xbox") or "xbox")},
                "theme": settings.theme,
            },
            "notifications": notifications,
            "orchestrator": self._orchestrator_snapshot(),
            "onboarding": {
                # completed = marker seen (not tied to overlay visibility).
                "completed": (self.context.paths.data_dir / ".services_onboarding_seen_v4").exists(),
                # forceOpen = re-open after completion (tray / onboarding.open). Not first-run.
                "forceOpen": bool(self.show_onboarding)
                and (self.context.paths.data_dir / ".services_onboarding_seen_v4").exists(),
                "initialMode": self._onboarding_initial_mode,
                "isUpdate": onboarding_is_update(self.context.paths.data_dir),
            },
            "ui": {
                "locale": settings.language if settings.language in {"ru", "en"} else "ru",
                "theme": settings.theme,
            },
        }


class WebMainWindow(QMainWindow):
    shutdown_finished = Signal()

    def __init__(
        self,
        context: Any | None = None,
        *,
        launch_hidden: bool = False,
        startup_show_onboarding: bool = False,
        startup_snapshot: dict[str, Any] | None = None,
        early_shell: bool = False,
    ) -> None:
        super().__init__()
        del startup_snapshot
        self.context = context
        self._launch_hidden = launch_hidden
        self._force_exit = False
        self.setWindowTitle("Zapret Hub")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # Early shell opens fully visible with the CSS preloader; later restores still fade in.
        self.setWindowOpacity(1.0 if early_shell or context is None else 0.0)
        self._window_animation: QPropertyAnimation | None = None
        self._first_show = True
        self._ui_ready = False
        self._show_when_ready_requested = False
        self._pending_quit_after_stop = False
        self._bound = False
        self._ui_loaded = False
        self._opened_as_early_shell = bool(early_shell or context is None)
        self._tray_notification_ids: set[str] = set()
        self.shutdown_finished.connect(self._finish_exit_after_shutdown)
        self.bridge: WebBridge | None = None
        self.channel: QWebChannel | None = None
        self._pending_deeplink: str | None = None

        self.view = QWebEngineView(self)
        self.view.setFixedSize(_WINDOW_WIDTH, _WINDOW_HEIGHT)
        self.view.page().setBackgroundColor(QColor(Qt.GlobalColor.transparent))
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        # WebEngine shows a busy/progress cursor while the page loads — keep a normal arrow.
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.view.setCursor(Qt.CursorShape.ArrowCursor)
        self._cursor_guard_timer = QTimer(self)
        self._cursor_guard_timer.setInterval(40)
        self._cursor_guard_timer.timeout.connect(self._force_arrow_cursor)
        self.view.loadStarted.connect(self._on_web_load_started)
        self.view.loadProgress.connect(self._force_arrow_cursor)
        self.view.loadFinished.connect(self._on_web_load_finished)
        self.setCentralWidget(self.view)
        self._apply_startup_geometry()
        self.winId()
        _disable_native_window_rounding(self)
        self._force_arrow_cursor()

        if early_shell or context is None:
            return

        self.bind_application(
            context,
            launch_hidden=launch_hidden,
            startup_show_onboarding=startup_show_onboarding,
        )

    def _on_web_load_started(self) -> None:
        self._force_arrow_cursor()
        if not self._cursor_guard_timer.isActive():
            self._cursor_guard_timer.start()

    def _on_web_load_finished(self, _ok: bool = True) -> None:
        self._cursor_guard_timer.stop()
        self._force_arrow_cursor()
        # Clear any leftover Windows "app starting" busy cursor after first paint.
        QTimer.singleShot(0, self._force_arrow_cursor)
        QTimer.singleShot(120, self._force_arrow_cursor)

    def _force_arrow_cursor(self, *_args: Any) -> None:
        """Prevent Chromium/WebEngine from switching to the loading/busy cursor."""
        try:
            while True:
                override = QGuiApplication.overrideCursor()
                if override is None:
                    break
                shape = override.shape()
                if shape in {Qt.CursorShape.WaitCursor, Qt.CursorShape.BusyCursor}:
                    QGuiApplication.restoreOverrideCursor()
                    continue
                break
        except Exception:
            pass
        try:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.view.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:
            pass
        if sys.platform.startswith("win"):
            try:
                # IDC_ARROW = 32512 — also clears the OS APPSTARTING spinner if stuck.
                ctypes.windll.user32.SetCursor(ctypes.windll.user32.LoadCursorW(0, 32512))
            except Exception:
                pass

    @staticmethod
    def _resolve_install_root() -> Path:
        if is_packaged_runtime():
            return packaged_install_root()
        return development_install_root(__file__)

    @classmethod
    def create_early_shell(cls, icon: QIcon | None = None) -> "WebMainWindow":
        window = cls(None, early_shell=True)
        if icon is not None:
            try:
                window.setWindowIcon(icon)
            except Exception:
                pass
        # Load the real frontend once (CSS preloader in index.html). Bootstrap only binds context later —
        # no second navigation, so the window does not blink away.
        window._load_frontend(window._resolve_install_root(), startup_show_onboarding=False, theme="night")
        return window

    def _load_frontend(self, install_root: Path, *, startup_show_onboarding: bool, theme: str) -> None:
        if self.bridge is None:
            self.bridge = WebBridge(self.context, self, show_onboarding=startup_show_onboarding)
        if self.channel is None:
            self.channel = QWebChannel(self.view.page())
            self.channel.registerObject("bridge", self.bridge)
            self.view.page().setWebChannel(self.channel)

        index_path = install_root / "web_ui" / "dist" / "index.html"
        if not index_path.exists():
            # Fallback keeps a visible CSS preloader if the bundle is missing.
            self.view.setHtml(_STARTUP_PRELOADER_HTML, QUrl("https://zapret.local/startup/"))
            self._ui_loaded = True
            return
        page_url = QUrl.fromLocalFile(str(index_path.resolve()))
        query = QUrlQuery()
        query.addQueryItem("theme", theme or "night")
        if startup_show_onboarding:
            query.addQueryItem("startupOnboarding", "1")
        page_url.setQuery(query)
        self.view.setUrl(page_url)
        self._ui_loaded = True

    def bind_application(
        self,
        context: Any,
        *,
        launch_hidden: bool = False,
        startup_show_onboarding: bool = False,
    ) -> None:
        self.context = context
        self._launch_hidden = launch_hidden
        self._tray_notification_ids = {item.id for item in self.context.notifications.list()}
        hardware_acceleration = bool(self.context.settings.get().hardware_acceleration_enabled)
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, hardware_acceleration)
        self.view.settings().setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, hardware_acceleration)

        theme = str(self.context.settings.get().theme or "night")

        if self._ui_loaded and self.bridge is not None:
            # Same page: attach real context and push state — do not reload (avoids window blink).
            self.bridge.context = context
            self.bridge.show_onboarding = startup_show_onboarding
            self.bridge._wire_orchestrator()
            self.bridge._wire_discord_presence()
            theme_attr = "concrete" if theme == "light" else "aurora" if theme == "night" else "obsidian"
            ui_scale = str(getattr(self.context.settings.get(), "ui_scale", "1") or "1")
            if ui_scale not in {"0.75", "1", "1.25"}:
                ui_scale = "1"
            try:
                self.view.page().runJavaScript(
                    f"document.documentElement.dataset.theme={json.dumps(theme_attr)};"
                    f"document.documentElement.style.zoom={json.dumps(ui_scale)};"
                    f"document.documentElement.dataset.uiScale={json.dumps(ui_scale)};"
                )
            except Exception:
                pass
            if getattr(self, "tray_icon", None) is None:
                self._setup_tray()
                self._notification_timer = QTimer(self)
                self._notification_timer.setInterval(900)
                self._notification_timer.timeout.connect(self._flush_windows_notifications)
                self._notification_timer.start()
            else:
                try:
                    self.tray_icon.setVisible(True)
                    self.tray_icon.show()
                except Exception:
                    pass
            self._bound = True
            self._push_startup_state()
            return

        if self.bridge is None:
            self.bridge = WebBridge(context, self, show_onboarding=startup_show_onboarding)
        else:
            self.bridge.context = context
            self.bridge.show_onboarding = startup_show_onboarding
            self.bridge._wire_orchestrator()
            self.bridge._wire_discord_presence()

        self._load_frontend(
            Path(context.paths.install_root),
            startup_show_onboarding=startup_show_onboarding,
            theme=theme,
        )
        self._setup_tray()
        self._notification_timer = QTimer(self)
        self._notification_timer.setInterval(900)
        self._notification_timer.timeout.connect(self._flush_windows_notifications)
        self._notification_timer.start()
        self._bound = True
        self._push_startup_state()

    def _push_startup_state(self) -> None:
        """Push state now and again shortly after — late UI subscribers must not miss it."""
        if self.bridge is None:
            return

        def emit() -> None:
            if self.bridge is None or self.bridge.context is None:
                return
            try:
                # Fresh AppData starts with onboarding, which normally suppresses
                # emit_state. Force the bootstrap pushes so the preloader can hide.
                self.bridge.emit_state(force=True)
            except Exception:
                pass

        emit()
        QTimer.singleShot(0, emit)
        QTimer.singleShot(200, emit)
        # Avoid a third forced emit ~1s later — it re-renders React mid onboarding intro.

    def _apply_startup_geometry(self) -> None:
        width, height = _WINDOW_WIDTH, _WINDOW_HEIGHT
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = avail.x() + max(0, (avail.width() - width) // 2)
            y = avail.y() + max(0, (avail.height() - height) // 2)
            self.setGeometry(QRect(x, y, width, height))
        else:
            self.resize(width, height)
        self.setFixedSize(width, height)
        self.view.setFixedSize(width, height)

    def _reveal_window(self) -> None:
        self._apply_startup_geometry()
        if self._opened_as_early_shell:
            self.setWindowOpacity(1.0)
            self.show()
            self.showNormal()
            _bring_widget_to_front(self)
            QTimer.singleShot(0, lambda: _bring_widget_to_front(self))
            return
        self.setWindowOpacity(0.0)
        self.show()
        self.showNormal()
        _bring_widget_to_front(self)
        QTimer.singleShot(0, lambda: _bring_widget_to_front(self))

    def attach_backend_client(self, backend: Any) -> None:
        if self.context is None:
            return
        self.context.backend = backend

    def mark_ui_ready(self) -> None:
        self._ui_ready = True
        # Window is already visible with the HTML preloader; ui.ready only
        # means the React shell finished its first useful paint.
        self._show_when_ready_requested = False
        self._release_boot_cursor()
        self._maybe_emit_demo_update_prompt()
        if self.bridge is not None:
            self.bridge._maybe_schedule_startup_update_check()
        if self._pending_deeplink:
            link = self._pending_deeplink
            self._pending_deeplink = None
            QTimer.singleShot(400, lambda: self.handle_deeplink(link))

    def handle_deeplink(self, raw: str) -> None:
        from zapret_hub.services.deeplink import parse_zaprethub_url

        parsed = parse_zaprethub_url(raw)
        if not parsed:
            return
        try:
            self.restore_from_external_launch()
        except Exception:
            pass
        action = str(parsed.get("action") or "")
        slug = str(parsed.get("slug") or "")
        if not slug:
            return
        # Marketplace deep links were removed together with the component; the
        # generic install alias is no longer actionable.
        return

    def queue_deeplink(self, raw: str) -> None:
        if getattr(self, "_ui_ready", False):
            self.handle_deeplink(raw)
        else:
            self._pending_deeplink = raw

    def _release_boot_cursor(self) -> None:
        try:
            while QGuiApplication.overrideCursor() is not None:
                QGuiApplication.restoreOverrideCursor()
        except Exception:
            pass
        self._force_arrow_cursor()

    def _maybe_emit_demo_update_prompt(self) -> None:
        if self.context is None or self.bridge is None:
            return
        marker = Path(self.context.paths.data_dir) / ".force_update_ui_once"
        if not marker.exists():
            return
        try:
            marker.unlink(missing_ok=True)
        except Exception:
            return
        from zapret_hub import __version__

        payload = {
            "currentVersion": str(__version__),
            "latestVersion": "3.0.2",
            "changelog": (
                "• Улучшения интерфейса быстрого доступа\n"
                "• Исправления стабильности переключения страниц\n"
                "• Обновления компонентов обхода"
            ),
            "htmlUrl": "https://github.com/klondike0x/zapret-hub-continuation/releases",
            "demo": True,
        }
        QTimer.singleShot(700, lambda: self.bridge.event.emit("app.update-available", json.dumps(payload, ensure_ascii=False)))

    def show_when_ready(self) -> None:
        if self._launch_hidden:
            self.prepare_hidden_tray_launch()
            return
        # Open immediately with the HTML preloader; do not wait for ui.ready.
        self._show_when_ready_requested = False
        if not self.isVisible():
            self._reveal_window()

    def prepare_hidden_tray_launch(self) -> None:
        """Autostart / start-in-tray: stay in tray without a ghost empty window.

        Clears first-show hide flags so a later tray click can actually restore.
        """
        self._launch_hidden = False
        self._first_show = False
        try:
            if self._window_animation is not None:
                self._window_animation.stop()
                self._window_animation = None
        except Exception:
            pass
        self.setWindowOpacity(1.0)
        self.hide()

    def start_enabled_components_async(self, *, autostart_only: bool = False) -> None:
        if self.context is None:
            return
        action = self.context.processes.start_autostart_components if autostart_only else self.context.processes.start_enabled_components
        bridge = self.bridge
        select_gen = int(getattr(bridge, "_runtime_select_gen", 0) or 0) if bridge is not None else 0

        def _run() -> None:
            try:
                if bridge is not None:
                    # User already took power/select control — don't fight them.
                    if getattr(bridge, "_power_user_touched", False):
                        return
                    if int(getattr(bridge, "_runtime_select_gen", 0) or 0) != select_gen:
                        return
                    with bridge._power_lock:
                        if bridge._power_desired is False:
                            return
                    with bridge._runtime_action_lock:
                        if getattr(bridge, "_power_user_touched", False):
                            return
                        if int(getattr(bridge, "_runtime_select_gen", 0) or 0) != select_gen:
                            return
                        action()
                else:
                    action()
            except Exception:
                try:
                    action()
                except Exception:
                    pass
            finally:
                try:
                    if bridge is not None:
                        bridge.emit_state(force=True)
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True, name="zapret-hub-autostart").start()

    def request_autostart_power(self) -> None:
        """Turn Quick Access power on with the user's last selected mode/settings."""
        if self.context is None or self.bridge is None:
            return
        bridge = self.bridge
        try:
            if getattr(bridge, "_power_user_touched", False):
                return
        except Exception:
            pass
        try:
            from zapret_hub.services.backend_worker import _sync_bypass_enabled_for_mode

            runtime_id = str(self.context.settings.get().selected_runtime_mode or "zapret")
            if runtime_id in {"zapret", "zapret2", "none"}:
                _sync_bypass_enabled_for_mode(self.context, runtime_id)
        except Exception:
            pass
        # Same path as the power button — starts selected bypass + aux components.
        try:
            bridge._dispatch("runtime.power", {"on": True})
        except Exception:
            try:
                self.start_enabled_components_async(autostart_only=False)
            except Exception:
                pass

    def restore_from_external_launch(self, *, deeplink: str | None = None) -> None:
        # Must clear tray-boot flags BEFORE show() — otherwise showEvent re-hides
        # the window on the first restore after --autostart-launch + start_in_tray.
        self._launch_hidden = False
        self._first_show = False
        self._apply_startup_geometry()
        # Do not fade a hidden WebEngine window back from opacity 0.  Chromium can
        # publish a transparent native frame before its first composited frame after
        # a long stay in the tray, which looks like an empty application window.
        try:
            if self._window_animation is not None:
                self._window_animation.stop()
                self._window_animation = None
        except Exception:
            pass
        self.setWindowOpacity(1.0)
        self.show()
        self.showNormal()
        _bring_widget_to_front(self)
        self._resume_web_view_after_tray()
        QTimer.singleShot(0, lambda: _bring_widget_to_front(self))
        if deeplink:
            QTimer.singleShot(200, lambda: self.handle_deeplink(deeplink))

    def _resume_web_view_after_tray(self) -> None:
        """Wake the existing page without rebuilding the complete React state."""
        try:
            page = self.view.page()
            lifecycle = getattr(QWebEnginePage, "LifecycleState", None)
            active = getattr(lifecycle, "Active", None)
            if active is not None:
                page.setLifecycleState(active)
        except Exception:
            pass
        try:
            self.view.setUpdatesEnabled(True)
            self.view.show()
            self.view.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            self.view.update()
        except Exception:
            pass

        def _refresh_compositor() -> None:
            if not self.isVisible():
                return
            try:
                self.view.page().runJavaScript(
                    "requestAnimationFrame(() => window.dispatchEvent(new Event('resize')));"
                )
                self.view.update()
            except Exception:
                pass

        # The second frame covers systems where the WebEngine renderer wakes just
        # after the native window has been shown.
        QTimer.singleShot(0, _refresh_compositor)
        QTimer.singleShot(80, _refresh_compositor)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        self._apply_startup_geometry()
        if self._first_show:
            self._first_show = False
            if self._launch_hidden:
                # Only for accidental first show before prepare_hidden_tray_launch().
                self._launch_hidden = False
                QTimer.singleShot(0, self.hide)
                return
            if self._opened_as_early_shell:
                self.setWindowOpacity(1.0)
                _bring_widget_to_front(self)
            else:
                _bring_widget_to_front(self)
                self._animate_opacity(0.0, 1.0, 170)

    def _animate_opacity(self, start: float, end: float, duration: int, finished: Callable[[], None] | None = None) -> None:
        if self._window_animation is not None:
            self._window_animation.stop()
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(duration)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        if finished is not None:
            animation.finished.connect(finished)
        self._window_animation = animation
        animation.start()

    def _cancel_onboarding_configuration(self) -> None:
        bridge = self.bridge
        if bridge is None:
            return
        bridge._onboarding_configuration_cancelled = True
        context = self.context
        if context is None:
            return
        config_running = bool(getattr(bridge, "_onboarding_configuration_running", False))
        diagnostic = False
        try:
            diagnostic = bool(getattr(context.processes, "_diagnostic_runtime_override", False))
        except Exception:
            diagnostic = False
        # Hiding to tray / quitting must not stop a healthy powered bypass.
        if not config_running and not diagnostic:
            return

        def _stop_diagnostic_runtime() -> None:
            try:
                context.processes.abort_diagnostics()
            except Exception:
                pass

        threading.Thread(target=_stop_diagnostic_runtime, daemon=True, name="zapret-hub-cancel-config").start()

    def fade_minimize(self) -> None:
        # Minimize may keep config selection running in the background.
        self._animate_opacity(self.windowOpacity(), 0.0, 110, self._finish_minimize)

    def _finish_minimize(self) -> None:
        self.showMinimized()
        self.setWindowOpacity(1.0)

    def fade_close(self) -> None:
        if self._force_exit:
            # Previous quit got stuck — hard-kill the process.
            os._exit(0)
        # Closing the window stops config selection only while it is running.
        # Only minimize keeps selection running in the background.
        bridge = self.bridge
        config_running = bool(bridge and getattr(bridge, "_onboarding_configuration_running", False))
        onboarding_open = bool(bridge and getattr(bridge, "show_onboarding", False))
        if config_running or onboarding_open:
            self._cancel_onboarding_configuration()
        status = self._runtime_power_status()
        # Diagnostics temporarily starts zapret, which would otherwise look like
        # "power on" and incorrectly hide to tray instead of quitting.
        if status in {"on", "starting"} and not config_running and not onboarding_open:
            self._animate_opacity(self.windowOpacity(), 0.0, 120, self._hide_to_tray)
            return
        self._exit_from_tray(reason="fade-close")

    def _setup_tray(self) -> None:
        if self.context is None:
            return
        # Tear down a dead/None tray from a previous exit so we always recreate.
        existing = getattr(self, "tray_icon", None)
        if existing is not None:
            try:
                existing.hide()
            except Exception:
                pass
        install_root = Path(self.context.paths.install_root)
        icon_path = install_root / "ui_assets" / "icons" / "app.ico"
        if not icon_path.exists():
            icon_path = install_root / "ui_assets" / "icons" / "app.png"
        icon = QIcon(str(icon_path)) if icon_path.exists() else self.windowIcon()
        if icon.isNull():
            icon = QIcon(str(install_root / "ui_assets" / "icons" / "app.png"))
        self.tray_icon = QSystemTrayIcon(icon, self)
        # QMenu must NOT be parented to QApplication (not a QWidget) — that broke
        # the tray icon/menu on Windows after tray_fix2/fix3. Keep an unparented
        # menu with a strong Python ref on self.
        self._tray_menu = QMenu()
        self._tray_menu.setObjectName("zapretHubTrayMenu")
        self._tray_menu_sig: tuple[Any, ...] | None = None
        # No border-radius: rounded QMenus force an expensive region mask on Windows.
        self._tray_menu.setStyleSheet(
            """
            QMenu {
                background: #151820;
                color: #edf1f8;
                border: 1px solid #2a3140;
                padding: 4px;
            }
            QMenu::item {
                min-width: 150px;
                padding: 7px 12px;
            }
            QMenu::item:selected { background: #252a35; }
            QMenu::separator {
                height: 1px;
                margin: 5px 8px;
                background: #2a3140;
            }
            """
        )
        self._tray_show_action = QAction(self)
        self._tray_toggle_action = QAction(self)
        self._tray_quit_action = QAction(self)
        self._tray_cached_language = "ru"
        self._tray_cached_runtime_on = False
        self._tray_runtime_menu = self._tray_menu.addMenu("")
        self._tray_runtime_detail_menu = self._tray_menu.addMenu("")
        self._tray_show_action.triggered.connect(self.restore_from_external_launch)
        self._tray_toggle_action.triggered.connect(self._tray_toggle_runtime)
        self._tray_quit_action.triggered.connect(self._exit_from_tray)
        self._tray_menu.insertAction(self._tray_runtime_menu.menuAction(), self._tray_show_action)
        self._tray_menu.insertAction(self._tray_runtime_menu.menuAction(), self._tray_toggle_action)
        self._tray_menu.addSeparator()
        self._tray_menu.addAction(self._tray_quit_action)
        # aboutToShow must stay empty — Windows blocks paint until the slot returns.
        # Menu is kept hot via background emit_state + aboutToHide soft refresh.
        self._tray_menu.aboutToShow.connect(self._on_tray_about_to_show)
        self._tray_menu.aboutToHide.connect(self._on_tray_about_to_hide)
        self._refresh_tray_menu()
        # Native Windows tray ПКМ: setContextMenu is the reliable path.
        self.tray_icon.setContextMenu(self._tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.setToolTip("Zapret Hub")
        if not QSystemTrayIcon.isSystemTrayAvailable():
            try:
                self.context.logging.log("warning", "system tray is not available")
            except Exception:
                pass
        self.tray_icon.setVisible(True)
        self.tray_icon.show()
        # Some Windows sessions need a deferred show after the message pump starts.
        QTimer.singleShot(0, lambda: self.tray_icon.show() if getattr(self, "tray_icon", None) else None)
        QTimer.singleShot(400, lambda: self.tray_icon.show() if getattr(self, "tray_icon", None) else None)

    def _tray_runtime_is_on(self) -> bool:
        if self.bridge is None:
            return False
        return self.bridge._peek_runtime_status() in {"on", "starting"}

    def _on_tray_about_to_show(self) -> None:
        """No-op on purpose — keep the prebuilt QMenu hot; never I/O here."""
        return

    def _on_tray_about_to_hide(self) -> None:
        # Soft refresh after close so the next right-click stays current.
        QTimer.singleShot(0, self._refresh_tray_menu)

    def _tray_menu_is_open(self) -> bool:
        menu = getattr(self, "_tray_menu", None)
        try:
            return menu is not None and bool(menu.isVisible())
        except Exception:
            return False

    def _sync_tray_power_label(self) -> None:
        """Update Turn on/off text from in-memory flags (safe anytime, including emit_state)."""
        if not hasattr(self, "_tray_toggle_action"):
            return
        language = str(getattr(self, "_tray_cached_language", None) or "ru")
        runtime_on = self._tray_runtime_is_on()
        self._tray_cached_runtime_on = runtime_on
        self._apply_tray_action_labels(language, runtime_on)

    def _apply_tray_action_labels(self, language: str, runtime_on: bool) -> None:
        self._tray_show_action.setText("Открыть Zapret Hub" if language == "ru" else "Open Zapret Hub")
        self._tray_toggle_action.setText(
            ("Выключить" if runtime_on else "Включить")
            if language == "ru"
            else ("Turn off" if runtime_on else "Turn on")
        )
        self._tray_quit_action.setText("Выйти" if language == "ru" else "Exit")

    def _refresh_tray_menu(self) -> None:
        """Rebuild tray from settings + caches. Never uses bridge.build_state(). Never on ПКМ path."""
        if self.context is None or self.bridge is None:
            return
        if not hasattr(self, "_tray_menu"):
            return
        # Never clear()/rebuild while the native tray menu is visible.
        if self._tray_menu_is_open():
            self._sync_tray_power_label()
            return
        settings = self.context.settings.get()
        language = str(settings.language or "ru")
        runtime_id = str(settings.selected_runtime_mode or "zapret")
        runtime_on = self._tray_runtime_is_on()
        self._tray_cached_language = language
        self._tray_cached_runtime_on = runtime_on
        self._apply_tray_action_labels(language, runtime_on)

        mode_order = tuple(str(item) for item in (settings.runtime_mode_order or []))
        generals: list[dict[str, str]] = []
        if runtime_id == "zapret":
            generals = list(self.bridge._get_generals_payload() or [])
            selected = str(settings.selected_zapret_general or "")
            detail_sig: tuple[Any, ...] = (
                "zapret",
                selected,
                tuple((str(item.get("id", "")), str(item.get("name", ""))) for item in generals),
            )
        else:
            detail_sig = (runtime_id,)

        sig = (language, runtime_id, runtime_on, mode_order, detail_sig)
        if getattr(self, "_tray_menu_sig", None) == sig:
            return
        self._tray_menu_sig = sig
        if runtime_id == "zapret":
            self._rebuild_tray_runtime_menu(
                runtime_id, runtime_on, language, generals=generals
            )
        else:
            self._rebuild_tray_runtime_menu(
                runtime_id, runtime_on, language, generals=None
            )

    def _rebuild_tray_runtime_menu(
        self,
        runtime_id: str,
        runtime_on: bool,
        language: str,
        *,
        generals: list[dict[str, str]] | None = None,
    ) -> None:
        del runtime_on  # power is read live in _tray_select_runtime
        names = {
            "zapret": "Zapret",
            "zapret2": "Zapret 2",
            "none": "Без основного компонента" if language == "ru" else "No primary component",
        }
        self._tray_runtime_menu.setTitle("Сетевой компонент" if language == "ru" else "Network component")
        self._tray_runtime_menu.clear()
        group = QActionGroup(self._tray_runtime_menu)
        group.setExclusive(True)
        mode_order = list(getattr(self.context.settings.get(), "runtime_mode_order", None) or [])
        for item in mode_order:
            action = QAction(names.get(item, item), self._tray_runtime_menu)
            action.setCheckable(True)
            action.setChecked(item == runtime_id)
            action.triggered.connect(
                lambda _checked=False, selected=item: self._tray_select_runtime(selected)
            )
            group.addAction(action)
            self._tray_runtime_menu.addAction(action)
        self._tray_runtime_group = group

        self._tray_runtime_detail_menu.clear()
        detail_action = self._tray_runtime_detail_menu.menuAction()
        if runtime_id == "zapret":
            if generals is None:
                generals = list(self.bridge._get_generals_payload() or [])
            if not generals:
                detail_action.setVisible(False)
                return
            detail_action.setVisible(True)
            self._tray_runtime_detail_menu.setEnabled(True)
            self._tray_runtime_detail_menu.setTitle("Конфигурация" if language == "ru" else "Configuration")
            selected = str(self.context.settings.get().selected_zapret_general or "")
            detail_group = QActionGroup(self._tray_runtime_detail_menu)
            detail_group.setExclusive(True)
            for option in generals:
                general_id = str(option.get("id", ""))
                action = QAction(str(option.get("name", general_id)), self._tray_runtime_detail_menu)
                action.setCheckable(True)
                action.setChecked(general_id == selected)
                action.triggered.connect(lambda _checked=False, value=general_id: self._tray_select_general(value))
                detail_group.addAction(action)
                self._tray_runtime_detail_menu.addAction(action)
            self._tray_runtime_detail_group = detail_group
        else:
            # zapret2 / none — no useful submenu items; hide the empty stub.
            detail_action.setVisible(False)

    def _tray_select_runtime(self, runtime_id: str, was_powered: bool | None = None) -> None:
        # Same path as bridge runtime.select (gen-token + process switch).
        if was_powered is None:
            was_powered = self._tray_runtime_is_on()
        self.bridge._dispatch("runtime.select", {"id": runtime_id})
        if not was_powered:
            self.bridge.emit_state()

    def _tray_select_general(self, general_id: str) -> None:
        self.context.settings.update(selected_zapret_general=general_id)

        def _apply() -> None:
            try:
                self.bridge._reconfigure_runtimes(("zapret",), lambda: None)
            except Exception as error:
                try:
                    self.context.logging.log("error", "tray general select failed", error=str(error))
                except Exception:
                    pass
            finally:
                self.bridge.emit_state(force=True)

        threading.Thread(target=_apply, daemon=True, name="zapret-hub-tray-general").start()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        # Left / double-click restore the window. Right-click is owned by setContextMenu.
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.restore_from_external_launch()

    def _tray_toggle_runtime(self) -> None:
        # Last-known status only — never build_state() on the tray click path.
        enabled = not self._tray_runtime_is_on()
        self.bridge._dispatch("runtime.power", {"on": enabled})

    def _exit_from_tray(self, *, reason: str = "requested") -> None:
        if self._force_exit:
            os._exit(0)
        try:
            if self.context is not None:
                self.context.logging.log("warning", "Application exit requested", reason=reason)
        except Exception:
            pass
        self._force_exit = True
        self._pending_quit_after_stop = False
        self._cancel_onboarding_configuration()
        self._dismantle_ui_immediately()

        context = self.context

        def shutdown() -> None:
            try:
                bridge = getattr(self, "bridge", None)
                presence = getattr(bridge, "_discord_presence", None) if bridge is not None else None
                if presence is not None:
                    try:
                        presence.stop()
                    except Exception:
                        pass
                if context is None:
                    return
                if context.backend is not None:
                    try:
                        context.backend.request_shutdown_background()
                    except Exception:
                        pass
                    try:
                        process = getattr(context.backend, "_process", None)
                        if process is not None and process.is_alive():
                            process.terminate()
                            process.join(timeout=1.5)
                            if process.is_alive():
                                process.kill()
                    except Exception:
                        pass
                else:
                    context.processes.stop_all()
            except Exception:
                pass

        # Daemon: do not keep the process alive if stop hangs (e.g. diagnostics).
        threading.Thread(target=shutdown, daemon=True, name="zapret-hub-shutdown").start()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)
            # Hard deadline if Qt / WebEngine / backend refuse to leave.
            QTimer.singleShot(2500, lambda: os._exit(0))
        else:
            os._exit(0)

    def _dismantle_ui_immediately(self) -> None:
        """Hide window and tray icon right away — do not wait for backend stop."""
        try:
            if self._window_animation is not None:
                self._window_animation.stop()
                self._window_animation = None
        except Exception:
            pass
        try:
            timer = getattr(self, "_notification_timer", None)
            if timer is not None:
                timer.stop()
        except Exception:
            pass
        self.setWindowOpacity(0.0)
        self.hide()
        tray = getattr(self, "tray_icon", None)
        if tray is not None:
            try:
                tray.setContextMenu(None)
                tray.hide()
                tray.setVisible(False)
                tray.deleteLater()
            except Exception:
                pass
            self.tray_icon = None  # type: ignore[assignment]
        menu = getattr(self, "_tray_menu", None)
        if menu is not None:
            try:
                menu.hide()
                menu.deleteLater()
            except Exception:
                pass
            self._tray_menu = None  # type: ignore[assignment]

    @Slot()
    def _finish_exit_after_shutdown(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _runtime_power_status(self) -> str:
        if self.bridge is None or self.context is None:
            return "off"
        try:
            return self.bridge._peek_runtime_status()
        except Exception:
            return "off"

    def _should_minimize_to_tray(self) -> bool:
        # Keep the app in tray only while the power button is on or still starting.
        # Never tray-hide during onboarding / config selection (diagnostics looks "on").
        bridge = self.bridge
        if bridge is not None:
            if getattr(bridge, "show_onboarding", False):
                return False
            if getattr(bridge, "_onboarding_configuration_running", False):
                return False
        return self._runtime_power_status() in {"on", "starting"}

    def _hide_to_tray(self) -> None:
        self.hide()
        self.setWindowOpacity(1.0)
        tray = getattr(self, "tray_icon", None)
        if tray is None or self.context is None:
            return
        settings = self.context.settings.get()
        if settings.windows_notifications_enabled and settings.show_tray_hide_notification:
            tray.showMessage(
                "Zapret Hub",
                "Приложение скрыто в трей." if settings.language == "ru" else "The app was minimized to tray.",
                QSystemTrayIcon.MessageIcon.Information,
                2200,
            )

    def _flush_windows_notifications(self) -> None:
        if self.context is None:
            return
        tray = getattr(self, "tray_icon", None)
        if tray is None:
            return
        settings = self.context.settings.get()
        entries = self.context.notifications.list()
        new_entries = [item for item in entries if item.id not in self._tray_notification_ids]
        self._tray_notification_ids.update(item.id for item in entries)
        if not (settings.windows_notifications_enabled and settings.notifications_enabled):
            return
        for item in new_entries[-3:]:
            icon = (
                QSystemTrayIcon.MessageIcon.Critical if item.level == "error"
                else QSystemTrayIcon.MessageIcon.Warning if item.level == "warn"
                else QSystemTrayIcon.MessageIcon.Information
            )
            tray.showMessage(item.title or "Zapret Hub", item.message, icon, 3500)

    def closeEvent(self, event: Any) -> None:
        if self._force_exit:
            event.accept()
            super().closeEvent(event)
            return
        if self._should_minimize_to_tray():
            event.ignore()
            self._hide_to_tray()
            return
        event.ignore()
        self._exit_from_tray(reason="window-close")
