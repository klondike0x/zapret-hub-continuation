from __future__ import annotations

from pathlib import Path


CURRENT_ONBOARDING_VERSION = 4
LEGACY_ONBOARDING_VERSIONS = (1, 2, 3)


def onboarding_marker(data_dir: Path, version: int = CURRENT_ONBOARDING_VERSION) -> Path:
    return data_dir / f".services_onboarding_seen_v{version}"


def onboarding_completed(data_dir: Path) -> bool:
    return onboarding_marker(data_dir).exists()


def onboarding_is_update(data_dir: Path) -> bool:
    if onboarding_completed(data_dir):
        return False
    return any(onboarding_marker(data_dir, version).exists() for version in LEGACY_ONBOARDING_VERSIONS)
