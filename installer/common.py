from __future__ import annotations

import base64
import ctypes
import locale
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from installer.embedded_app_icon import APP_PNG_BASE64

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

if sys.platform.startswith("win"):
    import winreg


def _is_ru() -> bool:
    try:
        lang = (locale.getdefaultlocale()[0] or "").lower()  # type: ignore[call-arg]
    except Exception:
        lang = ""
    return lang.startswith("ru")


RU = _is_ru()
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ZapretHub"
INSTALLER_VERSION = "3.0.2"
INSTALLER_LOG_PATH = Path(tempfile.gettempdir()) / "zapret_hub_installer.log"
UNINSTALLER_LOG_PATH = Path(tempfile.gettempdir()) / "zapret_hub_uninstaller.log"


def tr(ru: str, en: str) -> str:
    return ru if RU else en


def _resource_candidates() -> list[Path]:
    candidates: list[Path] = []
    try:
        file_path = Path(__file__).resolve()
    except Exception:
        file_path = None
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir)
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass))
        if file_path is not None:
            candidates.append(file_path.parent)
            for parent in file_path.parents:
                candidates.append(parent)
    else:
        if file_path is not None:
            candidates.append(file_path.parents[1])
            candidates.append(file_path.parent)
            for parent in file_path.parents:
                candidates.append(parent)
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def resource_root() -> Path:
    for candidate in _resource_candidates():
        if (candidate / "ui_assets" / "icons" / "installer_runtime_icon.png").exists():
            return candidate
    for candidate in _resource_candidates():
        if (candidate / "ui_assets" / "icons" / "app.png").exists():
            return candidate
    for candidate in _resource_candidates():
        if (candidate / "ui_assets" / "icons" / "app.ico").exists():
            return candidate
    return _resource_candidates()[0]


def _log(path: Path, event: str, **context: object) -> None:
    try:
        timestamp = datetime.now().isoformat(timespec="seconds")
        details = ", ".join(f"{key}={context[key]!r}" for key in sorted(context))
        line = f"[{timestamp}] {event}"
        if details:
            line += f" | {details}"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except Exception:
        return


def installer_log(event: str, **context: object) -> None:
    _log(INSTALLER_LOG_PATH, event, **context)


def uninstaller_log(event: str, **context: object) -> None:
    _log(UNINSTALLER_LOG_PATH, event, **context)


def _embedded_app_pixmap() -> QPixmap:
    try:
        raw = base64.b64decode(APP_PNG_BASE64)
    except Exception:
        return QPixmap()
    image = QImage.fromData(raw, "PNG")
    if image.isNull():
        return QPixmap()
    return QPixmap.fromImage(image)


def app_icon() -> QIcon:
    embedded = _embedded_app_pixmap()
    if not embedded.isNull():
        return QIcon(embedded)
    installer_png_path = resource_root() / "ui_assets" / "icons" / "installer_runtime_icon.png"
    if installer_png_path.exists():
        image = QImage(str(installer_png_path))
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            if not pixmap.isNull():
                return QIcon(pixmap)
    png_path = resource_root() / "ui_assets" / "icons" / "app.png"
    if png_path.exists():
        image = QImage(str(png_path))
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            if not pixmap.isNull():
                return QIcon(pixmap)
    icon_path = resource_root() / "ui_assets" / "icons" / "app.ico"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    if getattr(sys, "frozen", False):
        icon = QIcon(str(Path(sys.executable)))
        if not icon.isNull():
            return icon
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor("#b49af1"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(QRectF(4, 4, 56, 56), 10, 10)
    painter.setPen(QPen(QColor("#120f1a"), 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(20, 44, 30, 24)
    painter.drawLine(30, 24, 44, 40)
    painter.end()
    return QIcon(pixmap)


def apply_native_window_icons(widget: QWidget) -> None:
    if not sys.platform.startswith("win"):
        return
    icon = app_icon()
    try:
        widget.setWindowIcon(icon)
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(icon)
    except Exception:
        pass


def set_windows_app_id(app_id: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)  # type: ignore[attr-defined]
    except Exception:
        return


def disable_native_window_rounding(hwnd: int) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        value = ctypes.c_int(DWMWCP_DONOTROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:
        return


def bring_widget_to_front(widget: QWidget) -> None:
    widget.raise_()
    widget.activateWindow()
    if not sys.platform.startswith("win"):
        return
    try:
        hwnd = int(widget.winId())
        SW_RESTORE = 9
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)  # type: ignore[attr-defined]
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)  # type: ignore[attr-defined]
        ctypes.windll.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)  # type: ignore[attr-defined]
        ctypes.windll.user32.SetForegroundWindow(hwnd)  # type: ignore[attr-defined]
    except Exception:
        return


def is_admin() -> bool:
    if not sys.platform.startswith("win"):
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def relaunch_with_elevation(args: list[str]) -> bool:
    if not sys.platform.startswith("win"):
        return True
    if not getattr(sys, "frozen", False):
        return False
    cmd = " ".join(f'"{arg}"' for arg in args)
    result = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "runas", sys.executable, cmd, None, 1
    )
    return int(result) > 32


def default_install_dir() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Zapret Hub"


def _normalized_path_text(path: Path) -> str:
    try:
        return str(path.resolve()).rstrip("\\/").lower()
    except Exception:
        return str(path).rstrip("\\/").lower()


def looks_like_zapret_hub_dir(path: Path) -> bool:
    if not path.exists():
        return False
    return any((path / name).exists() for name in ("zapret_hub.exe", "Zapret_Hub.exe", "uninstall_zaprethub.exe"))


def install_dir_from_registry() -> Path | None:
    if not sys.platform.startswith("win"):
        return None
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            access = winreg.KEY_READ
            if root == winreg.HKEY_LOCAL_MACHINE:
                access |= winreg.KEY_WOW64_64KEY
            with winreg.OpenKey(root, UNINSTALL_KEY, 0, access) as key:
                value, _ = winreg.QueryValueEx(key, "InstallLocation")
                path = Path(str(value))
                if path.exists():
                    return path
        except Exception:
            continue
    return None


def resolve_install_dir(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit
    from_registry = install_dir_from_registry()
    if from_registry is not None:
        return from_registry
    if getattr(sys, "frozen", False):
        portable = Path(sys.executable).resolve().parent
        if looks_like_zapret_hub_dir(portable):
            return portable
    return default_install_dir()


def _run_hidden(command: list[str]) -> None:
    startup = None
    flags = 0
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    subprocess.run(command, check=False, capture_output=True, creationflags=flags, startupinfo=startup)


def _run_hidden_script(script: str) -> None:
    """Run a short PowerShell snippet with default process policy (no policy override flags)."""
    startup = None
    flags = 0
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    # Avoid policy-override CLI flags that Defender ML often scores as suspicious.
    subprocess.run(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
        check=False,
        capture_output=True,
        creationflags=flags,
        startupinfo=startup,
    )


def _remove_autostart_entries() -> None:
    if not sys.platform.startswith("win"):
        return
    # Do not invoke Task Scheduler: current builds only use the standard Run key.
    names = ("ZapretHub", "Zapret Hub", "zapret_hub")
    for hive, access in (
        (winreg.HKEY_CURRENT_USER, winreg.KEY_SET_VALUE),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY),
    ):
        try:
            with winreg.OpenKey(
                hive,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                access,
            ) as key:
                for name in names:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        continue
                    except OSError:
                        continue
        except OSError:
            continue


def _process_path_under_root(executable_path: str, root: Path) -> bool:
    if not executable_path:
        return False
    try:
        exe = Path(executable_path).resolve()
        root_resolved = root.resolve()
        exe.relative_to(root_resolved)
        return True
    except Exception:
        try:
            exe_text = str(Path(executable_path)).rstrip("\\/").casefold()
            root_text = str(root).rstrip("\\/").casefold()
            return exe_text == root_text or exe_text.startswith(root_text + "\\")
        except Exception:
            return False


def terminate_running_instances(install_dir: Path | None = None) -> None:
    """Stop only processes whose executable lives under the target install directory.

    Never kill Zapret_Hub.exe (or helpers) by image name alone — a portable copy
    in another folder must stay running.
    """
    if not sys.platform.startswith("win"):
        return
    if install_dir is None:
        return
    try:
        target_root = install_dir.resolve()
    except Exception:
        target_root = install_dir
    if not str(target_root).strip():
        return

    _remove_autostart_entries()
    # Service name is shared by Zapret Hub installs; only touch it when we have a real target.
    _run_hidden(["sc", "stop", "zapret"])
    _run_hidden(["sc", "delete", "zapret"])

    root_literal = str(target_root).replace("'", "''")
    current_pid = os.getpid()
    ps = f"""
$root = '{root_literal}'
try {{ $rootFull = [System.IO.Path]::GetFullPath($root).TrimEnd('\\') }} catch {{ $rootFull = $root.TrimEnd('\\') }}
$rootPrefix = $rootFull + '\\'
$selfPid = {current_pid}
Get-CimInstance Win32_Process | ForEach-Object {{
  if ($_.ProcessId -eq $selfPid) {{ return }}
  $exe = $null
  try {{ $exe = [string]$_.ExecutablePath }} catch {{ $exe = $null }}
  if ([string]::IsNullOrWhiteSpace($exe)) {{ return }}
  try {{ $full = [System.IO.Path]::GetFullPath($exe) }} catch {{ return }}
  $under = $false
  if ($full.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {{ $under = $true }}
  elseif ($full.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {{ $under = $true }}
  if (-not $under) {{ return }}
  try {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }} catch {{}}
}}
"""
    _run_hidden_script(ps)
    time.sleep(0.35)


def remove_shortcuts() -> None:
    shortcut_paths = [
        Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "Zapret Hub.lnk",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop" / "Zapret Hub.lnk",
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Zapret Hub.lnk",
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs\Zapret Hub.lnk",
    ]
    for path in shortcut_paths:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            continue


def _clear_path_attributes(path: Path) -> None:
    if not sys.platform.startswith("win") or not path.exists():
        return
    if path.is_dir():
        _run_hidden(["cmd", "/c", f'attrib -r -s -h "{path}" /s /d'])
    else:
        _run_hidden(["attrib", "-r", "-s", "-h", str(path)])


def _schedule_delete_on_reboot(path: Path) -> None:
    if not sys.platform.startswith("win") or not path.exists():
        return
    try:
        MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
        ctypes.windll.kernel32.MoveFileExW(str(path), None, MOVEFILE_DELAY_UNTIL_REBOOT)  # type: ignore[attr-defined]
    except Exception:
        return


def quarantine_item(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        quarantine_root = Path(tempfile.gettempdir()) / "zapret_hub_cleanup"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        target = quarantine_root / f"{path.name}_{int(time.time() * 1000)}"
        shutil.move(str(path), str(target))
        try:
            _clear_path_attributes(target)
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink(missing_ok=True)
        finally:
            if target.exists():
                _schedule_delete_on_reboot(target)
        return not path.exists()
    except Exception:
        return False


def safe_remove_item(path: Path, install_dir: Path | None = None) -> None:
    for _ in range(6):
        try:
            if not path.exists():
                return
            _clear_path_attributes(path)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=False)
            else:
                path.unlink()
            return
        except PermissionError:
            terminate_running_instances(install_dir or path.parent)
            time.sleep(0.45)
        except Exception:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                return
            raise
    if path.exists():
        raise PermissionError(f"cannot replace: {path}")


def wipe_install_dir(install_dir: Path) -> None:
    if not install_dir.exists():
        return
    ignored_leftovers = {"merged_runtime", "backups", "logs"}
    for _ in range(6):
        terminate_running_instances(install_dir)
        for item in list(install_dir.iterdir()):
            try:
                safe_remove_item(item, install_dir)
            except Exception:
                if item.name in ignored_leftovers:
                    if quarantine_item(item):
                        continue
                    continue
                if quarantine_item(item):
                    continue
                raise
        if not any(install_dir.iterdir()):
            return
        time.sleep(0.5)
    remaining = next((item for item in install_dir.iterdir() if item.name not in ignored_leftovers), None)
    if remaining is None:
        return
    raise PermissionError(f"cannot replace: {remaining}")


def user_data_dirs(install_dir: Path | None = None) -> list[Path]:
    roots: list[Path] = []
    explicit = str(os.environ.get("ZAPRET_HUB_WORK_ROOT", "") or "").strip()
    if explicit:
        roots.append(Path(explicit).expanduser())
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    for name in ("Zapret_Hub", "Zapret Hub", "ZapretHub"):
        roots.append(local_app_data / name)
    roaming = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    for name in ("Zapret_Hub", "Zapret Hub", "ZapretHub"):
        roots.append(roaming / name)
    if install_dir is not None:
        for name in ("user_data", "data", "configs", "mods", "mods_zapret2", "cache", "logs", "backups", "merged_runtime"):
            roots.append(install_dir / name)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in roots:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def remove_app_data(install_dir: Path | None = None) -> None:
    for path in user_data_dirs(install_dir):
        if not path.exists():
            continue
        try:
            safe_remove_item(path, install_dir)
        except Exception:
            quarantine_item(path)


def remove_uninstall_registry() -> None:
    if not sys.platform.startswith("win"):
        return
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            access = winreg.KEY_WRITE
            if root == winreg.HKEY_LOCAL_MACHINE:
                access |= winreg.KEY_WOW64_64KEY
            winreg.DeleteKeyEx(root, UNINSTALL_KEY, access=access, reserved=0)
        except Exception:
            continue


def launch_folder_removal(install_dir: Path) -> None:
    """Delete the installation directory after the uninstaller exits."""
    script_path = Path(tempfile.gettempdir()) / f"zapret_hub_uninstall_{int(time.time() * 1000)}.cmd"
    target = str(install_dir)
    script = "\r\n".join(
        [
            "@echo off",
            "setlocal",
            f'set "TARGET={target}"',
            "for /L %%i in (1,1,40) do (",
            '  if not exist "%TARGET%" goto done',
            '  rmdir /s /q "%TARGET%" >nul 2>&1',
            '  if not exist "%TARGET%" goto done',
            "  ping -n 2 127.0.0.1 >nul",
            ")",
            ":done",
            f'del /f /q "{script_path}" >nul 2>&1',
        ]
    )
    script_path.write_text(script, encoding="utf-8", errors="replace")
    startup = None
    flags = 0
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
    subprocess.Popen(
        ["cmd.exe", "/c", str(script_path)],
        creationflags=flags,
        startupinfo=startup,
    )


def estimate_install_size_kb(install_dir: Path) -> int:
    total = 0
    try:
        for item in install_dir.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                except OSError:
                    continue
    except Exception:
        return 0
    return max(1, total // 1024)


def write_uninstall_registry(install_dir: Path, uninstaller_exe: Path, app_exe: Path) -> None:
    if not sys.platform.startswith("win"):
        return
    uninstall_cmd = f'"{uninstaller_exe}" --install-dir "{install_dir}"'
    version_parts = INSTALLER_VERSION.split(".")
    try:
        major = int(version_parts[0]) if version_parts else 0
        minor = int(version_parts[1]) if len(version_parts) > 1 else 0
    except ValueError:
        major, minor = 0, 0
    values: dict[str, object] = {
        "DisplayName": "Zapret Hub",
        "DisplayVersion": INSTALLER_VERSION,
        "Publisher": "zapret-hub-continuation",
        "InstallLocation": str(install_dir),
        "DisplayIcon": str(app_exe if app_exe.exists() else uninstaller_exe),
        "UninstallString": uninstall_cmd,
        "QuietUninstallString": f'{uninstall_cmd} --silent',
        "InstallDate": datetime.now().strftime("%Y%m%d"),
        "URLInfoAbout": "https://github.com/klondike0x/zapret-hub-continuation",
        "HelpLink": "https://github.com/klondike0x/zapret-hub-continuation",
        "NoModify": 1,
        "NoRepair": 1,
        "VersionMajor": major,
        "VersionMinor": minor,
        "EstimatedSize": estimate_install_size_kb(install_dir),
    }
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            access = winreg.KEY_WRITE
            if root == winreg.HKEY_LOCAL_MACHINE:
                access |= winreg.KEY_WOW64_64KEY
            with winreg.CreateKeyEx(root, UNINSTALL_KEY, 0, access) as key:
                for name, value in values.items():
                    if isinstance(value, int):
                        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)
                    else:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
            return
        except Exception:
            continue


def _native_arch_key() -> str:
    arch = (
        os.environ.get("PROCESSOR_ARCHITEW6432")
        or os.environ.get("PROCESSOR_ARCHITECTURE")
        or ""
    ).lower()
    if "arm64" in arch or "aarch64" in arch:
        return "arm64"
    try:
        import platform

        machine = platform.machine().lower()
        if "arm" in machine or "aarch64" in machine:
            return "arm64"
    except Exception:
        pass
    return "x64"


def bundled_uninstaller_source() -> Path | None:
    arch = _native_arch_key()
    names = (
        Path("bundled_uninstaller") / f"uninstall_zaprethub_{arch}.exe",
        Path("bundled_uninstaller") / "uninstall_zaprethub.exe",
        Path("installer_payload") / f"uninstall_zaprethub_{arch}.exe",
        Path("installer_payload") / "uninstall_zaprethub.exe",
        Path(f"uninstall_zaprethub_{arch}.exe"),
        Path("uninstall_zaprethub.exe"),
    )
    for candidate in _resource_candidates():
        for rel in names:
            path = candidate / rel
            if path.is_file():
                return path
    if getattr(sys, "frozen", False):
        parent = Path(sys.executable).resolve().parent
        for name in (f"uninstall_zaprethub_{arch}.exe", "uninstall_zaprethub.exe"):
            sidecar = parent / name
            if sidecar.is_file() and sidecar.resolve() != Path(sys.executable).resolve():
                return sidecar
    return None


def copy_bundled_uninstaller(install_dir: Path) -> Path | None:
    source = bundled_uninstaller_source()
    target = install_dir / "uninstall_zaprethub.exe"
    if source is None:
        return target if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_target = target.with_suffix(target.suffix + ".tmp")
    try:
        if temp_target.exists():
            temp_target.unlink()
    except OSError:
        pass
    try:
        shutil.copyfile(source, temp_target)
        temp_target.replace(target)
        return target if target.exists() else None
    except Exception:
        try:
            if temp_target.exists():
                temp_target.unlink()
        except OSError:
            pass
        return target if target.exists() else None


def installed_executable(install_dir: Path) -> Path:
    for name in ("Zapret_Hub.exe", "zapret_hub.exe"):
        candidate = install_dir / name
        if candidate.exists():
            return candidate
    return install_dir / "Zapret_Hub.exe"


def perform_uninstall(install_dir: Path, progress_cb=None) -> None:
    def report(percent: int, status: str) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(int(percent), status)
        except Exception:
            return

    uninstaller_log("uninstall_start", target=str(install_dir))
    report(10, tr("Остановка процессов...", "Stopping processes..."))
    terminate_running_instances(install_dir)
    report(28, tr("Удаление ярлыков...", "Removing shortcuts..."))
    remove_shortcuts()
    report(46, tr("Удаление пользовательских данных...", "Removing user data..."))
    remove_app_data(install_dir)
    report(68, tr("Удаление записи в Параметрах Windows...", "Removing Windows Apps entry..."))
    remove_uninstall_registry()
    report(84, tr("Удаление файлов приложения...", "Removing application files..."))
    if install_dir.exists():
        try:
            wipe_install_dir(install_dir)
        except Exception:
            launch_folder_removal(install_dir)
        else:
            try:
                if install_dir.exists() and not any(install_dir.iterdir()):
                    install_dir.rmdir()
            except Exception:
                launch_folder_removal(install_dir)
    report(100, tr("Готово", "Done"))
    uninstaller_log("uninstall_done", target=str(install_dir))
