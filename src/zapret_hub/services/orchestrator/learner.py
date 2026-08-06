from __future__ import annotations

import ipaddress
from pathlib import Path

from zapret_hub.services.orchestrator.auto_overlay import (
    AutoOverlayStore,
    is_service_protected_host,
    migrate_legacy_markers_into_overlay,
)
from zapret_hub.services.orchestrator.conflicts import ConflictDetector

_AUTO_START = "# --- zapret-hub-auto ---"
_AUTO_END = "# --- end zapret-hub-auto ---"


def strip_auto_overlay(text: str) -> str:
    """Remove legacy Auto marker blocks from text (battle files must stay clean)."""
    if not text:
        return ""
    lines = text.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped == _AUTO_START:
            skipping = True
            continue
        if stripped == _AUTO_END:
            skipping = False
            continue
        if skipping:
            continue
        out.append(line.rstrip())
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out) + ("\n" if out else "")


def extract_auto_overlay_lines(text: str) -> list[str]:
    if not text:
        return []
    lines = text.splitlines()
    out: list[str] = []
    capturing = False
    for line in lines:
        stripped = line.strip()
        if stripped == _AUTO_START:
            capturing = True
            continue
        if stripped == _AUTO_END:
            capturing = False
            continue
        if capturing and stripped and not stripped.startswith("#"):
            out.append(stripped)
    return out


class HostlistLearner:
    """Auto-hostlist writer — only mutates configs/auto/overlay.json (diff), never battle lists.

    Service catalog hosts (Discord/YouTube/…) cannot be excluded. Removals of
    service-owned IPs/domains are rejected. Manual mode ignores the overlay.
    """

    FAIL_THRESHOLD = 2

    def __init__(self, configs_dir: Path) -> None:
        self.configs_dir = Path(configs_dir)
        self._overlay = AutoOverlayStore(self.configs_dir)
        try:
            migrate_legacy_markers_into_overlay(self.configs_dir)
        except Exception:
            pass

    def add_domains(self, domains: list[str], *, reason: str = "learn") -> list[str]:
        cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
        return self._overlay.add_domains(cleaned, reason=reason)

    def exclude_domains(self, domains: list[str], *, reason: str = "over_block") -> list[str]:
        cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
        cleaned = [d for d in cleaned if not is_service_protected_host(d)]
        return self._overlay.exclude_domains(cleaned, reason=reason)

    def add_ips(self, ips: list[str], *, reason: str = "learn") -> list[str]:
        cleaned = [item.strip() for item in ips if item and item.strip()]
        return self._overlay.add_ips(cleaned, reason=reason)

    def remove_domains(self, domains: list[str], *, reason: str = "diff_remove") -> list[str]:
        return self._overlay.remove_domains(domains, reason=reason)

    def remove_ips(self, ips: list[str], *, reason: str = "diff_remove") -> list[str]:
        return self._overlay.remove_ips(ips, reason=reason)

    def checkpoint(self) -> dict:
        return self._overlay.checkpoint()

    def restore(self, snapshot: dict) -> None:
        self._overlay.restore(snapshot)

    @staticmethod
    def _domain_match(host: str, entry: str) -> bool:
        host = host.strip().lower().rstrip(".")
        entry = entry.strip().lower().rstrip(".")
        if not host or not entry or entry.startswith("#"):
            return False
        return host == entry or host.endswith("." + entry)

    @staticmethod
    def _ip_match(address: str, entry: str) -> bool:
        try:
            target = ipaddress.ip_address(address)
        except ValueError:
            return False
        try:
            if "/" in entry:
                return target in ipaddress.ip_network(entry, strict=False)
            return target == ipaddress.ip_address(entry)
        except ValueError:
            return False

    def domain_in_merged_lists(self, domain: str, lists_dirs: list[Path]) -> bool:
        host = domain.strip().lower().rstrip(".")
        if not host:
            return False
        names = ("list-general.txt", "list-general-user.txt", "list-google.txt")
        for directory in lists_dirs:
            for name in names:
                path = directory / name
                if not path.exists():
                    continue
                try:
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    continue
                for line in lines:
                    if self._domain_match(host, line):
                        return True
        # Also treat pending Auto adds as present (avoid re-learning).
        try:
            snap = self._overlay.snapshot_public()
            for item in snap.get("adds", {}).get("domains", []):
                if self._domain_match(host, str(item)):
                    return True
        except Exception:
            pass
        return False

    def ip_in_merged_lists(self, ip: str, lists_dirs: list[Path]) -> bool:
        address = (ip or "").strip()
        if not address:
            return False
        names = ("ipset-all.txt", "ipset-all-user.txt")
        for directory in lists_dirs:
            for name in names:
                path = directory / name
                if not path.exists():
                    continue
                try:
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    continue
                for line in lines:
                    entry = line.strip()
                    if not entry or entry.startswith("#"):
                        continue
                    if self._ip_match(address, entry):
                        return True
        return False

    def classify(
        self,
        *,
        host: str,
        probe_ok: bool,
        probe_error: str = "",
        lists_dirs: list[Path] | None = None,
    ) -> str:
        if probe_ok:
            return "ok"
        err = (probe_error or "").lower()
        if "getaddrinfo" in err or "name or service not known" in err or "nodename" in err:
            return "dead_host"
        in_lists = self.domain_in_merged_lists(host, lists_dirs or [self.configs_dir])
        if not in_lists:
            return "external_miss"
        return "suspect_overblock"


def learn_host(
    host: str,
    *,
    success: bool = False,
    configs_dir: Path | None = None,
    fail_count: int = 0,
    threshold: int = HostlistLearner.FAIL_THRESHOLD,
) -> list[str]:
    if not host or configs_dir is None or success:
        return []
    if fail_count and fail_count < threshold:
        return []
    learner = HostlistLearner(configs_dir)
    return learner.add_domains([host])


__all__ = [
    "HostlistLearner",
    "ConflictDetector",
    "learn_host",
    "strip_auto_overlay",
    "extract_auto_overlay_lines",
]
