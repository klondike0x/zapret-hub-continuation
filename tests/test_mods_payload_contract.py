"""Mods payload contract: every field the web_ui renders must be present."""
from __future__ import annotations

import types

import pytest


def _mod_item(mod_id: str, *, source_url: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=mod_id,
        name=f"Mod {mod_id}",
        author="tester",
        description="desc",
        version="1.0",
        enabled=True,
        source_url=source_url,
        disk_size=0,
    )


class _FakeModsManager:
    def __init__(self, items):
        self._items = items

    def list_installed(self):
        return list(self._items)


class _FakeSettings:
    def get(self):
        return types.SimpleNamespace(
            enabled_mod_ids=["m1"],
            enabled_zapret2_mod_ids=["m2"],
        )


class _FakeContext:
    def __init__(self):
        self.mods = _FakeModsManager([_mod_item("m1", source_url="https://github.com/x/y")])
        self.mods2 = _FakeModsManager([_mod_item("m2")])
        self.settings = _FakeSettings()


@pytest.fixture()
def bridge():
    from zapret_hub.ui.web_window import WebBridge

    bridge = WebBridge.__new__(WebBridge)
    bridge.context = _FakeContext()
    return bridge


@pytest.mark.parametrize("runtime", ["zapret", "zapret2"])
def test_installed_mods_payload_has_all_ui_fields(bridge, runtime: str) -> None:
    payload = bridge._installed_mods_payload(runtime)
    assert payload, f"expected at least one mod for {runtime}"
    entry = payload[0]
    required = {
        "id",
        "name",
        "author",
        "description",
        "createdAt",
        "iconUrl",
        "sourceUrl",
        "version",
        "enabled",
        "diskSize",
        "compatibility",
        "compatibleFiles",
        "source",
        "runtime",
    }
    missing = sorted(required - set(entry))
    assert not missing, f"missing fields in {runtime} payload: {missing}"
    assert isinstance(entry["compatibleFiles"], list), "compatibleFiles must be a list (web_ui calls .map)"
    if runtime == "zapret":
        assert entry["source"] == "github", "zapret mod from GitHub should be marked source=github"
    else:
        assert entry["runtime"] == "zapret2"
