#!/usr/bin/env python3
"""Phase 34A — RAW ML Truth Audit (read-only forensic)."""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase34a" / ".cache"
BALANCE = 200.0
RISK_PCT = 0.5


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    c = df.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    return c.sort_index()


def _load_cache(name: str) -> dict | None:
    p = CACHE_DIR / f"{name}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save_cache(name: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{name}.json").write_text(json.dumps(payload, default=str), encoding="utf-8")


def _regime_bucket(regime: str, vol_state: str) -> str:
    r = regime.upper()
    if r == "HIGH_VOLATILITY":
        return "HIGH_VOL"
    if vol_state == "HIGH_VOL":
        return "HIGH_VOL"
    if vol_state == "LOW_VOL":
        return "LOW_VOL"
    if r in ("TREND", "RANGE"):
        return r
    return r


async def run_audit(*, use_cache: bool = True) -> dict:
    from tradingbot.ml.research.phase22f.config import build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest
    from tradingbot.ml.research.phase34a.collector import collect_raw_ml_signals
    from tradingbot.ml.research.phase34a.metrics import (
        classify_ml_quality,
        confidence_bucket,
        stats_from_replays,
    )
    from tradingbot.ml.research.phase33d.replay import replay_with_production_sl_tp

    configure_research_env()
    ds = build_dataset("A")

    print("Collecting raw ML signals (every bar)...", flush=True)
    collected = _load_cache("raw_signals_m5_a") if use_cache else None
    force = __import__("os").environ.get("PHASE34A_FORCE", "")
    if force.lower() in ("1", "true", "yes"):
        collected = None
    if collected is None:
        collected = await collect_raw_ml_signals(ds, timeframe="M5")
        _save_cache("raw_signals_m5_a", collected)

    signals = collected.get("signals") or []
    ohlcv = _prepare(await load_ohlcv_for_dataset(ds, "M5"))

    print(f"Replaying {len(signals)} raw ML signals...", flush=True)
    replays: list[dict] = []
    for sig in signals:
        idx = int(sig["bar_index"])
        direction = sig["direction"]
        replay = replay_with_production_sl_tp(
            ohlcv,
            idx,
            direction=direction,
            confidence=float(sig.get("confidence") or 0.55),
            spread_pips=float(sig.get("spread_pips") or 3.0),
        )
        replays.append({**sig, **replay})

    raw_stats = stats_from_replays(replays, initial_balance=BALANCE, risk_pct=RISK_PCT)

    print("Loading executed trades from production-path backtest...", flush=True)
    bt = _load_cache("backtest_m5_a") if use_cache else None
    if bt is None:
        bt = await run_rapid_backtest("M5", ds, blocked_events_limit=None)
        _save_cache("backtest_m5_a", bt)

    executed_replays: list[dict] = []
    for t in bt.get("trades_detail") or []:
        actual_r = float(t.get("r_multiple") or 0)
        executed_replays.append({
            "timestamp": t.get("entry_time"),
            "direction": t.get("side", "BUY"),
            "r_multiple": actual_r,
            "would_win": actual_r > 0,
            "would_lose": actual_r < 0,
            "actual_pnl": t.get("pnl"),
            "exit_reason": "production",
        })

    exec_stats = stats_from_replays(executed_replays, initial_balance=BALANCE, risk_pct=RISK_PCT)

    # Confidence buckets
    buckets: dict[str, list] = defaultdict(list)
    for r in replays:
        buckets[confidence_bucket(float(r.get("confidence") or 0))].append(r)
    bucket_order = ["<0.40"] + [f"{0.40 + i * 0.05:.2f}-{0.45 + i * 0.05:.2f}" for i in range(11)] + ["0.95-1.00"]
    confidence_report = {}
    for b in bucket_order:
        items = buckets.get(b, [])
        if not items:
            continue
        confidence_report[b] = stats_from_replays(items, initial_balance=BALANCE, risk_pct=RISK_PCT)

    # Regime performance
    regime_groups: dict[str, list] = defaultdict(list)
    for r in replays:
        key = _regime_bucket(str(r.get("regime", "")), str(r.get("volatility_state", "NORMAL")))
        regime_groups[key].append(r)
    regime_perf = {k: stats_from_replays(v, initial_balance=BALANCE, risk_pct=RISK_PCT) for k, v in regime_groups.items()}

    # Filter edge loss
    filter_names = [
        "AdaptiveRisk", "TradeQuality", "RSI Filter", "ADX Filter",
        "ProfitabilityFilters", "KernelInternal", "RiskGate",
    ]
    filter_edge: dict[str, dict] = {}
    raw_pf = float(raw_stats["profit_factor"])
    for filt in filter_names:
        passed = [r for r in replays if r.get("first_blocking_filter") != filt]
        blocked = [r for r in replays if r.get("first_blocking_filter") == filt]
        passed_stats = stats_from_replays(passed, initial_balance=BALANCE, risk_pct=RISK_PCT)
        blocked_stats = stats_from_replays(blocked, initial_balance=BALANCE, risk_pct=RISK_PCT)
        profitable_blocked = [r for r in blocked if r.get("would_win")]
        pf_after = float(passed_stats["profit_factor"])
        filter_edge[filt] = {
            "raw_pf_before_filter": raw_pf,
            "pf_after_filter": pf_after,
            "pf_delta": round(pf_after - raw_pf, 4),
            "trades_blocked": len(blocked),
            "trade_reduction_pct": round(len(blocked) / max(len(replays), 1) * 100, 2),
            "profitable_trades_removed": len(profitable_blocked),
            "edge_reduction_pct": round(
                sum(float(x.get("r_multiple", 0)) for x in profitable_blocked) / max(raw_stats["gross_r_wins"], 0.01) * 100, 2
            ) if profitable_blocked else 0.0,
            "blocked_avg_r": blocked_stats["average_r"],
            "passed_trade_count": passed_stats["trade_count"],
        }

    # Confusion matrix
    raw_correct = sum(1 for r in replays if r.get("would_win"))
    raw_wrong = sum(1 for r in replays if r.get("would_lose"))
    filtered = [r for r in replays if not r.get("would_reach_execution")]
    filtered_winner = sum(1 for r in filtered if r.get("would_win"))
    filtered_loser = sum(1 for r in filtered if r.get("would_lose"))
    executed_winner = sum(1 for r in executed_replays if r.get("would_win"))
    executed_loser = sum(1 for r in executed_replays if r.get("would_lose"))

    confusion = {
        "raw_ml_correct": raw_correct,
        "raw_ml_wrong": raw_wrong,
        "filtered_winner": filtered_winner,
        "filtered_loser": filtered_loser,
        "executed_winner": executed_winner,
        "executed_loser": executed_loser,
        "raw_ml_total": len(replays),
        "filtered_total": len(filtered),
        "executed_total": len(executed_replays),
    }

    ml_verdict = classify_ml_quality(raw_stats)
    if ml_verdict == "UNUSABLE":
        ml_verdict = "ML_IS_UNUSABLE"

    comparison = {
        "raw_ml": raw_stats,
        "executed_strategy": exec_stats,
        "differences": {
            "profit_factor": round(float(raw_stats["profit_factor"]) - float(exec_stats["profit_factor"]), 4),
            "win_rate_pct": round(raw_stats["win_rate_pct"] - exec_stats["win_rate_pct"], 2),
            "expectancy_r": round(raw_stats["expectancy_r"] - exec_stats["expectancy_r"], 4),
            "trade_count": raw_stats["trade_count"] - exec_stats["trade_count"],
            "max_drawdown_pct": round(raw_stats["max_drawdown_pct"] - exec_stats["max_drawdown_pct"], 2),
            "sharpe_ratio": round(raw_stats["sharpe_ratio"] - exec_stats["sharpe_ratio"], 4),
        },
    }

    trade_distribution = {
        "by_direction": {
            "BUY": stats_from_replays([r for r in replays if r["direction"] == "BUY"], initial_balance=BALANCE, risk_pct=RISK_PCT),
            "SELL": stats_from_replays([r for r in replays if r["direction"] == "SELL"], initial_balance=BALANCE, risk_pct=RISK_PCT),
        },
        "by_regime": {k: v["trade_count"] for k, v in regime_perf.items()},
        "by_confidence_bucket": {k: v["trade_count"] for k, v in confidence_report.items()},
        "by_filter_block": {k: v["trades_blocked"] for k, v in filter_edge.items()},
    }

    return {
        "now": NOW,
        "verdict": ml_verdict,
        "signals": signals,
        "replays": replays,
        "raw_stats": raw_stats,
        "exec_stats": exec_stats,
        "comparison": comparison,
        "confidence_report": confidence_report,
        "regime_perf": regime_perf,
        "filter_edge": filter_edge,
        "confusion": confusion,
        "trade_distribution": trade_distribution,
        "collection_meta": {
            "bars_scanned": collected.get("bars_scanned"),
            "elapsed_sec": collected.get("elapsed_sec"),
            "dataset": collected.get("dataset"),
        },
        "backtest_metrics": bt.get("metrics"),
        "hold_chain": bt.get("hold_chain"),
    }


def write_all(data: dict) -> None:
    def w(name: str, payload: dict | list) -> None:
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)

    w("raw_ml_signals.json", {
        "timestamp_utc": data["now"],
        "count": len(data["signals"]),
        "collection": data["collection_meta"],
        "signals": data["signals"],
    })
    w("raw_ml_replay.json", {
        "timestamp_utc": data["now"],
        "count": len(data["replays"]),
        "replays": data["replays"],
    })
    w("raw_ml_statistics.json", {"timestamp_utc": data["now"], "statistics": data["raw_stats"]})
    w("confidence_bucket_report.json", {"timestamp_utc": data["now"], "buckets": data["confidence_report"]})
    w("regime_performance.json", {"timestamp_utc": data["now"], "regimes": data["regime_perf"]})
    w("ml_vs_execution.json", {"timestamp_utc": data["now"], **data["comparison"]})
    w("filter_edge_loss.json", {"timestamp_utc": data["now"], "per_filter": data["filter_edge"]})
    w("prediction_quality.json", {
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "evidence": data["raw_stats"],
        "classification_basis": "raw_ml_replay_only_no_filters",
    })
    w("confusion_matrix.json", {"timestamp_utc": data["now"], "matrix": data["confusion"]})
    w("trade_distribution.json", {"timestamp_utc": data["now"], **data["trade_distribution"]})
    w("phase34a_final_report.json", {
        "phase": "34A",
        "title": "RAW ML Truth Audit",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "raw_ml_statistics": data["raw_stats"],
        "executed_statistics": data["exec_stats"],
        "ml_vs_execution": data["comparison"]["differences"],
        "confusion_matrix": data["confusion"],
        "regime_performance": data["regime_perf"],
        "confidence_buckets": {k: {"trade_count": v["trade_count"], "pf": v["profit_factor"], "wr": v["win_rate_pct"]} for k, v in data["confidence_report"].items()},
        "filter_edge_loss_summary": {k: {"pf_delta": v["pf_delta"], "trade_reduction_pct": v["trade_reduction_pct"], "profitable_removed": v["profitable_trades_removed"]} for k, v in data["filter_edge"].items()},
        "hold_chain": data["hold_chain"],
        "deliverables": [
            "raw_ml_signals.json", "raw_ml_replay.json", "raw_ml_statistics.json",
            "confidence_bucket_report.json", "regime_performance.json", "ml_vs_execution.json",
            "filter_edge_loss.json", "prediction_quality.json", "confusion_matrix.json",
            "trade_distribution.json", "phase34a_final_report.json",
        ],
    })


def main() -> None:
    data = asyncio.run(run_audit())
    write_all(data)
    print(json.dumps({
        "verdict": data["verdict"],
        "raw_signals": len(data["signals"]),
        "raw_pf": data["raw_stats"]["profit_factor"],
        "raw_wr": data["raw_stats"]["win_rate_pct"],
        "exec_pf": data["exec_stats"]["profit_factor"],
        "exec_trades": data["exec_stats"]["trade_count"],
    }, indent=2))


if __name__ == "__main__":
    main()
