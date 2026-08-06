from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from zapret_hub.services.components import ProcessManager, PINNED_ZAPRET_VERSION


def test_zapret_releases_use_cache_when_api_rate_limited(tmp_path: Path) -> None:
    process = ProcessManager.__new__(ProcessManager)
    process.logging = SimpleNamespace(log=lambda *_a, **_k: None)
    process.storage = SimpleNamespace(
        paths=SimpleNamespace(cache_dir=tmp_path),
        read_json=lambda path, default=None: __import__("json").loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default,
        write_json=lambda path, payload: Path(path).write_text(__import__("json").dumps(payload), encoding="utf-8"),
    )
    process._component_releases_mem = {}
    cached = [
        {"version": "1.9.9c", "tag": "1.9.9c", "asset_url": "u1", "asset_name": "a1", "zipball_url": "z1", "published_at": "", "prerelease": "0", "recommended": "0"},
        {"version": PINNED_ZAPRET_VERSION, "tag": PINNED_ZAPRET_VERSION, "asset_url": "u2", "asset_name": "a2", "zipball_url": "z2", "published_at": "", "prerelease": "0", "recommended": "1"},
        {"version": "1.8.5", "tag": "1.8.5", "asset_url": "u3", "asset_name": "a3", "zipball_url": "z3", "published_at": "", "prerelease": "0", "recommended": "0"},
    ]
    process._save_component_releases_cache("zapret", cached)

    class Boom:
        def github_json(self, *_a, **_k):
            raise RuntimeError("GitHub API rate limit exceeded. Try again in about 9 min.")

        def github_bytes(self, *_a, **_k):
            raise RuntimeError("should not hit atom when cache exists")

    process.github = Boom()
    releases = process.list_zapret_releases(limit=30)
    assert len(releases) >= 3
    assert {item["version"] for item in releases} >= {"1.9.9c", PINNED_ZAPRET_VERSION, "1.8.5"}


def test_recent_source_log_error_skips_windivert_success(tmp_path: Path) -> None:
    process = ProcessManager.__new__(ProcessManager)
    log_path = tmp_path / "zapret.log"
    log_path.write_text(
        "\n".join(
            [
                "windivert initialized. capture is started.",
                "A copy of winws is already running with the same filter",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    process.logging = SimpleNamespace(source_log_path=lambda _source: str(log_path))
    assert "already running" in process._recent_source_log_error("zapret").lower()
    log_path.write_text("windivert initialized. capture is started.\n", encoding="utf-8")
    assert process._recent_source_log_error("zapret") == ""
