"""Noise filters for Auto orchestrator — browsers, IDE, CDN/PTR hosts.

Browsers constantly open short-lived SYN_SENT to Akamai/Google/AWS PTR names.
Those must not trigger service activation, strategy cutovers, or endless generals.
"""

from __future__ import annotations

from pathlib import Path

# IDE / tooling that steals Auto while a real app is broken.
IDE_PROCESS_TOKENS: tuple[str, ...] = (
    "cursor.exe",
    "code.exe",
    "devenv.exe",
    "studio64.exe",
    "idea64.exe",
    "webstorm64.exe",
    "pycharm64.exe",
    "rider64.exe",
    "clion64.exe",
    "windsurf.exe",
)

BROWSER_PROCESS_TOKENS: tuple[str, ...] = (
    "msedge.exe",
    "msedgewebview2.exe",
    "chrome.exe",
    "chromium.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "opera_gx.exe",
    "vivaldi.exe",
    "browser.exe",
    "yandex.exe",
    "iexplore.exe",
    "waterfox.exe",
    "librewolf.exe",
)

# Reverse-DNS / edge fabric names — not user-facing sites worth learning or probing.
# Product CDNs (googlevideo, akamaized, cloudfront) stay learnable when a real app fails.
_INFRA_HOST_MARKERS: tuple[str, ...] = (
    "akamaitechnologies.com",
    "akamaiedge.net",
    "1e100.net",
    "googleusercontent.com",
    "edgekey.net",
    "edgesuite.net",
    "azurefd.net",
    "trafficmanager.net",
    "compute.amazonaws.com",
    "compute-1.amazonaws.com",
    "clients.gthost.com",
    "deploy.static.",
)

_INFRA_PREFIX_MARKERS: tuple[str, ...] = (
    "ec2-",
)


def exe_basename(process: str) -> str:
    raw = str(process or "").strip()
    if not raw:
        return ""
    return Path(raw.replace("\\", "/")).name.lower()


def is_browser_process(process: str) -> bool:
    name = exe_basename(process)
    blob = str(process or "").lower().replace("\\", "/")
    return any(token in name or token in blob for token in BROWSER_PROCESS_TOKENS)


def is_ide_process(process: str) -> bool:
    name = exe_basename(process)
    blob = str(process or "").lower().replace("\\", "/")
    return any(token in name or token in blob for token in IDE_PROCESS_TOKENS)


def is_noise_process(process: str) -> bool:
    return is_browser_process(process) or is_ide_process(process)


def is_infra_noise_host(host: str) -> bool:
    """True for CDN/PTR/edge fabric names that browsers hit constantly."""
    text = str(host or "").strip().lower().rstrip(".")
    if not text:
        return False
    # Pure IP is fine to learn as /32 later; PTR of IP is noise.
    if text.replace(".", "").isdigit():
        return False
    for marker in _INFRA_HOST_MARKERS:
        if marker in text:
            return True
    # Digit-heavy reverse labels like 111-38-111-172.clients...
    labels = text.split(".")
    if labels and labels[0].count("-") >= 2 and any(ch.isdigit() for ch in labels[0]):
        if any(token in text for token in ("clients.", "static.", "dynamic.", "pool.")):
            return True
    for prefix in _INFRA_PREFIX_MARKERS:
        if text.startswith(prefix) or f".{prefix}" in text:
            # a-*.deploy.static already covered; avoid matching normal domains starting with "a-"
            if prefix == "a-" and "akamai" not in text and "deploy.static" not in text:
                continue
            return True
    return False


def cdn_family_key(host: str) -> str:
    """Bucket related PTR names so one failed tune cools the whole fabric."""
    text = str(host or "").strip().lower().rstrip(".")
    if not text:
        return ""
    for marker in (
        "akamaitechnologies",
        "akamaiedge",
        "1e100.net",
        "compute.amazonaws",
        "compute-1.amazonaws",
        "azurefd",
        "gthost",
        "googleusercontent",
        "edgekey",
        "edgesuite",
    ):
        if marker in text:
            return marker
    if is_infra_noise_host(text):
        return "infra"
    return ""


def filter_learnable_hosts(hosts: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in hosts or []:
        host = str(item or "").strip().lower().rstrip(".")
        if not host or host in seen or is_infra_noise_host(host):
            continue
        seen.add(host)
        out.append(host)
    return out
