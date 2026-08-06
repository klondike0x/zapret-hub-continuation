from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import base64
import hashlib
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable


class MarketplaceError(RuntimeError):
    def __init__(self, code: str, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.details = details if isinstance(details, dict) else {}


@dataclass
class DownloadJob:
    id: str
    slug: str
    version_id: int | None = None
    title: str = ""
    compatibility: str = "zapret"
    author: str = ""
    summary: str = ""
    icon_url: str = ""
    project_url: str = ""
    marketplace_version: str = ""
    status: str = "queued"  # queued|downloading|paused|installing|done|error|cancelled
    progress: float = 0.0
    bytes_done: int = 0
    bytes_total: int = 0
    message: str = ""
    error: str = ""
    mod_id: str = ""
    # Update path: delete installed copy first, then download a clean install.
    replace_existing: bool = False
    restore_enabled: bool | None = None


@dataclass
class MarketplaceService:
    """Public Marketplace API client + sequential download queue."""

    BASE_URL = "https://goshkow.com/api/marketplace/v1"
    USER_AGENT = "Zapret-Hub"
    # Metadata (catalog /latest /project): fail fast — UI must not freeze on a stall.
    API_DEADLINE_SEC = 8.0
    TICKET_DEADLINE_SEC = 12.0
    COMPLETE_DEADLINE_SEC = 6.0
    # File downloads: soft stall (no hard 15s abort). Server supports Range/206 — use it.
    DOWNLOAD_STALL_SEC = 75.0
    DOWNLOAD_WALL_SEC = 900.0
    DOWNLOAD_ATTEMPTS = 5
    MIN_FREE_SPACE_BYTES = 1024 ** 3
    UPDATE_CHECK_WORKERS = 6

    storage_paths: Any
    logging: Any
    mods: Any | None = None
    mods2: Any | None = None
    on_event: Callable[[str, dict[str, Any]], None] | None = None

    _device_id: str = ""
    _jobs: list[DownloadJob] = field(default_factory=list, init=False, repr=False)
    _worker: threading.Thread | None = field(default=None, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _wake: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _busy: bool = field(default=False, init=False, repr=False)
    _active_id: str = field(default="", init=False, repr=False)
    _active_ticket: str = field(default="", init=False, repr=False)
    _cancel_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _pause_ids: set[str] = field(default_factory=set, init=False, repr=False)
    _update_cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)
    _dismissals: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _install_revision: int = field(default=0, init=False, repr=False)
    _last_completed: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self._device_id = self._load_or_create_device_id()
        self._dismissals = self._load_dismissals()
        self._ensure_worker()

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(name, payload)
        except Exception:
            pass

    def _log(self, level: str, message: str, **fields: Any) -> None:
        try:
            self.logging.log(level, message, **fields)
        except Exception:
            pass

    def _device_path(self) -> Path:
        return Path(self.storage_paths.data_dir) / "marketplace_device_id.txt"

    def _load_or_create_device_id(self) -> str:
        path = self._device_path()
        try:
            if path.exists():
                value = path.read_text(encoding="utf-8").strip()
                if value:
                    return value
        except Exception:
            pass
        value = str(uuid.uuid4())
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding="utf-8")
        except Exception:
            pass
        return value

    def _dismissals_path(self) -> Path:
        return Path(self.storage_paths.data_dir) / "marketplace_update_dismissals.json"

    def _load_dismissals(self) -> dict[str, str]:
        path = self._dismissals_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): str(v) for k, v in raw.items() if str(k).strip() and str(v).strip()}
        except Exception:
            pass
        return {}

    def _save_dismissals(self) -> None:
        path = self._dismissals_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self._dismissals, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as error:
            self._log("warning", "Failed to save marketplace dismissals", error=str(error))

    @staticmethod
    def _version_tuple(value: str) -> tuple[int, ...]:
        parts = [int(p) for p in re.findall(r"\d+", str(value or ""))]
        return tuple(parts) if parts else (0,)

    def _is_newer(self, latest: str, current: str) -> bool:
        return self._version_tuple(latest) > self._version_tuple(current)

    def _list_marketplace_mods(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for manager, compatibility in ((self.mods, "zapret"), (self.mods2, "zapret2")):
            if manager is None:
                continue
            try:
                installed = manager.list_installed()
            except Exception:
                continue
            for item in installed:
                slug = str(getattr(item, "marketplace_slug", "") or "").strip()
                if not slug:
                    continue
                rows.append(
                    {
                        "modId": item.id,
                        "slug": slug,
                        "title": item.name or slug,
                        "author": item.author or "",
                        "summary": item.description or "",
                        "iconUrl": str(getattr(item, "icon_url", "") or ""),
                        "projectUrl": str(getattr(item, "source_url", "") or ""),
                        "compatibility": compatibility,
                        "currentVersion": str(item.version or ""),
                    }
                )
        return rows

    def fetch_latest(self, slug: str, *, lang: str = "ru") -> dict[str, Any]:
        payload = self._request_json(
            "GET",
            f"/projects/{urllib.parse.quote(slug)}/latest",
            query={"lang": lang if lang in {"ru", "en"} else "ru"},
            timeout=int(self.API_DEADLINE_SEC),
        )
        version_id = int(payload.get("version_id") or payload.get("id") or 0) or None
        return {
            "version": str(payload.get("version") or ""),
            "compatibility": str(payload.get("compatibility") or "zapret"),
            "changelog": str(payload.get("changelog") or ""),
            "versionId": version_id,
            "size": int(payload.get("size") or 0),
            "sha256": str(payload.get("sha256") or ""),
            # Docs advertise download_url; live API currently returns download_ticket_url.
            "downloadUrl": str(payload.get("download_url") or ""),
            "downloadTicketUrl": str(payload.get("download_ticket_url") or ""),
            "legacyFallbackUrl": (
                f"/zapret-hub/marketplace/download/{version_id}" if version_id else ""
            ),
        }

    def check_updates(self, *, lang: str = "ru") -> dict[str, Any]:
        """Compare installed marketplace mods with /latest in parallel."""
        installed = self._list_marketplace_mods()
        updates: list[dict[str, Any]] = []
        notify: list[dict[str, Any]] = []
        if not installed:
            self._update_cache.clear()
            return {"ok": True, "updates": updates, "notify": notify}

        def _probe(item: dict[str, Any]) -> dict[str, Any] | None:
            slug = str(item.get("slug") or "")
            try:
                latest = self.fetch_latest(slug, lang=lang)
            except Exception as error:
                self._log("warning", "Marketplace update check failed", slug=slug, error=str(error))
                return None
            latest_version = str(latest.get("version") or "")
            current = str(item.get("currentVersion") or "")
            if not latest_version or not self._is_newer(latest_version, current):
                return {"slug": slug, "fresh": False}
            return {
                "slug": slug,
                "fresh": True,
                "row": {
                    **item,
                    "latestVersion": latest_version,
                    "changelog": str(latest.get("changelog") or ""),
                    "versionId": latest.get("versionId"),
                    "compatibility": str(latest.get("compatibility") or item.get("compatibility") or "zapret"),
                },
            }

        workers = max(1, min(self.UPDATE_CHECK_WORKERS, len(installed)))
        results: list[dict[str, Any] | None] = []
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="zh-mkt-upd") as pool:
            futures = [pool.submit(_probe, item) for item in installed]
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as error:
                    self._log("warning", "Marketplace update worker failed", error=str(error))

        # Preserve install order for stable UI.
        by_slug = {str(item.get("slug") or ""): item for item in results if isinstance(item, dict)}
        for item in installed:
            slug = str(item.get("slug") or "")
            probed = by_slug.get(slug)
            if not probed:
                continue
            if not probed.get("fresh"):
                self._update_cache.pop(slug, None)
                continue
            row = probed.get("row") if isinstance(probed.get("row"), dict) else None
            if not isinstance(row, dict):
                continue
            updates.append(row)
            self._update_cache[slug] = row
            latest_version = str(row.get("latestVersion") or "")
            dismissed = str(self._dismissals.get(slug) or "")
            if not dismissed or self._is_newer(latest_version, dismissed):
                notify.append(row)

        alive = {item["slug"] for item in installed}
        for slug in list(self._update_cache):
            if slug not in alive:
                self._update_cache.pop(slug, None)
        return {"ok": True, "updates": updates, "notify": notify}

    def updates_status(self) -> dict[str, Any]:
        return {"ok": True, "updates": list(self._update_cache.values())}

    def dismiss_updates(self, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Remember dismissed latest versions so the modal stays quiet until a newer release."""
        rows = items if isinstance(items, list) else []
        if not rows:
            # Dismiss everything currently cached as available.
            rows = list(self._update_cache.values())
        for item in rows:
            if not isinstance(item, dict):
                continue
            slug = str(item.get("slug") or "").strip()
            version = str(item.get("latestVersion") or item.get("version") or "").strip()
            if not slug or not version:
                continue
            previous = str(self._dismissals.get(slug) or "")
            if not previous or self._is_newer(version, previous):
                self._dismissals[slug] = version
        self._save_dismissals()
        return {"ok": True, "dismissals": dict(self._dismissals)}

    def clear_update(self, slug: str) -> None:
        slug = str(slug or "").strip()
        if not slug:
            return
        self._update_cache.pop(slug, None)
        self._dismissals.pop(slug, None)
        self._save_dismissals()

    def _iter_installed_by_slug(self, slug: str, *, compatibility: str = "") -> list[tuple[Any, Any]]:
        """Return (manager, entry) pairs matching marketplace slug."""
        slug = str(slug or "").strip()
        if not slug:
            return []
        managers: list[Any] = []
        compat = str(compatibility or "").strip().lower()
        if compat == "zapret2":
            managers = [self.mods2]
        elif compat == "zapret":
            managers = [self.mods]
        else:
            managers = [self.mods, self.mods2]
        found: list[tuple[Any, Any]] = []
        for manager in managers:
            if manager is None:
                continue
            try:
                installed = manager.list_installed()
            except Exception:
                continue
            for item in installed:
                item_slug = str(getattr(item, "marketplace_slug", "") or "").strip()
                if item_slug == slug or str(getattr(item, "id", "") or "") == slug:
                    found.append((manager, item))
        return found

    def _remove_existing_by_slug(self, slug: str, *, compatibility: str, strict: bool = False) -> list[str]:
        removed: list[str] = []
        for manager, item in self._iter_installed_by_slug(slug, compatibility=compatibility):
            mod_id = str(getattr(item, "id", "") or "")
            try:
                manager.remove(mod_id)
                removed.append(mod_id)
            except Exception as error:
                self._log("warning", "Failed to replace marketplace mod", slug=slug, mod_id=mod_id, error=str(error))
                if strict:
                    raise MarketplaceError(
                        "replace_failed",
                        f"Не удалось удалить предыдущую версию модификации перед обновлением: {error}",
                    ) from error
        return removed

    def remove_installed(self, slug: str) -> dict[str, Any]:
        slug = str(slug or "").strip()
        if not slug:
            raise MarketplaceError("invalid_slug", "Empty slug")
        removed: list[str] = []
        for manager in (self.mods, self.mods2):
            if manager is None:
                continue
            for item in list(manager.list_installed()):
                if str(getattr(item, "marketplace_slug", "") or "").strip() != slug:
                    continue
                manager.remove(item.id)
                removed.append(str(item.id))
        self.clear_update(slug)
        return {"ok": True, "slug": slug, "removed": removed}

    def device_id(self) -> str:
        return self._device_id

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
            "X-Zapret-Device": self._device_id,
        }
        token = str(os.environ.get("ZAPRET_HUB_MARKETPLACE_TOKEN", "") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _run_with_deadline(func, *, timeout: float):
        """Hard wall-clock deadline without ThreadPoolExecutor shutdown(wait=True) freeze."""
        box: dict[str, object] = {}
        errors: list[BaseException] = []
        done = threading.Event()
        limit = max(0.1, float(timeout))

        def _target() -> None:
            try:
                box["value"] = func()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                done.set()

        thread = threading.Thread(target=_target, name="zapret-hub-marketplace-net", daemon=True)
        thread.start()
        deadline = time.monotonic() + limit
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                seconds = max(1, int(round(limit)))
                raise MarketplaceError(
                    "timeout",
                    f"Не удалось подключиться к goshkow.com за {seconds} с. Проверьте сеть и попробуйте снова.",
                )
            if done.wait(timeout=min(0.25, remaining)):
                break
        if errors:
            raise errors[0]
        return box.get("value")

    @staticmethod
    def _friendly_network_message(error: BaseException) -> str:
        if isinstance(error, MarketplaceError):
            text = str(error).strip()
            return text or error.code
        if isinstance(error, TimeoutError):
            return "goshkow.com не отвечает (таймаут). Проверьте сеть и попробуйте снова."
        if isinstance(error, urllib.error.HTTPError):
            code = int(getattr(error, "code", 0) or 0)
            if code == 404:
                return "Модификация не найдена на goshkow.com (HTTP 404)."
            if code == 409:
                return "На сервере уже есть активная загрузка. Повторите через несколько секунд."
            if code == 429:
                return "Слишком много запросов к маркетплейсу. Подождите немного."
            if 500 <= code <= 599:
                return f"Маркетплейс goshkow.com временно недоступен (HTTP {code})."
            return f"Ошибка маркетплейса (HTTP {code})."
        if isinstance(error, (urllib.error.URLError, OSError)):
            return "Не удалось подключиться к маркетплейсу goshkow.com. Проверьте сеть."
        text = str(error).strip()
        return text or "Сетевая ошибка маркетплейса."

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        timeout: float = 8.0,
    ) -> dict[str, Any]:
        url = path if path.startswith("http") else f"{self.BASE_URL}{path}"
        if query:
            cleaned = {k: v for k, v in query.items() if v is not None and str(v) != ""}
            if cleaned:
                url = f"{url}?{urllib.parse.urlencode(cleaned)}"
        data = None
        headers = self._headers(json_body=body is not None)
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        sock_timeout = max(1.0, float(timeout))
        wall_timeout = sock_timeout + 1.0

        def _load() -> dict[str, Any]:
            with urllib.request.urlopen(request, timeout=sock_timeout) as response:
                raw = response.read().decode("utf-8-sig")
                if not raw.strip():
                    return {"ok": True}
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
                return {"ok": True, "data": payload}

        try:
            return self._run_with_deadline(_load, timeout=wall_timeout)  # type: ignore[return-value]
        except MarketplaceError:
            raise
        except urllib.error.HTTPError as error:
            code = "http_error"
            details: dict[str, Any] = {}
            err_body = ""
            try:
                err_body = error.read().decode("utf-8-sig")
                parsed = json.loads(err_body)
                if isinstance(parsed, dict):
                    details = parsed
                    if parsed.get("error"):
                        code = str(parsed.get("error"))
            except Exception:
                details = {"raw": err_body[:240]} if err_body else {}
            # Site legacy mirrors sometimes return 429 with plain text
            # "Download already active" instead of JSON 409.
            raw_lower = str(err_body or details.get("raw") or details.get("error") or "").lower()
            if error.code == 409 or "download already active" in raw_lower or code == "download_active":
                code = "download_active"
            elif error.code == 429:
                code = "rate_limited"
            raise MarketplaceError(code, self._friendly_network_message(error), details=details) from error
        except Exception as error:
            raise MarketplaceError("network_error", self._friendly_network_message(error)) from error

    def list_projects(
        self,
        *,
        q: str = "",
        compatibility: str = "",
        category: str = "",
        sort: str = "relevance",
        page: int = 1,
        limit: int = 20,
        lang: str = "ru",
        refresh: bool = False,
    ) -> dict[str, Any]:
        payload = self._request_json(
            "GET",
            "/projects",
            query={
                "q": q,
                "compatibility": compatibility,
                "category": category,
                "sort": sort,
                "page": max(1, int(page)),
                "limit": min(48, max(1, int(limit))),
                "lang": lang if lang in {"ru", "en"} else "ru",
                "_": int(time.time() * 1000) if refresh else None,
            },
            timeout=self.API_DEADLINE_SEC,
        )
        projects = payload.get("projects") if isinstance(payload.get("projects"), list) else []
        return {
            "ok": bool(payload.get("ok", True)),
            "projects": [self._normalize_card(item) for item in projects if isinstance(item, dict)],
            "total": int(payload.get("total") or 0),
            "page": int(payload.get("page") or page),
            "pages": int(payload.get("pages") or 1),
            "categories": list(payload.get("categories") or ["Игры", "Программы", "Соцсети"]),
        }

    def get_project(self, slug: str, *, lang: str = "ru") -> dict[str, Any]:
        payload = self._request_json(
            "GET",
            f"/projects/{urllib.parse.quote(slug)}",
            query={"lang": lang if lang in {"ru", "en"} else "ru"},
            timeout=self.API_DEADLINE_SEC,
        )
        project = payload.get("project") if isinstance(payload.get("project"), dict) else payload
        if not isinstance(project, dict):
            raise MarketplaceError("not_found", "Project not found")
        card = self._normalize_card(project)
        card["body"] = str(project.get("body") or "")
        card["bodyHtml"] = str(project.get("body_html") or "")
        card["links"] = project.get("links") if isinstance(project.get("links"), list) else []
        card["versions"] = [
            self._normalize_version(item) for item in (payload.get("versions") or []) if isinstance(item, dict)
        ]
        card["dependencies"] = payload.get("dependencies") if isinstance(payload.get("dependencies"), list) else []
        card["screenshots"] = payload.get("screenshots") if isinstance(payload.get("screenshots"), list) else []
        card["commentItems"] = payload.get("comments") if isinstance(payload.get("comments"), list) else []
        return {"ok": True, "project": card}

    def _normalize_card(self, item: dict[str, Any]) -> dict[str, Any]:
        compat = str(item.get("compatibility") or "zapret").lower()
        if compat not in {"zapret", "zapret2"}:
            compat = "zapret"
        updated = item.get("updated_at")
        try:
            updated_ts = int(updated) if updated is not None else 0
        except Exception:
            updated_ts = 0
        latest = item.get("latest_version") if isinstance(item.get("latest_version"), dict) else {}
        latest_size = item.get("latest_version_size") or item.get("latestVersionSize") or item.get("latest_size") or latest.get("size") or 0
        return {
            "id": int(item.get("id") or 0),
            "slug": str(item.get("slug") or ""),
            "title": str(item.get("title") or item.get("slug") or "Untitled"),
            "summary": str(item.get("summary") or ""),
            "author": str(item.get("author") or ""),
            "iconUrl": str(item.get("icon_url") or ""),
            "projectUrl": str(item.get("project_url") or ""),
            "apiUrl": str(item.get("api_url") or ""),
            "downloadUrl": str(item.get("download_url") or ""),
            "compatibility": compat,
            "categories": [str(c) for c in (item.get("categories") or []) if c],
            "license": str(item.get("license") or ""),
            "downloads": int(item.get("downloads") or 0),
            "downloadsCompact": str(item.get("downloads_compact") or item.get("downloads") or "0"),
            "likes": int(item.get("likes") or 0),
            "favorites": int(item.get("favorites") or 0),
            "followers": int(item.get("followers") or 0),
            "comments": int(item.get("comments") or 0) if not isinstance(item.get("comments"), list) else len(item.get("comments") or []),
            "featured": bool(item.get("featured")),
            "updatedAt": updated_ts,
            "latestVersionSize": int(latest_size or 0),
            "publishedAt": int(item.get("published_at") or 0) if str(item.get("published_at") or "").isdigit() or isinstance(item.get("published_at"), int) else 0,
        }

    def _normalize_version(self, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(item.get("id") or 0),
            "version": str(item.get("version") or ""),
            "changelog": str(item.get("changelog") or ""),
            "size": int(item.get("size") or item.get("file_size") or 0),
            "sha256": str(item.get("sha256") or ""),
            "downloads": int(item.get("downloads") or 0),
            "publishedAt": item.get("published_at"),
            "compatibility": str(item.get("compatibility") or ""),
        }

    def enqueue_download(
        self,
        slug: str,
        *,
        version_id: int | None = None,
        title: str = "",
        compatibility: str = "",
        author: str = "",
        summary: str = "",
        icon_url: str = "",
        project_url: str = "",
        marketplace_version: str = "",
        allow_update: bool = False,
    ) -> dict[str, Any]:
        slug = str(slug or "").strip()
        if not slug:
            raise MarketplaceError("invalid_slug", "Empty slug")
        cached = self._update_cache.get(slug) if isinstance(self._update_cache.get(slug), dict) else {}
        if not marketplace_version:
            marketplace_version = str(cached.get("latestVersion") or "")
        if version_id is None and cached.get("versionId"):
            try:
                version_id = int(cached.get("versionId") or 0) or None
            except Exception:
                version_id = None
        if not compatibility:
            compatibility = str(cached.get("compatibility") or "")
        installed = next((item for item in self._list_marketplace_mods() if item.get("slug") == slug), None)
        replacing = False
        restore_enabled: bool | None = None
        if installed is not None:
            current = str(installed.get("currentVersion") or "")
            latest = str(marketplace_version or "").strip()
            update_known = bool(cached) or (latest and self._is_newer(latest, current))
            # Installed same/older version → no-op. Newer / explicit update → delete + re-download.
            if not (allow_update or update_known):
                return {
                    "queued": False,
                    "alreadyInstalled": True,
                    "slug": slug,
                    "modId": str(installed.get("modId") or ""),
                    "pending": [
                        job.slug
                        for job in self._jobs
                        if job.status in {"queued", "downloading", "paused", "installing"}
                    ],
                }
            replacing = True
            if not title:
                title = str(installed.get("title") or slug)
            if not author:
                author = str(installed.get("author") or "")
            if not summary:
                summary = str(installed.get("summary") or "")
            if not icon_url:
                icon_url = str(installed.get("iconUrl") or "")
            if not project_url:
                project_url = str(installed.get("projectUrl") or "")
            if not compatibility:
                compatibility = str(installed.get("compatibility") or "")
            # Preserve enabled flag across delete → reinstall.
            for _manager, entry in self._iter_installed_by_slug(slug, compatibility=compatibility):
                restore_enabled = bool(getattr(entry, "enabled", True))
                break
            # Drop any stuck/previous queue entry for this slug so update always restarts.
            self._discard_jobs_for_slug(slug)
        compatibility = str(compatibility or "zapret").strip() or "zapret"
        self._ensure_install_space(compatibility)
        self._recover_stale_worker_state()
        with self._lock:
            if not replacing:
                for existing in self._jobs:
                    if existing.slug == slug and existing.status in {"queued", "downloading", "paused", "installing"}:
                        self._emit_queue()
                        return {
                            "queued": True,
                            "alreadyQueued": True,
                            "slug": slug,
                            "jobId": existing.id,
                            "pending": [
                                j.slug
                                for j in self._jobs
                                if j.status in {"queued", "downloading", "paused", "installing"}
                            ],
                        }
            job = DownloadJob(
                id=str(uuid.uuid4()),
                slug=slug,
                version_id=version_id,
                title=title or slug,
                compatibility=compatibility,
                author=author,
                summary=summary,
                icon_url=icon_url,
                project_url=project_url,
                marketplace_version=str(marketplace_version or "").strip(),
                status="queued",
                message=title or slug,
                replace_existing=replacing,
                restore_enabled=restore_enabled,
            )
            self._jobs.append(job)
        self._ensure_worker()
        self._wake.set()
        self._emit_job(job)
        self._emit_queue()
        return {
            "queued": True,
            "slug": slug,
            "jobId": job.id,
            "updating": replacing,
            "pending": [j.slug for j in self._jobs if j.status in {"queued", "downloading", "paused", "installing"}],
        }

    def _discard_jobs_for_slug(self, slug: str) -> None:
        """Cancel and drop queued jobs for slug; signal in-flight ones to abort."""
        slug = str(slug or "").strip()
        if not slug:
            return
        cancelled: list[DownloadJob] = []
        with self._lock:
            keep: list[DownloadJob] = []
            for job in self._jobs:
                if job.slug == slug and job.status in {"queued", "downloading", "paused", "installing"}:
                    self._cancel_ids.add(job.id)
                    self._pause_ids.discard(job.id)
                    if job.status in {"queued", "paused"}:
                        job.status = "cancelled"
                        job.message = "cancelled"
                        cancelled.append(job)
                        continue
                    # downloading/installing: keep the row until the worker observes cancel.
                keep.append(job)
            self._jobs = keep
        self._wake.set()
        for job in cancelled:
            self._emit_job(job)
        if cancelled:
            self._emit_queue()

    def _recover_stale_worker_state(self) -> None:
        """Clear phantom busy flags that leave new jobs stuck as queued forever."""
        with self._lock:
            if not self._busy:
                return
            active = next((job for job in self._jobs if job.id == self._active_id), None)
            if active is None or active.status not in {"downloading", "installing"}:
                self._log(
                    "warning",
                    "Marketplace download worker recovered from stale busy state",
                    active_id=self._active_id,
                    active_status=getattr(active, "status", ""),
                )
                self._busy = False
                self._active_id = ""

    def queue_status(self) -> dict[str, Any]:
        with self._lock:
            return self._queue_snapshot()

    def cancel_download(self, slug: str = "", *, job_id: str = "") -> dict[str, Any]:
        slug = str(slug or "").strip()
        job_id = str(job_id or "").strip()
        target: DownloadJob | None = None
        with self._lock:
            target = self._find_job(slug=slug, job_id=job_id)
            if target is None:
                return self._queue_snapshot()
            self._cancel_ids.add(target.id)
            self._pause_ids.discard(target.id)
            if target.status in {"queued", "paused"}:
                target.status = "cancelled"
                target.message = "cancelled"
                self._jobs = [j for j in self._jobs if j.id != target.id]
        self._wake.set()
        self._emit_job(target)
        self._emit_queue()
        return self.queue_status()

    def pause_download(self, slug: str = "", *, job_id: str = "") -> dict[str, Any]:
        slug = str(slug or "").strip()
        job_id = str(job_id or "").strip()
        target: DownloadJob | None = None
        with self._lock:
            target = self._find_job(slug=slug, job_id=job_id)
            if target is None:
                return self._queue_snapshot()
            self._pause_ids.add(target.id)
            if target.status == "queued":
                target.status = "paused"
                target.message = "paused"
        self._wake.set()
        if target is not None:
            self._emit_job(target)
        self._emit_queue()
        return self.queue_status()

    def resume_download(self, slug: str = "", *, job_id: str = "") -> dict[str, Any]:
        slug = str(slug or "").strip()
        job_id = str(job_id or "").strip()
        target: DownloadJob | None = None
        with self._lock:
            target = self._find_job(slug=slug, job_id=job_id)
            if target is None:
                return self._queue_snapshot()
            self._pause_ids.discard(target.id)
            if target.status == "paused":
                target.status = "queued"
                target.message = target.title or target.slug
        self._ensure_worker()
        self._wake.set()
        if target is not None:
            self._emit_job(target)
        self._emit_queue()
        return self.queue_status()

    def reorder_queue(self, ordered_slugs: list[str]) -> dict[str, Any]:
        ordered = [str(item).strip() for item in (ordered_slugs or []) if str(item).strip()]
        with self._lock:
            active = [j for j in self._jobs if j.status in {"downloading", "installing"}]
            paused = [j for j in self._jobs if j.status == "paused"]
            queued = [j for j in self._jobs if j.status == "queued"]
            by_slug = {j.slug: j for j in queued}
            next_queued: list[DownloadJob] = []
            seen: set[str] = set()
            for slug in ordered:
                job = by_slug.get(slug)
                if job is None or slug in seen:
                    continue
                next_queued.append(job)
                seen.add(slug)
            for job in queued:
                if job.slug not in seen:
                    next_queued.append(job)
            self._jobs = [*active, *next_queued, *paused]
        self._emit_queue()
        return self.queue_status()

    def _find_job(self, *, slug: str = "", job_id: str = "") -> DownloadJob | None:
        if job_id:
            for job in self._jobs:
                if job.id == job_id:
                    return job
        if slug:
            for job in self._jobs:
                if job.slug == slug and job.status in {"queued", "downloading", "paused", "installing"}:
                    return job
        return None

    def _job_payload(self, job: DownloadJob) -> dict[str, Any]:
        payload = {
            "jobId": job.id,
            "slug": job.slug,
            "status": job.status,
            "message": job.message or job.title or job.slug,
            "title": job.title,
            "iconUrl": job.icon_url,
            "compatibility": job.compatibility,
            "progress": float(job.progress),
            "bytesDone": int(job.bytes_done),
            "bytesTotal": int(job.bytes_total),
            "error": job.error,
        }
        if job.mod_id:
            payload["modId"] = job.mod_id
            payload["installedVerified"] = True
        return payload

    def _queue_snapshot(self) -> dict[str, Any]:
        active = next((j for j in self._jobs if j.status in {"downloading", "installing"}), None)
        items = [self._job_payload(j) for j in self._jobs if j.status in {"queued", "downloading", "paused", "installing"}]
        overall = 0.0
        if active is not None:
            byte_ratio = 0.0
            if active.bytes_total > 0:
                byte_ratio = max(0.0, min(1.0, float(active.bytes_done) / float(active.bytes_total)))
            job_progress = max(0.0, min(1.0, float(active.progress or 0.0)))
            overall = max(byte_ratio, job_progress)
            if active.status == "installing":
                # Install phase: never show an empty/low bar just because bytes froze.
                overall = max(overall, 0.85, job_progress or 0.85)
            elif overall <= 0:
                overall = 0.01
            else:
                overall = max(0.01, min(0.99, overall))
        elif items:
            overall = 0.01
        return {
            "busy": bool(self._busy),
            "activeSlug": active.slug if active else "",
            "overallProgress": overall,
            "pending": [j["slug"] for j in items],
            "items": items,
            "installRevision": self._install_revision,
            "lastCompleted": dict(self._last_completed),
        }

    def _emit_job(self, job: DownloadJob) -> None:
        payload = self._job_payload(job)
        payload["pending"] = [j.slug for j in self._jobs if j.status in {"queued", "downloading", "paused", "installing"}]
        self._emit("marketplace.download-progress", payload)

    def _emit_queue(self) -> None:
        self._emit("marketplace.queue", self.queue_status())

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="zapret-hub-marketplace-dl")
            self._worker.start()
            self._log("info", "Marketplace download worker started")

    def _worker_loop(self) -> None:
        while True:
            try:
                self._wake.wait(timeout=0.5)
                self._wake.clear()
                self._recover_stale_worker_state()
                job = self._pick_next_job()
                if job is None:
                    continue
                with self._lock:
                    self._busy = True
                    self._active_id = job.id
                    job.status = "downloading"
                    job.progress = 0.01
                    job.message = job.title or job.slug
                self._emit_job(job)
                self._emit_queue()
                try:
                    self._run_job(job)
                    with self._lock:
                        if job.id in self._cancel_ids:
                            job.status = "cancelled"
                            job.message = "cancelled"
                        elif job.id in self._pause_ids or job.status == "paused":
                            job.status = "paused"
                            job.message = "paused"
                            self._pause_ids.add(job.id)
                        elif job.status != "cancelled":
                            job.status = "done"
                            job.progress = 1.0
                            self._install_revision += 1
                            self._last_completed = {
                                "revision": self._install_revision,
                                "slug": job.slug,
                                "modId": job.mod_id,
                                "compatibility": job.compatibility,
                            }
                    self._emit_job(job)
                except Exception as error:
                    try:
                        code = str(getattr(error, "code", "") or "")
                        friendly = self._friendly_network_message(error)
                    except Exception:
                        code = ""
                        friendly = str(error) or "download_failed"
                    if code == "cancelled" or friendly == "cancelled":
                        job.status = "cancelled"
                        job.message = "cancelled"
                    elif code == "paused" or friendly == "paused":
                        with self._lock:
                            job.status = "paused"
                            job.message = "paused"
                            self._pause_ids.add(job.id)
                    else:
                        job.status = "error"
                        job.error = code or "network_error"
                        job.message = friendly
                        self._log("error", "Marketplace download failed", slug=job.slug, error=friendly)
                    self._emit_job(job)
                finally:
                    with self._lock:
                        self._busy = False
                        self._active_id = ""
                        self._cancel_ids.discard(job.id)
                        if job.status in {"done", "error", "cancelled"}:
                            self._jobs = [j for j in self._jobs if j.id != job.id]
                            self._pause_ids.discard(job.id)
                    self._emit_queue()
                    with self._lock:
                        has_more = any(j.status == "queued" for j in self._jobs)
                    if has_more:
                        self._wake.set()
            except Exception as error:
                self._log("error", "Marketplace download worker crashed", error=str(error))
                with self._lock:
                    self._busy = False
                    self._active_id = ""
                time.sleep(0.4)

    def _pick_next_job(self) -> DownloadJob | None:
        with self._lock:
            for job in self._jobs:
                if job.status == "queued" and job.id not in self._pause_ids and job.id not in self._cancel_ids:
                    return job
            return None

    def _run_job(self, job: DownloadJob) -> None:
        self._raise_if_stopped(job)
        # Updates: delete the installed copy first, then download a clean package.
        if job.replace_existing:
            job.message = "removing"
            job.progress = max(job.progress, 0.02)
            self._emit_job(job)
            self._remove_existing_by_slug(
                job.slug,
                compatibility=str(job.compatibility or "zapret"),
                strict=True,
            )
            # Notify UI that the old install is gone before the new zip arrives.
            self._emit(
                "marketplace.download-progress",
                {
                    **self._job_payload(job),
                    "removedForUpdate": True,
                    "pending": [
                        j.slug
                        for j in self._jobs
                        if j.status in {"queued", "downloading", "paused", "installing"}
                    ],
                },
            )
            self._raise_if_stopped(job)
            job.message = job.title or job.slug
            self._emit_job(job)
        # Ticket is created only when this worker is about to download — one active file request.
        ticket = self._create_ticket(job.slug, version_id=job.version_id)
        self._raise_if_stopped(job)
        filename = str(ticket.get("filename") or f"{job.slug}.zip")
        size = int(ticket.get("size") or 0)
        self._ensure_install_space(job.compatibility, incoming_bytes=size)
        sha256 = str(ticket.get("sha256") or "").lower().removeprefix("sha256:")
        ticket_token = str(ticket.get("ticket") or "")
        version_from_ticket = self._version_from_ticket(ticket, filename)
        if version_from_ticket and not job.marketplace_version:
            job.marketplace_version = version_from_ticket
        if ticket.get("version_id") and not job.version_id:
            try:
                job.version_id = int(ticket.get("version_id") or 0) or None
            except Exception:
                pass

        temp_dir = Path(self.storage_paths.cache_dir) / "marketplace_downloads"
        temp_dir.mkdir(parents=True, exist_ok=True)
        target = self._partial_path(temp_dir, job.slug, sha256=sha256, version_id=job.version_id, filename=filename)
        # Keep valid partials for Range resume. Only wipe corrupt/oversize leftovers.
        if target.exists():
            try:
                already = target.stat().st_size
            except OSError:
                already = 0
            if size > 0 and already > size:
                target.unlink(missing_ok=True)
                already = 0
            if already > 0:
                job.bytes_done = already
                if size > 0:
                    job.progress = max(0.01, min(0.89, already / size))
                self._log("info", "Marketplace resume from partial", slug=job.slug, bytes=already)

        job.bytes_total = size
        job.message = filename
        self._emit_job(job)

        with self._lock:
            self._active_ticket = ticket_token
        outcome = "error"
        try:
            urls = self._ticket_urls(ticket)
            self._download_file(urls, target, expected_size=size, job=job)
            self._raise_if_stopped(job)
            self._verify_file(target, expected_size=size, expected_sha256=sha256)
            outcome = "success"
        except MarketplaceError as error:
            if error.code == "cancelled":
                outcome = "cancelled"
            elif error.code == "paused":
                outcome = "paused"
            else:
                outcome = "error"
            raise
        except Exception:
            outcome = "error"
            raise
        finally:
            bytes_sent = target.stat().st_size if target.exists() else 0
            # Always release the server-side ticket so the next job never sees download_active.
            if ticket_token:
                try:
                    self._complete_ticket(
                        ticket_token,
                        success=(outcome == "success"),
                        bytes_sent=bytes_sent,
                    )
                except Exception as error:
                    self._log("warning", "Marketplace ticket complete raised", error=str(error))
            with self._lock:
                if self._active_ticket == ticket_token:
                    self._active_ticket = ""

        compat = str(job.compatibility or "").strip() or "zapret"
        title = job.title
        author = job.author
        summary = job.summary
        icon_url = job.icon_url
        project_url = job.project_url
        marketplace_version = str(job.marketplace_version or version_from_ticket or "").strip()
        if not marketplace_version or not job.compatibility:
            try:
                latest = self.fetch_latest(job.slug)
                marketplace_version = marketplace_version or str(latest.get("version") or "")
                if not job.compatibility:
                    compat = str(latest.get("compatibility") or compat or "zapret")
            except Exception:
                pass
        if not title or not icon_url or not project_url or not author or not summary:
            try:
                detail = self.get_project(job.slug)
                project = detail.get("project") if isinstance(detail.get("project"), dict) else {}
                title = title or str(project.get("title") or "")
                author = author or str(project.get("author") or "")
                summary = summary or str(project.get("summary") or "")
                icon_url = icon_url or str(project.get("iconUrl") or "")
                project_url = project_url or str(project.get("projectUrl") or "")
                if not job.compatibility:
                    compat = str(project.get("compatibility") or compat or "zapret")
            except Exception:
                pass
        self._raise_if_stopped(job)
        job.status = "installing"
        job.progress = max(job.progress, 0.9)
        job.message = filename
        self._emit_job(job)
        job.progress = max(job.progress, 0.94)
        self._emit_job(job)
        # Import uses the zip stem as a fallback mod id — never feed *.partial.zip.
        install_source = target
        clean_name = re.sub(r"[^\w.\-]+", "_", filename or f"{job.slug}.zip") or f"{job.slug}.zip"
        if not clean_name.lower().endswith(".zip"):
            clean_name = f"{clean_name}.zip"
        clean_path = target.with_name(clean_name)
        if clean_path != target:
            try:
                if clean_path.exists():
                    clean_path.unlink()
                shutil.copy2(target, clean_path)
                install_source = clean_path
            except Exception as error:
                self._log("warning", "Marketplace clean zip copy failed", error=str(error))
                install_source = target
        try:
            installed_id = self._install_zip(
                install_source,
                compatibility=compat,
                title=title,
                author=author,
                summary=summary,
                icon_url=icon_url,
                project_url=project_url,
                slug=job.slug,
                marketplace_version=marketplace_version,
                # Already removed at the start of an update job.
                skip_remove=bool(job.replace_existing),
            )
        finally:
            if install_source != target:
                try:
                    install_source.unlink(missing_ok=True)
                except Exception:
                    pass
        if job.restore_enabled is not None and installed_id:
            self._restore_mod_enabled(compat, installed_id, bool(job.restore_enabled))
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        self.clear_update(job.slug)
        job.progress = 0.99
        job.message = installed_id or job.slug
        job.compatibility = compat
        job.mod_id = installed_id

    def _restore_mod_enabled(self, compatibility: str, mod_id: str, enabled: bool) -> None:
        manager = self.mods2 if str(compatibility or "").strip().lower() == "zapret2" else self.mods
        if manager is None:
            return
        try:
            manager.set_enabled(mod_id, enabled)
        except Exception as error:
            self._log(
                "warning",
                "Failed to restore marketplace mod enabled state after update",
                mod_id=mod_id,
                enabled=enabled,
                error=str(error),
            )

    @staticmethod
    def _version_from_ticket(ticket: dict[str, Any], filename: str) -> str:
        for key in ("version", "marketplace_version"):
            value = str(ticket.get(key) or "").strip()
            if value:
                return value
        match = re.search(r"-(\d+(?:\.\d+)*)\.zip$", filename, flags=re.IGNORECASE)
        return match.group(1) if match else ""

    def _partial_path(
        self,
        temp_dir: Path,
        slug: str,
        *,
        sha256: str,
        version_id: int | None,
        filename: str,
    ) -> Path:
        key = (sha256 or str(version_id or "") or filename or slug).strip().lower()
        digest = hashlib.sha1(f"{slug}:{key}".encode("utf-8")).hexdigest()[:16]
        safe_slug = re.sub(r"[^\w.\-]+", "_", slug) or "mod"
        return temp_dir / f"{safe_slug}-{digest}.partial.zip"

    def _ticket_urls(self, ticket: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        for raw in (
            ticket.get("direct_url"),
            ticket.get("fallback_url"),
            ticket.get("legacy_fallback_url"),
            ticket.get("download_url"),
        ):
            url = str(raw or "").strip()
            if not url:
                continue
            if url.startswith("/"):
                url = urllib.parse.urljoin("https://goshkow.com", url)
            if url not in candidates:
                candidates.append(url)
        return candidates

    def _install_root(self, compatibility: str) -> Path:
        if str(compatibility or "").strip().lower() == "zapret2":
            manager_root = getattr(self.mods2, "mods_dir", None)
            if manager_root:
                return Path(manager_root)
            configured_root = getattr(self.storage_paths, "mods_zapret2_dir", None)
            if configured_root:
                return Path(configured_root)
        configured_root = getattr(self.storage_paths, "mods_dir", None)
        if configured_root:
            return Path(configured_root)
        return Path(self.storage_paths.data_dir) / "mods"

    def _ensure_install_space(self, compatibility: str, *, incoming_bytes: int = 0) -> None:
        root = self._install_root(compatibility)
        probe = root
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        try:
            free = int(shutil.disk_usage(probe).free)
        except OSError as error:
            self._log("warning", "Failed to check Marketplace free disk space", path=str(probe), error=str(error))
            return
        required = self.MIN_FREE_SPACE_BYTES + max(0, int(incoming_bytes or 0))
        if free < required:
            raise MarketplaceError(
                "insufficient_disk_space",
                f"insufficient_disk_space:{free}:{required}",
            )

    def _raise_if_stopped(self, job: DownloadJob) -> None:
        with self._lock:
            if job.id in self._cancel_ids:
                raise MarketplaceError("cancelled", "cancelled")
            if job.id in self._pause_ids:
                raise MarketplaceError("paused", "paused")

    def _create_ticket(self, slug: str, *, version_id: int | None) -> dict[str, Any]:
        body: dict[str, Any] = {"slug": slug}
        if version_id:
            body["version_id"] = int(version_id)
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                payload = self._request_json(
                    "POST",
                    "/downloads",
                    body=body,
                    timeout=self.TICKET_DEADLINE_SEC,
                )
                return self._normalize_ticket_payload(payload, slug=slug, version_id=version_id)
            except MarketplaceError as error:
                last_error = error
                if error.code == "download_active":
                    fallback = str(
                        error.details.get("fallback_url")
                        or error.details.get("legacy_fallback_url")
                        or ""
                    ).strip()
                    if fallback:
                        self._log(
                            "warning",
                            "Marketplace download_active — using server fallback URL",
                            slug=slug,
                            fallback=fallback,
                        )
                        return self._direct_download_ticket(
                            slug,
                            version_id=version_id,
                            forced_url=fallback,
                        )
                    if attempt < 2:
                        # Brief settle so a just-cancelled ticket can clear; never open a parallel ticket.
                        time.sleep(1.0 + attempt)
                        continue
                    return self._direct_download_ticket(slug, version_id=version_id)
                if error.code == "http_error":
                    self._log(
                        "warning",
                        "Marketplace ticket unavailable, using public download route",
                        slug=slug,
                        error=error.code,
                    )
                    return self._direct_download_ticket(slug, version_id=version_id)
                raise
        raise last_error or MarketplaceError("download_active")

    def _normalize_ticket_payload(
        self,
        payload: dict[str, Any],
        *,
        slug: str,
        version_id: int | None,
    ) -> dict[str, Any]:
        filename = str(payload.get("filename") or f"{slug}.zip")
        return {
            "ok": bool(payload.get("ok", True)),
            "ticket": str(payload.get("ticket") or ""),
            "ticket_id": payload.get("ticket_id"),
            "version_id": payload.get("version_id") or version_id,
            "version": str(payload.get("version") or ""),
            "filename": filename,
            "size": int(payload.get("size") or 0),
            "sha256": str(payload.get("sha256") or ""),
            "direct_url": str(payload.get("direct_url") or ""),
            "fallback_url": str(payload.get("fallback_url") or ""),
            "legacy_fallback_url": str(payload.get("legacy_fallback_url") or ""),
            "download_url": str(payload.get("download_url") or ""),
            "expires_at": payload.get("expires_at"),
        }

    def _direct_download_ticket(
        self,
        slug: str,
        *,
        version_id: int | None,
        forced_url: str = "",
    ) -> dict[str, Any]:
        latest: dict[str, Any] = {}
        try:
            latest = self.fetch_latest(slug)
        except Exception as error:
            self._log("warning", "Marketplace latest metadata unavailable", slug=slug, error=str(error))
        latest_id = int(latest.get("versionId") or 0) or None
        selected_id = int(version_id or 0) or latest_id
        forced = str(forced_url or "").strip()
        if forced.startswith("/"):
            forced = urllib.parse.urljoin("https://goshkow.com", forced)
        if forced:
            download_url = forced
            legacy = ""
        elif selected_id and selected_id != latest_id:
            download_url = f"https://goshkow.com/zapret-hub/marketplace/download/{selected_id}"
            legacy = download_url
        else:
            download_url = (
                "https://goshkow.com/zapret-hub/marketplace/projects/"
                f"{urllib.parse.quote(slug)}/download/latest"
            )
            legacy = f"/zapret-hub/marketplace/download/{selected_id}" if selected_id else ""
        # Prefer documented download_url from /latest when the API provides it.
        direct_from_latest = str(latest.get("downloadUrl") or "").strip()
        if direct_from_latest and not forced:
            download_url = direct_from_latest
        size = int(latest.get("size") or 0)
        sha256 = str(latest.get("sha256") or "")
        version = str(latest.get("version") or "").strip()
        filename = f"{slug}-{version}.zip" if version else f"{slug}.zip"
        return {
            "filename": filename,
            "size": size,
            "sha256": sha256,
            "version": version,
            "version_id": selected_id,
            "direct_url": download_url,
            "fallback_url": "",
            "legacy_fallback_url": legacy,
            "ticket": "",
        }

    def load_image_data_url(self, url: str) -> dict[str, str]:
        """Fetch a Marketplace image and return a browser-safe data URL.

        The Marketplace media endpoint currently serves images as
        application/octet-stream with nosniff, which Chromium correctly
        refuses to render in an <img>. Cache the bytes locally and determine
        the real image type from their signature instead of trusting headers.
        """
        source = str(url or "").strip()
        parsed = urllib.parse.urlparse(source)
        host = str(parsed.hostname or "").lower()
        allowed = host == "goshkow.com" or host.endswith(".goshkow.com") or host == "i.imgur.com"
        if parsed.scheme != "https" or not allowed:
            raise MarketplaceError("invalid_image_url", "Unsupported Marketplace image URL")

        cache_root = Path(self.storage_paths.cache_dir) / "marketplace_images"
        cache_root.mkdir(parents=True, exist_ok=True)
        cache_path = cache_root / hashlib.sha256(source.encode("utf-8")).hexdigest()
        payload = b""
        if cache_path.exists():
            try:
                payload = cache_path.read_bytes()
            except OSError:
                payload = b""
        if not payload:
            request = urllib.request.Request(
                source,
                headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,image/*", "User-Agent": self.USER_AGENT},
            )

            def _load() -> bytes:
                with urllib.request.urlopen(request, timeout=self.API_DEADLINE_SEC) as response:
                    data = response.read(5 * 1024 * 1024 + 1)
                if len(data) > 5 * 1024 * 1024:
                    raise MarketplaceError("image_too_large", "Marketplace image is too large")
                return data

            try:
                payload = self._run_with_deadline(_load, timeout=self.API_DEADLINE_SEC + 1.0)  # type: ignore[assignment]
            except Exception as error:
                raise MarketplaceError("image_download_failed", self._friendly_network_message(error)) from error
            cache_path.write_bytes(payload)

        mime = self._detect_image_mime(payload)
        if not mime:
            cache_path.unlink(missing_ok=True)
            raise MarketplaceError("invalid_image", "Marketplace returned an unsupported image")
        encoded = base64.b64encode(payload).decode("ascii")
        return {"url": source, "dataUrl": f"data:{mime};base64,{encoded}"}

    @staticmethod
    def _detect_image_mime(payload: bytes) -> str:
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if payload.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if payload.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if len(payload) >= 12 and payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
            return "image/webp"
        return ""

    def _complete_ticket(self, ticket: str, *, success: bool, bytes_sent: int) -> None:
        token = str(ticket or "").strip()
        if not token:
            return
        try:
            self._request_json(
                "POST",
                f"/downloads/{urllib.parse.quote(token, safe='')}/complete",
                body={"success": bool(success), "bytes_sent": int(bytes_sent)},
                timeout=self.COMPLETE_DEADLINE_SEC,
            )
        except Exception as error:
            # Never fail the local install/cancel path because complete hung.
            self._log("warning", "Marketplace ticket complete failed", error=str(error), success=success)

    def _download_file(
        self,
        urls: list[str] | str,
        target: Path,
        *,
        expected_size: int,
        job: DownloadJob | None = None,
        fallback_url: str = "",
    ) -> None:
        """Download with one logical stream at a time; resume via HTTP Range on reconnect."""
        if isinstance(urls, str):
            candidates = [urls, fallback_url]
        else:
            candidates = list(urls)
            if fallback_url:
                candidates.append(fallback_url)
        normalized: list[str] = []
        for raw in candidates:
            url = str(raw or "").strip()
            if not url:
                continue
            if url.startswith("/"):
                url = urllib.parse.urljoin("https://goshkow.com", url)
            if url not in normalized:
                normalized.append(url)
        if not normalized:
            raise MarketplaceError("no_url", "No download URL in ticket")

        last_error: BaseException | None = None
        wall_started = time.monotonic()
        attempt = 0
        while attempt < self.DOWNLOAD_ATTEMPTS:
            attempt += 1
            if time.monotonic() - wall_started >= self.DOWNLOAD_WALL_SEC:
                raise MarketplaceError(
                    "timeout",
                    "Загрузка модификации превысила лимит времени. Попробуйте снова.",
                )
            already = target.stat().st_size if target.exists() else 0
            if expected_size > 0 and already >= expected_size:
                return
            if job is not None:
                self._raise_if_stopped(job)
                job.bytes_done = already
                if expected_size > 0 and already > 0:
                    job.progress = max(job.progress, min(0.89, already / expected_size))
                    self._emit_job(job)

            url = normalized[(attempt - 1) % len(normalized)]
            try:
                self._stream_to_file(url, target, resume_from=already, job=job)
                done = target.stat().st_size if target.exists() else 0
                if expected_size > 0 and done < expected_size:
                    # Incomplete body — keep partial and retry with Range.
                    last_error = MarketplaceError(
                        "incomplete_body",
                        f"Incomplete download: {done}/{expected_size}",
                    )
                    self._log(
                        "warning",
                        "Marketplace incomplete body, resuming with Range",
                        bytes=done,
                        expected=expected_size,
                        attempt=attempt,
                    )
                    time.sleep(min(2.0, 0.4 * attempt))
                    continue
                return
            except MarketplaceError as error:
                if error.code in {"cancelled", "paused"}:
                    raise
                last_error = error
                self._log(
                    "warning",
                    "Marketplace download attempt failed, will resume",
                    source=url,
                    error=str(error),
                    attempt=attempt,
                    bytes=(target.stat().st_size if target.exists() else 0),
                )
                time.sleep(min(2.5, 0.5 * attempt))
            except Exception as error:
                last_error = error
                self._log(
                    "warning",
                    "Marketplace download attempt failed, will resume",
                    source=url,
                    error=str(error),
                    attempt=attempt,
                )
                time.sleep(min(2.5, 0.5 * attempt))

        if isinstance(last_error, MarketplaceError):
            raise last_error
        if last_error is not None:
            raise MarketplaceError("network_error", self._friendly_network_message(last_error)) from last_error
        raise MarketplaceError("no_url", "No usable download URL")

    def _stream_to_file(self, url: str, target: Path, *, resume_from: int, job: DownloadJob | None = None) -> None:
        headers = {
            "User-Agent": self.USER_AGENT,
            "X-Zapret-Device": self._device_id,
            "Accept": "*/*",
        }
        mode = "wb"
        if resume_from > 0:
            headers["Range"] = f"bytes={resume_from}-"
            mode = "ab"
        request = urllib.request.Request(url, headers=headers, method="GET")
        # Open + read MUST stay on the same thread. Soft stall timeout (not a hard 15s abort).
        sock_timeout = float(self.DOWNLOAD_STALL_SEC)
        try:
            response = urllib.request.urlopen(request, timeout=sock_timeout)
        except MarketplaceError:
            raise
        except urllib.error.HTTPError as error:
            body = ""
            try:
                body = error.read().decode("utf-8-sig", errors="ignore")
            except Exception:
                body = ""
            if error.code == 409 or "download already active" in body.lower():
                raise MarketplaceError(
                    "download_active",
                    "На сервере уже есть активная загрузка. Повторите через несколько секунд.",
                    details={"raw": body[:240]},
                ) from error
            raise MarketplaceError("network_error", self._friendly_network_message(error)) from error
        except Exception as error:
            raise MarketplaceError("network_error", self._friendly_network_message(error)) from error

        try:
            status = int(getattr(response, "status", None) or response.getcode() or 0)
            if resume_from > 0 and status == 200:
                # Server ignored Range — rewrite to avoid corrupt concat.
                mode = "wb"
                resume_from = 0
            elif resume_from > 0 and status not in {206, 200}:
                raise MarketplaceError("http_error", f"Unexpected resume status HTTP {status}")

            content_length = 0
            try:
                content_length = int(response.headers.get("Content-Length") or 0)
            except Exception:
                content_length = 0
            if job is not None:
                if job.bytes_total <= 0 and content_length > 0:
                    job.bytes_total = int(resume_from) + content_length
                    self._emit_job(job)
                elif job.bytes_total <= 0:
                    content_range = str(response.headers.get("Content-Range") or "")
                    match = re.search(r"/(\d+)\s*$", content_range)
                    if match:
                        job.bytes_total = int(match.group(1))
                        self._emit_job(job)

            done = int(resume_from)
            last_emit = 0.0
            started = time.monotonic()
            last_chunk = started
            with target.open(mode) as handle:
                while True:
                    if job is not None:
                        self._raise_if_stopped(job)
                    now = time.monotonic()
                    if now - started >= self.DOWNLOAD_WALL_SEC:
                        raise MarketplaceError(
                            "timeout",
                            "Загрузка модификации превысила лимит времени. Попробуйте снова.",
                        )
                    if now - last_chunk >= self.DOWNLOAD_STALL_SEC:
                        raise MarketplaceError(
                            "timeout",
                            "Загрузка модификации зависла (нет данных). Проверьте сеть и попробуйте снова.",
                        )
                    try:
                        chunk = response.read(1024 * 256)
                    except TimeoutError as error:
                        raise MarketplaceError(
                            "timeout",
                            "Загрузка модификации зависла (нет данных). Проверьте сеть и попробуйте снова.",
                        ) from error
                    except OSError as error:
                        if "timed out" in str(error).lower():
                            raise MarketplaceError(
                                "timeout",
                                "Загрузка модификации зависла (нет данных). Проверьте сеть и попробуйте снова.",
                            ) from error
                        raise MarketplaceError("network_error", self._friendly_network_message(error)) from error
                    if not chunk:
                        break
                    last_chunk = time.monotonic()
                    handle.write(chunk)
                    done += len(chunk)
                    if job is None:
                        continue
                    job.bytes_done = done
                    if job.bytes_total > 0:
                        job.progress = max(0.01, min(0.89, done / job.bytes_total))
                    else:
                        job.progress = max(0.05, min(0.85, job.progress + 0.01))
                    emit_now = time.monotonic()
                    if emit_now - last_emit >= 0.12:
                        last_emit = emit_now
                        self._emit_job(job)
                        self._emit_queue()
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _verify_file(self, path: Path, *, expected_size: int, expected_sha256: str) -> None:
        actual_size = path.stat().st_size
        if expected_size and actual_size != expected_size:
            path.unlink(missing_ok=True)
            raise MarketplaceError("size_mismatch", f"Size mismatch: {actual_size} != {expected_size}")
        if expected_sha256:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 256)
                    if not chunk:
                        break
                    digest.update(chunk)
            actual = digest.hexdigest().lower()
            if actual != expected_sha256.lower():
                path.unlink(missing_ok=True)
                raise MarketplaceError("checksum_mismatch", "SHA-256 mismatch")

    def _install_zip(
        self,
        zip_path: Path,
        *,
        compatibility: str,
        title: str = "",
        author: str = "",
        summary: str = "",
        icon_url: str = "",
        project_url: str = "",
        slug: str = "",
        marketplace_version: str = "",
        skip_remove: bool = False,
    ) -> str:
        """Install via the same filtered ZIP import path as manual mod import."""
        if not skip_remove:
            self._remove_existing_by_slug(slug, compatibility=compatibility)
        version = str(marketplace_version or "").strip()
        if compatibility == "zapret2":
            if self.mods2 is None:
                raise MarketplaceError("no_mods2", "Zapret2 mods manager unavailable")
            entry = self.mods2.import_from_path(zip_path)
            # Cache locally for instant/offline display, but persist the remote URL.
            # A partial reinstall can move the mod directory; a file:// URL from
            # the old directory then becomes a permanent broken cover.
            self._cache_cover_image(Path(entry.path), icon_url)
            try:
                entry = self.mods2.update_metadata(
                    entry.id,
                    name=title.strip() or entry.name,
                    description=summary.strip() or entry.description,
                    author=author.strip() or entry.author,
                    version=version or entry.version,
                    icon_url=icon_url,
                    marketplace_slug=slug,
                    source_url=project_url,
                )
                self._verify_installed_entry(self.mods2, entry.id, slug)
            except Exception as error:
                self._rollback_failed_import(self.mods2, entry.id)
                raise MarketplaceError("install_failed", f"Не удалось зарегистрировать модификацию: {error}") from error
            return str(entry.id)
        if self.mods is None:
            raise MarketplaceError("no_mods", "Mods manager unavailable")
        entry = self.mods.import_from_path(str(zip_path))
        # See the Zapret2 branch above: disk cache is an implementation detail,
        # while metadata must survive a mod directory replacement.
        self._cache_cover_image(Path(entry.path), icon_url)
        try:
            entry = self.mods.update_metadata(
                entry.id,
                name=title.strip() or entry.name,
                description=summary.strip() or entry.description,
                author=author.strip() or entry.author,
                version=version or entry.version,
                icon_url=icon_url,
                marketplace_slug=slug,
                source_url=project_url,
            )
            self._verify_installed_entry(self.mods, entry.id, slug)
        except Exception as error:
            self._rollback_failed_import(self.mods, entry.id)
            raise MarketplaceError("install_failed", f"Не удалось зарегистрировать модификацию: {error}") from error
        return str(entry.id)

    @staticmethod
    def _verify_installed_entry(manager: Any, mod_id: str, slug: str) -> None:
        saved = next((item for item in manager.list_installed() if str(item.id) == str(mod_id)), None)
        if saved is None:
            raise RuntimeError("модификация отсутствует в реестре установленных")
        if str(getattr(saved, "marketplace_slug", "") or "").strip() != str(slug or "").strip():
            raise RuntimeError("не сохранена связь с Marketplace")
        if not Path(str(getattr(saved, "path", "") or "")).exists():
            raise RuntimeError("папка модификации не создана")

    def _rollback_failed_import(self, manager: Any, mod_id: str) -> None:
        try:
            manager.remove(mod_id)
        except Exception as rollback_error:
            self._log("warning", "Failed to rollback Marketplace import", mod_id=mod_id, error=str(rollback_error))

    def _cache_cover_image(self, mod_path: Path, icon_url: str) -> str:
        """Download author-uploaded cover into the mod folder; return file:// URI when possible."""
        url = str(icon_url or "").strip()
        if not url.startswith(("http://", "https://")):
            return url
        try:
            mod_path.mkdir(parents=True, exist_ok=True)
            suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                suffix = ".img"
            target = mod_path / f"zapret-hub-cover{suffix}"
            request = urllib.request.Request(
                url,
                headers={"User-Agent": self.USER_AGENT, "Accept": "image/*,*/*"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read()
            if not data or len(data) > 8 * 1024 * 1024:
                return url
            target.write_bytes(data)
            return target.resolve().as_uri()
        except Exception as error:
            self._log("warning", "Marketplace cover cache failed", error=str(error), url=url)
            return url

    @staticmethod
    def _is_broken_local_cover(url: str) -> bool:
        value = str(url or "").strip()
        if not value.lower().startswith("file:"):
            return False
        try:
            return not Path(urllib.parse.unquote(urllib.parse.urlparse(value).path)).exists()
        except Exception:
            return True

    def repair_installed_covers(self, *, lang: str = "ru") -> int:
        """Repair legacy file:// cover links after a partial mod reinstall.

        This is deliberately a background-only operation. It consults the public
        project metadata only for entries whose cached local cover no longer
        exists, then keeps a fresh local cache while saving the stable remote URL.
        """
        repaired = 0
        for manager in (self.mods, self.mods2):
            if manager is None:
                continue
            try:
                entries = manager.list_installed()
            except Exception:
                continue
            for entry in entries:
                current = str(getattr(entry, "icon_url", "") or "").strip()
                slug = str(getattr(entry, "marketplace_slug", "") or "").strip()
                if not slug or not self._is_broken_local_cover(current):
                    continue
                try:
                    detail = self.get_project(slug, lang=lang)
                    project = detail.get("project") if isinstance(detail, dict) else {}
                    remote = str((project or {}).get("iconUrl") or "").strip()
                    if not remote.startswith(("http://", "https://")):
                        continue
                    self._cache_cover_image(Path(str(entry.path)), remote)
                    manager.update_metadata(entry.id, icon_url=remote)
                    repaired += 1
                except Exception as error:
                    self._log("warning", "Marketplace cover repair failed", slug=slug, error=str(error))
        return repaired
