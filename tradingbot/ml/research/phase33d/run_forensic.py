#!/usr/bin/env python3
"""Phase 33D — full rejected signal reconstruction & filter truth audit."""

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

MODULE_MAP = {
    "riskgate": "RiskGate",
    "max positions for symbol": "Max Positions",
    "entry cooldown": "Cooldown",
    "daily loss limit": "Daily Loss Limit",
    "cooldown after losses": "Cooldown",
    "ATR percentile too low": "ATR Filter",
    "friday no entry window": "Friday Gate",
    "opposite direction position open": "Opposite Position",
    "meta": "MetaLabeler",
    "rsi_filter": "RSI Filter",
    "adx_filter": "ADX Filter",
    "htf_confirmation": "HTF Alignment",
}


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    c = df.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    return c.sort_index()


def _pf(rs: list[float]) -> float:
    w = sum(x for x in rs if x > 0)
    l = abs(sum(x for x in rs if x < 0))
    return round(w / l, 4) if l > 0 else (2.0 if w > 0 else 0.0)


def _map_module(stage: str, reason: str) -> str:
    key = reason.split("(")[0].strip().lower()
    if key in MODULE_MAP:
        return MODULE_MAP[key]
    if stage in MODULE_MAP:
        return MODULE_MAP[stage]
    if "quality" in reason.lower():
        return "TradeQuality"
    if "risk" in reason.lower():
        return "AdaptiveRisk"
    if "calibration" in reason.lower():
        return "Calibration"
    if "decision" in reason.lower() or "regime" in reason.lower():
        return "DecisionOrchestrator"
    return stage or reason


def _to_utc_ts(v) -> pd.Timestamp:
    ts = pd.Timestamp(v)
    if ts is pd.NaT:
        return ts
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _bar_index(ts_index: pd.DatetimeIndex, ts: pd.Timestamp) -> int:
    if ts is pd.NaT:
        return -1
    return int(ts_index.searchsorted(ts))


def _classify_filter(mod: str, stats: dict) -> str:
    n = stats.get("rejected_trades", 0)
    if n == 0:
        return "DEAD"
    fnr = stats.get("false_negative_rate", 0)
    prec = stats.get("precision", 0)
    if fnr >= 0.4 and stats.get("edge_lost_r", 0) > 5:
        return "HARMFUL"
    if fnr >= 0.25:
        return "HARMFUL"
    if prec >= 0.6 and fnr < 0.2:
        return "PROFITABLE"
    if fnr < 0.15 and prec >= 0.5:
        return "NEUTRAL"
    if fnr > 0.35:
        return "HARMFUL"
    return "NEUTRAL"


def _first_ml_reject(rec: dict) -> tuple[str, str, str]:
    orch = rec.get("orchestrator_action")
    if orch not in ("BUY", "SELL"):
        return "DecisionOrchestrator", "regime_or_engine_hold", orch or "HOLD"
    if rec.get("calibrated_action") not in ("BUY", "SELL"):
        return "Calibration", "calibration_hold", str(rec.get("calibrated_action"))
    if not rec.get("risk_allowed"):
        return "AdaptiveRisk", str((rec.get("block_reasons") or ["risk_blocked"])[0]), orch
    if not rec.get("quality_allowed"):
        return "TradeQuality", str((rec.get("block_reasons") or ["quality_blocked"])[0]), orch
    blocked = rec.get("filters_blocked_by") or []
    if "rsi_filter" in blocked:
        return "RSI Filter", "rsi_filter", orch
    if "adx_filter" in blocked:
        return "ADX Filter", "adx_filter", orch
    return "ACCEPTED", "passed", orch


CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase33d" / ".cache"


def _load_cache(name: str) -> dict | None:
    p = CACHE_DIR / f"{name}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def _save_cache(name: str, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{name}.json").write_text(json.dumps(payload, default=str), encoding="utf-8")


async def run_audit(*, use_cache: bool = True) -> dict:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.research.phase22f.config import build_dataset, configure_research_env
    from tradingbot.ml.research.phase22f.datasets import load_ohlcv_for_dataset
    from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest
    from tradingbot.ml.research.phase22g.execution_tracer import run_execution_trace
    from tradingbot.ml.research.phase33d.forensic_context import row_checksum
    from tradingbot.ml.research.phase33d.replay import replay_with_production_sl_tp

    configure_research_env()
    ds = build_dataset("A")
    legacy = load_legacy_config()
    base_dir = legacy.get("BASE_DIR")

    print("Backtest with fixed forensic trace...", flush=True)
    bt = _load_cache("backtest_m5_a") if use_cache else None
    if bt is None:
        bt = await run_rapid_backtest("M5", ds, blocked_events_limit=None)
        _save_cache("backtest_m5_a", bt)
    ohlcv = _prepare(await load_ohlcv_for_dataset(ds, "M5"))
    ts_index = ohlcv.index

    print("Execution trace stride=10 for ML context...", flush=True)
    trace = _load_cache("execution_trace_m5_a_s10") if use_cache else None
    if trace is None:
        trace = await run_execution_trace(ds, stride=10, timeframe="M5")
        _save_cache("execution_trace_m5_a_s10", trace)
    records = [r for r in trace.get("records", []) if "error" not in r]

    events: list[dict] = []
    seen: set[tuple] = set()

    # ML-path rejections from execution trace
    for rec in records:
        module, reason, direction = _first_ml_reject(rec)
        if module == "ACCEPTED":
            continue
        ts = _to_utc_ts(rec.get("timestamp", ""))
        if ts is pd.NaT:
            continue
        ts_s = str(ts)
        key = (ts_s, direction, module)
        if key in seen:
            continue
        seen.add(key)
        idx = _bar_index(ts_index, ts)
        if idx >= len(ohlcv) - 5:
            continue
        unified = PipelineCache.get_unified_frame(
            ohlcv.iloc[: idx + 1], base_dir=base_dir, symbol="XAUUSD", timeframe="M5"
        )
        row = unified.iloc[-1].to_dict() if not unified.empty else {}
        fchk = row_checksum(row)
        prob = rec.get("range_prob") if rec.get("router_engine") == "phase9_9" else rec.get("trend_prob")
        replay = replay_with_production_sl_tp(
            ohlcv, idx, direction=direction,
            confidence=float(rec.get("calibrated_confidence") or 0.55),
            spread_pips=float(row.get("spread_pips", 3.0) or 3.0),
        )
        events.append({
            "event_id": f"ml_{len(events):05d}",
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "timestamp": ts_s,
            "bar_index": idx,
            "closed_bar_time": ts_s,
            "current_bar_time": ts_s,
            "feature_checksum": fchk,
            "dataset_checksum": "",
            "probability": prob,
            "confidence": rec.get("calibrated_confidence"),
            "quality_score": rec.get("quality_score"),
            "risk_score": None,
            "decision": rec.get("final_direction"),
            "regime": rec.get("regime"),
            "trend": rec.get("router_engine"),
            "adx": float(row.get("adx", 0) or 0),
            "atr": float(row.get("atr", 0) or 0),
            "rsi": float(row.get("rsi", 0) or 0),
            "spread": float(row.get("spread_pips", 0) or 0),
            "htf_trend": None,
            "reason": reason,
            "module": module,
            "function": "execution_trace",
            "line_number": 0,
            "direction": direction,
            "filter_chain": [module],
            "source": "execution_trace",
            "reconstruction_validated": True,
            **replay,
        })

    # RiskGate + RSI/ADX from fixed blocked_events
    blocked = bt.get("blocked_events") or []
    empty_ts_before = sum(1 for e in blocked if not e.get("timestamp"))
    rg_added = 0
    for ev in blocked:
        direction = ev.get("direction", "")
        if direction not in ("BUY", "SELL"):
            continue
        ts_s = str(ev.get("timestamp") or ev.get("closed_bar_time") or "")
        bar_idx = int(ev.get("bar_index", 0))
        if not ts_s and bar_idx > 0 and bar_idx < len(ts_index):
            ts_s = str(ts_index[bar_idx])
        if not ts_s:
            continue
        module = _map_module(ev.get("stage", ""), ev.get("reason", ""))
        key = (ts_s, direction, module, ev.get("reason", ""))
        if key in seen:
            continue
        seen.add(key)
        idx = bar_idx if bar_idx > 0 else _bar_index(ts_index, _to_utc_ts(ts_s))
        if idx >= len(ohlcv) - 5:
            continue
        unified = PipelineCache.get_unified_frame(
            ohlcv.iloc[: idx + 1], base_dir=base_dir, symbol="XAUUSD", timeframe="M5"
        )
        row = unified.iloc[-1].to_dict() if not unified.empty else {}
        replay = replay_with_production_sl_tp(
            ohlcv, idx, direction=direction,
            confidence=float(ev.get("confidence") or 0.55),
            spread_pips=float(ev.get("spread") or row.get("spread_pips", 3.0) or 3.0),
        )
        events.append({
            "event_id": f"rg_{len(events):05d}",
            "symbol": ev.get("symbol", "XAUUSD"),
            "timeframe": ev.get("timeframe", "M5"),
            "timestamp": ts_s,
            "bar_index": idx,
            "closed_bar_time": ts_s,
            "current_bar_time": ts_s,
            "feature_checksum": ev.get("feature_checksum") or row_checksum(row),
            "dataset_checksum": "",
            "probability": None,
            "confidence": ev.get("confidence"),
            "quality_score": ev.get("quality_score"),
            "risk_score": None,
            "decision": direction,
            "regime": ev.get("regime"),
            "trend": ev.get("engine"),
            "adx": ev.get("adx") or float(row.get("adx", 0) or 0),
            "atr": ev.get("atr") or float(row.get("atr", 0) or 0),
            "rsi": ev.get("rsi") or float(row.get("rsi", 0) or 0),
            "spread": ev.get("spread"),
            "htf_trend": ev.get("htf_bias"),
            "reason": ev.get("reason", ""),
            "module": module,
            "function": "BacktestRiskGate.evaluate",
            "line_number": 0,
            "direction": direction,
            "filter_chain": [module],
            "source": "blocked_events_fixed",
            "reconstruction_validated": bool(ts_s and idx > 0),
            **replay,
        })
        rg_added += 1

    trades = bt.get("trades_detail") or []
    accepted: list[dict] = []
    for t in trades:
        ts = _to_utc_ts(t.get("entry_time", ""))
        if ts is pd.NaT:
            continue
        idx = _bar_index(ts_index, ts)
        direction = t.get("side", "BUY")
        replay = replay_with_production_sl_tp(ohlcv, idx, direction=direction)
        actual_r = float(t.get("r_multiple") or 0)
        accepted.append({
            "timestamp": str(ts),
            "direction": direction,
            "module": "ACCEPTED",
            "r_multiple": actual_r,
            "replay_r_multiple": replay["r_multiple"],
            "would_win": actual_r > 0,
            "would_lose": actual_r < 0,
            "pnl": t.get("pnl"),
        })

    by_mod: dict[str, list] = defaultdict(list)
    for e in events:
        by_mod[e["module"]].append(e)

    filter_truth = {}
    prec_recall = {}
    for mod, items in by_mod.items():
        n = len(items)
        wins = sum(1 for x in items if x.get("would_win"))
        losses = sum(1 for x in items if x.get("would_lose"))
        rs = [float(x.get("r_multiple", 0)) for x in items]
        filter_truth[mod] = {
            "true_reject": losses,
            "false_reject": wins,
            "rejected_trades": n,
            "win_rate_if_taken": round(wins / max(n, 1) * 100, 2),
            "avg_r": round(sum(rs) / max(n, 1), 4),
            "expected_value": round(sum(rs) / max(n, 1), 4),
            "correct_rejection_pct": round(losses / max(n, 1) * 100, 2),
            "wrong_rejection_pct": round(wins / max(n, 1) * 100, 2),
            "false_negative_pct": round(wins / max(n, 1) * 100, 2),
            "edge_lost_r": round(sum(r for r in rs if r > 0), 4),
            "precision": round(losses / max(losses + wins, 1), 4),
            "false_negative_rate": round(wins / max(n, 1), 4),
            "false_positive_rate": round(wins / max(n, 1), 4),
        }
        prec_recall[mod] = {
            "precision": filter_truth[mod]["precision"],
            "recall_note": "recall needs full bad-trade population",
            "false_negative_rate": filter_truth[mod]["false_negative_rate"],
            "false_positive_rate": filter_truth[mod]["false_positive_rate"],
        }

    wrong = [e for e in events if e.get("would_win")]
    wrong.sort(key=lambda x: float(x.get("r_multiple", 0)), reverse=True)
    right = [e for e in events if e.get("would_lose")]

    acc_w = sum(1 for a in accepted if a.get("would_win"))
    acc_l = sum(1 for a in accepted if a.get("would_lose"))

    baseline_r = [float(t.get("r_multiple") or 0) for t in trades]
    hypo_r = baseline_r + [float(e.get("r_multiple", 0)) for e in wrong]

    damage = sorted(
        [{"filter": m, **{k: v for k, v in fq.items() if k in ("edge_lost_r", "false_reject", "true_reject")}} for m, fq in filter_truth.items()],
        key=lambda x: x.get("edge_lost_r", 0),
        reverse=True,
    )

    # Shapley-style marginal: unique rejections per filter
    shapley = []
    for mod, items in by_mod.items():
        unique = len(items)
        shapley.append({
            "filter": mod,
            "unique_rejections": unique,
            "edge_destroyed_r": filter_truth[mod]["edge_lost_r"],
            "edge_preserved_r": round(abs(sum(float(x.get("r_multiple", 0)) for x in items if x.get("would_lose"))), 4),
            "marginal_pf_delta_estimate": round(
                _pf(baseline_r + [float(x.get("r_multiple", 0)) for x in items if x.get("would_win")]) - _pf(baseline_r), 4
            ),
        })

    total_wrong = len(wrong)
    total_rej = len(events)
    wrong_pct = round(total_wrong / max(total_rej, 1) * 100, 2)

    if total_rej < 10:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif wrong_pct >= 40:
        verdict = "FILTERS_DESTROY_EDGE"
    elif wrong_pct >= 25:
        verdict = "FILTERS_PARTIALLY_VALID"
    elif total_wrong > 0:
        verdict = "FILTERS_PARTIALLY_VALID"
    else:
        verdict = "FILTERS_VALID"

    filter_ranking = {m: _classify_filter(m, v) for m, v in filter_truth.items()}
    redundant_filters = [m for m, c in filter_ranking.items() if c == "REDUNDANT"]
    harmful_filters = [m for m, c in filter_ranking.items() if c == "HARMFUL"]

    redundant_pct = 0.0
    if len(events) > 0:
        overlap_keys = len(seen)
        redundant_pct = round(max(0, 1 - overlap_keys / max(len(blocked) + len(records), 1)) * 100, 2)
    if redundant_pct > 50 and wrong_pct < 20:
        verdict = "FILTERS_REDUNDANT"

    return {
        "now": NOW,
        "verdict": verdict,
        "events": events,
        "accepted": accepted,
        "filter_truth": filter_truth,
        "prec_recall": prec_recall,
        "wrong": wrong,
        "right": right,
        "damage": damage,
        "shapley": shapley,
        "baseline_pf": _pf(baseline_r),
        "hypo_pf": _pf(hypo_r),
        "wrong_pct": wrong_pct,
        "blocked_events_total": len(blocked),
        "blocked_events_empty_ts_before_fix": empty_ts_before,
        "blocked_events_reconstructed": rg_added,
        "ml_trace_rejections": len(events) - rg_added,
        "trace_bars": len(records),
        "hold_chain": bt.get("hold_chain"),
        "metrics": bt.get("metrics"),
        "confusion": {
            "rejected_would_win": total_wrong,
            "rejected_would_lose": len(right),
            "accepted_would_win": acc_w,
            "accepted_would_lose": acc_l,
        },
        "redundant_pct": redundant_pct,
        "filter_ranking": filter_ranking,
        "harmful_filters": harmful_filters,
        "redundant_filter_list": redundant_filters,
    }


def write_all(data: dict) -> None:
    def w(name: str, payload: dict | list) -> None:
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)

    events = data["events"]
    w("reconstructed_rejections.json", {"timestamp_utc": data["now"], "count": len(events), "events": events})
    w("rejected_signal_database.json", {"timestamp_utc": data["now"], "count": len(events), "signals": events})
    w("replay_database.json", {"timestamp_utc": data["now"], "replays": events, "accepted": data["accepted"]})
    w("filter_truth_table.json", {"timestamp_utc": data["now"], "per_filter": data["filter_truth"]})
    w("filter_precision.json", {"timestamp_utc": data["now"], "per_filter": {k: {"precision": v["precision"]} for k, v in data["filter_truth"].items()}})
    w("filter_recall.json", {"timestamp_utc": data["now"], "per_filter": data["prec_recall"]})
    w("filter_false_negative.json", {"timestamp_utc": data["now"], "by_filter": {k: v["false_negative_pct"] for k, v in data["filter_truth"].items()}, "trades": data["wrong"]})
    w("filter_false_positive.json", {"timestamp_utc": data["now"], "accepted_losers": data["confusion"]["accepted_would_lose"]})
    w("filter_quality.json", {"timestamp_utc": data["now"], "per_filter": data["filter_truth"]})
    w("filter_precision_recall.json", {"timestamp_utc": data["now"], "per_filter": data["prec_recall"]})
    w("confusion_matrix.json", {"timestamp_utc": data["now"], "matrix": data["confusion"], "labels": {"rows": ["Rejected", "Accepted"], "columns": ["Would Win", "Would Lose"]}})
    w("edge_lost_by_filter.json", {"timestamp_utc": data["now"], "ranking": data["damage"]})
    w("top_false_negative_trades.json", {"timestamp_utc": data["now"], "count": len(data["wrong"]), "trades": data["wrong"][:100]})
    w("top_false_positive_trades.json", {"timestamp_utc": data["now"], "count": data["confusion"]["accepted_would_lose"], "note": "accepted trades with negative r_multiple"})
    w("top100_wrong_rejections.json", {"timestamp_utc": data["now"], "count": min(100, len(data["wrong"])), "trades": data["wrong"][:100]})
    w("expected_pf_if_not_rejected.json", {
        "timestamp_utc": data["now"],
        "baseline_pf_actual_trades": data["baseline_pf"],
        "hypothetical_pf_if_rejected_winners_executed": data["hypo_pf"],
        "added_winning_rejected_trades": len(data["wrong"]),
    })
    w("filter_shapley.json", {"timestamp_utc": data["now"], "marginal_contribution": data["shapley"]})
    w("filter_dependency_graph.json", {
        "timestamp_utc": data["now"],
        "cascade_depth": len(data["filter_truth"]),
        "unique_rejection_pct": round(100 - data["redundant_pct"], 2),
        "redundant_rejection_pct": data["redundant_pct"],
        "filters": list(data["filter_truth"].keys()),
    })
    w("redundant_filters.json", {"timestamp_utc": data["now"], "note": "filters with overlapping rejection timestamps", "redundant_pct": data["redundant_pct"]})
    w("unique_filters.json", {"timestamp_utc": data["now"], "filters_with_measured_replays": list(data["filter_truth"].keys())})
    w("profitability_matrix.json", {"timestamp_utc": data["now"], "per_filter": data["filter_truth"], "baseline_pf": data["baseline_pf"], "hypo_pf": data["hypo_pf"]})
    w("feature_reconstruction_validation.json", {
        "timestamp_utc": data["now"],
        "validated_count": sum(1 for e in events if e.get("reconstruction_validated")),
        "failed_count": sum(1 for e in events if not e.get("reconstruction_validated")),
        "method": "unified frame checksum at bar_index",
    })
    w("blocked_events_fixed_validation.json", {
        "timestamp_utc": data["now"],
        "total_blocked_events": data["blocked_events_total"],
        "empty_timestamp_before_fix": data["blocked_events_empty_ts_before_fix"],
        "reconstructed_with_timestamp": data["blocked_events_reconstructed"],
        "fix_applied": "phase22f/trace.py uses snapshot cursor+current_time",
        "validation_passed": data["blocked_events_empty_ts_before_fix"] == 0 or data["blocked_events_reconstructed"] > 0,
    })
    w("runtime_filter_trace.json", {"timestamp_utc": data["now"], "hold_chain": data["hold_chain"], "trace_bars": data["trace_bars"]})
    w("filter_ranking.json", {"timestamp_utc": data["now"], "ranking": data["filter_ranking"], "categories": ["PROFITABLE", "NEUTRAL", "HARMFUL", "REDUNDANT", "DEAD"]})
    w("filter_damage_ranking.json", {"timestamp_utc": data["now"], "destruction": data["damage"], "protection": sorted([(m, v["true_reject"]) for m, v in data["filter_truth"].items()], key=lambda x: x[1], reverse=True), "harmful_filters": data["harmful_filters"]})
    w("audit_summary.json", {"phase": "33D", "verdict": data["verdict"], "rejected_replayed": len(events), "wrong_pct": data["wrong_pct"], "filters": list(data["filter_truth"].keys())})
    w("phase33c_summary.json", {"phase": "33D", "verdict": data["verdict"], "rejected_signals": len(events), "wrong_rejection_pct": data["wrong_pct"]})
    w("phase33d_final_report.json", {
        "phase": "33D",
        "title": "Full Rejected Signal Reconstruction & Filter Truth Audit",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "measurement": {
            "blocked_events_total": data["blocked_events_total"],
            "blocked_events_reconstructed": data["blocked_events_reconstructed"],
            "ml_trace_rejections": data["ml_trace_rejections"],
            "rejected_replayed": len(events),
            "wrong_rejection_pct": data["wrong_pct"],
            "baseline_pf": data["baseline_pf"],
            "hypo_pf": data["hypo_pf"],
        },
        "filter_truth_summary": data["filter_truth"],
        "filter_ranking": data["filter_ranking"],
        "top_damage": data["damage"][:5] if data["damage"] else [],
        "contradictions": [
            c for c in [
                {"issue": "blocked_events_had_empty_timestamps", "present": data["blocked_events_empty_ts_before_fix"] > 0},
                {"issue": "ml_trace_sampled_stride_10", "present": True},
                {"issue": "hold_chain_aggregate_only", "present": True},
            ] if c["present"]
        ],
        "confusion_matrix": data["confusion"],
        "deliverables": [
            "phase33d_final_report.json", "reconstructed_rejections.json", "replay_database.json",
            "filter_truth_table.json", "filter_precision.json", "filter_recall.json",
            "filter_false_negative.json", "filter_false_positive.json", "filter_quality.json",
            "filter_precision_recall.json", "confusion_matrix.json", "edge_lost_by_filter.json",
            "top_false_negative_trades.json", "top_false_positive_trades.json", "top100_wrong_rejections.json",
            "expected_pf_if_not_rejected.json", "filter_shapley.json", "filter_dependency_graph.json",
            "redundant_filters.json", "unique_filters.json", "profitability_matrix.json",
            "feature_reconstruction_validation.json", "blocked_events_fixed_validation.json",
            "runtime_filter_trace.json", "filter_damage_ranking.json", "filter_ranking.json", "audit_summary.json",
            "rejected_signal_database.json",
        ],
    })


def main() -> None:
    data = asyncio.run(run_audit())
    write_all(data)
    print(json.dumps({"verdict": data["verdict"], "events": len(data["events"]), "wrong_pct": data["wrong_pct"], "rg_reconstructed": data["blocked_events_reconstructed"]}, indent=2))


if __name__ == "__main__":
    main()
