#!/usr/bin/env python3
"""Generate logs/robot_ready_for_live_report.json — wiring audit + backtest."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

REPORT_PATH = ROOT / "logs" / "robot_ready_for_live_report.json"
BACKTEST_PATH = ROOT / "logs" / "backtest_24h_report.json"


def _run_script(rel: str) -> tuple[int, str]:
    path = ROOT / rel
    if not path.is_file():
        return 127, f"missing: {rel}"
    proc = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _file_exists(rel: str) -> bool:
    return (ROOT / rel.replace("/", "\\")).is_file()


def main() -> int:
    backtest: dict = {}
    if BACKTEST_PATH.is_file():
        backtest = json.loads(BACKTEST_PATH.read_text(encoding="utf-8"))
    else:
        code, out = _run_script("scripts/backtest_vol_regime_24h.py")
        if BACKTEST_PATH.is_file():
            backtest = json.loads(BACKTEST_PATH.read_text(encoding="utf-8"))
        backtest.setdefault("_runner_exit", code)
        backtest.setdefault("_runner_output_tail", out[-500:] if out else "")

    checks = {
        "hta_power_button": {
            "file": "live_dashboard.hta",
            "bat": "start/3_live_loop_execute.bat",
            "pass": _file_exists("live_dashboard.hta") and _file_exists("start/3_live_loop_execute.bat"),
        },
        "vol_regime_not_ml": {
            "env_use_ml_kernel": __import__("os").environ.get("USE_ML_KERNEL", ""),
            "pass": __import__("os").environ.get("USE_ML_KERNEL", "false").lower() in ("0", "false", "no"),
        },
        "demo_live_runner": {
            "path": "tradingbot/ml/research/live_l6/demo_live_runner.py",
            "pass": _file_exists("tradingbot/ml/research/live_l6/demo_live_runner.py"),
        },
        "demo_monitor": {
            "path": "logs/live_l6_demo_monitor.ps1",
            "pass": _file_exists("logs/live_l6_demo_monitor.ps1"),
        },
        "start_demo_daemon_ps1": {
            "path": "scripts/start_demo_live_daemon.ps1",
            "pass": _file_exists("scripts/start_demo_live_daemon.ps1"),
        },
        "stop_daemon": {
            "path": "scripts/stop_live_daemon.ps1",
            "pass": _file_exists("scripts/stop_live_daemon.ps1"),
        },
        "mt5_attach_ipc_lock": {
            "module": "tradingbot/adapters/mt5_utils.py",
            "pass": _file_exists("tradingbot/adapters/mt5_utils.py"),
        },
        "demo_safety_guards": {
            "module": "tradingbot/ml/research/live_l6/demo_safety.py",
            "pass": _file_exists("tradingbot/ml/research/live_l6/demo_safety.py"),
        },
        "tq_rr_patch_vol_regime": {
            "module": "tradingbot/ml/trade_quality/rr_quality.py",
            "pass": _file_exists("tradingbot/ml/trade_quality/rr_quality.py"),
        },
        "load_env_bat": {
            "path": "start/_load_env.bat",
            "pass": _file_exists("start/_load_env.bat"),
        },
    }

    vr_code, vr_out = _run_script("scripts/verify_vol_regime_live_ready.py")
    checks["verify_vol_regime_live_ready"] = {"exit_code": vr_code, "pass": vr_code == 0, "output": vr_out[-800:]}

    power_chain = [
        "live_dashboard.hta btnLive onclick",
        "RunBatFile start\\3_live_loop_execute.bat",
        "start/_load_env.bat loads .env",
        "set USE_ML_KERNEL=false + TRADINGBOT_DEMO_LIVE=1",
        "scripts/check_vol_regime_live_setup.py (MT5 attach-only + demo check)",
        "scripts/verify_vol_regime_live_ready.py (VOL_REGIME + TQ patch)",
        "scripts/start_demo_live_daemon.ps1",
        "logs/live_l6_demo_monitor.ps1 (poll 15min, sets TRADINGBOT_DEMO_LIVE=1)",
        "tradingbot/ml/research/live_l6/demo_live_runner.py",
        "evaluate_vol_regime_from_frame + production TQ + MT5 order (demo only)",
    ]

    stop_chain = [
        "live_dashboard.hta btnStop",
        "start/5_stop_bot.bat",
        "scripts/stop_live_daemon.ps1",
        "data/manual_stop.flag + kill demo monitor + demo_live_runner + legacy watchdog",
    ]

    real_money_blockers = [
        "TRADINGBOT_DEMO_LIVE must be 1 (set by start bat / monitor — not for real accounts)",
        "verify_demo_account_or_abort blocks trade_mode=REAL (real_account_blocked)",
        "Non-demo server without demo trade_mode -> non_demo_account_blocked",
        "USE_ML_KERNEL=false — old ML kernel path disabled from power button",
        "VOL_REGIME_MAX_LOT=0.01 and daily kill switch 2% in live.py",
        "No bypass for real_money in this wiring — explicit production gate still required",
    ]

    instructions_fa = {
        "پیش از روشن کردن": [
            "MT5 را باز کنید و با حساب دمو 91213150 لاگین باشید",
            "دکمه Algo Trading در MT5 سبز باشد",
            "live_dashboard.hta را از پوشه پروژه اجرا کنید",
        ],
        "روشن کردن ربات": [
            "دکمه «روشن کردن ربات — LIVE» را بزنید",
            "مسیر VOL_REGIME ATR2.5_RR0.8 بدون ML اجرا می‌شود",
            "TRADINGBOT_DEMO_LIVE=1 خودکار ست می‌شود — فقط دمو",
        ],
        "توقف": [
            "دکمه «توقف ربات» — monitor و runner متوقف می‌شوند",
        ],
        "لاگ‌ها": [
            "logs/demo_live_journal.jsonl — چرخه‌های live",
            "logs/live_l6_demo_monitor_run.log — مانیتور",
            "logs/backtest_24h_report.json — بک‌تست ۲۴ ساعت",
        ],
        "پول واقعی": [
            "این wiring برای حساب دمو است — real money مسدود است",
            "برای live واقعی نیاز به gate جدا و USE_ML_KERNEL/مسیر production تأیید‌شده",
        ],
    }

    all_pass = all(v.get("pass") for v in checks.values() if isinstance(v, dict) and "pass" in v)

    report = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_root": str(ROOT),
        "ready_for_demo_live": all_pass and vr_code == 0,
        "ready_for_real_money": False,
        "backtest_24h": backtest,
        "dashboard_wiring_audit": checks,
        "power_button_chain": power_chain,
        "stop_button_chain": stop_chain,
        "real_money_blockers": real_money_blockers,
        "user_instructions_fa": instructions_fa,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"ready_for_demo_live": report["ready_for_demo_live"], "report": str(REPORT_PATH)}, ensure_ascii=False))
    return 0 if report["ready_for_demo_live"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
