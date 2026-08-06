from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_prepare_release_arguments_are_separate_powershell_array_entries() -> None:
    script = (ROOT / "scripts" / "build_nuitka_installer.ps1").read_text(encoding="utf-8")

    assert '$Version,\n        "--skip-installer-payload-zips"' in script


def test_uninstaller_packages_only_its_required_icons() -> None:
    script = (ROOT / "scripts" / "build_nuitka_installer.ps1").read_text(encoding="utf-8")
    uninstaller_section = script.split("function Build-Uninstaller", 1)[1].split("$installerDataFiles", 1)[0]

    assert '"--include-data-dir=ui_assets=ui_assets"' not in uninstaller_section
    assert "installer_runtime_icon.png=ui_assets\\icons\\installer_runtime_icon.png" in uninstaller_section
    assert "app.png=ui_assets\\icons\\app.png" in uninstaller_section
    assert "app.ico=ui_assets\\icons\\app.ico" in uninstaller_section


def test_installer_build_uses_onefile_without_inno_wrapper() -> None:
    script = (ROOT / "scripts" / "build_nuitka_installer.ps1").read_text(encoding="utf-8")

    assert '"--onefile"' in script
    assert "--onefile-cache-mode=cached" in script
    assert "Find-ISCC" not in script
    assert "zapret_hub_installer.iss" not in script
