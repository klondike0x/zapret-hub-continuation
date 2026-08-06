from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import os
import shutil
import sys
from typing import Any

from zapret_hub import __version__
from zapret_hub.domain import AppPaths
from zapret_hub.runtime_env import development_install_root, is_packaged_runtime, packaged_install_root, packaged_resource_root
from zapret_hub.services.autostart import AutostartManager
from zapret_hub.services.components import ProcessManager
from zapret_hub.services.diagnostics import DiagnosticsManager
from zapret_hub.services.files import FilesManager
from zapret_hub.services.logging_service import LoggingManager
from zapret_hub.services.merge import MergeEngine
from zapret_hub.services.mods import ModsManager
from zapret_hub.services.zapret2_mods import Zapret2ModsManager
from zapret_hub.services.notifications import NotificationManager
from zapret_hub.services.orchestrator import OrchestratorEngine, knowledge_dir
from zapret_hub.services.orchestrator.knowledge import KnowledgeStore
from zapret_hub.services.profiles import ProfilesManager
from zapret_hub.services.settings import SettingsManager
from zapret_hub.services.storage import StorageManager
from zapret_hub.services.updates import UpdatesManager

@dataclass(slots=True)
class ApplicationContext:
    paths: AppPaths
    storage: StorageManager
    settings: SettingsManager
    logging: LoggingManager
    autostart: AutostartManager
    processes: ProcessManager
    mods: ModsManager
    mods2: Zapret2ModsManager
    notifications: NotificationManager
    merge: MergeEngine
    diagnostics: DiagnosticsManager
    updates: UpdatesManager
    profiles: ProfilesManager
    files: FilesManager
    orchestrator: OrchestratorEngine
    knowledge: KnowledgeStore
    backend: Any | None = None


def bootstrap_application() -> ApplicationContext:
    if is_packaged_runtime():
        install_root = packaged_install_root()
        resource_root = packaged_resource_root()
    else:
        install_root = development_install_root(__file__)
        resource_root = install_root

    work_root = _resolve_work_root(install_root)
    runtime_dir = work_root / "runtime"
    ui_assets_dir = install_root / "ui_assets"
    sample_data_dir = install_root / "sample_data"
    _hydrate_bundled_assets(
        resource_root=resource_root,
        install_root=install_root,
        work_root=work_root,
        runtime_dir=runtime_dir,
        ui_assets_dir=ui_assets_dir,
        sample_data_dir=sample_data_dir,
    )

    paths = AppPaths(
        install_root=install_root,
        core_dir=install_root / "core",
        runtime_dir=runtime_dir,
        configs_dir=work_root / "configs",
        default_packs_dir=install_root / "default_packs",
        mods_dir=work_root / "mods",
        mods_zapret2_dir=work_root / "mods_zapret2",
        merged_runtime_dir=work_root / "merged_runtime",
        backups_dir=work_root / "backups",
        cache_dir=work_root / "cache",
        logs_dir=work_root / "logs",
        data_dir=work_root / "data",
        ui_assets_dir=ui_assets_dir,
    )
    storage = StorageManager(paths)
    storage.ensure_layout()
    _ensure_windows_apps_registration(install_root)

    settings = SettingsManager(storage)
    logging = LoggingManager(storage)
    autostart = AutostartManager(logging)
    processes = ProcessManager(storage, logging, settings)
    try:
        processes.ensure_pinned_zapret_runtime()
    except Exception as error:
        logging.log("warning", "Pinned Zapret runtime ensure failed", error=str(error))
    notifications = NotificationManager(storage)
    merge = MergeEngine(storage, logging, settings)
    mods = ModsManager(storage, logging, merge, settings, processes=processes)
    mods2 = Zapret2ModsManager(storage, logging, settings)
    diagnostics = DiagnosticsManager(storage, logging, processes, mods, merge)
    updates = UpdatesManager(storage, logging, processes=processes, settings=settings)
    profiles = ProfilesManager(storage)
    files = FilesManager(storage, settings)
    knowledge = KnowledgeStore(knowledge_dir(paths.data_dir))
    orchestrator = OrchestratorEngine(
        language=lambda: str(settings.get().language or "ru"),
    )
    _prime_first_run_state(settings, processes)

    context = ApplicationContext(
        paths=paths,
        storage=storage,
        settings=settings,
        logging=logging,
        autostart=autostart,
        processes=processes,
        mods=mods,
        mods2=mods2,
        notifications=notifications,
        merge=merge,
        diagnostics=diagnostics,
        updates=updates,
        profiles=profiles,
        files=files,
        orchestrator=orchestrator,
        knowledge=knowledge,
        backend=None,
    )
    orchestrator.attach(context)
    # Post-update / every-start: undo old Auto pollution in battle lists so Discord
    # etc. work out of the box in Manual; Auto overlay stays separate.
    try:
        from zapret_hub.services.orchestrator.auto_overlay import ensure_auto_integrity

        report = ensure_auto_integrity(paths.configs_dir, work_root=work_root)
        try:
            logging.log("info", "Auto integrity repair on startup", **{k: report.get(k) for k in report})
        except Exception:
            pass
    except Exception as error:
        try:
            logging.log("warning", "Auto integrity repair failed", error=str(error))
        except Exception:
            pass
    current = settings.get()
    backend = "zapret2" if str(current.selected_runtime_mode or "") == "zapret2" else "zapret"
    mode = str((current.zapret2_control_mode if backend == "zapret2" else current.zapret_control_mode) or "manual")
    orchestrator.set_mode(mode, backend=backend)
    return context


def build_startup_snapshot(context: ApplicationContext) -> dict[str, Any]:
    current = context.settings.get()
    general_options = list(context.processes.list_zapret_generals())
    if not str(current.selected_zapret_general or "").strip() and general_options:
        context.settings.update(selected_zapret_general=str(general_options[0]["id"]))
        current = context.settings.get()
    return {
        "components": [asdict(item) for item in context.processes.list_components()],
        "states": [asdict(item) for item in context.processes.list_states()],
        "settings": {
            "selected_zapret_general": current.selected_zapret_general,
            "favorite_zapret_generals": list(current.favorite_zapret_generals or []),
            "enabled_mod_ids": list(current.enabled_mod_ids or []),
            "enabled_zapret2_mod_ids": list(getattr(current, "enabled_zapret2_mod_ids", None) or []),
            "selected_runtime_mode": getattr(current, "selected_runtime_mode", "zapret"),
        },
        "general_options": general_options,
    }


def _prime_first_run_state(settings: SettingsManager, processes: ProcessManager) -> None:
    current = settings.get()
    changes: dict[str, Any] = {}
    if str(current.zapret_ipset_mode or "").strip() not in {"loaded", "none", "any"}:
        changes["zapret_ipset_mode"] = "loaded"
    if str(current.zapret_game_filter_mode or "").strip() not in {"disabled", "tcp", "udp", "tcpudp"}:
        changes["zapret_game_filter_mode"] = "disabled"
    if str(getattr(current, "zapret_gaming_set", "") or "").strip() not in {
        "base",
        "base-wide-stun",
        "wide-stun-base",
        "stun-wide-base",
        "stun-wide-base-local-exclude",
        "udp-first",
        "tcp-first",
        "stun-between",
    }:
        changes["zapret_gaming_set"] = "stun-wide-base"
    if changes:
        settings.update(**changes)


def _hydrate_bundled_assets(
    resource_root: Path,
    install_root: Path,
    work_root: Path,
    runtime_dir: Path,
    ui_assets_dir: Path,
    sample_data_dir: Path,
) -> None:
    bundled_runtime = resource_root / "runtime"
    bundled_ui_assets = resource_root / "ui_assets"
    bundled_sample_data = resource_root / "sample_data"

    # Program Files is not a writable runtime location. Keep generated configs,
    # merged Zapret trees and downloaded helper cores under LocalAppData instead.
    # Existing installations are migrated once without deleting the old copy.
    legacy_runtime = install_root / "runtime"
    if not runtime_dir.exists():
        source_runtime = legacy_runtime if legacy_runtime.exists() else bundled_runtime
        if source_runtime.exists():
            shutil.copytree(source_runtime, runtime_dir, dirs_exist_ok=True)

    for name in ("data", "configs", "mods", "mods_zapret2", "cache", "logs", "backups"):
        source = install_root / name
        destination = work_root / name
        if source.exists() and not destination.exists():
            shutil.copytree(source, destination, dirs_exist_ok=True)

    if bundled_ui_assets.exists() and not ui_assets_dir.exists():
        shutil.copytree(bundled_ui_assets, ui_assets_dir, dirs_exist_ok=True)

    if bundled_sample_data.exists() and not sample_data_dir.exists():
        shutil.copytree(bundled_sample_data, sample_data_dir, dirs_exist_ok=True)


def _ensure_windows_apps_registration(install_root: Path) -> None:
    """Register portable/installed builds in Windows Settings → Apps when an uninstaller is present."""
    if not sys.platform.startswith("win") or not is_packaged_runtime():
        return
    uninstaller = install_root / "uninstall_zaprethub.exe"
    if not uninstaller.exists():
        return
    app_exe = None
    for name in ("Zapret_Hub.exe", "zapret_hub.exe"):
        candidate = install_root / name
        if candidate.exists():
            app_exe = candidate
            break
    if app_exe is None:
        return
    try:
        import winreg
    except ImportError:
        return
    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ZapretHub"
    uninstall_cmd = f'"{uninstaller}" --install-dir "{install_root}"'
    version_parts = str(__version__).split(".")
    try:
        major = int(version_parts[0]) if version_parts else 0
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0
    except ValueError:
        major, minor = 0, 0
    values: dict[str, object] = {
        "DisplayName": "Zapret Hub",
        "DisplayVersion": str(__version__),
        "Publisher": "zapret-hub-continuation",
        "InstallLocation": str(install_root),
        "DisplayIcon": str(app_exe),
        "UninstallString": uninstall_cmd,
        "QuietUninstallString": f'{uninstall_cmd} --silent',
        "InstallDate": datetime.now().strftime("%Y%m%d"),
        "URLInfoAbout": "https://github.com/klondike0x/zapret-hub-continuation",
        "HelpLink": "https://github.com/klondike0x/zapret-hub-continuation",
        "NoModify": 1,
        "NoRepair": 1,
        "VersionMajor": major,
        "VersionMinor": minor,
    }
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            access = winreg.KEY_WRITE
            if root == winreg.HKEY_LOCAL_MACHINE:
                access |= winreg.KEY_WOW64_64KEY
            with winreg.CreateKeyEx(root, uninstall_key, 0, access) as key:
                for name, value in values.items():
                    if isinstance(value, int):
                        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                    else:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
            return
        except Exception:
            continue


def _resolve_work_root(install_root: Path) -> Path:
    """Return a writable per-user state directory for installed builds."""
    explicit = str(os.environ.get("ZAPRET_HUB_WORK_ROOT", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    if (install_root / "portable.flag").exists():
        return install_root / "user_data"
    if not is_packaged_runtime():
        return install_root
    local_app_data = os.environ.get("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    target = base / "Zapret_Hub"
    # Prefer a single folder name; migrate older LocalAppData locations once.
    if not target.exists():
        for legacy_name in ("Zapret Hub", "ZapretHub"):
            legacy = base / legacy_name
            if not legacy.exists() or not legacy.is_dir():
                continue
            try:
                legacy.rename(target)
                break
            except Exception:
                try:
                    shutil.copytree(legacy, target, dirs_exist_ok=True)
                    break
                except Exception:
                    continue
    return target
