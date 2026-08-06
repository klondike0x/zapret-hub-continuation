from __future__ import annotations

import argparse

from zapret_hub.workers import run_tg_ws_proxy_worker


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", choices=["tg-ws-proxy"], required=True)
    parser.add_argument("--tg-host", default="127.0.0.1")
    parser.add_argument("--tg-port", type=int, default=1443)
    parser.add_argument("--tg-secret", default="")
    parser.add_argument("--tg-verbose", action="store_true")
    parser.add_argument("--tg-dc-ip", action="append", default=[])
    parser.add_argument("--tg-cfproxy-enabled", default="true")
    parser.add_argument("--tg-cfproxy-priority", default="true")
    parser.add_argument("--tg-cfproxy-domain", default="")
    parser.add_argument("--tg-fake-tls-domain", default="")
    parser.add_argument("--tg-buf-kb", type=int, default=256)
    parser.add_argument("--tg-pool-size", type=int, default=4)
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--hub-token", default="")
    known, _ = parser.parse_known_args(argv)

    if known.worker == "tg-ws-proxy":
        return run_tg_ws_proxy_worker(
            host=known.tg_host,
            port=known.tg_port,
            secret=known.tg_secret,
            verbose=known.tg_verbose,
            dc_ip=list(known.tg_dc_ip or []),
            cfproxy_enabled=str(known.tg_cfproxy_enabled).lower() not in {"0", "false", "no", "off"},
            cfproxy_priority=str(known.tg_cfproxy_priority).lower() not in {"0", "false", "no", "off"},
            cfproxy_domain=known.tg_cfproxy_domain,
            fake_tls_domain=known.tg_fake_tls_domain,
            buf_kb=known.tg_buf_kb,
            pool_size=known.tg_pool_size,
        )
    raise SystemExit(2)

if __name__ == "__main__":
    raise SystemExit(main())

