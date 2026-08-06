from __future__ import annotations

import base64
import json
import re
import ssl
import time
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

import certifi

from zapret_hub.services.logging_service import LoggingManager
from zapret_hub.services.storage import StorageManager


GOSHKOW_VPN_HOST = "vpn.goshkow.com"
GOSHKOW_VPN_LEGACY_HOST = "vpn.goshkow.ru"
GOSHKOW_VPN_ACCESS_URL = "https://vpn.goshkow.com"


class GoshkowVpnManager:
    def __init__(self, storage: StorageManager, logging: LoggingManager) -> None:
        self.storage = storage
        self.logging = logging
        self._state_path = self.storage.paths.data_dir / "goshkow_vpn.json"

    def state(self) -> dict[str, Any]:
        raw = self.storage.read_json(self._state_path, default={}) or {}
        if not isinstance(raw, dict):
            raw = {}
        subscription_state = str(raw.get("subscription_state", "") or "").strip() or "empty"
        if subscription_state == "empty" and raw.get("subscription_url") and raw.get("servers") and raw.get("selected_server_id"):
            subscription_state = "valid"
        subscription_url = str(raw.get("subscription_url", "") or "")
        if subscription_url.startswith(f"https://{GOSHKOW_VPN_LEGACY_HOST}/"):
            subscription_url = f"https://{GOSHKOW_VPN_HOST}/{subscription_url.split('/', 3)[3]}"
        return {
            "subscription_url": subscription_url,
            "subscription_state": subscription_state,
            "servers": list(raw.get("servers", []) or []),
            "selected_server_id": str(raw.get("selected_server_id", "") or ""),
            "last_auto_server_id": str(raw.get("last_auto_server_id", "") or ""),
            "last_auto_server_name": str(raw.get("last_auto_server_name", "") or ""),
            "days_remaining": raw.get("days_remaining", None),
            "used_traffic_bytes": int(raw.get("used_traffic_bytes", 0) or 0),
            "routing_mode": str(raw.get("routing_mode", "global") or "global"),
            "rules_mode": str(raw.get("rules_mode", "blacklist") or "blacklist"),
            "processes": str(raw.get("processes", "") or ""),
            "processes_exclude_mode": bool(raw.get("processes_exclude_mode", False)),
            "system_proxy_mode": str(raw.get("system_proxy_mode", "set") or "set"),
            "tun_enabled": bool(raw.get("tun_enabled", True)),
            "auto_reconnect": bool(raw.get("auto_reconnect", True)),
            "last_updated_at": str(raw.get("last_updated_at", "") or ""),
            "last_error": str(raw.get("last_error", "") or ""),
        }

    def is_configured(self) -> bool:
        current = self.state()
        return bool(
            current["subscription_state"] == "valid"
            and current["subscription_url"]
            and current["servers"]
            and (current["selected_server_id"] or current["selected_server_id"] == "auto")
        )

    def save(self, **changes: Any) -> dict[str, Any]:
        current = self.state()
        current.update(changes)
        self.storage.write_json(self._state_path, current)
        return current

    def reset_traffic(self) -> dict[str, Any]:
        return self.save(used_traffic_bytes=0)

    def add_traffic(self, byte_count: int) -> dict[str, Any]:
        current = self.state()
        return self.save(used_traffic_bytes=max(0, int(current["used_traffic_bytes"]) + max(0, int(byte_count))))

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "selected_server_id",
            "routing_mode",
            "rules_mode",
            "processes",
            "processes_exclude_mode",
            "system_proxy_mode",
            "tun_enabled",
            "auto_reconnect",
        }
        changes = {key: payload[key] for key in allowed if key in payload}
        if "routing_mode" in changes and changes["routing_mode"] not in {"global", "blacklist", "whitelist"}:
            changes["routing_mode"] = "global"
        if "rules_mode" in changes and changes["rules_mode"] not in {"blacklist", "whitelist"}:
            changes["rules_mode"] = "blacklist"
        if "system_proxy_mode" in changes and changes["system_proxy_mode"] not in {"clear", "set", "unchanged", "pac"}:
            changes["system_proxy_mode"] = "set"
        if "selected_server_id" in changes:
            changes["auto_excluded_server_ids"] = []
            if str(changes.get("selected_server_id") or "") != "auto":
                changes["last_auto_server_id"] = ""
                changes["last_auto_server_name"] = ""
        return self.save(**changes)

    def import_subscription(self, url: str) -> dict[str, Any]:
        submitted_url = str(url or "").strip()
        if not submitted_url:
            return self.save(
                subscription_url="",
                subscription_state="empty",
                servers=[],
                selected_server_id="",
                days_remaining=None,
                last_updated_at=datetime.now(timezone.utc).isoformat(),
                last_error="",
            )
        try:
            normalized = self._normalize_subscription_url(submitted_url)
        except Exception as error:
            return self.save(
                subscription_url=submitted_url,
                subscription_state="invalid",
                servers=[],
                selected_server_id="",
                days_remaining=None,
                last_updated_at=datetime.now(timezone.utc).isoformat(),
                last_error=str(error),
            )
        try:
            body, headers = self._download_subscription(normalized)
        except Exception as error:
            return self.save(
                subscription_url=normalized,
                subscription_state="invalid",
                servers=[],
                selected_server_id="",
                days_remaining=None,
                last_updated_at=datetime.now(timezone.utc).isoformat(),
                last_error=str(error),
            )
        servers = self._parse_subscription(body)
        if not servers:
            return self.save(
                subscription_url=normalized,
                subscription_state="invalid",
                servers=[],
                selected_server_id="",
                days_remaining=self._days_remaining_from_headers(headers),
                last_updated_at=datetime.now(timezone.utc).isoformat(),
                last_error="В подписке не найдено ни одной поддерживаемой локации.",
            )
        current = self.state()
        if str(current.get("selected_server_id") or "") == "auto":
            selected = "auto"
        else:
            selected = self._match_selected_server_id(str(current.get("selected_server_id") or ""), servers)
        if not selected:
            selected = "auto"
        days_remaining = self._days_remaining_from_headers(headers)
        return self.save(
            subscription_url=normalized,
            subscription_state="valid",
            servers=servers,
            selected_server_id=selected,
            auto_excluded_server_ids=[],
            last_auto_server_id="" if selected == "auto" else current.get("last_auto_server_id", ""),
            last_auto_server_name="" if selected == "auto" else current.get("last_auto_server_name", ""),
            days_remaining=days_remaining,
            last_updated_at=datetime.now(timezone.utc).isoformat(),
            last_error="",
        )

    def refresh_subscription(self) -> dict[str, Any]:
        url = self.state()["subscription_url"]
        if not url:
            raise ValueError("Ссылка подписки ещё не добавлена.")
        return self.import_subscription(url)

    def selected_server(self) -> dict[str, Any] | None:
        current = self.state()
        selected = current["selected_server_id"]
        if selected == "auto":
            selected = current.get("last_auto_server_id") or ""
        for server in current["servers"]:
            if isinstance(server, dict) and str(server.get("id", "")) == selected:
                return dict(server)
        return None

    def _normalize_subscription_url(self, url: str) -> str:
        value = str(url or "").strip()
        parsed = urllib.parse.urlparse(value)
        host = parsed.netloc.lower()
        if parsed.scheme != "https" or host not in {GOSHKOW_VPN_HOST, GOSHKOW_VPN_LEGACY_HOST}:
            raise ValueError("Поддерживаются только подписки с домена vpn.goshkow.com.")
        if not parsed.path.startswith("/sub/"):
            raise ValueError("Ссылка должна вести на подписку vpn.goshkow.com/sub/...")
        return urllib.parse.urlunparse(parsed._replace(netloc=GOSHKOW_VPN_HOST, fragment=""))

    def _download_subscription(self, url: str) -> tuple[str, dict[str, str]]:
        errors: list[str] = []
        contexts = (
            ("system", ssl.create_default_context()),
            ("certifi", ssl.create_default_context(cafile=certifi.where())),
        )
        for label, context in contexts:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Zapret-Hub/3.0 goshkow-vpn",
                    "Accept": "text/plain, application/octet-stream, */*",
                    "Cache-Control": "no-cache",
                    "Connection": "close",
                },
            )
            try:
                # A new HTTPSHandler/context forces a fresh TLS handshake instead of
                # reusing a stale intermediary chain from a long-running process.
                opener = urllib.request.build_opener(
                    urllib.request.ProxyHandler({}),
                    urllib.request.HTTPSHandler(context=context),
                )
                with opener.open(request, timeout=14) as response:
                    raw = response.read()
                    headers = {key.lower(): value for key, value in response.headers.items()}
                if label != "system":
                    self.logging.log("info", "goshkow VPN certificate fallback succeeded", ssl_path=label)
                return raw.decode("utf-8", errors="ignore"), headers
            except Exception as error:
                errors.append(f"{label}: {error}")
                if not self._is_certificate_error(error):
                    break
                self.logging.log(
                    "warning",
                    "goshkow VPN certificate retry",
                    ssl_path=label,
                    error=str(error),
                )
        detail = "; ".join(errors) or "неизвестная ошибка сети"
        raise RuntimeError(f"Не удалось загрузить подписку goshkow vpn: {detail}")

    @staticmethod
    def _is_certificate_error(error: BaseException) -> bool:
        if isinstance(error, ssl.SSLCertVerificationError):
            return True
        if isinstance(error, urllib.error.URLError):
            reason = getattr(error, "reason", None)
            if isinstance(reason, ssl.SSLCertVerificationError):
                return True
            if isinstance(reason, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(reason).upper():
                return True
        return "CERTIFICATE_VERIFY_FAILED" in str(error).upper()

    def _parse_subscription(self, text: str) -> list[dict[str, Any]]:
        decoded = self._maybe_decode_base64(text)
        lines = [line.strip() for line in decoded.replace("\r", "\n").split("\n") if line.strip()]
        servers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, line in enumerate(lines):
            server = self._parse_subscription_line(line, index)
            if server is None:
                continue
            key = str(server["id"])
            if key in seen:
                continue
            seen.add(key)
            servers.append(server)
        return servers

    def _maybe_decode_base64(self, text: str) -> str:
        stripped = "".join(str(text or "").strip().split())
        if "://" in stripped:
            return text
        try:
            padded = stripped + "=" * (-len(stripped) % 4)
            decoded = base64.b64decode(padded, validate=False).decode("utf-8", errors="ignore")
            return decoded if "://" in decoded else text
        except Exception:
            return text

    def _parse_subscription_line(self, line: str, index: int) -> dict[str, Any] | None:
        parsed = urllib.parse.urlparse(line)
        scheme = parsed.scheme.lower()
        if scheme not in {"vless", "vmess", "trojan", "ss", "hysteria2", "hy2"}:
            return None
        name = self._clean_server_name(urllib.parse.unquote(parsed.fragment or "").strip())
        host = parsed.hostname or ""
        if scheme == "vmess":
            vmess = self._parse_vmess(line)
            if vmess is not None:
                name = self._clean_server_name(vmess.get("name", name) or name)
                host = vmess.get("host", host) or host
        if not name:
            name = host or f"Сервер {index + 1}"
        server_id = f"{scheme}:{host}:{index}".lower()
        return {
            "id": server_id,
            "name": name,
            "type": scheme,
            "host": host,
            "raw": line,
        }

    def _clean_server_name(self, value: str) -> str:
        text = str(value or "").strip()
        text = re.sub(r"[\U0001F1E6-\U0001F1FF]{2}", "", text)
        text = re.sub(r"[\U0001F300-\U0001FAFF]", " ", text)
        text = text.replace(" - ", " ").replace(" #", " ").replace("#", "")
        text = " ".join(text.split()).strip(" -–—")
        return text

    def _match_selected_server_id(self, selected_id: str, servers: list[dict[str, Any]]) -> str:
        selected = str(selected_id or "").strip().lower()
        if not selected:
            return ""
        server_ids = {str(item.get("id", "")).lower() for item in servers if isinstance(item, dict)}
        if selected in server_ids:
            return selected_id
        parts = selected.split(":", 3)
        if len(parts) >= 3:
            scheme, host, index = parts[0], parts[1], parts[2]
            candidate = f"{scheme}:{host}:{index}"
            if candidate in server_ids:
                return candidate
        return ""

    def _parse_vmess(self, line: str) -> dict[str, str] | None:
        try:
            raw = line.split("://", 1)[1].strip()
            padded = raw + "=" * (-len(raw) % 4)
            data = json.loads(base64.b64decode(padded).decode("utf-8", errors="ignore"))
            if not isinstance(data, dict):
                return None
            return {"name": str(data.get("ps", "") or ""), "host": str(data.get("add", "") or "")}
        except Exception:
            return None

    def _days_remaining_from_headers(self, headers: dict[str, str]) -> int | None:
        userinfo = headers.get("subscription-userinfo", "")
        if not userinfo:
            return None
        values: dict[str, int] = {}
        for part in userinfo.split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            try:
                values[key.strip().lower()] = int(value.strip())
            except ValueError:
                continue
        expire = values.get("expire")
        if not expire:
            return None
        return max(0, int((expire - int(time.time())) / 86400))
