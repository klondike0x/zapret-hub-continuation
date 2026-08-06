from __future__ import annotations

from typing import Any


# Conflict profiles: gaming set X breaks app Y → prefer fix set.
KNOWN_CONFLICTS: dict[str, dict[str, Any]] = {
    "ark": {
        "app": "ark",
        "process_keys": ("ark", "shootergame", "arkascended", "asa"),
        "broken_gaming_set": "stun-wide-base",
        "fix_gaming_set": "stun-wide-base-local-exclude",
        "udp_voice_ports": (3478, 3479, 3480, 5060, 5062),
        "require_udp": True,
        "message_ru": "Конфликт: режим Gaming для Ark Raiders мешает голосовому чату — пробую вариант с исключением локальных сетей.",
        "message_en": "Conflict: Gaming mode breaks Ark Raiders voice chat — trying local-network exclude.",
    },
    "back4blood": {
        "app": "back4blood",
        "process_keys": ("back4blood", "b4b"),
        "broken_gaming_set": "stun-wide-base-local-exclude",
        "fix_gaming_set": "stun-wide-base",
        "require_udp": False,
        "message_ru": "Для Back4Blood лучше подходит Gaming STUN · Wide · Base.",
        "message_en": "Back4Blood works best with Gaming STUN · Wide · Base.",
    },
}


class ConflictDetector:
    KNOWN = KNOWN_CONFLICTS

    def __init__(self, learned: list[dict[str, Any]] | None = None) -> None:
        self._learned = list(learned or [])

    def load_learned(self, rows: list[dict[str, Any]]) -> None:
        self._learned = list(rows or [])

    def detect(
        self,
        *,
        process: str,
        current_gaming_set: str,
        proto: str = "",
        remote_port: int = 0,
        symptom: str = "",
    ) -> dict[str, Any] | None:
        """Return conflict only when gaming set matches AND (UDP voice / require flags)."""
        name = (process or "").lower()
        if name.endswith(".exe"):
            name = name[:-4]

        for payload in self._learned:
            hit = self._match_payload(name, current_gaming_set, proto, remote_port, symptom, payload)
            if hit is not None:
                hit["source"] = "learned"
                return hit

        for key, payload in self.KNOWN.items():
            keys = tuple(payload.get("process_keys") or (key,))
            if not any(token in name for token in keys):
                continue
            hit = self._match_payload(name, current_gaming_set, proto, remote_port, symptom, payload)
            if hit is not None:
                hit["matched_key"] = key
                hit["source"] = "builtin"
                return hit
        return None

    @staticmethod
    def _match_payload(
        name: str,
        current_gaming_set: str,
        proto: str,
        remote_port: int,
        symptom: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        broken = str(payload.get("broken_gaming_set") or "")
        if broken and current_gaming_set and current_gaming_set != broken:
            return None

        require_udp = bool(payload.get("require_udp"))
        voice_ports = {int(p) for p in (payload.get("udp_voice_ports") or ())}
        if require_udp:
            # Only fire on UDP voice/STUN, not random TCP site fails while the game runs.
            if proto != "udp":
                return None
            if voice_ports and remote_port and int(remote_port) not in voice_ports:
                return None

        result = dict(payload)
        result["current_gaming_set"] = current_gaming_set
        result["process"] = name
        return result


def detect_conflict(context: dict | None = None) -> dict | None:
    data = context or {}
    process = str(data.get("process") or "")
    gaming_set = str(data.get("gaming_set") or data.get("current_gaming_set") or "stun-wide-base")
    return ConflictDetector().detect(
        process=process,
        current_gaming_set=gaming_set,
        proto=str(data.get("proto") or ""),
        remote_port=int(data.get("remote_port") or 0),
        symptom=str(data.get("symptom") or ""),
    )


def describe_conflict(conflict: dict | None = None, *, language: str = "ru") -> str:
    if not conflict:
        return ""
    lang = (language or "ru").lower()
    if lang.startswith("ru"):
        return str(conflict.get("message_ru") or conflict.get("message") or "")
    return str(conflict.get("message_en") or conflict.get("message_ru") or conflict.get("message") or "")
