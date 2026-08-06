from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import zapret_hub.services.components as components_module
from zapret_hub.services.components import ProcessManager
from zapret_hub.services.orchestrator.engine import OrchestratorEngine
from zapret_hub.ui.web_window import WebBridge


RELEASE_FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Release 1.10.0</title>
    <link rel="alternate" href="https://github.com/Flowseal/zapret-discord-youtube/releases/tag/1.10.0"/>
  </entry>
</feed>'''

COMMIT_FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Update bundle</title>
    <link rel="alternate" href="https://github.com/bol-van/zapret-win-bundle/commit/f4cf5dde162ae35e6f3a2fd72dde3e86b57dc278"/>
  </entry>
</feed>'''


class FakeLogging:
    def log(self, *_args, **_kwargs) -> None:
        return None


def test_zapret_cutover_retries_candidate_after_driver_handoff(monkeypatch, tmp_path: Path) -> None:
    """A WinDivert hand-off race must retry the staged runtime, not leave Zapret off."""
    previous = tmp_path / "runtime-a"
    candidate = tmp_path / "runtime-b"
    previous.mkdir()
    candidate.mkdir()
    manager = ProcessManager.__new__(ProcessManager)
    manager._zapret_runtime_lock = threading.RLock()
    manager._current_zapret_runtime = previous
    manager._current_zapret_script_name = "general.bat"
    manager._processes = {}
    manager._states = {}
    manager._image_running_cache = {}
    manager.logging = FakeLogging()
    manager._list_image_pids = lambda _image: set()
    manager._is_image_running = lambda _image: False
    manager._managed_zapret_driver_services = lambda: []
    manager._soft_stop_zapret_image = lambda: None
    manager._purge_stale_zapret_runtime = lambda: True
    manager._wait_for_image_exit = lambda *_args, **_kwargs: True

    class FakeProcess:
        pid = 4321

        @staticmethod
        def poll():
            return None

    starts: list[Path] = []

    def start(root: Path, **_kwargs):
        starts.append(Path(root))
        if len(starts) == 1:
            return SimpleNamespace(status="error", last_error="driver_busy")
        manager._processes["zapret"] = FakeProcess()
        return SimpleNamespace(status="running", last_error="")

    manager.start_zapret_from_runtime = start
    manager._zapret_process_stable = lambda process: process is manager._processes.get("zapret")
    monkeypatch.setattr(components_module.time, "sleep", lambda _seconds: None)

    state = manager._cutover_to_zapret_runtime(candidate)

    assert state.status == "running"
    assert starts == [candidate, candidate]


class FeedGitHub:
    def github_json(self, *_args, **_kwargs):
        raise RuntimeError("HTTP Error 403: rate limit exceeded")

    def github_bytes(self, url: str, **_kwargs) -> bytes:
        if "commits/master.atom" in url:
            return COMMIT_FEED
        return RELEASE_FEED


def manager() -> ProcessManager:
    process = ProcessManager.__new__(ProcessManager)
    process.github = FeedGitHub()
    process.logging = FakeLogging()
    return process


def test_zapret_release_resolves_1_10_0() -> None:
    release = manager().fetch_latest_zapret_release()
    assert release["latest_version"] == "1.10.0"
    assert release["asset_url"].endswith("/1.10.0/zapret-discord-youtube-1.10.0.zip")
    assert release["zipball_url"].endswith("/refs/tags/1.10.0")


def test_zapret2_release_uses_bol_van_zapret2_tags() -> None:
    process = manager()

    class Zapret2GitHub(FeedGitHub):
        def github_json(self, url: str, **_kwargs):
            if "bol-van/zapret2/releases" in url:
                return [
                    {
                        "tag_name": "v1.0.3",
                        "draft": False,
                        "prerelease": False,
                        "published_at": "2026-07-20T12:00:00Z",
                        "zipball_url": "https://codeload.github.com/bol-van/zapret2/zip/refs/tags/v1.0.3",
                        "assets": [
                            {
                                "name": "zapret2-v1.0.3.zip",
                                "browser_download_url": "https://github.com/bol-van/zapret2/releases/download/v1.0.3/zapret2-v1.0.3.zip",
                            }
                        ],
                    }
                ]
            raise RuntimeError("HTTP Error 403: rate limit exceeded")

    process.github = Zapret2GitHub()
    release = process.fetch_latest_zapret2_release()
    assert release["latest_version"] == "1.0.3"
    assert "bol-van/zapret2" in release["source_url"]
    assert release["source_url"].endswith("zapret2-v1.0.3.zip")


def test_zapret2_auto_discord_capture_includes_voice_udp_ranges() -> None:
    from zapret_hub.services.components import DISCORD_MEDIA_TCP_PORTS, DISCORD_VOICE_UDP_PORTS

    process = ProcessManager.__new__(ProcessManager)
    process.settings = SimpleNamespace(
        get=lambda: SimpleNamespace(
            zapret2_tcp_ports="80,443",
            zapret2_udp_ports="443",
            selected_service_ids=["discord"],
            zapret2_control_mode="auto",
        )
    )
    udp_ports = process._normalize_zapret2_ports("443", "443")
    udp_ports = process._merge_zapret2_ports(udp_ports, DISCORD_VOICE_UDP_PORTS)
    assert udp_ports == "443,3478-3497,19294-19344,50000-50100"
    assert "42377" not in udp_ports
    tcp_ports = process._normalize_zapret2_ports("80,443", "80,443")
    tcp_ports = process._merge_zapret2_ports(tcp_ports, DISCORD_MEDIA_TCP_PORTS)
    assert "2053" in tcp_ports
    assert "8443" in tcp_ports


def test_zapret2_default_profiles_include_discord_media_and_voice() -> None:
    from zapret_hub.services.orchestrator import zapret2_hub

    lists = {
        "hub": Path("hub.txt"),
        "auto": Path("auto.txt"),
        "exclude": Path("exclude.txt"),
        "ipset": Path("ipset.txt"),
    }
    repo = Path(__file__).resolve().parents[1]
    fake_root = repo / "runtime" / "zapret2"
    flowseal_bin = repo / "runtime" / "zapret-discord-youtube" / "bin"
    args = zapret2_hub.build_default_profile_args(
        lists=lists,
        asset_roots=[fake_root] if fake_root.is_dir() else [],
        tcp_ports="80,443,2053,2083,2087,2096,8443",
        include_hostlist_auto=False,
        flowseal_bin=flowseal_bin if flowseal_bin.is_dir() else None,
    )
    joined = " ".join(args)
    assert "--blob=quic_google:@" in joined or not fake_root.is_dir()
    assert "--blob=tls_google:@" in joined or not fake_root.is_dir()
    assert "--blob=discord_udp:@" in joined or not (fake_root.is_dir() or flowseal_bin.is_dir())
    # bol-van syntax is name:@file — never name=@C:\... (drive colon breaks the parser).
    blob_args = [a for a in args if a.startswith("--blob=")]
    assert blob_args
    assert all(":@" in a for a in blob_args)
    assert not any("=@" in a for a in blob_args)
    assert all(":@C:" not in a for a in blob_args)
    assert "--hostlist-domains=discord.media" in joined
    assert "--hostlist-domains=updates.discord.com" in joined
    assert "--hostlist-domains=googlevideo.com" in joined
    assert "--filter-udp=19294-19344,50000-50100" in joined
    assert "--filter-l7=discord,stun" in joined
    assert "--lua-desync=hub_discord" in joined
    assert "--lua-desync=hub_discord_ipdisc" in joined
    # balanced (default) = Flowseal-safe Discord TLS (not syndata — that is opt-in).
    assert "--lua-desync=hub_discord_https" in joined
    assert "--lua-desync=hub_discord_media" in joined
    assert "--lua-desync=syndata:blob=tls_google" not in joined
    assert "--lua-desync=hub_youtube" in joined
    assert "--lua-desync=hub_googlevideo" in joined
    assert "--ipcache-hostname=1" in joined
    assert "--ipset-exclude-ip=162.158.0.0/15,162.159.128.0/20" in joined
    # Discord profiles must appear before general TLS.
    assert joined.index("--lua-desync=hub_discord") < joined.index("--lua-desync=hub_tls")

    syndata = zapret2_hub.build_default_profile_args(
        lists=lists,
        asset_roots=[fake_root] if fake_root.is_dir() else [],
        tcp_ports="80,443,2053,2083,2087,2096,8443",
        strategy_id="syndata",
        include_hostlist_auto=False,
        flowseal_bin=flowseal_bin if flowseal_bin.is_dir() else None,
    )
    syndata_joined = " ".join(syndata)
    assert "--lua-desync=syndata:blob=tls_google" in syndata_joined


def test_harvest_skips_discord_breaking_cloudflare_cidrs() -> None:
    from zapret_hub.services.orchestrator import zapret2_hub

    ips = zapret2_hub.harvest_service_ips(["cloudflare", "discord"], include_bypass_seeds=True)
    lowered = {item.lower() for item in ips}
    assert "162.158.0.0/15" not in lowered
    assert "162.159.128.0/20" not in lowered
    assert "1.1.1.0/24" in lowered


def test_flowseal_discord_domains_seeded() -> None:
    from zapret_hub.services.orchestrator import zapret2_hub

    assert "dis.gd" in zapret2_hub.FLOWSEAL_DISCORD_DOMAINS
    assert "discordapp.io" in zapret2_hub.FLOWSEAL_DISCORD_DOMAINS
    assert "discord.com" in zapret2_hub.BYPASS_SEED_DOMAINS
    assert "stable.dl2.discordapp.net" in zapret2_hub.BYPASS_SEED_DOMAINS
    assert "youtubekids.com" in zapret2_hub.YOUTUBE_SEED_DOMAINS
    assert "jnn-pa.googleapis.com" in zapret2_hub.BYPASS_SEED_DOMAINS


def test_discord_attachments_are_kept_outside_dpi_and_warframe_has_a_rule() -> None:
    from zapret_hub.services.service_rules import SERVICE_RULES

    assert "discord-attachments-uploads-prd.storage.googleapis.com" in SERVICE_RULES["discord"].list_exclude
    assert "api.warframe.com" in SERVICE_RULES["warframe"].list_general
    assert SERVICE_RULES["warframe"].health_hosts == ("www.warframe.com", "api.warframe.com")


def test_zapret_bundles_keep_installed_layer_order(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    base = tmp_path / "runtime" / "zapret-discord-youtube"
    for folder in (first, second, base):
        folder.mkdir(parents=True)

    installed = [
        {"id": "market", "path": str(first), "source_type": "zapret_bundle", "enabled": True},
        {"id": "custom", "path": str(second), "source_type": "zapret_bundle", "enabled": True},
    ]

    class Storage:
        paths = SimpleNamespace(
            runtime_dir=tmp_path / "runtime",
            mods_dir=tmp_path / "mods",
            cache_dir=tmp_path / "cache",
            data_dir=tmp_path / "data",
        )

        @staticmethod
        def read_json(path: Path, default=None):
            return installed if path.name == "installed_mods.json" else default

    process = ProcessManager.__new__(ProcessManager)
    process.storage = Storage()

    assert [item["id"] for item in process._get_zapret_bundles(enabled_only=True)] == ["market", "custom", "base"]


def test_marketplace_bundle_overlays_complete_zapret_runtime(tmp_path: Path) -> None:
    base = tmp_path / "runtime" / "zapret-discord-youtube"
    mod = tmp_path / "mod"
    active = tmp_path / "active"
    for root in (base, mod):
        (root / "bin").mkdir(parents=True)
        (root / "lists").mkdir()
    (base / "general.bat").write_text("base", encoding="utf-8")
    (base / "bin" / "base.bin").write_bytes(b"base")
    (base / "lists" / "list-general.txt").write_text("base.example\n", encoding="utf-8")
    (mod / "market-general.bat").write_text("market", encoding="utf-8")
    (mod / "bin" / "market.bin").write_bytes(b"market")
    (mod / "lists" / "list-general.txt").write_text("market.example\n", encoding="utf-8")

    process = ProcessManager.__new__(ProcessManager)
    process.storage = SimpleNamespace(paths=SimpleNamespace(runtime_dir=tmp_path / "runtime"))
    process._next_active_runtime_dir = lambda: active
    process._get_zapret_bundles = lambda enabled_only: [
        {"id": "market", "path": mod},
        {"id": "base", "path": base},
    ]
    process._apply_selected_service_rules = lambda *_args, **_kwargs: None
    process._apply_user_collection_overrides = lambda *_args, **_kwargs: None
    process._apply_gaming_set_list_overlays = lambda *_args, **_kwargs: None
    process._materialize_visible_merged_runtime = lambda *_args, **_kwargs: None

    result = process._materialize_zapret_runtime(
        selected_bundle_root=base,
        selected_bundle_id="base",
        selected_script_name="general.bat",
    )

    assert (result / "market-general.bat").read_text(encoding="utf-8") == "market"
    assert (result / "bin" / "market.bin").read_bytes() == b"market"
    # Merge overlay: keep Flowseal/base bins that the mod did not replace.
    assert (result / "bin" / "base.bin").read_bytes() == b"base"


def test_service_change_restarts_running_zapret() -> None:
    events: list[str] = []
    values = SimpleNamespace(
        selected_service_ids=[],
        enabled_component_ids=["zapret"],
        autostart_component_ids=[],
        zapret_control_mode="manual",
    )

    class Settings:
        @staticmethod
        def get():
            return values

        @staticmethod
        def update(**changes):
            for key, value in changes.items():
                setattr(values, key, value)

    class Processes:
        running = {"zapret"}

        @classmethod
        def list_states(cls):
            return [SimpleNamespace(component_id=item, status="running") for item in cls.running]

        @classmethod
        def stop_component(cls, component_id: str):
            events.append(f"stop:{component_id}")
            cls.running.discard(component_id)

        @classmethod
        def start_component(cls, component_id: str):
            events.append(f"start:{component_id}")
            cls.running.add(component_id)
            return SimpleNamespace(status="running", component_id=component_id)

        @classmethod
        def seamless_restart_zapret(cls):
            events.append("seamless:zapret")
            cls.running.add("zapret")
            return SimpleNamespace(status="running", component_id="zapret")

    bridge = WebBridge.__new__(WebBridge)
    bridge.context = SimpleNamespace(
        settings=Settings(),
        processes=Processes(),
        merge=SimpleNamespace(rebuild=lambda: events.append("rebuild")),
        files=SimpleNamespace(
            _invalidate_collection_cache=lambda: None,
            rebuild_materialized_collections=lambda: events.append("collections"),
        ),
        logging=FakeLogging(),
    )
    bridge._runtime_reconfigure_lock = threading.Lock()
    bridge._runtime_transition_status = "on"
    bridge._service_power_hold = 0
    bridge.emit_state = lambda *args, **kwargs: None
    bridge._hold_service_power = lambda: 1
    bridge._release_service_power = lambda *_a, **_k: None
    bridge._emit_runtime_status = lambda *_a, **_k: None
    bridge._set_auxiliary_components_power_async = lambda *_a, **_k: None
    bridge._sync_orchestrator_lifecycle = lambda: None
    bridge._component_running = lambda cid: cid in Processes.running

    bridge._apply_selected_services(["youtube", "discord"], emit=False)

    assert values.selected_service_ids == ["discord", "youtube"]
    assert "zapret" in values.enabled_component_ids
    assert events == ["rebuild", "collections", "seamless:zapret"]


def test_clearing_bypass_services_stops_zapret_without_restart() -> None:
    events: list[str] = []
    values = SimpleNamespace(
        selected_service_ids=["youtube"],
        enabled_component_ids=["zapret"],
        autostart_component_ids=["zapret"],
        selected_runtime_mode="zapret",
        zapret_control_mode="manual",
    )

    class Settings:
        @staticmethod
        def get():
            return values

        @staticmethod
        def update(**changes):
            for key, value in changes.items():
                setattr(values, key, value)

    class Processes:
        running = {"zapret"}

        @classmethod
        def list_states(cls):
            return [SimpleNamespace(component_id=item, status="running") for item in cls.running]

        @classmethod
        def stop_component(cls, component_id: str):
            events.append(f"stop:{component_id}")
            cls.running.discard(component_id)

        @classmethod
        def start_component(cls, component_id: str):
            events.append(f"start:{component_id}")

    bridge = WebBridge.__new__(WebBridge)
    bridge.context = SimpleNamespace(
        settings=Settings(),
        processes=Processes(),
        merge=SimpleNamespace(rebuild=lambda: events.append("rebuild")),
        files=SimpleNamespace(
            _invalidate_collection_cache=lambda: None,
            rebuild_materialized_collections=lambda: None,
        ),
        logging=FakeLogging(),
    )
    bridge._runtime_reconfigure_lock = threading.Lock()
    bridge._runtime_transition_status = "on"
    bridge._service_power_hold = 0
    bridge.emit_state = lambda *args, **kwargs: None
    bridge._hold_service_power = lambda: 1
    bridge._release_service_power = lambda *_a, **_k: None
    bridge._emit_runtime_status = lambda *_a, **_k: None
    bridge._set_auxiliary_components_power_async = lambda *_a, **_k: None
    bridge._sync_orchestrator_lifecycle = lambda: None
    bridge._component_running = lambda cid: cid in Processes.running

    bridge._apply_selected_services([], emit=False)

    assert "zapret" not in values.enabled_component_ids
    assert "zapret" not in values.autostart_component_ids
    assert events == ["stop:zapret", "rebuild"]


def test_auto_resume_restarts_zapret_with_rebuilt_services(tmp_path: Path) -> None:
    events: list[str] = []
    values = SimpleNamespace(
        selected_runtime_mode="zapret",
        selected_service_ids=["youtube"],
        enabled_component_ids=["zapret"],
        trusted_general="base|general.bat",
        zapret_control_mode="auto",
        general_autotest_done=True,
    )

    class Settings:
        @staticmethod
        def get():
            return values

        @staticmethod
        def update(**changes):
            for key, value in changes.items():
                setattr(values, key, value)

    class Processes:
        @staticmethod
        def list_states():
            return [SimpleNamespace(component_id="zapret", status="running")]

        @staticmethod
        def stop_component(component_id: str):
            events.append(f"stop:{component_id}")

        @staticmethod
        def start_component(component_id: str):
            events.append(f"start:{component_id}")

        @staticmethod
        def rebuild_zapret_runtime_snapshot():
            events.append("snapshot")

    configs = tmp_path / "configs"
    configs.mkdir()
    engine = OrchestratorEngine()
    engine.context = SimpleNamespace(
        settings=Settings(),
        processes=Processes(),
        merge=SimpleNamespace(rebuild=lambda: events.append("rebuild")),
        files=SimpleNamespace(
            _invalidate_collection_cache=lambda: None,
            rebuild_materialized_collections=lambda: events.append("collections"),
        ),
        paths=SimpleNamespace(configs_dir=configs),
        knowledge=None,
        logging=FakeLogging(),
    )
    engine._cutover = SimpleNamespace(snapshot=lambda: events.append("cutover"))
    engine.sync_lifecycle = lambda **_kwargs: {}

    result = engine.run_bootstrap(youtube=True, discord=True)

    assert result["ok"] is True
    assert result["resumed"] is True
    assert values.selected_service_ids == ["discord", "youtube"]
    # Resume rebuilds snapshot then soft-starts (no hard stop when seamless API absent).
    assert events[-3:] == ["snapshot", "start:zapret", "cutover"]
