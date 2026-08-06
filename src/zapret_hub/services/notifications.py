from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime
from typing import Any

from zapret_hub.domain import NotificationEntry
from zapret_hub.services.storage import StorageManager


class NotificationManager:
    def __init__(self, storage: StorageManager, *, limit: int = 160) -> None:
        self.storage = storage
        self.limit = max(20, int(limit or 160))
        self._path = self.storage.paths.data_dir / "notifications.json"
        if not self._path.exists():
            self.storage.write_json(self._path, [])

    def list(self) -> list[NotificationEntry]:
        raw = self.storage.read_json(self._path, default=[]) or []
        if not isinstance(raw, list):
            return []
        entries: list[NotificationEntry] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                entries.append(NotificationEntry(**item))
            except Exception:
                continue
        return entries

    def unread_count(self) -> int:
        return sum(1 for item in self.list() if not item.read)

    @staticmethod
    def _now_local_iso() -> str:
        return datetime.now().astimezone().isoformat()

    def add(
        self,
        level: str,
        title: str,
        message: str,
        *,
        source: str = "app",
        details: dict[str, Any] | None = None,
    ) -> NotificationEntry:
        entries = self.list()
        entry_details = dict(details or {})
        dedupe_key = str(entry_details.get("dedupe_key", "") or "").strip()
        if dedupe_key:
            for index, existing in enumerate(entries):
                if str(existing.details.get("dedupe_key", "") or "") != dedupe_key:
                    continue
                existing.level = (level or "info").strip().lower() or "info"
                existing.title = title.strip() or "Zapret Hub"
                existing.message = message.strip()
                existing.source = (source or "app").strip() or "app"
                existing.created_at = self._now_local_iso()
                existing.read = False
                existing.details.update(entry_details)
                entries[index] = existing
                self.storage.write_json(self._path, [asdict(item) for item in entries[-self.limit :]])
                return existing
        entry = NotificationEntry(
            id=uuid.uuid4().hex,
            level=(level or "info").strip().lower() or "info",
            title=title.strip() or "Zapret Hub",
            message=message.strip(),
            source=(source or "app").strip() or "app",
            created_at=self._now_local_iso(),
            read=False,
            details=entry_details,
        )
        entries.append(entry)
        entries = entries[-self.limit :]
        self.storage.write_json(self._path, [asdict(item) for item in entries])
        return entry

    def mark_all_read(self) -> None:
        entries = self.list()
        changed = False
        for item in entries:
            if not item.read:
                item.read = True
                changed = True
        if changed:
            self.storage.write_json(self._path, [asdict(item) for item in entries])

    def dismiss(self, notification_id: str) -> None:
        entries = [item for item in self.list() if item.id != notification_id]
        self.storage.write_json(self._path, [asdict(item) for item in entries])
