from __future__ import annotations

from zapret_hub.services.discord_presence import (
    STATUS_FLAVORS_EN,
    STATUS_FLAVORS_RU,
    PresenceSnapshot,
    build_activity,
    format_uptime,
    pick_status_flavor,
)


def test_status_flavor_pools() -> None:
    assert len(STATUS_FLAVORS_RU) >= 15
    assert len(STATUS_FLAVORS_EN) == len(STATUS_FLAVORS_RU)


def test_pick_status_flavor_uses_rng() -> None:
    import random

    rng = random.Random(7)
    first = pick_status_flavor(language="ru", rng=rng)
    rng = random.Random(7)
    second = pick_status_flavor(language="ru", rng=rng)
    assert first == second
    assert first in STATUS_FLAVORS_RU


def test_format_uptime() -> None:
    assert format_uptime(100, ru=True, now=100) == "только запущен"
    assert format_uptime(100, ru=False, now=160) == "1m"
    assert format_uptime(100, ru=True, now=100 + 3700) == "1ч 1м"


def test_build_activity_idle_uses_flavor() -> None:
    flavor = STATUS_FLAVORS_RU[0]
    activity = build_activity(
        PresenceSnapshot(
            enabled=True,
            powered=False,
            runtime_mode="zapret",
            control_mode="manual",
            general_name="general.bat",
            strategy_id="balanced",
            language="ru",
            version="3.0.1",
        ),
        started_at=1_700_000_000,
        flavor=flavor,
        now=1_700_000_000,
    )
    assert activity["details"] == flavor
    assert "паузе" in activity["state"]
    assert activity["assets"]["small_image"] == "idle"


def test_build_activity_zapret1_manual() -> None:
    flavor = STATUS_FLAVORS_EN[3]
    activity = build_activity(
        PresenceSnapshot(
            enabled=True,
            powered=True,
            runtime_mode="zapret",
            control_mode="manual",
            general_name="general (ALT12).bat",
            strategy_id="balanced",
            language="en",
            version="3.0.1",
        ),
        started_at=1_700_000_001,
        flavor=flavor,
        now=1_700_000_001 + 120,
    )
    assert activity["details"] == flavor
    assert "Zapret 1" in activity["state"]
    assert "general (ALT12)" in activity["state"]
    assert activity["assets"]["small_image"] == "zapret"


def test_build_activity_zapret2_auto() -> None:
    flavor = STATUS_FLAVORS_RU[5]
    activity = build_activity(
        PresenceSnapshot(
            enabled=True,
            powered=True,
            runtime_mode="zapret2",
            control_mode="auto",
            general_name="",
            strategy_id="aggressive",
            language="ru",
            version="3.0.1",
        ),
        started_at=1,
        flavor=flavor,
        now=1,
    )
    assert activity["details"] == flavor
    assert "Zapret 2" in activity["state"]
    assert "авто" in activity["state"]
    assert activity["assets"]["small_image"] == "zapret2"
