from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from zapret_hub.services.onboarding_state import onboarding_completed, onboarding_is_update, onboarding_marker
from zapret_hub.services.settings import SettingsManager


class _Storage:
    def __init__(self, data_dir: Path) -> None:
        self.paths = SimpleNamespace(data_dir=data_dir)

    def read_json(self, path: Path, default=None):
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("legacy_version", [1, 2, 3])
def test_legacy_onboarding_marker_is_an_update(tmp_path: Path, legacy_version: int) -> None:
    onboarding_marker(tmp_path, legacy_version).write_text("1", encoding="utf-8")

    assert onboarding_is_update(tmp_path)
    assert not onboarding_completed(tmp_path)


def test_current_onboarding_marker_is_not_an_update(tmp_path: Path) -> None:
    onboarding_marker(tmp_path, 2).write_text("1", encoding="utf-8")
    onboarding_marker(tmp_path).write_text("1", encoding="utf-8")

    assert onboarding_completed(tmp_path)
    assert not onboarding_is_update(tmp_path)


@pytest.mark.parametrize(("system_theme", "expected"), [("dark", "night"), ("light", "light")])
def test_legacy_theme_is_replaced_from_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    system_theme: str,
    expected: str,
) -> None:
    storage = _Storage(tmp_path)
    storage.write_json(tmp_path / "settings.json", {"theme": "oled", "component_selection_initialized": True})
    monkeypatch.setattr(SettingsManager, "_detect_system_theme", lambda _self: system_theme)

    assert SettingsManager(storage).get().theme == expected


def test_current_theme_choice_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _Storage(tmp_path)
    storage.write_json(tmp_path / "settings.json", {"theme": "oled", "component_selection_initialized": True})
    (tmp_path / ".theme_defaults_v4").write_text("1", encoding="utf-8")
    monkeypatch.setattr(SettingsManager, "_detect_system_theme", lambda _self: "dark")

    assert SettingsManager(storage).get().theme == "oled"


def test_new_client_defaults_youtube_discord_and_tg_proxy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _Storage(tmp_path)
    storage.write_json(
        tmp_path / "components.json",
        [
            {"id": "zapret", "enabled": True, "autostart": False},
            {"id": "tg-ws-proxy", "enabled": True, "autostart": True},
        ],
    )
    monkeypatch.setattr(SettingsManager, "_detect_system_theme", lambda _self: "dark")
    monkeypatch.setattr(SettingsManager, "_detect_system_language", lambda _self: "ru")

    settings = SettingsManager(storage).get()
    assert "tg-ws-proxy" in settings.enabled_component_ids
    assert "youtube" in settings.selected_service_ids
    assert "discord" in settings.selected_service_ids
