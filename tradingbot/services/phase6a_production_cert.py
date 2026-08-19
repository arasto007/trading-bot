"""Phase 6A — final production certification orchestrator."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase26b.analyzers import _profit_factor

ROOT = Path(__file__).resolve().parents[2]
PHASE6A_DIR = ROOT / "logs" / "phase6a"
RESULT_PATH = ROOT / "logs" / "phase6a_final_result.txt"
ARTIFACT_PATH = PHASE6A_DIR / "phase6a_certification.json"

FORWARD_TARGET_DAYS = 30
FORWARD_MIN_TRADES = 20
FORWARD_PF_GATE = 1.5
FORWARD_EXP_GATE = 0.30
FORWARD_MAX_DD_GATE = 5.0
WF_PF_GATE = 1.3
MC_PF_GATE = 1.2


def is_phase6a_forward_enabled() -> bool:
    return os.getenv("PHASE6A_FORWARD_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


def required_config() -> dict[str, bool]:
    from tradingbot.config.live import get_live_config
    from tradingbot.ml.integration.config import is_ml_kernel_enabled, is_ml_shadow_enabled

    live = get_live_config()
    return {
        "PA_PRODUCTION_LOCK": bool(live.get("PA_PRODUCTION_LOCK", True)),
        "VOL_REGIME_ENABLED": bool(live.get("VOL_REGIME_ENABLED", False)),
        "ADAPTIVE_REGIME_ENABLED": bool(live.get("ADAPTIVE_REGIME_ENABLED", False)),
        "USE_ML_KERNEL": is_ml_kernel_enabled(),
        "ENABLE_ML_SHADOW": is_ml_shadow_enabled(),
        "PHASE52A_PM": os.getenv("PHASE52A_PM", "false").lower() in ("1", "true", "yes"),
        "META_ACTIVE": float(live.get("META_LABEL_THRESHOLD", 0)) > 0,
    }


def config_ok(cfg: dict[str, bool]) -> bool:
    return (
        cfg["PA_PRODUCTION_LOCK"]
        and cfg["META_ACTIVE"]
        and not cfg["VOL_REGIME_ENABLED"]
        and not cfg["ADAPTIVE_REGIME_ENABLED"]
        and not cfg["USE_ML_KERNEL"]
        and cfg["ENABLE_ML_SHADOW"]
        and not cfg["PHASE52A_PM"]
    )


def collect_forward_metrics(config: dict[str, Any]) -> dict[str, Any]:
    """Roll up Phase 51A/6A forward demo trades (shared log path)."""
    from tradingbot.services.phase51a_forward_cert import (
        EVENTS_PATH,
        TRADES_PATH,
        _completed_trades,
        _read_jsonl,
        collect_daily_report,
        forward_start_date,
        save_daily_report,
    )

    start = forward_start_date()
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    daily: list[dict[str, Any]] = []

    if start:
        from datetime import timedelta

        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        for offset in range(FORWARD_TARGET_DAYS):
            day = start_dt + timedelta(days=offset)
            if day > today:
                break
            try:
                report = collect_daily_report(config, day=day)
                save_daily_report(report)
                daily.append(report)
            except Exception:
                daily.append({"date": day.strftime("%Y-%m-%d"), "skipped": True})

    trades = _completed_trades(since_start=True)
    executed = len(trades)
    rs = [float((t.get("exit") or {}).get("pnl_R", 0)) for t in trades]
    pnls = [float((t.get("exit") or {}).get("pnl_usd", 0)) for t in trades]
    pf = _profit_factor([{"pnl": p} for p in pnls]) if pnls else 0.0
    exp_r = sum(rs) / len(rs) if rs else 0.0

    equity = 200.0
    peak = cur = equity
    max_dd_pct = 0.0
    for t in sorted(trades, key=lambda x: (x.get("exit") or {}).get("timestamp", "")):
        cur += float((t.get("exit") or {}).get("pnl_usd", 0))
        peak = max(peak, cur)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, (peak - cur) / peak * 100.0)

    runtime_critical = order_fails = abnormal = 0
    for row in _read_jsonl(EVENTS_PATH):
        ev = row.get("event")
        if ev == "runtime_error":
            runtime_critical += 1
        elif ev == "order_send_failure":
            order_fails += 1
    from tradingbot.services.phase47c_forward_tracker import _count_abnormal_stops

    if start:
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = today + __import__("datetime").timedelta(days=1)
        abnormal = _count_abnormal_stops(start_dt, end_dt)

    pf_num = float(pf) if pf not in ("inf", float("inf")) else 999.0
    forward_days = len(daily)
    window_complete = forward_days >= FORWARD_TARGET_DAYS

    return {
        "start_date": start,
        "forward_days": forward_days,
        "target_days": FORWARD_TARGET_DAYS,
        "window_complete": window_complete,
        "executed_trades": executed,
        "forward_pf": round(pf_num, 3) if pf_num != 999.0 else "inf",
        "forward_expectancy_R": round(exp_r, 3),
        "forward_max_dd_pct": round(max_dd_pct, 4),
        "runtime_critical_errors": runtime_critical,
        "order_send_failures": order_fails,
        "abnormal_stop_events": abnormal,
        "daily_reports": daily,
        "trades_path": str(TRADES_PATH),
        "trades_path_exists": TRADES_PATH.is_file(),
    }


def _load_cached_pa_trades(df: pd.DataFrame) -> list[dict[str, Any]] | None:
    cache = ROOT / "logs" / "phase5a_pa_trades.json"
    if not cache.is_file():
        return None
    try:
        import json

        rows = json.loads(cache.read_text(encoding="utf-8"))
        return rows if rows else None
    except Exception:
        return None


def run_offline_tests(df: Any) -> dict[str, Any]:
    from tradingbot.ml.research.phase6a.fault_injection_live import run_fault_injection_suite
    from tradingbot.ml.research.phase6a.monte_carlo_pa import run_monte_carlo_r
    from tradingbot.ml.research.phase6a.walk_forward_pa import _collect_pa_meta_trades, run_walk_forward
    from logs.phase_c_meta_resurrection import apply_meta_filter
    from tradingbot.services.meta_labeler import get_meta_labeler

    cached = _load_cached_pa_trades(df)
    if cached is not None:
        meta = get_meta_labeler()
        kept, _ = apply_meta_filter(cached, df, meta, threshold=0.38, fp=None)
    else:
        kept = _collect_pa_meta_trades(df)
    wf = run_walk_forward(df, n_windows=6, window_days=30, all_trades=kept)
    rs = [float(t["r_multiple"]) for t in kept]
    mc = run_monte_carlo_r(rs, simulations=10_000)
    faults = run_fault_injection_suite()
    return {
        "walk_forward": wf,
        "monte_carlo": mc,
        "fault_injection": faults,
        "pa_meta_trades_backtest": len(kept),
    }


def evaluate_certification(
    config: dict[str, Any],
    *,
    df: Any | None = None,
    skip_offline: bool = False,
) -> dict[str, Any]:
    cfg_flags = required_config()
    forward = collect_forward_metrics(config)
    offline = {} if skip_offline else run_offline_tests(df)

    wf_median = float((offline.get("walk_forward") or {}).get("median_pf", 0))
    mc_median = float((offline.get("monte_carlo") or {}).get("pf_median", 0))

    pf_fwd = forward.get("forward_pf", 0)
    pf_num = float(pf_fwd) if pf_fwd not in ("inf", float("inf")) else 999.0

    gates = {
        "config_ok": config_ok(cfg_flags),
        "forward_trades": forward["executed_trades"] >= FORWARD_MIN_TRADES,
        "forward_pf": pf_num > FORWARD_PF_GATE,
        "forward_expectancy": float(forward["forward_expectancy_R"]) > FORWARD_EXP_GATE,
        "forward_max_dd": float(forward["forward_max_dd_pct"]) < FORWARD_MAX_DD_GATE,
        "walk_forward_pf": wf_median > WF_PF_GATE,
        "monte_carlo_pf": mc_median > MC_PF_GATE,
        "runtime_errors_zero": forward["runtime_critical_errors"] == 0,
        "abnormal_stops_zero": forward["abnormal_stop_events"] == 0,
        "order_failures_zero": forward["order_send_failures"] == 0,
        "fault_injection": (offline.get("fault_injection") or {}).get("all_passed", False),
        "forward_window_complete": forward["window_complete"],
    }

    certified = all(gates.values())

    return {
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "config": cfg_flags,
        "forward": forward,
        "offline": offline,
        "gates": gates,
        "production_certified": certified,
        "real_account_ready": certified,
    }


def format_phase6a_result(report: dict[str, Any]) -> str:
    fwd = report.get("forward", {})
    offline = report.get("offline", {})
    wf = offline.get("walk_forward", {})
    mc = offline.get("monte_carlo", {})
    lines = [
        "PHASE_6A_RESULT",
        f"FORWARD_TRADES={fwd.get('executed_trades', 0)}",
        f"FORWARD_PF={fwd.get('forward_pf', 0)}",
        f"FORWARD_EXPECTANCY_R={fwd.get('forward_expectancy_R', 0)}",
        f"FORWARD_MAX_DD_PCT={fwd.get('forward_max_dd_pct', 0)}",
        f"WF_MEDIAN_PF={wf.get('median_pf', 0)}",
        f"MONTE_CARLO_MEDIAN_PF={mc.get('pf_median', 0)}",
        f"RUNTIME_CRITICAL_ERRORS={fwd.get('runtime_critical_errors', 0)}",
        f"ABNORMAL_STOP_EVENTS={fwd.get('abnormal_stop_events', 0)}",
        f"ORDER_SEND_FAILURES={fwd.get('order_send_failures', 0)}",
        f"PRODUCTION_CERTIFIED={'YES' if report.get('production_certified') else 'NO'}",
        f"REAL_ACCOUNT_READY={'YES' if report.get('real_account_ready') else 'NO'}",
    ]
    return "\n".join(lines)


def write_artifacts(report: dict[str, Any]) -> tuple[Path, Path]:
    PHASE6A_DIR.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    text = format_phase6a_result(report)
    RESULT_PATH.write_text(text + "\n", encoding="utf-8")
    return RESULT_PATH, ARTIFACT_PATH
