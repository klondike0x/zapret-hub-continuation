from __future__ import annotations

"""Detect live calls / matches so orchestrator does not kill winws mid-session."""

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class SessionLock:
    active: bool
    kind: str = ""  # call | game | ""
    reason: str = ""


_CALL_PROCESS_TOKENS: tuple[str, ...] = (
    "discord",
    "discordptb",
    "discordcanary",
    "zoom",
    "zoom.exe",
    "teams",
    "ms-teams",
    "msteams",
    "skype",
    "skypeapp",
    "slack",
    "telegram",
    "whatsapp",
    "webex",
    "cisco jabber",
    "ringcentral",
    "voximplant",
)

_GAME_PROCESS_TOKENS: tuple[str, ...] = (
    "fortniteclient",
    "fortniteclient-win64-shipping",
    "valorant",
    "valorant-win64-shipping",
    "cs2",
    "csgo",
    "dota2",
    "league of legends",
    "leagueclient",
    "riotclientservices",
    "overwatch",
    "r5apex",
    "r5apex_dx12",
    "cod.exe",
    "codmw",
    "modernwarfare",
    "gta5",
    "gtav",
    "playgtav",
    "escapefromtarkov",
    "huntgame",
    "pubg",
    "tslgame",
    "destiny2",
    "warzone",
    "rocketleague",
    "shootergame",  # Destiny / some UE shooters
    "bf2042",
    "bf1",
    "bfv",
)

# Discord / Zoom voice-ish UDP — treat as active call when process also matches.
_VOICE_UDP_PORTS = frozenset(range(19294, 19345)) | frozenset(range(50000, 50101)) | frozenset({3478, 3479, 3480})


def _basename(process: str) -> str:
    blob = (process or "").replace("\\", "/").lower()
    name = blob.rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".exe") else name


def _token_hit(process: str, tokens: Iterable[str]) -> str:
    blob = (process or "").replace("\\", "/").lower()
    base = _basename(process)
    for token in tokens:
        key = token.lower()
        if key in base or key in blob:
            return token
    return ""


def detect_session_lock(
    samples: list[Any] | None = None,
    *,
    process_names: list[str] | None = None,
) -> SessionLock:
    """Return a session lock when a call or game match appears live.

    Prefer connection samples (voice UDP + process). Fall back to process list.
    """
    processes: list[str] = list(process_names or [])
    for sample in samples or []:
        proc = str(getattr(sample, "process", "") or "")
        if proc:
            processes.append(proc)
        port = int(getattr(sample, "remote_port", 0) or 0)
        proto = str(getattr(sample, "proto", "") or "").lower()
        if proto == "udp" and port in _VOICE_UDP_PORTS:
            hit = _token_hit(proc, _CALL_PROCESS_TOKENS)
            if hit or not proc:
                label = hit or "voice-udp"
                return SessionLock(True, "call", f"active voice ({label})")

    for proc in processes:
        game = _token_hit(proc, _GAME_PROCESS_TOKENS)
        if game:
            return SessionLock(True, "game", f"game process ({game})")
        call = _token_hit(proc, _CALL_PROCESS_TOKENS)
        if call:
            # Discord/Zoom running is enough to defer hard restarts; voice UDP strengthens it.
            return SessionLock(True, "call", f"call app ({call})")

    return SessionLock(False)
