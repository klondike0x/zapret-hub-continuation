"""Elevated smoke test: materialize + start Zapret1 / Zapret2 against live work root."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULT = Path(os.environ.get("ZAPRET_HUB_SMOKE_RESULT", str(REPO / "logs" / "pipeline_smoke_result.json")))


def main() -> int:
    work = Path(os.environ.get("ZAPRET_HUB_WORK_ROOT", r"C:\Users\User\AppData\Local\Zapret_Hub")).resolve()
    os.environ["ZAPRET_HUB_WORK_ROOT"] = str(work)
    sys.path.insert(0, str(REPO / "src"))

    report: dict = {
        "admin": False,
        "work_root": str(work),
        "blob_ok": False,
        "zapret1": {},
        "zapret2": {},
        "errors": [],
    }
    try:
        import ctypes

        report["admin"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception as exc:
        report["errors"].append(f"admin_check:{exc}")

    try:
        from zapret_hub.bootstrap import bootstrap_application
        from zapret_hub.services.orchestrator import zapret2_hub

        ctx = bootstrap_application()
        cm = ctx.processes

        # --- Zapret2 command dry-check (blob syntax) ---
        runtime_root = cm._ensure_zapret2_runtime()
        winws2 = cm._find_zapret2_winws(runtime_root)
        if winws2 is None:
            raise FileNotFoundError("winws2.exe missing")
        cmd2 = cm._build_zapret2_command(winws2, runtime_root)
        blobs = [a for a in cmd2 if a.startswith("--blob=")]
        bad = [b for b in blobs if "=@" in b.split(":", 1)[0] or not (":@" in b)]
        # Correct form: --blob=name:@/cygdrive/...
        ok_blobs = [b for b in blobs if ":@" in b and "/cygdrive/" in b]
        report["blob_ok"] = bool(blobs) and not bad and bool(ok_blobs)
        report["zapret2"]["blob_sample"] = blobs[:6]
        report["zapret2"]["blob_bad"] = bad
        report["zapret2"]["cmd_len"] = len(cmd2)

        # Remember mode; restore at end.
        prev_mode = str(ctx.settings.get().selected_runtime_mode or "zapret")
        report["prev_mode"] = prev_mode

        # Stop both first
        for cid in ("zapret2", "zapret"):
            try:
                cm.stop_component(cid)
            except Exception:
                pass
        time.sleep(0.8)

        # --- Zapret1 start (mode=zapret) ---
        ctx.settings.update(selected_runtime_mode="zapret")
        t0 = time.time()
        st1 = cm.start_component("zapret")
        time.sleep(4.0)  # cover confirm window (~3.6s)
        st1b = cm._states.get("zapret")
        proc1 = cm._processes.get("zapret")
        alive1 = proc1 is not None and proc1.poll() is None
        img1 = cm._is_image_running("winws.exe")
        active_bins = sorted(
            work.glob("merged_runtime/active_zapret_*/bin/ACTIVE_DISCORD_UDP.bin"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        report["zapret1"] = {
            "status_immediate": getattr(st1, "status", None),
            "error_immediate": getattr(st1, "last_error", None),
            "status_after": getattr(st1b, "status", None) if st1b else None,
            "error_after": getattr(st1b, "last_error", None) if st1b else None,
            "popen_alive": alive1,
            "image_running": img1,
            "active_discord_present": bool(active_bins),
            "active_discord_path": str(active_bins[0]) if active_bins else None,
            "elapsed_s": round(time.time() - t0, 2),
        }
        zlog = work / "logs" / "zapret.log"
        if zlog.is_file():
            report["zapret1"]["log_tail"] = zlog.read_text(encoding="utf-8", errors="replace")[-800:]

        # Stop zapret before zapret2 (exclusive WinDivert)
        try:
            cm.stop_component("zapret")
        except Exception:
            pass
        time.sleep(1.2)

        # --- Zapret2 start (mode=zapret2) ---
        ctx.settings.update(selected_runtime_mode="zapret2")
        t0 = time.time()
        st2 = cm.start_component("zapret2")
        time.sleep(4.0)
        st2b = cm._states.get("zapret2")
        proc2 = cm._processes.get("zapret2")
        alive2 = proc2 is not None and proc2.poll() is None
        img2 = cm._is_image_running("winws2.exe")
        z2log = work / "logs" / "zapret2.log"
        log_tail2 = z2log.read_text(encoding="utf-8", errors="replace")[-1200:] if z2log.is_file() else ""
        app_log = work / "logs" / "app.log"
        app_tail = app_log.read_text(encoding="utf-8", errors="replace")[-1500:] if app_log.is_file() else ""
        report["zapret2"].update(
            {
                "status_immediate": getattr(st2, "status", None),
                "error_immediate": getattr(st2, "last_error", None),
                "status_after": getattr(st2b, "status", None) if st2b else None,
                "error_after": getattr(st2b, "last_error", None) if st2b else None,
                "popen_alive": alive2,
                "image_running": img2,
                "log_tail": log_tail2,
                "app_tail": app_tail,
                "elapsed_s": round(time.time() - t0, 2),
            }
        )

        # Cleanup + restore mode
        for cid in ("zapret2", "zapret"):
            try:
                cm.stop_component(cid)
            except Exception:
                pass
        try:
            ctx.settings.update(selected_runtime_mode=prev_mode)
        except Exception:
            pass

        report["ok"] = bool(
            report["admin"]
            and report["blob_ok"]
            and report["zapret1"].get("popen_alive")
            and report["zapret1"].get("image_running")
            and report["zapret1"].get("active_discord_present")
            and report["zapret1"].get("status_after") == "running"
            and report["zapret2"].get("popen_alive")
            and report["zapret2"].get("image_running")
            and report["zapret2"].get("status_after") == "running"
        )
    except Exception as exc:
        report["errors"].append(repr(exc))
        report["ok"] = False
        import traceback

        report["traceback"] = traceback.format_exc()

    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": report.get("ok"), "result": str(RESULT)}, ensure_ascii=False))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
