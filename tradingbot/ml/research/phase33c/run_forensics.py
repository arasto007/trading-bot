"""Phase 33C — rejected signal outcome audit (read-only forensic)."""

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

MAX_HOLD = 72
DEFAULT_RR = 2.0
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def replay_trade(
    candles: pd.DataFrame,
    bar_index: int,
    *,
    direction: str,
    rr: float = DEFAULT_RR,
    max_hold: int = MAX_HOLD,
) -> dict:
    c = candles.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    if bar_index >= len(c) - 1:
        return _empty_outcome()

    entry = float(c.iloc[bar_index]["close"])
    atr = float(c.iloc[bar_index].get("high", entry) - c.iloc[bar_index].get("low", entry))
    sl_dist = max(atr, entry * 0.0005)
    if direction == "BUY":
        sl, tp = entry - sl_dist, entry + sl_dist * rr
    else:
        sl, tp = entry + sl_dist, entry - sl_dist * rr

    r_unit = abs(entry - sl) or 1e-9
    mfe = mae = 0.0
    tp_hit = sl_hit = False
    bars_tp = bars_sl = None
    exit_r = 0.0
    end = min(bar_index + max_hold, len(c) - 1)

    for j in range(bar_index + 1, end + 1):
        bar = c.iloc[j]
        hi, lo = float(bar["high"]), float(bar["low"])
        bars_elapsed = j - bar_index
        if direction == "BUY":
            fav = (hi - entry) / r_unit
            adv = (entry - lo) / r_unit
            mfe = max(mfe, fav)
            mae = max(mae, adv)
            if lo <= sl and not sl_hit:
                sl_hit = True
                bars_sl = bars_elapsed
                exit_r = -1.0
                break
            if hi >= tp and not tp_hit:
                tp_hit = True
                bars_tp = bars_elapsed
                exit_r = rr
                break
        else:
            fav = (entry - lo) / r_unit
            adv = (hi - entry) / r_unit
            mfe = max(mfe, fav)
            mae = max(mae, adv)
            if hi >= sl and not sl_hit:
                sl_hit = True
                bars_sl = bars_elapsed
                exit_r = -1.0
                break
            if lo <= tp and not tp_hit:
                tp_hit = True
                bars_tp = bars_elapsed
                exit_r = rr
                break
    else:
        close = float(c.iloc[end]["close"])
        exit_r = (close - entry) / r_unit if direction == "BUY" else (entry - close) / r_unit

    return {
        "entry_price": round(entry, 5),
        "stop_loss": round(sl, 5),
        "take_profit": round(tp, 5),
        "would_tp": tp_hit,
        "would_sl": sl_hit,
        "bars_until_tp": bars_tp,
        "bars_until_sl": bars_sl,
        "mfe_r": round(mfe, 4),
        "mae_r": round(mae, 4),
        "final_r_multiple": round(exit_r, 4),
    }


def _empty_outcome() -> dict:
    return {
        "entry_price": None,
        "stop_loss": None,
        "take_profit": None,
        "would_tp": False,
        "would_sl": False,
        "bars_until_tp": None,
        "bars_until_sl": None,
        "mfe_r": 0.0,
        "mae_r": 0.0,
        "final_r_multiple": 0.0,
    }


def primary_reject_module(rec: dict) -> tuple[str, str]:
    if rec.get("orchestrator_action") not in ("BUY", "SELL"):
        return "DecisionOrchestrator", "regime_or_engine_hold"
    if rec.get("calibrated_action") not in ("BUY", "SELL"):
        return "Calibration", "calibration_hold"
    if not rec.get("risk_allowed"):
        br = rec.get("block_reasons") or []
        return "AdaptiveRisk", br[0] if br else "risk_block"
    if not rec.get("quality_allowed"):
        br = rec.get("block_reasons") or []
        return "TradeQuality", br[0] if br else "quality_block"
    blocked = rec.get("filters_blocked_by") or []
    if "rsi_filter" in blocked:
        return "RSI Filter", "rsi_filter"
    if "adx_filter" in blocked:
        return "ADX Filter", "adx_filter"
    if rec.get("final_direction") in ("BUY", "SELL") and rec.get("execution_decision") != "EXECUTE":
        return "RiskGate", "riskgate_or_pre_execution"
    return "KernelAdapter", "kernel_hold"


def riskgate_module(reason: str) -> str:
    r = reason.lower()
    if "htf" in r:
        return "HTF Alignment"
    if "cooldown" in r and "loss" in r:
        return "Cooldown"
    if "cooldown" in r or "entry cooldown" in r:
        return "Cooldown"
    if "daily loss" in r:
        return "Daily Loss Limit"
    if "max positions" in r:
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


def stats_for_group(rows: list[dict]) -> dict:
    if not rows:
        return {
            "rejected_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate_pct": 0.0,
            "avg_r": 0.0,
            "avg_mfe": 0.0,
            "avg_mae": 0.0,
            "expected_value": 0.0,
            "correct_rejection_pct": 0.0,
            "wrong_rejection_pct": 0.0,
            "false_negative_pct": 0.0,
            "edge_lost_r": 0.0,
        }
    rs = [float(r["final_r_multiple"]) for r in rows]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    false_neg = [r for r in rs if r > 0]
    correct = [r for r in rs if r <= 0]
    n = len(rows)
    return {
        "rejected_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / n, 2),
        "avg_r": round(sum(rs) / n, 4),
        "avg_mfe": round(sum(float(r["mfe_r"]) for r in rows) / n, 4),
        "avg_mae": round(sum(float(r["mae_r"]) for r in rows) / n, 4),
        "expected_value": round(sum(rs) / n, 4),
        "correct_rejection_pct": round(100.0 * len(correct) / n, 2),
        "wrong_rejection_pct": round(100.0 * len(false_neg) / n, 2),
        "false_negative_pct": round(100.0 * len(false_neg) / n, 2),
        "edge_lost_r": round(sum(false_neg), 4),
    }


def precision_recall(rejected: list[dict], accepted: list[dict]) -> dict:
    """Filter as 'reject' predictor; outcome r>0 = would win."""
    rej_would_win = sum(1 for r in rejected if float(r["final_r_multiple"]) > 0)
    rej_would_lose = len(rejected) - rej_would_win
    acc_would_win = sum(1 for r in accepted if float(r["final_r_multiple"]) > 0)
    acc_would_lose = len(accepted) - acc_would_win
    tp = rej_would_lose
    fp = rej_would_win
    fn = acc_would_lose
    tn = acc_would_win
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fnr = fp / (fp + tn) if (fp + tn) else 0.0
    fpr = fn / (fn + tn) if (fn + tn) else 0.0
    return {
        "true_positive_reject_bad": tp,
        "false_positive_reject_good": fp,
        "false_negative_accept_bad": fn,
        "true_negative_accept_good": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_negative_rate": round(fnr, 4),
        "false_positive_rate": round(fpr, 4),
    }


async def run_audit() -> dict:
    from tradingbot.ml.research.phase22f.config import build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest
    from tradingbot.ml.research.phase22g.execution_tracer import run_execution_trace
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

    configure_research_env()
    dataset = build_dataset("A")
    ohlcv = await load_ohlcv_for_dataset(dataset, "M5")
    if ohlcv is None or ohlcv.empty:
        raise RuntimeError("no_ohlcv")

    ohlcv = ohlcv.copy()
    ohlcv.index = pd.to_datetime(ohlcv.index, utc=True)
    unified = build_unified_frame(ohlcv, None)
    unified["timestamp"] = pd.to_datetime(unified["timestamp"], utc=True)
    uidx = {pd.Timestamp(t): i for i, t in enumerate(unified["timestamp"])}

    print("Running rapid backtest...", flush=True)
    bt = await run_rapid_backtest("M5", dataset)
    print("Running execution trace stride=6...", flush=True)
    trace = await run_execution_trace(dataset, stride=6, timeframe="M5")

    rejected_db: list[dict] = []
    seen: set[str] = set()

    def add_record(base: dict) -> None:
        key = f"{base.get('timestamp')}|{base.get('direction')}|{base.get('reject_module')}|{base.get('reject_reason')}"
        if key in seen:
            return
        seen.add(key)
        rejected_db.append(base)

    # ML-layer rejects from execution trace
    for rec in trace.get("records") or []:
        if "error" in rec:
            continue
        direction = rec.get("orchestrator_action") or rec.get("final_direction")
        if direction not in ("BUY", "SELL"):
            continue
        if rec.get("execution_decision") == "EXECUTE":
            continue
        mod, reason = primary_reject_module(rec)
        ts = pd.Timestamp(rec["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        bar_idx = ohlcv.index.searchsorted(ts)
        if bar_idx >= len(ohlcv) - 5:
            continue
        outcome = replay_trade(ohlcv, bar_idx, direction=direction)
        urow = unified.iloc[uidx.get(ts, min(bar_idx, len(unified) - 1))]
        add_record({
            "timestamp": str(ts),
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "direction": direction,
            "entry_price": outcome["entry_price"],
            "stop_loss": outcome["stop_loss"],
            "take_profit": outcome["take_profit"],
            "confidence": rec.get("calibrated_confidence"),
            "probability": rec.get("range_prob") or rec.get("trend_prob"),
            "market_regime": rec.get("regime"),
            "adx": float(urow.get("adx", 0) or 0),
            "atr": float(urow.get("atr", 0) or 0),
            "atr_percentile": float(urow.get("atr_percentile", 0) or 0),
            "spread": float(urow.get("spread_pips", 0) or 0),
            "rsi": float(urow.get("rsi", 0) or 0),
            "reject_reason": reason,
            "reject_module": mod,
            "would_tp": outcome["would_tp"],
            "would_sl": outcome["would_sl"],
            "mfe_r": outcome["mfe_r"],
            "mae_r": outcome["mae_r"],
            "bars_until_tp": outcome["bars_until_tp"],
            "bars_until_sl": outcome["bars_until_sl"],
            "final_r_multiple": outcome["final_r_multiple"],
            "source": "execution_trace",
        })

    # RiskGate rejects from backtest blocked_events
    for ev in bt.get("blocked_events") or []:
        direction = ev.get("direction", "")
        if direction not in ("BUY", "SELL"):
            continue
        ts = pd.Timestamp(ev.get("timestamp", ""))
        if ts is pd.NaT:
            continue
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        bar_idx = ohlcv.index.searchsorted(ts)
        if bar_idx >= len(ohlcv) - 5:
            continue
        outcome = replay_trade(ohlcv, bar_idx, direction=direction)
        urow = unified.iloc[uidx.get(ts, min(bar_idx, len(unified) - 1))]
        reason = ev.get("reason", "riskgate")
        mod = riskgate_module(reason)
        add_record({
            "timestamp": str(ts),
            "symbol": "XAUUSD",
            "timeframe": ev.get("timeframe", "M5"),
            "direction": direction,
            "entry_price": outcome["entry_price"],
            "stop_loss": outcome["stop_loss"],
            "take_profit": outcome["take_profit"],
            "confidence": None,
            "probability": None,
            "market_regime": ev.get("regime"),
            "adx": float(urow.get("adx", 0) or 0),
            "atr": float(urow.get("atr", 0) or 0),
            "atr_percentile": float(urow.get("atr_percentile", 0) or 0),
            "spread": float(urow.get("spread_pips", 0) or 0),
            "rsi": float(urow.get("rsi", 0) or 0),
            "reject_reason": reason,
            "reject_module": mod,
            "would_tp": outcome["would_tp"],
            "would_sl": outcome["would_sl"],
            "mfe_r": outcome["mfe_r"],
            "mae_r": outcome["mae_r"],
            "bars_until_tp": outcome["bars_until_tp"],
            "bars_until_sl": outcome["bars_until_sl"],
            "final_r_multiple": outcome["final_r_multiple"],
            "source": "blocked_events",
        })

    # Accepted trades for confusion matrix
    accepted_db: list[dict] = []
    for t in bt.get("trades_detail") or []:
        direction = t.get("side", "BUY")
        ts = pd.Timestamp(t.get("entry_time", ""))
        if ts is pd.NaT:
            continue
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        bar_idx = ohlcv.index.searchsorted(ts)
        outcome = replay_trade(ohlcv, bar_idx, direction=direction) if bar_idx < len(ohlcv) - 5 else _empty_outcome()
        accepted_db.append({
            "timestamp": str(ts),
            "direction": direction,
            "entry_price": t.get("entry_price") or outcome["entry_price"],
            "stop_loss": t.get("entry_sl"),
            "final_r_multiple": float(t.get("r_multiple") or outcome["final_r_multiple"]),
            "pnl": t.get("pnl"),
            "would_tp": outcome["would_tp"],
            "would_sl": outcome["would_sl"],
            "mfe_r": outcome["mfe_r"],
            "mae_r": outcome["mae_r"],
            "reject_module": "ACCEPTED",
        })

    by_module: dict[str, list[dict]] = defaultdict(list)
    for r in rejected_db:
        by_module[r["reject_module"]].append(r)

    filter_quality = {mod: stats_for_group(rows) for mod, rows in by_module.items()}
    filter_precision = {
        mod: precision_recall(rows, accepted_db)
        for mod, rows in by_module.items()
    }

    false_negatives = [r for r in rejected_db if float(r["final_r_multiple"]) > 0]
    false_negatives.sort(key=lambda x: float(x["final_r_multiple"]), reverse=True)
    top100_wrong = false_negatives[:100]

    rej_would_win = sum(1 for r in rejected_db if float(r["final_r_multiple"]) > 0)
    rej_would_lose = len(rejected_db) - rej_would_win
    acc_would_win = sum(1 for r in accepted_db if float(r["final_r_multiple"]) > 0)
    acc_would_lose = len(accepted_db) - acc_would_win

    confusion = {
        "rows": ["Rejected", "Accepted"],
        "columns": ["Would_Win", "Would_Lose"],
        "matrix": {
            "Rejected_Would_Win": rej_would_win,
            "Rejected_Would_Lose": rej_would_lose,
            "Accepted_Would_Win": acc_would_win,
            "Accepted_Would_Lose": acc_would_lose,
        },
    }

    baseline_metrics = bt.get("metrics") or {}
    baseline_pf = float(baseline_metrics.get("profit_factor") or 0)
    wins_r = sum(float(r["final_r_multiple"]) for r in rejected_db if float(r["final_r_multiple"]) > 0)
    losses_r = abs(sum(float(r["final_r_multiple"]) for r in rejected_db if float(r["final_r_multiple"]) < 0))
    hypo_pf_rej_winners = wins_r / losses_r if losses_r > 0 else (999.0 if wins_r > 0 else 0.0)

    damage = []
    for mod, st in filter_quality.items():
        damage.append({
            "filter": mod,
            "false_negatives": st["winning_trades"],
            "edge_lost_r": st["edge_lost_r"],
            "correct_rejections": st["losing_trades"],
            "protection_r": round(abs(sum(float(r["final_r_multiple"]) for r in by_module[mod] if float(r["final_r_multiple"]) < 0)), 4),
            "wrong_rejection_pct": st["wrong_rejection_pct"],
        })
    damage.sort(key=lambda x: x["edge_lost_r"], reverse=True)

    total_false_neg_pct = round(100.0 * rej_would_win / max(len(rejected_db), 1), 2)
    verdict = "FILTERS_WORKING_CORRECTLY"
    if total_false_neg_pct > 50:
        verdict = "EDGE_DESTROYED_BY_FILTERS"
    elif total_false_neg_pct > 35:
        verdict = "FILTER_TOO_STRICT"
    elif rej_would_win > rej_would_lose:
        verdict = "FALSE_NEGATIVES_CONFIRMED"

    return {
        "generated_utc": NOW,
        "dataset": dataset.to_dict(),
        "method": "rapid_backtest blocked_events + execution_trace stride=6 + forward replay MAX_HOLD=72 RR=2",
        "rejected_count": len(rejected_db),
        "accepted_count": len(accepted_db),
        "baseline_pf": baseline_pf,
        "rejected_db": rejected_db,
        "accepted_db": accepted_db,
        "filter_quality": filter_quality,
        "filter_precision": filter_precision,
        "top100_wrong": top100_wrong,
        "confusion": confusion,
        "hypo_pf_rej_winners_only": round(hypo_pf_rej_winners, 4),
        "damage_ranking": damage,
        "verdict": verdict,
        "total_false_negative_pct": total_false_neg_pct,
        "hold_chain": bt.get("hold_chain"),
    }


def write_deliverables(data: dict) -> None:
    root = ROOT
    rej = data["rejected_db"]
    acc = data["accepted_db"]

    def w(name: str, payload: dict) -> None:
        (root / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"  wrote {name}", flush=True)

    w("rejected_signal_database.json", {
        "timestamp_utc": NOW,
        "count": len(rej),
        "records": rej,
    })
    w("rejected_trade_replay.json", {
        "timestamp_utc": NOW,
        "replay_params": {"max_hold_bars": MAX_HOLD, "rr": DEFAULT_RR},
        "records": [{k: r[k] for k in (
            "timestamp", "direction", "reject_module", "would_tp", "would_sl",
            "bars_until_tp", "bars_until_sl", "mfe_r", "mae_r", "final_r_multiple",
        )} for r in rej],
    })
    w("false_negative_analysis.json", {
        "timestamp_utc": NOW,
        "false_negative_count": sum(1 for r in rej if float(r["final_r_multiple"]) > 0),
        "false_negative_pct": data["total_false_negative_pct"],
        "total_edge_lost_r": round(sum(float(r["final_r_multiple"]) for r in rej if float(r["final_r_multiple"]) > 0), 4),
        "by_module": {m: s["edge_lost_r"] for m, s in data["filter_quality"].items()},
    })
    w("false_positive_analysis.json", {
        "timestamp_utc": NOW,
        "note": "Accepted trades that would lose (hindsight)",
        "accepted_would_lose": data["confusion"]["matrix"]["Accepted_Would_Lose"],
        "accepted_count": len(acc),
    })
    w("filter_quality.json", {"timestamp_utc": NOW, "by_module": data["filter_quality"]})
    w("filter_precision_recall.json", {"timestamp_utc": NOW, "by_module": data["filter_precision"]})
    w("confusion_matrix.json", {"timestamp_utc": NOW, **data["confusion"]})
    w("edge_lost_by_filter.json", {
        "timestamp_utc": NOW,
        "ranking": data["damage_ranking"],
    })
    w("top100_wrong_rejections.json", {
        "timestamp_utc": NOW,
        "count": len(data["top100_wrong"]),
        "records": data["top100_wrong"],
    })
    w("expected_pf_if_not_rejected.json", {
        "timestamp_utc": NOW,
        "baseline_pf": data["baseline_pf"],
        "hypothetical_pf_if_rejected_winners_executed": data["hypo_pf_rej_winners_only"],
        "rejected_winners_r_sum": round(sum(float(r["final_r_multiple"]) for r in rej if float(r["final_r_multiple"]) > 0), 4),
        "rejected_losers_r_sum": round(abs(sum(float(r["final_r_multiple"]) for r in rej if float(r["final_r_multiple"]) < 0)), 4),
        "note": "Counterfactual PF if only rejected signals with r>0 had executed — no strategy change",
    })
    w("filter_damage_ranking.json", {
        "timestamp_utc": NOW,
        "most_profitable_trade_destruction": data["damage_ranking"][:5],
        "most_loss_protection": sorted(data["damage_ranking"], key=lambda x: x["protection_r"], reverse=True)[:5],
        "full_ranking": data["damage_ranking"],
    })
    w("phase33c_summary.json", {
        "phase": "33C",
        "verdict": data["verdict"],
        "rejected_replayed": len(rej),
        "accepted_trades": len(acc),
        "false_negative_pct": data["total_false_negative_pct"],
        "baseline_pf": data["baseline_pf"],
        "hypo_pf_rej_winners": data["hypo_pf_rej_winners_only"],
        "top_damage_filter": data["damage_ranking"][0]["filter"] if data["damage_ranking"] else None,
    })
    w("phase33c_final_report.json", {
        "phase": "33C",
        "title": "Rejected Signal Outcome Audit",
        "timestamp_utc": NOW,
        "verdict": data["verdict"],
        "method": data["method"],
        "dataset": data["dataset"],
        "summary": {
            "rejected_signals_replayed": len(rej),
            "accepted_trades": len(acc),
            "false_negative_pct": data["total_false_negative_pct"],
            "baseline_pf": data["baseline_pf"],
            "hypothetical_pf_rejected_winners_only": data["hypo_pf_rej_winners_only"],
            "confusion_matrix": data["confusion"]["matrix"],
        },
        "filter_damage_top3": data["damage_ranking"][:3],
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
        "production_modified": False,
    })


def main() -> None:
    data = asyncio.run(run_audit())
    print(f"Verdict: {data['verdict']}", flush=True)
    print(f"Rejected: {data['rejected_count']} Accepted: {data['accepted_count']}", flush=True)
    write_deliverables(data)


if __name__ == "__main__":
    main()
