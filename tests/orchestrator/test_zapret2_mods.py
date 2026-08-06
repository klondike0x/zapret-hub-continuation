from __future__ import annotations

from pathlib import Path

from zapret_hub.services.orchestrator import zapret2_hub
from zapret_hub.services.zapret2_mods import Zapret2ModsManager


def test_merge_mod_overlays_appends_lists(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    paths = zapret2_hub.ensure_zapret2_lists(configs)
    paths["hub"].write_text("youtube.com\n", encoding="utf-8")

    mod = tmp_path / "mods_zapret2" / "demo"
    (mod / "lists").mkdir(parents=True)
    (mod / "lists" / "list-general.txt").write_text("discord.com\nyoutube.com\n", encoding="utf-8")
    (mod / "lists" / "ipset-all.txt").write_text("1.2.3.4\n", encoding="utf-8")
    (mod / "extra.lua").write_text("-- demo\n", encoding="utf-8")

    result = zapret2_hub.merge_mod_overlays(configs, [mod])
    assert result["domains"] == 2
    assert result["ips"] == 1
    hub = paths["hub"].read_text(encoding="utf-8")
    assert "discord.com" in hub
    assert "youtube.com" in hub
    assert "# --- zapret-hub-mod-overlays ---" in hub
    assert (paths["hub"].parent / "mod_lua" / "demo__extra.lua").exists()

    # Second merge with no mods clears overlay section.
    zapret2_hub.merge_mod_overlays(configs, [])
    hub2 = paths["hub"].read_text(encoding="utf-8")
    assert "discord.com" not in hub2
    assert "youtube.com" in hub2
    assert "# --- zapret-hub-mod-overlays ---" not in hub2


def test_full_mod_profile_preserves_profile_order_and_resolves_assets(tmp_path: Path) -> None:
    configs = tmp_path / "configs"
    mod = tmp_path / "mods_zapret2" / "youtube-discord"
    (mod / "profiles").mkdir(parents=True)
    (mod / "lua").mkdir()
    (mod / "bin").mkdir()
    (mod / "lists").mkdir()
    (mod / "windivert.filter").mkdir()
    (mod / "lua" / "zapret-lib.lua").write_text("-- lib\n", encoding="utf-8")
    (mod / "bin" / "fake_tls.bin").write_bytes(b"fake")
    (mod / "lists" / "discord.txt").write_text("discord.com\n", encoding="utf-8")
    (mod / "windivert.filter" / "discord.txt").write_text("udp\n", encoding="utf-8")
    profile = mod / "profiles" / "general.txt"
    profile.write_text(
        "\n".join(
            (
                "--lua-init=@lua/zapret-lib.lua",
                "--wf-raw-part=@windivert.filter/discord.txt",
                "--blob=tls:@bin/fake_tls.bin",
                "--hostlist=lists/discord.txt",
                "--filter-tcp=443",
                "--lua-desync=multisplit:pos=1",
            )
        ),
        encoding="utf-8",
    )

    result = zapret2_hub.merge_mod_overlays(configs, [mod])
    assert result["profile"] == str(profile.resolve())
    assert zapret2_hub.active_mod_profile(configs) == profile.resolve()

    args = zapret2_hub.build_mod_profile_args(profile)
    assert args[0] == f"--lua-init=@{mod / 'lua' / 'zapret-lib.lua'}"
    assert args[1] == f"--wf-raw-part=@{mod / 'windivert.filter' / 'discord.txt'}"
    assert args[2] == f"--blob=tls:@{mod / 'bin' / 'fake_tls.bin'}"
    assert args[3] == f"--hostlist={mod / 'lists' / 'discord.txt'}"
    assert args[-1] == "--lua-desync=multisplit:pos=1"

    zapret2_hub.merge_mod_overlays(configs, [])
    assert zapret2_hub.active_mod_profile(configs) is None


def test_zapret2_mods_manager_enable_merge(tmp_path: Path, monkeypatch) -> None:
    class Paths:
        mods_zapret2_dir = tmp_path / "mods_zapret2"
        data_dir = tmp_path / "data"
        configs_dir = tmp_path / "configs"
        mods_dir = tmp_path / "mods"

    class Storage:
        def __init__(self) -> None:
            self.paths = Paths()
            self.paths.data_dir.mkdir(parents=True)
            self.paths.mods_zapret2_dir.mkdir(parents=True)
            self._json: dict[str, object] = {}

        def write_json(self, path, payload) -> None:
            self._json[str(path)] = payload
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            import json

            Path(path).write_text(json.dumps(payload), encoding="utf-8")

        def read_json(self, path, default=None):
            import json

            p = Path(path)
            if not p.exists():
                return default
            return json.loads(p.read_text(encoding="utf-8"))

    class Settings:
        def __init__(self) -> None:
            self.enabled_zapret2_mod_ids: list[str] = []

        def update(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

        def get(self):
            return self

    class Logging:
        def log(self, *args, **kwargs) -> None:
            return None

    storage = Storage()
    settings = Settings()
    mgr = Zapret2ModsManager(storage, Logging(), settings)  # type: ignore[arg-type]
    entry = mgr.create_empty(name="Test Mod")
    assert entry.enabled is False
    mgr.set_enabled(entry.id, True)
    assert entry.id in settings.enabled_zapret2_mod_ids
    hub = Path(storage.paths.configs_dir) / "zapret2" / "list-hub.txt"
    assert hub.exists()
