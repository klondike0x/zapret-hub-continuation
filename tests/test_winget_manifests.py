from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from scripts.generate_winget_manifests import PACKAGE_IDENTIFIER, generate_manifests


def test_generate_winget_manifests_selects_architecture_and_hash(tmp_path: Path) -> None:
    x64 = tmp_path / "zapret_hub_3.0.0_portable_win_x64.zip"
    arm64 = tmp_path / "zapret_hub_3.0.0_portable_win_arm64.zip"
    x64.write_bytes(b"x64 portable")
    arm64.write_bytes(b"arm64 portable")

    output = tmp_path / "winget"
    generated = generate_manifests(
        version="3.0.0",
        x64_archive=x64,
        arm64_archive=arm64,
        output_dir=output,
        release_base_url="https://github.com/goshkow/Zapret-Hub/releases/download/v3.0.0",
    )

    assert len(generated) == 4
    installer = yaml.safe_load((output / f"{PACKAGE_IDENTIFIER}.installer.yaml").read_text(encoding="utf-8"))
    installers = {item["Architecture"]: item for item in installer["Installers"]}
    assert set(installers) == {"x64", "arm64"}
    assert installers["x64"]["InstallerSha256"] == hashlib.sha256(x64.read_bytes()).hexdigest().upper()
    assert installers["arm64"]["InstallerSha256"] == hashlib.sha256(arm64.read_bytes()).hexdigest().upper()
    assert installer["InstallerType"] == "zip"
    assert installer["NestedInstallerType"] == "portable"
    assert installer["NestedInstallerFiles"][0]["RelativeFilePath"] == r"zapret_hub\Zapret_Hub.exe"
