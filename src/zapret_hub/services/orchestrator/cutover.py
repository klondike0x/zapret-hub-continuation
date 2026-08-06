from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from zapret_hub.services.orchestrator.learner import HostlistLearner
from zapret_hub.services.orchestrator.signals import ProbeResult, SignalCollector, probe_required_ok
from zapret_hub.services.orchestrator.tuner import TunerStep
from zapret_hub.services.service_catalog import SERVICE_PRESET_IDS, SERVICE_PRESETS
from zapret_hub.services.service_rules import SERVICE_RULES


_SETTINGS_KEYS = (
    "selected_zapret_general",
    "zapret_ipset_mode",
    "zapret_game_filter_mode",
    "zapret_gaming_set",
    "selected_service_ids",
    "enabled_component_ids",
    "trusted_general",
    "enabled_mod_ids",
    "enabled_zapret2_mod_ids",
    "zapret2_strategy_id",
)


# Classic list applies still restart winws (hostlists must land), but not on every
# domain tick — adaptive spacing + deferred flush (FluxRoute-style calm).
_LIST_RESTART_BASE_S = 45.0
_LIST_RESTART_MAX_S = 300.0
_LIST_RESTART_WINDOW_S = 300.0
_LIST_DEBOUNCE_QUIET_S = 18.0
_SESSION_LOCK_DEFER_S = 120.0


class CutoverManager:
    """Warm A/B cutover: stage B → start B beside A → kill A only after B is alive.

    Settings↔runtime always restored together on failure. Never leave the machine
    without a running classic winws when a cutover is attempted.
    """

    def __init__(
        self,
        context: Any,
        *,
        knowledge: Any | None = None,
        signals: SignalCollector | None = None,
    ) -> None:
        self.context = context
        self.knowledge = knowledge
        self.signals = signals or SignalCollector()
        self.last_good: dict[str, Any] | None = None
        self._slot_a: Path | None = None
        self._settle_s = 2.2
        self._last_list_restart_at = 0.0
        self._list_restart_times: list[float] = []
        self._deferred_list_restart = False
        self._deferred_list_due_at = 0.0
        self._deferred_probe_targets: list[dict[str, str]] = []
        self._deferred_required_hosts: list[str] = []

    def _log(self, level: str, message: str, **fields: Any) -> None:
        logging = getattr(self.context, "logging", None)
        if logging is None:
            return
        try:
            logging.log(level, message, **fields)
        except Exception:
            pass

    def snapshot(self, *, force_runtime: Path | None = None) -> dict[str, Any]:
        settings = self.context.settings.get()
        payload: dict[str, Any] = {key: getattr(settings, key, None) for key in _SETTINGS_KEYS}
        payload["selected_service_ids"] = list(settings.selected_service_ids or [])
        payload["enabled_component_ids"] = list(getattr(settings, "enabled_component_ids", None) or [])
        payload["enabled_mod_ids"] = list(getattr(settings, "enabled_mod_ids", None) or [])
        payload["enabled_zapret2_mod_ids"] = list(getattr(settings, "enabled_zapret2_mod_ids", None) or [])
        live = force_runtime or getattr(self.context.processes, "_current_zapret_runtime", None)
        if live is not None:
            payload["runtime_path"] = str(live)
            self._slot_a = Path(live)
            try:
                self.context.processes.remember_auto_runtime(Path(live))
            except Exception:
                pass
        self.last_good = payload
        if self.knowledge is not None:
            try:
                self.knowledge.save_last_known_good(payload)
            except Exception:
                pass
        return dict(payload)

    def load_last_good(self) -> dict[str, Any]:
        if self.last_good:
            return dict(self.last_good)
        if self.knowledge is not None:
            try:
                stored = self.knowledge.load_last_known_good()
                if stored:
                    self.last_good = dict(stored)
                    return dict(stored)
            except Exception:
                pass
        return {}

    def apply_plan(
        self,
        steps: list[TunerStep] | list[dict[str, Any]] | None,
        *,
        probe_targets: list[dict[str, str]] | None = None,
        required_hosts: list[str] | None = None,
        restart: bool | None = None,
    ) -> dict[str, Any]:
        """Apply ALL steps, then ONE staged cutover + probe. Rollback settings+runtime on fail."""
        if self._runtime_backend() == "zapret2":
            return self._apply_plan_zapret2(
                steps,
                probe_targets=probe_targets,
                required_hosts=required_hosts,
                restart=restart,
            )
        return self._apply_plan_classic(
            steps,
            probe_targets=probe_targets,
            required_hosts=required_hosts,
            restart=restart,
        )

    def _runtime_backend(self) -> str:
        try:
            mode = str(self.context.settings.get().selected_runtime_mode or "zapret")
        except Exception:
            mode = "zapret"
        return "zapret2" if mode == "zapret2" else "zapret"

    def _abort_if_backend_changed(self, backend: str) -> dict[str, Any] | None:
        if self._runtime_backend() != backend:
            return {
                "ok": False,
                "applied": [],
                "skipped": [],
                "results": [],
                "restarted": False,
                "error": "runtime_mode_changed",
                "backend": backend,
            }
        aborted = self._abort_if_power_off(backend)
        return aborted

    def _abort_if_power_off(self, backend: str) -> dict[str, Any] | None:
        """User turned Quick Access off mid-tune — do not restart the bypass."""
        try:
            orch = getattr(self.context, "orchestrator", None)
            if orch is not None and hasattr(orch, "is_live") and not orch.is_live():
                return {
                    "ok": False,
                    "applied": [],
                    "skipped": [],
                    "results": [],
                    "restarted": False,
                    "error": "power_off",
                    "backend": backend,
                }
        except Exception:
            pass
        return None

    def _apply_plan_classic(
        self,
        steps: list[TunerStep] | list[dict[str, Any]] | None,
        *,
        probe_targets: list[dict[str, str]] | None = None,
        required_hosts: list[str] | None = None,
        restart: bool | None = None,
    ) -> dict[str, Any]:
        """Classic Zapret: strategy/mods/knobs → warm process cutover.
        Hostlist-only → rewrite live lists without killing winws (Discord-safe).
        """
        normalized = self._normalize_steps(steps)
        normalized = self._coalesce_list_steps(normalized)
        if not normalized:
            return {"ok": True, "applied": [], "skipped": [], "results": [], "restarted": False, "backend": "zapret"}

        was_running = self._zapret_running() if restart is None else bool(restart)
        baseline = self.snapshot()
        overlay_checkpoint = self._overlay_checkpoint()
        live_a = getattr(self.context.processes, "_current_zapret_runtime", None)
        if live_a is not None:
            self._slot_a = Path(live_a)
            try:
                self.context.processes.pin_orchestrator_runtime(self._slot_a)
            except Exception:
                pass

        applied: list[dict[str, Any]] = []
        list_changed = False
        hard_restart = False
        try:
            for step in normalized:
                changed = self._apply_one_mutation(step, backend="zapret")
                applied.append({"kind": step.kind, "value": step.value, "reason": step.reason})
                if changed == "lists":
                    list_changed = True
                elif changed in {"settings", "mods", "restart"}:
                    hard_restart = True

            aborted = self._abort_if_backend_changed("zapret")
            if aborted is not None:
                return aborted

            if not was_running:
                self._rebuild_snapshot_only()
                self.snapshot()
                self._clear_deferred_list_restart()
                return {
                    "ok": True,
                    "applied": applied,
                    "skipped": [],
                    "results": [{"ok": True, "restarted": False}],
                    "restarted": False,
                    "backend": "zapret",
                }

            if hard_restart:
                if list_changed:
                    self._hot_reload_classic_lists()
                deferred = self._defer_classic_for_session(
                    applied=applied,
                    probe_targets=probe_targets,
                    required_hosts=required_hosts,
                    hot_reload=list_changed,
                )
                if deferred is not None:
                    self.snapshot()
                    return deferred
                self._clear_deferred_list_restart()
                return self._classic_cutover_and_probe(
                    applied=applied,
                    baseline=baseline,
                    overlay_checkpoint=overlay_checkpoint,
                    probe_targets=probe_targets,
                    required_hosts=required_hosts,
                )

            if list_changed:
                # Domain/IP learning: rewrite lists under live runtime — never cut over.
                self._hot_reload_classic_lists()
                self._clear_deferred_list_restart()
                try:
                    self.context.processes.pin_orchestrator_runtime(None)
                except Exception:
                    pass
                self.snapshot()
                self._log("info", "Orchestrator hot-reloaded classic lists (no process cutover)")
                return {
                    "ok": True,
                    "applied": applied,
                    "skipped": [],
                    "results": [{"ok": True, "restarted": False, "hot_reload": True}],
                    "restarted": False,
                    "hot_reload": True,
                    "backend": "zapret",
                }

            try:
                self.context.processes.pin_orchestrator_runtime(None)
            except Exception:
                pass
            return {
                "ok": True,
                "applied": applied,
                "skipped": [],
                "results": [{"ok": True, "restarted": False}],
                "restarted": False,
                "backend": "zapret",
            }
        except Exception as error:
            self._log("error", "Orchestrator apply_plan failed", error=str(error))
            try:
                self._full_rollback(baseline, overlay_checkpoint=overlay_checkpoint)
            except Exception:
                pass
            return {
                "ok": False,
                "applied": [],
                "skipped": applied,
                "results": [],
                "restarted": False,
                "error": str(error),
                "rolled_back": True,
                "backend": "zapret",
            }

    def _adaptive_list_restart_interval_s(self, *, batch_size: int = 1) -> float:
        now = time.monotonic()
        self._list_restart_times = [t for t in self._list_restart_times if (now - t) <= _LIST_RESTART_WINDOW_S]
        count = len(self._list_restart_times)
        interval = _LIST_RESTART_BASE_S * (1.55 ** max(0, count))
        # Large batched domain dumps are worth applying sooner.
        if batch_size >= 8:
            interval *= 0.65
        elif batch_size >= 4:
            interval *= 0.8
        return max(_LIST_DEBOUNCE_QUIET_S, min(_LIST_RESTART_MAX_S, interval))

    def _list_restart_allowed(self, *, batch_size: int = 1) -> bool:
        if self._last_list_restart_at <= 0:
            return True
        interval = self._adaptive_list_restart_interval_s(batch_size=batch_size)
        return (time.monotonic() - self._last_list_restart_at) >= interval

    def _note_list_restart(self) -> None:
        now = time.monotonic()
        self._last_list_restart_at = now
        self._list_restart_times.append(now)
        self._list_restart_times = [t for t in self._list_restart_times if (now - t) <= _LIST_RESTART_WINDOW_S]

    def _arm_deferred_list_restart(
        self,
        *,
        probe_targets: list[dict[str, str]] | None,
        required_hosts: list[str] | None,
        force_due_in: float | None = None,
    ) -> float:
        now = time.monotonic()
        if force_due_in is not None:
            due = now + max(5.0, float(force_due_in))
        else:
            interval = self._adaptive_list_restart_interval_s()
            if self._last_list_restart_at > 0:
                due = self._last_list_restart_at + interval
            else:
                due = now + _LIST_DEBOUNCE_QUIET_S
            # While domains keep arriving, wait a short quiet period — but never past MAX.
            if self._deferred_list_restart:
                due = max(due, now + _LIST_DEBOUNCE_QUIET_S)
            cap = (self._last_list_restart_at or now) + _LIST_RESTART_MAX_S
            due = min(max(due, now + 1.0), cap)
        self._deferred_list_restart = True
        self._deferred_list_due_at = due
        if probe_targets:
            self._deferred_probe_targets = list(probe_targets)
        if required_hosts:
            self._deferred_required_hosts = list(required_hosts)
        return max(0.0, due - now)

    def _session_lock(self):
        from zapret_hub.services.orchestrator.presence import detect_session_lock

        samples = None
        process_names: list[str] = []
        try:
            samples = self.signals.snapshot_connections(limit=120)
        except Exception:
            samples = None
        # Fallback: running process image names (idle Discord/game with few sockets).
        try:
            processes = getattr(self.context, "processes", None)
            if processes is not None and hasattr(processes, "_run_quiet"):
                proc = processes._run_quiet(["tasklist", "/FO", "CSV", "/NH"])
                raw = str(getattr(proc, "stdout", "") or "")
                for line in raw.splitlines():
                    parts = [part.strip().strip('"') for part in line.split(",")]
                    if parts:
                        process_names.append(parts[0])
        except Exception:
            pass
        return detect_session_lock(samples, process_names=process_names)

    def _defer_classic_for_session(
        self,
        *,
        applied: list[dict[str, Any]],
        probe_targets: list[dict[str, str]] | None,
        required_hosts: list[str] | None,
        hot_reload: bool = False,
    ) -> dict[str, Any] | None:
        """During Discord/Zoom/game — keep live winws, postpone classic process cutover."""
        lock = self._session_lock()
        if not lock.active:
            return None
        due_in = self._arm_deferred_list_restart(
            probe_targets=probe_targets,
            required_hosts=required_hosts,
            force_due_in=_SESSION_LOCK_DEFER_S,
        )
        self._log(
            "info",
            "Orchestrator deferred classic cutover during live session",
            reason=lock.reason,
            kind=lock.kind,
            due_in_s=round(due_in, 1),
        )
        return {
            "ok": True,
            "applied": applied,
            "skipped": [],
            "results": [{"ok": True, "restarted": False, "deferred_restart": True, "session_lock": lock.reason}],
            "restarted": False,
            "deferred_restart": True,
            "session_lock": lock.reason,
            "hot_reload": hot_reload,
            "backend": "zapret",
        }

    def _clear_deferred_list_restart(self) -> None:
        self._deferred_list_restart = False
        self._deferred_list_due_at = 0.0
        self._deferred_probe_targets = []
        self._deferred_required_hosts = []

    def has_deferred_list_restart(self) -> bool:
        return bool(self._deferred_list_restart)

    def flush_deferred_list_restart(self) -> dict[str, Any] | None:
        """Legacy deferred classic restart: now only hot-reloads lists (no process kill)."""
        if not self._deferred_list_restart:
            return None
        if time.monotonic() < self._deferred_list_due_at:
            return None
        if self._runtime_backend() != "zapret":
            self._clear_deferred_list_restart()
            return None
        aborted = self._abort_if_backend_changed("zapret")
        if aborted is not None:
            self._clear_deferred_list_restart()
            return aborted
        if self._zapret_running():
            self._hot_reload_classic_lists()
        else:
            self._rebuild_snapshot_only()
        self._clear_deferred_list_restart()
        self._log("info", "Orchestrator flushed deferred classic lists via hot-reload")
        return {"ok": True, "restarted": False, "hot_reload": True, "deferred_restart": False, "backend": "zapret"}

    def _classic_cutover_and_probe(
        self,
        *,
        applied: list[dict[str, Any]],
        baseline: dict[str, Any],
        overlay_checkpoint: dict[str, Any] | None,
        probe_targets: list[dict[str, str]] | None,
        required_hosts: list[str] | None,
    ) -> dict[str, Any]:
        self._rebuild_snapshot_only()
        aborted = self._abort_if_backend_changed("zapret")
        if aborted is not None:
            return aborted
        slot_b = self._stage_candidate_b()
        self._log("info", "Orchestrator staged candidate B", runtime=str(slot_b), steps=len(applied))

        aborted = self._abort_if_backend_changed("zapret")
        if aborted is not None:
            return aborted
        if hasattr(self.context.processes, "hot_replace_zapret_runtime"):
            started = self.context.processes.hot_replace_zapret_runtime(slot_b)
        else:
            try:
                self.context.processes.stop_component("zapret")
            except Exception as error:
                self._log("warning", "Orchestrator stop A failed", error=str(error))
            aborted = self._abort_if_backend_changed("zapret")
            if aborted is not None:
                return aborted
            started = self.context.processes.start_zapret_from_runtime(slot_b)
        restarted = str(getattr(started, "status", "")) == "running"
        if not restarted:
            self._full_rollback(baseline, overlay_checkpoint=overlay_checkpoint)
            return {
                "ok": False,
                "applied": [],
                "skipped": applied,
                "results": [],
                "restarted": False,
                "rolled_back": True,
                "error": str(getattr(started, "last_error", "") or "start_b_failed"),
                "backend": "zapret",
            }

        time.sleep(self._settle_s)
        targets = list(probe_targets or [])
        ok = True
        if targets:
            results = self._probe(targets)
            ok = probe_required_ok(results, required_hosts=required_hosts or [])
        if not ok:
            self._log("info", "Orchestrator candidate B failed probe — full rollback")
            self._full_rollback(baseline, overlay_checkpoint=overlay_checkpoint)
            return {
                "ok": False,
                "applied": [],
                "skipped": applied,
                "results": [],
                "restarted": True,
                "rolled_back": True,
                "error": "probe_failed",
                "backend": "zapret",
            }

        try:
            self.context.processes.pin_orchestrator_runtime(None)
        except Exception:
            pass
        self.snapshot(force_runtime=slot_b)
        try:
            self.context.processes.remember_auto_runtime(slot_b)
            self.context.processes._cleanup_inactive_zapret_runtimes()
        except Exception:
            pass
        return {
            "ok": True,
            "applied": applied,
            "skipped": [],
            "results": [{"ok": True, "restarted": True, "runtime": str(slot_b)}],
            "restarted": True,
            "runtime": str(slot_b),
            "backend": "zapret",
        }

    def _hot_reload_classic_lists(self) -> None:
        """Rewrite hostlists/ipsets under the live winws runtime (mtime path + deferred restart)."""
        processes = self.context.processes
        live = getattr(processes, "_current_zapret_runtime", None)
        if live is None:
            self._rebuild_snapshot_only()
            return
        lists_dir = Path(live) / "lists"
        try:
            lists_dir.mkdir(parents=True, exist_ok=True)
            if hasattr(processes, "_ensure_zapret_user_lists"):
                processes._ensure_zapret_user_lists(lists_dir)
            if hasattr(processes, "_materialize_visible_merged_runtime"):
                processes._materialize_visible_merged_runtime(Path(live))
            self._log("info", "Orchestrator hot-reloaded classic lists", runtime=str(live))
        except Exception as error:
            self._log("warning", "Classic list hot-reload failed", error=str(error))
            self._rebuild_snapshot_only()

    def _apply_plan_zapret2(
        self,
        steps: list[TunerStep] | list[dict[str, Any]] | None,
        *,
        probe_targets: list[dict[str, str]] | None = None,
        required_hosts: list[str] | None = None,
        restart: bool | None = None,
    ) -> dict[str, Any]:
        """Zapret2: never kill winws2 — lists/strategy Lua reload via mtime/hot-load."""
        from zapret_hub.services.orchestrator import zapret2_hub

        normalized = self._normalize_steps(steps)
        normalized = self._coalesce_list_steps(normalized)
        if not normalized:
            return {"ok": True, "applied": [], "skipped": [], "results": [], "restarted": False, "backend": "zapret2"}

        was_running = self._zapret2_running() if restart is None else bool(restart)
        baseline = self.snapshot()
        overlay_checkpoint = self._overlay_checkpoint()
        applied: list[dict[str, Any]] = []
        try:
            for step in normalized:
                changed = self._apply_one_mutation(step, backend="zapret2")
                applied.append({"kind": step.kind, "value": step.value, "reason": step.reason, "changed": changed})

            # Always rematerialize watched files so winws2 picks up hostlist/ipset/strategy Lua.
            aborted = self._abort_if_backend_changed("zapret2")
            if aborted is not None:
                return aborted
            if was_running:
                try:
                    configs = Path(self.context.paths.configs_dir)
                    auto_root = Path(self.context.paths.runtime_dir) / "zapret2" / "lists_auto"
                    zapret2_hub.materialize_auto_lists(configs, auto_root)
                    # Touch strategy lua mtime so winws2 reloads even if content was rewritten in place.
                    strategy_id = str(getattr(self.context.settings.get(), "zapret2_strategy_id", "balanced") or "balanced")
                    zapret2_hub.write_hub_strategy_lua(configs, strategy_id)
                    self._log("info", "Orchestrator hot-reloaded Zapret2 lists/strategy (no process restart)")
                except Exception as error:
                    self._log("warning", "Zapret2 hot-reload rematerialize failed", error=str(error))

            targets = list(probe_targets or [])
            ok = True
            if targets and was_running:
                time.sleep(0.35)
                results = self._probe(targets)
                ok = probe_required_ok(results, required_hosts=required_hosts or [])
            if not ok:
                self._log("info", "Zapret2 plan failed probe — rollback lists/settings (process kept running)")
                self._full_rollback_zapret2(baseline, overlay_checkpoint=overlay_checkpoint)
                return {
                    "ok": False,
                    "applied": [],
                    "skipped": applied,
                    "results": [],
                    "restarted": False,
                    "rolled_back": True,
                    "error": "probe_failed",
                    "backend": "zapret2",
                }

            self.snapshot()
            return {
                "ok": True,
                "applied": applied,
                "skipped": [],
                "results": [{"ok": True, "restarted": False, "hot_reload": True}],
                "restarted": False,
                "backend": "zapret2",
                "listsDir": str(zapret2_hub.zapret2_lists_dir(Path(self.context.paths.configs_dir))),
            }
        except Exception as error:
            self._log("error", "Zapret2 apply_plan failed", error=str(error))
            try:
                self._full_rollback_zapret2(baseline, overlay_checkpoint=overlay_checkpoint)
            except Exception:
                pass
            return {
                "ok": False,
                "applied": [],
                "skipped": applied,
                "results": [],
                "restarted": False,
                "error": str(error),
                "rolled_back": True,
                "backend": "zapret2",
            }

    def _overlay_store(self) -> Any:
        from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

        return AutoOverlayStore(Path(self.context.paths.configs_dir))

    def _overlay_checkpoint(self) -> dict[str, Any] | None:
        try:
            return self._overlay_store().checkpoint()
        except Exception:
            return None

    def _overlay_restore(self, checkpoint: dict[str, Any] | None) -> None:
        if not checkpoint:
            return
        try:
            self._overlay_store().restore(checkpoint)
        except Exception as error:
            self._log("warning", "Auto overlay restore failed", error=str(error))

    def _full_rollback_zapret2(
        self,
        baseline: dict[str, Any] | None = None,
        *,
        overlay_checkpoint: dict[str, Any] | None = None,
    ) -> bool:
        self._overlay_restore(overlay_checkpoint)
        good = dict(baseline or self.load_last_good() or {})
        if not good:
            return False
        changes: dict[str, Any] = {}
        for key in _SETTINGS_KEYS:
            if key in good and good[key] is not None:
                changes[key] = good[key]
        if changes:
            try:
                self.context.settings.update(**changes)
            except Exception as error:
                self._log("warning", "Zapret2 rollback settings failed", error=str(error))
        self._restore_mod2_enables(list(good.get("enabled_zapret2_mod_ids") or []))
        if self._runtime_backend() != "zapret2":
            return False
        if self._abort_if_power_off("zapret2") is not None:
            return False
        try:
            if self._zapret2_running():
                self.context.processes.stop_component("zapret2")
            if self._abort_if_power_off("zapret2") is not None:
                return False
            state = self.context.processes.start_component("zapret2")
            ok = str(getattr(state, "status", "")) == "running"
            if ok:
                self.last_good = dict(good)
            return ok
        except Exception:
            return False

    def _zapret2_running(self) -> bool:
        try:
            states = {item.component_id: item for item in self.context.processes.list_states()}
            state = states.get("zapret2")
            return bool(state and getattr(state, "status", "") == "running")
        except Exception:
            return False

    def apply_knobs(self, steps: list[Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.apply_plan(steps, **kwargs)

    def apply(self, steps: list[Any] | None = None, **kwargs: Any) -> bool:
        return bool(self.apply_plan(steps, **kwargs).get("ok"))

    def apply_step(
        self,
        step: TunerStep,
        *,
        probe_targets: list[dict[str, str]] | None = None,
        required_hosts: list[str] | None = None,
        was_running: bool | None = None,
    ) -> dict[str, Any]:
        """Legacy single-step API — delegates to batched apply_plan."""
        return self.apply_plan(
            [step],
            probe_targets=probe_targets,
            required_hosts=required_hosts,
            restart=was_running,
        )

    def _full_rollback(
        self,
        baseline: dict[str, Any] | None = None,
        *,
        overlay_checkpoint: dict[str, Any] | None = None,
    ) -> bool:
        """Restore settings AND runtime from baseline / last_good. Always together."""
        self._overlay_restore(overlay_checkpoint)
        good = dict(baseline or self.load_last_good() or {})
        if not good:
            return self._rebuild_and_maybe_restart(restart=True)

        changes: dict[str, Any] = {}
        for key in _SETTINGS_KEYS:
            if key in good and good[key] is not None:
                changes[key] = good[key]
        # Restore mod enables explicitly (ids list + ModsManager flags).
        enabled_mods = list(good.get("enabled_mod_ids") or [])
        enabled_mods2 = list(good.get("enabled_zapret2_mod_ids") or [])
        if changes:
            try:
                self.context.settings.update(**changes)
            except Exception as error:
                self._log("warning", "Rollback settings update failed", error=str(error))
        self._restore_mod_enables(enabled_mods)
        self._restore_mod2_enables(enabled_mods2)

        if self._abort_if_power_off("zapret") is not None:
            return False

        runtime_path = str(good.get("runtime_path") or "")
        path_ok = bool(runtime_path and Path(runtime_path).exists())
        try:
            if self._zapret_running():
                self.context.processes.stop_component("zapret")
        except Exception:
            pass

        if self._abort_if_power_off("zapret") is not None:
            return False

        if path_ok:
            try:
                self.context.processes.pin_orchestrator_runtime(Path(runtime_path))
            except Exception:
                pass
            state = self.context.processes.start_zapret_from_runtime(Path(runtime_path))
            try:
                self.context.processes.pin_orchestrator_runtime(None)
            except Exception:
                pass
            if str(getattr(state, "status", "")) == "running":
                self.last_good = dict(good)
                return True
            self._log("warning", "Rollback start from saved path failed — full rebuild")

        ok = self._rebuild_and_maybe_restart(restart=True)
        if ok:
            self.snapshot()
        return ok

    def rollback(self, *, restart: bool = True) -> bool:
        if not restart:
            good = self.load_last_good()
            if not good:
                return False
            changes = {k: good[k] for k in _SETTINGS_KEYS if k in good and good[k] is not None}
            if changes:
                self.context.settings.update(**changes)
            self._restore_mod_enables(list(good.get("enabled_mod_ids") or []))
            self._restore_mod2_enables(list(good.get("enabled_zapret2_mod_ids") or []))
            return True
        return self._full_rollback()

    def _restore_mod_enables(self, enabled_ids: list[str]) -> None:
        mods = getattr(self.context, "mods", None)
        if mods is None:
            return
        want = {str(item) for item in enabled_ids}
        try:
            installed = mods.list_installed()
        except Exception:
            return
        for mod in installed:
            should = mod.id in want
            if bool(mod.enabled) == should:
                continue
            try:
                mods.set_enabled(mod.id, should)
            except Exception as error:
                self._log("warning", "Rollback mod enable failed", mod_id=mod.id, error=str(error))

    def _restore_mod2_enables(self, enabled_ids: list[str]) -> None:
        mods2 = getattr(self.context, "mods2", None)
        if mods2 is None:
            return
        want = {str(item) for item in enabled_ids}
        try:
            installed = mods2.list_installed()
        except Exception:
            return
        for mod in installed:
            should = mod.id in want
            if bool(mod.enabled) == should:
                continue
            try:
                mods2.set_enabled(mod.id, should)
            except Exception as error:
                self._log("warning", "Rollback Zapret2 mod enable failed", mod_id=mod.id, error=str(error))

    def commit_trusted_general(self, general_id: str, *, snapshot_after: bool = False) -> None:
        if not general_id:
            return
        self.context.settings.update(
            trusted_general=general_id,
            selected_zapret_general=general_id,
            general_autotest_done=True,
        )
        if self.knowledge is not None:
            try:
                self.knowledge.rank_general(general_id, 5.0)
            except Exception:
                pass
        if snapshot_after:
            self.snapshot()

    def apply_and_start_trusted(
        self,
        *,
        general_id: str,
        probe_targets: list[dict[str, str]],
        required_hosts: list[str],
    ) -> dict[str, Any]:
        """Bootstrap: mutate to trusted general, stage/start, probe; rollback to pre-bootstrap on fail."""
        baseline = self.snapshot()  # BEFORE trusted mutation
        live_a = getattr(self.context.processes, "_current_zapret_runtime", None)
        if live_a is not None:
            try:
                self.context.processes.pin_orchestrator_runtime(Path(live_a))
            except Exception:
                pass

        try:
            self.commit_trusted_general(general_id, snapshot_after=False)
            self._rebuild_snapshot_only()
            slot_b = self._stage_candidate_b()
            if hasattr(self.context.processes, "hot_replace_zapret_runtime"):
                state = self.context.processes.hot_replace_zapret_runtime(slot_b)
            else:
                try:
                    if self._zapret_running():
                        self.context.processes.stop_component("zapret")
                except Exception:
                    pass
                state = self.context.processes.start_zapret_from_runtime(slot_b)
            if str(getattr(state, "status", "")) != "running":
                self._full_rollback(baseline)
                return {"ok": False, "error": str(getattr(state, "last_error", "") or "start_failed")}
            time.sleep(self._settle_s)
            results = self._probe(probe_targets)
            ok = probe_required_ok(results, required_hosts=required_hosts)
            if not ok:
                self._full_rollback(baseline)
                return {"ok": False, "error": "probe_failed", "results": [r.__dict__ for r in results]}
            try:
                self.context.processes.pin_orchestrator_runtime(None)
            except Exception:
                pass
            self.snapshot(force_runtime=slot_b)
            return {"ok": True, "runtime": str(slot_b), "general": general_id}
        except Exception as error:
            try:
                self._full_rollback(baseline)
            except Exception:
                pass
            return {"ok": False, "error": str(error)}

    def _normalize_steps(self, steps: list[Any] | None) -> list[TunerStep]:
        out: list[TunerStep] = []
        seen: set[tuple[str, str]] = set()
        for raw in steps or []:
            if isinstance(raw, TunerStep):
                step = raw
            else:
                step = TunerStep(
                    kind=str(raw.get("kind") or ""),
                    value=str(raw.get("value") or ""),
                    reason=str(raw.get("reason") or ""),
                    label_ru=str(raw.get("label_ru") or ""),
                    label_en=str(raw.get("label_en") or ""),
                )
            if not step.kind or not step.value:
                continue
            key = (step.kind, step.value)
            if key in seen:
                continue
            seen.add(key)
            out.append(step)
        return out

    def _apply_one_mutation(self, step: TunerStep, *, backend: str = "zapret") -> str:
        if step.kind in {"add_domain", "add_ip", "exclude_domain", "remove_domain", "remove_ip"}:
            self._apply_list_step(step, backend=backend)
            return "lists"
        if step.kind == "enable_mod":
            if backend == "zapret2":
                self._apply_enable_mod2(step.value)
                return "mods"
            self._apply_enable_mod(step.value)
            return "mods"
        return self._apply_settings_step(step, backend=backend)

    def _apply_list_step(self, step: TunerStep, *, backend: str = "zapret") -> list[str]:
        values = [part.strip() for part in str(step.value or "").replace(",", "\n").splitlines() if part.strip()]
        if not values:
            return []
        reason = str(step.reason or step.kind or "auto")
        if backend == "zapret2":
            from zapret_hub.services.orchestrator import zapret2_hub

            configs = Path(self.context.paths.configs_dir)
            if step.kind == "add_domain":
                return zapret2_hub.add_auto_domains(configs, values, reason=reason)
            if step.kind == "exclude_domain":
                return zapret2_hub.exclude_auto_domains(configs, values, reason=reason)
            if step.kind == "add_ip":
                return zapret2_hub.add_auto_ips(configs, values, reason=reason)
            if step.kind == "remove_domain":
                from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

                return AutoOverlayStore(configs).remove_domains(values, reason=reason)
            if step.kind == "remove_ip":
                from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

                return AutoOverlayStore(configs).remove_ips(values, reason=reason)
            return []

        configs = Path(self.context.paths.configs_dir)
        learner = HostlistLearner(configs)
        if step.kind == "add_domain":
            return learner.add_domains(values, reason=reason)
        if step.kind == "exclude_domain":
            return learner.exclude_domains(values, reason=reason)
        if step.kind == "add_ip":
            return learner.add_ips(values, reason=reason)
        if step.kind == "remove_domain":
            return learner.remove_domains(values, reason=reason)
        if step.kind == "remove_ip":
            return learner.remove_ips(values, reason=reason)
        return []

    def _coalesce_list_steps(self, steps: list[TunerStep]) -> list[TunerStep]:
        """Merge many add_domain/add_ip/exclude into one write each."""
        domains: list[str] = []
        ips: list[str] = []
        excludes: list[str] = []
        other: list[TunerStep] = []
        meta: dict[str, TunerStep] = {}
        for step in steps:
            if step.kind == "add_domain":
                domains.extend(
                    part.strip() for part in str(step.value or "").replace(",", "\n").splitlines() if part.strip()
                )
                meta["add_domain"] = step
            elif step.kind == "add_ip":
                ips.extend(
                    part.strip() for part in str(step.value or "").replace(",", "\n").splitlines() if part.strip()
                )
                meta["add_ip"] = step
            elif step.kind == "exclude_domain":
                excludes.extend(
                    part.strip() for part in str(step.value or "").replace(",", "\n").splitlines() if part.strip()
                )
                meta["exclude_domain"] = step
            else:
                other.append(step)

        def uniq(items: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for item in items:
                key = item.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
            return out

        merged: list[TunerStep] = []
        domains = uniq(domains)
        ips = uniq(ips)
        excludes = uniq(excludes)
        if domains:
            base = meta.get("add_domain")
            preview = domains[0] if len(domains) == 1 else f"{len(domains)} доменов"
            merged.append(
                TunerStep(
                    kind="add_domain",
                    value="\n".join(domains),
                    reason=str(getattr(base, "reason", "") or "external_miss"),
                    label_ru=f"Добавляю {preview} в списки",
                    label_en=f"Adding {preview} to lists",
                )
            )
        if ips:
            base = meta.get("add_ip")
            preview = ips[0] if len(ips) == 1 else f"{len(ips)} адресов"
            merged.append(
                TunerStep(
                    kind="add_ip",
                    value="\n".join(ips),
                    reason=str(getattr(base, "reason", "") or "external_miss"),
                    label_ru=f"Добавляю {preview}",
                    label_en=f"Adding {preview}",
                )
            )
        if excludes:
            base = meta.get("exclude_domain")
            preview = excludes[0] if len(excludes) == 1 else f"{len(excludes)} доменов"
            merged.append(
                TunerStep(
                    kind="exclude_domain",
                    value="\n".join(excludes),
                    reason=str(getattr(base, "reason", "") or "over_block"),
                    label_ru=f"Исключаю {preview}",
                    label_en=f"Excluding {preview}",
                )
            )
        return merged + other

    def _apply_enable_mod(self, mod_id: str) -> None:
        mods = getattr(self.context, "mods", None)
        if mods is None:
            raise RuntimeError("Mods manager unavailable")
        installed_ids = {item.id for item in mods.list_installed()}
        if mod_id not in installed_ids:
            try:
                index_ids = {item.id for item in mods.fetch_index()}
            except Exception:
                index_ids = set()
            if mod_id in index_ids:
                mods.install(mod_id)
            else:
                raise RuntimeError(f"Mod not installed: {mod_id}")
        mods.set_enabled(mod_id, True)
        self._log("info", "Orchestrator enabled mod", mod_id=mod_id)

    def _apply_enable_mod2(self, mod_id: str) -> None:
        mods = getattr(self.context, "mods2", None)
        if mods is None:
            raise RuntimeError("Zapret2 mods manager unavailable")
        installed_ids = {item.id for item in mods.list_installed()}
        if mod_id not in installed_ids:
            raise RuntimeError(f"Zapret2 mod not installed: {mod_id}")
        mods.set_enabled(mod_id, True)
        self._log("info", "Orchestrator enabled Zapret2 mod", mod_id=mod_id)

    def _stage_candidate_b(self) -> Path:
        processes = self.context.processes
        if hasattr(processes, "stage_zapret_candidate_runtime"):
            return Path(processes.stage_zapret_candidate_runtime())
        self._rebuild_snapshot_only()
        live = getattr(processes, "_current_zapret_runtime", None)
        if live is None:
            raise RuntimeError("Failed to stage candidate runtime")
        return Path(live)

    def _apply_settings_step(self, step: TunerStep, *, backend: str = "zapret") -> str:
        from zapret_hub.services.orchestrator import zapret2_hub

        settings = self.context.settings.get()
        configs = Path(self.context.paths.configs_dir)

        if step.kind == "enable_service":
            selected = {str(item) for item in (settings.selected_service_ids or [])}
            if step.value in SERVICE_PRESET_IDS:
                selected.add(step.value)
            ordered = [preset.id for preset in SERVICE_PRESETS if preset.id in selected]
            changes: dict[str, Any] = {"selected_service_ids": ordered}
            enabled = {str(item) for item in (settings.enabled_component_ids or [])}
            # Auto never switches Quick Access bypass. Only keep the active one enabled.
            active = str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret")
            live_backend = "zapret2" if active == "zapret2" else "zapret"
            if live_backend != backend:
                # Stale plan for the other bypass — ignore component flips.
                backend = live_backend
            if live_backend == "zapret2":
                enabled.add("zapret2")
                enabled.discard("zapret")
            elif step.value not in {"telegram-desktop", "ai"}:
                enabled.add("zapret")
                enabled.discard("zapret2")
            if step.value == "telegram-desktop":
                enabled.add("tg-ws-proxy")
            if step.value == "ai":
                enabled.add("xbox-dns")
            if step.value in {"gaming", "warframe"} and live_backend == "zapret":
                changes["zapret_game_filter_mode"] = "tcpudp"
            if step.value == "fortnite" and live_backend == "zapret":
                changes["zapret_ipset_mode"] = "any"
                changes["zapret_game_filter_mode"] = "tcpudp"
            changes["enabled_component_ids"] = sorted(enabled)
            self.context.settings.update(**changes)
            # One-shot: dump known domains for this service. Classic stock services
            # must NOT receive CDN CIDRs into ipset-all-user (breaks Discord).
            harvested_domains = zapret2_hub.harvest_service_domains([step.value])
            from zapret_hub.services.service_rules import is_stock_service

            harvested_ips = (
                []
                if is_stock_service(step.value)
                else zapret2_hub.harvest_service_ips([step.value])
            )
            if backend == "zapret2":
                zapret2_hub.seed_service_lists(configs, [step.value])
            else:
                # Stock service domains stay in service materialization; only extra
                # non-stock harvest goes into Auto overlay (never battle user lists).
                from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

                store = AutoOverlayStore(configs)
                if harvested_domains and not is_stock_service(step.value):
                    store.add_domains(harvested_domains, reason=f"enable_service:{step.value}")
                if harvested_ips:
                    store.add_ips(harvested_ips, reason=f"enable_service:{step.value}")
            # Gaming/Fortnite also flip WinDivert knobs → need process restart on classic.
            if live_backend == "zapret" and step.value in {"gaming", "fortnite", "warframe"}:
                return "settings"
            return "lists"

        if step.kind == "ipset":
            if backend == "zapret2":
                # Widen coverage via Auto overlay remove/add — never mutate battle ipset-hub
                # with Discord CDN when Discord service is selected. Seed only non-Discord nets.
                from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

                selected = {str(x) for x in (self.context.settings.get().selected_service_ids or [])}
                nets = list(zapret2_hub.BYPASS_SEED_NETWORKS)
                if "discord" in selected:
                    nets = [n for n in nets if str(n).strip().lower() not in {"162.159.128.0/20"}]
                AutoOverlayStore(configs).add_ips(nets, reason="ipset_widen")
                return "lists"
            self.context.settings.update(zapret_ipset_mode=step.value)
            return "settings"

        if step.kind == "game_filter":
            if backend == "zapret2":
                return "skip"
            self.context.settings.update(zapret_game_filter_mode=step.value)
            return "settings"

        if step.kind == "gaming_set":
            if backend == "zapret2":
                return "skip"
            self.context.settings.update(zapret_gaming_set=step.value)
            return "settings"

        if step.kind == "general":
            if backend == "zapret2":
                strategy_id = step.value if step.value in zapret2_hub.STRATEGY_IDS else zapret2_hub.next_strategy_id(
                    str(getattr(settings, "zapret2_strategy_id", "balanced") or "balanced")
                )
                # Accept either strategy id or "zapret2|balanced" style.
                if "|" in strategy_id:
                    strategy_id = strategy_id.rsplit("|", 1)[-1]
                if strategy_id not in zapret2_hub.STRATEGY_IDS:
                    strategy_id = "balanced"
                self.context.settings.update(zapret2_strategy_id=strategy_id)
                zapret2_hub.write_hub_strategy_lua(configs, strategy_id)
                # winws2 hot-loads strategy Lua — do not request a process restart.
                return "strategy"
            self.context.settings.update(selected_zapret_general=step.value)
            return "settings"

        return "skip"

    def _rebuild_snapshot_only(self) -> None:
        try:
            self.context.merge.rebuild()
        except Exception as error:
            self._log("warning", "merge.rebuild failed", error=str(error))
        try:
            self.context.files._invalidate_collection_cache()
            self.context.files.rebuild_materialized_collections()
        except Exception:
            pass
        try:
            self.context.processes.rebuild_zapret_runtime_snapshot()
        except Exception:
            pass

    def _rebuild_and_maybe_restart(self, *, restart: bool) -> bool:
        self._rebuild_snapshot_only()
        if not restart:
            return False
        if self._abort_if_power_off("zapret") is not None:
            return False
        try:
            if self._zapret_running():
                self.context.processes.stop_component("zapret")
            if self._abort_if_power_off("zapret") is not None:
                return False
            state = self.context.processes.start_component("zapret")
            return bool(getattr(state, "status", "") == "running")
        except Exception:
            return False

    def _zapret_running(self) -> bool:
        try:
            states = {item.component_id: item for item in self.context.processes.list_states()}
            state = states.get("zapret")
            return bool(state and getattr(state, "status", "") == "running")
        except Exception:
            return False

    def _probe(self, targets: list[dict[str, str]]) -> list[ProbeResult]:
        normalized: list[dict[str, str]] = []
        for item in targets:
            value = str(item.get("value") or item.get("url") or item.get("host") or "").strip()
            if not value:
                continue
            normalized.append({"value": value})
        if not normalized:
            return []
        return self.signals.probe_targets(normalized, timeout_s=4.0, require_http=True)

    def probe_for_services(self, service_ids: list[str]) -> list[dict[str, str]]:
        targets: list[dict[str, str]] = []
        seen: set[str] = set()
        for service_id in service_ids:
            rule = SERVICE_RULES.get(service_id)
            if rule is None:
                continue
            for _name, value in rule.test_targets:
                key = value.strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                targets.append({"value": value})
        return targets
