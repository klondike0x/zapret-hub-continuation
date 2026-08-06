from zapret_hub.services.deeplink import parse_zaprethub_url


def test_install_alias():
    assert parse_zaprethub_url("zaprethub://install/foo") == {
        "action": "install",
        "slug": "foo",
        "version_id": "",
    }


def test_marketplace_links_are_no_longer_actionable():
    # Marketplace deep links were removed together with the component.
    assert parse_zaprethub_url("zaprethub://marketplace/install/youtube-flow") is None
    assert parse_zaprethub_url("zaprethub://marketplace/install?slug=yt&version_id=12") is None
    assert parse_zaprethub_url("zaprethub://marketplace/project/discord-bridge") is None


def test_unknown_scheme_is_ignored():
    assert parse_zaprethub_url("https://example.com/install/foo") is None
    assert parse_zaprethub_url("") is None
