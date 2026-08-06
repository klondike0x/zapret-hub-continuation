from __future__ import annotations

from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlparse


def parse_zaprethub_url(raw: str) -> dict[str, str] | None:
    """Parse zaprethub:// deep links.

    Supported:
      zaprethub://marketplace/install/<slug>
      zaprethub://marketplace/install?slug=<slug>&version_id=123
      zaprethub://marketplace/project/<slug>
      zaprethub://install/<slug>   (short alias)

    Hub treats marketplace deep links with a slug as "Add to Zapret Hub":
    open the project page and enqueue a native download.
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

    # zaprethub://install/slug
    if host == "install" and parts:
        return {"action": "install", "slug": parts[0], "version_id": str(query.get("version_id") or "")}
    if host == "marketplace":
        if parts and parts[0] == "install":
            slug = parts[1] if len(parts) > 1 else str(query.get("slug") or "")
            if not slug:
                return None
            return {"action": "install", "slug": slug, "version_id": str(query.get("version_id") or "")}
        if parts and parts[0] in {"project", "open"}:
            slug = parts[1] if len(parts) > 1 else str(query.get("slug") or "")
            if not slug:
                return None
            return {"action": "open", "slug": slug, "version_id": ""}
        if str(query.get("slug") or ""):
            action = "install" if str(query.get("action") or "install") == "install" else "open"
            return {"action": action, "slug": str(query.get("slug")), "version_id": str(query.get("version_id") or "")}
    # zaprethub:///marketplace/install/slug (empty host)
    if not host and parts:
        if parts[0] == "install" and len(parts) > 1:
            return {"action": "install", "slug": parts[1], "version_id": str(query.get("version_id") or "")}
        if parts[0] == "marketplace" and len(parts) >= 3 and parts[1] == "install":
            return {"action": "install", "slug": parts[2], "version_id": str(query.get("version_id") or "")}
        if parts[0] == "marketplace" and len(parts) >= 3 and parts[1] in {"project", "open"}:
            return {"action": "open", "slug": parts[2], "version_id": ""}
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
