from __future__ import annotations

import pytest

from zapret_hub.services.goshkow_vpn import GoshkowVpnManager


def _manager() -> GoshkowVpnManager:
    return object.__new__(GoshkowVpnManager)


def test_subscription_uses_com_domain() -> None:
    url = "https://vpn.goshkow.com/sub/example-key#fragment"

    assert _manager()._normalize_subscription_url(url) == "https://vpn.goshkow.com/sub/example-key"


def test_legacy_subscription_is_migrated_to_com_domain() -> None:
    url = "https://vpn.goshkow.ru/sub/example-key"

    assert _manager()._normalize_subscription_url(url) == "https://vpn.goshkow.com/sub/example-key"


def test_foreign_subscription_domain_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"vpn\.goshkow\.com"):
        _manager()._normalize_subscription_url("https://example.com/sub/example-key")
