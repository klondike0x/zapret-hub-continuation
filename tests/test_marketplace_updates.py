from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import hashlib
import threading
import time
import urllib.request
import zipfile

import pytest

from zapret_hub.services.marketplace import MarketplaceError, MarketplaceService


def test_version_compare():
    svc = MarketplaceService.__new__(MarketplaceService)
    assert svc._is_newer("1.2.0", "1.1.9")
    assert svc._is_newer("2.0.0", "1.9.9")
    assert not svc._is_newer("1.0.0", "1.0.0")
    assert not svc._is_newer("1.0.0", "1.0.1")


def test_marketplace_card_reads_nested_latest_version_size() -> None:
    svc = MarketplaceService.__new__(MarketplaceService)
    card = svc._normalize_card(
        {
            "id": 3,
            "slug": "sample",
            "title": "Sample",
            "latest_version": {"version": "2.1.0", "size": 6_919_188},
        }
    )
    assert card["latestVersionSize"] == 6_919_188
    version = svc._normalize_version({"id": 4, "version": "2.1.0", "file_size": 6_919_188})
    assert version["size"] == 6_919_188


def test_repair_installed_covers_replaces_stale_file_url(monkeypatch, tmp_path: Path) -> None:
    entry = SimpleNamespace(
        id="z2-demo",
        path=str(tmp_path / "z2-demo"),
        icon_url="file:///C:/deleted/zapret-hub-cover.img",
        marketplace_slug="z2-demo",
    )

    class Manager:
        def __init__(self) -> None:
            self.updated = ""

        def list_installed(self):
            return [entry]

        def update_metadata(self, mod_id, *, icon_url):
            assert mod_id == "z2-demo"
            self.updated = icon_url

    manager = Manager()
    svc = MarketplaceService.__new__(MarketplaceService)
    svc.mods = None
    svc.mods2 = manager
    monkeypatch.setattr(svc, "get_project", lambda slug, lang="ru": {"project": {"iconUrl": "https://cdn.example/cover.webp"}})
    monkeypatch.setattr(svc, "_cache_cover_image", lambda path, url: url)
    monkeypatch.setattr(svc, "_log", lambda *args, **kwargs: None)

    assert svc.repair_installed_covers() == 1
    assert manager.updated == "https://cdn.example/cover.webp"


def test_dismiss_until_newer(tmp_path):
    class Paths:
        data_dir = tmp_path
        cache_dir = tmp_path / "cache"

    class Logging:
        def log(self, *a, **k):
            pass

    svc = MarketplaceService(storage_paths=Paths(), logging=Logging(), mods=None, mods2=None)
    svc._update_cache = {
        "youtube-flow": {"slug": "youtube-flow", "latestVersion": "1.1.0", "title": "YT"},
    }
    svc.dismiss_updates([{"slug": "youtube-flow", "latestVersion": "1.1.0"}])
    assert svc._dismissals["youtube-flow"] == "1.1.0"

    # Same latest should not notify.
    svc._update_cache = {
        "youtube-flow": {
            "slug": "youtube-flow",
            "latestVersion": "1.1.0",
            "currentVersion": "1.0.0",
            "title": "YT",
        }
    }
    # Simulate notify filter
    notify = []
    for row in svc._update_cache.values():
        dismissed = svc._dismissals.get(row["slug"], "")
        if not dismissed or svc._is_newer(row["latestVersion"], dismissed):
            notify.append(row)
    assert notify == []

    # Newer release should notify again.
    row = {
        "slug": "youtube-flow",
        "latestVersion": "1.2.0",
        "currentVersion": "1.0.0",
        "title": "YT",
    }
    dismissed = svc._dismissals.get(row["slug"], "")
    assert svc._is_newer(row["latestVersion"], dismissed)


def test_download_queue_completes_download_and_install(monkeypatch, tmp_path: Path) -> None:
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("general-test.bat", "@echo off\n")
    payload = archive_buffer.getvalue()

    class Response:
        status = 200
        headers = {"Content-Length": str(len(payload))}

        def __init__(self) -> None:
            self._offset = 0

        def getcode(self) -> int:
            return self.status

        def read(self, size: int = -1) -> bytes:
            if self._offset >= len(payload):
                return b""
            end = len(payload) if size < 0 else min(len(payload), self._offset + size)
            chunk = payload[self._offset:end]
            self._offset = end
            return chunk

        def close(self) -> None:
            return None

    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    class Mods:
        def __init__(self) -> None:
            self.imported: list[Path] = []
            self.installed: list[SimpleNamespace] = []

        def list_installed(self) -> list[object]:
            return list(self.installed)

        def import_from_path(self, path: str) -> object:
            imported = Path(path)
            self.imported.append(imported)
            installed = tmp_path / "installed" / "market-test"
            installed.mkdir(parents=True, exist_ok=True)
            entry = SimpleNamespace(
                id="market-test",
                path=installed,
                name="Market test",
                description="",
                author="",
                version="1.0.0",
                marketplace_slug="",
            )
            self.installed.append(entry)
            return entry

        def update_metadata(self, mod_id: str, **metadata) -> object:
            entry = next(item for item in self.installed if item.id == mod_id)
            for key, value in metadata.items():
                setattr(entry, key, value)
            return entry

        def remove(self, mod_id: str) -> None:
            self.installed = [item for item in self.installed if item.id != mod_id]

    events: list[tuple[str, dict[str, object]]] = []
    completed = threading.Event()

    def on_event(name: str, event_payload: dict[str, object]) -> None:
        events.append((name, event_payload))
        if name == "marketplace.download-progress" and event_payload.get("status") == "done":
            completed.set()

    mods = Mods()
    service = MarketplaceService(storage_paths=Paths(), logging=Logging(), mods=mods, on_event=on_event)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        service,
        "_create_ticket",
        lambda *_args, **_kwargs: {
            "filename": "market-test.zip",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "direct_url": "https://example.test/market-test.zip",
            "fallback_url": "",
            "ticket": "ticket-1",
        },
    )
    monkeypatch.setattr(service, "_complete_ticket", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "fetch_latest", lambda *_args, **_kwargs: {"version": "1.0.0", "compatibility": "zapret"})
    monkeypatch.setattr(service, "get_project", lambda *_args, **_kwargs: {"project": {}})

    queued = service.enqueue_download("market-test", title="Market test", compatibility="zapret")

    assert queued["queued"] is True
    assert completed.wait(3), events
    assert mods.imported
    assert mods.installed[0].marketplace_slug == "market-test"
    assert mods.installed[0].path.exists()
    assert any(name == "marketplace.download-progress" and data.get("status") == "installing" for name, data in events)
    assert any(name == "marketplace.download-progress" and data.get("status") == "done" for name, data in events)
    deadline = time.monotonic() + 2
    snapshot = service.queue_status()
    while snapshot["busy"] and time.monotonic() < deadline:
        time.sleep(0.01)
        snapshot = service.queue_status()
    assert snapshot["installRevision"] == 1
    assert snapshot["lastCompleted"] == {
        "revision": 1,
        "slug": "market-test",
        "modId": "market-test",
        "compatibility": "zapret",
    }


def test_remove_installed_marketplace_mod(tmp_path: Path) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    class Mods:
        def __init__(self) -> None:
            self.installed = [SimpleNamespace(id="mod-1", marketplace_slug="market-test")]

        def list_installed(self) -> list[object]:
            return list(self.installed)

        def remove(self, mod_id: str) -> None:
            self.installed = [item for item in self.installed if item.id != mod_id]

    mods = Mods()
    service = MarketplaceService(storage_paths=Paths(), logging=Logging(), mods=mods)

    result = service.remove_installed("market-test")

    assert result == {"ok": True, "slug": "market-test", "removed": ["mod-1"]}
    assert mods.installed == []


def test_enqueue_rejects_already_installed_same_version(tmp_path: Path) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    installed = SimpleNamespace(
        id="mod-1",
        name="Installed",
        author="",
        description="",
        icon_url="",
        source_url="",
        version="1.0.0",
        marketplace_slug="market-test",
    )
    mods = SimpleNamespace(list_installed=lambda: [installed])
    service = MarketplaceService(storage_paths=Paths(), logging=Logging(), mods=mods)

    result = service.enqueue_download("market-test")

    assert result["queued"] is False
    assert result["alreadyInstalled"] is True
    assert result["modId"] == "mod-1"
    assert service.queue_status()["items"] == []


def test_enqueue_allows_update_when_newer_version_available(tmp_path: Path, monkeypatch) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        mods_dir = tmp_path / "mods"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    installed = SimpleNamespace(
        id="mod-1",
        name="Installed",
        author="",
        description="",
        icon_url="",
        source_url="",
        version="2.10~4",
        marketplace_slug="shizapret-mod",
        enabled=True,
    )
    mods = SimpleNamespace(list_installed=lambda: [installed])
    service = MarketplaceService(storage_paths=Paths(), logging=Logging(), mods=mods)
    service._update_cache["shizapret-mod"] = {
        "slug": "shizapret-mod",
        "latestVersion": "2.10~5",
        "versionId": 42,
        "compatibility": "zapret",
    }
    monkeypatch.setattr(service, "_ensure_install_space", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_ensure_worker", lambda: None)
    monkeypatch.setattr(service, "_emit_job", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_emit_queue", lambda: None)

    result = service.enqueue_download(
        "shizapret-mod",
        marketplace_version="2.10~5",
        allow_update=True,
    )

    assert result["queued"] is True
    assert result.get("updating") is True
    assert result.get("jobId")
    assert any(item["slug"] == "shizapret-mod" for item in service.queue_status()["items"])
    job = next(job for job in service._jobs if job.slug == "shizapret-mod")
    assert job.replace_existing is True
    assert job.restore_enabled is True


def test_update_removes_then_redownloads(monkeypatch, tmp_path: Path) -> None:
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("general-test.bat", "@echo off\n")
    payload = archive_buffer.getvalue()

    class Response:
        status = 200
        headers = {"Content-Length": str(len(payload))}

        def __init__(self) -> None:
            self._offset = 0

        def getcode(self) -> int:
            return self.status

        def read(self, size: int = -1) -> bytes:
            if self._offset >= len(payload):
                return b""
            end = len(payload) if size < 0 else min(len(payload), self._offset + size)
            chunk = payload[self._offset:end]
            self._offset = end
            return chunk

        def close(self) -> None:
            return None

    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        mods_dir = tmp_path / "mods"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    class Mods:
        def __init__(self) -> None:
            self.removed: list[str] = []
            self.enabled_calls: list[tuple[str, bool]] = []
            self.installed = [
                SimpleNamespace(
                    id="old-mod",
                    path=tmp_path / "installed" / "old-mod",
                    name="Old",
                    description="",
                    author="",
                    version="1.0.0",
                    marketplace_slug="market-test",
                    enabled=False,
                )
            ]
            (tmp_path / "installed" / "old-mod").mkdir(parents=True, exist_ok=True)

        def list_installed(self) -> list[object]:
            return list(self.installed)

        def remove(self, mod_id: str) -> None:
            self.removed.append(mod_id)
            self.installed = [item for item in self.installed if item.id != mod_id]

        def import_from_path(self, path: str) -> object:
            installed = tmp_path / "installed" / "market-test"
            installed.mkdir(parents=True, exist_ok=True)
            entry = SimpleNamespace(
                id="market-test",
                path=installed,
                name="Market test",
                description="",
                author="",
                version="1.0.0",
                marketplace_slug="",
                enabled=True,
            )
            self.installed.append(entry)
            return entry

        def update_metadata(self, mod_id: str, **metadata) -> object:
            entry = next(item for item in self.installed if item.id == mod_id)
            for key, value in metadata.items():
                setattr(entry, key, value)
            return entry

        def set_enabled(self, mod_id: str, enabled: bool) -> object:
            self.enabled_calls.append((mod_id, enabled))
            entry = next(item for item in self.installed if item.id == mod_id)
            entry.enabled = enabled
            return entry

    events: list[tuple[str, dict[str, object]]] = []
    completed = threading.Event()
    removed_before_download = threading.Event()

    def on_event(name: str, event_payload: dict[str, object]) -> None:
        events.append((name, event_payload))
        if name == "marketplace.download-progress" and event_payload.get("status") == "done":
            completed.set()

    mods = Mods()
    service = MarketplaceService(storage_paths=Paths(), logging=Logging(), mods=mods, on_event=on_event)
    service._update_cache["market-test"] = {
        "slug": "market-test",
        "latestVersion": "1.1.0",
        "versionId": 9,
        "compatibility": "zapret",
    }

    original_create = service._create_ticket

    def create_ticket_after_remove(*args, **kwargs):
        assert mods.removed == ["old-mod"], "update must delete installed mod before download ticket"
        removed_before_download.set()
        return {
            "filename": "market-test.zip",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "direct_url": "https://example.test/market-test.zip",
            "fallback_url": "",
            "ticket": "ticket-upd",
            "version": "1.1.0",
        }

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(service, "_create_ticket", create_ticket_after_remove)
    monkeypatch.setattr(service, "_complete_ticket", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "fetch_latest", lambda *_args, **_kwargs: {"version": "1.1.0", "compatibility": "zapret"})
    monkeypatch.setattr(service, "get_project", lambda *_args, **_kwargs: {"project": {}})
    del original_create

    queued = service.enqueue_download(
        "market-test",
        title="Market test",
        compatibility="zapret",
        marketplace_version="1.1.0",
        allow_update=True,
    )
    assert queued["queued"] is True
    assert queued.get("updating") is True
    assert completed.wait(3), events
    assert removed_before_download.is_set()
    assert mods.removed == ["old-mod"]
    assert mods.enabled_calls == [("market-test", False)]
    assert mods.installed[0].marketplace_slug == "market-test"
    assert mods.installed[0].version == "1.1.0"


def test_recover_stale_busy_unblocks_queue(tmp_path: Path) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        mods_dir = tmp_path / "mods"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    service = MarketplaceService(storage_paths=Paths(), logging=Logging(), mods=None)
    service._busy = True
    service._active_id = "missing-job"
    service._recover_stale_worker_state()
    assert service._busy is False
    assert service._active_id == ""


def test_enqueue_rejects_download_when_less_than_one_gib_remains(monkeypatch, tmp_path: Path) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        mods_dir = tmp_path / "mods"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    service = MarketplaceService(storage_paths=Paths(), logging=Logging())
    monkeypatch.setattr(
        "zapret_hub.services.marketplace.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=10 * 1024**3, used=9 * 1024**3, free=1024**3 - 1),
    )

    with pytest.raises(MarketplaceError) as error:
        service.enqueue_download("market-test")

    assert error.value.code == "insufficient_disk_space"
    assert service.queue_status()["items"] == []


def test_install_space_reserves_one_gib_after_archive_download(monkeypatch, tmp_path: Path) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"
        mods_dir = tmp_path / "mods"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    service = MarketplaceService(storage_paths=Paths(), logging=Logging())
    monkeypatch.setattr(
        "zapret_hub.services.marketplace.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=10 * 1024**3, used=8 * 1024**3, free=1024**3 + 100),
    )

    with pytest.raises(MarketplaceError) as error:
        service._ensure_install_space("zapret", incoming_bytes=101)

    assert error.value.code == "insufficient_disk_space"


def test_ticket_http_error_uses_verified_public_download(monkeypatch, tmp_path: Path) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    service = MarketplaceService(storage_paths=Paths(), logging=Logging())

    def reject_ticket(*_args, **_kwargs):
        raise MarketplaceError("http_error", "HTTP 403")

    monkeypatch.setattr(service, "_request_json", reject_ticket)
    monkeypatch.setattr(
        service,
        "fetch_latest",
        lambda *_args, **_kwargs: {
            "version": "2.1.0",
            "versionId": 4,
            "size": 123,
            "sha256": "abc123",
        },
    )

    ticket = service._create_ticket("shizapret_mod", version_id=None)

    assert ticket["direct_url"].endswith("/projects/shizapret_mod/download/latest")
    assert ticket["size"] == 123
    assert ticket["sha256"] == "abc123"
    assert ticket["filename"] == "shizapret_mod-2.1.0.zip"


def test_download_active_uses_fallback_url_from_error(monkeypatch, tmp_path: Path) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    service = MarketplaceService(storage_paths=Paths(), logging=Logging())

    def reject_active(*_args, **_kwargs):
        raise MarketplaceError(
            "download_active",
            "busy",
            details={"fallback_url": "/zapret-hub/marketplace/download/4"},
        )

    monkeypatch.setattr(service, "_request_json", reject_active)
    monkeypatch.setattr(
        service,
        "fetch_latest",
        lambda *_args, **_kwargs: {
            "version": "2.1.0",
            "versionId": 4,
            "size": 123,
            "sha256": "abc123",
        },
    )

    ticket = service._create_ticket("shizapret_mod", version_id=4)
    assert ticket["direct_url"].endswith("/zapret-hub/marketplace/download/4")
    assert ticket["ticket"] == ""


def test_download_tries_absolute_fallback_after_marketplace_error(monkeypatch, tmp_path: Path) -> None:
    service = MarketplaceService.__new__(MarketplaceService)
    service.DOWNLOAD_ATTEMPTS = 2
    service.DOWNLOAD_WALL_SEC = 30.0
    service.DOWNLOAD_STALL_SEC = 5.0
    calls: list[tuple[str, int]] = []

    def stream(url: str, _target: Path, *, resume_from: int, job=None) -> None:
        del job
        calls.append((url, resume_from))
        if len(calls) == 1:
            raise MarketplaceError("network_error", "CDN rejected request")

    monkeypatch.setattr(service, "_stream_to_file", stream)
    monkeypatch.setattr(service, "_log", lambda *_args, **_kwargs: None)

    service._download_file(
        [
            "https://download.goshkow.com/file.zip",
            "/zapret-hub/marketplace/download/4",
        ],
        tmp_path / "mod.zip",
        expected_size=0,
    )

    assert calls[0] == ("https://download.goshkow.com/file.zip", 0)
    assert calls[1][0] == "https://goshkow.com/zapret-hub/marketplace/download/4"


def test_download_resumes_partial_with_range(monkeypatch, tmp_path: Path) -> None:
    service = MarketplaceService.__new__(MarketplaceService)
    service.DOWNLOAD_ATTEMPTS = 3
    service.DOWNLOAD_WALL_SEC = 30.0
    service.DOWNLOAD_STALL_SEC = 5.0
    target = tmp_path / "mod.partial.zip"
    target.write_bytes(b"hello")
    calls: list[int] = []

    def stream(url: str, path: Path, *, resume_from: int, job=None) -> None:
        del url, job
        calls.append(resume_from)
        if resume_from == 5:
            with path.open("ab") as handle:
                handle.write(b" world")
            return
        raise MarketplaceError("timeout", "stall")

    monkeypatch.setattr(service, "_stream_to_file", stream)
    monkeypatch.setattr(service, "_log", lambda *_args, **_kwargs: None)

    service._download_file(
        ["https://download.goshkow.com/file.zip"],
        target,
        expected_size=11,
    )

    assert calls == [5]
    assert target.read_bytes() == b"hello world"


def test_complete_ticket_failure_does_not_break_install(monkeypatch, tmp_path: Path) -> None:
    archive_buffer = BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("general-test.bat", "@echo off\n")
    payload = archive_buffer.getvalue()

    class Response:
        status = 200
        headers = {"Content-Length": str(len(payload))}

        def __init__(self) -> None:
            self._offset = 0

        def getcode(self) -> int:
            return self.status

        def read(self, size: int = -1) -> bytes:
            if self._offset >= len(payload):
                return b""
            end = len(payload) if size < 0 else min(len(payload), self._offset + size)
            chunk = payload[self._offset:end]
            self._offset = end
            return chunk

        def close(self) -> None:
            return None

    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    class Mods:
        def __init__(self) -> None:
            self.imported: list[Path] = []
            self.installed: list[SimpleNamespace] = []

        def list_installed(self) -> list[object]:
            return list(self.installed)

        def import_from_path(self, path: str) -> object:
            imported = Path(path)
            self.imported.append(imported)
            installed = tmp_path / "installed" / "market-test"
            installed.mkdir(parents=True, exist_ok=True)
            entry = SimpleNamespace(
                id="market-test",
                path=installed,
                name="Market test",
                description="",
                author="",
                version="1.0.0",
                marketplace_slug="",
            )
            self.installed.append(entry)
            return entry

        def update_metadata(self, mod_id: str, **metadata) -> object:
            entry = next(item for item in self.installed if item.id == mod_id)
            for key, value in metadata.items():
                setattr(entry, key, value)
            return entry

        def remove(self, mod_id: str) -> None:
            self.installed = [item for item in self.installed if item.id != mod_id]

    events: list[tuple[str, dict[str, object]]] = []
    completed = threading.Event()

    def on_event(name: str, event_payload: dict[str, object]) -> None:
        events.append((name, event_payload))
        if name == "marketplace.download-progress" and event_payload.get("status") == "done":
            completed.set()

    mods = Mods()
    service = MarketplaceService(storage_paths=Paths(), logging=Logging(), mods=mods, on_event=on_event)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        service,
        "_create_ticket",
        lambda *_args, **_kwargs: {
            "filename": "market-test.zip",
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "direct_url": "https://example.test/market-test.zip",
            "fallback_url": "",
            "legacy_fallback_url": "",
            "ticket": "ticket-1",
            "version": "1.0.0",
        },
    )

    def boom(*_args, **_kwargs):
        raise MarketplaceError("timeout", "complete hung")

    monkeypatch.setattr(service, "_complete_ticket", boom)
    monkeypatch.setattr(service, "fetch_latest", lambda *_args, **_kwargs: {"version": "1.0.0", "compatibility": "zapret"})
    monkeypatch.setattr(service, "get_project", lambda *_args, **_kwargs: {"project": {}})

    queued = service.enqueue_download("market-test", title="Market test", compatibility="zapret")
    assert queued["queued"] is True
    assert completed.wait(3), events
    assert mods.installed[0].marketplace_slug == "market-test"


def test_marketplace_image_uses_content_signature_and_disk_cache(monkeypatch, tmp_path: Path) -> None:
    class Paths:
        data_dir = tmp_path / "data"
        cache_dir = tmp_path / "cache"

    class Logging:
        def log(self, *_args, **_kwargs) -> None:
            return None

    png = b"\x89PNG\r\n\x1a\n" + b"payload"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size: int = -1) -> bytes:
            return png

    calls = 0

    def urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return Response()

    service = MarketplaceService(storage_paths=Paths(), logging=Logging())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    url = "https://goshkow.com/zapret-hub/marketplace/media/project/2/icon"

    first = service.load_image_data_url(url)
    second = service.load_image_data_url(url)

    assert first == second
    assert first["dataUrl"].startswith("data:image/png;base64,")
    assert calls == 1
