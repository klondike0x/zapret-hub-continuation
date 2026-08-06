from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import logging.handlers
import socket as _socket
import struct
import sys
import traceback
from collections import deque
from datetime import datetime
from pathlib import Path

# эти импорты нужны nuitka, иначе tg-ws-proxy вспоминает о них только при запуске
from cryptography.hazmat.primitives.ciphers import Cipher as _Cipher
from cryptography.hazmat.primitives.ciphers import algorithms as _algorithms
from cryptography.hazmat.primitives.ciphers import modes as _modes
from zapret_hub.runtime_env import development_install_root, is_packaged_runtime, packaged_install_root, packaged_resource_root


def run_tg_ws_proxy_worker(
    host: str,
    port: int,
    secret: str,
    verbose: bool = False,
    dc_ip: list[str] | None = None,
    cfproxy_enabled: bool = True,
    cfproxy_priority: bool = True,
    cfproxy_domain: str = "",
    fake_tls_domain: str = "",
    buf_kb: int = 256,
    pool_size: int = 4,
) -> int:
    if is_packaged_runtime():
        install_root = packaged_install_root()
        resource_root = packaged_resource_root()
    else:
        install_root = development_install_root(__file__)
        resource_root = install_root
    tg_repo = install_root / "runtime" / "tg-ws-proxy"
    if not tg_repo.exists():
        bundled_repo = resource_root / "runtime" / "tg-ws-proxy"
        if bundled_repo.exists():
            tg_repo = bundled_repo
    if not tg_repo.exists():
        print(f"tg-ws-proxy runtime directory not found: {tg_repo}", file=sys.stderr)
        return 2

    proxy_pkg_root = str(tg_repo)
    if proxy_pkg_root not in sys.path:
        sys.path.insert(0, proxy_pkg_root)

    try:
        from proxy import tg_ws_proxy
    except Exception as error:
        _write_worker_error(
            install_root,
            f"Failed to import tg-ws-proxy worker: {error}\n{traceback.format_exc()}",
            "tg_worker_error.log",
        )
        return 3

    force_empty_dc_map = list(dc_ip or []) == ["__empty__"]
    if force_empty_dc_map:
        try:
            tg_ws_proxy.parse_dc_ip_list = lambda _items: {}  # type: ignore[attr-defined]
        except Exception:
            pass

    argv = ["tg-ws-proxy", "--host", host, "--port", str(port)]
    if secret:
        argv.extend(["--secret", secret])
    for item in dc_ip or []:
        item = str(item).strip()
        if item and item != "__empty__":
            argv.extend(["--dc-ip", item])
    if force_empty_dc_map:
        argv.extend(["--dc-ip", "__empty__"])
    if not cfproxy_enabled:
        argv.append("--no-cfproxy")
    if cfproxy_domain.strip():
        argv.extend(["--cfproxy-domain", cfproxy_domain.strip()])
    if fake_tls_domain.strip():
        argv.extend(["--fake-tls-domain", fake_tls_domain.strip()])
    argv.extend(["--buf-kb", str(max(4, int(buf_kb or 256)))])
    argv.extend(["--pool-size", str(max(0, int(pool_size or 4)))])
    if verbose:
        argv.append("--verbose")

    prev_argv = sys.argv
    try:
        sys.argv = argv
        try:
            tg_ws_proxy.main()
        except Exception as error:
            _write_worker_error(
                install_root,
                f"Worker crashed: {error}\n{traceback.format_exc()}",
                "tg_worker_error.log",
            )
            return 4
    finally:
        sys.argv = prev_argv
    return 0
def _resolve_install_root() -> Path:
    if is_packaged_runtime():
        return packaged_install_root()
    return development_install_root(__file__)


def _write_worker_error(install_root: Path, message: str, filename: str) -> None:
    try:
        logs = install_root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        path = logs / filename
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.utcnow().isoformat()}] {message}\n")
    except Exception:
        pass
