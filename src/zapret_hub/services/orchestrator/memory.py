from __future__ import annotations

import time
from typing import Any


class WorkingMemory:
    """Short-term per-host / per-app debounce counters (orchestrator thread only)."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._items.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._items[key] = value

    def clear(self) -> None:
        self._items.clear()

    def bump_fail(self, host: str) -> int:
        key = f"fail:{host.lower()}"
        count = int(self._items.get(key, 0) or 0) + 1
        self._items[key] = count
        self._items[f"fail_at:{host.lower()}"] = time.monotonic()
        return count

    def reset_fail(self, host: str) -> None:
        self._items.pop(f"fail:{host.lower()}", None)
        self._items.pop(f"fail_at:{host.lower()}", None)

    def fail_count(self, host: str) -> int:
        return int(self._items.get(f"fail:{host.lower()}", 0) or 0)

    def mark_notified(self, key: str, ttl_s: float = 600.0) -> bool:
        """Return True if this is a fresh notify (not within TTL)."""
        stamp_key = f"notify:{key}"
        now = time.monotonic()
        until = float(self._items.get(stamp_key, 0.0) or 0.0)
        if until > now:
            return False
        self._items[stamp_key] = now + ttl_s
        return True

    def tuning_started_at(self) -> float:
        return float(self._items.get("tuning_started_at", 0.0) or 0.0)

    def set_tuning_started(self) -> None:
        self._items["tuning_started_at"] = time.monotonic()

    def clear_tuning_started(self) -> None:
        self._items.pop("tuning_started_at", None)
        self._items.pop("long_tune_notified", None)

    def long_tune_notified(self) -> bool:
        return bool(self._items.get("long_tune_notified"))

    def set_long_tune_notified(self) -> None:
        self._items["long_tune_notified"] = True
