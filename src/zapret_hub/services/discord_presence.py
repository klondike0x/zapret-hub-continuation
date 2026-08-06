"""Discord Rich Presence via local IPC (no OAuth / no extra deps).

Requires Discord desktop running. Application ID defaults to the Hub app;
override with settings or ``ZAPRET_HUB_DISCORD_CLIENT_ID``. Optional art keys:
``logo``, ``zapret``, ``zapret2``, ``idle``.
"""
from __future__ import annotations

import json
import os
import random
import socket
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Callable


OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4

# Built-in Zapret Hub Discord application (Developer Portal).
DEFAULT_DISCORD_CLIENT_ID = "1530470595710685314"

# Fun lines picked once per Hub launch (RU / EN). Original phrasing — not NetFix copies.
STATUS_FLAVORS_RU: tuple[str, ...] = (
    "Сидит в Hub и следит за пакетами",
    "Держит DPI на коротком поводке",
    "Кормит сеть правильными маршрутами",
    "Разминает обход перед выходом в мир",
    "Греет стратегию, пока ты в чате",
    "Чистит помехи между тобой и Discord",
    "Собирает пакеты в аккуратный строй",
    "Шепчет winws нужные аргументы",
    "Перекладывает блокировки в архив",
    "Ловит Wi‑Fi за хвост и не отпускает",
    "Смотрит на TLS как на конструктор",
    "Качает атмосферу свободного интернета",
    "Живёт в трее и охраняет соединение",
    "Чинит путь до любимых сервисов",
    "Держит паузу на чужих фильтрах",
)

STATUS_FLAVORS_EN: tuple[str, ...] = (
    "Parked in Hub, watching packets",
    "Keeping DPI on a short leash",
    "Feeding the network clean routes",
    "Warming up bypass before go-time",
    "Heating a strategy while you chat",
    "Clearing static between you and Discord",
    "Lining packets up in neat rows",
    "Whispering the right args to winws",
    "Filing blocks under ‘not today’",
    "Holding Wi‑Fi by the tail",
    "Treating TLS like a puzzle box",
    "Pumping free-internet vibes",
    "Living in the tray, guarding the link",
    "Repairing the path to favorite apps",
    "Putting foreign filters on pause",
)

assert len(STATUS_FLAVORS_RU) == len(STATUS_FLAVORS_EN) >= 15


@dataclass(slots=True)
class PresenceSnapshot:
    enabled: bool
    powered: bool
    runtime_mode: str
    control_mode: str
    general_name: str
    strategy_id: str
    language: str
    version: str


class DiscordIpcClient:
    """Minimal Discord IPC client (Windows named pipe / Unix socket)."""

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._pipe: BinaryIO | None = None
        self._lock = threading.RLock()
        self.client_id = ""

    @property
    def connected(self) -> bool:
        return self._sock is not None or self._pipe is not None

    def connect(self, client_id: str) -> None:
        client_id = str(client_id or "").strip()
        if not client_id:
            raise RuntimeError("discord_client_id_missing")
        with self._lock:
            self.close()
            self.client_id = client_id
            if os.name == "nt":
                self._pipe = self._open_windows_pipe()
            else:
                self._sock = self._open_unix_socket()
            self._send(OP_HANDSHAKE, {"v": 1, "client_id": client_id})
            # Read READY (or error) once.
            self._recv(timeout=2.5)

    def set_activity(self, activity: dict[str, Any] | None, *, pid: int) -> None:
        with self._lock:
            if not self.connected:
                raise RuntimeError("discord_ipc_not_connected")
            payload = {
                "cmd": "SET_ACTIVITY",
                "args": {"pid": int(pid), "activity": activity},
                "nonce": str(uuid.uuid4()),
            }
            self._send(OP_FRAME, payload)
            # Drain one response (best-effort); ignore timeouts.
            try:
                self._recv(timeout=0.8)
            except Exception:
                pass

    def clear(self, *, pid: int) -> None:
        try:
            self.set_activity(None, pid=pid)
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            sock = self._sock
            pipe = self._pipe
            self._sock = None
            self._pipe = None
            self.client_id = ""
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            if pipe is not None:
                try:
                    pipe.close()
                except Exception:
                    pass

    def _open_windows_pipe(self) -> BinaryIO:
        errors: list[str] = []
        for index in range(10):
            path = rf"\\?\pipe\discord-ipc-{index}"
            try:
                # Discord on Windows exposes IPC as a named pipe, not AF_UNIX.
                return open(path, "r+b", buffering=0)
            except OSError as error:
                errors.append(f"{path}: {error}")
        raise RuntimeError("discord_ipc_unavailable: " + "; ".join(errors[:4]))

    def _open_unix_socket(self) -> socket.socket:
        errors: list[str] = []
        candidates: list[str] = []
        bases = [
            os.environ.get("XDG_RUNTIME_DIR"),
            os.environ.get("TMPDIR"),
            os.environ.get("TMP"),
            os.environ.get("TEMP"),
            f"/run/user/{os.getuid()}" if hasattr(os, "getuid") else None,
            "/tmp",
        ]
        for base in bases:
            if not base:
                continue
            root = Path(base)
            for index in range(10):
                for suffix in (
                    f"discord-ipc-{index}",
                    f"snap.discord/discord-ipc-{index}",
                    f"app/com.discordapp.Discord/discord-ipc-{index}",
                ):
                    path = root / suffix
                    if path.exists():
                        candidates.append(str(path))
        if not hasattr(socket, "AF_UNIX"):
            raise RuntimeError("discord_ipc_unavailable: AF_UNIX missing")
        for path in candidates:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.settimeout(1.5)
                sock.connect(path)
                return sock
            except OSError as error:
                errors.append(f"{path}: {error}")
                try:
                    sock.close()
                except Exception:
                    pass
        raise RuntimeError("discord_ipc_unavailable: " + "; ".join(errors[:4]))

    def _send(self, op: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        header = struct.pack("<II", int(op), len(data))
        self._write_bytes(header + data)

    def _write_bytes(self, data: bytes) -> None:
        sock = self._sock
        pipe = self._pipe
        if sock is not None:
            sock.sendall(data)
            return
        if pipe is not None:
            pipe.write(data)
            pipe.flush()
            return
        raise RuntimeError("discord_ipc_not_connected")

    def _recv(self, *, timeout: float = 2.0) -> dict[str, Any]:
        if not self.connected:
            raise RuntimeError("discord_ipc_not_connected")
        sock = self._sock
        if sock is not None:
            sock.settimeout(timeout)
        # Named pipes don't support socket timeouts; keep reads short via buffering=0.
        header = self._recvexact(8)
        op, length = struct.unpack("<II", header)
        body = self._recvexact(int(length)) if length else b"{}"
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        if int(op) == OP_PING:
            try:
                self._send(OP_PONG, payload if isinstance(payload, dict) else {})
            except Exception:
                pass
        if int(op) == OP_CLOSE:
            self.close()
            raise RuntimeError("discord_ipc_closed")
        if isinstance(payload, dict) and payload.get("evt") == "ERROR":
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            raise RuntimeError(str(data.get("message") or "discord_ipc_error"))
        return payload if isinstance(payload, dict) else {}

    def _recvexact(self, size: int) -> bytes:
        chunks: list[bytes] = []
        remaining = int(size)
        sock = self._sock
        pipe = self._pipe
        while remaining > 0:
            if sock is not None:
                chunk = sock.recv(remaining)
            elif pipe is not None:
                chunk = pipe.read(remaining)
            else:
                raise RuntimeError("discord_ipc_not_connected")
            if not chunk:
                raise RuntimeError("discord_ipc_eof")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def format_uptime(started_at: int, *, ru: bool, now: int | None = None) -> str:
    elapsed = max(0, int(now if now is not None else time.time()) - int(started_at))
    hours, rem = divmod(elapsed, 3600)
    minutes = rem // 60
    if hours >= 1:
        return f"{hours}ч {minutes}м" if ru else f"{hours}h {minutes}m"
    if minutes >= 1:
        return f"{minutes}м" if ru else f"{minutes}m"
    return "только запущен" if ru else "just launched"


def pick_status_flavor(*, language: str = "ru", rng: random.Random | None = None) -> str:
    ru = str(language or "ru").lower().startswith("ru")
    pool = STATUS_FLAVORS_RU if ru else STATUS_FLAVORS_EN
    chooser = rng.choice if rng is not None else random.choice
    return str(chooser(pool))


def build_activity(
    snap: PresenceSnapshot,
    *,
    started_at: int,
    flavor: str,
    now: int | None = None,
) -> dict[str, Any]:
    """Build a SET_ACTIVITY payload from Hub runtime state + launch flavor line."""
    ru = str(snap.language or "ru").lower().startswith("ru")
    mode = str(snap.runtime_mode or "none")
    powered = bool(snap.powered)
    control = str(snap.control_mode or "manual")
    general = str(snap.general_name or "").strip()
    strategy = str(snap.strategy_id or "balanced").strip()
    details = (flavor or pick_status_flavor(language=snap.language)).strip()[:128]
    uptime = format_uptime(started_at, ru=ru, now=now)

    if not powered or mode in {"", "none"}:
        state = f"{'На паузе' if ru else 'Idle'} · {uptime}"
        small = "idle"
        small_text = "Idle"
    elif mode == "zapret2":
        if control == "auto":
            mode_bit = "Zapret 2 · авто" if ru else "Zapret 2 · auto"
        else:
            mode_bit = f"Zapret 2 · {strategy}"
        state = f"{mode_bit} · {uptime}"
        small = "zapret2"
        small_text = "Zapret 2"
    else:
        pretty = general.replace(".bat", "").strip() or "general"
        if control == "auto":
            mode_bit = f"Zapret 1 · авто · {pretty}" if ru else f"Zapret 1 · auto · {pretty}"
        else:
            mode_bit = f"Zapret 1 · {pretty}"
        state = f"{mode_bit} · {uptime}"
        small = "zapret"
        small_text = "Zapret 1"

    return {
        "details": details[:128],
        "state": state[:128],
        "timestamps": {"start": int(started_at)},
        "assets": {
            # Upload these keys in Discord Developer Portal → Rich Presence → Art Assets
            "large_image": "logo",
            "large_text": f"Zapret Hub {snap.version}".strip()[:128],
            "small_image": small,
            "small_text": small_text[:128],
        },
    }


class DiscordPresenceManager:
    """Background presence updater. Safe when Discord is closed or client id missing."""

    def __init__(
        self,
        *,
        get_settings: Callable[[], Any],
        get_snapshot: Callable[[], PresenceSnapshot],
        log: Callable[..., None] | None = None,
        pid: int | None = None,
    ) -> None:
        self._get_settings = get_settings
        self._get_snapshot = get_snapshot
        self._log = log or (lambda *_a, **_k: None)
        self._pid = int(pid or os.getpid())
        self._client = DiscordIpcClient()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._lock = threading.RLock()
        self._started_at = int(time.time())
        # Rotate the visible line periodically, but never repeat it immediately.
        self._flavor_index = random.randrange(len(STATUS_FLAVORS_RU))
        self._flavor_changed_at = time.monotonic()
        self._last_fingerprint = ""
        self._last_status = "idle"
        self._last_error = ""

    def _flavor_for(self, language: str) -> str:
        ru = str(language or "ru").lower().startswith("ru")
        pool = STATUS_FLAVORS_RU if ru else STATUS_FLAVORS_EN
        if time.monotonic() - self._flavor_changed_at >= 15 * 60:
            if len(pool) > 1:
                previous = self._flavor_index % len(pool)
                candidates = [index for index in range(len(pool)) if index != previous]
                self._flavor_index = random.choice(candidates)
            self._flavor_changed_at = time.monotonic()
        return pool[self._flavor_index % len(pool)]

    @property
    def status(self) -> dict[str, str]:
        return {
            "state": self._last_status,
            "error": self._last_error,
            "connected": "1" if self._client.connected else "0",
        }

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self.refresh()
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="zapret-hub-discord-rpc", daemon=True)
            self._thread.start()
            self.refresh()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        try:
            if self._client.connected:
                self._client.clear(pid=self._pid)
        except Exception:
            pass
        self._client.close()
        self._last_status = "stopped"
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.2)
        self._thread = None

    def refresh(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as error:
                self._last_error = str(error)
                self._last_status = "error"
                try:
                    self._log("warning", "Discord presence tick failed", error=str(error))
                except Exception:
                    pass
                self._client.close()
            self._wake.wait(timeout=12.0)
            self._wake.clear()

    def _tick(self) -> None:
        settings = self._get_settings()
        enabled = bool(getattr(settings, "discord_rpc_enabled", True))
        client_id = str(
            getattr(settings, "discord_rpc_client_id", "")
            or os.environ.get("ZAPRET_HUB_DISCORD_CLIENT_ID", "")
            or DEFAULT_DISCORD_CLIENT_ID
            or ""
        ).strip()
        if not enabled:
            if self._client.connected:
                try:
                    self._client.clear(pid=self._pid)
                except Exception:
                    pass
                self._client.close()
            self._last_status = "disabled"
            self._last_fingerprint = ""
            return
        if not client_id:
            if self._client.connected:
                try:
                    self._client.clear(pid=self._pid)
                except Exception:
                    pass
                self._client.close()
            self._last_status = "no_client_id"
            self._last_error = ""
            return

        snap = self._get_snapshot()
        activity = build_activity(
            snap,
            started_at=self._started_at,
            flavor=self._flavor_for(snap.language),
        )
        fingerprint = json.dumps(activity, sort_keys=True, ensure_ascii=False)

        if self._client.connected and self._client.client_id != client_id:
            self._client.close()
            self._last_fingerprint = ""

        if not self._client.connected:
            try:
                self._client.connect(client_id)
                self._last_status = "connected"
                self._last_error = ""
                self._last_fingerprint = ""
            except Exception as error:
                self._last_status = "discord_offline"
                self._last_error = str(error)
                return

        if fingerprint == self._last_fingerprint:
            return
        try:
            self._client.set_activity(activity, pid=self._pid)
            self._last_fingerprint = fingerprint
            self._last_status = "ok"
            self._last_error = ""
        except Exception as error:
            self._last_error = str(error)
            self._last_status = "error"
            self._client.close()
