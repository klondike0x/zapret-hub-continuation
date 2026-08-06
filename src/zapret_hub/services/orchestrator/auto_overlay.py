from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from zapret_hub.services.service_rules import (
    AUTO_DEFAULT_SERVICE_IDS,
    SERVICE_RULES,
    is_stock_catalog_host,
)

_OVERLAY_DIR = "auto"
_OVERLAY_NAME = "overlay.json"
_HISTORY_LIMIT = 400


def overlay_path(configs_dir: Path) -> Path:
    return Path(configs_dir) / _OVERLAY_DIR / _OVERLAY_NAME


def _empty_payload() -> dict[str, Any]:
    return {
        "version": 1,
        "adds": {"domains": [], "ips": [], "excludes": []},
        "removes": {"domains": [], "ips": []},
        "history": [],
    }


def service_protected_hosts() -> set[str]:
    """Hosts that belong to enabled-capable service catalogs — Auto must never touch."""
    out: set[str] = set()
    for sid in AUTO_DEFAULT_SERVICE_IDS:
        rule = SERVICE_RULES.get(sid)
        if rule is None:
            continue
        for item in (*rule.list_general, *rule.list_google, *rule.health_hosts):
            host = str(item).strip().lower().rstrip(".")
            if host:
                out.add(host)
    return out


def service_protected_ips() -> set[str]:
    """CIDRs/IPs owned by service rules — Auto cannot remove or re-seed as exclude."""
    out: set[str] = set()
    for sid in AUTO_DEFAULT_SERVICE_IDS:
        rule = SERVICE_RULES.get(sid)
        if rule is None:
            continue
        for item in rule.ipset_all or ():
            key = str(item).strip().lower()
            if key:
                out.add(key)
        for item in getattr(rule, "identity_networks", ()) or ():
            key = str(item).strip().lower()
            if key:
                out.add(key)
    return out


def is_service_protected_host(host: str) -> bool:
    cleaned = (host or "").strip().lower().rstrip(".")
    if not cleaned:
        return False
    if is_stock_catalog_host(cleaned):
        return True
    protected = service_protected_hosts()
    if cleaned in protected:
        return True
    return any(cleaned == p or cleaned.endswith("." + p) for p in protected if p)


def is_service_protected_ip(address: str) -> bool:
    key = (address or "").strip().lower()
    return bool(key) and key in service_protected_ips()


class AutoOverlayStore:
    """Auto-only diff overlay. Never mutates battle/user/service source lists.

    Adds / removes are applied at materialize time when Auto is on.
    Manual merge ignores this file entirely — originals stay intact.
    """

    def __init__(self, configs_dir: Path) -> None:
        self.configs_dir = Path(configs_dir)
        self.path = overlay_path(self.configs_dir)
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        if not self.path.is_file():
            return _empty_payload()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return _empty_payload()
        if not isinstance(raw, dict):
            return _empty_payload()
        base = _empty_payload()
        for section in ("adds", "removes"):
            src = raw.get(section) if isinstance(raw.get(section), dict) else {}
            for key in base[section]:
                values = src.get(key) if isinstance(src, dict) else None
                if isinstance(values, list):
                    base[section][key] = [
                        str(item).strip() for item in values if str(item).strip()
                    ]
        history = raw.get("history")
        if isinstance(history, list):
            base["history"] = [item for item in history if isinstance(item, dict)][-_HISTORY_LIMIT:]
        return base

    def _write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.path)

    def checkpoint(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._read()))

    def restore(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            payload = snapshot if isinstance(snapshot, dict) else _empty_payload()
            self._write(payload if payload.get("version") else {**_empty_payload(), **payload})

    def clear(self) -> None:
        with self._lock:
            self._write(_empty_payload())
            if self.path.exists():
                # Keep empty file so path stays stable for debugging.
                pass

    def _append_history(
        self,
        payload: dict[str, Any],
        *,
        kind: str,
        values: list[str],
        reason: str,
    ) -> str:
        entry_id = uuid.uuid4().hex[:12]
        history = list(payload.get("history") or [])
        history.append(
            {
                "id": entry_id,
                "ts": int(time.time()),
                "kind": kind,
                "values": list(values),
                "reason": str(reason or ""),
                "reverted": False,
            }
        )
        payload["history"] = history[-_HISTORY_LIMIT:]
        return entry_id

    def add_domains(self, domains: list[str], *, reason: str = "") -> list[str]:
        cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
        # Adding a service host is redundant but harmless; still record if new.
        return self._mutate_list("adds", "domains", cleaned, kind="add_domain", reason=reason)

    def add_ips(self, ips: list[str], *, reason: str = "") -> list[str]:
        cleaned = [item.strip() for item in ips if item and item.strip()]
        # Never "add" service-owned CDN nets as Auto removes later — skip protected.
        cleaned = [item for item in cleaned if not is_service_protected_ip(item)]
        return self._mutate_list("adds", "ips", cleaned, kind="add_ip", reason=reason)

    def exclude_domains(self, domains: list[str], *, reason: str = "") -> list[str]:
        cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
        # Immutable services: Discord/YouTube/… can never be Auto-excluded.
        cleaned = [d for d in cleaned if not is_service_protected_host(d)]
        return self._mutate_list("adds", "excludes", cleaned, kind="exclude_domain", reason=reason)

    def remove_domains(self, domains: list[str], *, reason: str = "") -> list[str]:
        """Mark non-service domains to drop from the merged hostlist (diff only)."""
        cleaned = [d.strip().lower().rstrip(".") for d in domains if d and d.strip()]
        cleaned = [d for d in cleaned if not is_service_protected_host(d)]
        return self._mutate_list("removes", "domains", cleaned, kind="remove_domain", reason=reason)

    def remove_ips(self, ips: list[str], *, reason: str = "") -> list[str]:
        """Mark non-service IPs to drop from merged ipset (diff only)."""
        cleaned = [item.strip() for item in ips if item and item.strip()]
        cleaned = [item for item in cleaned if not is_service_protected_ip(item)]
        return self._mutate_list("removes", "ips", cleaned, kind="remove_ip", reason=reason)

    def _mutate_list(
        self,
        section: str,
        key: str,
        values: list[str],
        *,
        kind: str,
        reason: str,
    ) -> list[str]:
        if not values:
            return []
        with self._lock:
            payload = self._read()
            bucket: list[str] = list(payload[section][key])
            seen = {item.strip().lower() for item in bucket}
            added: list[str] = []
            for item in values:
                norm = item.strip()
                key_l = norm.lower()
                if not norm or key_l in seen:
                    continue
                # Cross-cancel: adding undoes a pending remove and vice versa.
                opposite = "removes" if section == "adds" else "adds"
                opp_key = key if key != "excludes" else "domains"
                if section == "adds" and key == "excludes":
                    # Excludes are only in adds.excludes; cancel matching adds.domains.
                    payload["adds"]["domains"] = [
                        row for row in payload["adds"]["domains"] if row.strip().lower() != key_l
                    ]
                elif opposite in payload and opp_key in payload[opposite]:
                    before = list(payload[opposite][opp_key])
                    payload[opposite][opp_key] = [
                        row for row in before if row.strip().lower() != key_l
                    ]
                seen.add(key_l)
                bucket.append(norm)
                added.append(norm)
            if not added:
                return []
            payload[section][key] = bucket
            self._append_history(payload, kind=kind, values=added, reason=reason)
            self._write(payload)
            return added

    def revert_entry(self, entry_id: str) -> bool:
        with self._lock:
            payload = self._read()
            history = list(payload.get("history") or [])
            target = next((item for item in history if str(item.get("id")) == str(entry_id)), None)
            if target is None or bool(target.get("reverted")):
                return False
            kind = str(target.get("kind") or "")
            values = [str(v).strip() for v in list(target.get("values") or []) if str(v).strip()]
            lower = {v.lower() for v in values}

            def _drop(bucket: list[str]) -> list[str]:
                return [row for row in bucket if row.strip().lower() not in lower]

            if kind == "add_domain":
                payload["adds"]["domains"] = _drop(payload["adds"]["domains"])
            elif kind == "add_ip":
                payload["adds"]["ips"] = _drop(payload["adds"]["ips"])
            elif kind == "exclude_domain":
                payload["adds"]["excludes"] = _drop(payload["adds"]["excludes"])
            elif kind == "remove_domain":
                payload["removes"]["domains"] = _drop(payload["removes"]["domains"])
            elif kind == "remove_ip":
                payload["removes"]["ips"] = _drop(payload["removes"]["ips"])
            else:
                return False
            target["reverted"] = True
            self._append_history(
                payload,
                kind="revert",
                values=values,
                reason=f"undo:{entry_id}:{kind}",
            )
            self._write(payload)
            return True

    def revert_since_checkpoint(self, snapshot: dict[str, Any]) -> None:
        """Roll overlay back to a prior checkpoint (failed Auto plan)."""
        self.restore(snapshot)

    def snapshot_public(self) -> dict[str, Any]:
        with self._lock:
            payload = self._read()
            return {
                "adds": payload["adds"],
                "removes": payload["removes"],
                "history": list(payload.get("history") or [])[-40:],
            }

    def apply_to_lists_dir(self, lists_dir: Path) -> dict[str, int]:
        """Apply diff onto a materialized runtime lists directory (never source configs)."""
        lists_dir = Path(lists_dir)
        with self._lock:
            payload = self._read()
        stats = {"domains_added": 0, "ips_added": 0, "excludes_added": 0, "domains_removed": 0, "ips_removed": 0}

        def _read_lines(path: Path) -> list[str]:
            if not path.is_file():
                return []
            try:
                return [row.rstrip() for row in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
            except Exception:
                return []

        def _write_lines(path: Path, rows: list[str]) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")

        # 1) Removals from merged hostlist / ipset (service-protected rows stay).
        remove_domains = {
            row.strip().lower().rstrip(".")
            for row in payload["removes"]["domains"]
            if row.strip() and not is_service_protected_host(row)
        }
        remove_ips = {
            row.strip().lower()
            for row in payload["removes"]["ips"]
            if row.strip() and not is_service_protected_ip(row)
        }
        for name in ("list-general.txt", "list-general-user.txt", "list-google.txt"):
            path = lists_dir / name
            rows = _read_lines(path)
            if not rows or not remove_domains:
                continue
            kept: list[str] = []
            for row in rows:
                host = row.strip().lower().rstrip(".")
                if host and not host.startswith("#") and (
                    host in remove_domains
                    or any(host == d or host.endswith("." + d) for d in remove_domains)
                ):
                    stats["domains_removed"] += 1
                    continue
                kept.append(row)
            if len(kept) != len(rows):
                _write_lines(path, kept)
        for name in ("ipset-all.txt", "ipset-all-user.txt"):
            path = lists_dir / name
            rows = _read_lines(path)
            if not rows or not remove_ips:
                continue
            kept = []
            for row in rows:
                key = row.strip().lower()
                if key and not key.startswith("#") and key in remove_ips:
                    stats["ips_removed"] += 1
                    continue
                kept.append(row)
            if len(kept) != len(rows):
                _write_lines(path, kept)

        # 2) Adds into user-facing runtime lists (overlay only — source configs untouched).
        def _append_unique(path: Path, values: list[str], *, counter: str) -> None:
            if not values:
                return
            rows = _read_lines(path)
            seen = {row.strip().lower() for row in rows if row.strip() and not row.lstrip().startswith("#")}
            changed = False
            for item in values:
                key = item.strip().lower()
                if not key or key in seen:
                    continue
                if counter.startswith("exclude") and is_service_protected_host(item):
                    continue
                if counter.startswith("ips") and is_service_protected_ip(item):
                    continue
                seen.add(key)
                rows.append(item.strip())
                stats[counter] += 1
                changed = True
            if changed:
                _write_lines(path, rows)

        _append_unique(
            lists_dir / "list-general-user.txt",
            list(payload["adds"]["domains"]),
            counter="domains_added",
        )
        _append_unique(
            lists_dir / "ipset-all-user.txt",
            list(payload["adds"]["ips"]),
            counter="ips_added",
        )
        _append_unique(
            lists_dir / "list-exclude-user.txt",
            [d for d in payload["adds"]["excludes"] if not is_service_protected_host(d)],
            counter="excludes_added",
        )
        return stats


def migrate_legacy_markers_into_overlay(configs_dir: Path) -> dict[str, int]:
    """One-shot: pull old `# --- zapret-hub-auto ---` blocks into overlay.json, then strip them."""
    from zapret_hub.services.orchestrator.learner import extract_auto_overlay_lines, strip_auto_overlay

    configs = Path(configs_dir)
    store = AutoOverlayStore(configs)
    moved = {"domains": 0, "excludes": 0, "ips": 0}
    mapping = {
        "list-general-user.txt": ("domains", "add_domains"),
        "list-exclude-user.txt": ("excludes", "exclude_domains"),
        "ipset-all-user.txt": ("ips", "add_ips"),
    }
    for filename, (counter, method) in mapping.items():
        path = configs / filename
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        lines = extract_auto_overlay_lines(text)
        if lines:
            added = getattr(store, method)(lines, reason="migrate_legacy_markers")
            moved[counter] += len(added)
        cleaned = strip_auto_overlay(text)
        # Also drop any leftover protected service hosts from battle exclude files.
        if filename == "list-exclude-user.txt" and cleaned:
            kept_rows: list[str] = []
            for row in cleaned.splitlines():
                host = row.strip().lower().rstrip(".")
                if host and not host.startswith("#") and is_service_protected_host(host):
                    continue
                kept_rows.append(row.rstrip())
            cleaned = "\n".join(kept_rows) + ("\n" if kept_rows else "")
        if cleaned != text:
            try:
                path.write_text(cleaned, encoding="utf-8")
            except Exception:
                pass

    # Zapret2 list-auto → overlay domains, then clear list-auto (regenerated on Auto materialize).
    z2_auto = configs / "zapret2" / "list-auto.txt"
    if z2_auto.is_file():
        try:
            rows = [
                row.strip().lower().rstrip(".")
                for row in z2_auto.read_text(encoding="utf-8", errors="ignore").splitlines()
                if row.strip() and not row.lstrip().startswith("#")
            ]
        except Exception:
            rows = []
        if rows:
            added = store.add_domains(rows, reason="migrate_list_auto")
            moved["domains"] += len(added)
            try:
                z2_auto.write_text("", encoding="utf-8")
            except Exception:
                pass
    return moved


def scrub_protected_hosts_from_exclude_file(path: Path) -> int:
    """Remove stock-service hosts from an exclude list file. Returns removed count."""
    path = Path(path)
    if not path.is_file():
        return 0
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return 0
    kept: list[str] = []
    removed = 0
    for line in lines:
        host = line.strip().lower().rstrip(".")
        if host and not host.startswith("#") and is_service_protected_host(host):
            removed += 1
            continue
        kept.append(line.rstrip())
    if removed:
        try:
            path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except Exception:
            return 0
    return removed


def scrub_overlay_service_violations(configs_dir: Path) -> dict[str, int]:
    """Drop illegal Auto overlay rows that touch immutable services."""
    store = AutoOverlayStore(configs_dir)
    with store._lock:
        payload = store._read()
        removed = {"excludes": 0, "remove_domains": 0, "remove_ips": 0, "adds_ips": 0}
        before_ex = list(payload["adds"]["excludes"])
        payload["adds"]["excludes"] = [row for row in before_ex if not is_service_protected_host(row)]
        removed["excludes"] = len(before_ex) - len(payload["adds"]["excludes"])

        before_rd = list(payload["removes"]["domains"])
        payload["removes"]["domains"] = [row for row in before_rd if not is_service_protected_host(row)]
        removed["remove_domains"] = len(before_rd) - len(payload["removes"]["domains"])

        before_ri = list(payload["removes"]["ips"])
        payload["removes"]["ips"] = [row for row in before_ri if not is_service_protected_ip(row)]
        removed["remove_ips"] = len(before_ri) - len(payload["removes"]["ips"])

        before_ai = list(payload["adds"]["ips"])
        payload["adds"]["ips"] = [row for row in before_ai if not is_service_protected_ip(row)]
        removed["adds_ips"] = len(before_ai) - len(payload["adds"]["ips"])

        if any(removed.values()):
            store._append_history(
                payload,
                kind="repair",
                values=[f"{k}:{v}" for k, v in removed.items() if v],
                reason="scrub_service_violations",
            )
            store._write(payload)
        return removed


def ensure_auto_integrity(
    configs_dir: Path,
    *,
    work_root: Path | None = None,
) -> dict[str, Any]:
    """Idempotent post-update / every-start repair.

    1) Move legacy in-file Auto markers into overlay.json
    2) Scrub battle excludes/ipsets of service-owned rows (Discord/YouTube/…)
    3) Scrub illegal rows from overlay itself
    4) Scrub live runtime exclude copies under merged_runtime so Discord works
       without waiting for the next materialize

    Manual mode never applies overlay — after this, battle files match stock
    service rules again even if old Auto polluted them.
    """
    from zapret_hub.services.orchestrator import zapret2_hub

    configs = Path(configs_dir)
    report: dict[str, Any] = {
        "migrated": {},
        "sanitized": {},
        "overlay_scrub": {},
        "runtime_excludes_removed": 0,
    }
    try:
        report["migrated"] = migrate_legacy_markers_into_overlay(configs)
    except Exception as error:
        report["migrate_error"] = str(error)
    try:
        report["sanitized"] = zapret2_hub.sanitize_classic_discord_pollution(configs)
    except Exception as error:
        report["sanitize_error"] = str(error)
    # Extra pass: scrub ALL stock-service hosts from classic + zapret2 excludes.
    for rel in (
        configs / "list-exclude-user.txt",
        configs / "list-exclude.txt",
    ):
        report["runtime_excludes_removed"] += scrub_protected_hosts_from_exclude_file(rel)
    try:
        z2_exclude = zapret2_hub.ensure_zapret2_lists(configs)["exclude"]
        report["runtime_excludes_removed"] += scrub_protected_hosts_from_exclude_file(z2_exclude)
    except Exception:
        pass
    try:
        report["overlay_scrub"] = scrub_overlay_service_violations(configs)
    except Exception as error:
        report["overlay_scrub_error"] = str(error)

    roots: list[Path] = []
    if work_root is not None:
        merged = Path(work_root) / "merged_runtime"
        if merged.is_dir():
            roots.append(merged)
    for root in roots:
        try:
            for path in root.rglob("list-exclude*.txt"):
                report["runtime_excludes_removed"] += scrub_protected_hosts_from_exclude_file(path)
        except Exception:
            pass
        # Also strip Discord CDN parent from live ipset-all when Discord service is stock.
        try:
            ban = {"162.158.0.0/15", "162.159.128.0/20"}
            ban |= {str(x).strip().lower() for x in zapret2_hub.BYPASS_SEED_NETWORKS}
            for path in root.rglob("ipset-all.txt"):
                try:
                    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
                except Exception:
                    continue
                kept = [row for row in lines if row.strip().lower() not in ban]
                if len(kept) != len(lines):
                    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        except Exception:
            pass
    return report


__all__ = [
    "AutoOverlayStore",
    "migrate_legacy_markers_into_overlay",
    "ensure_auto_integrity",
    "scrub_protected_hosts_from_exclude_file",
    "scrub_overlay_service_violations",
    "overlay_path",
    "is_service_protected_host",
    "is_service_protected_ip",
    "service_protected_hosts",
    "service_protected_ips",
]
