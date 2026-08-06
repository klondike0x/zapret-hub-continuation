from __future__ import annotations

import multiprocessing as mp
import os
import queue
import tempfile
import traceback
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from zapret_hub.domain import FileRecord
from zapret_hub.services.service_catalog import SERVICE_PRESETS, SERVICE_PRESET_IDS


def _snapshot(context) -> dict[str, Any]:
    settings = context.settings.get()
    return {
        "components": [asdict(item) for item in context.processes.list_components()],
        "states": [asdict(item) for item in context.processes.list_states()],
        "settings": {
            "selected_zapret_general": settings.selected_zapret_general,
            "favorite_zapret_generals": list(settings.favorite_zapret_generals or []),
            "enabled_mod_ids": list(settings.enabled_mod_ids or []),
            "selected_service_ids": list(settings.selected_service_ids or []),
            "zapret_ipset_mode": settings.zapret_ipset_mode,
            "zapret_game_filter_mode": settings.zapret_game_filter_mode,
            "zapret_gaming_set": getattr(settings, "zapret_gaming_set", "stun-wide-base"),
            "zapret_udp_exclude_ports": settings.zapret_udp_exclude_ports,
            "zapret_control_mode": getattr(settings, "zapret_control_mode", "manual"),
            "zapret2_control_mode": getattr(settings, "zapret2_control_mode", "manual"),
            "trusted_general": getattr(settings, "trusted_general", ""),
            "selected_runtime_mode": getattr(settings, "selected_runtime_mode", "zapret"),
            "autostart_windows": bool(settings.autostart_windows),
            "apply_update_on_next_launch": bool(getattr(settings, "apply_update_on_next_launch", False)),
        },
    }


def _mods_payload(context) -> dict[str, Any]:
    return {
        "index": context.mods.fetch_index(),
        "installed": list(context.mods.list_installed()),
    }


def _general_file_records(context) -> list[FileRecord]:
    records: list[FileRecord] = []
    seen: set[str] = set()
    for option in context.processes.list_zapret_generals():
        path = Path(str(option.get("path", "") or ""))
        if not path.exists() or not path.is_file():
            continue
        resolved = str(path.resolve()).lower()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            relative = str(path.relative_to(context.paths.install_root))
        except ValueError:
            relative = str(path)
        bundle = str(option.get("bundle", "") or "").strip()
        label = f"{bundle}/{path.name}" if bundle else relative
        records.append(FileRecord(path=str(path), relative_path=label, size=path.stat().st_size))
    return sorted(records, key=lambda item: item.relative_path.lower())


def _host_file_records(context) -> list[FileRecord]:
    path = context.files.ensure_local_hosts_file()
    try:
        relative = str(path.relative_to(context.paths.install_root))
    except ValueError:
        relative = str(path)
    return [FileRecord(path=str(path), relative_path=relative, size=path.stat().st_size)]


def _active_bypass_id(context) -> str:
    mode = str(getattr(context.settings.get(), "selected_runtime_mode", "zapret") or "zapret")
    return mode if mode in {"zapret", "zapret2"} else "zapret"


def _stop_zapret_for_reconfiguration(context) -> bool:
    """Stop the active bypass (zapret or zapret2) before list/settings rebuild."""
    component_id = _active_bypass_id(context)
    states = {item.component_id: item for item in context.processes.list_states()}
    state = states.get(component_id)
    status = str(getattr(state, "status", "") or "").strip().lower() if state else ""
    was_running = status == "running"
    if was_running:
        context.processes.stop_component(component_id)
        return True
    settings = context.settings.get()
    enabled = {str(item) for item in list(settings.enabled_component_ids or [])}
    selected_mode = str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret")
    # Recover after a failed/partial start so reconfigure can bring the bypass back.
    should_recover = status in {"error", "partial", "starting"} and component_id in enabled and selected_mode == component_id
    return should_recover


def _finish_zapret_reconfiguration(context, *, restart: bool) -> bool:
    """Rebuild classic lists/runtime; restart active bypass when requested."""
    component_id = _active_bypass_id(context)
    context.merge.rebuild()
    context.files._invalidate_collection_cache()
    context.files.rebuild_materialized_collections()
    if component_id == "zapret":
        context.processes.rebuild_zapret_runtime_snapshot()
    if restart:
        state = context.processes.start_component(component_id)
        return bool(getattr(state, "status", "") == "running")
    return False


def _restart_zapret_if_running(context) -> bool:
    was_running = _stop_zapret_for_reconfiguration(context)
    return _finish_zapret_reconfiguration(context, restart=was_running)



def _sync_bypass_enabled_for_mode(context, runtime_id: str) -> None:
    """Mutual-exclusion for Quick Access mode ↔ enabled_component_ids."""
    settings = context.settings.get()
    enabled = {str(item) for item in list(settings.enabled_component_ids or [])}
    autostart = {str(item) for item in list(settings.autostart_component_ids or [])}
    mode = str(runtime_id or "zapret")
    if mode == "zapret":
        enabled.add("zapret")
        enabled.discard("zapret2")
        autostart.discard("zapret2")
    elif mode == "zapret2":
        enabled.add("zapret2")
        enabled.discard("zapret")
        autostart.discard("zapret")
    elif mode == "none":
        enabled.discard("zapret")
        enabled.discard("zapret2")
        autostart.discard("zapret")
        autostart.discard("zapret2")
    context.settings.update(
        enabled_component_ids=sorted(enabled),
        autostart_component_ids=sorted(autostart),
        selected_runtime_mode=mode if mode in {"zapret", "zapret2", "none"} else "zapret",
    )


def _sync_aux_components_from_services(context) -> None:
    settings = context.settings.get()
    selected = {str(item) for item in list(settings.selected_service_ids or [])}
    enabled = {str(item) for item in list(settings.enabled_component_ids or [])}
    autostart = {str(item) for item in list(settings.autostart_component_ids or [])}
    if "telegram-desktop" in selected:
        enabled.add("tg-ws-proxy")
        autostart.add("tg-ws-proxy")
    else:
        enabled.discard("tg-ws-proxy")
        autostart.discard("tg-ws-proxy")
    if "ai" in selected:
        enabled.add("xbox-dns")
    else:
        enabled.discard("xbox-dns")
    changes: dict[str, Any] = {}
    if enabled != set(settings.enabled_component_ids or []) or autostart != set(settings.autostart_component_ids or []):
        changes.update(
            enabled_component_ids=sorted(enabled),
            autostart_component_ids=sorted(autostart),
        )
    if changes:
        context.settings.update(**changes)


def _runtime_running_states(context) -> tuple[dict[str, Any], bool, bool, bool]:
    states = {item.component_id: item for item in context.processes.list_states()}
    any_running = any(item.status == "running" for item in states.values())
    zapret_running = bool(states.get("zapret") and states["zapret"].status == "running")
    zapret2_running = bool(states.get("zapret2") and states["zapret2"].status == "running")
    return states, any_running, zapret_running, zapret2_running





def _prepare_general_autotest_runtime(context) -> dict[str, Any]:
    settings = context.settings.get()
    states, _any_running, zapret_running, zapret2_running = _runtime_running_states(context)
    running_ids = [
        component_id
        for component_id, state in states.items()
        if getattr(state, "status", "") == "running"
    ]
    restore = {
        "was_running": bool(running_ids),
        "selected_runtime_mode": str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret"),
        "zapret_running": bool(zapret_running),
        "zapret2_running": bool(zapret2_running),
        "running_component_ids": running_ids,
        "enabled_component_ids": list(settings.enabled_component_ids or []),
    }
    for component_id in running_ids:
        try:
            context.processes.stop_component(component_id)
        except Exception:
            pass
    return restore


def _restore_general_autotest_runtime(context, restore: dict[str, Any]) -> bool:
    if not bool(restore.get("was_running", False)):
        return False
    running_component_ids = {
        str(item).strip()
        for item in list(restore.get("running_component_ids", []) or [])
        if str(item).strip()
    }
    mode = str(restore.get("selected_runtime_mode", "") or "").strip()
    if not mode:
        mode = "zapret"
    if bool(restore.get("zapret2_running", False)):
        context.processes.start_component("zapret2")
        for component_id in sorted(running_component_ids - _runtime_excluded_component_ids()):
            context.processes.start_component(component_id)
        return True
    if bool(restore.get("zapret_running", False)):
        _finish_zapret_reconfiguration(context, restart=True)
        for component_id in sorted(running_component_ids - {"zapret", "zapret2"}):
            context.processes.start_component(component_id)
        return True
    if mode == "zapret":
        _finish_zapret_reconfiguration(context, restart=True)
        for component_id in sorted(running_component_ids - {"zapret", "zapret2"}):
            context.processes.start_component(component_id)
        return True
    if mode == "zapret2":
        context.processes.start_component("zapret2")
        for component_id in sorted(running_component_ids - _runtime_excluded_component_ids()):
            context.processes.start_component(component_id)
        return True
    return False


def _set_enabled_components(context, enabled: set[str]) -> None:
    context.settings.update(enabled_component_ids=sorted(enabled))


def _start_enabled_aux_components(context, *, exclude: set[str] | None = None) -> None:
    excluded = {str(item) for item in (exclude or set())}
    for component in context.processes.list_components():
        if not component.enabled or component.id in excluded:
            continue
        context.processes.start_component(component.id)


def _reset_stale_start_states(context, components, *, autostart_only: bool, exclude: set[str] | None = None) -> None:
    excluded = {str(item) for item in (exclude or set())}
    states = {item.component_id: item for item in context.processes.list_states()}
    for component in components:
        if component.id in excluded:
            continue
        if not component.enabled or (autostart_only and not component.autostart):
            continue
        state = states.get(component.id)
        if str(getattr(state, "status", "") or "").strip().lower() in {"error", "partial"}:
            try:
                context.processes.stop_component(component.id)
            except Exception:
                pass



def _runtime_excluded_component_ids() -> set[str]:
    return {"zapret", "zapret2"}



def _set_zapret_enabled_from_components(context, enabled_target: bool) -> dict[str, Any]:
    settings = context.settings.get()
    enabled = {str(item) for item in list(settings.enabled_component_ids or [])}
    _states, any_running, zapret_running, _zapret2_running = _runtime_running_states(context)

    if enabled_target:
        restore_xbox_dns = bool(getattr(settings, "xbox_dns_was_enabled_before_zapret2", False))
        enabled.add("zapret")
        enabled.discard("zapret2")
        if restore_xbox_dns:
            enabled.add("xbox-dns")
        _set_enabled_components(context, enabled)
        context.settings.update(
            selected_runtime_mode="zapret",
            zapret_was_enabled_before_zapret2=False,
            zapret_was_running_before_zapret2=False,
            xbox_dns_was_enabled_before_zapret2=False,
        )
        if zapret2_running:
            context.processes.stop_component("zapret2")
        if any_running:
            context.processes.start_component("zapret")
            _start_enabled_aux_components(context, exclude=_runtime_excluded_component_ids())
    else:
        enabled.discard("zapret")
        _set_enabled_components(context, enabled)
        if zapret_running:
            context.processes.stop_component("zapret")
    return _snapshot(context)


def _set_zapret2_enabled_from_components(context, enabled_target: bool) -> dict[str, Any]:
    settings = context.settings.get()
    enabled = {str(item) for item in list(settings.enabled_component_ids or [])}
    _states, any_running, zapret_running, zapret2_running = _runtime_running_states(context)

    if enabled_target:
        previous_zapret_enabled = "zapret" in enabled
        previous_xbox_dns_enabled = "xbox-dns" in enabled
        enabled.add("zapret2")
        enabled.discard("zapret")
        _set_enabled_components(context, enabled)
        context.settings.update(
            selected_runtime_mode="zapret2",
            zapret_was_enabled_before_zapret2=previous_zapret_enabled,
            zapret_was_running_before_zapret2=zapret_running,
            xbox_dns_was_enabled_before_zapret2=previous_xbox_dns_enabled,
        )
        if zapret_running:
            context.processes.stop_component("zapret")
        if any_running:
            context.processes.start_component("zapret2")
            _start_enabled_aux_components(context, exclude=_runtime_excluded_component_ids())
    else:
        restore_zapret = bool(getattr(settings, "zapret_was_enabled_before_zapret2", False))
        restore_xbox_dns = bool(getattr(settings, "xbox_dns_was_enabled_before_zapret2", False))
        enabled.discard("zapret2")
        if restore_zapret:
            enabled.add("zapret")
            if restore_xbox_dns:
                enabled.add("xbox-dns")
        else:
            enabled.discard("zapret")
            if restore_xbox_dns:
                enabled.add("xbox-dns")
        _set_enabled_components(context, enabled)
        context.settings.update(
            selected_runtime_mode="zapret",
            zapret_was_enabled_before_zapret2=False,
            zapret_was_running_before_zapret2=False,
            xbox_dns_was_enabled_before_zapret2=False,
        )
        if zapret2_running:
            context.processes.stop_component("zapret2")
        if any_running and restore_zapret:
            context.processes.start_component("zapret")
            _start_enabled_aux_components(context, exclude=_runtime_excluded_component_ids())
        elif any_running and restore_xbox_dns:
            context.processes.start_component("xbox-dns")
    return _snapshot(context)


def _fortnite_zapret_settings(context) -> dict[str, str]:
    return {
        "zapret_ipset_mode": "any",
        "zapret_game_filter_mode": "tcpudp",
    }


def _gaming_zapret_settings(context) -> dict[str, str]:
    return {"zapret_game_filter_mode": "tcpudp", "zapret_ipset_mode": "loaded"}


def _ubisoft_zapret_settings(context) -> dict[str, str]:
    return {}



def _worker_main(task_queue, result_queue) -> None:
    from zapret_hub.bootstrap import bootstrap_application

    def _emit_progress(task_id: str, action: str, payload: dict[str, Any]) -> None:
        result_queue.put({"id": task_id, "action": action, "ok": True, "kind": "progress", "payload": payload})

    context = bootstrap_application()
    while True:
        task = task_queue.get()
        if not isinstance(task, dict):
            continue
        action = str(task.get("action", ""))
        if action == "shutdown":
            try:
                context.processes.stop_all()
            except Exception:
                pass
            result_queue.put({"id": task.get("id", ""), "action": action, "ok": True, "payload": {}})
            break
        task_id = str(task.get("id", ""))
        payload = task.get("payload", {}) or {}
        try:
            result = _run_action(context, action, payload, lambda progress: _emit_progress(task_id, action, progress))
            result_queue.put({"id": task_id, "action": action, "ok": True, "payload": result or {}})
        except Exception as error:
            try:
                context.logging.log(
                    "error",
                    "Backend task failed",
                    action=action,
                    error=str(error),
                    traceback=traceback.format_exc(),
                )
            except Exception:
                pass
            result_queue.put(
                {
                    "id": task_id,
                    "action": action,
                    "ok": False,
                    "error": str(error),
                    "source": _action_error_source(action),
                }
            )


def _action_error_source(action: str) -> str:
    normalized = (action or "").strip().lower()
    if "xbox_dns" in normalized or "xbox-dns" in normalized or "dns" in normalized:
        return "xbox-dns"
    if "tg_ws_proxy" in normalized or "tg-ws-proxy" in normalized or "telegram" in normalized:
        return "tg-ws-proxy"
    if "zapret2" in normalized:
        return "zapret2"
    if "zapret" in normalized or "general" in normalized or "merge" in normalized:
        return "zapret"
    if "mod" in normalized:
        return "mods"
    if "settings" in normalized:
        return "settings"
    if "file" in normalized:
        return "files"
    return "backend"


def _run_action(context, action: str, payload: dict[str, Any], emit_progress: callable | None = None) -> dict[str, Any]:
    payload = {key: value for key, value in payload.items() if not str(key).startswith("_")}
    context.settings.reload()

    if action == "toggle_master_runtime":
        _sync_aux_components_from_services(context)
        components = context.processes.list_components()
        states = {item.component_id: item for item in context.processes.list_states()}
        zapret2_enabled = any(component.id == "zapret2" and component.enabled for component in components)
        active_ids = [c.id for c in components if c.enabled]
        running_ids = {
            component_id
            for component_id, state in states.items()
            if state.status == "running"
        }
        # Xbox DNS may remain active on its own. It must not turn the master
        # button into a disconnect action when no actual runtime is running yet.
        runtime_running_ids = running_ids & {"zapret", "zapret2"}
        if runtime_running_ids:
            for cid in list(running_ids):
                context.processes.stop_component(cid)
            mode = "disconnect"
        else:
            if zapret2_enabled:
                context.processes.stop_component("zapret")
                context.processes.start_component("zapret2")
                _start_enabled_aux_components(context, exclude=_runtime_excluded_component_ids())
            else:
                for cid in active_ids:
                    if cid != "zapret2":
                        context.processes.start_component(cid)
            mode = "connect"
        result = {"mode": mode}
        result.update(_snapshot(context))
        return result

    if action == "load_startup_snapshot":
        _sync_aux_components_from_services(context)
        current = context.settings.get()
        if not str(current.selected_zapret_general or "").strip():
            options = context.processes.list_zapret_generals()
            if options:
                context.settings.update(selected_zapret_general=str(options[0]["id"]))
        result = _snapshot(context)
        result.update(_mods_payload(context))
        result["general_options"] = list(context.processes.list_zapret_generals())
        return result

    if action == "load_components_payload":
        _sync_aux_components_from_services(context)
        current = context.settings.get()
        options = context.processes.list_zapret_generals()
        if not str(current.selected_zapret_general or "").strip() and options:
            context.settings.update(selected_zapret_general=str(options[0]["id"]))
        result = _snapshot(context)
        result["general_options"] = options
        return result

    if action == "start_enabled_components":
        _sync_aux_components_from_services(context)
        autostart_only = bool(payload.get("autostart_only", False)) if isinstance(payload, dict) else False
        components = context.processes.list_components()
        zapret2_enabled = any(component.id == "zapret2" and component.enabled for component in components)
        if zapret2_enabled:
            context.processes.stop_component("zapret")
            _reset_stale_start_states(context, components, autostart_only=autostart_only, exclude=_runtime_excluded_component_ids())
            for component in components:
                if component.id in _runtime_excluded_component_ids():
                    continue
                if component.enabled and (not autostart_only or component.autostart):
                    context.processes.start_component(component.id)
            context.processes.start_component("zapret2")
        elif autostart_only:
            _reset_stale_start_states(context, components, autostart_only=True, exclude=_runtime_excluded_component_ids())
            for component in components:
                if component.id == "zapret2":
                    continue
                if component.enabled and component.autostart:
                    context.processes.start_component(component.id)
        else:
            _reset_stale_start_states(context, components, autostart_only=False, exclude=_runtime_excluded_component_ids())
            for component in components:
                if component.id == "zapret2":
                    continue
                if component.enabled:
                    context.processes.start_component(component.id)
        result = _snapshot(context)
        return result

    if action == "start_component":
        component_id = str(payload.get("component_id", "")).strip()
        if component_id:
            if component_id == "zapret":
                result = _set_zapret_enabled_from_components(context, True)
                return result
            if component_id == "zapret2":
                result = _set_zapret2_enabled_from_components(context, True)
                return result
            context.processes.start_component(component_id)
        result = _snapshot(context)
        return result

    if action == "stop_component":
        component_id = str(payload.get("component_id", "")).strip()
        if component_id:
            if component_id == "zapret":
                return _set_zapret_enabled_from_components(context, False)
            if component_id == "zapret2":
                return _set_zapret2_enabled_from_components(context, False)
            context.processes.stop_component(component_id)
        return _snapshot(context)

    if action == "select_runtime_mode":
        mode = str(payload.get("mode", "") or "").strip()
        if mode not in {"zapret", "zapret2"}:
            mode = "zapret"
        if mode == "zapret2":
            return _set_zapret2_enabled_from_components(context, True)
        return _set_zapret_enabled_from_components(context, True)

    if action == "refresh_xbox_dns":
        result = {"xbox_dns": context.processes.refresh_xbox_dns()}
        result.update(_snapshot(context))
        return result

    if action == "apply_deferred_changes":
        service_ids = payload.get("service_ids", None)
        settings_payload = payload.get("settings", {})
        mods_payload = payload.get("mods", {})
        result: dict[str, Any] = {}
        if isinstance(service_ids, list):
            service_result = _run_action(
                context,
                "set_selected_services",
                {
                    "service_ids": service_ids,
                    "client_revision": int(payload.get("service_client_revision", 0) or 0),
                },
                emit_progress,
            )
            result.update(service_result or {})
        if isinstance(settings_payload, dict) and settings_payload:
            settings_result = _run_action(
                context,
                "apply_settings",
                {
                    **settings_payload,
                    "client_revision": int(payload.get("client_revision", 0) or 0),
                },
                emit_progress,
            )
            for key in ("zapret_restarted", "tg_proxy_restarted", "theme_changed", "language_changed", "autostart_changed"):
                if bool(settings_result.get(key)):
                    result[key] = settings_result.get(key)
        if isinstance(mods_payload, dict) and mods_payload:
            mods_result = _run_action(
                context,
                "set_mod_enabled_states",
                {"mods": mods_payload},
                emit_progress,
            )
            if bool(mods_result.get("zapret_restarted")):
                result["zapret_restarted"] = True
            result.update({key: value for key, value in (mods_result or {}).items() if key in {"mods_changed"}})
        result["client_revision"] = int(payload.get("client_revision", 0) or 0)
        result["service_client_revision"] = int(payload.get("service_client_revision", 0) or 0)
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        return result

    if action == "prepare_general_autotest_runtime":
        restore = _prepare_general_autotest_runtime(context)
        result = {"restore_runtime": restore}
        result.update(_snapshot(context))
        return result

    if action == "restore_general_autotest_runtime":
        restore = payload.get("restore_runtime", {})
        restored = _restore_general_autotest_runtime(context, restore if isinstance(restore, dict) else {})
        result = {"runtime_restored": restored}
        result.update(_snapshot(context))
        return result

    if action == "apply_settings":
        before = context.settings.get()
        try:
            client_revision = int(payload.get("client_revision", 0) or 0)
        except (TypeError, ValueError):
            client_revision = 0
        effective_payload = {key: value for key, value in payload.items() if key != "client_revision"}
        zapret_before = (
            before.zapret_ipset_mode,
            before.zapret_game_filter_mode,
            getattr(before, "zapret_gaming_set", "stun-wide-base"),
            before.zapret_udp_exclude_ports,
            before.selected_zapret_general,
        )
        tg_before = (
            before.tg_proxy_host,
            int(before.tg_proxy_port),
            before.tg_proxy_secret,
            before.tg_proxy_dc_ip,
            bool(before.tg_proxy_cfproxy_enabled),
            bool(before.tg_proxy_cfproxy_priority),
            before.tg_proxy_cfproxy_domain,
            before.tg_proxy_fake_tls_domain,
            int(before.tg_proxy_buf_kb),
            int(before.tg_proxy_pool_size),
        )
        theme_before = before.theme
        language_before = before.language
        autostart_before = bool(before.autostart_windows)
        requested_zapret = (
            str(effective_payload.get("zapret_ipset_mode", before.zapret_ipset_mode)),
            str(effective_payload.get("zapret_game_filter_mode", before.zapret_game_filter_mode)),
            str(effective_payload.get("zapret_gaming_set", getattr(before, "zapret_gaming_set", "stun-wide-base"))),
            str(effective_payload.get("zapret_udp_exclude_ports", before.zapret_udp_exclude_ports)),
            str(effective_payload.get("selected_zapret_general", before.selected_zapret_general)),
        )
        zapret_changed = zapret_before != requested_zapret
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if zapret_changed else False
        context.settings.update(**effective_payload)
        current = context.settings.get()
        zapret_after = (
            current.zapret_ipset_mode,
            current.zapret_game_filter_mode,
            getattr(current, "zapret_gaming_set", "stun-wide-base"),
            current.zapret_udp_exclude_ports,
            current.selected_zapret_general,
        )
        tg_after = (
            str(effective_payload.get("tg_proxy_host", current.tg_proxy_host)),
            int(effective_payload.get("tg_proxy_port", current.tg_proxy_port)),
            str(effective_payload.get("tg_proxy_secret", current.tg_proxy_secret)),
            str(effective_payload.get("tg_proxy_dc_ip", current.tg_proxy_dc_ip)),
            bool(effective_payload.get("tg_proxy_cfproxy_enabled", current.tg_proxy_cfproxy_enabled)),
            bool(effective_payload.get("tg_proxy_cfproxy_priority", current.tg_proxy_cfproxy_priority)),
            str(effective_payload.get("tg_proxy_cfproxy_domain", current.tg_proxy_cfproxy_domain)),
            str(effective_payload.get("tg_proxy_fake_tls_domain", current.tg_proxy_fake_tls_domain)),
            int(effective_payload.get("tg_proxy_buf_kb", current.tg_proxy_buf_kb)),
            int(effective_payload.get("tg_proxy_pool_size", current.tg_proxy_pool_size)),
        )
        states = {item.component_id: item for item in context.processes.list_states()}
        tg_proxy_restarted = False
        if tg_before != tg_after and states.get("tg-ws-proxy") and states["tg-ws-proxy"].status == "running":
            context.processes.stop_component("tg-ws-proxy")
            context.processes.start_component("tg-ws-proxy")
            tg_proxy_restarted = True
        zapret_restarted = False
        # Only rebuild/restart when Zapret knobs actually changed (same 5-tuple).
        if zapret_changed and zapret_before != zapret_after:
            zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {
            "theme_changed": theme_before != context.settings.get().theme,
            "language_changed": language_before != context.settings.get().language,
            "autostart_changed": autostart_before != bool(context.settings.get().autostart_windows),
            "client_revision": client_revision,
            "tg_proxy_restarted": tg_proxy_restarted,
            "zapret_restarted": zapret_restarted,
        }
        result.update(_snapshot(context))
        return result

    if action == "select_general":
        selected = str(payload.get("selected", "")).strip()
        if not selected:
            return {}
        zapret_was_running = _stop_zapret_for_reconfiguration(context)
        settings = context.settings.get()
        settings.selected_zapret_general = selected
        context.settings.save()
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {"selected": selected, "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        return result

    if action == "set_selected_services":
        raw_ids = payload.get("service_ids", []) or []
        try:
            client_revision = int(payload.get("client_revision", 0) or 0)
        except (TypeError, ValueError):
            client_revision = 0
        requested = {str(item).strip() for item in raw_ids if str(item).strip() in SERVICE_PRESET_IDS}
        ordered = [preset.id for preset in SERVICE_PRESETS if preset.id in requested]
        settings = context.settings.get()
        before_services = set(settings.selected_service_ids or [])
        before_zapret_services = before_services - {"ai"}
        requested_zapret_services = requested - {"ai"}
        enabled_components = set(settings.enabled_component_ids or [])
        autostart_components = set(settings.autostart_component_ids or [])
        zapret2_enabled = "zapret2" in enabled_components
        restore_zapret_after_zapret2 = bool(getattr(settings, "zapret_was_enabled_before_zapret2", False))
        has_zapret_services = bool(requested_zapret_services)
        if has_zapret_services and not zapret2_enabled:
            enabled_components.add("zapret")
        else:
            enabled_components.discard("zapret")
            autostart_components.discard("zapret")
        if "ai" in requested:
            enabled_components.add("xbox-dns")
        else:
            enabled_components.discard("xbox-dns")
            autostart_components.discard("xbox-dns")
        if zapret2_enabled:
            restore_zapret_after_zapret2 = has_zapret_services
            enabled_components.discard("zapret")
        if "ai" in before_services and "ai" not in requested:
            states = {item.component_id: item for item in context.processes.list_states()}
            if states.get("xbox-dns") and states["xbox-dns"].status == "running":
                context.processes.stop_component("xbox-dns")
        elif "ai" in requested and "ai" not in before_services:
            states = {item.component_id: item for item in context.processes.list_states()}
            if any(item.status == "running" for item in states.values()):
                try:
                    context.processes.start_component("xbox-dns")
                except Exception:
                    pass
        if not has_zapret_services:
            states = {item.component_id: item for item in context.processes.list_states()}
            if states.get("zapret") and states["zapret"].status == "running":
                context.processes.stop_component("zapret")
        zapret_services_changed = before_zapret_services != requested_zapret_services
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if zapret_services_changed else False
        settings_changes = {
            "selected_service_ids": ordered,
            "enabled_component_ids": sorted(enabled_components),
            "autostart_component_ids": sorted(autostart_components),
        }
        if zapret2_enabled:
            settings_changes["zapret_was_enabled_before_zapret2"] = restore_zapret_after_zapret2
        if "gaming" in requested:
            settings_changes.update(_gaming_zapret_settings(context))
        if "ubisoft" in requested:
            settings_changes.update(_ubisoft_zapret_settings(context))
        if "fortnite" in requested:
            settings_changes.update(_fortnite_zapret_settings(context))
        context.settings.update(**settings_changes)
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running) if zapret_services_changed else False
        result = {"selected_service_ids": ordered, "client_revision": client_revision, "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        result["general_options"] = list(context.processes.list_zapret_generals())
        return result

    if action == "toggle_component_enabled":
        component_id = str(payload.get("component_id", "")).strip()
        if component_id:
            if component_id == "zapret":
                result = _set_zapret_enabled_from_components(
                    context,
                    "zapret" not in {str(item) for item in list(context.settings.get().enabled_component_ids or [])},
                )
                result["component"] = next(
                    (asdict(item) for item in context.processes.list_components() if item.id == "zapret"),
                    {},
                )
                return result
            if component_id == "zapret2":
                result = _set_zapret2_enabled_from_components(
                    context,
                    "zapret2" not in {str(item) for item in list(context.settings.get().enabled_component_ids or [])},
                )
                result["component"] = next(
                    (asdict(item) for item in context.processes.list_components() if item.id == "zapret2"),
                    {},
                )
                return result
            component = context.processes.toggle_component_enabled(component_id)
            if component_id == "xbox-dns":
                settings = context.settings.get()
                selected = {str(item) for item in list(settings.selected_service_ids or [])}
                autostart = {str(item) for item in list(settings.autostart_component_ids or [])}
                if component.enabled:
                    selected.add("ai")
                else:
                    selected.discard("ai")
                    autostart.discard("xbox-dns")
                    states = {item.component_id: item for item in context.processes.list_states()}
                    if states.get("xbox-dns") and states["xbox-dns"].status == "running":
                        context.processes.stop_component("xbox-dns")
                ordered = [preset.id for preset in SERVICE_PRESETS if preset.id in selected]
                context.settings.update(
                    selected_service_ids=ordered,
                    autostart_component_ids=sorted(autostart),
                )
            result = {"component": asdict(component)}
            result.update(_snapshot(context))
            return result
        return {}

    if action == "toggle_component_autostart":
        component_id = str(payload.get("component_id", "")).strip()
        if component_id:
            component = context.processes.toggle_component_autostart(component_id)
            result = {"component": asdict(component)}
            result.update(_snapshot(context))
            return result
        return {}

    if action == "toggle_mod":
        mod_id = str(payload.get("mod_id", "")).strip()
        if not mod_id:
            return {}
        zapret_was_running = _stop_zapret_for_reconfiguration(context)
        installed = {item.id: item for item in context.mods.list_installed()}
        if mod_id not in installed:
            context.mods.install(mod_id)
            installed = {item.id: item for item in context.mods.list_installed()}
        if mod_id in installed:
            context.mods.set_enabled(mod_id, not installed[mod_id].enabled)
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {"mod_id": mod_id, "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        return result

    if action == "set_mod_enabled_states":
        raw_mods = payload.get("mods", {})
        if not isinstance(raw_mods, dict):
            raw_mods = {}
        desired = {str(key).strip(): bool(value) for key, value in raw_mods.items() if str(key).strip()}
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if desired else False
        changed = False
        installed = {item.id: item for item in context.mods.list_installed()}
        for mod_id, enabled in desired.items():
            if mod_id not in installed and enabled:
                context.mods.install(mod_id)
                installed = {item.id: item for item in context.mods.list_installed()}
            entry = installed.get(mod_id)
            if entry is None:
                continue
            if bool(entry.enabled) != enabled:
                context.mods.set_enabled(mod_id, enabled)
                changed = True
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running) if changed else False
        result = {"mods_changed": changed, "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        return result

    if action == "install_mod":
        mod_id = str(payload.get("mod_id", "")).strip()
        if mod_id:
            context.mods.install(mod_id)
        result = {"mod_id": mod_id}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        return result

    if action == "remove_mod":
        mod_id = str(payload.get("mod_id", "")).strip()
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if mod_id else False
        zapret_restarted = False
        if mod_id:
            context.mods.remove(mod_id)
            zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {"mod_id": mod_id, "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        return result

    if action == "create_mod":
        name = str(payload.get("name", "")).strip()
        description = str(payload.get("description", "") or "")
        author = str(payload.get("author", "") or "")
        entry = context.mods.create_empty(name=name or "Custom mod", description=description, author=author)
        result = {"mod_id": entry.id}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        return result

    if action == "update_mod_metadata":
        mod_id = str(payload.get("mod_id", "")).strip()
        context.mods.update_metadata(
            mod_id,
            name=str(payload.get("name", "") or ""),
            description=str(payload.get("description", "") or ""),
            author=str(payload.get("author", "") or ""),
            version=str(payload.get("version", "") or ""),
        )
        result = {"mod_id": mod_id, "files": context.mods.list_files(mod_id)}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        return result

    if action == "load_mod_editor":
        mod_id = str(payload.get("mod_id", "")).strip()
        installed = {item.id: item for item in context.mods.list_installed()}
        entry = installed[mod_id]
        return {"mod": asdict(entry), "files": context.mods.list_files(mod_id)}

    if action == "read_mod_file":
        mod_id = str(payload.get("mod_id", "")).strip()
        path = str(payload.get("path", "") or "")
        return {"mod_id": mod_id, "path": path, "content": context.mods.read_file(mod_id, path)}

    if action == "write_mod_file":
        mod_id = str(payload.get("mod_id", "")).strip()
        path = str(payload.get("path", "") or "")
        content = str(payload.get("content", "") or "")
        zapret_was_running = _stop_zapret_for_reconfiguration(context)
        context.mods.write_file(mod_id, path, content)
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {"mod_id": mod_id, "path": path, "files": context.mods.list_files(mod_id), "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        result["general_options"] = list(context.processes.list_zapret_generals())
        return result

    if action == "delete_mod_file":
        mod_id = str(payload.get("mod_id", "")).strip()
        path = str(payload.get("path", "") or "")
        zapret_was_running = _stop_zapret_for_reconfiguration(context)
        context.mods.delete_file(mod_id, path)
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {"mod_id": mod_id, "files": context.mods.list_files(mod_id), "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        result["general_options"] = list(context.processes.list_zapret_generals())
        return result

    if action == "import_mod_from_github":
        repo_url = str(payload.get("repo_url", "")).strip()
        previous_selected_general = str(payload.get("previous_selected_general", "")).strip()
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if repo_url else False
        zapret_restarted = False
        if repo_url:
            context.mods.import_from_github(repo_url)
            if previous_selected_general:
                context.settings.update(selected_zapret_general=previous_selected_general)
            zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {"repo_url": repo_url, "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        result["general_options"] = list(context.processes.list_zapret_generals())
        return result

    if action == "import_mod_from_paths":
        raw_paths = payload.get("paths", []) or []
        paths = [str(item).strip() for item in raw_paths if str(item).strip()]
        previous_selected_general = str(payload.get("previous_selected_general", "")).strip()
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if paths else False
        zapret_restarted = False
        if paths:
            context.mods.import_from_paths(paths)
            if previous_selected_general:
                context.settings.update(selected_zapret_general=previous_selected_general)
            zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {"paths": paths, "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        result["general_options"] = list(context.processes.list_zapret_generals())
        return result

    if action == "import_mod_from_path":
        path = str(payload.get("path", "")).strip()
        previous_selected_general = str(payload.get("previous_selected_general", "")).strip()
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if path else False
        zapret_restarted = False
        if path:
            context.mods.import_from_path(path)
            if previous_selected_general:
                context.settings.update(selected_zapret_general=previous_selected_general)
            zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = {"path": path, "zapret_restarted": zapret_restarted}
        result.update(_snapshot(context))
        result.update(_mods_payload(context))
        result["general_options"] = list(context.processes.list_zapret_generals())
        return result

    if action == "move_mod":
        mod_id = str(payload.get("mod_id", "")).strip()
        direction = int(payload.get("direction", 0) or 0)
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if mod_id and direction else False
        zapret_restarted = False
        if mod_id and direction:
            context.mods.move(mod_id, direction)
            zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = _snapshot(context)
        result["zapret_restarted"] = zapret_restarted
        result.update(_mods_payload(context))
        return result

    if action == "set_mod_emoji":
        mod_id = str(payload.get("mod_id", "")).strip()
        emoji = str(payload.get("emoji", "")).strip()
        if mod_id and emoji:
            context.mods.set_emoji(mod_id, emoji)
        result = _snapshot(context)
        result.update(_mods_payload(context))
        return result

    if action == "restart_zapret_if_running":
        zapret_restarted = _restart_zapret_if_running(context)
        result = _snapshot(context)
        result["zapret_restarted"] = zapret_restarted
        return result

    if action == "add_collection_values":
        collection_id = str(payload.get("collection_id", "")).strip()
        raw = str(payload.get("raw", "") or "")
        zapret_was_running = _stop_zapret_for_reconfiguration(context)
        values = context.files.add_collection_values(collection_id, raw)
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = _snapshot(context)
        result["zapret_restarted"] = zapret_restarted
        result["files_payload"] = {
            "mode_index": 1,
            "collection_id": collection_id,
            "collection_values": list(values),
        }
        return result

    if action == "remove_collection_value":
        collection_id = str(payload.get("collection_id", "")).strip()
        value = str(payload.get("value", "") or "")
        zapret_was_running = _stop_zapret_for_reconfiguration(context)
        values = context.files.remove_collection_value(collection_id, value)
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = _snapshot(context)
        result["zapret_restarted"] = zapret_restarted
        result["files_payload"] = {
            "mode_index": 1,
            "collection_id": collection_id,
            "collection_values": list(values),
        }
        return result

    if action == "reset_user_overrides":
        collection_id = str(payload.get("collection_id", "")).strip()
        zapret_was_running = _stop_zapret_for_reconfiguration(context)
        context.files.reset_user_overrides()
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        values = context.files.read_collection(collection_id) if collection_id else []
        result = _snapshot(context)
        result["zapret_restarted"] = zapret_restarted
        result["files_payload"] = {
            "mode_index": 1,
            "collection_id": collection_id,
            "collection_values": list(values),
        }
        return result

    if action == "load_files_payload":
        mode_index = int(payload.get("mode_index", 0) or 0)
        collection_id = str(payload.get("collection_id", "")).strip()
        file_filter = str(payload.get("file_filter", "all") or "all")
        records = None
        if mode_index == 2:
            if file_filter == "generals":
                records = _general_file_records(context)
            elif file_filter == "hosts":
                records = _host_file_records(context)
            else:
                records = context.files.list_files()
        return {
            "files_payload": {
                "mode_index": mode_index,
                "collection_id": collection_id,
                "file_filter": file_filter,
                "records": records,
                "collection_values": context.files.read_collection(collection_id) if mode_index == 1 else None,
            }
        }

    if action == "write_file_text":
        full_path = str(payload.get("path", "")).strip()
        content = str(payload.get("content", "") or "")
        zapret_was_running = _stop_zapret_for_reconfiguration(context) if full_path else False
        zapret_restarted = False
        if full_path:
            context.files.write_text(full_path, content)
            zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = _snapshot(context)
        result["zapret_restarted"] = zapret_restarted
        result["path"] = full_path
        return result

    if action == "rebuild_merge_runtime":
        zapret_was_running = _stop_zapret_for_reconfiguration(context)
        zapret_restarted = _finish_zapret_reconfiguration(context, restart=zapret_was_running)
        result = _snapshot(context)
        result["zapret_restarted"] = zapret_restarted
        result.update(_mods_payload(context))
        return result

    if action == "set_favorite_generals":
        favorites = [str(item).strip() for item in (payload.get("favorites", []) or []) if str(item).strip()]
        current = context.settings.get()
        current.favorite_zapret_generals = favorites
        context.settings.save()
        return _snapshot(context)

    if action == "set_general_autotest_done":
        done = bool(payload.get("done", True))
        current = context.settings.get()
        current.general_autotest_done = done
        context.settings.save()
        return _snapshot(context)

    if action == "run_general_diagnostics":
        cancel_path = str(payload.get("cancel_path", "") or "")
        results = context.processes.run_general_diagnostics(
            progress_callback=(
                lambda current, total, name: emit_progress(
                    {
                        "current": current,
                        "total": total,
                        "name": name,
                    }
                )
                if emit_progress is not None
                else None
            ),
            stop_callback=(lambda: bool(cancel_path) and os.path.exists(cancel_path)),
        )
        return {"results": results}

    if action == "run_general_diagnostic_single":
        general_id = str(payload.get("general_id", "")).strip()
        cancel_path = str(payload.get("cancel_path", "") or "")
        ipset_mode = str(payload.get("ipset_mode", "loaded") or "loaded").strip()
        game_mode = str(payload.get("game_mode", "tcpudp") or "tcpudp").strip()
        result = context.processes.run_single_general_diagnostic(
            general_id,
            ipset_mode=ipset_mode,
            game_mode=game_mode,
            progress_callback=(
                lambda current, total, name: emit_progress(
                    {"current": current, "total": total, "name": name}
                )
                if emit_progress is not None
                else None
            ),
            stop_callback=(lambda: bool(cancel_path) and os.path.exists(cancel_path)),
        )
        return result

    if action == "run_settings_diagnostics":
        cancel_path = str(payload.get("cancel_path", "") or "")
        result = context.processes.run_settings_diagnostics(
            progress_callback=(
                lambda current, total, name: emit_progress(
                    {"current": current, "total": total, "name": name}
                )
                if emit_progress is not None
                else None
            ),
            stop_callback=(lambda: bool(cancel_path) and os.path.exists(cancel_path)),
        )
        return result

    if action == "update_zapret_runtime":
        result = context.processes.update_zapret_runtime()
        result.update(_snapshot(context))
        return result

    if action == "update_zapret2_runtime":
        result = context.processes.update_zapret2_runtime()
        result.update(_snapshot(context))
        return result

    return {}


class BackendWorkerClient(QObject):
    task_finished = Signal(dict)
    task_failed = Signal(dict)
    task_progress = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        ctx = mp.get_context("spawn")
        self._task_queue = ctx.Queue()
        self._result_queue = ctx.Queue()
        self._process = ctx.Process(target=_worker_main, args=(self._task_queue, self._result_queue), daemon=True)
        self._process.start()
        self._cancel_paths: dict[str, str] = {}
        self._pending_tasks: set[str] = set()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(80)
        self._poll_timer.timeout.connect(self._poll_results)

    @property
    def process_pid(self) -> int | None:
        try:
            pid = int(getattr(self._process, "pid", 0) or 0)
            return pid or None
        except Exception:
            return None

    def submit(self, action: str, payload: dict[str, Any] | None = None) -> str:
        task_id = uuid.uuid4().hex
        task_payload = dict(payload or {})
        if action in {"run_general_diagnostics", "run_general_diagnostic_single", "run_settings_diagnostics"}:
            cancel_path = os.path.join(tempfile.gettempdir(), f"zapret_hub_cancel_{task_id}.flag")
            try:
                if os.path.exists(cancel_path):
                    os.remove(cancel_path)
            except OSError:
                pass
            self._cancel_paths[task_id] = cancel_path
            task_payload["cancel_path"] = cancel_path
        self._pending_tasks.add(task_id)
        if not self._poll_timer.isActive():
            self._poll_timer.start()
        self._task_queue.put({"id": task_id, "action": action, "payload": task_payload})
        return task_id

    def cancel(self, task_id: str) -> None:
        cancel_path = self._cancel_paths.get(task_id)
        if not cancel_path:
            return
        try:
            with open(cancel_path, "w", encoding="utf-8") as handle:
                handle.write("cancelled")
        except OSError:
            pass

    def _poll_results(self) -> None:
        while True:
            try:
                message = self._result_queue.get_nowait()
            except queue.Empty:
                break
            if str(message.get("kind", "")) == "progress":
                self.task_progress.emit(message)
                continue
            task_id = str(message.get("id", ""))
            if task_id:
                self._pending_tasks.discard(task_id)
            cancel_path = self._cancel_paths.pop(task_id, None)
            if cancel_path:
                try:
                    if os.path.exists(cancel_path):
                        os.remove(cancel_path)
                except OSError:
                    pass
            if bool(message.get("ok")):
                self.task_finished.emit(message)
            else:
                self.task_failed.emit(message)
        if not self._pending_tasks and self._poll_timer.isActive():
            self._poll_timer.stop()

    def stop(self) -> None:
        try:
            self._task_queue.put({"id": uuid.uuid4().hex, "action": "shutdown", "payload": {}})
        except Exception:
            pass
        self._poll_timer.stop()
        if self._process.is_alive():
            self._process.join(timeout=3)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2)

    def request_shutdown_background(self) -> None:
        try:
            self._task_queue.put({"id": uuid.uuid4().hex, "action": "shutdown", "payload": {}})
        except Exception:
            pass
        self._poll_timer.stop()
