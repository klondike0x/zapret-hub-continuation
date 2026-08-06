from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from zapret_hub import __version__
from zapret_hub.domain import UpdateInfo
from zapret_hub.services.logging_service import LoggingManager
from zapret_hub.services.storage import StorageManager


class UpdatesManager:
    REPO_URL = "https://github.com/klondike0x/zapret-hub-continuation"
    MIRROR_UPDATE_URL = "https://api.github.com/repos/klondike0x/zapret-hub-continuation/releases?per_page=10"
    MIRROR_INFO_URL = MIRROR_UPDATE_URL
    GITHUB_RELEASES_API_URL = MIRROR_UPDATE_URL
    _EXE_NAMES = ("zapret_hub.exe", "Zapret_Hub.exe")
    # Hard ceilings so UI never sticks on "Скачиваем обновление…" forever.
    META_DEADLINE_SEC = 10.0
    DOWNLOAD_DEADLINE_SEC = 600.0
    DOWNLOAD_STALL_SEC = 75.0
    DOWNLOAD_ATTEMPTS = 5

    def __init__(
        self,
        storage: StorageManager,
        logging: LoggingManager,
        *,
        processes: object | None = None,
        settings: object | None = None,
    ) -> None:
        self.storage = storage
        self.logging = logging
        self.processes = processes
        self.settings = settings

    def _mirror_urls(self) -> tuple[str, str]:
        custom = ""
        try:
            if self.settings is not None:
                custom = str(getattr(self.settings.get(), "app_update_url", "") or "").strip()
        except Exception:
            custom = ""
        if custom:
            return custom, custom
        return self.MIRROR_UPDATE_URL, self.MIRROR_INFO_URL

    def check_updates(self) -> list[UpdateInfo]:
        app_release = self.fetch_latest_application_release()
        app_status = UpdateInfo(
            target="application",
            current_version=__version__,
            latest_version=str(app_release.get("latest_version", __version__)),
            status=str(app_release.get("status", "error")),
            changelog=str(app_release.get("body", "")),
        )

        cache_file = self.storage.paths.cache_dir / "mods_index.json"
        cache_stamp = datetime.fromtimestamp(cache_file.stat().st_mtime).isoformat() if cache_file.exists() else "missing"
        updates = [
            app_status,
            UpdateInfo(
                target="mods-index",
                current_version=cache_stamp,
                latest_version=cache_stamp,
                status="ready",
                changelog="Local sample index loaded",
            ),
        ]
        self.logging.log("info", "Update check completed", items=len(updates), app_status=app_status.status)
        return updates

    def fetch_latest_application_release(self, *, force_refresh: bool = False) -> dict[str, str]:
        payload = None if force_refresh else self._read_release_cache(max_age_seconds=600)
        using_fresh_cache = payload is not None
        cache_warning = ""
        if payload is None:
            try:
                payload = self._fetch_mirror_update()
                self._write_release_cache(payload)
            except Exception as error:
                cached_payload = self._read_release_cache(max_age_seconds=None)
                if cached_payload is not None:
                    payload = cached_payload
                    cache_warning = self._friendly_mirror_error(error)
                    self.logging.log("warning", "Using cached app release metadata", error=str(error))
                else:
                    self.logging.log("warning", "Failed to fetch latest app release", error=str(error))
                    return {
                        "status": "error",
                        "current_version": __version__,
                        "latest_version": __version__,
                        "error": self._friendly_mirror_error(error),
                        "html_url": self.REPO_URL + "/releases",
                    }
        else:
            self.logging.log("info", "Using fresh app release metadata cache")

        if payload is None:
            return {
                "status": "error",
                "current_version": __version__,
                "latest_version": __version__,
                "error": "Метаданные обновления недоступны.",
                "html_url": self.REPO_URL + "/releases",
            }

        return self._build_application_release_status(payload, using_cache=using_fresh_cache or bool(cache_warning), cache_warning=cache_warning)

    def _build_application_release_status(
        self,
        payload: object,
        *,
        using_cache: bool = False,
        cache_warning: str = "",
    ) -> dict[str, str]:
        releases = self._normalize_release_entries(payload)
        if not releases:
            return {
                "status": "error",
                "current_version": __version__,
                "latest_version": __version__,
                "error": "Зеркало не вернуло доступный релиз.",
                "html_url": self.REPO_URL + "/releases",
                "releases": [],
            }
        latest = releases[0]
        release_payload = latest["payload"]
        latest_version = str(latest["version"]).strip() or __version__
        html_url = str(latest["html_url"]).strip() or (self.REPO_URL + "/releases")
        body = str(latest["body"]).strip()
        asset = self._pick_release_asset(release_payload.get("assets") or [])
        latest_release_stamp = self._release_timestamp(latest, asset)
        installed_stamp = self._installed_build_timestamp()
        installed_identity = self._installed_release_identity()
        remote_digest = str(asset.get("digest", "") if asset else "").strip().lower().removeprefix("sha256:")
        installed_digest = str(installed_identity.get("digest") or "").strip().lower().removeprefix("sha256:")
        installed_version = str(installed_identity.get("version") or "").strip()
        is_newer_version = self._version_key(latest_version) > self._version_key(__version__)
        same_version = self._version_key(latest_version) == self._version_key(__version__)
        # Hotfixes are same version + different archive digest. Do NOT fall back to
        # exe mtime vs mirror timestamps: Copy-Item keeps zip mtimes, so a just-applied
        # update still looks "older" than binary_updated_at and loops forever.
        is_same_version_hotfix = False
        if same_version and remote_digest:
            if installed_digest:
                is_same_version_hotfix = installed_digest != remote_digest
            elif installed_version and installed_version != latest_version:
                is_same_version_hotfix = True
        status = "available" if is_newer_version or is_same_version_hotfix else "up-to-date"
        newer_releases = [
            {
                "version": str(item["version"]),
                "body": str(item["body"]),
                "html_url": str(item["html_url"]),
                "is_latest": bool(idx == 0),
                "is_hotfix": bool(idx == 0 and is_same_version_hotfix),
            }
            for idx, item in enumerate(releases)
            if self._version_key(str(item["version"])) > self._version_key(__version__) or (idx == 0 and is_same_version_hotfix)
        ]
        return {
            "status": status,
            "current_version": __version__,
            "latest_version": latest_version,
            "html_url": html_url,
            "body": body,
            "asset_name": str(asset.get("name", "")) if asset else "",
            "asset_url": str(asset.get("browser_download_url", "")) if asset else "",
            "asset_digest": str(asset.get("digest", "")) if asset else "",
            "asset_size": str(asset.get("size", "")) if asset else "",
            "is_hotfix": bool(is_same_version_hotfix),
            "release_updated_at": latest_release_stamp.isoformat() if latest_release_stamp else "",
            "installed_build_at": installed_stamp.isoformat() if installed_stamp else "",
            "installed_build_digest": installed_digest,
            "releases": newer_releases,
            "using_cache": "1" if using_cache else "",
            "cache_warning": cache_warning,
        }

    @staticmethod
    def _run_with_deadline(func, *, timeout: float):
        """Run func() with a hard wall-clock deadline on a daemon thread.

        Avoid ``ThreadPoolExecutor`` + ``future.result(timeout=...)``: on timeout
        ``shutdown(wait=True)`` can block forever while DNS/connect hangs.
        """
        box: dict[str, object] = {}
        errors: list[BaseException] = []
        done = threading.Event()

        def _target() -> None:
            try:
                box["value"] = func()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=_target, name="zapret-hub-update-net", daemon=True)
        thread.start()
        deadline = time.monotonic() + max(0.1, float(timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Источник обновлений не отвечает (таймаут)")
            if done.wait(timeout=min(0.25, remaining)):
                break
        if errors:
            raise errors[0]
        return box.get("value")

    def _request_json(self, url: str, *, timeout: int) -> object:
        sock_timeout = max(1, int(timeout))

        def _load() -> object:
            request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Zapret-Hub"})
            with urllib.request.urlopen(request, timeout=sock_timeout) as response:
                return json.loads(response.read().decode("utf-8-sig"))

        # Respect the requested timeout — do not force a 15s floor that feels like a hang.
        return self._run_with_deadline(_load, timeout=float(sock_timeout) + 1.0)

    def _fetch_mirror_update(self) -> object:
        primary, fallback = self._mirror_urls()
        mirror_error: BaseException | None = None
        try:
            return self._request_json(primary, timeout=int(self.META_DEADLINE_SEC))
        except Exception as primary_error:
            mirror_error = primary_error
            if fallback and fallback != primary:
                try:
                    return self._request_json(fallback, timeout=int(self.META_DEADLINE_SEC))
                except Exception as fallback_error:
                    mirror_error = fallback_error
            try:
                self.logging.log("warning", "Mirror unavailable, using GitHub release metadata", error=str(mirror_error))
                return self._request_json(self.GITHUB_RELEASES_API_URL, timeout=int(self.META_DEADLINE_SEC))
            except Exception:
                raise primary_error

    def _download_bytes(
        self,
        url: str,
        *,
        timeout: int,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bytes:
        """Compatibility wrapper — prefer file download with Range resume."""
        with tempfile.NamedTemporaryFile(prefix="zapret_hub_dl_", suffix=".bin", delete=False) as handle:
            temp_path = Path(handle.name)
        try:
            self._download_to_path(url, temp_path, timeout=timeout, progress_callback=progress_callback)
            return temp_path.read_bytes()
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _download_to_path(
        self,
        url: str,
        target: Path,
        *,
        timeout: int,
        expected_size: int = 0,
        strict_size: bool = True,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> None:
        """Single active file request with HTTP Range resume on reconnect."""
        stall_limit = float(self.DOWNLOAD_STALL_SEC)
        wall_limit = max(float(timeout), float(self.DOWNLOAD_DEADLINE_SEC))
        wall_started = time.monotonic()
        last_error: BaseException | None = None

        for attempt in range(1, self.DOWNLOAD_ATTEMPTS + 1):
            if time.monotonic() - wall_started >= wall_limit:
                raise TimeoutError("Загрузка обновления превысила лимит времени.")
            already = target.stat().st_size if target.exists() else 0
            if expected_size > 0 and already >= expected_size:
                if progress_callback is not None:
                    progress_callback(already, expected_size)
                return
            if progress_callback is not None and already > 0:
                progress_callback(already, expected_size or already)

            headers = {"User-Agent": "Zapret-Hub", "Accept": "*/*"}
            mode = "wb"
            resume_from = already
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"
                mode = "ab"

            try:
                request = urllib.request.Request(url, headers=headers, method="GET")
                # Stay on this thread: open+read together.
                with urllib.request.urlopen(request, timeout=stall_limit) as response:
                    status = int(getattr(response, "status", None) or 0)
                    if status <= 0:
                        getcode = getattr(response, "getcode", None)
                        if callable(getcode):
                            try:
                                status = int(getcode() or 0)
                            except Exception:
                                status = 0
                    local_resume = resume_from
                    local_mode = mode
                    if local_resume > 0 and status == 200:
                        local_mode = "wb"
                        local_resume = 0
                    total = expected_size
                    try:
                        content_length = int(response.headers.get("Content-Length") or 0)
                    except Exception:
                        content_length = 0
                    if (
                        not strict_size
                        and local_resume == 0
                        and expected_size > 0
                        and content_length > 0
                        and content_length != expected_size
                    ):
                        # A hotfix may be live at the URL while the mirror JSON
                        # still contains the previous archive size. Use the
                        # response size for progress/resume and verify SHA-256
                        # after download.
                        expected_size = content_length
                        strict_size = True
                    if total <= 0 and content_length > 0:
                        total = local_resume + content_length
                    if total <= 0:
                        content_range = str(response.headers.get("Content-Range") or "")
                        match = re.search(r"/(\d+)\s*$", content_range)
                        if match:
                            total = int(match.group(1))
                    if expected_size <= 0 and total > 0:
                        expected_size = total
                    downloaded = local_resume
                    last_chunk = time.monotonic()
                    if progress_callback is not None:
                        progress_callback(downloaded, total or expected_size)
                    with target.open(local_mode) as handle:
                        while True:
                            now = time.monotonic()
                            if now - wall_started >= wall_limit:
                                raise TimeoutError("Загрузка обновления превысила лимит времени.")
                            if now - last_chunk >= stall_limit:
                                raise TimeoutError("Загрузка обновления зависла (нет данных).")
                            chunk = response.read(1024 * 256)
                            if not chunk:
                                break
                            last_chunk = time.monotonic()
                            handle.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback is not None:
                                progress_callback(downloaded, total or expected_size)
                done = target.stat().st_size if target.exists() else 0
                if expected_size > 0 and done < expected_size and strict_size:
                    last_error = TimeoutError(f"Incomplete update download: {done}/{expected_size}")
                    time.sleep(min(2.0, 0.4 * attempt))
                    continue
                return
            except Exception as error:
                last_error = error
                try:
                    self.logging.log(
                        "warning",
                        "App update download attempt failed, will resume",
                        attempt=attempt,
                        error=str(error),
                        bytes=(target.stat().st_size if target.exists() else 0),
                    )
                except Exception:
                    pass
                time.sleep(min(2.5, 0.5 * attempt))

        if last_error is not None:
            raise last_error
        raise TimeoutError("Загрузка обновления не удалась.")

    def _is_certificate_error(self, error: Exception) -> bool:
        return "CERTIFICATE_VERIFY_FAILED" in str(error).upper()

    def _friendly_mirror_error(self, error: BaseException) -> str:
        if self._is_certificate_error(error):
            return "Не удалось проверить сертификат источника обновлений."
        if isinstance(error, TimeoutError):
            text = str(error).strip()
            return text or "Источник обновлений не отвечает (таймаут)."
        if isinstance(error, urllib.error.HTTPError):
            code = int(getattr(error, "code", 0) or 0)
            if code == 404:
                return "Обновление не найдено в источнике (HTTP 404)."
            if 500 <= code <= 599:
                return f"Источник обновлений временно недоступен (HTTP {code})."
            return f"Ошибка источника обновлений (HTTP {code})."
        if isinstance(error, (urllib.error.URLError, OSError)):
            return "Не удалось подключиться к источнику обновлений. Проверьте сеть."
        return f"Не удалось связаться с источником обновлений: {error}"

    def _release_cache_path(self) -> Path:
        return self.storage.paths.cache_dir / "app_releases_cache.json"

    def _read_release_cache(self, *, max_age_seconds: int | None) -> object | None:
        path = self._release_cache_path()
        try:
            raw = self.storage.read_json(path, default=None)
        except Exception as error:
            self.logging.log("warning", "Failed to read app release cache", error=str(error))
            return None
        if not isinstance(raw, dict):
            return None
        fetched_at = self._parse_github_datetime(str(raw.get("fetched_at") or ""))
        if max_age_seconds is not None:
            if fetched_at is None:
                return None
            age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
            if age > max_age_seconds:
                return None
        payload = raw.get("payload")
        return payload if payload is not None else None

    def _write_release_cache(self, payload: object) -> None:
        try:
            self.storage.write_json(
                self._release_cache_path(),
                {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "payload": payload,
                },
            )
        except Exception as error:
            self.logging.log("warning", "Failed to write app release cache", error=str(error))

    def _normalize_release_entries(self, payload: object) -> list[dict[str, object]]:
        if isinstance(payload, dict) and payload.get("version"):
            version = str(payload.get("version") or "").strip().lstrip("v")
            mirror_assets = payload.get("assets") if isinstance(payload.get("assets"), dict) else {}
            assets: list[dict[str, object]] = []
            for architecture, raw_asset in mirror_assets.items():
                if not isinstance(raw_asset, dict):
                    continue
                asset = dict(raw_asset)
                asset["architecture"] = str(architecture)
                asset["browser_download_url"] = str(raw_asset.get("download_url") or "")
                assets.append(asset)
            return [
                {
                    "version": version,
                    "body": str(payload.get("changelog") or ""),
                    "html_url": self._release_page_url(payload.get("github_url"), version),
                    "published_at": str(payload.get("published_at") or ""),
                    "updated_at": str(payload.get("binary_updated_at") or payload.get("published_at") or ""),
                    "payload": {"assets": assets},
                }
            ]
        if not isinstance(payload, list):
            return []
        entries: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            if bool(item.get("draft")) or bool(item.get("prerelease")):
                continue
            version = str(item.get("tag_name") or item.get("name") or "").strip().lstrip("v")
            if not version:
                continue
            entries.append(
                {
                    "version": version,
                    "body": str(item.get("body") or ""),
                    "html_url": self._release_page_url(item.get("html_url"), version),
                    "published_at": str(item.get("published_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                    "payload": item,
                }
            )
        entries.sort(key=lambda item: self._version_key(str(item["version"])), reverse=True)
        return entries

    def _release_page_url(self, value: object, version: str) -> str:
        """Return a concrete GitHub release page, never the inert releases index."""
        releases_index = self.REPO_URL.rstrip("/") + "/releases"
        candidate = str(value or "").strip()
        if candidate.rstrip("/") and candidate.rstrip("/") != releases_index:
            return candidate
        normalized = str(version or "").strip().lstrip("v")
        return f"{releases_index}/tag/v{normalized}" if normalized else releases_index

    def _release_timestamp(self, release: dict[str, object], asset: dict[str, object] | None) -> datetime | None:
        candidates = [
            self._parse_github_datetime(str(release.get("published_at") or "")),
            self._parse_github_datetime(str(release.get("updated_at") or "")),
        ]
        if asset:
            candidates.extend(
                [
                    self._parse_github_datetime(str(asset.get("created_at") or "")),
                    self._parse_github_datetime(str(asset.get("updated_at") or "")),
                ]
            )
        valid = [item for item in candidates if item is not None]
        return max(valid) if valid else None

    def _installed_build_timestamp(self) -> datetime | None:
        candidates: list[Path] = []
        try:
            candidates.append(Path(sys.executable))
        except Exception:
            pass
        try:
            candidates.append(Path(__file__))
        except Exception:
            pass
        stamps: list[datetime] = []
        for path in candidates:
            try:
                if path.exists():
                    stamps.append(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))
            except OSError:
                continue
        return max(stamps) if stamps else None

    def _installed_release_identity(self) -> dict[str, str]:
        """Load archive SHA256 identity for this install.

        Written by the slim installer and in-app updater after verifying the
        portable zip against mirror ``assets.*.digest``. Product version may stay
        3.0.0 across hotfixes; the digest is what distinguishes builds.
        """
        candidates: list[Path] = []
        try:
            candidates.append(self.storage.paths.data_dir / "app_release_identity.json")
        except Exception:
            pass
        try:
            candidates.append(self.storage.paths.install_root / "data" / "app_release_identity.json")
        except Exception:
            pass
        try:
            # Packaged/unpacked portable folder stamp from prepare_nuitka_release.
            candidates.append(self.storage.paths.install_root / "build_info.json")
        except Exception:
            pass
        try:
            candidates.append(Path(sys.executable).resolve().parent / "build_info.json")
        except Exception:
            pass
        for path in candidates:
            try:
                payload = self.storage.read_json(path, default={})
            except Exception:
                payload = {}
            if not isinstance(payload, dict) or not payload:
                continue
            normalized = {str(key): str(value) for key, value in payload.items() if value is not None}
            digest = str(normalized.get("digest") or "").strip().lower().removeprefix("sha256:")
            if not digest:
                continue
            normalized["digest"] = digest
            return normalized
        return {}

    def _write_installed_release_identity(self, *, version: str, digest: str, updated_at: str = "") -> None:
        payload = {
            "version": str(version or "").strip(),
            "digest": str(digest or "").strip().lower().removeprefix("sha256:"),
            "updated_at": str(updated_at or "").strip(),
        }
        targets = [
            self.storage.paths.data_dir / "app_release_identity.json",
            self.storage.paths.install_root / "data" / "app_release_identity.json",
            self.storage.paths.install_root / "build_info.json",
        ]
        for path in targets:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                self.storage.write_json(path, payload)
            except Exception:
                continue

    def _parse_github_datetime(self, value: str) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def prepare_update(
        self,
        release_info: dict[str, str],
        *,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, str]:
        asset_url = str(release_info.get("asset_url") or "").strip()
        asset_name = str(release_info.get("asset_name") or "").strip() or "update.zip"
        if not asset_url:
            raise ValueError("No downloadable asset was found for this platform.")

        temp_root = Path(tempfile.mkdtemp(prefix="zapret_hub_update_"))
        zip_path = temp_root / asset_name
        expected_size = int(str(release_info.get("asset_size") or "0") or 0)
        expected_digest = str(release_info.get("asset_digest") or "").strip().lower().removeprefix("sha256:")
        def report(phase: str, current: int, total: int) -> None:
            if progress_callback is not None:
                progress_callback(phase, current, total)

        self._download_to_path(
            asset_url,
            zip_path,
            timeout=int(self.DOWNLOAD_DEADLINE_SEC),
            expected_size=expected_size,
            # When a digest exists it is authoritative; mirror size metadata
            # can briefly lag behind a freshly uploaded hotfix archive.
            strict_size=not bool(expected_digest),
            progress_callback=lambda current, total: report("download", current, total or expected_size),
        )
        archive_bytes = zip_path.read_bytes()
        report("verify", len(archive_bytes), len(archive_bytes))
        if expected_size and len(archive_bytes) != expected_size and not expected_digest:
            raise ValueError("Размер загруженного обновления не совпадает с данными зеркала.")
        expected_digest = str(release_info.get("asset_digest") or "").strip().lower()
        if expected_digest:
            expected_digest = expected_digest.removeprefix("sha256:")
            actual_digest = hashlib.sha256(archive_bytes).hexdigest()
            if actual_digest != expected_digest:
                raise ValueError("SHA-256 загруженного обновления не совпадает с данными зеркала.")
        # Keep zip_path on disk for extract; bytes already verified.

        extract_root = temp_root / "payload"
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.infolist()
            report("extract", 0, max(1, len(members)))
            for index, member in enumerate(members, start=1):
                archive.extract(member, extract_root)
                report("extract", index, max(1, len(members)))

        payload_root = self._resolve_payload_root(extract_root)
        launch_exe = self._find_payload_exe(payload_root)
        if launch_exe is None:
            raise FileNotFoundError("The downloaded update package does not contain zapret_hub.exe.")
        report("ready", 1, 1)

        return {
            "temp_root": str(temp_root),
            "extract_root": str(payload_root),
            "launch_exe": str(launch_exe),
            "version": str(release_info.get("latest_version", "")),
            "asset_digest": str(release_info.get("asset_digest", "")),
            "release_updated_at": str(release_info.get("release_updated_at", "")),
        }

    def _find_payload_exe(self, root: Path) -> Path | None:
        for name in self._EXE_NAMES:
            candidate = root / name
            if candidate.exists():
                return candidate
        try:
            for path in root.iterdir():
                if path.is_file() and path.name.lower() == "zapret_hub.exe":
                    return path
        except Exception:
            pass
        return None

    def _resolve_payload_root(self, extract_root: Path) -> Path:
        if self._find_payload_exe(extract_root) is not None:
            return extract_root
        named_root = extract_root / "zapret_hub"
        if self._find_payload_exe(named_root) is not None:
            return named_root
        try:
            for candidate in extract_root.iterdir():
                if candidate.is_dir() and self._find_payload_exe(candidate) is not None:
                    return candidate
        except Exception:
            pass
        return extract_root

    def launch_update(self, prepared_update: dict[str, str]) -> None:
        extract_root = Path(prepared_update["extract_root"])
        install_root = self.storage.paths.install_root
        current_executable = Path(sys.executable).resolve()
        current_pid = os.getpid()
        script_root = Path(tempfile.gettempdir()) / "zapret_hub_updates"
        script_root.mkdir(parents=True, exist_ok=True)
        update_id = int(datetime.utcnow().timestamp() * 1000)
        script_path = script_root / f"apply_update_{update_id}.ps1"
        log_path = script_root / f"apply_update_{update_id}.log"
        ready_path = script_root / f"apply_update_{update_id}.ready"
        identity_json = json.dumps(
            {
                "version": str(prepared_update.get("version") or ""),
                "digest": str(prepared_update.get("asset_digest") or "").removeprefix("sha256:"),
                "updated_at": str(prepared_update.get("release_updated_at") or ""),
            },
            ensure_ascii=False,
        )
        # Do not write the installed identity yet. The updater must only mark
        # a release as installed after the payload was copied and relaunched;
        # writing it here made failed updates report a false "up to date" state.
        data_dir = self.storage.paths.data_dir
        identity_dirs_ps = [
            str(data_dir).replace("'", "''"),
            str((install_root / "data")).replace("'", "''"),
        ]

        script = textwrap.dedent(
            f"""
            $ErrorActionPreference = 'SilentlyContinue'
            $pidToWait = {current_pid}
            $src = '{str(extract_root).replace("'", "''")}'
            $dst = '{str(install_root).replace("'", "''")}'
            $launch = '{str(current_executable).replace("'", "''")}'
            $tempRoot = '{str(Path(prepared_update["temp_root"])).replace("'", "''")}'
            $logPath = '{str(log_path).replace("'", "''")}'
            $readyPath = '{str(ready_path).replace("'", "''")}'
            $preserve = @('data', 'mods', 'configs', 'cache', 'logs', 'backups')
            $backupRoot = Join-Path '{str(script_root).replace("'", "''")}' ('preserve_' + [guid]::NewGuid().ToString('N'))
            # Write this before any elevation or file-system work. If it is
            # missing, PowerShell itself did not start the helper.
            try {{
              Add-Content -LiteralPath $logPath -Value ('[' + (Get-Date -Format s) + '] helper bootstrap started')
            }} catch {{}}
            Remove-Item -LiteralPath $readyPath -Force -ErrorAction SilentlyContinue

            function Remove-PathRobust([string]$targetPath) {{
              if (-not (Test-Path $targetPath)) {{ return $true }}
              for ($i = 0; $i -lt 6; $i++) {{
                try {{
                  attrib -r -s -h $targetPath /s /d *> $null
                }} catch {{}}
                try {{
                  Remove-Item $targetPath -Recurse -Force -ErrorAction Stop
                  return $true
                }} catch {{
                  Start-Sleep -Milliseconds 300
                }}
              }}
              $quarantineRoot = Join-Path $env:TEMP 'zapret_hub_update_quarantine'
              New-Item -ItemType Directory -Path $quarantineRoot -Force | Out-Null
              $moved = Join-Path $quarantineRoot ((Split-Path $targetPath -Leaf) + '_' + [guid]::NewGuid().ToString('N'))
              try {{
                Move-Item $targetPath $moved -Force -ErrorAction Stop
                return $true
              }} catch {{
                return $false
              }}
            }}

            function Add-UpdateLog([string]$message) {{
              try {{
                Add-Content -LiteralPath $logPath -Value ('[' + (Get-Date -Format s) + '] ' + $message)
              }} catch {{}}
            }}

            # Check the actual destination instead of assuming that Program
            # Files lives on C:. Users can install the app on another drive.
            function Test-UpdateTargetWritable([string]$targetDir) {{
              try {{
                New-Item -ItemType Directory -Path $targetDir -Force -ErrorAction Stop | Out-Null
                $probe = Join-Path $targetDir ('.zapret_hub_write_probe_' + [guid]::NewGuid().ToString('N'))
                [System.IO.File]::WriteAllText($probe, 'ok')
                Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
                return $true
              }} catch {{
                return $false
              }}
            }}

            # The app must exit before replacement, so elevate this detached
            # helper only when the actual install folder requires it.
            $canWriteTarget = Test-UpdateTargetWritable $dst
            $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
            $principal = New-Object Security.Principal.WindowsPrincipal($identity)
            if (-not $canWriteTarget -and -not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
              Add-UpdateLog 'requesting administrator rights for protected install folder'
              try {{
                $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', $PSCommandPath)
                Start-Process -FilePath 'powershell.exe' -ArgumentList $arguments -WorkingDirectory $dst -Verb RunAs -ErrorAction Stop | Out-Null
                # The elevated copy must claim the updater lock and signal
                # readiness before this unprivileged launcher can exit.
                for ($i = 0; $i -lt 180; $i++) {{
                  if (Test-Path $readyPath) {{ exit 0 }}
                  Start-Sleep -Milliseconds 250
                }}
                Add-UpdateLog 'elevated updater did not become ready'
                exit 6
              }} catch {{
                Add-UpdateLog ('administrator elevation failed: ' + $_.Exception.Message)
                exit 6
              }}
            }}

            # Take the lock only after elevation. Holding it before spawning an
            # elevated copy made that copy immediately quit as a duplicate.
            $mutex = New-Object System.Threading.Mutex($false, 'Global\\ZapretHubApplicationUpdater')
            $ownsMutex = $false
            try {{ $ownsMutex = $mutex.WaitOne(0) }} catch {{}}
            if (-not $ownsMutex) {{
              Add-UpdateLog 'another updater is already active'
              exit 3
            }}
            New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
            Set-Content -LiteralPath $readyPath -Value 'ready' -Encoding ASCII
            Add-UpdateLog 'updater ready'

            function Test-StandalonePayload([string]$sourceDir) {{
              return (Test-Path (Join-Path $sourceDir 'python311.dll')) -and
                     (Test-Path (Join-Path $sourceDir 'python3.dll')) -and
                     (Test-Path (Join-Path $sourceDir 'zapret_hub.exe'))
            }}

            function Test-InstalledStandalone([string]$targetDir) {{
              return (Test-Path (Join-Path $targetDir 'python311.dll')) -and
                     (Test-Path (Join-Path $targetDir 'python3.dll')) -and
                     (Test-Path (Join-Path $targetDir 'zapret_hub.exe'))
            }}

            function Overlay-Tree([string]$sourceDir, [string]$targetDir, [string[]]$preserveNames) {{
              New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
              $sourceItems = Get-ChildItem -LiteralPath $sourceDir -Force -ErrorAction SilentlyContinue
              foreach ($item in $sourceItems) {{
                if ($preserveNames -contains $item.Name) {{ continue }}
                $dest = Join-Path $targetDir $item.Name
                if ($item.PSIsContainer) {{
                  Overlay-Tree $item.FullName $dest $preserveNames
                }} else {{
                  if (Test-Path $dest) {{
                    [void](Remove-PathRobust $dest)
                  }}
                  New-Item -ItemType Directory -Path (Split-Path $dest -Parent) -Force | Out-Null
                  try {{
                    Copy-Item -LiteralPath $item.FullName -Destination $dest -Force -ErrorAction Stop
                  }} catch {{
                    Add-UpdateLog ('copy failed: ' + $item.FullName + ' -> ' + $dest + ' | ' + $_.Exception.Message)
                  }}
                }}
              }}
            }}

            for ($i = 0; $i -lt 40; $i++) {{
              if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) {{ break }}
              Start-Sleep -Milliseconds 250
            }}

            if (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {{
              Add-Content -LiteralPath $logPath -Value ('[' + (Get-Date -Format s) + '] forcing old process stop')
              Stop-Process -Id $pidToWait -Force -ErrorAction SilentlyContinue
              for ($i = 0; $i -lt 40; $i++) {{
                if (-not (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue)) {{ break }}
                Start-Sleep -Milliseconds 250
              }}
            }}

            # The app performs a graceful component shutdown before applying an
            # update. Do not delete driver services or terminate unrelated
            # processes here: besides breaking active connections this pattern is
            # commonly flagged by endpoint protection.

            New-Item -ItemType Directory -Path $dst -Force | Out-Null

            foreach ($item in $preserve) {{
              $dstItem = Join-Path $dst $item
              try {{
                if (Test-Path $dstItem) {{
                  Move-Item $dstItem (Join-Path $backupRoot $item) -Force
                }}
              }} catch {{}}
            }}
            Add-Content -LiteralPath $logPath -Value ('[' + (Get-Date -Format s) + '] preserved user dirs')

            $sourceIsStandalone = Test-StandalonePayload $src
            if ($sourceIsStandalone) {{
              Add-UpdateLog 'standalone payload detected'
              $oldInternal = Join-Path $dst '_internal'
              if (Test-Path $oldInternal) {{
                [void](Remove-PathRobust $oldInternal)
                Add-UpdateLog 'old _internal removed for standalone update'
              }}
            }}

            $excludeDirs = @()
            foreach ($item in $preserve) {{ $excludeDirs += (Join-Path $src $item) }}
            $robocopyArgs = @($src, $dst, '/E', '/R:8', '/W:1', '/COPY:DAT', '/DCOPY:DAT', '/NFL', '/NDL', '/NJH', '/NJS', '/NP', '/XJ', '/XD') + $excludeDirs
            & robocopy @robocopyArgs | Out-Null
            $copyCode = $LASTEXITCODE
            if ($copyCode -gt 7) {{
              Add-UpdateLog ('robocopy failed with exit code ' + $copyCode)
              foreach ($item in $preserve) {{
                $backupItem = Join-Path $backupRoot $item
                if (Test-Path $backupItem) {{
                  Move-Item -LiteralPath $backupItem -Destination (Join-Path $dst $item) -Force
                }}
              }}
              if ($ownsMutex) {{ $mutex.ReleaseMutex() }}
              exit 4
            }}
            Add-UpdateLog ('payload copied, robocopy exit code ' + $copyCode)

            if ($sourceIsStandalone -and -not (Test-InstalledStandalone $dst)) {{
              Add-UpdateLog 'standalone validation failed after overlay, retrying top-level runtime files'
              foreach ($fileName in @('zapret_hub.exe', 'python311.dll', 'python3.dll')) {{
                $sourceFile = Join-Path $src $fileName
                $targetFile = Join-Path $dst $fileName
                if (Test-Path $sourceFile) {{
                  [void](Remove-PathRobust $targetFile)
                  try {{
                    Copy-Item $sourceFile $targetFile -Force -ErrorAction Stop
                    Add-UpdateLog ('runtime file copied: ' + $fileName)
                  }} catch {{
                    Add-UpdateLog ('runtime file copy failed: ' + $fileName + ' | ' + $_.Exception.Message)
                  }}
                }}
              }}
            }}

            foreach ($item in $preserve) {{
              $backupItem = Join-Path $backupRoot $item
              $target = Join-Path $dst $item
              if (Test-Path $backupItem) {{
                try {{
                  if (Test-Path $target) {{
                    [void](Remove-PathRobust $target)
                  }}
                }} catch {{}}
                Move-Item $backupItem $target -Force
              }}
            }}
            Add-Content -LiteralPath $logPath -Value ('[' + (Get-Date -Format s) + '] user data restored')

            if ($sourceIsStandalone -and -not (Test-InstalledStandalone $dst)) {{
              Add-UpdateLog 'standalone validation failed, aborting relaunch to avoid broken install'
              exit 2
            }}

            Start-Sleep -Milliseconds 250
            $launch = Join-Path $dst 'zapret_hub.exe'
            $restarted = $false
            $existingAppPids = @(Get-Process -Name 'zapret_hub', 'Zapret_Hub' -ErrorAction SilentlyContinue | ForEach-Object {{ $_.Id }})

            function Test-RelaunchedApp([System.Diagnostics.Process]$candidate, [int[]]$knownPids) {{
              try {{
                if (-not $candidate.HasExited) {{ return $true }}
              }} catch {{}}
              # A non-elevated bootstrap process intentionally exits after it
              # delegates to the UAC-approved copy. Accept only a new process,
              # never an unrelated old Zapret Hub instance.
              try {{
                $newProcess = Get-Process -Name 'zapret_hub', 'Zapret_Hub' -ErrorAction SilentlyContinue |
                  Where-Object {{ $knownPids -notcontains $_.Id }} |
                  Select-Object -First 1
                return $null -ne $newProcess
              }} catch {{
                return $false
              }}
            }}

            for ($attempt = 1; $attempt -le 3; $attempt++) {{
              try {{
                $newProcess = Start-Process -FilePath $launch -WorkingDirectory $dst -PassThru -ErrorAction Stop
                for ($healthCheck = 0; $healthCheck -lt 12; $healthCheck++) {{
                  Start-Sleep -Milliseconds 250
                  if (Test-RelaunchedApp $newProcess $existingAppPids) {{
                    $restarted = $true
                    Add-UpdateLog ('relaunched app on attempt ' + $attempt)
                    break
                  }}
                }}
                if (-not $restarted) {{
                  $exitCode = if ($newProcess.HasExited) {{ $newProcess.ExitCode }} else {{ 'unknown' }}
                  Add-UpdateLog ('relaunch attempt ' + $attempt + ' did not become healthy; exit code ' + $exitCode)
                }}
              }} catch {{
                Add-UpdateLog ('relaunch attempt ' + $attempt + ' failed: ' + $_.Exception.Message)
              }}
              if ($restarted) {{ break }}
              Start-Sleep -Milliseconds 750
            }}
            if (-not $restarted) {{
              Add-UpdateLog 'failed to relaunch app after 3 attempts'
              if ($ownsMutex) {{ $mutex.ReleaseMutex() }}
              exit 5
            }}
            # Commit the release identity only after the new process is alive.
            # This keeps retry/check behavior correct if replacement or launch fails.
            $identityDirs = @(
              '{identity_dirs_ps[0]}',
              '{identity_dirs_ps[1]}'
            )
            foreach ($identityDir in $identityDirs) {{
              if (-not $identityDir) {{ continue }}
              New-Item -ItemType Directory -Path $identityDir -Force | Out-Null
              Set-Content -LiteralPath (Join-Path $identityDir 'app_release_identity.json') -Value '{identity_json.replace("'", "''")}' -Encoding UTF8
            }}
            Add-UpdateLog 'installed release identity saved after successful relaunch'
            Remove-Item $backupRoot -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
            if ($ownsMutex) {{ $mutex.ReleaseMutex() }}
            Start-Sleep -Milliseconds 500
            Remove-Item '{str(script_path).replace("'", "''")}' -Force -ErrorAction SilentlyContinue
            """
        ).strip()
        script_path.write_text(script, encoding="utf-8")
        startupinfo = None
        creationflags = 0
        if sys.platform.startswith("win"):
            # DETACHED_PROCESS must NOT be used here: on some PowerShell 5.1
            # builds it makes powershell.exe exit 0 immediately without ever
            # executing the -File script (helper log/ready files never appear
            # and the app reports "Помощник обновления завершился до запуска").
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0

        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                # Local script execution policies must not prevent the verified
                # update helper from starting after the archive is prepared.
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script_path),
            ],
            creationflags=creationflags,
            startupinfo=startupinfo,
            cwd=str(install_root),
        )
        # The current app must not quit until the helper has proved that it can
        # work with the destination. A generic log line is insufficient: an
        # elevation handoff can still fail after it was written.
        if sys.platform.startswith("win") and getattr(process, "pid", None):
            deadline = time.monotonic() + 45.0
            while time.monotonic() < deadline:
                if ready_path.exists():
                    break
                exit_code = process.poll()
                if exit_code is not None:
                    raise RuntimeError(f"Помощник обновления завершился до запуска (код {exit_code}).")
                time.sleep(0.05)
            else:
                raise RuntimeError("Не удалось запустить помощник обновления. Приложение не было закрыто.")
        self.logging.log("info", "App update launched", target_version=prepared_update.get("version", ""), source=str(extract_root))

    def _pick_release_asset(self, assets: list[dict[str, object]]) -> dict[str, object] | None:
        machine = platform.machine().lower()
        want_arm = "arm" in machine or "aarch64" in machine
        arch_key = "arm64" if want_arm else "x64"
        pattern = (
            re.compile(r"portable.*win_arm64\.zip$", re.IGNORECASE)
            if want_arm
            else re.compile(r"portable.*win_x64\.zip$", re.IGNORECASE)
        )
        # Prefer mirror architecture keys (x64 / arm64), then name regex.
        for asset in assets:
            if str(asset.get("architecture") or "").lower() == arch_key and str(asset.get("browser_download_url") or "").strip():
                return asset
        for asset in assets:
            name = str(asset.get("name") or "")
            if pattern.search(name) and str(asset.get("browser_download_url") or "").strip():
                return asset
        # Last resort: any portable zip with a download URL (skip installer).
        for asset in assets:
            name = str(asset.get("name") or "").lower()
            arch = str(asset.get("architecture") or "").lower()
            if arch == "installer" or "installer" in name:
                continue
            if str(asset.get("browser_download_url") or "").strip() and name.endswith(".zip"):
                return asset
        return None

    def _version_key(self, version: str) -> tuple[int, ...]:
        parts = re.findall(r"\d+", version)
        if not parts:
            return (0,)
        return tuple(int(part) for part in parts)
