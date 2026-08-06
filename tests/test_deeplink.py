from zapret_hub.services.deeplink import parse_zaprethub_url


def test_install_path():
    assert parse_zaprethub_url("zaprethub://marketplace/install/youtube-flow") == {
        "action": "install",
        "slug": "youtube-flow",
        "version_id": "",
    }


def test_install_query():
    assert parse_zaprethub_url("zaprethub://marketplace/install?slug=yt&version_id=12") == {
        "action": "install",
        "slug": "yt",
        "version_id": "12",
    }


def test_project_open():
    assert parse_zaprethub_url("zaprethub://marketplace/project/discord-bridge") == {
        "action": "open",
        "slug": "discord-bridge",
        "version_id": "",
    }


def test_short_alias():
    assert parse_zaprethub_url("zaprethub://install/foo") == {
        "action": "install",
        "slug": "foo",
        "version_id": "",
    }
