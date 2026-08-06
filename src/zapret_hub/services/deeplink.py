from __future__ import annotations

from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlparse


def parse_zaprethub_url(raw: str) -> dict[str, str] | None:
    """Parse zaprethub:// deep links.

    The marketplace-only deep link scheme was removed; the parser is kept for
    protocol compatibility and returns None for unknown actions.
    """
    text = str(raw or "").strip().strip('"')
    if not text:
        return None
    if "://" not in text and text.lower().startswith("zaprethub:"):
        text = text.replace("zaprethub:", "zaprethub://", 1)
    if not text.lower().startswith("zaprethub://"):
        return None
    parsed = urlparse(text)
    host = (parsed.netloc or "").strip("/").lower()
    parts = [unquote(p) for p in (parsed.path or "").strip("/").split("/") if p]
    query = {k: (v[-1] if v else "") for k, v in parse_qs(parsed.query).items()}
    # zaprethub://install/slug — kept as a generic install alias.
    if host == "install" and parts:
        return {"action": "install", "slug": parts[0], "version_id": str(query.get("version_id") or "")}
    return None


def extract_deep_link_from_argv(argv: list[str]) -> str | None:
    for item in argv:
        text = str(item or "").strip().strip('"')
        if text.lower().startswith("zaprethub:"):
            return text
    return None


def register_windows_protocol(executable: str | None = None) -> bool:
    """Register HKCU zaprethub:// handler pointing at this executable."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import winreg
    except Exception:
        return False
    exe = executable or sys.executable
    try:
        exe_path = str(Path(exe).resolve())
    except Exception:
        exe_path = str(exe)
    # Packaged builds: exe is zapret_hub.exe. Dev: python.exe — use -m style via current script if needed.
    if Path(exe_path).name.lower().startswith("python"):
        # Prefer launching the Hub entry module with the URL as argv.
        command = f'"{exe_path}" -m zapret_hub "%1"'
    else:
        command = f'"{exe_path}" "%1"'
    try:
        root = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\zaprethub")
        winreg.SetValueEx(root, "", 0, winreg.REG_SZ, "URL:Zapret Hub Protocol")
        winreg.SetValueEx(root, "URL Protocol", 0, winreg.REG_SZ, "")
        icon = winreg.CreateKey(root, "DefaultIcon")
        winreg.SetValueEx(icon, "", 0, winreg.REG_SZ, f"{exe_path},0")
        cmd_key = winreg.CreateKey(root, r"shell\open\command")
        winreg.SetValueEx(cmd_key, "", 0, winreg.REG_SZ, command)
        return True
    except Exception:
        return False
