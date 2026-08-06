from pathlib import Path
import zipfile
import tempfile

from zapret_hub.services.zapret2_mods import Zapret2ModsManager


def test_zapret2_zip_filters_executables(tmp_path: Path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("lists/list-general.txt", "youtube.com\n")
        archive.writestr("helper.lua", "return {}\n")
        archive.writestr("bin/fake_tls.bin", "payload")
        archive.writestr("windivert.filter/windivert_part.discord_media.txt", "udp")
        archive.writestr("WinDivert.dll", "dll")
        archive.writestr("tool.exe", "exe")
        archive.writestr("driver.sys", "sys")
        archive.writestr("readme.txt", "docs")

    class _Paths:
        data_dir = tmp_path / "data"
        mods_dir = tmp_path / "mods"
        configs_dir = tmp_path / "configs"
        mods_zapret2_dir = tmp_path / "mods2"

    class _Storage:
        paths = _Paths()

        def __init__(self):
            self.paths.data_dir.mkdir(parents=True, exist_ok=True)
            self.paths.mods_dir.mkdir(parents=True, exist_ok=True)
            self.paths.configs_dir.mkdir(parents=True, exist_ok=True)
            self.paths.mods_zapret2_dir.mkdir(parents=True, exist_ok=True)

        def read_json(self, path, default=None):
            return default if default is not None else []

        def write_json(self, path, payload):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            import json
            Path(path).write_text(json.dumps(payload), encoding="utf-8")

    class _Logging:
        def log(self, *args, **kwargs):
            pass

    class _Settings:
        def update(self, **kwargs):
            pass

        def get(self):
            return type("S", (), {"enabled_zapret2_mod_ids": []})()

    mgr = Zapret2ModsManager(_Storage(), _Logging(), _Settings())
    entry = mgr.import_from_path(zip_path)
    root = Path(entry.path)
    assert (root / "lists" / "list-general.txt").exists()
    assert (root / "helper.lua").exists()
    assert (root / "bin" / "fake_tls.bin").exists()
    assert (root / "windivert.filter" / "windivert_part.discord_media.txt").exists()
    assert not (root / "WinDivert.dll").exists()
    assert not (root / "tool.exe").exists()
    assert not (root / "driver.sys").exists()
    assert not (root / "readme.txt").exists()
