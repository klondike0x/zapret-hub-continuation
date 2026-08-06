from __future__ import annotations

from zapret_hub.domain import ConfigProfile
from zapret_hub.services.storage import StorageManager


class ProfilesManager:
    def __init__(self, storage: StorageManager) -> None:
        self.storage = storage
        self._profiles_path = self.storage.paths.data_dir / "profiles.json"

    def list_profiles(self) -> list[ConfigProfile]:
        raw = self.storage.read_json(self._profiles_path, default=[]) or []
        return [ConfigProfile(**item) for item in raw]
