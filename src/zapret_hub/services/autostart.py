from __future__ import annotations

import sys
import winreg
from pathlib import Path

from zapret_hub.services.logging_service import LoggingManager


class AutostartManager:
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "ZapretHub"
    LEGACY_APP_NAMES = ("Zapret Hub", "zapret_hub")

    def __init__(self, logging: LoggingManager) -> None:
        self.logging = logging

    def is_enabled(self) -> bool:
        # A per-user Run entry is transparent, reversible and does not require
        # a scheduled task with elevated privileges.
        return self._run_entry_exists()

    def set_enabled(self, enabled: bool) -> bool:
        command = self._build_command()
        self._remove_legacy_run_entries()
        result = False
        if enabled:
            result = self._set_run_entry(command)
        else:
            result = not self.is_enabled()
        self.logging.log("info", "Windows autostart changed", enabled=enabled, actual=result, command=command if enabled else "")
        return result

    def _build_command(self) -> str:
        executable = Path(sys.executable)
        if executable.suffix.lower() == ".exe" and executable.name.lower() != "python.exe":
            return f'"{executable}" --autostart-launch'
        main_module = Path(__file__).resolve().parents[1] / "main.py"
        return f'"{executable}" "{main_module}" --autostart-launch'

    def _run_entry_exists(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_READ) as key:
                for name in (self.APP_NAME, *self.LEGACY_APP_NAMES):
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    if str(value or "").strip():
                        return True
        except FileNotFoundError:
            return False
        return False

    def _set_run_entry(self, command: str) -> bool:
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, self.APP_NAME, 0, winreg.REG_SZ, command)
            return self._run_entry_exists()
        except OSError as error:
            self.logging.log("warning", "Failed to create autostart Run entry", error=str(error))
            return False

    def _remove_legacy_run_entries(self) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                for name in (self.APP_NAME, *self.LEGACY_APP_NAMES):
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
        except FileNotFoundError:
            return
