"""Compare live performance vs backtest baseline — alert on drift."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# 6-year VOL_REGIME ATR2.5_RR0.8 backtest baseline
BASELINE_PF = 1.43
BASELINE_WIN_RATE = 0.52
BASELINE_AVG_R = 0.15
MIN_TRADES = 10


def _closed_bot_deals(config: dict[str, Any], *, days: int = 14) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        import MetaTrader5 as mt5

        from tradingbot.adapters.mt5_utils import attach_mt5_session

        if not attach_mt5_session(config, strict_account=False, use_lock=False):
            return rows
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        deals = mt5.history_deals_get(start, end)
        if not deals:
            return rows
        for d in deals:
            if int(getattr(d, "magic", 0) or 0) != 234000:
                continue
            if int(getattr(d, "entry", 0)) != 1:
                continue
            rows.append(
                {
                    "profit": float(getattr(d, "profit", 0.0)),
                    "time": datetime.fromtimestamp(int(d.time), tz=timezone.utc).isoformat(),
                }
            )
    except Exception:
        pass
    return rows


def compute_drift_report(base_dir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    deals = _closed_bot_deals(config)
    wins = sum(1 for d in deals if d["profit"] > 0)
    losses = sum(1 for d in deals if d["profit"] < 0)
    n = len(deals)
    gross_win = sum(d["profit"] for d in deals if d["profit"] > 0)
    gross_loss = abs(sum(d["profit"] for d in deals if d["profit"] < 0))
    live_pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    win_rate = (wins / n) if n else 0.0

    pf_drift = (live_pf / BASELINE_PF - 1.0) if BASELINE_PF > 0 and n >= MIN_TRADES else 0.0
    wr_drift = win_rate - BASELINE_WIN_RATE if n >= MIN_TRADES else 0.0

    alerts: list[str] = []
    status = "insufficient_data"
    if n >= MIN_TRADES:
        status = "ok"
        if live_pf < 1.0:
            alerts.append(f"live PF {live_pf:.2f} below 1.0")
            status = "warn"
        if live_pf < BASELINE_PF * 0.7:
            alerts.append(f"live PF {live_pf:.2f} far below backtest {BASELINE_PF}")
            status = "critical"
        if wr_drift < -0.15:
            alerts.append(f"win rate {win_rate:.0%} vs baseline {BASELINE_WIN_RATE:.0%}")
            status = "warn" if status == "ok" else status

    from tradingbot.services.live_reporting import journal_summary

    j = journal_summary(base_dir, day=datetime.now(timezone.utc))
    slip_avg = j.get("slippage_avg_pips")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": {
            "pf": BASELINE_PF,
            "win_rate": BASELINE_WIN_RATE,
            "avg_r": BASELINE_AVG_R,
        },
        "live_window_days": 14,
        "live_trades": n,
        "live_wins": wins,
        "live_losses": losses,
        "live_pf": round(live_pf, 3) if live_pf < 900 else None,
        "live_win_rate": round(win_rate, 4),
        "pf_drift_pct": round(pf_drift * 100, 1) if n >= MIN_TRADES else None,
        "slippage_avg_pips_today": slip_avg,
        "status": status,
        "alerts": alerts,
    }
    out = Path(base_dir) / "logs" / "drift_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def format_drift_telegram(report: dict[str, Any]) -> str:
    lines = [
        "TradingBot drift monitor",
        f"Status: {report.get('status')}",
        f"Live trades (14d): {report.get('live_trades')} PF={report.get('live_pf')} WR={report.get('live_win_rate')}",
        f"Baseline PF={report.get('baseline', {}).get('pf')} WR={report.get('baseline', {}).get('win_rate')}",
        f"Slippage today avg: {report.get('slippage_avg_pips_today', '-')} pips",
    ]
    for a in report.get("alerts") or []:
        lines.append(f"! {a}")
    return "\n".join(lines)
