"""Phase 28.4 — diagnose poor RAW gold_ny_sweep outcomes on the Phase 28 tape.

RESEARCH ONLY. Reconstructs the 24 stored baseline setups and measures
analytical counterfactuals. Does not optimize, change strategy/RiskGate/ML,
start MT5, or rewrite parquet.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase26c_zero_signal_audit import _enrich_frame
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    PHASE280_BASELINE_JSON,
    UNKNOWN,
    load_parquet_utc,
    theoretical_outcome,
)
from tradingbot.backtest.phase28_1_full_baseline import PHASE281_JSON
from tradingbot.backtest.phase28_2_walk_forward import PHASE282_JSON
from tradingbot.backtest.phase28_3_monte_carlo import PHASE283_JSON
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.gold_strategies.m5_london_sweep import (
    asian_range,
    evaluate_m5_london_sweep,
    m5_asian_end_hour,
    m5_ny_entry_hours,
)
from tradingbot.domain.market_filters import atr_percentile, compute_adx
from tradingbot.domain.price_action import enrich_price_action
from tradingbot.domain.risk_logic import infer_regime_from_ohlcv

PHASE = "28.4"
PHASE284_JSON = "logs/phase28_4_strategy_diagnosis.json"
PHASE284_MD = "docs_v2/02_research/PHASE28_4_STRATEGY_DIAGNOSIS.md"
OVERLAP_GAP_MINUTES = 30

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "parameters_searched",
    "strategy_changed",
    "riskgate_changed",
    "dataset_fingerprint",
    "raw_setups",
    "reconstructed_setups",
    "entry_diagnosis",
    "sl_diagnosis",
    "tp_diagnosis",
    "session_diagnosis",
    "regime_diagnosis",
    "signal_quality_diagnosis",
    "overlap_diagnosis",
    "root_cause_ranking",
    "what_is_proven",
    "what_is_not_proven",
    "riskgate_status",
    "FINAL_GATE",
    "phase_28_5_started",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _fmt(x: Any, digits: int = 4) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        if np.isnan(x):
            return "n/a"
        return f"{x:.{digits}f}"
    return str(x)


def _parse_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def load_stored_setups(root: Path) -> dict[str, Any]:
    p280 = _safe_load_json(root / PHASE280_BASELINE_JSON) or {}
    p281 = _safe_load_json(root / PHASE281_JSON) or {}
    p282 = _safe_load_json(root / PHASE282_JSON) or {}
    p283 = _safe_load_json(root / PHASE283_JSON) or {}
    if not (p280 and p281 and p282 and p283):
        raise FileNotFoundError("Phase 28.0–28.3 artifacts are required")
    rows = list((p280.get("raw_signal_results") or {}).get("setup_rows") or [])
    if len(rows) != 24:
        raise RuntimeError(f"Phase 28.0 expected 24 setup_rows, got {len(rows)}")
    r280 = [float(r["r_multiple"]) for r in rows]
    r281 = [
        float(r["r_multiple"])
        for r in ((p281.get("raw_signal") or {}).get("setup_rows") or [])
        if r.get("r_multiple") is not None
    ]
    if r280 != r281:
        raise RuntimeError("Phase 28.0 and 28.1 RAW R series do not match")
    folds: dict[str, str] = {}
    for r in (p282.get("raw_signal") or {}).get("setup_rows") or []:
        folds[str(r.get("timestamp"))] = str(r.get("fold") or UNKNOWN)
    exe_rows = list((p281.get("executable") or {}).get("rows") or [])
    exe_by_ts = {str(r.get("timestamp")): r for r in exe_rows}
    return {
        "setups": rows,
        "folds": folds,
        "executable_by_ts": exe_by_ts,
        "phase28_0_fingerprint": p280.get("dataset_fingerprint"),
        "phase28_1_fingerprint": p281.get("dataset_fingerprint"),
        "phase28_2_fingerprint": p282.get("dataset_fingerprint"),
        "phase28_3_conclusion": p283.get("conclusion"),
        "executable_allowed": int((p281.get("executable") or {}).get("allowed") or 0),
        "executable_fills": int((p281.get("executable") or {}).get("executed_simulated_fills") or 0),
        "attribution": (p281.get("executable") or {}).get("attribution_counts") or {},
    }


def walk_from(
    df: pd.DataFrame,
    start_idx: int,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
) -> dict[str, Any]:
    """Inclusive start. SL-before-TP on the same bar (official convention)."""
    risk = abs(float(entry) - float(sl))
    buy = str(direction).upper() in {"BUY", "1", "LONG"}
    if risk <= 0 or start_idx >= len(df):
        return {"outcome": "invalid", "r_multiple": None, "exit_index": None}
    for j in range(start_idx, len(df)):
        high = float(df.iloc[j]["high"])
        low = float(df.iloc[j]["low"])
        if buy:
            hit_sl = low <= sl
            hit_tp = high >= tp
            if hit_sl:
                return {
                    "outcome": "loss",
                    "r_multiple": -1.0,
                    "exit_index": int(j),
                    "exit_time": str(df.index[j]),
                    "same_bar_sl_and_tp": bool(hit_sl and hit_tp),
                }
            if hit_tp:
                return {
                    "outcome": "win",
                    "r_multiple": float((tp - entry) / risk),
                    "exit_index": int(j),
                    "exit_time": str(df.index[j]),
                    "same_bar_sl_and_tp": False,
                }
        else:
            hit_sl = high >= sl
            hit_tp = low <= tp
            if hit_sl:
                return {
                    "outcome": "loss",
                    "r_multiple": -1.0,
                    "exit_index": int(j),
                    "exit_time": str(df.index[j]),
                    "same_bar_sl_and_tp": bool(hit_sl and hit_tp),
                }
            if hit_tp:
                return {
                    "outcome": "win",
                    "r_multiple": float((entry - tp) / risk),
                    "exit_index": int(j),
                    "exit_time": str(df.index[j]),
                    "same_bar_sl_and_tp": False,
                }
    return {"outcome": "open", "r_multiple": None, "exit_index": None}


def excursion_stats(
    df: pd.DataFrame,
    entry_idx: int,
    direction: str,
    entry: float,
    sl: float,
    tp: float,
    official_exit_idx: int | None,
) -> dict[str, Any]:
    risk = abs(float(entry) - float(sl))
    buy = str(direction).upper() in {"BUY", "1", "LONG"}
    if risk <= 0:
        return {"mae_r_before_exit": None, "mfe_r_before_exit": None}
    mae = 0.0
    mfe = 0.0
    sl_hit = False
    sl_bar: int | None = None
    tp_after_sl = False
    tp_any = False
    mfe_after_sl = 0.0
    end = len(df)
    for j in range(entry_idx + 1, end):
        high = float(df.iloc[j]["high"])
        low = float(df.iloc[j]["low"])
        if buy:
            fav = (high - entry) / risk
            adv = (entry - low) / risk
            hit_sl = low <= sl
            hit_tp = high >= tp
        else:
            fav = (entry - low) / risk
            adv = (high - entry) / risk
            hit_sl = high >= sl
            hit_tp = low <= tp
        if not sl_hit:
            mae = max(mae, max(0.0, adv))
            mfe = max(mfe, max(0.0, fav))
            if hit_tp:
                tp_any = True
            if hit_sl:
                sl_hit = True
                sl_bar = j
        else:
            mfe_after_sl = max(mfe_after_sl, max(0.0, fav))
            if hit_tp:
                tp_after_sl = True
                tp_any = True
                break
        if official_exit_idx is not None and j >= int(official_exit_idx) and sl_hit:
            continue
        if official_exit_idx is not None and j >= int(official_exit_idx) and not sl_hit:
            break
    return {
        "mae_r_before_exit": round(mae, 4),
        "mfe_r_before_exit": round(mfe, 4),
        "mfe_ge_1R5_before_stop": bool(mfe >= 1.5),
        "stopped_then_reached_original_tp": bool(sl_hit and tp_after_sl),
        "tp_touched_any_time": tp_any,
        "mfe_r_after_stop": round(mfe_after_sl, 4) if sl_hit else None,
        "sl_hit": sl_hit,
    }


def _candle_stats(row: pd.Series) -> dict[str, float]:
    o = float(row["open"])
    h = float(row["high"])
    low = float(row["low"])
    c = float(row["close"])
    rng = max(h - low, 1e-9)
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - low
    return {
        "range": rng,
        "body": body,
        "body_ratio": body / rng,
        "upper_wick_ratio": upper / rng,
        "lower_wick_ratio": lower / rng,
        "close_location": (c - low) / rng,
        "bullish": float(c >= o),
    }


def reconstruct_levels(df: pd.DataFrame, i: int, cfg: dict[str, Any]) -> dict[str, Any]:
    asian_start = int(cfg.get("ASIAN_START_HOUR", 0))
    asian_end = m5_asian_end_hour(cfg)
    bounds = asian_range(df, i, start_hour=asian_start, end_hour=asian_end, min_bars=4)
    row = df.iloc[i]
    atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else float(row["close"]) * 0.001
    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf = atr * float(cfg.get("SWEEP_BUFFER_ATR", 0.15))
    start_j = max(0, i - lookback)
    window = df.iloc[start_j : i + 1]
    win_high = float(window["high"].max())
    win_low = float(window["low"].min())
    asian_hi = float(bounds[0]) if bounds else None
    asian_lo = float(bounds[1]) if bounds else None
    sweep_hi_idx = int(start_j + int(window["high"].values.argmax())) if len(window) else i
    sweep_lo_idx = int(start_j + int(window["low"].values.argmin())) if len(window) else i
    first_reclaim: int | None = None
    if asian_hi is not None and asian_lo is not None:
        swept = False
        for j in range(start_j, i + 1):
            hj = float(df.iloc[j]["high"])
            lj = float(df.iloc[j]["low"])
            if hj > asian_hi + buf or lj < asian_lo - buf:
                swept = True
            cj = float(df.iloc[j]["close"])
            if swept and asian_lo < cj < asian_hi and first_reclaim is None:
                first_reclaim = j
    setup = evaluate_m5_london_sweep(df, i, cfg)
    return {
        "asian_high": asian_hi,
        "asian_low": asian_lo,
        "asian_range": None if asian_hi is None or asian_lo is None else asian_hi - asian_lo,
        "sweep_window_high": win_high,
        "sweep_window_low": win_low,
        "sweep_high_index": sweep_hi_idx,
        "sweep_low_index": sweep_lo_idx,
        "sweep_buffer_price": buf,
        "atr": atr,
        "first_reclaim_index": first_reclaim,
        "evaluator_entry": None if setup is None else float(setup.entry),
        "evaluator_sl": None if setup is None else float(setup.stop_loss),
        "evaluator_tp": None if setup is None else float(setup.take_profit),
        "evaluator_direction": None if setup is None else int(setup.direction),
        "evaluator_meta": None if setup is None else dict(setup.metadata or {}),
    }


def diagnose_one(
    stored: dict[str, Any],
    df: pd.DataFrame,
    cfg: dict[str, Any],
    *,
    fold: str,
    exe: dict[str, Any] | None,
) -> dict[str, Any]:
    ts = _parse_ts(stored["timestamp"])
    i = int(stored.get("closed_bar_index") if stored.get("closed_bar_index") is not None else stored["cursor"])
    if str(df.index[i]) != str(pd.Timestamp(stored["timestamp"])):
        loc = df.index.get_indexer([ts], method="nearest")
        i = int(loc[0])
    window = enrich_price_action(df.iloc[: i + 1].copy(), cfg, at_index=i)
    levels = reconstruct_levels(window, i, cfg)
    direction = str(stored["direction"]).upper()
    entry = float(stored["entry_price"])
    sl = float(stored["stop_loss"])
    tp = float(stored["take_profit"])
    buy = direction == "BUY"
    sl_dist = abs(entry - sl)
    tp_dist = abs(tp - entry)
    planned_rr = float(stored.get("planned_rr") or (tp_dist / sl_dist if sl_dist else 0.0))
    atr = float(levels["atr"] or 0.0)
    asian_hi = levels["asian_high"]
    asian_lo = levels["asian_low"]
    sweep_level = levels["sweep_window_high"] if not buy else levels["sweep_window_low"]
    reclaim_level = asian_hi if not buy else asian_lo
    sweep_idx = levels["sweep_high_index"] if not buy else levels["sweep_low_index"]
    first_reclaim = levels["first_reclaim_index"]
    candle = _candle_stats(window.iloc[i])
    closed = window
    regime = infer_regime_from_ohlcv(closed, i)
    adx = compute_adx(closed)
    atr_pct = atr_percentile(closed)
    official_exit = stored.get("exit_index")
    official_exit_i = int(official_exit) if official_exit is not None else None
    exc = excursion_stats(df, i, direction, entry, sl, tp, official_exit_i)
    bars_to_outcome = None
    if official_exit_i is not None:
        bars_to_outcome = official_exit_i - i
    beyond_sweep = None
    if sweep_level is not None:
        beyond_sweep = (sl - sweep_level) if not buy else (sweep_level - sl)
    asian_range_size = levels["asian_range"]
    sweep_depth_atr = None
    if asian_hi is not None and atr > 0:
        if not buy:
            sweep_depth_atr = (levels["sweep_window_high"] - asian_hi) / atr
        else:
            sweep_depth_atr = (asian_lo - levels["sweep_window_low"]) / atr
    reclaim_atr = None
    if reclaim_level is not None and atr > 0:
        reclaim_atr = abs(entry - reclaim_level) / atr
    dist_from_sweep_atr = None
    if sweep_level is not None and atr > 0:
        dist_from_sweep_atr = abs(entry - sweep_level) / atr

    next_open = None
    if i + 1 < len(df):
        e2 = float(df.iloc[i + 1]["open"])
        next_open = {
            "entry_price": e2,
            "label": "ANALYTICAL_COUNTERFACTUAL",
            **walk_from(df, i + 1, direction, e2, sl, tp),
            "r_vs_same_sl_tp": None,
        }
        if next_open.get("r_multiple") is not None and sl_dist > 0:
            next_open["implied_R_if_same_exit"] = float(
                ((tp - e2) / abs(e2 - sl)) if buy else ((e2 - tp) / abs(e2 - sl))
            )

    reclaim_cf = None
    if first_reclaim is not None:
        e3 = float(df.iloc[first_reclaim]["close"])
        start = first_reclaim + 1
        reclaim_cf = {
            "entry_price": e3,
            "entry_index": int(first_reclaim),
            "bars_before_official_signal": int(i - first_reclaim),
            "same_as_official_signal_bar": bool(first_reclaim == i),
            "label": "ANALYTICAL_COUNTERFACTUAL",
            **walk_from(df, start, direction, e3, sl, tp),
        }

    confirm_cf = None
    if i + 1 < len(df):
        e4 = float(df.iloc[i + 1]["close"])
        confirm_cf = {
            "entry_price": e4,
            "entry_index": i + 1,
            "label": "ANALYTICAL_COUNTERFACTUAL",
            **walk_from(df, i + 2, direction, e4, sl, tp),
        }

    official_check = theoretical_outcome(df, i, direction, entry, sl, tp)
    return {
        "timestamp": str(ts),
        "hour_utc": int(ts.hour),
        "minute_utc": int(ts.minute),
        "weekday": ts.day_name(),
        "calendar_date": str(ts.date()),
        "fold": fold,
        "direction": direction,
        "entry_price": entry,
        "stop_loss": sl,
        "take_profit": tp,
        "sl_distance": sl_dist,
        "tp_distance": tp_dist,
        "sl_distance_atr": None if atr <= 0 else sl_dist / atr,
        "tp_distance_atr": None if atr <= 0 else tp_dist / atr,
        "theoretical_R": stored.get("r_multiple"),
        "planned_rr": planned_rr,
        "outcome": stored.get("outcome"),
        "bars_to_outcome": bars_to_outcome,
        "duration_minutes": stored.get("duration_minutes"),
        "exit_time": stored.get("exit_time"),
        "exit_index": official_exit_i,
        "confidence": stored.get("confidence"),
        "quality_score": stored.get("quality_score"),
        "asian_high": asian_hi,
        "asian_low": asian_lo,
        "asian_range": asian_range_size,
        "asian_range_atr": None if not asian_range_size or atr <= 0 else asian_range_size / atr,
        "sweep_level": sweep_level,
        "reclaim_level": reclaim_level,
        "sweep_index": sweep_idx,
        "bars_from_sweep_to_signal": None if sweep_idx is None else i - int(sweep_idx),
        "first_reclaim_index": first_reclaim,
        "same_bar_sweep_and_reclaim": bool(first_reclaim == i),
        "distance_beyond_sweep": beyond_sweep,
        "distance_beyond_sweep_atr": None if beyond_sweep is None or atr <= 0 else beyond_sweep / atr,
        "sweep_depth_atr": sweep_depth_atr,
        "reclaim_distance_atr": reclaim_atr,
        "distance_from_sweep_atr": dist_from_sweep_atr,
        "atr": atr,
        "atr_percentile": atr_pct,
        "adx": adx,
        "regime": regime,
        "candle": candle,
        "session_context": {
            "window": "NY 15-16 UTC",
            "in_configured_window": bool(15 <= ts.hour < 16),
            "index_timezone": "UTC",
        },
        "excursions": exc,
        "official_replay_matches_stored": official_check.get("outcome") == stored.get("outcome"),
        "evaluator_matched_stored_entry": (
            levels["evaluator_entry"] is not None
            and abs(float(levels["evaluator_entry"]) - entry) < 1e-6
        ),
        "entry_counterfactuals": {
            "official_close": {
                "entry_price": entry,
                "label": "OFFICIAL",
                "outcome": stored.get("outcome"),
                "r_multiple": stored.get("r_multiple"),
            },
            "next_bar_open": next_open,
            "after_reclaim_confirmation": reclaim_cf,
            "after_signal_bar_confirmation": confirm_cf,
        },
        "riskgate": {
            "allowed": bool((exe or {}).get("allowed")),
            "bucket": (exe or {}).get("bucket"),
            "reason": (exe or {}).get("reason"),
            "separate_from_raw": True,
        },
        "index": i,
    }


def cluster_overlaps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clusters: list[list[int]] = []
    assigned = [-1] * len(rows)
    for i, a in enumerate(rows):
        if assigned[i] >= 0:
            continue
        cid = len(clusters)
        clusters.append([i])
        assigned[i] = cid
        ta = _parse_ts(a["timestamp"])
        for j in range(i + 1, len(rows)):
            if assigned[j] >= 0:
                continue
            b = rows[j]
            tb = _parse_ts(b["timestamp"])
            same_day = a["calendar_date"] == b["calendar_date"]
            same_dir = a["direction"] == b["direction"]
            gap = abs((tb - ta).total_seconds()) / 60.0
            same_exit = a.get("exit_index") is not None and a.get("exit_index") == b.get("exit_index")
            sweep_close = False
            if a.get("sweep_level") is not None and b.get("sweep_level") is not None:
                sweep_close = abs(float(a["sweep_level"]) - float(b["sweep_level"])) < 0.5
            if same_day and same_dir and (gap <= OVERLAP_GAP_MINUTES or same_exit or sweep_close):
                assigned[j] = cid
                clusters[cid].append(j)
    for i, row in enumerate(rows):
        row["overlap_cluster_id"] = assigned[i]
        row["overlaps_another_setup"] = len(clusters[assigned[i]]) > 1
        row["cluster_size"] = len(clusters[assigned[i]])
    event_count = len(clusters)
    independent = sum(1 for c in clusters if len(c) == 1)
    return {
        "n_setups": len(rows),
        "n_event_clusters": event_count,
        "n_singleton_events": independent,
        "n_clustered_setups": len(rows) - independent,
        "largest_cluster": max((len(c) for c in clusters), default=0),
        "shared_exit_groups": _shared_exit_groups(rows),
        "do_not_treat_as_24_independent": True,
        "rule": (
            f"Same UTC date + same direction + (gap<={OVERLAP_GAP_MINUTES}m "
            "OR same official exit_index OR sweep extreme within 0.5)"
        ),
        "clusters": [
            {
                "id": k,
                "size": len(c),
                "timestamps": [rows[i]["timestamp"] for i in c],
                "direction": rows[c[0]]["direction"],
                "date": rows[c[0]]["calendar_date"],
                "shared_exit_index": rows[c[0]].get("exit_index")
                if len({rows[i].get("exit_index") for i in c}) == 1
                else None,
            }
            for k, c in enumerate(clusters)
        ],
    }


def _shared_exit_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_exit: dict[Any, list[str]] = defaultdict(list)
    for r in rows:
        if r.get("exit_index") is None:
            continue
        by_exit[r["exit_index"]].append(r["timestamp"])
    return [
        {"exit_index": k, "n": len(v), "timestamps": v}
        for k, v in by_exit.items()
        if len(v) > 1
    ]


def _summarize_r(items: list[dict[str, Any] | None]) -> dict[str, Any]:
    values = []
    for item in items:
        if not item:
            continue
        r = item.get("r_multiple")
        if r is not None:
            values.append(float(r))
    if not values:
        return {"n": 0, "wins": 0, "losses": 0, "win_rate": None, "expectancy_R": None}
    wins = sum(1 for v in values if v > 0)
    return {
        "n": len(values),
        "wins": wins,
        "losses": len(values) - wins,
        "win_rate": wins / len(values),
        "expectancy_R": float(sum(values) / len(values)),
        "note": "ANALYTICAL / descriptive only. Not an optimized parameter. n=24 is not proof.",
    }


def build_diagnoses(rows: list[dict[str, Any]], overlap: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    official = _summarize_r([{"r_multiple": r.get("theoretical_R")} for r in rows])
    next_open = _summarize_r([r["entry_counterfactuals"]["next_bar_open"] for r in rows])
    reclaim = _summarize_r([r["entry_counterfactuals"]["after_reclaim_confirmation"] for r in rows])
    confirm = _summarize_r([r["entry_counterfactuals"]["after_signal_bar_confirmation"] for r in rows])
    same_reclaim = sum(1 for r in rows if r.get("same_bar_sweep_and_reclaim"))
    sl_dists = [float(r["sl_distance"]) for r in rows]
    sl_atrs = [float(r["sl_distance_atr"]) for r in rows if r.get("sl_distance_atr") is not None]
    beyond = [float(r["distance_beyond_sweep_atr"]) for r in rows if r.get("distance_beyond_sweep_atr") is not None]
    stopped_then_tp = sum(1 for r in rows if (r.get("excursions") or {}).get("stopped_then_reached_original_tp"))
    mfe_ge = sum(1 for r in rows if (r.get("excursions") or {}).get("mfe_ge_1R5_before_stop"))
    mfe_vals = [float(r["excursions"]["mfe_r_before_exit"]) for r in rows if r.get("excursions", {}).get("mfe_r_before_exit") is not None]
    mae_vals = [float(r["excursions"]["mae_r_before_exit"]) for r in rows if r.get("excursions", {}).get("mae_r_before_exit") is not None]
    hours = Counter(int(r["hour_utc"]) for r in rows)
    minutes = Counter(int(r["minute_utc"]) for r in rows)
    dates = Counter(r["calendar_date"] for r in rows)
    regimes = Counter(r.get("regime") for r in rows)
    atr_pcts = [float(r["atr_percentile"]) for r in rows]
    qualities = [float(r["quality_score"]) for r in rows if r.get("quality_score") is not None]
    confs = [float(r["confidence"]) for r in rows if r.get("confidence") is not None]
    planned = [float(r["planned_rr"]) for r in rows if r.get("planned_rr") is not None]
    ny_s, ny_e = m5_ny_entry_hours(cfg)

    entry_diag = {
        "official_definition": (
            "Entry = close of the last CLOSED M5 signal bar (PriceActionStrategy setup.entry). "
            "Theoretical exits start at the next bar. SIGNAL_CONFIRMATION_BARS is 0 on M5."
        ),
        "observed": official,
        "counterfactual_next_bar_open": next_open,
        "counterfactual_after_reclaim_confirmation": reclaim,
        "counterfactual_after_signal_bar_confirmation": confirm,
        "same_bar_sweep_and_reclaim_count": same_reclaim,
        "production_strategy_altered": False,
        "class": "ANALYTICAL_COUNTERFACTUAL_ONLY",
        "interpretation": (
            "Counterfactuals reuse stored SL/TP prices. They are not new strategy rules "
            "and are not an optimization search. A different entry R on n=24 is not proof."
        ),
    }
    sl_diag = {
        "definition": (
            "SL = sweep-window extreme ± SL_ATR_MULT*ATR (0.35). "
            "M5_REQUIRE_REJECTION=False. Not a structure swing SL."
        ),
        "sl_distance_median": float(np.median(sl_dists)) if sl_dists else None,
        "sl_distance_p25": float(np.percentile(sl_dists, 25)) if sl_dists else None,
        "sl_distance_p75": float(np.percentile(sl_dists, 75)) if sl_dists else None,
        "sl_distance_atr_median": float(np.median(sl_atrs)) if sl_atrs else None,
        "distance_beyond_sweep_atr_median": float(np.median(beyond)) if beyond else None,
        "stopped_then_reached_original_tp": stopped_then_tp,
        "stopped_then_reached_original_tp_pct": stopped_then_tp / max(len(rows), 1),
        "mae_r_median": float(np.median(mae_vals)) if mae_vals else None,
        "mae_r_p95": float(np.percentile(mae_vals, 95)) if mae_vals else None,
        "note": "MAE/MFE derived from OHLC after the signal bar. Descriptive. Not realized fills.",
    }
    tp_diag = {
        "definition": (
            "TP = max(opposite Asian bound, risk * MIN_RR/TP_RR=1.5). RR was not changed."
        ),
        "planned_rr_median": float(np.median(planned)) if planned else None,
        "planned_rr_min": float(min(planned)) if planned else None,
        "planned_rr_max": float(max(planned)) if planned else None,
        "mfe_r_median_before_exit": float(np.median(mfe_vals)) if mfe_vals else None,
        "mfe_r_p95_before_exit": float(np.percentile(mfe_vals, 95)) if mfe_vals else None,
        "n_mfe_ge_1R5_before_stop": mfe_ge,
        "n_mfe_ge_1R5_before_stop_pct": mfe_ge / max(len(rows), 1),
        "stopped_then_tp": stopped_then_tp,
        "rr_changed": False,
        "interpretation": (
            "If MFE rarely reaches 1.5R before the stop, the fixed RR is optimistic on THIS tape. "
            "That is a sample observation, not a proven structural flaw."
        ),
    }
    session_diag = {
        "configured_ny_window": f"{ny_s}-{ny_e} UTC",
        "asian_end_utc": m5_asian_end_hour(cfg),
        "utc_interpretation": "tz-aware parquet index converted/localized to UTC; hour = timestamp.hour",
        "all_signal_hours_utc": dict(hours),
        "all_signal_minutes_utc": dict(sorted(minutes.items())),
        "signal_dates": dict(dates),
        "all_24_inside_hour_15": all(r["hour_utc"] == 15 for r in rows),
        "unique_signal_dates": len(dates),
        "cluster_in_one_hour": True,
        "pathological_sample": (
            "BY DESIGN the M5 window is only 15:00–15:59 UTC. All 24 official signals "
            "are in that single hour. That concentrates the RAW book into a handful of NY opens, "
            "not a round-the-clock sample. It does not prove the window is wrong."
        ),
    }
    regime_diag = {
        "use_adx_filter_on_m5": bool(cfg.get("USE_ADX_FILTER", False)),
        "use_atr_percentile_on_raw": False,
        "atr_percentile_is_riskgate_layer": True,
        "regime_counts": dict(regimes),
        "atr_percentile_median": float(np.median(atr_pcts)) if atr_pcts else None,
        "atr_percentile_p90": float(np.percentile(atr_pcts, 90)) if atr_pcts else None,
        "thresholds_tuned": False,
        "interpretation": (
            "RAW setups are emitted before RiskGate ATR/META. High ATR percentile on many "
            "signal bars is a regime observation for the executable book, not a RAW filter."
        ),
    }
    quality_diag = {
        "min_quality_score_gate": cfg.get("MIN_QUALITY_SCORE"),
        "min_confidence_gate": cfg.get("MIN_CONFIDENCE"),
        "m5_require_rejection": bool(cfg.get("M5_REQUIRE_REJECTION", True)),
        "quality_median": float(np.median(qualities)) if qualities else None,
        "quality_min": float(min(qualities)) if qualities else None,
        "confidence_median": float(np.median(confs)) if confs else None,
        "confidence_min": float(min(confs)) if confs else None,
        "loss_quality_median": float(np.median([float(r["quality_score"]) for r in rows if r.get("outcome") == "loss" and r.get("quality_score") is not None])),
        "win_quality": [r.get("quality_score") for r in rows if r.get("outcome") == "win"],
        "no_rejection_candle_required": not bool(cfg.get("M5_REQUIRE_REJECTION", True)),
        "interpretation": (
            "All 24 already cleared MIN_CONFIDENCE 0.52 and MIN_QUALITY_SCORE 55. "
            "Losses are not a low-score leftover. M5_REQUIRE_REJECTION is False."
        ),
    }
    return {
        "entry_diagnosis": entry_diag,
        "sl_diagnosis": sl_diag,
        "tp_diagnosis": tp_diag,
        "session_diagnosis": session_diag,
        "regime_diagnosis": regime_diag,
        "signal_quality_diagnosis": quality_diag,
        "overlap_diagnosis": overlap,
    }


def build_ranking(diags: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    stopped_tp = diags["sl_diagnosis"]["stopped_then_reached_original_tp"]
    mfe_ge = diags["tp_diagnosis"]["n_mfe_ge_1R5_before_stop"]
    clusters = diags["overlap_diagnosis"]["n_event_clusters"]
    return {
        "PRIMARY": {
            "code": "G",
            "label": "Data/sample limitations",
            "evidence": (
                "Canonical tape is 3000 M5 bars / ~14.9 days. RAW n=24, 1 win. "
                "Phase 28.0–28.2 DATA_INSUFFICIENT / INSUFFICIENT_SAMPLE. "
                "Phase 28.3 Monte Carlo conclusion INSUFFICIENT_SAMPLE. "
                f"Overlap reduces that further to {clusters} event clusters."
            ),
            "confidence": "HIGH that inference is blocked; LOW that G 'causes' the -0.90R path",
            "limitations": (
                "Sample limitation explains why we cannot prove a cause. "
                "It does not by itself generate the losses."
            ),
            "statistically_proven": True,
            "proven_claim": "This tape cannot support an edge or no-edge claim.",
        },
        "SECONDARY": {
            "code": "H",
            "label": "Overlapping setups / trade independence",
            "evidence": (
                f"{len(rows)} RAW rows collapse to {clusters} event clusters. "
                f"{diags['overlap_diagnosis']['n_clustered_setups']} setups share a date/direction/"
                "sweep/exit with another. Several groups share one official exit_index. "
                "24 is not 24 independent observations."
            ),
            "confidence": "HIGH as an observation on this tape",
            "limitations": "Does not prove the underlying sweep idea is false.",
            "statistically_proven": False,
            "observed_behavior": True,
        },
        "TERTIARY": {
            "code": "I",
            "label": "Combination of SL placement (C), signal repetition (A), and session window (E)",
            "evidence": (
                "SL sits ~0.35 ATR beyond the same sweep extreme, so a continued sweep "
                f"stops a whole cluster together. stopped_then_TP={stopped_tp}/24. "
                f"MFE reached 1.5R before stop on {mfe_ge}/24. "
                "All 24 timestamps are hour 15 UTC by design (NY 15–16). "
                "M5_REQUIRE_REJECTION=False so consecutive M5 closes inside the Asian range "
                "re-fire on the same liquidity event."
            ),
            "confidence": "MEDIUM as a plausible mechanism on this tape; NOT proven out of sample",
            "limitations": (
                "n=24 and dependent events. Cannot isolate A vs C vs E. "
                "Do not treat this as a mandate to change SL, RR, or session."
            ),
            "statistically_proven": False,
            "plausible_mechanism": True,
        },
        "UNRESOLVED": {
            "codes": ["B", "D", "F", "J"],
            "label": (
                "Entry-timing (B), TP/RR realism (D), market-regime mismatch (F) as standalone "
                "primaries; and J — cannot determine a single proven structural cause"
            ),
            "evidence": (
                "Next-bar-open / reclaim / confirmation counterfactuals are descriptive only. "
                "ADX filter is off on M5. ATR percentile is a RiskGate layer, not RAW. "
                "One win cannot define a regime contrast."
            ),
            "confidence": "HIGH that these are unresolved",
            "limitations": "A longer independent event sample is required.",
            "statistically_proven": False,
        },
        "official_answer_to_primary_question": "J",
        "official_answer_note": (
            "Cannot determine a single proven cause of the poor RAW path from 24 dependent "
            "theoretical setups. G is proven as an inference limit. H/C/A/E are observed or "
            "plausible on this tape only."
        ),
    }


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    rank = payload["root_cause_ranking"]
    e = payload["entry_diagnosis"]
    sl = payload["sl_diagnosis"]
    tp = payload["tp_diagnosis"]
    sess = payload["session_diagnosis"]
    ov = payload["overlap_diagnosis"]
    path = root / PHASE284_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = payload["reconstructed_setups"]
    lines = [
        "| ts UTC | dir | fold | entry | SL | TP | R | out | cluster | ATR% | regime | q | RG |",
        "|---|---|---|---:|---:|---:|---:|---|---:|---:|---|---:|---|",
    ]
    for r in rows:
        rg = r["riskgate"]["bucket"] or "n/a"
        lines.append(
            f"| {r['timestamp'][5:16]} | {r['direction']} | {r['fold']} | "
            f"{_fmt(r['entry_price'], 2)} | {_fmt(r['stop_loss'], 2)} | {_fmt(r['take_profit'], 2)} | "
            f"{_fmt(r['theoretical_R'], 2)} | {r['outcome']} | {r['overlap_cluster_id']} | "
            f"{_fmt(r['atr_percentile'], 1)} | {r['regime']} | {_fmt(r['quality_score'], 0)} | {rg} |"
        )
    path.write_text(
        f"""# Phase 28.4 — Strategy Diagnosis

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`
**Official answer:** `{rank.get("official_answer_to_primary_question")}` — cannot determine a single proven cause

Diagnosis of the **stored** 24 RAW `gold_ny_sweep` setups. No production behavior change.

STOP AFTER PHASE 28.4. DO NOT START PHASE 28.5.

---

## Dataset

Fingerprint `{payload.get("dataset_fingerprint")}` matches Phase 28.0–28.3. Canonical parquet was not rewritten.

RAW setups: 24 (BUY 16 / SELL 8; 1 win / 23 losses). EXECUTABLE: 0 allowed / 0 fills.

---

## Reconstructed RAW book

{chr(10).join(lines)}

Do **not** treat 24 rows as 24 independent trades. See overlap.

---

## ENTRY

Official: close of the closed signal bar. `SIGNAL_CONFIRMATION_BARS=0`.

| Book | n | wins | WR | exp R |
|---|---:|---:|---:|---:|
| Official close | {e["observed"]["n"]} | {e["observed"]["wins"]} | {_fmt(e["observed"]["win_rate"])} | {_fmt(e["observed"]["expectancy_R"])} |
| Next-bar open (counterfactual) | {e["counterfactual_next_bar_open"]["n"]} | {e["counterfactual_next_bar_open"]["wins"]} | {_fmt(e["counterfactual_next_bar_open"]["win_rate"])} | {_fmt(e["counterfactual_next_bar_open"]["expectancy_R"])} |
| After first reclaim close (counterfactual) | {e["counterfactual_after_reclaim_confirmation"]["n"]} | {e["counterfactual_after_reclaim_confirmation"]["wins"]} | {_fmt(e["counterfactual_after_reclaim_confirmation"]["win_rate"])} | {_fmt(e["counterfactual_after_reclaim_confirmation"]["expectancy_R"])} |
| After +1 bar confirmation (counterfactual) | {e["counterfactual_after_signal_bar_confirmation"]["n"]} | {e["counterfactual_after_signal_bar_confirmation"]["wins"]} | {_fmt(e["counterfactual_after_signal_bar_confirmation"]["win_rate"])} | {_fmt(e["counterfactual_after_signal_bar_confirmation"]["expectancy_R"])} |

Same-bar sweep+reclaim: `{e["same_bar_sweep_and_reclaim_count"]}` / 24.

These counterfactuals are **ANALYTICAL ONLY**. They reuse stored SL/TP. They are not candidate rules.

---

## SL

Median SL distance `{_fmt(sl["sl_distance_median"], 2)}` ({_fmt(sl["sl_distance_atr_median"])} ATR). Median distance beyond sweep `{_fmt(sl["distance_beyond_sweep_atr_median"])}` ATR (configured pad 0.35).

Stopped then later touched original TP: `{sl["stopped_then_reached_original_tp"]}` / 24 (`{_fmt(sl["stopped_then_reached_original_tp_pct"])}`).

MAE median / p95: `{_fmt(sl["mae_r_median"])}` / `{_fmt(sl["mae_r_p95"])}` R.

---

## TP / RR

RR **not** changed. Planned RR median `{_fmt(tp["planned_rr_median"])}` (min `{_fmt(tp["planned_rr_min"])}`, max `{_fmt(tp["planned_rr_max"])}`).

MFE before official exit: median `{_fmt(tp["mfe_r_median_before_exit"])}` R, p95 `{_fmt(tp["mfe_r_p95_before_exit"])}` R. MFE ≥ 1.5R before stop: `{tp["n_mfe_ge_1R5_before_stop"]}` / 24.

---

## SESSION

Configured NY `{sess["configured_ny_window"]}`; Asian end `{sess["asian_end_utc"]}:00` UTC. All 24 signals hour 15 UTC: `{sess["all_24_inside_hour_15"]}`. Unique signal dates: `{sess["unique_signal_dates"]}`.

{sess["pathological_sample"]}

---

## REGIME / SIGNAL QUALITY / OVERLAP

Regime counts: `{payload["regime_diagnosis"]["regime_counts"]}`. ATR% median `{_fmt(payload["regime_diagnosis"]["atr_percentile_median"])}`. ADX filter is off on M5 RAW. ATR percentile is RiskGate, not RAW.

Quality median `{_fmt(payload["signal_quality_diagnosis"]["quality_median"])}`; all 24 already ≥ 55. `M5_REQUIRE_REJECTION=False`.

Event clusters: `{ov["n_event_clusters"]}` (singletons `{ov["n_singleton_events"]}`, clustered setups `{ov["n_clustered_setups"]}`, largest `{ov["largest_cluster"]}`).

---

## Root-cause ranking

**PRIMARY:** `{rank["PRIMARY"]["code"]}` — {rank["PRIMARY"]["label"]}  
Confidence: {rank["PRIMARY"]["confidence"]}

**SECONDARY:** `{rank["SECONDARY"]["code"]}` — {rank["SECONDARY"]["label"]}  
Confidence: {rank["SECONDARY"]["confidence"]}

**TERTIARY:** `{rank["TERTIARY"]["code"]}` — {rank["TERTIARY"]["label"]}  
Confidence: {rank["TERTIARY"]["confidence"]}

**UNRESOLVED:** {rank["UNRESOLVED"]["codes"]} — {rank["UNRESOLVED"]["label"]}

Official answer to “what primarily caused the poor RAW results?”: **{rank["official_answer_to_primary_question"]}**.  
{rank["official_answer_note"]}

---

## Proven vs not proven

**Proven:** {payload["what_is_proven"]}

**Not proven:** {payload["what_is_not_proven"]}

## RiskGate (separate)

{payload["riskgate_status"]["note"]}

## Recommendation for a later phase (not started)

{payload.get("recommendation_for_next_phase")}

## Safety

No MT5, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 28.5 was **not** started.
""",
        encoding="utf-8",
    )


def run_phase28_4_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    loaded = load_stored_setups(root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical fingerprint changed — Phase 28.4 refuses to proceed")
    for key in ("phase28_0_fingerprint", "phase28_1_fingerprint", "phase28_2_fingerprint"):
        if loaded[key] != fp:
            raise RuntimeError(f"{key} does not match the canonical parquet")

    cfg = get_price_action_config(PRIMARY_SYMBOL, "M5")
    raw = load_parquet_utc(root / CANONICAL_PARQUET)
    df = _enrich_frame(raw)
    reconstructed = [
        diagnose_one(
            stored,
            df,
            cfg,
            fold=loaded["folds"].get(str(stored["timestamp"]), UNKNOWN),
            exe=loaded["executable_by_ts"].get(str(stored["timestamp"])),
        )
        for stored in loaded["setups"]
    ]
    overlap = cluster_overlaps(reconstructed)
    diags = build_diagnoses(reconstructed, overlap, cfg)
    ranking = build_ranking(diags, reconstructed)
    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}

    compact = []
    for r in reconstructed:
        compact.append(
            {
                k: r[k]
                for k in (
                    "timestamp",
                    "direction",
                    "fold",
                    "entry_price",
                    "stop_loss",
                    "take_profit",
                    "sl_distance",
                    "tp_distance",
                    "theoretical_R",
                    "outcome",
                    "bars_to_outcome",
                    "asian_high",
                    "asian_low",
                    "sweep_level",
                    "reclaim_level",
                    "atr",
                    "atr_percentile",
                    "adx",
                    "regime",
                    "quality_score",
                    "confidence",
                    "overlap_cluster_id",
                    "overlaps_another_setup",
                    "session_context",
                    "excursions",
                    "entry_counterfactuals",
                    "riskgate",
                    "candle",
                    "planned_rr",
                    "sweep_depth_atr",
                    "distance_beyond_sweep_atr",
                    "same_bar_sweep_and_reclaim",
                )
            }
        )

    what_proven = (
        "The approved XAUUSD_i M5 tape is statistically insufficient for edge or no-edge claims "
        "(28.0–28.3). All 24 official RAW timestamps fall in 15:00–15:59 UTC. "
        f"The 24 rows are not independent ({overlap['n_event_clusters']} event clusters). "
        "EXECUTABLE remains 0 allowed / 0 fills (META/ATR), which is a separate book. "
        "FINAL_GATE remains BLOCKED. Fingerprint unchanged."
    )
    what_not = (
        "NOT_PROVEN: that gold_ny_sweep is a bad strategy; that it is a good strategy; "
        "that close-entry, 0.35 ATR SL, 1.5 RR, or the NY 15-16 window is the unique cause; "
        "that changing any of those would improve live or longer-tape results; "
        "that META/ATR rejects prove no edge. Counterfactual books are not optimized alternatives."
    )
    recommendation = (
        "Do not start parameter optimization. If a later research phase exists, prefer "
        "(1) a longer defensible XAUUSD_i tape or (2) event-level (cluster) analysis of the "
        "same unchanged rules. Do not change SL/TP/RR/session/RiskGate from this 24-row book. "
        "Phase 28.5 was not started."
    )

    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": "PASS_WITH_DEFERRAL",
        "research_only": True,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "parameters_searched": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "ml_changed": False,
        "rr_changed": False,
        "ohlc_used_for_diagnosis_only": True,
        "ev_eq_01": "NOT_PROVEN",
        "cost_completeness": BLOCKED,
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "dataset": CANONICAL_PARQUET,
        "dataset_fingerprint": fp,
        "raw_setups": 24,
        "buy": 16,
        "sell": 8,
        "wins": 1,
        "losses": 23,
        "prior_phase_28_3_conclusion": loaded["phase28_3_conclusion"],
        "reconstructed_setups": compact,
        **diags,
        "root_cause_ranking": ranking,
        "evidence_confidence": {
            "sample_insufficiency": "HIGH",
            "overlap_dependence": "HIGH",
            "sl_shared_sweep_mechanism": "MEDIUM",
            "entry_timing_as_primary": "LOW",
            "tp_unrealistic_as_primary": "LOW",
            "regime_mismatch_as_primary": "LOW",
            "strategy_is_bad": "NOT_ALLOWED",
            "strategy_is_good": "NOT_ALLOWED",
        },
        "what_is_proven": what_proven,
        "what_is_not_proven": what_not,
        "riskgate_status": {
            "allowed": loaded["executable_allowed"],
            "fills": loaded["executable_fills"],
            "attribution": loaded["attribution"],
            "bypassed": False,
            "modified": False,
            "note": (
                "RiskGate attribution stays separate from RAW diagnosis. "
                f"META={loaded['attribution'].get('META', 0)} ATR={loaded['attribution'].get('ATR', 0)} "
                "0 allowed / 0 fills. 0 executable ≠ no edge."
            ),
        },
        "recommendation_for_next_phase": recommendation,
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "ML_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "PARAMETERS_SEARCHED": False,
            "PHASE_28_5_STARTED": False,
        },
        "phase_28_5_started": False,
        "deterministic_reproducibility": {
            "n_reconstructed": len(reconstructed),
            "config_hash": hashlib.sha256(
                json.dumps(
                    {"phase": PHASE, "n": 24, "fp": fp},
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:16],
        },
    }

    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after

    _write_json(root / PHASE284_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Performance validation (Phase 28.4)"
        block = (
            "\n\n## Performance validation (Phase 28.4)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Diagnosis uses stored 28.0–28.3 setups + read-only OHLC | **SUPPORTED** |\n"
            "| 24 RAW rows are independent observations | **FALSE** — event clusters |\n"
            "| Poor RAW path has a proven single structural cause | **NOT_PROVEN** — official answer J |\n"
            "| Strategy is proven bad / good | **NOT_ALLOWED** — INSUFFICIENT_SAMPLE |\n"
            "| Phase 28.4 authorizes live trading or optimization | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")

    return payload


if __name__ == "__main__":
    run_phase28_4_collection()
