from __future__ import annotations

"""Map domain / IP / process → service_id for Auto orchestrator incidents."""

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable

from zapret_hub.services.service_rules import SERVICE_RULES, ServiceRule


@dataclass(frozen=True, slots=True)
class MapHit:
    service_id: str
    kind: str  # "domain" | "ip" | "process" | "resolve" | "reverse_dns"
    matched: str
    score: float = 1.0


# Executable / process name fragments → service_id.
# Browsers are intentionally NOT mapped (false positives → youtube).
PROCESS_SERVICE_MAP: dict[str, str] = {
    "discord": "discord",
    "discordptb": "discord",
    "discordcanary": "discord",
    "telegram": "telegram-desktop",
    "telegram.exe": "telegram-desktop",
    "spotify": "spotify",
    "spotify.exe": "spotify",
    "steam": "gaming",
    "steamwebhelper": "gaming",
    "epicgameslauncher": "epic-games",
    "epicgameslauncher.exe": "epic-games",
    "fortniteclient": "fortnite",
    "fortniteclient-win64-shipping": "fortnite",
    "fortnitelauncher": "fortnite",
    "warframe": "warframe",
    "warframe.x64": "warframe",
    "uplay": "ubisoft",
    "upc": "ubisoft",
    "ubisoftconnect": "ubisoft",
    "battle.net": "battle-net",
    "riotclientservices": "riot-games",
    "leagueclient": "league-of-legends",
    "league of legends": "league-of-legends",
    "shootergame": "gaming",
    "arkascended": "gaming",
    "back4blood": "gaming",
    "figma": "figma",
    "netflix": "netflix",
}

# Install-folder markers for generic updaters (Update.exe / Squirrel / etc.).
_PATH_SERVICE_MARKERS: tuple[tuple[str, str], ...] = (
    ("/discord/", "discord"),
    ("/discordptb/", "discord"),
    ("/discordcanary/", "discord"),
    ("/spotify/", "spotify"),
    ("/telegram desktop/", "telegram-desktop"),
    ("/telegramdesktop/", "telegram-desktop"),
    ("/steam/", "gaming"),
    ("/epic games/", "epic-games"),
    ("/epicgames/", "epic-games"),
    ("/warframe/", "warframe"),
    ("/battle.net/", "battle-net"),
    ("/riot games/", "riot-games"),
    ("/ubisoft/", "ubisoft"),
    ("/ubisoft game launcher/", "ubisoft"),
    ("/figma/", "figma"),
)
_UPDATER_PROCESS_NAMES = frozenset({"update", "updater", "updated", "squirrel", "install", "installer"})
# Broad CDN buckets that lose to a process-mapped app service.
_BROAD_CDN_SERVICES = frozenset({"cloudflare", "clouds"})


def _normalize_host(value: str) -> str:
    host = (value or "").strip().lower().rstrip(".")
    if host.startswith("http://"):
        host = host[7:]
    elif host.startswith("https://"):
        host = host[8:]
    host = host.split("/", 1)[0]
    host = host.split(":", 1)[0]
    return host.strip("[]")


def _normalize_process(value: str) -> str:
    name = (value or "").strip().lower()
    if "\\" in name or "/" in name:
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if name.endswith(".exe"):
        name = name[:-4]
    return name


def _domain_matches(host: str, pattern: str) -> bool:
    pattern = pattern.strip().lower().rstrip(".")
    if not host or not pattern:
        return False
    return host == pattern or host.endswith("." + pattern)


def _iter_rule_domains(rule: ServiceRule) -> Iterable[str]:
    yield from rule.list_general
    yield from rule.list_google
    yield from rule.hosts
    for _name, entries in rule.extra_lists:
        if "ipset" in _name.lower():
            continue
        yield from entries


def _iter_rule_ips(rule: ServiceRule) -> Iterable[str]:
    yield from rule.ipset_all
    yield from getattr(rule, "identity_networks", ()) or ()
    for name, entries in rule.extra_lists:
        if "ipset" in name.lower():
            yield from entries


def _ip_in_network(ip: str, network_or_ip: str) -> bool:
    try:
        target = ipaddress.ip_address(ip)
    except ValueError:
        return False
    try:
        if "/" in network_or_ip:
            return target in ipaddress.ip_network(network_or_ip, strict=False)
        return target == ipaddress.ip_address(network_or_ip)
    except ValueError:
        return False


class ServiceMapper:
    """Resolve a host / IP / process into one or more service ids."""

    def __init__(self, rules: dict[str, ServiceRule] | None = None) -> None:
        self.rules = rules if rules is not None else SERVICE_RULES
        self._domain_index = self._build_domain_index()
        self._ip_index = self._build_ip_index()

    def _build_domain_index(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for service_id, rule in self.rules.items():
            for domain in _iter_rule_domains(rule):
                cleaned = domain.strip().lower().rstrip(".")
                if cleaned:
                    rows.append((cleaned, service_id))
        rows.sort(key=lambda item: len(item[0]), reverse=True)
        return rows

    def _build_ip_index(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        for service_id, rule in self.rules.items():
            for entry in _iter_rule_ips(rule):
                cleaned = entry.strip()
                if cleaned:
                    rows.append((cleaned, service_id))
        return rows

    def map_domain(self, domain: str) -> list[MapHit]:
        host = _normalize_host(domain)
        if not host:
            return []
        hits: list[MapHit] = []
        seen: set[str] = set()
        for pattern, service_id in self._domain_index:
            if service_id in seen:
                continue
            if _domain_matches(host, pattern):
                seen.add(service_id)
                hits.append(
                    MapHit(
                        service_id=service_id,
                        kind="domain",
                        matched=pattern,
                        score=float(len(pattern)),
                    )
                )
        return hits

    def map_ip(self, ip: str) -> list[MapHit]:
        address = (ip or "").strip()
        if not address:
            return []
        hits: list[MapHit] = []
        seen: set[str] = set()
        for network, service_id in self._ip_index:
            if service_id in seen:
                continue
            if _ip_in_network(address, network):
                seen.add(service_id)
                # Prefer tighter CIDRs so Discord /20 beats Cloudflare /15.
                score = 1.0
                try:
                    if "/" in network:
                        score = float(ipaddress.ip_network(network, strict=False).prefixlen)
                except ValueError:
                    score = 1.0
                hits.append(MapHit(service_id=service_id, kind="ip", matched=network, score=score))
        return hits

    def map_process(self, process: str) -> list[MapHit]:
        raw = (process or "").strip()
        name = _normalize_process(raw)
        if not name:
            return []
        hits: list[MapHit] = []
        seen: set[str] = set()
        path_blob = raw.replace("\\", "/").lower()
        # Generic updaters (Update.exe) only count when the install path is known.
        if name in _UPDATER_PROCESS_NAMES or name.endswith("update") or name.endswith("updater"):
            for marker, service_id in _PATH_SERVICE_MARKERS:
                if marker in path_blob and service_id not in seen:
                    seen.add(service_id)
                    hits.append(
                        MapHit(service_id=service_id, kind="process", matched=f"{marker}{name}", score=3.0)
                    )
                    break
        else:
            for marker, service_id in _PATH_SERVICE_MARKERS:
                if marker in path_blob and service_id not in seen and (
                    name.startswith(service_id.split("-")[0]) or service_id.replace("-", "") in name.replace("-", "")
                ):
                    # Path confirms a known app binary even when the exe name is odd.
                    seen.add(service_id)
                    hits.append(MapHit(service_id=service_id, kind="process", matched=marker, score=2.5))
                    break
        for key, service_id in PROCESS_SERVICE_MAP.items():
            key_norm = _normalize_process(key)
            if key_norm == name or key_norm in name or name in key_norm:
                if service_id not in seen:
                    seen.add(service_id)
                    hits.append(MapHit(service_id=service_id, kind="process", matched=key, score=2.0))
        return hits

    def resolve(self, host: str, *, timeout_s: float = 2.0) -> list[str]:
        """Forward DNS: hostname → IP addresses."""
        name = _normalize_host(host)
        if not name:
            return []
        try:
            previous = socket.getdefaulttimeout()
            socket.setdefaulttimeout(timeout_s)
            try:
                infos = socket.getaddrinfo(name, None)
            finally:
                socket.setdefaulttimeout(previous)
        except OSError:
            return []
        addresses: list[str] = []
        seen: set[str] = set()
        for info in infos:
            addr = str(info[4][0])
            if addr not in seen:
                seen.add(addr)
                addresses.append(addr)
        return addresses

    def reverse_dns(self, ip: str, *, timeout_s: float = 2.0) -> str:
        """Reverse DNS: IP → hostname (empty string on failure)."""
        address = (ip or "").strip()
        if not address:
            return ""
        try:
            previous = socket.getdefaulttimeout()
            socket.setdefaulttimeout(timeout_s)
            try:
                host, _aliases, _addrs = socket.gethostbyaddr(address)
            finally:
                socket.setdefaulttimeout(previous)
            return _normalize_host(host)
        except OSError:
            return ""

    def map(
        self,
        *,
        host: str = "",
        ip: str = "",
        process: str = "",
        use_dns: bool = True,
    ) -> list[MapHit]:
        """Combine domain / IP / process signals into ranked MapHit list."""
        hits: list[MapHit] = []
        hits.extend(self.map_process(process))
        hits.extend(self.map_domain(host))

        resolved_ips = list(filter(None, [ip.strip()] if ip else []))
        if use_dns and host and not resolved_ips:
            resolved_ips = self.resolve(host)

        for address in resolved_ips:
            hits.extend(self.map_ip(address))
            if use_dns and not host:
                ptr = self.reverse_dns(address)
                if ptr:
                    for item in self.map_domain(ptr):
                        hits.append(
                            MapHit(
                                service_id=item.service_id,
                                kind="reverse_dns",
                                matched=ptr,
                                score=item.score * 0.9,
                            )
                        )

        grouped: dict[str, list[MapHit]] = {}
        for hit in hits:
            grouped.setdefault(hit.service_id, []).append(hit)

        best: dict[str, MapHit] = {}
        for service_id, service_hits in grouped.items():
            strongest = max(service_hits, key=lambda item: item.score)
            evidence_kinds = {item.kind for item in service_hits}
            score = sum(item.score for item in service_hits)
            if "domain" in evidence_kinds and "ip" in evidence_kinds:
                score += 8.0
            if "process" in evidence_kinds and ({"domain", "ip", "reverse_dns"} & evidence_kinds):
                score += 5.0
            best[service_id] = MapHit(
                service_id=service_id,
                kind=strongest.kind,
                matched=strongest.matched,
                score=score,
            )
        # Prefer app-specific services over broad CDN buckets when process evidence exists.
        process_services = {hit.service_id for hit in self.map_process(process)}
        specific = process_services - _BROAD_CDN_SERVICES
        if specific:
            for broad in list(_BROAD_CDN_SERVICES):
                if broad in best and specific:
                    best.pop(broad, None)
        return sorted(best.values(), key=lambda item: item.score, reverse=True)

    def primary_service(
        self,
        *,
        host: str = "",
        ip: str = "",
        process: str = "",
    ) -> str | None:
        hits = self.map(host=host, ip=ip, process=process)
        return hits[0].service_id if hits else None


_DEFAULT_MAPPER = ServiceMapper()


def map_target(host: str = "", ip: str = "", process: str = "") -> str | None:
    """Module-level helper used by thin wrappers and tests."""
    return _DEFAULT_MAPPER.primary_service(host=host, ip=ip, process=process)


def map_all_targets(host: str = "", ip: str = "", process: str = "") -> list[str]:
    """Return all matching service ids for the given signals."""
    hits = _DEFAULT_MAPPER.map(host=host, ip=ip, process=process)
    return [hit.service_id for hit in hits]
