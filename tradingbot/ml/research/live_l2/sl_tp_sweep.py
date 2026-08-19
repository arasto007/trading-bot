"""L2.5 — SL/TP parameter sweep on best L2 hypotheses (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.live_l2.edge_discovery import (
    FUTURE_WINDOW,
    GATE_MIN_TRADES_YEAR,
    GATE_MIN_YEARS_PASS,
    GATE_PF,
    STRIDE,
    WARMUP,
    _atr,
    _evaluate_gate,
    _hypothesis_report,
    _pf_from_labels,
    _scan_hypothesis,
    _yearly_stats,
)
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    HYPOTHESES_R2,
    _prepare_frame_round2,
)
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast

ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = ROOT / "live_l2_sl_tp_sweep_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
YEAR_START = 2021
YEAR_END = 2026
GOLD_ATR_SL_DEFAULT = 2.0
GOLD_RR_DEFAULT = 2.5
XAUUSD_PIP_SIZE = 0.01
PRODUCTION_AUDIT_SAMPLE = 500


def _sl_tp_atr_rr(
    entry: float,
    direction: int,
    atr: float,
    *,
    atr_mult: float,
    rr: float,
) -> tuple[float, float]:
    if not np.isfinite(atr) or atr <= 0 or entry <= 0:
        return 0.0, 0.0
    sl_dist = atr * atr_mult
    if direction > 0:
        sl = entry - sl_dist
        tp = entry + sl_dist * rr
    else:
        sl = entry + sl_dist
        tp = entry - sl_dist * rr
    return float(sl), float(tp)


def _sl_tp_fixed_pips(
    entry: float,
    direction: int,
    atr: float,
    *,
    pip_sl: float,
    rr: float = GOLD_RR_DEFAULT,
) -> tuple[float, float]:
    if entry <= 0:
        return 0.0, 0.0
    sl_dist = pip_sl * XAUUSD_PIP_SIZE
    if direction > 0:
        sl = entry - sl_dist
        tp = entry + sl_dist * rr
    else:
        sl = entry + sl_dist
        tp = entry - sl_dist * rr
    return float(sl), float(tp)


def _make_sl_tp_fn(
    mode: str,
    *,
    atr_mult: float | None = None,
    rr: float | None = None,
    pip_sl: float | None = None,
) -> Callable[[float, int, float], tuple[float, float]]:
    if mode == "production":
        return lambda _entry, _direction, _atr: (0.0, 0.0)

    if mode == "atr_rr":

        def fn(entry: float, direction: int, atr: float) -> tuple[float, float]:
            return _sl_tp_atr_rr(
                entry,
                direction,
                atr,
                atr_mult=float(atr_mult or GOLD_ATR_SL_DEFAULT),
                rr=float(rr or GOLD_RR_DEFAULT),
            )

        return fn

    if mode == "fixed_pips":

        def fn(entry: float, direction: int, atr: float) -> tuple[float, float]:
            return _sl_tp_fixed_pips(
                entry,
                direction,
                atr,
                pip_sl=float(pip_sl or 100),
                rr=float(rr or GOLD_RR_DEFAULT),
            )

        return fn

    raise ValueError(f"unknown sl_tp mode: {mode}")


def _resolve_trade_with_sl_tp_fn(
    candles: pd.DataFrame,
    frame: pd.DataFrame,
    idx: int,
    direction: int,
    sl_tp_fn: Callable[[float, int, float], tuple[float, float]],
    *,
    use_production: bool = False,
    future_window: int = FUTURE_WINDOW,
) -> int | None:
    if idx < WARMUP or idx >= len(candles) - future_window - 1:
        return None
    entry = float(candles["close"].iloc[idx])
    atr = float(frame["atr14"].iloc[idx]) if "atr14" in frame.columns else _atr(
        candles["high"], candles["low"], candles["close"], 14
    ).iloc[idx]
    if use_production:
        sl, tp = production_sl_tp_at_bar_fast(candles, idx, direction)
    else:
        sl, tp = sl_tp_fn(entry, direction, float(atr))
    if sl <= 0 or tp <= 0:
        return None
    resolved = resolve_label_with_sl_tp(
        candles,
        idx,
        direction,
        sl,
        tp,
        future_window_bars=future_window,
        entry_price=entry,
    )
    label = int(resolved["label"])
    if label == int(Label.NO_RESOLUTION):
        return None
    return 1 if label == int(Label.TP_FIRST) else 0


def _scan_hypothesis_sl_tp(
    frame: pd.DataFrame,
    candles: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame, int], int | None],
    sl_tp_fn: Callable[[float, int, float], tuple[float, float]],
    *,
    use_production: bool = False,
    stride: int = STRIDE,
) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    indices = range(WARMUP, len(frame) - FUTURE_WINDOW - 1, stride)
    for idx in indices:
        direction = signal_fn(frame, idx)
        if direction not in (1, -1):
            continue
        outcome = _resolve_trade_with_sl_tp_fn(
            candles,
            frame,
            idx,
            direction,
            sl_tp_fn,
            use_production=use_production,
        )
        if outcome is None:
            continue
        trades.append(
            {
                "bar_index": idx,
                "timestamp": str(frame.index[idx]),
                "year": int(frame.index[idx].year),
                "direction": "BUY" if direction > 0 else "SELL",
                "outcome": outcome,
            }
        )
    return trades


def _config_report(
    config_id: str,
    config_meta: dict[str, Any],
    trades: list[dict[str, Any]],
) -> dict[str, Any]:
    yearly = _yearly_stats(trades)
    gate = _evaluate_gate(yearly)
    labels = [int(t["outcome"]) for t in trades]
    wins = sum(labels)
    return {
        "config_id": config_id,
        **config_meta,
        "total_trades": len(trades),
        "overall_pf": _pf_from_labels(labels) if labels else 0.0,
        "overall_win_rate_pct": round(wins / len(labels) * 100, 2) if labels else 0.0,
        "yearly": yearly,
        "gate": gate,
        "honest_edge": gate["gate_pass"],
    }


def _build_sweep_configs() -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = [
        {
            "config_id": "PRODUCTION_BASELINE",
            "mode": "production",
            "description": "production compute_sl_tp (gold ATR>=2.0, RR>=2.5)",
        },
    ]
    for rr in (1.0, 1.5, 2.0, 2.5, 3.0):
        configs.append(
            {
                "config_id": f"ATR2.0_RR{rr}",
                "mode": "atr_rr",
                "atr_mult": GOLD_ATR_SL_DEFAULT,
                "rr": rr,
                "description": f"ATR SL x{GOLD_ATR_SL_DEFAULT}, RR={rr}",
            }
        )
    for atr_mult in (1.0, 1.5, 2.0):
        configs.append(
            {
                "config_id": f"ATR{atr_mult}_RR2.5",
                "mode": "atr_rr",
                "atr_mult": atr_mult,
                "rr": GOLD_RR_DEFAULT,
                "description": f"ATR SL x{atr_mult}, RR={GOLD_RR_DEFAULT}",
            }
        )
    for pip_sl in (50, 100, 150):
        configs.append(
            {
                "config_id": f"FIXED_{pip_sl}PIPS_RR2.5",
                "mode": "fixed_pips",
                "pip_sl": pip_sl,
                "rr": GOLD_RR_DEFAULT,
                "description": f"Fixed {pip_sl} pip SL, RR={GOLD_RR_DEFAULT}",
            }
        )
    return configs


def audit_production_sl_tp(
    candles: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    sample_size: int = PRODUCTION_AUDIT_SAMPLE,
) -> dict[str, Any]:
    """Document production RR distribution on a stratified sample."""
    indices = np.linspace(WARMUP, len(frame) - FUTURE_WINDOW - 2, sample_size, dtype=int)
    rr_values: list[float] = []
    sl_dist_pips: list[float] = []
    tp_dist_pips: list[float] = []
    atr_mult_implied: list[float] = []

    for idx in indices:
        for direction in (1, -1):
            entry = float(candles["close"].iloc[idx])
            sl, tp = production_sl_tp_at_bar_fast(candles, idx, direction)
            if sl <= 0 or tp <= 0 or entry <= 0:
                continue
            sl_dist = abs(entry - sl)
            tp_dist = abs(tp - entry)
            rr = tp_dist / sl_dist if sl_dist > 0 else 0.0
            atr = float(frame["atr14"].iloc[idx]) if "atr14" in frame.columns else np.nan
            rr_values.append(rr)
            sl_dist_pips.append(sl_dist / XAUUSD_PIP_SIZE)
            tp_dist_pips.append(tp_dist / XAUUSD_PIP_SIZE)
            if np.isfinite(atr) and atr > 0:
                atr_mult_implied.append(sl_dist / atr)

    if not rr_values:
        return {"verdict": "NO_SAMPLES", "sample_size": 0}

    rr_arr = np.array(rr_values)
    sl_arr = np.array(sl_dist_pips)
    tp_arr = np.array(tp_dist_pips)
    atr_arr = np.array(atr_mult_implied) if atr_mult_implied else np.array([0.0])

    return {
        "verdict": "AUDIT_COMPLETE",
        "sample_bars": int(len(indices)),
        "sample_trades_both_directions": len(rr_values),
        "production_defaults": {
            "gold_sl_atr_mult_min": GOLD_ATR_SL_DEFAULT,
            "gold_rr_min": GOLD_RR_DEFAULT,
            "source": "tradingbot.domain.signal_helpers.compute_sl_tp",
        },
        "rr_distribution": {
            "mean": round(float(rr_arr.mean()), 4),
            "median": round(float(np.median(rr_arr)), 4),
            "std": round(float(rr_arr.std()), 4),
            "min": round(float(rr_arr.min()), 4),
            "max": round(float(rr_arr.max()), 4),
            "p25": round(float(np.percentile(rr_arr, 25)), 4),
            "p75": round(float(np.percentile(rr_arr, 75)), 4),
            "pct_at_2_5": round(float((rr_arr >= 2.49).mean() * 100), 2),
        },
        "sl_distance_pips": {
            "mean": round(float(sl_arr.mean()), 2),
            "median": round(float(np.median(sl_arr)), 2),
            "p25": round(float(np.percentile(sl_arr, 25)), 2),
            "p75": round(float(np.percentile(sl_arr, 75)), 2),
        },
        "tp_distance_pips": {
            "mean": round(float(tp_arr.mean()), 2),
            "median": round(float(np.median(tp_arr)), 2),
        },
        "implied_atr_sl_mult": {
            "mean": round(float(atr_arr.mean()), 4) if len(atr_arr) else 0.0,
            "median": round(float(np.median(atr_arr)), 4) if len(atr_arr) else 0.0,
        },
        "interpretation_en": (
            "Production gold SL/TP uses ATR mult >=2.0 and RR >=2.5; "
            "high RR requires ~29% win rate for breakeven at RR=2.5."
        ),
    }


def run_sl_tp_sweep(
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    year_start: int = YEAR_START,
    year_end: int = YEAR_END,
    hypotheses: tuple[str, ...] = ("PULLBACK_VWAP", "MULTI_TF_TREND"),
) -> dict[str, Any]:
    candles = resolve_fullest_candles(symbol, timeframe)
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES", "error": "fullest candle source missing"}

    frame = _prepare_frame_round2(candles)
    frame = frame[(frame.index.year >= year_start) & (frame.index.year <= year_end)]

    production_audit = audit_production_sl_tp(candles, frame)
    configs = _build_sweep_configs()

    hypothesis_results: list[dict[str, Any]] = []
    all_config_rows: list[dict[str, Any]] = []

    for hyp_id in hypotheses:
        if hyp_id not in HYPOTHESES_R2:
            continue
        meta = HYPOTHESES_R2[hyp_id]
        signal_fn = meta["signal_fn"]
        stride = meta["stride"]
        config_results: list[dict[str, Any]] = []

        print(f"L2.5: {hyp_id} — sweeping {len(configs)} SL/TP configs ...", flush=True)
        for cfg in configs:
            use_production = cfg["mode"] == "production"
            sl_tp_fn = _make_sl_tp_fn(
                cfg["mode"],
                atr_mult=cfg.get("atr_mult"),
                rr=cfg.get("rr"),
                pip_sl=cfg.get("pip_sl"),
            )
            trades = _scan_hypothesis_sl_tp(
                frame,
                candles,
                signal_fn,
                sl_tp_fn,
                use_production=use_production,
                stride=stride,
            )
            rep = _config_report(cfg["config_id"], cfg, trades)
            config_results.append(rep)
            all_config_rows.append(
                {
                    "hypothesis": hyp_id,
                    "config_id": cfg["config_id"],
                    "overall_pf": rep["overall_pf"],
                    "total_trades": rep["total_trades"],
                    "honest_edge": rep["honest_edge"],
                    "years_passed_gate": rep["gate"]["years_passed_gate"],
                }
            )
            print(
                f"  {cfg['config_id']}: pf={rep['overall_pf']} trades={rep['total_trades']} "
                f"gate={rep['honest_edge']}",
                flush=True,
            )

        config_results.sort(key=lambda r: (r["honest_edge"], r["overall_pf"], r["total_trades"]), reverse=True)
        hypothesis_results.append(
            {
                "hypothesis_id": hyp_id,
                "title_en": meta["title_en"],
                "stride": stride,
                "configs": config_results,
                "best_config": config_results[0]["config_id"] if config_results else None,
                "best_pf": config_results[0]["overall_pf"] if config_results else 0.0,
                "any_honest_edge": any(c["honest_edge"] for c in config_results),
            }
        )

    passing = [
        r
        for hr in hypothesis_results
        for r in hr["configs"]
        if r["honest_edge"]
    ]
    best_overall = max(all_config_rows, key=lambda x: (x["honest_edge"], x["overall_pf"], x["total_trades"]), default=None)

    return {
        "phase": "L2.5",
        "title": "SL/TP Parameter Sweep",
        "title_fa": "اسکن پارامتر SL/TP",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "EDGE_FOUND" if passing else "NO_HONEST_EDGE",
        "research_only": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "year_range": [year_start, year_end],
        "hypotheses_tested": list(hypotheses),
        "methodology": {
            "stride": "per-hypothesis from L2r2",
            "future_window_bars": FUTURE_WINDOW,
            "gate_pf": GATE_PF,
            "gate_min_trades_year": GATE_MIN_TRADES_YEAR,
            "gate_min_years": GATE_MIN_YEARS_PASS,
            "config_count": len(configs),
            "rr_values_tested": [1.0, 1.5, 2.0, 2.5, 3.0],
            "atr_mult_values_tested": [1.0, 1.5, 2.0],
            "fixed_pip_sl_tested": [50, 100, 150],
            "xauusd_pip_size": XAUUSD_PIP_SIZE,
        },
        "production_sl_tp_audit": production_audit,
        "hypothesis_results": hypothesis_results,
        "ranking": sorted(all_config_rows, key=lambda x: x["overall_pf"], reverse=True),
        "best_overall": best_overall,
        "any_config_passes_gate": bool(passing),
        "configs_passing_gate": [c["config_id"] for c in passing],
        "recommendation_en": (
            "At least one SL/TP config passes honest gate — investigate further"
            if passing
            else "No SL/TP variant rescues rule edge — problem is signal not sizing"
        ),
        "recommendation_fa": (
            "حداقل یک پیکربندی SL/TP gate را پاس کرد"
            if passing
            else "هیچ variant SL/TP لبه rule را نجات نداد — مشکل سیگنال است نه sizing"
        ),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_sl_tp_sweep()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    return data


if __name__ == "__main__":
    main()
