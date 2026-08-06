from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from zapret_hub.domain import InstalledMod
from zapret_hub.services.components import ProcessManager
from zapret_hub.services.mods import ModsManager
from zapret_hub.services.zapret2_mods import Zapret2ModsManager
from zapret_hub.ui import web_window as web_window_module


class FakeLogging:
    def log(self, *_args, **_kwargs) -> None:
        return None


class FakeSettings:
    def __init__(self) -> None:
        self.enabled_mod_ids: list[str] = []
        self.enabled_zapret2_mod_ids: list[str] = []

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get(self):
        return self


class FakeMerge:
    def __init__(self) -> None:
        self.calls = 0

    def rebuild(self) -> None:
        self.calls += 1


class FakeStorage:
    def __init__(self, root: Path) -> None:
        self.paths = SimpleNamespace(
            data_dir=root / "data",
            mods_dir=root / "mods",
            mods_zapret2_dir=root / "mods_zapret2",
            configs_dir=root / "configs",
        )
        self.paths.data_dir.mkdir(parents=True)
        self.paths.mods_dir.mkdir(parents=True)
        self.paths.mods_zapret2_dir.mkdir(parents=True)
        self.paths.configs_dir.mkdir(parents=True)
        self._json: dict[str, object] = {}

    def write_json(self, path, payload) -> None:
        import json

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")
        self._json[str(target)] = payload

    def read_json(self, path, default=None):
        import json

        target = Path(path)
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8"))


def test_mods_set_enabled_states_batches_merge(tmp_path: Path) -> None:
    storage = FakeStorage(tmp_path)
    settings = FakeSettings()
    merge = FakeMerge()
    mgr = ModsManager(storage, FakeLogging(), merge, settings)  # type: ignore[arg-type]
    first = InstalledMod(id="a", version="1", path=str(tmp_path / "a"), enabled=False)
    second = InstalledMod(id="b", version="1", path=str(tmp_path / "b"), enabled=False)
    storage.write_json(storage.paths.data_dir / "installed_mods.json", [asdict(first), asdict(second)])

    installed = mgr.set_enabled_states({"a": True, "b": True})
    assert {item.id for item in installed if item.enabled} == {"a", "b"}
    assert settings.enabled_mod_ids == ["a", "b"]
    assert merge.calls == 1


def test_mod_reorder_can_defer_expensive_merge(tmp_path: Path) -> None:
    storage = FakeStorage(tmp_path)
    settings = FakeSettings()
    merge = FakeMerge()
    mgr = ModsManager(storage, FakeLogging(), merge, settings)  # type: ignore[arg-type]
    first = InstalledMod(id="a", version="1", path=str(tmp_path / "a"))
    second = InstalledMod(id="b", version="1", path=str(tmp_path / "b"))
    storage.write_json(storage.paths.data_dir / "installed_mods.json", [asdict(first), asdict(second)])

    reordered = mgr.reorder(["b", "a"], rebuild=False)

    assert [item.id for item in reordered] == ["b", "a"]
    assert merge.calls == 0


def test_zapret2_set_enabled_states_batches_merge(tmp_path: Path, monkeypatch) -> None:
    storage = FakeStorage(tmp_path)
    settings = FakeSettings()
    mgr = Zapret2ModsManager(storage, FakeLogging(), settings)  # type: ignore[arg-type]
    merges: list[list[str]] = []

    def fake_merge(configs_dir, roots):
        merges.append([str(path) for path in roots])
        return {"domains": 0, "ips": 0}

    monkeypatch.setattr("zapret_hub.services.orchestrator.zapret2_hub.merge_mod_overlays", fake_merge)
    first = mgr.create_empty(name="One")
    second = mgr.create_empty(name="Two")
    merges.clear()

    installed = mgr.set_enabled_states({first.id: True, second.id: True})
    assert {item.id for item in installed if item.enabled} == {first.id, second.id}
    assert settings.enabled_zapret2_mod_ids == sorted([first.id, second.id])
    assert len(merges) == 1


def test_build_zapret2_command_loads_mod_lua_and_uses_zapret2_control_mode(tmp_path: Path, monkeypatch) -> None:
    configs = tmp_path / "configs"
    hub = configs / "zapret2" / "list-hub.txt"
    hub.parent.mkdir(parents=True)
    hub.write_text("example.com\n", encoding="utf-8")
    mod_lua = hub.parent / "mod_lua"
    mod_lua.mkdir()
    lua_file = mod_lua / "demo__extra.lua"
    lua_file.write_text("-- demo\n", encoding="utf-8")

    lists = {
        "hub": hub,
        "ipset": hub.parent / "ipset-hub.txt",
        "lua_targets": hub.parent / "targets.lua",
        "lua_orch": hub.parent / "orch.lua",
        "lua_strategy": hub.parent / "strategy.lua",
    }
    for path in lists.values():
        if path.suffix == ".lua":
            path.write_text("-- stub\n", encoding="utf-8")
        elif path != hub:
            path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.prepare_zapret2_runtime_files",
        lambda *_args, **_kwargs: lists,
    )
    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.bundle_winws_root",
        lambda *_args, **_kwargs: tmp_path / "bundle",
    )
    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.find_bundle_lua",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.build_default_profile_args",
        lambda **_kwargs: ["--filter-tcp=80"],
    )
    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.materialize_auto_lists",
        lambda *_args, **_kwargs: {},
    )

    process = ProcessManager.__new__(ProcessManager)
    process.storage = SimpleNamespace(paths=SimpleNamespace(configs_dir=configs, runtime_dir=tmp_path / "runtime"))
    process.settings = SimpleNamespace(
        get=lambda: SimpleNamespace(
            zapret2_tcp_ports="80,443",
            zapret2_udp_ports="443",
            selected_service_ids=["discord"],
            zapret2_control_mode="auto",
            zapret2_raw_filter="",
            zapret2_strategy_id="balanced",
            zapret2_lua_strategy="",
        )
    )
    process._zapret2_lua_arg = lambda runtime_root, filename, **_kwargs: str(runtime_root / filename)

    winws2 = tmp_path / "winws2.exe"
    winws2.write_bytes(b"")
    command = process._build_zapret2_command(winws2, tmp_path / "runtime")

    assert any(arg.startswith("--wf-udp-out=") and "3478-3497" in arg for arg in command)
    assert f"--lua-init=@{lua_file}" in command
    assert "--lua-init=@" + str(lists["lua_targets"]) in command


def test_build_zapret2_command_uses_complete_mod_profile(tmp_path: Path, monkeypatch) -> None:
    configs = tmp_path / "configs"
    profile = tmp_path / "mod" / "profiles" / "general.txt"
    profile.parent.mkdir(parents=True)
    profile.write_text("--wf-tcp-out=80,443\n--filter-tcp=443\n", encoding="utf-8")
    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.active_mod_profile",
        lambda *_args: profile,
    )

    process = ProcessManager.__new__(ProcessManager)
    process.storage = SimpleNamespace(paths=SimpleNamespace(configs_dir=configs, runtime_dir=tmp_path / "runtime"))
    process.settings = SimpleNamespace(get=lambda: SimpleNamespace())
    process.logging = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    winws2 = tmp_path / "winws2.exe"

    command = process._build_zapret2_command(winws2, tmp_path / "runtime")
    assert command == [str(winws2), "--wf-tcp-out=80,443", "--filter-tcp=443"]


def test_build_zapret2_command_keeps_mod_lua_before_custom_strategy(tmp_path: Path, monkeypatch) -> None:
    configs = tmp_path / "configs"
    hub = configs / "zapret2" / "list-hub.txt"
    hub.parent.mkdir(parents=True)
    hub.write_text("example.com\n", encoding="utf-8")
    lua_file = hub.parent / "mod_lua" / "custom__mod.lua"
    lua_file.parent.mkdir(parents=True)
    lua_file.write_text("-- mod\n", encoding="utf-8")
    lists = {
        "hub": hub,
        "ipset": hub.parent / "ipset-hub.txt",
        "lua_targets": hub.parent / "targets.lua",
        "lua_orch": hub.parent / "orch.lua",
        "lua_strategy": hub.parent / "strategy.lua",
    }
    for path in lists.values():
        if path.suffix == ".lua":
            path.write_text("-- stub\n", encoding="utf-8")
        elif path != hub:
            path.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.prepare_zapret2_runtime_files",
        lambda *_args, **_kwargs: lists,
    )
    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.bundle_winws_root",
        lambda *_args, **_kwargs: tmp_path / "bundle",
    )
    monkeypatch.setattr(
        "zapret_hub.services.orchestrator.zapret2_hub.find_bundle_lua",
        lambda *_args, **_kwargs: None,
    )

    process = ProcessManager.__new__(ProcessManager)
    process.storage = SimpleNamespace(paths=SimpleNamespace(configs_dir=configs, runtime_dir=tmp_path / "runtime"))
    process.settings = SimpleNamespace(
        get=lambda: SimpleNamespace(
            zapret2_tcp_ports="80,443",
            zapret2_udp_ports="443",
            selected_service_ids=[],
            zapret2_control_mode="manual",
            zapret2_raw_filter="",
            zapret2_strategy_id="balanced",
            zapret2_lua_strategy="--filter-tcp=443 --dpi-desync=fake",
        )
    )
    process._zapret2_lua_arg = lambda runtime_root, filename, **_kwargs: str(runtime_root / filename)

    command = process._build_zapret2_command(tmp_path / "winws2.exe", tmp_path / "runtime")
    lua_index = command.index(f"--lua-init=@{lua_file}")
    strategy_index = command.index("--filter-tcp=443")
    assert lua_index < strategy_index
    assert str(lists["lua_targets"]) not in " ".join(command)


def test_web_bridge_batches_mod_runtime_apply() -> None:
    source = Path(web_window_module.__file__).read_text(encoding="utf-8")
    assert "def _queue_mod_runtime_apply(" in source
    assert "time.sleep(0.2)" in source
    assert "manager.set_enabled_states(valid)" in source
    assert 'self._queue_mod_runtime_refresh("zapret2")' in source
    assert 'self._queue_mod_runtime_refresh("zapret")' in source
    assert 'getattr(settings, "zapret2_control_mode"' in Path(
        __file__
    ).parents[1].joinpath("src/zapret_hub/services/components.py").read_text(encoding="utf-8")
    assert 'force_process_restart={"zapret2": normalized_backend == "zapret2"}' in source
