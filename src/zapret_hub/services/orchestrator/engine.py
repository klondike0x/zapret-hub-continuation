from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Any, Callable

from zapret_hub.services.orchestrator.conflicts import ConflictDetector, describe_conflict
from zapret_hub.services.orchestrator.cutover import CutoverManager
from zapret_hub.services.orchestrator.learner import HostlistLearner
from zapret_hub.services.orchestrator.mapper import ServiceMapper
from zapret_hub.services.orchestrator.memory import WorkingMemory
from zapret_hub.services.orchestrator.noise import (
    IDE_PROCESS_TOKENS,
    cdn_family_key,
    exe_basename,
    filter_learnable_hosts,
    is_browser_process,
    is_infra_noise_host,
    is_noise_process,
)
from zapret_hub.services.orchestrator.signals import SignalCollector, classify_failure, is_interesting_udp_port
from zapret_hub.services.orchestrator.tuner import SmartTuner
from zapret_hub.services.service_catalog import SERVICE_PRESETS
from zapret_hub.services.service_rules import (
    SERVICE_RULES,
    health_hosts_for,
    merge_auto_default_services,
)


OrchestratorStatus = str  # "idle" | "tuning" | "ok"

_STATUS_TEXT = {
    ("manual", "idle"): ("Вручную", "Manual"),
    ("manual", "tuning"): ("Вручную", "Manual"),
    ("manual", "ok"): ("Вручную", "Manual"),
    ("auto", "idle"): ("Авто · ожидание", "Auto · idle"),
    ("auto", "tuning"): ("Подбираю конфигурацию…", "Tuning configuration…"),
    ("auto", "ok"): ("Авто · работает", "Auto · running"),
}

_LONG_TUNE_S = 30.0
_FAIL_THRESHOLD = 2
_PROCESS_FAIL_THRESHOLD = 1  # SYN_SENT from a known app is enough
_BROWSER_FAIL_THRESHOLD = 4  # browsers flap SYN_SENT constantly — need stronger confirm
_SCAN_INTERVAL_S = 4.0
_MAX_STEPS = 12
_EXHAUSTED_COOLDOWN_S = 1800.0  # 30m — stop endless general retries on the same host
_BROWSER_COOLDOWN_S = 3600.0  # after a failed browser tune, stay quiet
_SERVICE_ACTIVATION_TTL_S = 1800.0
_SYN_SENT_MIN_AGE_HINT = 2  # require repeated fails; SYN_SENT alone is normal
_SCAN_SAMPLE_LIMIT = 200

# Back-compat alias for tests / callers that referenced the old constant.
_NOISE_PROCESS_TOKENS = IDE_PROCESS_TOKENS

_STEP_PHASES: tuple[tuple[str, frozenset[str]], ...] = (
    ("services", frozenset({"enable_service"})),
    ("network", frozenset({"gaming_set", "game_filter", "ipset"})),
    ("lists", frozenset({"add_domain", "add_ip", "exclude_domain"})),
    ("strategy", frozenset({"general"})),
)
_PHASE_LABELS = {
    "services": ("сервисы", "services"),
    "user_mods": ("пользовательские модификации", "custom modifications"),
    "network": ("TCP/UDP", "TCP/UDP"),
    "lists": ("домены и IP", "domains and IPs"),
    "strategy": ("стратегия", "strategy"),
    "fallback": ("дополнительная проверка", "additional check"),
}


def _exe_label(process: str) -> str:
    """Short exe name for status (no IPs/domains/CIDRs)."""
    raw = str(process or "").strip()
    if not raw:
        return ""
    name = Path(raw.replace("\\", "/")).name
    return name[:48]


def _collapse_ip_batch(ips: list[str]) -> list[str]:
    """If many peers share a /24, keep the /24 once instead of N singles."""
    import ipaddress
    from collections import defaultdict

    buckets: dict[str, list[str]] = defaultdict(list)
    other: list[str] = []
    for raw in ips:
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            addr = ipaddress.ip_address(text)
            if addr.version != 4:
                other.append(text)
                continue
            net = str(ipaddress.ip_network(f"{text}/24", strict=False))
            buckets[net].append(text)
        except ValueError:
            other.append(text)
    out: list[str] = []
    for net, members in buckets.items():
        if len(members) >= 3:
            out.append(net)
        else:
            out.extend(members)
    out.extend(other)
    return list(dict.fromkeys(out))


class OrchestratorEngine:
    """Background Auto-mode loop: incidents → classify → tuner → batched cutover → knowledge."""

    def __init__(
        self,
        *,
        on_status: Callable[[dict[str, Any]], None] | None = None,
        language: Callable[[], str] | None = None,
    ) -> None:
        self.context: Any | None = None
        self._on_status = on_status
        self._on_notify: Callable[[str, str, str], None] | None = None
        self._on_toast: Callable[[str, str], None] | None = None
        self._on_conflict: Callable[[dict[str, Any]], None] | None = None
        self._on_long_pick: Callable[[dict[str, Any]], None] | None = None
        self._language = language or (lambda: "ru")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._mode = "manual"
        self._status: OrchestratorStatus = "idle"
        self._detail = ""
        self._zapret_active = False
        self._min_incident_interval_s = 20.0
        self._last_incident_at = 0.0
        self._loop_interval_s = 1.0
        self._last_scan_at = 0.0
        self._mapper = ServiceMapper()
        self._signals = SignalCollector()
        self._tuner = SmartTuner()
        self._memory = WorkingMemory()
        self._conflicts = ConflictDetector()
        self._cutover: CutoverManager | None = None
        self._busy = False

    def _log(self, level: str, message: str, **fields: Any) -> None:
        if self.context is None:
            return
        logging = getattr(self.context, "logging", None)
        if logging is None:
            return
        try:
            logging.log(level, message, **fields)
        except Exception:
            pass

    def attach(self, context: Any) -> None:
        self.context = context
        knowledge = getattr(context, "knowledge", None)
        self._cutover = CutoverManager(context, knowledge=knowledge, signals=self._signals)
        try:
            settings = context.settings.get()
            backend = self._active_backend(settings)
            mode = self._configured_mode(settings, backend)
        except Exception:
            mode = "manual"
        with self._lock:
            self._mode = "auto" if mode == "auto" else "manual"
            self._status = "idle"
        try:
            self._mapper = ServiceMapper()
        except Exception:
            pass
        self._reload_learned_conflicts()
        # Every attach: verify Auto never left service hosts in battle excludes.
        try:
            self.ensure_service_guards()
        except Exception:
            pass

    def ensure_service_guards(self) -> dict[str, Any]:
        """Re-check that Auto did not pollute immutable service catalogs / battle lists."""
        if self.context is None:
            return {"ok": False, "error": "no_context"}
        from zapret_hub.services.orchestrator.auto_overlay import ensure_auto_integrity

        configs = Path(self.context.paths.configs_dir)
        work_root = Path(self.context.paths.configs_dir).parent
        report = ensure_auto_integrity(configs, work_root=work_root)
        self._log("info", "Orchestrator service-guard check", **{str(k): report.get(k) for k in report})
        return {"ok": True, **report}

    def _reload_learned_conflicts(self) -> None:
        knowledge = getattr(self.context, "knowledge", None) if self.context else None
        if knowledge is None:
            return
        try:
            rows = knowledge.recent_conflicts(limit=80)
            self._conflicts.load_learned(rows)
        except Exception:
            pass

    @staticmethod
    def _active_backend(settings: Any) -> str:
        return "zapret2" if str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret") == "zapret2" else "zapret"

    @staticmethod
    def _configured_mode(settings: Any, backend: str) -> str:
        field = "zapret2_control_mode" if backend == "zapret2" else "zapret_control_mode"
        return "auto" if str(getattr(settings, field, "manual") or "manual") == "auto" else "manual"

    def set_mode(self, mode: str, *, backend: str | None = None) -> dict[str, Any]:
        """Set Auto/Manual for one bypass.

        Each bypass (zapret / zapret2) has its own control-mode flag. Automation
        never switches Quick Access between them — only the currently selected
        bypass is live-tuned; the other flag is stored for when the user selects it.
        """
        normalized = "auto" if str(mode or "").strip().lower() == "auto" else "manual"
        if self.context is None:
            with self._lock:
                self._mode = normalized
                if normalized == "manual":
                    self._status = "idle"
                    self._detail = ""
                    self._drain_queue()
            snapshot = self.status_snapshot()
            self._emit_status(snapshot)
            return snapshot

        settings = self.context.settings.get()
        active = self._active_backend(settings)
        target = str(backend or active)
        if target not in {"zapret", "zapret2"}:
            target = active

        field = "zapret2_control_mode" if target == "zapret2" else "zapret_control_mode"
        updates: dict[str, Any] = {field: normalized}

        # Inactive bypass: persist its Auto flag only — do not touch live engine.
        if target != active:
            try:
                self.context.settings.update(**updates)
            except Exception:
                pass
            snapshot = self.status_snapshot()
            self._emit_status(snapshot)
            return snapshot

        with self._lock:
            self._mode = normalized
            if normalized == "manual":
                self._status = "idle"
                self._detail = ""
                self._drain_queue()

        try:
            if normalized == "auto":
                before_services = {str(item) for item in (settings.selected_service_ids or [])}
                merged = merge_auto_default_services(settings.selected_service_ids)
                updates["selected_service_ids"] = merged
                if "gaming" in merged and "gaming" not in before_services:
                    if str(settings.zapret_game_filter_mode or "disabled") == "disabled":
                        updates["zapret_game_filter_mode"] = "tcpudp"
                self.context.settings.update(**updates)
                self._seed_auto_services(merged)
            else:
                self.context.settings.update(**updates)
        except Exception:
            try:
                self.context.settings.update(**{field: normalized})
            except Exception:
                pass

        self.sync_lifecycle(zapret_active=self._zapret_active)
        snapshot = self.status_snapshot()
        self._emit_status(snapshot)
        return snapshot

    def _seed_auto_services(self, service_ids: list[str]) -> None:
        """Overlay-only seed when entering Auto.

        Classic Zapret already materializes stock service hostlists on start.
        Dumping Cloudflare/gaming CIDRs into ipset-all-user here is what breaks
        Discord the moment the user switches Manual → Auto.
        """
        if self.context is None or not service_ids:
            return
        try:
            from zapret_hub.services.orchestrator import zapret2_hub
            from zapret_hub.services.orchestrator.auto_overlay import AutoOverlayStore

            configs = Path(self.context.paths.configs_dir)
            settings = self.context.settings.get()
            backend = self._active_backend(settings)
            if backend == "zapret2":
                # Zapret2 hub lists are separate; seed domains + curated nets there.
                zapret2_hub.seed_service_lists(configs, list(service_ids), only_missing=True)
            else:
                # Classic: domains-only into Auto overlay (never battle user lists).
                store = AutoOverlayStore(configs)
                domains = zapret2_hub.harvest_service_domains(list(service_ids))
                if domains:
                    store.add_domains(domains, reason="seed_auto_services")
                try:
                    zapret2_hub.sanitize_classic_discord_pollution(configs)
                except Exception:
                    pass
        except Exception as error:
            self._log("warning", "Failed to seed Auto default services", error=str(error))

    def reset_auto_cache(self) -> dict[str, Any]:
        """Clear Auto overlay + knowledge so learning starts fresh. Battle lists stay intact."""
        result: dict[str, Any] = {"ok": True, "overlay": False, "knowledge": False, "memory": False}
        if self.context is None:
            result["ok"] = False
            result["error"] = "no_context"
            return result
        try:
            from zapret_hub.services.orchestrator.auto_overlay import (
                AutoOverlayStore,
                migrate_legacy_markers_into_overlay,
            )

            configs = Path(self.context.paths.configs_dir)
            try:
                migrate_legacy_markers_into_overlay(configs)
            except Exception:
                pass
            AutoOverlayStore(configs).clear()
            result["overlay"] = True
            try:
                from zapret_hub.services.orchestrator.auto_overlay import ensure_auto_integrity

                ensure_auto_integrity(configs, work_root=Path(self.context.paths.configs_dir).parent)
                result["battle_scrub"] = True
            except Exception:
                pass
        except Exception as error:
            result["ok"] = False
            result["error"] = str(error)
        try:
            knowledge = getattr(self.context, "knowledge", None)
            if knowledge is not None:
                knowledge.clear()
                result["knowledge"] = True
        except Exception:
            pass
        try:
            self._memory.clear()
            self._memory.clear_tuning_started()
            result["memory"] = True
        except Exception:
            pass
        try:
            self.set_status("idle", detail="auto_cache_reset")
        except Exception:
            pass
        snapshot = self.status_snapshot()
        self._emit_status(snapshot)
        result["status"] = snapshot
        return result

    def get_mode(self) -> str:
        with self._lock:
            return self._mode

    def sync_lifecycle(self, *, zapret_active: bool) -> dict[str, Any]:
        if self.context is not None:
            try:
                settings = self.context.settings.get()
                configured = self._configured_mode(settings, self._active_backend(settings))
                with self._lock:
                    if configured != self._mode:
                        self._mode = configured
                        if configured == "manual":
                            self._status = "idle"
                            self._detail = ""
                            self._drain_queue()
            except Exception:
                pass
        with self._lock:
            self._zapret_active = bool(zapret_active)
            should_run = self._mode == "auto" and self._zapret_active
        if should_run:
            try:
                self.ensure_service_guards()
            except Exception:
                pass
            self.start()
            with self._lock:
                if self._status == "idle":
                    self._status = "ok"
        else:
            # Power-off must halt Auto even mid-tuning — otherwise cutover restarts Zapret.
            self.stop(clear_tuning=True)
            with self._lock:
                if not self._zapret_active or self._mode != "auto":
                    self._status = "idle"
                    self._detail = ""
        return self.status_snapshot()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="zapret-hub-orchestrator",
                daemon=True,
            )
            self._thread.start()
            if self._status == "idle" and self._mode == "auto":
                self._status = "ok"

    def stop(self, *, clear_tuning: bool = False) -> None:
        thread: threading.Thread | None
        with self._lock:
            thread = self._thread
            self._stop.set()
            self._thread = None
            if clear_tuning or self._mode != "auto":
                self._status = "idle"
                self._detail = ""
                self._busy = False
                self._drain_queue()
                try:
                    self._memory.clear_tuning_started()
                except Exception:
                    pass
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def is_live(self) -> bool:
        """True while Auto may mutate the selected bypass (power must stay on)."""
        with self._lock:
            return self._mode == "auto" and self._zapret_active and not self._stop.is_set()

    def enqueue(self, incident: dict[str, Any]) -> bool:
        now = time.monotonic()
        with self._lock:
            if self._mode != "auto":
                return False
            if (now - self._last_incident_at) < self._min_incident_interval_s:
                return False
            self._last_incident_at = now
        self._queue.put(dict(incident))
        return True

    def set_status(self, status: OrchestratorStatus, *, detail: str = "") -> dict[str, Any]:
        normalized = status if status in {"idle", "tuning", "ok"} else "idle"
        with self._lock:
            self._status = normalized
            self._detail = str(detail or "")
        snapshot = self.status_snapshot()
        self._emit_status(snapshot)
        return snapshot

    def status_snapshot(self) -> dict[str, Any]:
        with self._lock:
            mode = self._mode
            status = self._status
            detail = self._detail
            running = self._thread is not None and self._thread.is_alive()
            zapret_active = self._zapret_active
        language = str(self._language() or "ru").lower()
        ru_text, en_text = _STATUS_TEXT.get((mode, status), ("—", "—"))
        status_text = ru_text if language.startswith("ru") else en_text
        backend = "zapret"
        try:
            if self.context is not None:
                backend = (
                    "zapret2"
                    if str(self.context.settings.get().selected_runtime_mode or "") == "zapret2"
                    else "zapret"
                )
        except Exception:
            backend = "zapret"
        if mode == "auto" and backend == "zapret2":
            status_text = (
                status_text.replace("Авто", "Авто · Zapret 2")
                if language.startswith("ru")
                else status_text.replace("Auto", "Auto · Zapret 2")
            )
        if detail and mode == "auto" and status == "tuning":
            status_text = f"{status_text}: {detail}"
        return {
            "mode": mode,
            "status": status,
            "statusText": status_text,
            "detail": detail,
            "isAuto": mode == "auto",
            "running": running,
            "zapretActive": zapret_active,
            "backend": backend,
        }

    def run_bootstrap(self, *, youtube: bool = True, discord: bool = True) -> dict[str, Any]:
        if self.context is None:
            return {"ok": False, "error": "no_context"}
        settings = self.context.settings.get()
        runtime = str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret")
        self.set_mode("auto", backend="zapret2" if runtime == "zapret2" else "zapret")
        knowledge = getattr(self.context, "knowledge", None)
        cutover = self._cutover or CutoverManager(self.context, knowledge=knowledge, signals=self._signals)
        self._cutover = cutover

        settings = self.context.settings.get()
        trusted_existing = str(getattr(settings, "trusted_general", "") or "").strip()
        strategy_existing = str(getattr(settings, "zapret2_strategy_id", "balanced") or "balanced")
        already_ready = bool(getattr(settings, "general_autotest_done", False)) and (
            bool(trusted_existing) if runtime != "zapret2" else True
        )

        selected = {str(item) for item in (settings.selected_service_ids or [])}
        if youtube:
            selected.add("youtube")
        if discord:
            selected.add("discord")
        ordered = [preset.id for preset in SERVICE_PRESETS if preset.id in selected]

        # Resume path: keep accumulated lists/strategy/general — only ensure services + soft start.
        if already_ready:
            self.set_status("tuning", detail="resume")
            try:
                enabled = {str(item) for item in (settings.enabled_component_ids or [])}
                if runtime == "zapret2":
                    enabled.add("zapret2")
                    from zapret_hub.services.orchestrator import zapret2_hub

                    zapret2_hub.seed_service_lists(
                        Path(self.context.paths.configs_dir),
                        ordered,
                        only_missing=True,
                    )
                else:
                    enabled.add("zapret")
                    # Classic: append missing harvested domains once, never wipe.
                    from zapret_hub.services.orchestrator import zapret2_hub

                    learner = HostlistLearner(Path(self.context.paths.configs_dir))
                    for sid in ordered:
                        if sid not in {"youtube", "discord"}:
                            continue
                        for host in zapret2_hub.harvest_service_domains([sid]):
                            if not learner.domain_in_merged_lists(host, [Path(self.context.paths.configs_dir)]):
                                learner.add_domains([host])
                        learner.add_ips(zapret2_hub.harvest_service_ips([sid]))
                changes: dict[str, Any] = {
                    ("zapret2_control_mode" if runtime == "zapret2" else "zapret_control_mode"): "auto",
                    "selected_service_ids": ordered,
                    "enabled_component_ids": sorted(enabled),
                }
                # Preserve current runtime — do not force classic zapret.
                self.context.settings.update(**changes)
                if runtime == "zapret2":
                    try:
                        running = any(
                            getattr(s, "component_id", "") == "zapret2" and getattr(s, "status", "") == "running"
                            for s in self.context.processes.list_states()
                        )
                        if running:
                            # winws2 hot-loads lists/strategy — do not kill the live process.
                            from zapret_hub.services.orchestrator import zapret2_hub

                            configs = Path(self.context.paths.configs_dir)
                            auto_root = Path(self.context.paths.runtime_dir) / "zapret2" / "lists_auto"
                            zapret2_hub.materialize_auto_lists(configs, auto_root)
                            strategy_id = str(getattr(self.context.settings.get(), "zapret2_strategy_id", "balanced") or "balanced")
                            zapret2_hub.write_hub_strategy_lua(configs, strategy_id)
                        else:
                            self.context.processes.start_component("zapret2")
                    except Exception as error:
                        self._log("warning", "Resume zapret2 hot-reload/start failed", error=str(error))
                else:
                    try:
                        self.context.merge.rebuild()
                        self.context.files._invalidate_collection_cache()
                        self.context.files.rebuild_materialized_collections()
                        self.context.processes.rebuild_zapret_runtime_snapshot()
                        running = any(
                            getattr(s, "component_id", "") == "zapret" and getattr(s, "status", "") == "running"
                            for s in self.context.processes.list_states()
                        )
                        if running and hasattr(self.context.processes, "seamless_restart_zapret"):
                            self.context.processes.seamless_restart_zapret()
                        elif running and hasattr(self.context.processes, "hot_replace_zapret_runtime"):
                            slot = self.context.processes.stage_zapret_candidate_runtime()
                            self.context.processes.hot_replace_zapret_runtime(slot)
                        else:
                            self.context.processes.start_component("zapret")
                    except Exception as error:
                        self._log("warning", "Resume zapret rebuild/restart failed", error=str(error))
                cutover.snapshot()
                self._zapret_active = True
                self.set_status("ok")
                self.sync_lifecycle(zapret_active=True)
                return {
                    "ok": True,
                    "resumed": True,
                    "mode": "auto",
                    "backend": runtime if runtime in {"zapret", "zapret2"} else "zapret",
                    "trustedGeneral": trusted_existing or strategy_existing,
                    "services": ordered,
                }
            except Exception as error:
                self.set_status("ok")
                self._log("error", "Bootstrap resume failed", error=str(error))
                return {"ok": False, "error": str(error), "mode": "auto", "resumed": False}

        self.set_status("tuning", detail="YouTube / Discord" if (youtube or discord) else "bootstrap")
        cutover.snapshot()

        try:
            enabled = {str(item) for item in (settings.enabled_component_ids or [])}
            if runtime == "zapret2":
                enabled.add("zapret2")
                from zapret_hub.services.orchestrator import zapret2_hub

                self.context.settings.update(
                    zapret2_control_mode="auto",
                    selected_service_ids=ordered,
                    enabled_component_ids=sorted(enabled),
                    general_autotest_done=True,
                    zapret2_strategy_id=strategy_existing or "balanced",
                )
                zapret2_hub.seed_service_lists(
                    Path(self.context.paths.configs_dir), ordered, only_missing=True
                )
                zapret2_hub.write_hub_strategy_lua(
                    Path(self.context.paths.configs_dir), strategy_existing or "balanced"
                )
                try:
                    self.context.processes.start_component("zapret2")
                except Exception as error:
                    self.set_status("ok")
                    return {"ok": False, "error": str(error), "mode": "auto", "backend": "zapret2"}
                if knowledge is not None:
                    try:
                        knowledge.set_winner(
                            "bootstrap",
                            {
                                "general": strategy_existing or "balanced",
                                "services": ["youtube", "discord"],
                                "score": 10.0,
                                "symptom": "bootstrap",
                                "backend": "zapret2",
                            },
                        )
                    except Exception:
                        pass
                self._zapret_active = True
                self.set_status("ok")
                self.sync_lifecycle(zapret_active=True)
                return {
                    "ok": True,
                    "mode": "auto",
                    "backend": "zapret2",
                    "trustedGeneral": strategy_existing or "balanced",
                    "services": ordered,
                }

            enabled.add("zapret")
            self.context.settings.update(
                zapret_control_mode="auto",
                selected_service_ids=ordered,
                enabled_component_ids=sorted(enabled),
                # Keep user's runtime if already zapret; only default when empty/none.
                selected_runtime_mode="zapret" if runtime in {"", "none", "zapret"} else runtime,
            )
            try:
                self.context.merge.rebuild()
                self.context.files._invalidate_collection_cache()
                self.context.files.rebuild_materialized_collections()
                self.context.processes.rebuild_zapret_runtime_snapshot()
            except Exception as error:
                self._log("warning", "Bootstrap pre-merge failed", error=str(error))

            # First-time classic: seed YT/Discord catalogs before diagnostics.
            from zapret_hub.services.orchestrator import zapret2_hub

            learner = HostlistLearner(Path(self.context.paths.configs_dir))
            learner.add_domains(zapret2_hub.harvest_service_domains(ordered))
            learner.add_ips(zapret2_hub.harvest_service_ips(ordered))

            chosen: dict[str, Any] | None = None
            diag_error = ""
            try:
                results = self.context.processes.run_general_diagnostics(
                    progress_callback=lambda current, total, name: self.set_status(
                        "tuning",
                        detail=str(name or "").split(" - ", 1)[0][:48],
                    ),
                    # Do not tie diagnostics to orchestrator._stop / mode flips — that
                    # aborted the scan immediately after setMode/sync_lifecycle races.
                    stop_callback=None,
                )
                candidates = [item for item in results if isinstance(item, dict) and item.get("id")]
                chosen = next((item for item in candidates if item.get("status") == "ok"), None)
                if chosen is None and candidates:
                    # Prefer any scored candidate over total failure.
                    chosen = candidates[0]
            except Exception as error:
                diag_error = str(error)
                self._log("error", "Bootstrap diagnostics failed", error=diag_error)

            if chosen is None:
                # Soft path: enable Auto with the first available general and let the
                # orchestrator keep tuning in the background. Hard-failing onboarding
                # every time probes miss is worse UX than a deferred handoff.
                generals = []
                try:
                    generals = self.context.processes.list_zapret_generals()
                except Exception:
                    generals = []
                fallback_id = str(trusted_existing or "").strip()
                if not fallback_id and generals:
                    fallback_id = str(generals[0].get("id") or "").strip()
                return self._bootstrap_deferred(
                    ordered=ordered,
                    trusted=fallback_id,
                    reason=diag_error or "no_working_general",
                )

            trusted = str(chosen.get("id") or "")
            self.context.settings.update(
                selected_zapret_general=trusted,
                trusted_general=trusted,
                zapret_ipset_mode=str(chosen.get("ipset_mode") or settings.zapret_ipset_mode or "loaded"),
                zapret_game_filter_mode=str(
                    chosen.get("game_mode") or settings.zapret_game_filter_mode or "disabled"
                ),
                general_autotest_done=True,
            )

            probe_services = [sid for sid in ("youtube", "discord") if sid in selected]
            probe_targets = cutover.probe_for_services(probe_services)
            required_hosts: list[str] = []
            if youtube:
                for host in health_hosts_for("youtube") or ("redirector.googlevideo.com", "www.youtube.com"):
                    if host not in required_hosts:
                        required_hosts.append(host)
                if not any("youtube" in str(t.get("value", "")).lower() or "googlevideo" in str(t.get("value", "")).lower() for t in probe_targets):
                    probe_targets.append({"value": "https://redirector.googlevideo.com/"})
                    probe_targets.append({"value": "https://www.youtube.com/"})
            if discord:
                for host in health_hosts_for("discord") or ("updates.discord.com", "discord.com"):
                    if host not in required_hosts:
                        required_hosts.append(host)
                if not any("discord" in str(t.get("value", "")).lower() for t in probe_targets):
                    probe_targets.append({"value": "https://updates.discord.com/"})
                    probe_targets.append({"value": "https://discord.com/"})

            apply_result = cutover.apply_and_start_trusted(
                general_id=trusted,
                probe_targets=probe_targets,
                required_hosts=required_hosts,
            )
            if not apply_result.get("ok"):
                self._log("warning", "Bootstrap apply/probe soft-deferred", error=str(apply_result.get("error") or ""))
                return self._bootstrap_deferred(
                    ordered=ordered,
                    trusted=trusted,
                    reason=str(apply_result.get("error") or "apply_failed"),
                )

            if knowledge is not None:
                try:
                    knowledge.record_situation(
                        {"kind": "bootstrap", "services": ordered, "general": trusted, "ok": True}
                    )
                    knowledge.set_winner(
                        "bootstrap",
                        {
                            "general": trusted,
                            "ipset": str(self.context.settings.get().zapret_ipset_mode or "loaded"),
                            "services": ["youtube", "discord"],
                            "score": 10.0,
                            "symptom": "bootstrap",
                        },
                    )
                except Exception:
                    pass

            self._zapret_active = True
            self.set_status("ok")
            self.sync_lifecycle(zapret_active=True)
            return {
                "ok": True,
                "mode": "auto",
                "backend": "zapret",
                "trustedGeneral": trusted,
                "services": ordered,
                "ipset": str(self.context.settings.get().zapret_ipset_mode or "loaded"),
            }
        except Exception as error:
            self._log("error", "Bootstrap failed", error=str(error))
            try:
                ordered_fallback = [preset.id for preset in SERVICE_PRESETS if preset.id in {"youtube", "discord"}]
                return self._bootstrap_deferred(
                    ordered=ordered_fallback,
                    trusted=str(getattr(self.context.settings.get(), "trusted_general", "") or ""),
                    reason=str(error),
                )
            except Exception:
                self.set_status("ok")
                return {"ok": False, "error": str(error), "mode": "auto"}

    def _bootstrap_deferred(
        self,
        *,
        ordered: list[str],
        trusted: str,
        reason: str,
    ) -> dict[str, Any]:
        """Enable Auto even when probes/diagnostics did not fully finish."""
        trusted = str(trusted or "").strip()
        try:
            enabled = {str(item) for item in (self.context.settings.get().enabled_component_ids or [])}
            enabled.add("zapret")
            changes: dict[str, Any] = {
                "zapret_control_mode": "auto",
                "selected_service_ids": ordered,
                "enabled_component_ids": sorted(enabled),
                "selected_runtime_mode": "zapret",
            }
            if trusted:
                changes["selected_zapret_general"] = trusted
                changes["trusted_general"] = trusted
                # Leave autotest_done False so the live orchestrator can keep searching.
                changes["general_autotest_done"] = False
            self.context.settings.update(**changes)
            try:
                self.context.merge.rebuild()
                self.context.files._invalidate_collection_cache()
                self.context.files.rebuild_materialized_collections()
                self.context.processes.rebuild_zapret_runtime_snapshot()
            except Exception as error:
                self._log("warning", "Deferred bootstrap merge failed", error=str(error))
            try:
                self.context.processes.start_component("zapret")
            except Exception as error:
                self._log("warning", "Deferred bootstrap start failed", error=str(error))
            if self._cutover is not None:
                try:
                    self._cutover.snapshot()
                except Exception:
                    pass
            self._zapret_active = True
            self.set_status("ok")
            self.sync_lifecycle(zapret_active=True)
            return {
                "ok": True,
                "deferred": True,
                "reason": reason,
                "mode": "auto",
                "backend": "zapret",
                "trustedGeneral": trusted,
                "services": ordered,
            }
        except Exception as error:
            self.set_status("ok")
            self._log("error", "Deferred bootstrap failed", error=str(error))
            return {"ok": False, "error": str(error), "mode": "auto", "deferred": False}
    def _loop(self) -> None:
        while not self._stop.is_set():
            incident: dict[str, Any] | None = None
            try:
                incident = self._queue.get(timeout=self._loop_interval_s)
            except queue.Empty:
                incident = None
            if self._stop.is_set():
                break
            if incident is not None:
                self._handle_incident(incident)
                continue
            now = time.monotonic()
            if self._mode == "auto" and self._zapret_active and not self._busy:
                try:
                    cutover = self._ensure_cutover()
                    if cutover.has_deferred_list_restart():
                        flushed = cutover.flush_deferred_list_restart()
                        if flushed is not None:
                            self._log(
                                "info",
                                "Orchestrator deferred list restart flushed",
                                ok=bool(flushed.get("ok")),
                                restarted=bool(flushed.get("restarted")),
                                error=str(flushed.get("error") or ""),
                            )
                except Exception as error:
                    self._log("warning", "Orchestrator deferred list flush failed", error=str(error))
            if (now - self._last_scan_at) >= _SCAN_INTERVAL_S:
                self._last_scan_at = now
                if self._mode == "auto" and self._zapret_active and not self._busy:
                    try:
                        self._passive_scan()
                    except Exception as error:
                        self._log("warning", "Orchestrator scan failed", error=str(error))
            self._maybe_long_tune_notify()

    def _passive_scan(self) -> None:
        if self.context is None:
            return
        knowledge = getattr(self.context, "knowledge", None)
        samples = self._signals.snapshot_connections(limit=_SCAN_SAMPLE_LIMIT)
        settings = self.context.settings.get()
        selected = {str(item) for item in (settings.selected_service_ids or [])}
        lists_dirs = self._list_dirs()
        learner = HostlistLearner(Path(self.context.paths.configs_dir))

        # Prefer real apps. Drop IDE/browser noise unless the process itself maps
        # to a selected service (e.g. Discord Update.exe). Domain/IP maps from
        # Edge→Akamai must never promote a browser into the primary scan.
        filtered: list[Any] = []
        deferred_noise: list[Any] = []
        for sample in samples:
            process_services = {hit.service_id for hit in self._mapper.map_process(sample.process)}
            if is_noise_process(sample.process) and not process_services:
                # Pure browser/IDE traffic — only consider later, and never for service_detected.
                deferred_noise.append(sample)
                continue
            if is_noise_process(sample.process) and not (process_services & selected):
                deferred_noise.append(sample)
            else:
                filtered.append(sample)
        samples = [*filtered, *deferred_noise]

        # Group by process so one Discord launch → one batched incident (all hosts/IPs).
        by_process: dict[str, list[Any]] = {}
        for sample in samples:
            label = _exe_label(sample.process).lower() or f"pid:{int(getattr(sample, 'pid', 0) or 0)}"
            by_process.setdefault(label, []).append(sample)

        best: dict[str, Any] | None = None
        best_score = -1

        for _label, group in by_process.items():
            if self._stop.is_set() or self._mode != "auto":
                return
            process = str(group[0].process or "")
            process_is_noise = is_noise_process(process)
            process_is_browser = is_browser_process(process)
            process_services = [hit.service_id for hit in self._mapper.map_process(process)]
            if knowledge is not None and process_is_noise:
                exe = exe_basename(process)
                if knowledge.on_cooldown(f"process:{exe}") or knowledge.on_cooldown("browser-tune"):
                    continue

            domains: list[str] = []
            ips: list[str] = []
            services: list[str] = list(process_services)
            syn_count = 0
            udp_fail = 0
            primary_sample = group[0]
            probed_hosts: set[str] = set()

            for sample in group:
                state = (sample.state or "").upper()
                interesting_tcp = state in {"SYN_SENT", "SYN_RECEIVED"}
                interesting_udp = sample.proto == "udp" and is_interesting_udp_port(sample.remote_port)
                host = str(sample.domain or "").strip().lower().rstrip(".")
                # Browsers flap SYN_SENT to CDN PTRs constantly — ignore that signal.
                if process_is_noise and host and is_infra_noise_host(host):
                    interesting_tcp = False
                if interesting_tcp:
                    syn_count += 1
                    primary_sample = sample
                if interesting_udp:
                    udp_fail += 1
                    primary_sample = sample

                # Domain/IP evidence is useful for known apps; browsers must not
                # invent "epic-games" from an Akamai PTR and force activation.
                if not process_is_noise:
                    mapped = [
                        hit.service_id
                        for hit in self._mapper.map(
                            host=sample.domain,
                            ip=sample.remote_ip,
                            process=process,
                            use_dns=bool(sample.domain),
                        )
                    ]
                    for sid in mapped:
                        if sid not in services:
                            services.append(sid)

                if host and host not in domains and not is_infra_noise_host(host):
                    domains.append(host)
                elif host and host not in domains and not process_is_noise:
                    # Keep infra hosts for known apps (rare); browsers drop them.
                    domains.append(host)
                if sample.remote_ip and sample.remote_ip not in ips:
                    ips.append(sample.remote_ip)

            # Activate missing services ONLY from process evidence (Discord.exe etc.).
            # Never from Edge talking to a CDN that reverse-maps to epic-games.
            missing = [sid for sid in process_services if sid not in selected]
            if missing and not process_is_noise:
                activation_key = f"service-activation:{missing[0]}:{_exe_label(process).lower()}"
                if not self._memory.mark_notified(activation_key, ttl_s=_SERVICE_ACTIVATION_TTL_S):
                    continue
                self._log(
                    "info",
                    "Orchestrator detected an active service process",
                    process=process,
                    service=missing[0],
                    domains=len(domains),
                    ips=len(ips),
                )
                self._handle_incident(
                    {
                        "domain": domains[0] if domains else "",
                        "ip": ips[0] if ips else str(primary_sample.remote_ip or ""),
                        "process": process,
                        "proto": primary_sample.proto,
                        "remote_port": primary_sample.remote_port,
                        "services": missing,
                        "symptom": "service_detected",
                        "selected": list(selected),
                        "domains": domains,
                        "ips": ips,
                        "domains_missing": filter_learnable_hosts(
                            [host for host in domains if not learner.domain_in_merged_lists(host, lists_dirs)]
                        ),
                    }
                )
                return

            if process_is_noise and not process_services and not syn_count and not udp_fail:
                # Browser/IDE with only ESTABLISHED infra noise — nothing to fix.
                continue

            if not services and not syn_count and not udp_fail and not process_is_browser:
                continue

            # Service already selected — need real failure signals.
            failing = syn_count > 0 or udp_fail > 0
            # Process-driven probes: only check remotes THIS process is talking to
            # (not blind periodic discord.com polls). Cap to keep the scan cheap.
            if not failing and services and not process_is_noise:
                candidates = [h for h in domains if h and not is_infra_noise_host(h)][:4]
                if not candidates:
                    # Resolve a few IPs for process-owned remotes when DNS was empty.
                    for sample in group[:6]:
                        if sample.domain or not sample.remote_ip:
                            continue
                        if knowledge is not None and knowledge.is_dead_host(sample.remote_ip):
                            continue
                        ptr = ""
                        try:
                            ptr = self._mapper.reverse_dns(sample.remote_ip)
                        except Exception:
                            ptr = ""
                        if ptr and is_infra_noise_host(ptr):
                            continue
                        if ptr and ptr not in domains:
                            domains.append(ptr)
                            candidates.append(ptr)
                        if len(candidates) >= 3:
                            break
                for host in candidates:
                    if host in probed_hosts:
                        continue
                    probed_hosts.add(host)
                    if knowledge is not None and (
                        knowledge.is_dead_host(host) or knowledge.on_cooldown(f"host:{host}")
                    ):
                        continue
                    family = cdn_family_key(host)
                    if knowledge is not None and family and knowledge.on_cooldown(f"cdn:{family}"):
                        continue
                    result = self._signals.probe_host_access(host, timeout_s=2.5)
                    if result.ok:
                        self._memory.reset_fail(host)
                        continue
                    failing = True
                    primary_sample = next((s for s in group if (s.domain or "").lower().rstrip(".") == host), primary_sample)
                    in_lists = learner.domain_in_merged_lists(host, lists_dirs)
                    symptom = classify_failure(result, domain_in_lists=in_lists)
                    if symptom == "dead_host":
                        if knowledge is not None:
                            knowledge.mark_dead_host(host)
                        continue
                    threshold = _PROCESS_FAIL_THRESHOLD if process_services else _FAIL_THRESHOLD
                    if self._memory.bump_fail(host) < threshold:
                        continue
                    score = 100 + syn_count * 10 + len(domains) + (20 if set(services) & selected else 0)
                    incident = {
                        "domain": host,
                        "ip": str(primary_sample.remote_ip or ""),
                        "process": process,
                        "proto": "tcp",
                        "remote_port": int(primary_sample.remote_port or 443),
                        "services": services,
                        "symptom": symptom,
                        "selected": list(selected),
                        "domains": domains,
                        "ips": ips,
                        "domains_missing": filter_learnable_hosts(
                            [item for item in domains if not learner.domain_in_merged_lists(item, lists_dirs)]
                        ),
                    }
                    if score > best_score:
                        best_score = score
                        best = incident
                    break
                continue

            # Browsers: only act on learnable missing domains with sustained fails —
            # never escalate SYN_SENT alone into strategy thrash.
            if process_is_browser:
                learnable_missing = filter_learnable_hosts(
                    [host for host in domains if host and not learner.domain_in_merged_lists(host, lists_dirs)]
                )
                if not learnable_missing:
                    continue
                fail_key = learnable_missing[0]
                if self._memory.bump_fail(fail_key) < _BROWSER_FAIL_THRESHOLD:
                    continue
                if knowledge is not None and (
                    knowledge.is_dead_host(fail_key) or knowledge.on_cooldown(f"host:{fail_key}")
                ):
                    continue
                score = 40 + len(learnable_missing)
                incident = {
                    "domain": fail_key,
                    "ip": ips[0] if ips else str(primary_sample.remote_ip or ""),
                    "process": process,
                    "proto": primary_sample.proto,
                    "remote_port": primary_sample.remote_port,
                    "services": list(process_services) or list(services),
                    "symptom": "external_miss",
                    "selected": list(selected),
                    "domains": learnable_missing,
                    "ips": [],  # don't seed random CDN IPs from browser scans
                    "domains_missing": learnable_missing,
                }
                if score > best_score:
                    best_score = score
                    best = incident
                continue

            if not failing:
                continue

            # SYN_SENT / interesting UDP — trust the OS signal; do not wait for slow probes.
            # Known apps fire on the first failing scan; unknowns still need a short confirm.
            if not (process_services and syn_count >= 1):
                threshold = _PROCESS_FAIL_THRESHOLD if process_services else _FAIL_THRESHOLD
                fail_key = domains[0] if domains else (ips[0] if ips else _exe_label(process).lower())
                if self._memory.bump_fail(fail_key) < threshold:
                    continue

            symptom = "tcp_timeout" if syn_count else "external_miss"
            score = 80 + syn_count * 15 + udp_fail * 8 + len(domains) + len(ips)
            if set(services) & selected:
                score += 25
            # Prefer real apps over leftover IDE noise.
            if process_is_noise:
                score -= 50
            incident = {
                "domain": domains[0] if domains else "",
                "ip": ips[0] if ips else str(primary_sample.remote_ip or ""),
                "process": process,
                "proto": primary_sample.proto,
                "remote_port": primary_sample.remote_port,
                "services": services,
                "symptom": symptom,
                "selected": list(selected),
                "domains": domains,
                "ips": ips,
                "domains_missing": filter_learnable_hosts(
                    [host for host in domains if host and not learner.domain_in_merged_lists(host, lists_dirs)]
                ),
            }
            if score > best_score:
                best_score = score
                best = incident

        if best is None:
            return
        self._handle_incident(best)

    def _handle_incident(self, incident: dict[str, Any]) -> None:
        if self.context is None or self._mode != "auto":
            return
        if not self.is_live():
            return
        if self._busy:
            return
        self._busy = True
        knowledge = getattr(self.context, "knowledge", None)
        try:
            if not self.is_live():
                return
            domain = str(incident.get("domain") or "").strip().lower().rstrip(".")
            ip = str(incident.get("ip") or "").strip()
            domains = [
                str(item).strip().lower().rstrip(".")
                for item in (incident.get("domains") or [])
                if str(item).strip()
            ]
            ips = [str(item).strip() for item in (incident.get("ips") or []) if str(item).strip()]
            domains_missing = [
                str(item).strip().lower().rstrip(".")
                for item in (incident.get("domains_missing") or [])
                if str(item).strip()
            ]
            if domain and domain not in domains:
                domains.insert(0, domain)
            if ip and ip not in ips:
                ips.insert(0, ip)
            ips = _collapse_ip_batch(ips)
            process = str(incident.get("process") or "")
            proto = str(incident.get("proto") or "")
            remote_port = int(incident.get("remote_port") or 0)
            host_key = domain or ip or (domains[0] if domains else "") or (ips[0] if ips else "") or process.lower()
            if not host_key:
                return
            if is_infra_noise_host(host_key) and is_noise_process(process):
                # Never open a full tune on browser→CDN PTR noise.
                return
            if knowledge is not None and (
                knowledge.is_dead_host(host_key) or knowledge.on_cooldown(f"host:{host_key}")
            ):
                return
            family = cdn_family_key(host_key)
            if knowledge is not None and family and knowledge.on_cooldown(f"cdn:{family}"):
                return
            if knowledge is not None and is_noise_process(process):
                exe = exe_basename(process)
                if knowledge.on_cooldown(f"process:{exe}") or knowledge.on_cooldown("browser-tune"):
                    return

            domains = filter_learnable_hosts(domains) or ([domain] if domain and not is_infra_noise_host(domain) else [])
            domains_missing = filter_learnable_hosts(domains_missing)
            if domain and is_infra_noise_host(domain):
                domain = domains[0] if domains else ""
                host_key = domain or ip or process.lower()
                if not host_key:
                    return

            services = list(incident.get("services") or [])
            if not services:
                services = [
                    hit.service_id
                    for hit in self._mapper.map(host=domain, ip=ip, process=process, use_dns=True)
                ]

            settings = self.context.settings.get()
            selected = {str(item) for item in (settings.selected_service_ids or [])}
            enabled_mods = {str(item) for item in (getattr(settings, "enabled_mod_ids", None) or [])}
            current = {
                "general": str(settings.selected_zapret_general or ""),
                "ipset": str(settings.zapret_ipset_mode or "loaded"),
                "game_filter": str(settings.zapret_game_filter_mode or "disabled"),
                "gaming_set": str(getattr(settings, "zapret_gaming_set", "stun-wide-base") or "stun-wide-base"),
                "configs_dir": str(self.context.paths.configs_dir),
            }
            learner = HostlistLearner(Path(self.context.paths.configs_dir))
            lists_dirs = self._list_dirs()
            domain_in_merged = learner.domain_in_merged_lists(domain, lists_dirs) if domain else False
            if not domains_missing:
                domains_missing = [
                    item for item in domains if item and not learner.domain_in_merged_lists(item, lists_dirs)
                ]

            symptom = str(incident.get("symptom") or "")
            if not symptom:
                if domain:
                    probe = self._signals.probe_host_access(domain)
                    symptom = classify_failure(probe, domain_in_lists=domain_in_merged)
                    if symptom == "dead_host":
                        if knowledge is not None:
                            knowledge.mark_dead_host(domain)
                        return
                else:
                    symptom = "external_miss"

            known_conflict = self._conflicts.detect(
                process=process,
                current_gaming_set=str(current.get("gaming_set") or ""),
                proto=proto,
                remote_port=remote_port,
                symptom=symptom,
            )
            if known_conflict and symptom != "dead_host":
                app_key = str(known_conflict.get("app") or process or "app")
                if self._memory.mark_notified(f"conflict:{app_key}", ttl_s=600.0):
                    msg_ru = describe_conflict(known_conflict, language="ru")
                    msg_en = describe_conflict(known_conflict, language="en")
                    self._emit_conflict(
                        {
                            "messageRu": msg_ru,
                            "messageEn": msg_en,
                            "domain": domain,
                            "app": app_key,
                        }
                    )
                    if knowledge is not None:
                        try:
                            knowledge.record_conflict(known_conflict)
                        except Exception:
                            pass

            detail = _exe_label(process) or (services[0] if services else "подбор")
            self._memory.set_tuning_started()
            self.set_status("tuning", detail=detail)

            winner = None
            winner_symptom = ""
            winner_app = ""
            if knowledge is not None:
                # Prefer per-app profile so Discord vs YouTube (etc.) can switch cleanly.
                if process:
                    winner = knowledge.winner_for_app(process)
                if winner is None:
                    winner = knowledge.winner_for_host(host_key)
                if winner:
                    winner_symptom = str(winner.get("symptom") or "")
                    winner_app = str(winner.get("app") or "")
                if known_conflict:
                    stored = knowledge.find_conflict(str(known_conflict.get("app") or ""))
                    if stored:
                        known_conflict = {**known_conflict, **stored}

            ranked = knowledge.ranked_generals() if knowledge is not None else []
            trusted = str(getattr(settings, "trusted_general", "") or "")
            backend = (
                "zapret2"
                if str(getattr(settings, "selected_runtime_mode", "zapret") or "zapret") == "zapret2"
                else "zapret"
            )

            installed_mods: list[Any] = []
            mod_generals: list[dict[str, str]] = []
            if backend == "zapret2":
                from zapret_hub.services.orchestrator import zapret2_hub

                mod_generals = zapret2_hub.strategy_generals()
                trusted = str(getattr(settings, "zapret2_strategy_id", "balanced") or "balanced")
                current["general"] = trusted
                enabled_mods = {str(item) for item in (getattr(settings, "enabled_zapret2_mod_ids", None) or [])}
                try:
                    mods2 = getattr(self.context, "mods2", None)
                    if mods2 is not None:
                        installed_mods = list(mods2.list_installed())
                except Exception as error:
                    self._log("warning", "list_installed Zapret2 mods failed", error=str(error))
            else:
                try:
                    mods = getattr(self.context, "mods", None)
                    if mods is not None:
                        installed_mods = list(mods.list_installed())
                except Exception as error:
                    self._log("warning", "list_installed mods failed", error=str(error))
                try:
                    mod_generals = list(self.context.processes.list_zapret_generals())
                except Exception as error:
                    self._log("warning", "list_zapret_generals failed", error=str(error))
            installed_mods.sort(
                key=lambda item: (
                    str(getattr(item, "name", "") or getattr(item, "id", "") or "").lower(),
                )
            )

            steps = self._tuner.plan(
                symptom=symptom,
                domain=domain,
                ip=ip,
                process=process,
                proto=proto,
                service_ids=services,
                selected_services=selected,
                current=current,
                knowledge_winner=winner,
                known_conflict=known_conflict,
                ranked_generals=ranked,
                trusted_general=trusted,
                domain_in_merged=domain_in_merged,
                max_steps=_MAX_STEPS,
                winner_symptom=winner_symptom,
                winner_app=winner_app,
                installed_mods=installed_mods,
                mod_generals=mod_generals,
                enabled_mod_ids=enabled_mods,
                domains=domains,
                ips=ips,
                domains_missing=domains_missing,
            )
            if not steps:
                if knowledge is not None:
                    knowledge.set_cooldown(f"host:{host_key}", _EXHAUSTED_COOLDOWN_S)
                self.set_status("ok")
                self._memory.clear_tuning_started()
                return

            probe_targets, required_hosts = self._build_probe_gate(
                domain, ip, services, extra_domains=domains
            )
            cutover = self._ensure_cutover()
            # Keep status as «Подбираю конфигурацию…: Discord.exe» — not IPs/CIDRs/knobs.
            self.set_status("tuning", detail=detail)
            if not self.is_live():
                self.set_status("idle")
                self._memory.clear_tuning_started()
                return
            result: dict[str, Any] = {"ok": False, "applied": [], "error": "no_applicable_stage"}
            attempted_steps: list[Any] = []
            for phase, staged_steps in self._staged_plans(steps):
                if not self.is_live():
                    self.set_status("idle")
                    self._memory.clear_tuning_started()
                    return
                attempted_steps = staged_steps
                phase_labels = _PHASE_LABELS.get(phase, (phase, phase))
                phase_label = phase_labels[0] if self._language().lower().startswith("ru") else phase_labels[1]
                self.set_status("tuning", detail=f"{detail} · {phase_label}")
                self._log(
                    "info",
                    "Orchestrator trying staged plan",
                    host=host_key,
                    app=process,
                    phase=phase,
                    steps=len(staged_steps),
                )
                result = cutover.apply_plan(
                    staged_steps,
                    probe_targets=probe_targets,
                    required_hosts=required_hosts,
                )
                if result.get("ok"):
                    self._log(
                        "info",
                        "Orchestrator staged plan succeeded",
                        host=host_key,
                        app=process,
                        phase=phase,
                    )
                    break

            if knowledge is not None:
                try:
                    for step in attempted_steps:
                        knowledge.record_situation(
                            {
                                "host": host_key,
                                "step": step.kind,
                                "value": step.value,
                                "ok": bool(result.get("ok")),
                                "symptom": symptom,
                                "reason": step.reason,
                                "batched": True,
                            }
                        )
                    if not result.get("ok"):
                        for step in attempted_steps:
                            if step.kind == "general":
                                knowledge.rank_general(step.value, -1.0)
                except Exception as error:
                    self._log("warning", "Knowledge record failed", error=str(error))

            if result.get("ok"):
                self._memory.reset_fail(host_key)
                for item in domains:
                    self._memory.reset_fail(item)
                for item in ips:
                    self._memory.reset_fail(item)
                settings = self.context.settings.get()
                payload = {
                    "general": (
                        str(getattr(settings, "zapret2_strategy_id", "") or "")
                        if backend == "zapret2"
                        else str(settings.selected_zapret_general or "")
                    ),
                    "ipset": str(settings.zapret_ipset_mode or ""),
                    "game_filter": str(settings.zapret_game_filter_mode or ""),
                    "gaming_set": str(getattr(settings, "zapret_gaming_set", "") or ""),
                    "services": list(settings.selected_service_ids or []),
                    "mods": list(
                        (getattr(settings, "enabled_zapret2_mod_ids", None) or [])
                        if backend == "zapret2"
                        else (getattr(settings, "enabled_mod_ids", None) or [])
                    ),
                    "score": 3.0,
                    "symptom": symptom,
                    "app": process.lower() if process else "",
                    "backend": backend,
                }
                if knowledge is not None:
                    try:
                        knowledge.set_host_winner(host_key, payload)
                        for item in domains[:8]:
                            knowledge.set_host_winner(item, payload)
                        if process:
                            knowledge.set_app_winner(process, payload)
                        for step in result.get("applied") or []:
                            if step.get("kind") == "general":
                                knowledge.rank_general(str(step.get("value") or ""), 2.0)
                    except Exception as error:
                        self._log("warning", "Knowledge winner save failed", error=str(error))
            else:
                err = str(result.get("error") or "")
                if err in {"power_off", "runtime_mode_changed"}:
                    self.set_status("idle")
                    self._memory.clear_tuning_started()
                    return
                if knowledge is not None:
                    knowledge.set_cooldown(f"host:{host_key}", _EXHAUSTED_COOLDOWN_S)
                    for item in domains[:8]:
                        knowledge.set_cooldown(f"host:{item}", _EXHAUSTED_COOLDOWN_S)
                    family = cdn_family_key(host_key)
                    if family:
                        knowledge.set_cooldown(f"cdn:{family}", _EXHAUSTED_COOLDOWN_S)
                    if is_noise_process(process):
                        knowledge.set_cooldown(f"process:{exe_basename(process)}", _BROWSER_COOLDOWN_S)
                        knowledge.set_cooldown("browser-tune", _BROWSER_COOLDOWN_S)
                self._log("info", "Orchestrator plan failed", host=host_key, symptom=symptom, error=err)

            if not self.is_live():
                self.set_status("idle")
            else:
                self.set_status("ok")
            self._memory.clear_tuning_started()
        finally:
            self._busy = False

    def _build_probe_gate(
        self,
        domain: str,
        ip: str,
        services: list[str],
        *,
        extra_domains: list[str] | None = None,
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Incident-focused probes: prefer failing domain/service targets, not unrelated sites."""
        targets: list[dict[str, str]] = []
        required: list[str] = []
        for host in [domain, *(extra_domains or [])]:
            host = str(host or "").strip().lower().rstrip(".")
            if not host or is_infra_noise_host(host):
                continue
            targets.append({"value": f"https://{host}/"})
            targets.append({"value": host})
            if host not in required:
                required.append(host)
        for service_id in services:
            rule = SERVICE_RULES.get(service_id)
            if rule is None:
                continue
            for host in health_hosts_for(service_id)[:3]:
                if is_infra_noise_host(host):
                    continue
                targets.append({"value": f"https://{host}/"})
                if host not in required:
                    required.append(host)
            for _name, value in rule.test_targets[:4]:
                targets.append({"value": value})
                if not domain and "://" in value:
                    host = value.split("://", 1)[1].split("/", 1)[0].split(":", 1)[0]
                    if host and host not in required and not is_infra_noise_host(host):
                        required.append(host)
                elif not domain and value and not value.upper().startswith("PING:"):
                    if value not in required and not is_infra_noise_host(value):
                        required.append(value)
        if not required and ip:
            # IP-only gaming: require at least one service target if present; else soft-pass on any ok.
            pass
        # Dedupe targets
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for item in targets:
            key = item["value"].lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique[:10], required[:5]

    @staticmethod
    def _staged_plans(steps: list[Any]) -> list[tuple[str, list[Any]]]:
        """Build cumulative plans so a successful lower-cost layer stops escalation."""
        remaining = list(steps)
        cumulative: list[Any] = []
        plans: list[tuple[str, list[Any]]] = []
        consumed: set[int] = set()
        for phase in ("user_mods",):
            additions = [
                step
                for index, step in enumerate(remaining)
                if index not in consumed and step.kind == "enable_mod"
            ]
            if additions:
                # Services must always be tried before the modification layer.
                if not plans:
                    service_steps = [step for step in remaining if step.kind == "enable_service"]
                    if service_steps:
                        cumulative.extend(service_steps)
                        for index, step in enumerate(remaining):
                            if step.kind == "enable_service":
                                consumed.add(index)
                        plans.append(("services", list(cumulative)))
                for addition in additions:
                    cumulative.append(addition)
                    for index, step in enumerate(remaining):
                        if index not in consumed and step is addition:
                            consumed.add(index)
                            break
                    plans.append((phase, list(cumulative)))
        for phase, kinds in _STEP_PHASES:
            additions = [step for index, step in enumerate(remaining) if index not in consumed and step.kind in kinds]
            if not additions:
                continue
            for index, step in enumerate(remaining):
                if index not in consumed and step.kind in kinds:
                    consumed.add(index)
            if phase == "lists":
                cumulative.extend(additions)
                plans.append((phase, list(cumulative)))
                continue
            for addition in additions:
                # A second value for the same knob is an alternative, not
                # another mutation to batch on top of the first one.
                if phase != "services":
                    cumulative = [step for step in cumulative if step.kind != addition.kind]
                cumulative.append(addition)
                plans.append((phase, list(cumulative)))
        unknown = [step for index, step in enumerate(remaining) if index not in consumed]
        if unknown:
            cumulative.extend(unknown)
            plans.append(("fallback", list(cumulative)))
        return plans

    def _list_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        if self.context is None:
            return dirs
        configs = Path(self.context.paths.configs_dir)
        dirs.append(configs)
        active = getattr(self.context.processes, "_current_zapret_runtime", None)
        if active is not None:
            lists = Path(active) / "lists"
            if lists.exists():
                dirs.append(lists)
        visible = Path(self.context.paths.merged_runtime_dir) / "zapret" / "lists"
        if visible.exists():
            dirs.append(visible)
        return dirs

    def _ensure_cutover(self) -> CutoverManager:
        if self._cutover is None:
            knowledge = getattr(self.context, "knowledge", None) if self.context else None
            self._cutover = CutoverManager(self.context, knowledge=knowledge, signals=self._signals)
        return self._cutover

    def _maybe_long_tune_notify(self) -> None:
        with self._lock:
            if self._status != "tuning" or self._mode != "auto":
                return
            detail = self._detail
        started = self._memory.tuning_started_at()
        if not started:
            return
        if (time.monotonic() - started) < _LONG_TUNE_S:
            return
        if self._memory.long_tune_notified():
            return
        self._memory.set_long_tune_notified()
        target = detail or "сайту"
        msg_ru = (
            f"Подбор конфигурации занимает дольше обычного, пожалуйста, подождите — "
            f"доступ к {target} появится совсем скоро."
        )
        msg_en = (
            f"Configuration tuning is taking longer than usual — please wait, "
            f"access to {target} will be ready shortly."
        )
        self._emit_long_pick({"domain": target, "messageRu": msg_ru, "messageEn": msg_en})

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _emit_status(self, snapshot: dict[str, Any] | None = None) -> None:
        payload = snapshot if snapshot is not None else self.status_snapshot()
        callback = self._on_status
        if callback is None:
            return
        try:
            callback(payload)
        except Exception:
            pass

    def _emit_notify(self, level: str, message_ru: str, message_en: str) -> None:
        callback = self._on_notify
        if callback is None:
            return
        try:
            callback(level, message_ru, message_en)
        except Exception:
            pass

    def _emit_conflict(self, payload: dict[str, Any]) -> None:
        callback = self._on_conflict
        if callback is None:
            return
        try:
            callback(payload)
        except Exception:
            pass

    def _emit_long_pick(self, payload: dict[str, Any]) -> None:
        callback = self._on_long_pick
        if callback is None:
            return
        try:
            callback(payload)
        except Exception:
            pass

    def _emit_toast(self, message: str, kind: str = "info") -> None:
        callback = self._on_toast
        if callback is None:
            return
        try:
            callback(message, kind)
        except Exception:
            pass
