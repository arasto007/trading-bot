"""L4 — ML refinement on proven PULLBACK_VWAP signal only (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.live_l2.edge_discovery import (
    GATE_PF,
    _evaluate_gate,
    _pf_from_labels,
    _yearly_stats,
)
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    HYPOTHESES_R2,
    _prepare_frame_round2,
)
from tradingbot.ml.research.live_l2.sl_tp_sweep import _make_sl_tp_fn, _scan_hypothesis_sl_tp
from tradingbot.ml.research.live_l4.v8_regime_ml_test import _v8_feature_set
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

ROOT = Path(__file__).resolve().parents[4]
V8_LABELED = ROOT / "tradingbot" / "ml" / "research" / "live_l1" / "artifacts" / "dataset_v8_labeled.parquet"
V8_ENRICHED = ROOT / "tradingbot" / "ml" / "research" / "live_l1" / "artifacts" / "dataset_v8_enriched.parquet"
REPORT_PATH = ROOT / "live_l4_signal_ml_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
YEAR_START = 2021
YEAR_END = 2026
SIGNAL_ID = "PULLBACK_VWAP"
ATR_MULT = 2.0
RR = 1.0
THRESHOLDS = [0.40, 0.45, 0.50, 0.55]
WF_YEARS = (2022, 2023, 2024, 2025, 2026)
MIN_TRAIN = 200
MIN_TEST = 30
SEED = 42


def _resolve_v8() -> tuple[pd.DataFrame, str]:
    path = V8_LABELED if V8_LABELED.is_file() else V8_ENRICHED
    df = pd.read_parquet(path)
    label_col = "label_v3_rr1" if "label_v3_rr1" in df.columns else "label_v3"
    return df, label_col


def _match_trades_to_v8(
    trades: list[dict[str, Any]],
    v8: pd.DataFrame,
) -> pd.DataFrame:
    v8 = v8.copy()
    v8["timestamp"] = pd.to_datetime(v8["timestamp"], utc=True)
    v8 = v8.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    idx = v8.set_index("timestamp")
    rows: list[dict[str, Any]] = []
    for t in trades:
        ts = pd.Timestamp(t["timestamp"])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        if ts not in idx.index:
            pos = idx.index.searchsorted(ts)
            if pos >= len(idx):
                continue
            ts = idx.index[pos]
        row = idx.loc[ts]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        rec = row.to_dict()
        rec["signal_outcome"] = int(t["outcome"])
        rec["signal_year"] = int(t["year"])
        rows.append(rec)
    return pd.DataFrame(rows)


def _walk_forward_ml(
    matched: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    *,
    threshold: float | None = None,
) -> tuple[list[dict[str, Any]], list[int], list[int]]:
    work = matched[matched[label_col].isin([0, 1])].copy()
    if work.empty:
        return [], [], []

    baseline_labels: list[int] = []
    filtered_labels: list[int] = []
    windows: list[dict[str, Any]] = []

    for test_year in WF_YEARS:
        train = work[work["signal_year"] < test_year]
        test = work[work["signal_year"] == test_year]
        if len(train) < MIN_TRAIN or len(test) < MIN_TEST:
            continue

        X_tr = train[feature_cols].astype(float).fillna(0)
        y_tr = train[label_col].astype(int).values
        X_te = test[feature_cols].astype(float).fillna(0)
        y_te = test[label_col].astype(int).values
        sig_out = test["signal_outcome"].astype(int).values

        scaler = StandardScaler()
        model = create_trend_ml_model("random_forest", seed=SEED)
        X_tr_s = scaler.fit_transform(X_tr)
        model.fit(X_tr_s, y_tr)
        proba = model.predict_proba(scaler.transform(X_te))[:, 1]

        baseline_labels.extend(sig_out.tolist())
        if threshold is None:
            filtered_labels.extend(sig_out.tolist())
            sel = len(sig_out)
        else:
            mask = proba >= threshold
            filtered_labels.extend(sig_out[mask].tolist())
            sel = int(mask.sum())

        try:
            auc = float(roc_auc_score(y_te, proba)) if len(np.unique(y_te)) > 1 else 0.5
        except ValueError:
            auc = 0.5

        windows.append(
            {
                "test_year": test_year,
                "train_rows": len(train),
                "test_rows": len(test),
                "selected_trades": sel,
                "auc": round(auc, 4),
                "baseline_pf": _pf_from_labels(sig_out.tolist()),
                "filtered_pf": _pf_from_labels(sig_out[mask].tolist()) if threshold is not None else _pf_from_labels(sig_out.tolist()),
            }
        )

    return windows, baseline_labels, filtered_labels


def run_signal_ml_refinement() -> dict[str, Any]:
    candles = resolve_fullest_candles(SYMBOL, TIMEFRAME)
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES"}

    meta = HYPOTHESES_R2[SIGNAL_ID]
    frame = _prepare_frame_round2(candles)
    frame = frame[(frame.index.year >= YEAR_START) & (frame.index.year <= YEAR_END)]
    sl_tp_fn = _make_sl_tp_fn("atr_rr", atr_mult=ATR_MULT, rr=RR)
    trades = _scan_hypothesis_sl_tp(
        frame, candles, meta["signal_fn"], sl_tp_fn, use_production=False, stride=meta["stride"]
    )
    print(f"L4: {SIGNAL_ID} baseline trades={len(trades)}", flush=True)

    v8, label_col = _resolve_v8()
    matched = _match_trades_to_v8(trades, v8)
    if matched.empty:
        return {"verdict": "NO_V8_MATCH", "trades": len(trades)}

    feature_cols = _v8_feature_set(matched[matched[label_col].isin([0, 1])])
    if not feature_cols:
        return {"verdict": "NO_FEATURES", "matched_rows": len(matched)}

    _, baseline_labels, _ = _walk_forward_ml(matched, feature_cols, label_col, threshold=None)
    baseline_pf = _pf_from_labels(baseline_labels)
    baseline_yearly = _yearly_stats(
        [{"year": y, "outcome": o} for y, o in zip(matched["signal_year"], matched["signal_outcome"])]
    )

    threshold_results: list[dict[str, Any]] = []
    for thr in THRESHOLDS:
        windows, _, filtered_labels = _walk_forward_ml(matched, feature_cols, label_col, threshold=thr)
        pf = _pf_from_labels(filtered_labels)
        trade_reduction_pct = round(
            (1 - len(filtered_labels) / max(len(baseline_labels), 1)) * 100, 2
        )
        threshold_results.append(
            {
                "threshold": thr,
                "wf_windows": len(windows),
                "filtered_trades": len(filtered_labels),
                "baseline_trades": len(baseline_labels),
                "trade_reduction_pct": trade_reduction_pct,
                "filtered_pf": pf,
                "baseline_pf": baseline_pf,
                "pf_delta": round(pf - baseline_pf, 4),
                "ml_helps": pf > baseline_pf and len(filtered_labels) >= MIN_TEST,
                "windows": windows,
            }
        )
        print(f"  thr={thr}: pf={pf} baseline={baseline_pf} trades={len(filtered_labels)}", flush=True)

    best = max(threshold_results, key=lambda r: (r["ml_helps"], r["filtered_pf"], -r["trade_reduction_pct"]), default=None)
    ml_helps = best is not None and best["ml_helps"]

    return {
        "phase": "L4",
        "title": "ML on Proven Signal Only",
        "title_fa": "ML فقط روی سیگنال PULLBACK_VWAP",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "ML_IMPROVES" if ml_helps else "ML_HURTS_OR_NEUTRAL",
        "research_only": True,
        "signal": SIGNAL_ID,
        "sl_tp": f"ATR{ATR_MULT}_RR{RR}",
        "label_col": label_col,
        "v8_dataset": str(V8_LABELED if V8_LABELED.is_file() else V8_ENRICHED),
        "feature_count": len(feature_cols),
        "matched_signal_rows": len(matched),
        "baseline_no_ml": {
            "total_trades": len(baseline_labels),
            "overall_pf": baseline_pf,
            "yearly": baseline_yearly,
            "gate": _evaluate_gate(baseline_yearly),
        },
        "ml_threshold_results": threshold_results,
        "best_threshold": best["threshold"] if best else None,
        "ml_helps_pf": ml_helps,
        "recommendation_en": (
            "ML improves PF on PULLBACK_VWAP — consider L5 paper test with ML filter"
            if ml_helps
            else "ML reduces trades without improving PF — skip ML filter (consistent with L2.6)"
        ),
        "recommendation_fa": (
            "ML PF را بهبود می‌دهد" if ml_helps else "ML فقط تعداد معامله را کم می‌کند — فعلاً بدون ML"
        ),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_signal_ml_refinement()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    return data


if __name__ == "__main__":
    main()
