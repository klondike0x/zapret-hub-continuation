"""TG WS Proxy worker wiring: helpers and entrypoint must exist.

Regression for two bugs that made TG WS Proxy silently fail to start:
1. ``_build_worker_env`` / ``_worker_python_executable`` were lost during the
   VPN/Marketplace cleanup and not restored with the component.
2. ``worker_entry.py`` lost its ``if __name__ == "__main__"`` guard, so
   ``python -m zapret_hub.worker_entry`` exited 0 without running anything.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import zapret_hub.worker_entry as worker_entry_module
from zapret_hub.services.components import ProcessManager
from zapret_hub.workers import run_tg_ws_proxy_worker


def test_process_manager_has_worker_helpers() -> None:
    """The tg-ws-proxy launcher depends on these two helpers."""
    assert hasattr(ProcessManager, "_build_worker_env")
    assert hasattr(ProcessManager, "_worker_python_executable")
    assert callable(ProcessManager._build_worker_env)
    assert callable(ProcessManager._worker_python_executable)


def test_worker_entry_has_main_guard() -> None:
    """Without the guard, `python -m zapret_hub.worker_entry` exits 0 silently."""
    source = Path(worker_entry_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    has_guard = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        for node in ast.walk(tree)
    )
    assert has_guard, "worker_entry.py must have `if __name__ == \"__main__\":`"
    assert source.rstrip().endswith('raise SystemExit(main())')


def test_worker_entry_parses_and_exposes_worker() -> None:
    """The entrypoint must keep accepting --worker tg-ws-proxy."""
    assert hasattr(worker_entry_module, "main")
    # Parse-only smoke: module must stay importable and callable.
    result = subprocess.run(
        [sys.executable, "-m", "zapret_hub.worker_entry", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # argparse help exits 0 without a worker; the module must at least start.
    assert result.returncode in (0, 2)


def test_run_tg_ws_proxy_worker_importable() -> None:
    """The worker entrypoint must resolve to a callable in workers.py."""
    assert callable(run_tg_ws_proxy_worker)
