from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from zapret_hub.services.updates import UpdatesManager


MIRROR_FIXTURE = {
    "product": "Zapret Hub",
    "version": "2.1.2",
    "tag": "v2.1.2",
    "changelog": "• Fix one\n• Fix two",
    "github_url": "https://github.com/goshkow/Zapret-Hub/releases/tag/v2.1.2",
    "published_at": "2026-06-01T12:00:00Z",
    "binary_updated_at": "2026-06-01T12:30:00Z",
    "assets": {
        "installer": {
            "name": "Zapret_Hub_Setup_2.1.2.exe",
            "download_url": "https://goshkow.com/zapret-hub/installer",
            "digest": "sha256:aaa",
            "size": 10,
        },
        "x64": {
            "name": "zapret_hub_2.1.2_portable_win_x64.zip",
            "download_url": "https://goshkow.com/zapret-hub/x64",
            "digest": "sha256:bbb",
            "size": 20,
            "updated_at": "2026-06-01T12:30:00Z",
        },
        "arm64": {
            "name": "zapret_hub_2.1.2_portable_win_arm64.zip",
            "download_url": "https://goshkow.com/zapret-hub/arm64",
            "digest": "sha256:ccc",
            "size": 21,
        },
    },
}


def test_normalize_mirror_payload_maps_download_urls() -> None:
    mgr = UpdatesManager.__new__(UpdatesManager)
    entries = UpdatesManager._normalize_release_entries(mgr, MIRROR_FIXTURE)
    assert len(entries) == 1
    assert entries[0]["version"] == "2.1.2"
    assert "Fix one" in str(entries[0]["body"])
    assets = entries[0]["payload"]["assets"]  # type: ignore[index]
    assert isinstance(assets, list)
    by_arch = {str(item.get("architecture")): item for item in assets}
    assert by_arch["x64"]["browser_download_url"] == "https://goshkow.com/zapret-hub/x64"
    assert by_arch["arm64"]["browser_download_url"] == "https://goshkow.com/zapret-hub/arm64"


def test_mirror_release_index_is_normalized_to_exact_github_tag() -> None:
    mgr = UpdatesManager.__new__(UpdatesManager)
    payload = {**MIRROR_FIXTURE, "github_url": "https://github.com/goshkow/Zapret-Hub/releases"}

    entries = UpdatesManager._normalize_release_entries(mgr, payload)

    assert entries[0]["html_url"] == "https://github.com/goshkow/Zapret-Hub/releases/tag/v2.1.2"


def test_pick_release_asset_prefers_architecture_key(monkeypatch) -> None:
    mgr = UpdatesManager.__new__(UpdatesManager)
    entries = UpdatesManager._normalize_release_entries(mgr, MIRROR_FIXTURE)
    assets = entries[0]["payload"]["assets"]  # type: ignore[index]
    monkeypatch.setattr("zapret_hub.services.updates.platform.machine", lambda: "AMD64")
    picked = UpdatesManager._pick_release_asset(mgr, assets)  # type: ignore[arg-type]
    assert picked is not None
    assert picked["architecture"] == "x64"
    assert picked["browser_download_url"] == "https://goshkow.com/zapret-hub/x64"


def test_pick_release_asset_arm(monkeypatch) -> None:
    mgr = UpdatesManager.__new__(UpdatesManager)
    entries = UpdatesManager._normalize_release_entries(mgr, MIRROR_FIXTURE)
    assets = entries[0]["payload"]["assets"]  # type: ignore[index]
    monkeypatch.setattr("zapret_hub.services.updates.platform.machine", lambda: "ARM64")
    picked = UpdatesManager._pick_release_asset(mgr, assets)  # type: ignore[arg-type]
    assert picked is not None
    assert picked["architecture"] == "arm64"


def test_version_compare_available_and_uptodate(monkeypatch) -> None:
    mgr = UpdatesManager.__new__(UpdatesManager)
    mgr.REPO_URL = UpdatesManager.REPO_URL
    monkeypatch.setattr("zapret_hub.services.updates.__version__", "2.0.0")
    monkeypatch.setattr(UpdatesManager, "_installed_build_timestamp", lambda self: None)
    status = UpdatesManager._build_application_release_status(mgr, MIRROR_FIXTURE)
    assert status["status"] == "available"
    assert status["latest_version"] == "2.1.2"
    assert status["asset_url"] == "https://goshkow.com/zapret-hub/x64"
    assert status["asset_digest"].endswith("bbb") or "bbb" in status["asset_digest"]

    monkeypatch.setattr("zapret_hub.services.updates.__version__", "9.9.9")
    status2 = UpdatesManager._build_application_release_status(mgr, MIRROR_FIXTURE)
    assert status2["status"] == "up-to-date"


def test_same_version_hotfix_uses_archive_digest(monkeypatch) -> None:
    mgr = UpdatesManager.__new__(UpdatesManager)
    mgr.REPO_URL = UpdatesManager.REPO_URL
    monkeypatch.setattr("zapret_hub.services.updates.__version__", "2.1.2")
    monkeypatch.setattr(
        UpdatesManager,
        "_installed_build_timestamp",
        lambda self: datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        UpdatesManager,
        "_installed_release_identity",
        lambda self: {"version": "2.1.2", "digest": "old-digest"},
    )

    status = UpdatesManager._build_application_release_status(mgr, MIRROR_FIXTURE)

    assert status["status"] == "available"
    assert status["is_hotfix"] is True
    assert status["asset_digest"].endswith("bbb")


def test_same_version_same_digest_is_up_to_date(monkeypatch) -> None:
    mgr = UpdatesManager.__new__(UpdatesManager)
    mgr.REPO_URL = UpdatesManager.REPO_URL
    monkeypatch.setattr("zapret_hub.services.updates.__version__", "2.1.2")
    monkeypatch.setattr(
        UpdatesManager,
        "_installed_build_timestamp",
        lambda self: datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        UpdatesManager,
        "_installed_release_identity",
        lambda self: {"version": "2.1.2", "digest": "bbb"},
    )

    status = UpdatesManager._build_application_release_status(mgr, MIRROR_FIXTURE)

    assert status["status"] == "up-to-date"
    assert status["is_hotfix"] is False


def test_same_version_without_identity_does_not_false_hotfix(monkeypatch) -> None:
    """Mirror timestamps + preserved zip mtimes must not loop forever as hotfixes."""
    mgr = UpdatesManager.__new__(UpdatesManager)
    mgr.REPO_URL = UpdatesManager.REPO_URL
    monkeypatch.setattr("zapret_hub.services.updates.__version__", "2.1.2")
    monkeypatch.setattr(
        UpdatesManager,
        "_installed_build_timestamp",
        lambda self: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(UpdatesManager, "_installed_release_identity", lambda self: {})

    status = UpdatesManager._build_application_release_status(mgr, MIRROR_FIXTURE)

    assert status["status"] == "up-to-date"
    assert status["is_hotfix"] is False


def test_find_payload_exe_accepts_title_case(tmp_path) -> None:
    mgr = UpdatesManager.__new__(UpdatesManager)
    root = tmp_path / "payload"
    root.mkdir()
    (root / "Zapret_Hub.exe").write_bytes(b"mz")
    found = UpdatesManager._find_payload_exe(mgr, root)
    assert found is not None
    assert found.name.lower() == "zapret_hub.exe"
    assert UpdatesManager._resolve_payload_root(mgr, root) == root


def test_download_bytes_reports_content_progress(monkeypatch) -> None:
    class Response:
        headers = {"Content-Length": "6"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int) -> bytes:
            return self.parts.pop(0)

        parts = [b"abc", b"def", b""]

    mgr = UpdatesManager.__new__(UpdatesManager)
    monkeypatch.setattr("zapret_hub.services.updates.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(UpdatesManager, "_run_with_deadline", lambda _self, fn, timeout: fn())
    progress: list[tuple[int, int]] = []

    payload = mgr._download_bytes("https://example.test/update.zip", timeout=120, progress_callback=lambda done, total: progress.append((done, total)))

    assert payload == b"abcdef"
    assert progress == [(0, 6), (3, 6), (6, 6)]


def test_download_accepts_stale_mirror_size_when_response_size_is_authoritative(tmp_path, monkeypatch) -> None:
    class Response:
        headers = {"Content-Length": "6"}
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int) -> bytes:
            return self.parts.pop(0)

        parts = [b"abc", b"def", b""]

    mgr = UpdatesManager.__new__(UpdatesManager)
    target = tmp_path / "update.zip"
    monkeypatch.setattr("zapret_hub.services.updates.urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(UpdatesManager, "_run_with_deadline", lambda _self, fn, timeout: fn())

    UpdatesManager._download_to_path(
        mgr,
        "https://example.test/update.zip",
        target,
        timeout=120,
        expected_size=9,
        strict_size=False,
    )

    assert target.read_bytes() == b"abcdef"


def test_update_helper_uses_fast_literal_copy_and_restart_retries(tmp_path, monkeypatch) -> None:
    install_root = tmp_path / "install"
    source_root = tmp_path / "payload"
    source_root.mkdir()
    temp_root = tmp_path / "download"
    temp_root.mkdir()
    script_root = tmp_path / "scripts"

    mgr = UpdatesManager.__new__(UpdatesManager)
    mgr.storage = SimpleNamespace(paths=SimpleNamespace(install_root=install_root, data_dir=install_root / "data"))
    mgr.logging = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    monkeypatch.setattr("zapret_hub.services.updates.tempfile.gettempdir", lambda: str(script_root.parent))
    monkeypatch.setattr("zapret_hub.services.updates.subprocess.Popen", lambda *_args, **_kwargs: SimpleNamespace())
    monkeypatch.setattr(UpdatesManager, "_write_installed_release_identity", lambda *_args, **_kwargs: None)

    mgr.launch_update(
        {
            "extract_root": str(source_root),
            "temp_root": str(temp_root),
            "version": "3.0.0",
            "asset_digest": "sha256:test",
            "release_updated_at": "2026-07-22T12:00:00Z",
        }
    )

    scripts = list((script_root.parent / "zapret_hub_updates").glob("apply_update_*.ps1"))
    assert len(scripts) == 1
    script = scripts[0].read_text(encoding="utf-8")
    assert "ZapretHubApplicationUpdater" in script
    assert "& robocopy @robocopyArgs" in script
    assert "Copy-Item -LiteralPath" in script
    assert "$attempt -le 3" in script
    assert "Start-Process -FilePath $launch" in script
    assert "Test-UpdateTargetWritable" in script
    assert "requesting administrator rights for protected install folder" in script
    assert "elevated updater did not become ready" in script
    assert "helper bootstrap started" in script
    assert "-ExecutionPolicy', 'Bypass'" in script
    assert "Test-RelaunchedApp" in script
    assert "Set-Content -LiteralPath $readyPath" in script
    assert "-Verb RunAs" in script
    assert script.index("requesting administrator rights for protected install folder") < script.index(
        "ZapretHubApplicationUpdater"
    )
    assert script.index("Set-Content -LiteralPath $readyPath") > script.index("ZapretHubApplicationUpdater")
