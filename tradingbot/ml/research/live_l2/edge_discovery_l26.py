"""L2.6 — combined edge test: PULLBACK_VWAP + ATR2.0/RR1.0 + v8 TREND ML filter (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.live_l2.edge_discovery import (
    FUTURE_WINDOW,
    GATE_MIN_TRADES_YEAR,
    GATE_MIN_YEARS_PASS,
    GATE_PF,
    WARMUP,
    _evaluate_gate,
    _pf_from_labels,
    _yearly_stats,
)
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    HYPOTHESES_R2,
    _prepare_frame_round2,
)
from tradingbot.ml.research.live_l2.sl_tp_sweep import (
    _make_sl_tp_fn,
    _scan_hypothesis_sl_tp,
)
from tradingbot.ml.research.live_l4.v8_regime_ml_test import _v8_feature_set
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

ROOT = Path(__file__).resolve().parents[4]
V8_ENRICHED = ROOT / "tradingbot" / "ml" / "research" / "live_l1" / "artifacts" / "dataset_v8_enriched.parquet"
V8_LABELED = ROOT / "tradingbot" / "ml" / "research" / "live_l1" / "artifacts" / "dataset_v8_labeled.parquet"
REPORT_PATH = ROOT / "live_l2_edge_discovery_l26_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
YEAR_START = 2021
YEAR_END = 2026
HYPOTHESIS_ID = "PULLBACK_VWAP"
SL_TP_CONFIG_ID = "ATR2.0_RR1.0"
ATR_MULT = 2.0
RR = 1.0
ML_REGIME = "TREND"
THRESHOLDS = [0.35, 0.40, 0.45, 0.50, 0.55]
MIN_TRAIN_ROWS = 200
MIN_TEST_ROWS = 50
SEED = 42


def _resolve_v8_path() -> Path:
    if V8_LABELED.is_file():
        return V8_LABELED
    return V8_ENRICHED


def _pick_label_col(df: pd.DataFrame) -> str:
    if "label_v3_rr1" in df.columns and df["label_v3_rr1"].isin([0, 1]).sum() >= MIN_TRAIN_ROWS:
        return "label_v3_rr1"
    return "label_v3"


def _build_feature_index(v8: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    work = v8.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work = work.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    return work.set_index("timestamp")


def _walk_forward_filter_trades(
    trades: list[dict[str, Any]],
    v8_indexed: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    *,
    threshold: float,
    regime: str = ML_REGIME,
) -> list[dict[str, Any]]:
    if not trades or not feature_cols:
        return []

    labeled = v8_indexed[v8_indexed[label_col].isin([0, 1])].copy()
    if regime and "regime" in labeled.columns:
        labeled = labeled[labeled["regime"].astype(str).str.upper() == regime.upper()]
    if labeled.empty:
        return []

    labeled["year"] = labeled.index.year
    filtered: list[dict[str, Any]] = []

    for test_year in range(YEAR_START, YEAR_END + 1):
        train = labeled[labeled["year"] < test_year]
        year_trades = [t for t in trades if t["year"] == test_year]
        if len(train) < MIN_TRAIN_ROWS or not year_trades:
            continue

        X_tr = train[feature_cols].astype(float).fillna(0).values
        y_tr = train[label_col].astype(int).values
        scaler = StandardScaler()
        model = create_trend_ml_model("random_forest", seed=SEED)
        model.fit(scaler.fit_transform(X_tr), y_tr)

        for trade in year_trades:
            ts = pd.Timestamp(trade["timestamp"])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            if ts not in v8_indexed.index:
                idx = v8_indexed.index.searchsorted(ts)
                if idx >= len(v8_indexed):
                    continue
                ts = v8_indexed.index[idx]
            row = v8_indexed.loc[ts]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
            X = row[feature_cols].astype(float).fillna(0).values.reshape(1, -1)
            proba = float(model.predict_proba(scaler.transform(X))[0, 1])
            if proba >= threshold:
                out = dict(trade)
                out["ml_proba"] = round(proba, 4)
                out["ml_threshold"] = threshold
                filtered.append(out)

    return filtered


def _threshold_report(
    threshold: float | None,
    trades: list[dict[str, Any]],
    *,
    mode: str,
) -> dict[str, Any]:
    yearly = _yearly_stats(trades)
    gate = _evaluate_gate(yearly)
    labels = [int(t["outcome"]) for t in trades]
    wins = sum(labels)
    return {
        "mode": mode,
        "ml_threshold": threshold,
        "total_trades": len(trades),
        "overall_pf": _pf_from_labels(labels) if labels else 0.0,
        "overall_win_rate_pct": round(wins / len(labels) * 100, 2) if labels else 0.0,
        "yearly": yearly,
        "gate": gate,
        "honest_edge": gate["gate_pass"],
    }


def run_edge_discovery_l26(
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    year_start: int = YEAR_START,
    year_end: int = YEAR_END,
) -> dict[str, Any]:
    candles = resolve_fullest_candles(symbol, timeframe)
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES", "error": "fullest candle source missing"}

    meta = HYPOTHESES_R2[HYPOTHESIS_ID]
    frame = _prepare_frame_round2(candles)
    frame = frame[(frame.index.year >= year_start) & (frame.index.year <= year_end)]

    sl_tp_fn = _make_sl_tp_fn("atr_rr", atr_mult=ATR_MULT, rr=RR)
    print(
        f"L2.6: scanning {HYPOTHESIS_ID} with {SL_TP_CONFIG_ID} (stride={meta['stride']}) ...",
        flush=True,
    )
    all_trades = _scan_hypothesis_sl_tp(
        frame,
        candles,
        meta["signal_fn"],
        sl_tp_fn,
        use_production=False,
        stride=meta["stride"],
    )
    baseline = _threshold_report(None, all_trades, mode="baseline_no_ml")
    print(
        f"  baseline: trades={baseline['total_trades']} pf={baseline['overall_pf']} "
        f"gate={baseline['honest_edge']}",
        flush=True,
    )

    v8_path = _resolve_v8_path()
    if not v8_path.is_file():
        return {
            "verdict": "V8_DATASET_MISSING",
            "path": str(v8_path),
            "baseline": baseline,
        }

    v8 = pd.read_parquet(v8_path)
    label_col = _pick_label_col(v8)
    feature_cols = _v8_feature_set(v8[v8[label_col].isin([0, 1])]) if label_col in v8.columns else []
    v8_indexed = _build_feature_index(v8, feature_cols)

    threshold_results: list[dict[str, Any]] = []
    for thr in THRESHOLDS:
        filtered = _walk_forward_filter_trades(
            all_trades,
            v8_indexed,
            feature_cols,
            label_col,
            threshold=thr,
        )
        rep = _threshold_report(thr, filtered, mode="ml_filtered")
        threshold_results.append(rep)
        print(
            f"  ML thr={thr}: trades={rep['total_trades']} pf={rep['overall_pf']} "
            f"gate={rep['honest_edge']}",
            flush=True,
        )

    all_configs = [{"mode": "baseline_no_ml", "ml_threshold": None, **baseline}]
    all_configs.extend(threshold_results)
    all_configs.sort(
        key=lambda r: (r["honest_edge"], r["overall_pf"], r["total_trades"]),
        reverse=True,
    )
    best = all_configs[0]
    any_pass = baseline["honest_edge"] or any(r["honest_edge"] for r in threshold_results)
    passing_configs = []
    if baseline["honest_edge"]:
        passing_configs.append({"mode": "baseline_no_ml", "threshold": None, **baseline["gate"]})
    for r in threshold_results:
        if r["honest_edge"]:
            passing_configs.append(
                {"mode": "ml_filtered", "threshold": r["ml_threshold"], **r["gate"]}
            )

    return {
        "phase": "L2.6",
        "title": "Combined Edge Test",
        "title_fa": "تست لبه ترکیبی (سیگنال + SL/TP + ML)",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "EDGE_FOUND" if any_pass else "NO_HONEST_EDGE",
        "research_only": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "year_range": [year_start, year_end],
        "signal": {
            "hypothesis_id": HYPOTHESIS_ID,
            "title_en": meta["title_en"],
            "stride": meta["stride"],
        },
        "sl_tp": {
            "config_id": SL_TP_CONFIG_ID,
            "atr_mult": ATR_MULT,
            "rr": RR,
            "note_en": "Research override — NOT production change",
        },
        "ml_filter": {
            "model": "random_forest",
            "train_regime": ML_REGIME,
            "feature_count": len(feature_cols),
            "label_col": label_col,
            "v8_dataset": str(v8_path),
            "thresholds_swept": THRESHOLDS,
            "walk_forward": "train years < test_year per signal year",
        },
        "methodology": {
            "future_window_bars": FUTURE_WINDOW,
            "gate_pf": GATE_PF,
            "gate_min_trades_year": GATE_MIN_TRADES_YEAR,
            "gate_min_years": GATE_MIN_YEARS_PASS,
        },
        "baseline_no_ml": baseline,
        "ml_threshold_results": threshold_results,
        "best_config": {
            "mode": best["mode"],
            "threshold": best.get("ml_threshold"),
            "overall_pf": best["overall_pf"],
            "total_trades": best["total_trades"],
            "honest_edge": best["honest_edge"],
            "years_passed_gate": best["gate"]["years_passed_gate"],
        },
        "any_config_passes_gate": any_pass,
        "configs_passing_gate": passing_configs,
        "recommendation_en": (
            "Combined config passes honest gate — investigate L3 path"
            if any_pass
            else "No combined config passes 3-year gate — L3 remains blocked"
        ),
        "recommendation_fa": (
            "پیکربندی ترکیبی gate را پاس کرد"
            if any_pass
            else "هیچ پیکربندی ترکیبی gate سه‌ساله را پاس نکرد — L3 همچنان BLOCKED"
        ),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_edge_discovery_l26()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    return data


if __name__ == "__main__":
    main()
