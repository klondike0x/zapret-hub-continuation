from __future__ import annotations

import socket
import ssl
import time
import urllib.request
from urllib.error import HTTPError
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(slots=True)
class ProbeResult:
    ok: bool
    target: str
    latency_ms: float
    error: str = ""
    kind: str = "tls"
    cls: str = ""  # dns_fail | tcp_timeout | tls_fail | http_block | ok | ...


@dataclass(slots=True)
class ConnSample:
    remote_ip: str
    remote_port: int
    proto: str
    state: str
    pid: int
    process: str = ""
    domain: str = ""


_DISCORD_VOICE_UDP_PORTS = frozenset(range(19294, 19345)) | frozenset(range(50000, 50101))
_INTERESTING_UDP_PORTS = frozenset({3478, 3479, 3480, 5222, 5060, 5062, 443}) | _DISCORD_VOICE_UDP_PORTS


def is_interesting_udp_port(port: int) -> bool:
    try:
        value = int(port)
    except Exception:
        return False
    return value in _INTERESTING_UDP_PORTS


def _host_from_target(value: str) -> str:
    raw = (value or "").strip()
    if raw.upper().startswith("PING:"):
        raw = raw.split(":", 1)[1].strip()
    if "://" in raw:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
    else:
        host = raw.split("/", 1)[0]
        host = host.split(":", 1)[0]
    return host.strip("[]").lower().rstrip(".")


def probe_required_ok(results: list[ProbeResult], *, required_hosts: list[str] | None = None) -> bool:
    """Cutover gate: every required host must have at least one successful probe."""
    if not results:
        return False
    required = [_host_from_target(h) for h in (required_hosts or []) if h]
    required = [h for h in required if h]
    if not required:
        # No explicit host — require ALL probes ok (strict).
        return all(item.ok for item in results)
    by_host: dict[str, list[ProbeResult]] = {}
    for item in results:
        host = _host_from_target(item.target)
        if not host:
            continue
        by_host.setdefault(host, []).append(item)
        # Also match suffix.
        for req in required:
            if host == req or host.endswith("." + req) or req.endswith("." + host):
                by_host.setdefault(req, []).append(item)
    for req in required:
        matches = by_host.get(req) or []
        if not matches:
            # Fuzzy: any result whose target contains req
            matches = [item for item in results if req in _host_from_target(item.target)]
        if not matches or not any(item.ok for item in matches):
            return False
    return True


def _windows_no_window_kwargs() -> dict[str, Any]:
    """Ensure console helpers (netstat and similar) never flash a window."""
    import subprocess
    import sys

    if not sys.platform.startswith("win"):
        return {}
    kwargs: dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startup.wShowWindow = 0  # SW_HIDE
        kwargs["startupinfo"] = startup
    except Exception:
        pass
    return kwargs


class SignalCollector:
    def __init__(self) -> None:
        self._pid_cache: dict[int, str] = {}
        self._toolhelp_cache: dict[int, str] = {}
        self._toolhelp_at = 0.0

    def probe_https(self, url: str, timeout_s: float = 4.0) -> ProbeResult:
        started = time.perf_counter()
        try:
            request = urllib.request.Request(url, method="GET", headers={"User-Agent": "ZapretHub-Orchestrator/1.0"})
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                code = int(getattr(response, "status", 200) or 200)
                _ = response.read(64)
            if code >= 400:
                return ProbeResult(
                    ok=False,
                    target=url,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    error=f"http_{code}",
                    kind="http",
                    cls="http_block",
                )
            return ProbeResult(
                ok=True,
                target=url,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                kind="http",
                cls="ok",
            )
        except HTTPError as error:
            # A 4xx response proves DNS, TCP and TLS connectivity. Many service
            # gateways intentionally reject a generic orchestrator GET request.
            if 400 <= int(error.code) < 500:
                return ProbeResult(
                    ok=True,
                    target=url,
                    latency_ms=(time.perf_counter() - started) * 1000.0,
                    kind="http",
                    cls="ok",
                )
            cls = _classify_error(str(error), kind="http")
            return ProbeResult(
                ok=False,
                target=url,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error=str(error),
                kind="http",
                cls=cls,
            )
        except Exception as error:
            cls = _classify_error(str(error), kind="http")
            return ProbeResult(
                ok=False,
                target=url,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error=str(error),
                kind="http",
                cls=cls,
            )

    def probe_tls(self, host: str, port: int = 443, timeout_s: float = 3.5) -> ProbeResult:
        started = time.perf_counter()
        try:
            context = ssl.create_default_context()
            with socket.create_connection((host, port), timeout=timeout_s) as sock:
                with context.wrap_socket(sock, server_hostname=host) as tls:
                    tls.do_handshake()
            return ProbeResult(
                ok=True,
                target=f"{host}:{port}",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                cls="ok",
            )
        except Exception as error:
            cls = _classify_error(str(error), kind="tls")
            return ProbeResult(
                ok=False,
                target=f"{host}:{port}",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error=str(error),
                cls=cls,
            )

    def probe_host_access(self, host: str, *, timeout_s: float = 4.0) -> ProbeResult:
        """Production verdict: TLS handshake AND HTTPS GET must succeed."""
        host = _host_from_target(host)
        if not host:
            return ProbeResult(ok=False, target=host, latency_ms=0.0, error="empty_host", cls="dns_fail")
        tls = self.probe_tls(host, timeout_s=timeout_s)
        if not tls.ok:
            return tls
        http = self.probe_https(f"https://{host}/", timeout_s=timeout_s)
        if not http.ok:
            return http
        return ProbeResult(
            ok=True,
            target=host,
            latency_ms=tls.latency_ms + http.latency_ms,
            kind="tls+http",
            cls="ok",
        )

    def probe_targets(
        self,
        targets: list[dict[str, str]],
        *,
        timeout_s: float = 4.0,
        require_http: bool = True,
    ) -> list[ProbeResult]:
        results: list[ProbeResult] = []
        for item in targets:
            value = str(item.get("value") or item.get("url") or "").strip()
            if not value:
                continue
            if value.upper().startswith("PING:"):
                host = value.split(":", 1)[1].strip()
                results.append(self._probe_ping(host, timeout_s=timeout_s))
            elif value.startswith("https://") or value.startswith("http://"):
                if require_http and value.startswith("https://"):
                    host = _host_from_target(value)
                    results.append(self.probe_host_access(host, timeout_s=timeout_s))
                else:
                    results.append(self.probe_https(value, timeout_s=timeout_s))
            else:
                if require_http:
                    results.append(self.probe_host_access(value, timeout_s=timeout_s))
                else:
                    results.append(self.probe_tls(value, timeout_s=timeout_s))
        return results

    @staticmethod
    def _probe_ping(host: str, timeout_s: float = 2.0) -> ProbeResult:
        started = time.perf_counter()
        try:
            socket.getaddrinfo(host, None)
            with socket.create_connection((host, 80), timeout=timeout_s):
                pass
            return ProbeResult(
                ok=True,
                target=host,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                kind="ping",
                cls="ok",
            )
        except Exception as error:
            return ProbeResult(
                ok=False,
                target=host,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                error=str(error),
                kind="ping",
                cls=_classify_error(str(error), kind="tcp"),
            )

    def snapshot_connections(self, *, limit: int = 120, resolve_dns: bool = True) -> list[ConnSample]:
        try:
            import psutil  # type: ignore
        except Exception:
            samples = self._snapshot_windows_netstat(limit=limit)
        else:
            samples = self._snapshot_psutil(psutil, limit=limit)
            if not samples:
                samples = self._snapshot_windows_netstat(limit=limit)
        # Prefer failing / interesting states first; known apps before IDE noise.
        samples.sort(
            key=lambda s: (
                0 if (s.state or "").upper() in {"SYN_SENT", "SYN_RECEIVED"} else 1,
                0 if any(
                    marker in (s.process or "").lower().replace("\\", "/")
                    for marker in ("/discord", "/spotify", "/steam", "/epic", "/telegram", "discord", "spotify", "fortnite")
                )
                else 1,
                s.proto != "udp",
            )
        )
        if resolve_dns:
            self._enrich_domains(samples, max_lookups=max(8, min(48, limit // 4 or 8)))
        return samples[:limit]

    def _snapshot_psutil(self, psutil_mod: Any, *, limit: int) -> list[ConnSample]:
        priority: list[ConnSample] = []
        regular: list[ConnSample] = []
        try:
            for conn in psutil_mod.net_connections(kind="inet"):
                if not conn.raddr:
                    continue
                remote_ip = str(conn.raddr.ip)
                if remote_ip in {"127.0.0.1", "::1", "0.0.0.0"}:
                    continue
                pid = int(conn.pid or 0)
                process = self._process_name(pid, psutil_mod)
                proto = "udp" if conn.type == socket.SOCK_DGRAM else "tcp"
                state = str(getattr(conn, "status", "") or "")
                if proto == "tcp" and state.upper() not in {
                    "SYN_SENT",
                    "SYN_RECEIVED",
                    "ESTABLISHED",
                    "CLOSE_WAIT",
                    "",
                }:
                    continue
                sample = ConnSample(
                    remote_ip=remote_ip,
                    remote_port=int(conn.raddr.port),
                    proto=proto,
                    state=state,
                    pid=pid,
                    process=process,
                )
                blob = process.lower().replace("\\", "/")
                important = state.upper() in {"SYN_SENT", "SYN_RECEIVED"} or any(
                    marker in blob
                    for marker in (
                        "/discord",
                        "discord",
                        "/spotify",
                        "spotify",
                        "/steam",
                        "/epic",
                        "fortnite",
                        "/telegram",
                        "/battle.net",
                        "/riot",
                    )
                )
                if important:
                    priority.append(sample)
                else:
                    regular.append(sample)
                if len(priority) + len(regular) >= max(limit * 4, 240):
                    break
        except Exception:
            return []
        return [*priority, *regular]

    def _process_name(self, pid: int, psutil_mod: Any | None = None) -> str:
        if pid <= 0:
            return ""
        cached = self._pid_cache.get(pid)
        if cached is not None:
            return cached
        name = ""
        if psutil_mod is not None:
            try:
                proc = psutil_mod.Process(pid)
                # Prefer full path so Discord\\Update.exe maps to discord.
                try:
                    exe = str(proc.exe() or "").strip()
                except Exception:
                    exe = ""
                if exe:
                    name = exe
                else:
                    name = str(proc.name() or "")
            except Exception:
                name = ""
        if not name:
            # Prefer silent Toolhelp snapshot over spawning console process helpers.
            name = self._toolhelp_pid_names().get(pid, "")
        self._pid_cache[pid] = name
        if len(self._pid_cache) > 400:
            for key in list(self._pid_cache.keys())[:200]:
                self._pid_cache.pop(key, None)
        return name

    def _toolhelp_pid_names(self) -> dict[int, str]:
        import sys
        import time as time_mod

        if not sys.platform.startswith("win"):
            return {}
        now = time_mod.monotonic()
        if self._toolhelp_cache and (now - self._toolhelp_at) < 2.0:
            return self._toolhelp_cache
        mapping: dict[int, str] = {}
        try:
            import ctypes

            TH32CS_SNAPPROCESS = 0x00000002
            INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

            class PROCESSENTRY32W(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_wchar * 260),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if not snapshot or snapshot == INVALID_HANDLE_VALUE:
                return self._toolhelp_cache
            try:
                entry = PROCESSENTRY32W()
                entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
                if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                    return self._toolhelp_cache
                while True:
                    mapping[int(entry.th32ProcessID)] = str(entry.szExeFile or "")
                    if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                        break
            finally:
                kernel32.CloseHandle(snapshot)
        except Exception:
            return self._toolhelp_cache
        self._toolhelp_cache = mapping
        self._toolhelp_at = now
        return mapping

    def _enrich_domains(self, samples: list[ConnSample], *, max_lookups: int = 8) -> None:
        lookups = 0
        previous_timeout = socket.getdefaulttimeout()
        ordered = sorted(
            samples,
            key=lambda s: 0 if (s.state or "").upper() in {"SYN_SENT", "SYN_RECEIVED"} else 1,
        )
        try:
            socket.setdefaulttimeout(0.35)
            for sample in ordered:
                if sample.domain or lookups >= max_lookups:
                    continue
                state = (sample.state or "").upper()
                if state not in {"SYN_SENT", "SYN_RECEIVED"} and sample.remote_port not in {
                    443,
                    80,
                    5222,
                    3478,
                    2053,
                    2083,
                    2087,
                    2096,
                    8443,
                }:
                    continue
                try:
                    name, _aliases, _ips = socket.gethostbyaddr(sample.remote_ip)
                    sample.domain = str(name or "").lower().rstrip(".")
                    lookups += 1
                except Exception:
                    continue
        finally:
            socket.setdefaulttimeout(previous_timeout)

    def _snapshot_windows_netstat(self, *, limit: int = 80) -> list[ConnSample]:
        import subprocess
        import sys

        if not sys.platform.startswith("win"):
            return []
        samples: list[ConnSample] = []
        quiet = _windows_no_window_kwargs()
        pid_names = self._toolhelp_pid_names()
        for proto_flag, proto_name in (("tcp", "tcp"), ("udp", "udp")):
            try:
                completed = subprocess.run(
                    ["netstat", "-ano", "-p", proto_flag],
                    capture_output=True,
                    text=True,
                    timeout=2.5,
                    check=False,
                    **quiet,
                )
            except Exception:
                continue
            for line in completed.stdout.splitlines():
                parts = line.split()
                if not parts or parts[0].upper() != proto_flag.upper():
                    continue
                if proto_name == "tcp":
                    if len(parts) < 5:
                        continue
                    remote = parts[2]
                    state = parts[3]
                    try:
                        pid = int(parts[4])
                    except ValueError:
                        continue
                    if state.upper() not in {"SYN_SENT", "SYN_RECEIVED", "ESTABLISHED", "CLOSE_WAIT"}:
                        continue
                else:
                    if len(parts) < 4:
                        continue
                    remote = parts[2]
                    state = ""
                    try:
                        pid = int(parts[3])
                    except ValueError:
                        continue
                if ":" not in remote:
                    continue
                host, _, port_s = remote.rpartition(":")
                host = host.strip("[]")
                if host in {"127.0.0.1", "0.0.0.0", "*"}:
                    continue
                try:
                    port = int(port_s)
                except ValueError:
                    continue
                samples.append(
                    ConnSample(
                        remote_ip=host,
                        remote_port=port,
                        proto=proto_name,
                        state=state,
                        pid=pid,
                        process=self._process_name(pid),
                    )
                )
                if len(samples) >= limit:
                    return samples
        return samples


def _classify_error(error: str, *, kind: str) -> str:
    err = (error or "").lower()
    if "getaddrinfo" in err or "name or service not known" in err or "nodename" in err or "name resolution" in err:
        return "dns_fail"
    if "timed out" in err or "timeout" in err or "winerror 10060" in err:
        return "tcp_timeout" if kind in {"tcp", "tls", "ping"} else "http_block"
    if "ssl" in err or "certificate" in err or "handshake" in err or "eof occurred" in err:
        return "tls_fail"
    if kind == "http" or "http" in err or "403" in err or "451" in err or "redirect" in err:
        return "http_block"
    if "reset" in err or "connection refused" in err or "10054" in err:
        return "tcp_timeout"
    return "tcp_timeout"


def classify_failure(
    probe: ProbeResult,
    *,
    domain_in_lists: bool,
    coverage_miss: bool | None = None,
) -> str:
    """Honest classes for the tuner — never map 'in lists + timeout' to internal_conflict.

    Returns:
      dead_host | dns_fail | tcp_timeout | tls_fail | http_block |
      external_miss | suspect_overblock | ok
    """
    if probe.ok:
        return "ok"
    cls = (probe.cls or _classify_error(probe.error, kind=probe.kind)).strip() or "tcp_timeout"
    if cls == "dns_fail":
        return "dead_host"
    miss = coverage_miss if coverage_miss is not None else (not domain_in_lists)
    if miss:
        return "external_miss"
    # In lists but still failing — likely wrong general / over-desync, not "conflict".
    if cls in {"tls_fail", "http_block"}:
        return "suspect_overblock"
    if cls == "tcp_timeout":
        return "tcp_timeout"
    return cls


def collect_signals() -> dict:
    collector = SignalCollector()
    return {
        "connections": [item.__dict__ for item in collector.snapshot_connections(limit=40)],
        "probes": [],
        "dns": [],
    }
