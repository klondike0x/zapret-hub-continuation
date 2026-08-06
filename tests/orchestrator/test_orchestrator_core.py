from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from zapret_hub.services.orchestrator.conflicts import ConflictDetector
from zapret_hub.services.orchestrator.cutover import CutoverManager
from zapret_hub.services.orchestrator.knowledge import KnowledgeStore
from zapret_hub.services.orchestrator.learner import HostlistLearner
from zapret_hub.services.orchestrator.mapper import ServiceMapper, map_target
from zapret_hub.services.orchestrator.signals import ConnSample, ProbeResult, classify_failure, probe_required_ok
from zapret_hub.services.orchestrator.tuner import SmartTuner, TunerStep


def test_classify_failure_matrix():
    assert classify_failure(
        ProbeResult(ok=False, target="x", latency_ms=1, error="getaddrinfo failed", cls="dns_fail"),
        domain_in_lists=False,
    ) == "dead_host"
    assert classify_failure(
        ProbeResult(ok=False, target="x", latency_ms=1, error="timed out", cls="tcp_timeout"),
        domain_in_lists=False,
    ) == "external_miss"
    assert classify_failure(
        ProbeResult(ok=False, target="x", latency_ms=1, error="timed out", cls="tcp_timeout"),
        domain_in_lists=True,
    ) == "tcp_timeout"
    assert classify_failure(
        ProbeResult(ok=False, target="x", latency_ms=1, error="ssl handshake", cls="tls_fail"),
        domain_in_lists=True,
    ) == "suspect_overblock"
    assert classify_failure(
        ProbeResult(ok=False, target="x", latency_ms=1, error="timed out", cls="tcp_timeout"),
        domain_in_lists=True,
    ) != "internal_conflict"


def test_probe_required_ok_incident_host():
    results = [
        ProbeResult(ok=True, target="https://discord.com/", latency_ms=10),
        ProbeResult(ok=False, target="https://www.youtube.com/", latency_ms=10, error="timeout"),
    ]
    assert probe_required_ok(results, required_hosts=["youtube.com"]) is False
    assert probe_required_ok(results, required_hosts=["discord.com"]) is True


def test_probe_required_ok_empty_required_is_strict():
    results = [
        ProbeResult(ok=True, target="https://a.com/", latency_ms=10),
        ProbeResult(ok=False, target="https://b.com/", latency_ms=10, error="timeout"),
    ]
    assert probe_required_ok(results, required_hosts=[]) is False
    assert probe_required_ok(
        [
            ProbeResult(ok=True, target="https://a.com/", latency_ms=10),
            ProbeResult(ok=True, target="https://b.com/", latency_ms=10),
        ],
        required_hosts=[],
    ) is True


def test_mapper_browsers_not_youtube():
    mapper = ServiceMapper()
    assert mapper.primary_service(process="chrome.exe") is None
    assert mapper.primary_service(process="msedge.exe") is None
    assert mapper.primary_service(process="firefox.exe") is None
    assert map_target(process="FortniteClient-Win64-Shipping.exe") == "fortnite"


def test_mapper_combines_process_and_domain_evidence():
    mapper = ServiceMapper()
    process_only = mapper.map(process="Discord.exe")[0]
    combined = mapper.map(process="Discord.exe", host="gateway.discord.gg", use_dns=False)[0]
    assert combined.service_id == "discord"
    assert combined.score > process_only.score


def test_mapper_discord_update_exe_path():
    mapper = ServiceMapper()
    hits = mapper.map_process(r"C:\Users\User\AppData\Local\Discord\Update.exe")
    assert hits and hits[0].service_id == "discord"


def test_mapper_warframe_process_and_domain():
    mapper = ServiceMapper()
    process = mapper.map_process(r"D:\\Games\\Warframe\\Warframe.x64.exe")
    domain = mapper.map_domain("api.warframe.com")
    assert process and process[0].service_id == "warframe"
    assert domain and domain[0].service_id == "warframe"


def test_mapper_spotify_updater_path():
    mapper = ServiceMapper()
    hits = mapper.map_process(r"C:\Users\User\AppData\Roaming\Spotify\Update.exe")
    assert hits and hits[0].service_id == "spotify"


def test_mapper_discord_ip_beats_cloudflare():
    mapper = ServiceMapper()
    hits = mapper.map(ip="162.159.135.232", use_dns=False)
    assert hits
    assert hits[0].service_id == "discord"


def test_health_hosts_prefer_critical_paths():
    from zapret_hub.services.service_rules import health_hosts_for, merge_auto_default_services

    assert health_hosts_for("discord")[0] == "updates.discord.com"
    assert health_hosts_for("youtube")[0] == "redirector.googlevideo.com"
    assert health_hosts_for("github")[0] == "codeload.github.com"
    assert merge_auto_default_services(["telegram-desktop"])[:5] == [
        "cloudflare",
        "discord",
        "youtube",
        "gaming",
        "clouds",
    ]
    assert "telegram-desktop" in merge_auto_default_services(["telegram-desktop"])


def test_passive_scan_activates_discord_from_established_process(tmp_path: Path):
    engine = __import__(
        "zapret_hub.services.orchestrator.engine", fromlist=["OrchestratorEngine"]
    ).OrchestratorEngine()
    settings = SimpleNamespace(selected_service_ids=[])
    engine.context = SimpleNamespace(
        settings=SimpleNamespace(get=lambda: settings),
        paths=SimpleNamespace(configs_dir=tmp_path, merged_runtime_dir=tmp_path),
        processes=SimpleNamespace(_current_zapret_runtime=None),
        knowledge=None,
        logging=None,
    )
    engine._mode = "auto"
    engine._signals = SimpleNamespace(
        snapshot_connections=lambda limit=200: [
            ConnSample(
                remote_ip="162.159.135.232",
                remote_port=443,
                proto="tcp",
                state="ESTABLISHED",
                pid=42,
                process="Discord.exe",
            )
        ]
    )
    incidents: list[dict[str, Any]] = []
    engine._handle_incident = incidents.append
    engine._passive_scan()
    assert incidents
    assert incidents[0]["services"] == ["discord"]
    assert incidents[0]["symptom"] == "service_detected"


def test_passive_scan_batches_all_discord_remotes(tmp_path: Path):
    engine = __import__(
        "zapret_hub.services.orchestrator.engine", fromlist=["OrchestratorEngine"]
    ).OrchestratorEngine()
    settings = SimpleNamespace(selected_service_ids=["discord", "youtube"])
    engine.context = SimpleNamespace(
        settings=SimpleNamespace(get=lambda: settings),
        paths=SimpleNamespace(configs_dir=tmp_path, merged_runtime_dir=tmp_path),
        processes=SimpleNamespace(_current_zapret_runtime=None),
        knowledge=None,
        logging=None,
    )
    engine._mode = "auto"
    engine._signals = SimpleNamespace(
        snapshot_connections=lambda limit=200: [
            ConnSample(
                remote_ip="162.159.135.232",
                remote_port=443,
                proto="tcp",
                state="SYN_SENT",
                pid=42,
                process=r"C:\Users\User\AppData\Local\Discord\Update.exe",
                domain="updates.discord.com",
            ),
            ConnSample(
                remote_ip="162.159.135.240",
                remote_port=443,
                proto="tcp",
                state="SYN_SENT",
                pid=42,
                process=r"C:\Users\User\AppData\Local\Discord\Update.exe",
                domain="cdn.discordapp.com",
            ),
            ConnSample(
                remote_ip="162.159.138.10",
                remote_port=443,
                proto="tcp",
                state="ESTABLISHED",
                pid=42,
                process=r"C:\Users\User\AppData\Local\Discord\Update.exe",
                domain="gateway.discord.gg",
            ),
        ]
    )
    incidents: list[dict[str, Any]] = []
    engine._handle_incident = incidents.append
    engine._passive_scan()
    assert incidents
    assert incidents[0]["services"] == ["discord"]
    assert "updates.discord.com" in incidents[0]["domains"]
    assert "cdn.discordapp.com" in incidents[0]["domains"]
    assert "gateway.discord.gg" in incidents[0]["domains"]
    assert len(incidents[0]["ips"]) >= 2


def test_staged_plans_escalate_cumulatively():
    engine = __import__(
        "zapret_hub.services.orchestrator.engine", fromlist=["OrchestratorEngine"]
    ).OrchestratorEngine()
    steps = [
        TunerStep(kind="add_domain", value="discord.com", reason="t", label_ru="", label_en=""),
        TunerStep(kind="general", value="alt.bat", reason="t", label_ru="", label_en=""),
        TunerStep(kind="enable_mod", value="discord-mod", reason="t", label_ru="", label_en=""),
        TunerStep(kind="enable_service", value="discord", reason="t", label_ru="", label_en=""),
        TunerStep(kind="game_filter", value="tcpudp", reason="t", label_ru="", label_en=""),
    ]
    plans = engine._staged_plans(steps)
    assert [phase for phase, _items in plans] == ["services", "user_mods", "network", "lists", "strategy"]
    assert [item.kind for item in plans[0][1]] == ["enable_service"]
    assert [item.kind for item in plans[-1][1]] == [
        "enable_service",
        "enable_mod",
        "game_filter",
        "add_domain",
        "general",
    ]


def test_staged_plans_try_generals_as_alternatives():
    engine = __import__(
        "zapret_hub.services.orchestrator.engine", fromlist=["OrchestratorEngine"]
    ).OrchestratorEngine()
    steps = [
        TunerStep(kind="enable_service", value="discord", reason="t", label_ru="", label_en=""),
        TunerStep(kind="general", value="one.bat", reason="t", label_ru="", label_en=""),
        TunerStep(kind="general", value="two.bat", reason="t", label_ru="", label_en=""),
    ]
    plans = engine._staged_plans(steps)
    strategy_plans = [items for phase, items in plans if phase == "strategy"]
    assert [[step.value for step in items if step.kind == "general"] for items in strategy_plans] == [
        ["one.bat"],
        ["two.bat"],
    ]


def test_tuner_multi_general_and_order():
    # List work still pending → no strategy in the same plan.
    pending = SmartTuner().plan(
        symptom="external_miss",
        domain="example.com",
        service_ids=["youtube"],
        selected_services=set(),
        current={"general": "general.bat", "ipset": "loaded", "game_filter": "disabled", "gaming_set": "stun-wide-base"},
        ranked_generals=[("alt1.bat", 5.0), ("alt2.bat", 4.0), ("alt3.bat", 3.0), ("alt4.bat", 2.0)],
        trusted_general="trusted.bat",
        domain_in_merged=False,
        max_steps=10,
    )
    assert [s.kind for s in pending][0] == "add_domain"
    assert "enable_service" in [s.kind for s in pending]
    assert not any(s.kind == "general" for s in pending)

    # After domain is already in lists, strategy is allowed as last resort.
    steps = SmartTuner().plan(
        symptom="tcp_timeout",
        domain="example.com",
        service_ids=["youtube"],
        selected_services={"youtube"},
        current={"general": "general.bat", "ipset": "loaded", "game_filter": "disabled", "gaming_set": "stun-wide-base"},
        ranked_generals=[("alt1.bat", 5.0), ("alt2.bat", 4.0), ("alt3.bat", 3.0), ("alt4.bat", 2.0)],
        trusted_general="trusted.bat",
        domain_in_merged=True,
        max_steps=10,
    )
    generals = [s.value for s in steps if s.kind == "general"]
    assert "trusted.bat" in generals
    assert len(generals) <= 2
    assert "alt4.bat" not in generals


def test_tuner_service_detected_skips_strategy():
    steps = SmartTuner().plan(
        symptom="service_detected",
        process="msedge.exe",
        domain="lt-in-f95.1e100.net",
        service_ids=["epic-games"],
        selected_services=set(),
        current={"general": "general.bat", "ipset": "loaded", "game_filter": "disabled", "gaming_set": "stun-wide-base"},
        ranked_generals=[("alt1.bat", 5.0)],
        trusted_general="trusted.bat",
        domains=["lt-in-f95.1e100.net", "epicgames.com"],
        domains_missing=["lt-in-f95.1e100.net", "epicgames.com"],
        max_steps=12,
    )
    kinds = [s.kind for s in steps]
    assert "enable_service" in kinds
    assert "general" not in kinds
    assert "game_filter" not in kinds
    assert "gaming_set" not in kinds
    assert not any(s.kind == "add_domain" and "1e100.net" in s.value for s in steps)
    assert any(s.kind == "add_domain" and "epicgames.com" in s.value for s in steps)


def test_passive_scan_ignores_browser_cdn_ptr(tmp_path: Path):
    engine = __import__(
        "zapret_hub.services.orchestrator.engine", fromlist=["OrchestratorEngine"]
    ).OrchestratorEngine()
    settings = SimpleNamespace(selected_service_ids=["discord", "youtube"])
    engine.context = SimpleNamespace(
        settings=SimpleNamespace(get=lambda: settings),
        paths=SimpleNamespace(configs_dir=tmp_path, merged_runtime_dir=tmp_path),
        processes=SimpleNamespace(_current_zapret_runtime=None),
        knowledge=None,
        logging=None,
    )
    engine._mode = "auto"
    engine._signals = SimpleNamespace(
        snapshot_connections=lambda limit=200: [
            ConnSample(
                remote_ip="2.16.53.65",
                remote_port=443,
                proto="tcp",
                state="SYN_SENT",
                pid=11,
                process="msedge.exe",
                domain="a2-16-53-65.deploy.static.akamaitechnologies.com",
            ),
            ConnSample(
                remote_ip="142.250.185.95",
                remote_port=443,
                proto="tcp",
                state="SYN_SENT",
                pid=11,
                process="msedge.exe",
                domain="lt-in-f95.1e100.net",
            ),
        ]
    )
    incidents: list[dict[str, Any]] = []
    engine._handle_incident = incidents.append
    engine._passive_scan()
    assert incidents == []


def test_passive_scan_does_not_activate_epic_from_edge_akamai(tmp_path: Path):
    engine = __import__(
        "zapret_hub.services.orchestrator.engine", fromlist=["OrchestratorEngine"]
    ).OrchestratorEngine()
    settings = SimpleNamespace(selected_service_ids=["discord"])
    engine.context = SimpleNamespace(
        settings=SimpleNamespace(get=lambda: settings),
        paths=SimpleNamespace(configs_dir=tmp_path, merged_runtime_dir=tmp_path),
        processes=SimpleNamespace(_current_zapret_runtime=None),
        knowledge=None,
        logging=None,
    )
    engine._mode = "auto"
    engine._signals = SimpleNamespace(
        snapshot_connections=lambda limit=200: [
            ConnSample(
                remote_ip="2.16.53.65",
                remote_port=443,
                proto="tcp",
                state="ESTABLISHED",
                pid=11,
                process="msedge.exe",
                domain="a2-16-53-65.deploy.static.akamaitechnologies.com",
            )
        ]
    )
    incidents: list[dict[str, Any]] = []
    engine._handle_incident = incidents.append
    engine._passive_scan()
    assert incidents == []


def test_tuner_fortnite_enables_mod_and_alt9_general():
    mod = SimpleNamespace(
        id="fortnite-unlock",
        name="Fortnite Unlock ALT9",
        description="Unlock Fortnite via ALT9",
        general_scripts=["general (ALT9).bat"],
        source_type="zapret_bundle",
        enabled=False,
    )
    steps = SmartTuner().plan(
        symptom="external_miss",
        process="FortniteClient-Win64-Shipping.exe",
        proto="udp",
        service_ids=["fortnite"],
        selected_services={"fortnite"},
        current={
            "general": "base|general.bat",
            "ipset": "loaded",
            "game_filter": "disabled",
            "gaming_set": "stun-wide-base",
        },
        domain_in_merged=False,
        max_steps=12,
        installed_mods=[mod],
        enabled_mod_ids=set(),
        mod_generals=[
            {
                "id": "fortnite-unlock|general (ALT9).bat",
                "bundle_id": "fortnite-unlock",
                "name": "general (ALT9).bat",
            },
            {
                "id": "other-mod|general.bat",
                "bundle_id": "other-mod",
                "name": "general.bat",
            },
        ],
        trusted_general="base|trusted.bat",
        ranked_generals=[],
    )
    kinds = [s.kind for s in steps]
    assert "enable_mod" in kinds
    assert any(s.kind == "enable_mod" and s.value == "fortnite-unlock" for s in steps)
    assert any(s.kind == "ipset" and s.value == "any" for s in steps)
    generals = [s.value for s in steps if s.kind == "general"]
    assert any("ALT9" in g or "alt9" in g.lower() for g in generals)


def test_tuner_ignores_removed_mod_from_knowledge():
    steps = SmartTuner().plan(
        symptom="external_miss",
        domain="discord.com",
        process="Discord.exe",
        service_ids=["discord"],
        selected_services={"discord"},
        current={"general": "general.bat", "ipset": "loaded", "game_filter": "disabled"},
        knowledge_winner={"mods": ["removed-marketplace-mod"]},
        installed_mods=[],
        enabled_mod_ids=set(),
    )
    assert not any(step.kind == "enable_mod" and step.value == "removed-marketplace-mod" for step in steps)


def test_conflict_detect_requires_udp_voice_for_ark():
    detector = ConflictDetector()
    assert (
        detector.detect(
            process="ShooterGame.exe",
            current_gaming_set="stun-wide-base",
            proto="tcp",
            remote_port=443,
        )
        is None
    )
    assert (
        detector.detect(
            process="ShooterGame.exe",
            current_gaming_set="stun-wide-base",
            proto="udp",
            remote_port=53,
        )
        is None
    )
    hit = detector.detect(
        process="ShooterGame.exe",
        current_gaming_set="stun-wide-base",
        proto="udp",
        remote_port=3478,
    )
    assert hit is not None
    assert hit["fix_gaming_set"] == "stun-wide-base-local-exclude"
    miss = detector.detect(
        process="ShooterGame.exe",
        current_gaming_set="udp-first",
        proto="udp",
        remote_port=3478,
    )
    assert miss is None


def test_learner_exact_domain_match(tmp_path: Path):
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "list-general.txt").write_text("youtube.com\nfoo.bar\n", encoding="utf-8")
    learner = HostlistLearner(tmp_path)
    assert learner.domain_in_merged_lists("www.youtube.com", [lists]) is True
    assert learner.domain_in_merged_lists("notyoutube.com", [lists]) is False
    (lists / "list-general.txt").write_text("tube\n", encoding="utf-8")
    assert learner.domain_in_merged_lists("youtube.com", [lists]) is False


def test_knowledge_sqlite_winners_and_eviction(tmp_path: Path):
    store = KnowledgeStore(tmp_path / "knowledge")
    store.set_winner("host:a.com", {"general": "g1", "score": 1.0, "symptom": "external_miss"})
    store.rank_general("g1", 2.0)
    store.record_conflict({"app": "ark", "fix_gaming_set": "stun-wide-base-local-exclude"})
    assert store.winner_for_host("a.com")["general"] == "g1"
    assert store.ranked_generals()[0][0] == "g1"
    assert store.find_conflict("ark") is not None
    store.set_cooldown("host:a.com", 60)
    assert store.on_cooldown("host:a.com") is True
    store.mark_dead_host("dead.example", ttl_s=1)
    assert store.is_dead_host("dead.example") is True
    store.clear()
    store.close()


@dataclass
class FakeSettings:
    selected_zapret_general: str = "base|general.bat"
    zapret_ipset_mode: str = "loaded"
    zapret_game_filter_mode: str = "disabled"
    zapret_gaming_set: str = "stun-wide-base"
    selected_service_ids: list[str] = field(default_factory=list)
    trusted_general: str = ""
    enabled_mod_ids: list[str] = field(default_factory=list)
    enabled_component_ids: list[str] = field(default_factory=lambda: ["zapret"])

    def get(self) -> FakeSettings:
        return self

    def update(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


@dataclass
class FakeMod:
    id: str
    name: str
    enabled: bool = False
    source_type: str = "zapret_bundle"
    general_scripts: list[str] = field(default_factory=list)
    description: str = ""


class FakeMods:
    def __init__(self, mods: list[FakeMod]) -> None:
        self._mods = {m.id: m for m in mods}

    def list_installed(self) -> list[FakeMod]:
        return list(self._mods.values())

    def fetch_index(self) -> list[FakeMod]:
        return []

    def set_enabled(self, mod_id: str, enabled: bool) -> None:
        self._mods[mod_id].enabled = enabled

    def install(self, mod_id: str) -> None:
        raise RuntimeError("not in index")


class FakeState:
    def __init__(self, status: str = "running", last_error: str = "") -> None:
        self.status = status
        self.last_error = last_error
        self.component_id = "zapret"


class FakeProcesses:
    def __init__(self, runtime: Path) -> None:
        self._current_zapret_runtime = runtime
        self._running = True
        self._starts: list[str] = []
        self._fail_next_start = False
        self._pinned: Path | None = None

    def list_states(self) -> list[FakeState]:
        return [FakeState("running" if self._running else "stopped")]

    def stop_component(self, _component_id: str) -> FakeState:
        self._running = False
        return FakeState("stopped")

    def start_component(self, _component_id: str) -> FakeState:
        self._running = True
        self._starts.append("component")
        return FakeState("running")

    def start_zapret_from_runtime(self, path: Path) -> FakeState:
        if self._fail_next_start:
            self._fail_next_start = False
            self._running = False
            return FakeState("stopped", last_error="boom")
        self._running = True
        self._current_zapret_runtime = Path(path)
        self._starts.append(str(path))
        return FakeState("running")

    def pin_orchestrator_runtime(self, path: Path | None) -> None:
        self._pinned = Path(path) if path is not None else None

    def stage_zapret_candidate_runtime(self) -> Path:
        slot_b = self._current_zapret_runtime.parent / "slot_b"
        slot_b.mkdir(parents=True, exist_ok=True)
        (slot_b / "marker").write_text("b", encoding="utf-8")
        return slot_b

    def rebuild_zapret_runtime_snapshot(self) -> None:
        return None


class FakeMerge:
    def rebuild(self) -> None:
        return None


class FakeFiles:
    def _invalidate_collection_cache(self) -> None:
        return None

    def rebuild_materialized_collections(self) -> None:
        return None


class FakeSignals:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    def probe_targets(self, targets: list[dict[str, str]], **_kwargs: Any) -> list[ProbeResult]:
        return [
            ProbeResult(ok=self.ok, target=str(t.get("value") or ""), latency_ms=1, error="" if self.ok else "fail")
            for t in targets
        ]


def _make_cutover_context(tmp_path: Path, *, probe_ok: bool = True) -> tuple[Any, CutoverManager, Path]:
    slot_a = tmp_path / "slot_a"
    slot_a.mkdir()
    (slot_a / "marker").write_text("a", encoding="utf-8")
    settings = FakeSettings(enabled_mod_ids=[], selected_service_ids=["youtube"])
    mods = FakeMods([FakeMod(id="fortnite-unlock", name="FN", enabled=False)])
    ctx = SimpleNamespace(
        settings=settings,
        processes=FakeProcesses(slot_a),
        merge=FakeMerge(),
        files=FakeFiles(),
        mods=mods,
        paths=SimpleNamespace(configs_dir=tmp_path / "configs"),
        logging=None,
    )
    (tmp_path / "configs").mkdir(exist_ok=True)
    cutover = CutoverManager(ctx, signals=FakeSignals(ok=probe_ok))
    # Speed up tests — skip real settle sleep.
    cutover._settle_s = 0.0
    return ctx, cutover, slot_a


def test_apply_plan_batches_and_commits(tmp_path: Path):
    ctx, cutover, _slot_a = _make_cutover_context(tmp_path, probe_ok=True)
    result = cutover.apply_plan(
        [
            TunerStep(kind="ipset", value="any", reason="t", label_ru="", label_en=""),
            TunerStep(kind="enable_mod", value="fortnite-unlock", reason="t", label_ru="", label_en=""),
            TunerStep(kind="general", value="base|alt.bat", reason="t", label_ru="", label_en=""),
        ],
        probe_targets=[{"value": "https://www.youtube.com/"}],
        required_hosts=["youtube.com"],
    )
    assert result["ok"] is True
    assert result["restarted"] is True
    assert len(result["applied"]) == 3
    assert ctx.settings.zapret_ipset_mode == "any"
    assert ctx.settings.selected_zapret_general == "base|alt.bat"
    assert ctx.mods._mods["fortnite-unlock"].enabled is True
    assert Path(result["runtime"]).name == "slot_b"
    assert cutover.last_good is not None
    assert Path(str(cutover.last_good["runtime_path"])).name == "slot_b"


def test_apply_plan_probe_fail_rolls_back_settings_and_mods(tmp_path: Path):
    ctx, cutover, _slot_a = _make_cutover_context(tmp_path, probe_ok=False)
    ctx.settings.zapret_ipset_mode = "loaded"
    ctx.settings.selected_zapret_general = "base|general.bat"
    result = cutover.apply_plan(
        [
            TunerStep(kind="ipset", value="any", reason="t", label_ru="", label_en=""),
            TunerStep(kind="enable_mod", value="fortnite-unlock", reason="t", label_ru="", label_en=""),
            TunerStep(kind="general", value="base|alt.bat", reason="t", label_ru="", label_en=""),
        ],
        probe_targets=[{"value": "https://www.youtube.com/"}],
        required_hosts=["youtube.com"],
    )
    assert result["ok"] is False
    assert result.get("rolled_back") is True
    assert ctx.settings.zapret_ipset_mode == "loaded"
    assert ctx.settings.selected_zapret_general == "base|general.bat"
    assert ctx.mods._mods["fortnite-unlock"].enabled is False
    assert Path(ctx.processes._current_zapret_runtime).name == "slot_a"


def test_cutover_enables_zapret2_mod(tmp_path: Path):
    ctx, cutover, _slot_a = _make_cutover_context(tmp_path, probe_ok=True)
    ctx.mods2 = FakeMods([FakeMod(id="discord-zapret2", name="Discord Zapret2", enabled=False)])
    changed = cutover._apply_one_mutation(
        TunerStep(kind="enable_mod", value="discord-zapret2", reason="user_mod", label_ru="", label_en=""),
        backend="zapret2",
    )
    assert changed == "mods"
    assert ctx.mods2._mods["discord-zapret2"].enabled is True


def test_apply_and_start_trusted_rolls_back_on_probe_fail(tmp_path: Path):
    ctx, cutover, _slot_a = _make_cutover_context(tmp_path, probe_ok=False)
    ctx.settings.selected_zapret_general = "base|old.bat"
    result = cutover.apply_and_start_trusted(
        general_id="base|new.bat",
        probe_targets=[{"value": "https://www.youtube.com/"}],
        required_hosts=["youtube.com"],
    )
    assert result["ok"] is False
    assert ctx.settings.selected_zapret_general == "base|old.bat"
    assert Path(ctx.processes._current_zapret_runtime).name == "slot_a"


def test_tuner_batches_multiple_domains_and_ips():
    steps = SmartTuner().plan(
        symptom="external_miss",
        domain="a.example.com",
        ip="1.1.1.1",
        domains=["a.example.com", "b.example.com", "c.example.com"],
        ips=["1.1.1.1", "2.2.2.2"],
        domains_missing=["a.example.com", "b.example.com", "c.example.com"],
        service_ids=[],
        selected_services=set(),
        current={"general": "g.bat", "ipset": "any", "game_filter": "disabled", "gaming_set": "stun-wide-base"},
        domain_in_merged=False,
        max_steps=10,
    )
    domain_steps = [s for s in steps if s.kind == "add_domain"]
    ip_steps = [s for s in steps if s.kind == "add_ip"]
    assert len(domain_steps) == 1
    assert "a.example.com" in domain_steps[0].value
    assert "b.example.com" in domain_steps[0].value
    assert "c.example.com" in domain_steps[0].value
    assert len(ip_steps) == 1
    assert "1.1.1.1/32" in ip_steps[0].value
    assert "2.2.2.2/32" in ip_steps[0].value


def test_cutover_coalesce_and_batch_write(tmp_path: Path):
    configs = tmp_path / "configs"
    configs.mkdir()
    ctx, cutover, _slot = _make_cutover_context(tmp_path, probe_ok=True)
    ctx.paths.configs_dir = configs
    result = cutover.apply_plan(
        [
            TunerStep(kind="add_domain", value="one.com", reason="t", label_ru="", label_en=""),
            TunerStep(kind="add_domain", value="two.com", reason="t", label_ru="", label_en=""),
            TunerStep(kind="add_ip", value="9.9.9.9", reason="t", label_ru="", label_en=""),
            TunerStep(kind="add_ip", value="8.8.8.8/32", reason="t", label_ru="", label_en=""),
        ],
        probe_targets=[{"value": "https://www.youtube.com/"}],
        required_hosts=["youtube.com"],
    )
    assert result["ok"] is True
    domain_applied = [s for s in result["applied"] if s["kind"] == "add_domain"]
    ip_applied = [s for s in result["applied"] if s["kind"] == "add_ip"]
    assert len(domain_applied) == 1
    assert "one.com" in domain_applied[0]["value"] and "two.com" in domain_applied[0]["value"]
    assert len(ip_applied) == 1
    # Auto writes overlay/diff only — battle user lists stay untouched.
    overlay = configs / "auto" / "overlay.json"
    assert overlay.is_file()
    payload = overlay.read_text(encoding="utf-8")
    assert "one.com" in payload and "two.com" in payload
    assert "9.9.9.9" in payload and "8.8.8.8" in payload
    assert not (configs / "list-general-user.txt").exists() or "one.com" not in (
        configs / "list-general-user.txt"
    ).read_text(encoding="utf-8")
    assert not (configs / "ipset-all-user.txt").exists() or "9.9.9.9" not in (
        configs / "ipset-all-user.txt"
    ).read_text(encoding="utf-8")


def test_signals_never_calls_tasklist():
    import inspect

    from zapret_hub.services.orchestrator import signals as signals_mod

    source = inspect.getsource(signals_mod)
    assert "tasklist" not in source
    assert "CREATE_NO_WINDOW" in source


def test_zapret2_seed_is_append_only(tmp_path: Path):
    from zapret_hub.services.orchestrator import zapret2_hub

    first = zapret2_hub.seed_bypass_catalog(tmp_path, only_missing=True)
    assert first["domains"]
    hub_lines = [
        line.strip()
        for line in (tmp_path / "zapret2" / "list-hub.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert "discord.com" in hub_lines
    assert "youtube.com" in hub_lines
    second = zapret2_hub.seed_bypass_catalog(tmp_path, only_missing=True)
    assert second["domains"] == []
    hub_lines2 = [
        line.strip()
        for line in (tmp_path / "zapret2" / "list-hub.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert hub_lines2 == hub_lines
    zapret2_hub.add_domains(tmp_path, ["custom.example"])
    zapret2_hub.seed_service_lists(tmp_path, ["discord"], only_missing=True)
    assert "custom.example" in (tmp_path / "zapret2" / "list-hub.txt").read_text(encoding="utf-8")


def test_zapret2_lua_files_created_once(tmp_path: Path):
    from zapret_hub.services.orchestrator import zapret2_hub

    paths = zapret2_hub.prepare_zapret2_runtime_files(tmp_path, "balanced")
    orch = paths["lua_orch"].read_text(encoding="utf-8")
    assert "function hub_tls" in orch
    assert "function hub_discord" in orch
    assert "function hub_discord_media" in orch
    assert "function hub_discord_https" in orch
    assert "function hub_youtube" in orch
    assert "function hub_googlevideo" in orch
    assert "HUB_ORCHESTRATOR_VERSION = 5" in orch
    assert "tcp_md5 = true" not in orch
    strategy = paths["lua_strategy"].read_text(encoding="utf-8")
    assert 'HUB_STRATEGY = "balanced"' in strategy
    paths["lua_orch"].write_text(orch + "\n-- keep\n", encoding="utf-8")
    zapret2_hub.prepare_zapret2_runtime_files(tmp_path, "fake_heavy")
    assert "-- keep" in paths["lua_orch"].read_text(encoding="utf-8")
    assert 'HUB_STRATEGY = "fake_heavy"' in paths["lua_strategy"].read_text(encoding="utf-8")


def test_tuner_discord_seed_batches_catalog():
    steps = SmartTuner().plan(
        symptom="external_miss",
        domain="gateway.discord.gg",
        service_ids=["discord"],
        selected_services=set(),
        current={"general": "g.bat", "ipset": "any", "game_filter": "disabled", "gaming_set": "stun-wide-base"},
        domain_in_merged=False,
        domains_missing=["gateway.discord.gg"],
        max_steps=12,
    )
    domain_steps = [s for s in steps if s.kind == "add_domain"]
    assert any(s.kind == "enable_service" and s.value == "discord" for s in steps)
    blob = "\n".join(s.value for s in domain_steps)
    assert "discord.com" in blob
    assert "gateway.discord.gg" in blob
    # Soft HTTPS miss: lists/services only — no GameFilter / strategy thrash.
    assert not any(step.kind == "game_filter" for step in steps)
    assert not any(step.kind == "general" for step in steps)
