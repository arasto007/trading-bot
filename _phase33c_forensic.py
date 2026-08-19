"""Phase 33C — rejected signal outcome audit (read-only forensic runner)."""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
MAX_HOLD_BARS = 100
DEFAULT_RR = 2.0


def _prepare(candles: pd.DataFrame) -> pd.DataFrame:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    return c.sort_index()


def replay_rejected(
    candles: pd.DataFrame,
    bar_index: int,
    *,
    direction: str,
    rr: float = DEFAULT_RR,
) -> dict:
    """Forward replay — no execution."""
    c = _prepare(candles)
    if bar_index >= len(c) - 1 or direction not in ("BUY", "SELL"):
        return {
            "would_tp": False,
            "would_sl": False,
            "bars_to_tp": None,
            "bars_to_sl": None,
            "mfe": 0.0,
            "mae": 0.0,
            "r_multiple": 0.0,
            "exit_reason": "no_data",
        }

    entry = float(c.iloc[bar_index]["close"])
    atr = float(c.iloc[bar_index]["high"] - c.iloc[bar_index]["low"])
    sl_dist = max(atr, entry * 0.0005)
    if direction == "BUY":
        sl, tp = entry - sl_dist, entry + sl_dist * rr
    else:
        sl, tp = entry + sl_dist, entry - sl_dist * rr

    r_unit = abs(entry - sl)
    mfe = 0.0
    mae = 0.0
    would_tp = False
    would_sl = False
    bars_to_tp = None
    bars_to_sl = None
    exit_r = 0.0
    exit_reason = "timeout"

    end = min(bar_index + MAX_HOLD_BARS, len(c) - 1)
    for j in range(bar_index + 1, end + 1):
        bar = c.iloc[j]
        hi, lo = float(bar["high"]), float(bar["low"])
        bars_elapsed = j - bar_index
        if direction == "BUY":
            fav = (hi - entry) / r_unit if r_unit > 0 else 0.0
            adv = (entry - lo) / r_unit if r_unit > 0 else 0.0
            mfe = max(mfe, fav)
            mae = max(mae, adv)
            if lo <= sl and not would_sl:
                would_sl = True
                bars_to_sl = bars_elapsed
                exit_r = -1.0
                exit_reason = "sl"
                break
            if hi >= tp and not would_tp:
                would_tp = True
                bars_to_tp = bars_elapsed
                exit_r = rr
                exit_reason = "tp"
                break
        else:
            fav = (entry - lo) / r_unit if r_unit > 0 else 0.0
            adv = (hi - entry) / r_unit if r_unit > 0 else 0.0
            mfe = max(mfe, fav)
            mae = max(mae, adv)
            if hi >= sl and not would_sl:
                would_sl = True
                bars_to_sl = bars_elapsed
                exit_r = -1.0
                exit_reason = "sl"
                break
            if lo <= tp and not would_tp:
                would_tp = True
                bars_to_tp = bars_elapsed
                exit_r = rr
                exit_reason = "tp"
                break
    else:
        close = float(c.iloc[end]["close"])
        if direction == "BUY":
            exit_r = (close - entry) / r_unit if r_unit > 0 else 0.0
        else:
            exit_r = (entry - close) / r_unit if r_unit > 0 else 0.0
        exit_reason = "timeout"

    return {
        "entry_price": round(entry, 5),
        "sl": round(sl, 5),
        "tp": round(tp, 5),
        "would_tp": would_tp,
        "would_sl": would_sl,
        "bars_to_tp": bars_to_tp,
        "bars_to_sl": bars_to_sl,
        "mfe": round(mfe, 4),
        "mae": round(mae, 4),
        "r_multiple": round(exit_r, 4),
        "exit_reason": exit_reason,
    }


def _to_utc_ts(raw: object) -> pd.Timestamp:
    ts = pd.Timestamp(raw)
    if ts is pd.NaT:
        return ts
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _feat(row: dict, key: str, default=0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _first_reject_module(rec: dict) -> tuple[str, str]:
    orch = rec.get("orchestrator_action")
    if orch not in ("BUY", "SELL"):
        return "DecisionOrchestrator", "regime_or_engine_hold"
    if rec.get("calibrated_action") not in ("BUY", "SELL"):
        return "Calibration", "calibration_hold"
    if not rec.get("risk_allowed"):
        br = rec.get("block_reasons") or []
        for b in br:
            if str(b).startswith("risk"):
                return "AdaptiveRisk", str(b)
        return "AdaptiveRisk", "risk_blocked"
    if not rec.get("quality_allowed"):
        br = rec.get("block_reasons") or []
        for b in br:
            if str(b).startswith("quality"):
                return "TradeQuality", str(b)
        return "TradeQuality", "quality_blocked"
    blocked = rec.get("filters_blocked_by") or []
    if "rsi_filter" in blocked:
        return "RSI Filter", "rsi_filter"
    if "adx_filter" in blocked:
        return "ADX Filter", "adx_filter"
    if rec.get("execution_decision") != "EXECUTE":
        return "RiskGate", "riskgate_or_signal_stage"
    return "ACCEPTED", "executed"


def _map_riskgate_reason(reason: str) -> str:
    r = reason.lower()
    if "htf" in r or "alignment" in r:
        return "HTF Alignment"
    if "cooldown" in r and "loss" in r:
        return "Cooldown"
    if "cooldown" in r or "entry cooldown" in r:
        return "Cooldown"
    if "daily loss" in r:
        return "Daily Loss Limit"
    if "max position" in r:
        return "Max Positions"
    if "atr" in r:
        return "ATR Filter"
    if "spread" in r:
        return "Spread Gate"
    if "friday" in r:
        return "Friday Gate"
    if "opposite" in r:
        return "Opposite Position"
    if "meta" in r:
        return "MetaLabeler"
    return "RiskGate"


def _pf_from_r(values: list[float]) -> float:
    wins = sum(x for x in values if x > 0)
    losses = abs(sum(x for x in values if x < 0))
    if losses <= 0:
        return round(2.0 if wins > 0 else 0.0, 4)
    return round(wins / losses, 4)


async def run() -> dict:
    from tradingbot.ml.research.phase22f.config import build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest
    from tradingbot.ml.research.phase22g.execution_tracer import run_execution_trace
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.domain.models import MarketKey

    configure_research_env()
    ds = build_dataset("A")
    legacy = load_legacy_config()
    base_dir = legacy.get("BASE_DIR")

    print("Running production-path backtest...", flush=True)
    bt = await run_rapid_backtest("M5", ds)
    ohlcv = await load_ohlcv_for_dataset(ds, "M5")
    if ohlcv is None or ohlcv.empty:
        raise RuntimeError("no_ohlcv")

    ohlcv = _prepare(ohlcv)
    ts_index = ohlcv.index

    print("Running execution trace stride=10...", flush=True)
    trace = await run_execution_trace(ds, stride=10, timeframe="M5")
    records = [r for r in trace.get("records", []) if "error" not in r]

    rejected_db: list[dict] = []
    accepted_db: list[dict] = []

    for rec in records:
        direction = rec.get("orchestrator_action")
        if direction not in ("BUY", "SELL"):
            continue
        ts = _to_utc_ts(rec.get("timestamp", ""))
        if ts is pd.NaT:
            continue
        idx = int(ts_index.searchsorted(ts))
        if idx >= len(ohlcv) - 5:
            continue

        unified = PipelineCache.get_unified_frame(
            ohlcv.iloc[: idx + 1],
            base_dir=base_dir,
            symbol="XAUUSD",
            timeframe="M5",
        )
        row = unified.iloc[-1].to_dict() if not unified.empty else {}

        module, reason = _first_reject_module(rec)
        replay = replay_rejected(ohlcv, idx, direction=direction)
        prob = rec.get("range_prob") if rec.get("router_engine") == "phase9_9" else rec.get("trend_prob")

        entry = {
            "timestamp": str(ts),
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "direction": direction,
            "entry_price": replay["entry_price"],
            "sl": replay["sl"],
            "tp": replay["tp"],
            "confidence": rec.get("calibrated_confidence"),
            "probability": prob,
            "market_regime": rec.get("regime"),
            "adx": _feat(row, "adx"),
            "atr": _feat(row, "atr"),
            "atr_percentile": _feat(row, "atr_percentile"),
            "spread": _feat(row, "spread_pips"),
            "rsi": _feat(row, "rsi"),
            "reject_module": module,
            "reject_reason": reason,
            "would_tp": replay["would_tp"],
            "would_sl": replay["would_sl"],
            "mfe": replay["mfe"],
            "mae": replay["mae"],
            "bars_to_tp": replay["bars_to_tp"],
            "bars_to_sl": replay["bars_to_sl"],
            "r_multiple": replay["r_multiple"],
            "exit_reason": replay["exit_reason"],
            "would_win": replay["r_multiple"] > 0,
            "would_lose": replay["r_multiple"] < 0,
        }

        if module == "ACCEPTED":
            accepted_db.append(entry)
        else:
            rejected_db.append(entry)

    blocked = bt.get("blocked_events") or []
    seen_ts_dir = {(e["timestamp"], e.get("direction")) for e in rejected_db if "timestamp" in e}
    for ev in blocked:
        direction = ev.get("direction", "")
        if direction not in ("BUY", "SELL"):
            direction = direction if direction in ("BUY", "SELL") else "BUY"
        ts = _to_utc_ts(ev.get("timestamp", ""))
        if ts is pd.NaT:
            continue
        key = (str(ts), direction)
        if key in seen_ts_dir:
            for e in rejected_db:
                if e["timestamp"] == str(ts) and e["direction"] == direction:
                    e["reject_module"] = _map_riskgate_reason(ev.get("reason", ""))
                    e["reject_reason"] = ev.get("reason", "")
            continue
        idx = int(ts_index.searchsorted(ts))
        if idx >= len(ohlcv) - 5:
            continue
        replay = replay_rejected(ohlcv, idx, direction=direction)
        module = _map_riskgate_reason(ev.get("reason", ""))
        rejected_db.append({
            "timestamp": str(ts),
            "symbol": ev.get("timeframe", "XAUUSD") if isinstance(ev.get("timeframe"), str) else "XAUUSD",
            "timeframe": "M5",
            "direction": direction,
            "entry_price": replay["entry_price"],
            "sl": replay["sl"],
            "tp": replay["tp"],
            "confidence": None,
            "probability": None,
            "market_regime": ev.get("regime"),
            "adx": None,
            "atr": None,
            "atr_percentile": None,
            "spread": None,
            "rsi": None,
            "reject_module": module,
            "reject_reason": ev.get("reason", ""),
            **{k: replay[k] for k in ("would_tp", "would_sl", "mfe", "mae", "bars_to_tp", "bars_to_sl", "r_multiple", "exit_reason")},
            "would_win": replay["r_multiple"] > 0,
            "would_lose": replay["r_multiple"] < 0,
            "source": "blocked_events",
        })

    trades = bt.get("trades_detail") or []
    for t in trades:
        ts = _to_utc_ts(t.get("entry_time", ""))
        if ts is pd.NaT:
            continue
        idx = int(ts_index.searchsorted(ts))
        direction = t.get("side", "BUY")
        replay = replay_rejected(ohlcv, idx, direction=direction)
        actual_r = float(t.get("r_multiple") or 0)
        accepted_db.append({
            "timestamp": str(ts),
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "direction": direction,
            "entry_price": t.get("entry_price"),
            "sl": t.get("entry_sl"),
            "tp": None,
            "confidence": None,
            "probability": None,
            "market_regime": None,
            "reject_module": "ACCEPTED",
            "reject_reason": "executed",
            "r_multiple": actual_r,
            "replay_r_multiple": replay["r_multiple"],
            "would_win": actual_r > 0,
            "would_lose": actual_r < 0,
            "pnl": t.get("pnl"),
            "source": "trades_detail",
        })

    by_filter: dict[str, list] = defaultdict(list)
    for e in rejected_db:
        by_filter[e["reject_module"]].append(e)

    filter_quality = {}
    for mod, items in by_filter.items():
        n = len(items)
        wins = sum(1 for x in items if x.get("would_win"))
        losses = sum(1 for x in items if x.get("would_lose"))
        rs = [float(x.get("r_multiple", 0)) for x in items]
        filter_quality[mod] = {
            "rejected_trades": n,
            "winning_would_have_been": wins,
            "losing_would_have_been": losses,
            "neutral": n - wins - losses,
            "win_rate_if_taken": round(wins / max(n, 1) * 100, 2),
            "avg_r": round(sum(rs) / max(n, 1), 4),
            "avg_mfe": round(sum(float(x.get("mfe", 0)) for x in items) / max(n, 1), 4),
            "avg_mae": round(sum(float(x.get("mae", 0)) for x in items) / max(n, 1), 4),
            "expected_value": round(sum(rs) / max(n, 1), 4),
            "correct_rejection_pct": round(losses / max(n, 1) * 100, 2),
            "wrong_rejection_pct": round(wins / max(n, 1) * 100, 2),
            "false_negative_pct": round(wins / max(n, 1) * 100, 2),
            "edge_lost_r": round(sum(r for r in rs if r > 0), 4),
        }

    prec_recall = {}
    for mod, items in by_filter.items():
        tp = sum(1 for x in items if x.get("would_lose"))
        fp = sum(1 for x in items if x.get("would_win"))
        prec = tp / max(tp + fp, 1)
        prec_recall[mod] = {
            "true_positive_reject": tp,
            "false_positive_reject": fp,
            "precision": round(prec, 4),
            "false_negative_rate": round(fp / max(len(items), 1), 4),
            "false_positive_rate": round(fp / max(len(items), 1), 4),
            "recall_note": "recall requires full population of bad trades — not isolated per filter",
        }

    wrong = [e for e in rejected_db if e.get("would_win")]
    wrong.sort(key=lambda x: float(x.get("r_multiple", 0)), reverse=True)
    top100 = wrong[:100]

    rej_win = sum(1 for e in rejected_db if e.get("would_win"))
    rej_lose = sum(1 for e in rejected_db if e.get("would_lose"))
    acc_win = sum(1 for e in accepted_db if e.get("would_win"))
    acc_lose = sum(1 for e in accepted_db if e.get("would_lose"))

    confusion = {
        "matrix": {
            "rejected_would_win": rej_win,
            "rejected_would_lose": rej_lose,
            "accepted_would_win": acc_win,
            "accepted_would_lose": acc_lose,
        },
        "labels": {
            "rows": ["Rejected", "Accepted"],
            "columns": ["Would Win", "Would Lose"],
        },
    }

    baseline_r = [float(t.get("r_multiple") or 0) for t in trades]
    baseline_pf = _pf_from_r(baseline_r)
    added_r = [float(e.get("r_multiple", 0)) for e in rejected_db if e.get("would_win")]
    hypo_pf = _pf_from_r(baseline_r + added_r)

    damage = []
    for mod, fq in filter_quality.items():
        damage.append({
            "filter": mod,
            "edge_lost_r": fq["edge_lost_r"],
            "wrong_rejections": fq["winning_would_have_been"],
            "correct_rejections": fq["losing_would_have_been"],
            "false_negative_pct": fq["false_negative_pct"],
        })
    damage.sort(key=lambda x: x["edge_lost_r"], reverse=True)

    protect = sorted(
        [(m, filter_quality[m]["losing_would_have_been"]) for m in filter_quality],
        key=lambda x: x[1],
        reverse=True,
    )

    total_rej = len(rejected_db)
    total_wrong = len(wrong)
    wrong_pct = round(total_wrong / max(total_rej, 1) * 100, 2)

    if wrong_pct >= 40:
        verdict = "EDGE_DESTROYED_BY_FILTERS"
    elif wrong_pct >= 25:
        verdict = "FILTER_TOO_STRICT"
    elif total_wrong > 0:
        verdict = "FALSE_NEGATIVES_CONFIRMED"
    else:
        verdict = "FILTERS_WORKING_CORRECTLY"

    return {
        "now": NOW,
        "dataset": ds.to_dict(),
        "verdict": verdict,
        "rejected_db": rejected_db,
        "accepted_db": accepted_db,
        "filter_quality": filter_quality,
        "prec_recall": prec_recall,
        "top100": top100,
        "confusion": confusion,
        "baseline_pf": baseline_pf,
        "hypo_pf": hypo_pf,
        "damage": damage,
        "protect": protect,
        "hold_chain": bt.get("hold_chain"),
        "metrics": bt.get("metrics"),
        "trace_stride": 10,
        "trace_bars": len(records),
        "wrong_rejection_pct": wrong_pct,
    }


def write_deliverables(data: dict) -> None:
    def w(name: str, payload: dict | list) -> None:
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)

    w("rejected_signal_database.json", {
        "timestamp_utc": data["now"],
        "count": len(data["rejected_db"]),
        "method": "execution_trace stride=10 + blocked_events replay",
        "signals": data["rejected_db"],
    })
    w("rejected_trade_replay.json", {
        "timestamp_utc": data["now"],
        "replays": data["rejected_db"],
        "accepted_replays": data["accepted_db"],
    })
    w("filter_quality.json", {"timestamp_utc": data["now"], "per_filter": data["filter_quality"]})
    w("filter_precision_recall.json", {"timestamp_utc": data["now"], "per_filter": data["prec_recall"]})
    w("false_negative_analysis.json", {
        "timestamp_utc": data["now"],
        "total_false_negatives": sum(1 for e in data["rejected_db"] if e.get("would_win")),
        "false_negative_pct": data["wrong_rejection_pct"],
        "by_filter": {k: v["false_negative_pct"] for k, v in data["filter_quality"].items()},
        "edge_lost_r_total": round(sum(float(e.get("r_multiple", 0)) for e in data["rejected_db"] if e.get("would_win")), 4),
    })
    w("false_positive_analysis.json", {
        "timestamp_utc": data["now"],
        "accepted_losing_trades": sum(1 for e in data["accepted_db"] if e.get("would_lose")),
        "accepted_winning_trades": sum(1 for e in data["accepted_db"] if e.get("would_win")),
        "note": "accepted trades from trades_detail actual r_multiple",
    })
    w("confusion_matrix.json", {"timestamp_utc": data["now"], **data["confusion"]})
    w("edge_lost_by_filter.json", {
        "timestamp_utc": data["now"],
        "ranking": data["damage"],
    })
    w("top100_wrong_rejections.json", {
        "timestamp_utc": data["now"],
        "count": len(data["top100"]),
        "trades": data["top100"],
    })
    w("expected_pf_if_not_rejected.json", {
        "timestamp_utc": data["now"],
        "baseline_pf_actual_trades": data["baseline_pf"],
        "hypothetical_pf_if_rejected_winners_executed": data["hypo_pf"],
        "added_winning_rejected_trades": sum(1 for e in data["rejected_db"] if e.get("would_win")),
        "method": "add replay R of rejected would-win signals to actual trade R — no strategy change",
        "disclaimer": "hindsight replay using research simulator — not live execution",
    })
    w("filter_damage_ranking.json", {
        "timestamp_utc": data["now"],
        "most_profitable_trade_destruction": data["damage"],
        "most_loss_protection": [{"filter": f, "losses_prevented": c} for f, c in data["protect"]],
    })
    w("phase33c_summary.json", {
        "phase": "33C",
        "verdict": data["verdict"],
        "rejected_signals": len(data["rejected_db"]),
        "wrong_rejection_pct": data["wrong_rejection_pct"],
        "baseline_pf": data["baseline_pf"],
        "hypo_pf": data["hypo_pf"],
        "top_damage_filter": data["damage"][0]["filter"] if data["damage"] else None,
    })
    w("phase33c_final_report.json", {
        "phase": "33C",
        "title": "Rejected Signal Outcome Audit",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "measurement": {
            "dataset": data["dataset"],
            "trace_stride": data["trace_stride"],
            "trace_bars": data["trace_bars"],
            "backtest_trades": data["metrics"].get("total_trades"),
            "baseline_pf": data["baseline_pf"],
            "baseline_expectancy": data["metrics"].get("expectancy"),
        },
        "summary": {
            "rejected_signals_replayed": len(data["rejected_db"]),
            "wrong_rejection_pct": data["wrong_rejection_pct"],
            "false_negatives": sum(1 for e in data["rejected_db"] if e.get("would_win")),
            "correct_rejections": sum(1 for e in data["rejected_db"] if e.get("would_lose")),
            "hypothetical_pf_if_winners_restored": data["hypo_pf"],
            "top_edge_killer": data["damage"][0] if data["damage"] else None,
            "top_loss_protector": data["protect"][0] if data["protect"] else None,
        },
        "confusion_matrix": data["confusion"]["matrix"],
        "deliverables": [
            "phase33c_final_report.json",
            "rejected_signal_database.json",
            "false_negative_analysis.json",
            "false_positive_analysis.json",
            "filter_quality.json",
            "filter_precision_recall.json",
            "rejected_trade_replay.json",
            "confusion_matrix.json",
            "edge_lost_by_filter.json",
            "top100_wrong_rejections.json",
            "expected_pf_if_not_rejected.json",
            "filter_damage_ranking.json",
            "phase33c_summary.json",
        ],
    })


def main() -> None:
    data = asyncio.run(run())
    write_deliverables(data)
    print(json.dumps({"verdict": data["verdict"], "rejected": len(data["rejected_db"]), "wrong_pct": data["wrong_rejection_pct"]}, indent=2))


if __name__ == "__main__":
    main()
