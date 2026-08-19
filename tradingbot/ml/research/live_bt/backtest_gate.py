"""BACKTEST_GATE — strict pre-paper backtest validation (research only)."""

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
    FUTURE_WINDOW,
    GATE_MIN_TRADES_YEAR,
    GATE_MIN_YEARS_PASS,
    GATE_PF,
    WARMUP,
    _pf_from_labels,
    _yearly_stats,
)
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    HYPOTHESES_R2,
    _prepare_frame_round2,
)
from tradingbot.ml.research.live_l2.sl_tp_sweep import (
    GOLD_RR_DEFAULT,
    _config_report,
    _make_sl_tp_fn,
    _scan_hypothesis_sl_tp,
)
from tradingbot.ml.research.live_l4.signal_ml_refinement import (
    _match_trades_to_v8,
    _walk_forward_ml,
)
from tradingbot.ml.research.live_l4.v8_regime_ml_test import (
    PRIMARY_THRESHOLD,
    V7_BASELINE_FEATURES,
    _regime_walk_forward,
    _v8_feature_set,
)
from tradingbot.ml.research.phase39.candle_sources import audit_report, resolve_fullest_candles
from tradingbot.ml.research.trend_ml.models import create_trend_ml_model

ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = ROOT / "live_backtest_gate_report.json"
V8_LABELED = ROOT / "tradingbot" / "ml" / "research" / "live_l1" / "artifacts" / "dataset_v8_labeled.parquet"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
YEAR_START = 2021
YEAR_END = 2026
HYPOTHESIS_ID = "VOL_REGIME"
ATR_MULT = 2.5
RR_RESEARCH = 0.8
RR_PRODUCTION = GOLD_RR_DEFAULT
OVERALL_PF_MIN = 1.2
ML_AUC_MIN = 0.55
ML_HONEST_PF_MIN = 1.3
WF_YEARS = (2022, 2023, 2024, 2025, 2026)
MIN_TRADES_HONEST = 30
SEED = 42


def _evaluate_vol_regime_gate(
    yearly: dict[str, dict[str, Any]],
    overall_pf: float,
    *,
    pf_threshold: float = GATE_PF,
    overall_pf_min: float = OVERALL_PF_MIN,
) -> dict[str, Any]:
    years_pass = sum(
        1
        for y in range(YEAR_START, YEAR_END + 1)
        if yearly.get(str(y), {}).get("pf", 0) >= pf_threshold
        and yearly.get(str(y), {}).get("trades", 0) >= GATE_MIN_TRADES_YEAR
    )
    return {
        "pf_per_year_min": pf_threshold,
        "min_trades_per_year": GATE_MIN_TRADES_YEAR,
        "min_years_pass": GATE_MIN_YEARS_PASS,
        "overall_pf_min": overall_pf_min,
        "years_passed_gate": years_pass,
        "overall_pf": overall_pf,
        "gate_pass": years_pass >= GATE_MIN_YEARS_PASS and overall_pf >= overall_pf_min,
    }


def _run_vol_regime_backtest(
    frame: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    rr: float,
    use_production: bool = False,
    config_id: str,
) -> dict[str, Any]:
    meta = HYPOTHESES_R2[HYPOTHESIS_ID]
    signal_fn = meta["signal_fn"]
    stride = int(meta.get("stride", 6))
    if use_production:
        sl_tp_fn = _make_sl_tp_fn("production")
    else:
        sl_tp_fn = _make_sl_tp_fn("atr_rr", atr_mult=ATR_MULT, rr=rr)

    trades = _scan_hypothesis_sl_tp(
        frame,
        candles,
        signal_fn,
        sl_tp_fn,
        use_production=use_production,
        stride=stride,
    )
    config_meta = {
        "hypothesis_id": HYPOTHESIS_ID,
        "mode": "production" if use_production else "atr_rr",
        "atr_mult": ATR_MULT,
        "rr": RR_PRODUCTION if use_production else rr,
        "use_production_sl_tp": use_production,
    }
    rep = _config_report(config_id, config_meta, trades)
    rep["gate"] = _evaluate_vol_regime_gate(rep["yearly"], rep["overall_pf"])
    rep["gate_pass"] = rep["gate"]["gate_pass"]
    return rep


def _run_ml_v8_trend_gate(v8_path: Path | None = None) -> dict[str, Any]:
    path = v8_path or V8_LABELED
    if not path.is_file():
        return {"verdict": "V8_LABELED_MISSING", "path": str(path), "gate_pass": False, "trained": False}

    df = pd.read_parquet(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    labeled = df[df["label_v3"].isin([0, 1])].copy()
    trend = labeled[labeled["regime"].astype(str).str.upper() == "TREND"].copy() if "regime" in labeled.columns else pd.DataFrame()

    if len(trend) < 500:
        return {
            "verdict": "INSUFFICIENT_TREND_ROWS",
            "rows_trend": len(trend),
            "gate_pass": False,
            "trained": False,
        }

    v7_feats = [c for c in V7_BASELINE_FEATURES if c in trend.columns]
    v8_feats = _v8_feature_set(trend)
    rf_10f = v7_feats[:10] if len(v7_feats) >= 10 else v7_feats

    wf_v8 = _regime_walk_forward(
        trend,
        regime=None,
        feature_cols=v8_feats,
        label_col="label_v3",
        test_years=WF_YEARS,
        threshold=PRIMARY_THRESHOLD,
    )
    wf_10f = _regime_walk_forward(
        trend,
        regime=None,
        feature_cols=rf_10f,
        label_col="label_v3",
        test_years=WF_YEARS,
        threshold=PRIMARY_THRESHOLD,
    )

    primary = wf_v8 if wf_v8.get("verdict") == "WF_COMPLETE" else wf_10f
    trained = primary.get("verdict") == "WF_COMPLETE"
    mean_auc = float(primary.get("mean_auc", 0))
    mean_pf = float(primary.get("mean_pf_at_threshold", 0))
    mean_pf_honest = float(primary.get("mean_pf_honest_min_trades_30", 0))
    gate_pass = trained and mean_auc >= ML_AUC_MIN and mean_pf_honest >= ML_HONEST_PF_MIN

    return {
        "verdict": "WF_COMPLETE" if trained else primary.get("verdict", "FAIL"),
        "trained": trained,
        "dataset_path": str(path),
        "regime": "TREND",
        "label_col": "label_v3",
        "model": "random_forest",
        "feature_set_rf_10f": rf_10f,
        "feature_set_v8_expanded": v8_feats,
        "primary_threshold": PRIMARY_THRESHOLD,
        "walk_forward_years": list(WF_YEARS),
        "rf_10f_result": wf_10f,
        "v8_expanded_result": wf_v8,
        "mean_auc": mean_auc,
        "mean_pf_at_threshold": mean_pf,
        "mean_pf_honest_30": mean_pf_honest,
        "gate": {
            "auc_min": ML_AUC_MIN,
            "honest_pf_min": ML_HONEST_PF_MIN,
            "auc_gate_pass": mean_auc >= ML_AUC_MIN,
            "honest_pf_gate_pass": mean_pf_honest >= ML_HONEST_PF_MIN,
            "gate_pass": gate_pass,
        },
        "gate_pass": gate_pass,
    }


def _run_ml_vol_regime_entries(
    frame: pd.DataFrame,
    candles: pd.DataFrame,
    v8_path: Path | None = None,
) -> dict[str, Any]:
    path = v8_path or V8_LABELED
    if not path.is_file():
        return {"verdict": "V8_LABELED_MISSING", "gate_pass": False}

    sl_tp_fn = _make_sl_tp_fn("atr_rr", atr_mult=ATR_MULT, rr=RR_RESEARCH)
    meta = HYPOTHESES_R2[HYPOTHESIS_ID]
    trades = _scan_hypothesis_sl_tp(
        frame,
        candles,
        meta["signal_fn"],
        sl_tp_fn,
        use_production=False,
        stride=int(meta.get("stride", 6)),
    )
    rule_labels = [int(t["outcome"]) for t in trades]
    rule_pf = _pf_from_labels(rule_labels) if rule_labels else 0.0
    rule_yearly = _yearly_stats(trades)

    v8 = pd.read_parquet(path)
    label_col = "label_v3_rr1" if "label_v3_rr1" in v8.columns else "label_v3"
    matched = _match_trades_to_v8(trades, v8)
    if matched.empty or label_col not in matched.columns:
        return {
            "verdict": "NO_MATCHED_V8_ROWS",
            "rule_only_pf": rule_pf,
            "gate_pass": False,
        }

    feature_cols = _v8_feature_set(matched)
    windows, baseline_labels, filtered_labels = _walk_forward_ml(
        matched,
        feature_cols,
        label_col,
        threshold=PRIMARY_THRESHOLD,
    )

    ml_pf = _pf_from_labels(filtered_labels) if filtered_labels else 0.0
    ml_beats_rule = ml_pf > rule_pf and len(filtered_labels) >= MIN_TRADES_HONEST

    aucs: list[float] = []
    for test_year in WF_YEARS:
        train = matched[matched["signal_year"] < test_year]
        test = matched[matched["signal_year"] == test_year]
        if len(train) < 200 or len(test) < 30:
            continue
        if label_col not in train.columns:
            continue
        work_tr = train[train[label_col].isin([0, 1])]
        work_te = test[test[label_col].isin([0, 1])]
        if len(work_tr) < 100 or len(work_te) < 20:
            continue
        X_tr = work_tr[feature_cols].astype(float).fillna(0)
        y_tr = work_tr[label_col].astype(int).values
        X_te = work_te[feature_cols].astype(float).fillna(0)
        y_te = work_te[label_col].astype(int).values
        scaler = StandardScaler()
        model = create_trend_ml_model("random_forest", seed=SEED)
        model.fit(scaler.fit_transform(X_tr), y_tr)
        proba = model.predict_proba(scaler.transform(X_te))[:, 1]
        try:
            aucs.append(float(roc_auc_score(y_te, proba)))
        except ValueError:
            aucs.append(0.5)

    mean_auc = round(float(np.mean(aucs)), 4) if aucs else 0.0

    return {
        "verdict": "COMPLETE",
        "label_col": label_col,
        "signal_entries_matched": len(matched),
        "rule_only": {
            "total_trades": len(trades),
            "overall_pf": rule_pf,
            "yearly": rule_yearly,
        },
        "ml_filtered": {
            "threshold": PRIMARY_THRESHOLD,
            "filtered_trades": len(filtered_labels),
            "overall_pf": ml_pf,
            "walk_forward_windows": windows,
            "mean_auc": mean_auc,
        },
        "ml_beats_rule_only": ml_beats_rule,
        "pf_delta_ml_vs_rule": round(ml_pf - rule_pf, 4),
        "gate_pass": ml_beats_rule,
    }


def _determine_next_step(
    track_a: dict[str, Any],
    track_b: dict[str, Any],
    track_c: dict[str, Any],
    track_d: dict[str, Any],
) -> dict[str, Any]:
    a_pass = bool(track_a.get("gate_pass"))
    b_pass = bool(track_b.get("gate_pass"))
    c_pass = bool(track_c.get("gate_pass"))
    d_pass = bool(track_d.get("gate_pass"))

    if a_pass and b_pass:
        next_step = "PAPER_RESUME"
        reason_en = "VOL_REGIME passes research and production RR backtest gates."
        reason_fa = "VOL_REGIME هر دو gate تحقیق و production RR را پاس کرد."
    elif a_pass and not b_pass:
        next_step = "RR_PRODUCTION_RESEARCH"
        reason_en = (
            "Research RR=0.8 passes but production RR=2.5 fails — "
            "document TQ patch (tq_rr_research_patch_spec.json) before paper."
        )
        reason_fa = "RR=0.8 پاس شد ولی RR=2.5 production نه — patch TQ لازم است."
    elif c_pass:
        next_step = "ML_INTEGRATION_RESEARCH"
        reason_en = "ML v8 TREND walk-forward passes strict gate — research ML integration path."
        reason_fa = "ML v8 gate را پاس کرد — مسیر یکپارچه‌سازی ML."
    elif d_pass:
        next_step = "ML_INTEGRATION_RESEARCH"
        reason_en = "ML on VOL_REGIME entries beats rule-only — research ML integration."
        reason_fa = "ML روی ورودی VOL_REGIME از rule-only بهتر است."
    else:
        next_step = "NEW_HYPOTHESIS_REQUIRED"
        reason_en = "All backtest gates failed — do not resume paper."
        reason_fa = "همه gateها fail — paper از سر گرفته نشود."

    paper_resume_allowed = next_step == "PAPER_RESUME"

    return {
        "next_step": next_step,
        "paper_resume_allowed": paper_resume_allowed,
        "reason_en": reason_en,
        "reason_fa": reason_fa,
        "track_passes": {
            "A_vol_regime_rr08": a_pass,
            "B_vol_regime_production_rr25": b_pass,
            "C_ml_v8_trend": c_pass,
            "D_ml_vol_regime_entries": d_pass,
        },
    }


def run_backtest_gate(
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    year_start: int = YEAR_START,
    year_end: int = YEAR_END,
) -> dict[str, Any]:
    candle_audit = audit_report(symbol, timeframe)
    candles = resolve_fullest_candles(symbol, timeframe)
    if candles is None or candles.empty:
        return {
            "verdict": "NO_CANDLES",
            "candle_audit": candle_audit,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    frame = _prepare_frame_round2(candles)
    frame = frame[(frame.index.year >= year_start) & (frame.index.year <= year_end)]
    candle_source_used = candle_audit.get("fullest_source") or {}

    print("BACKTEST_GATE A: VOL_REGIME ATR2.5_RR0.8 ...", flush=True)
    track_a = _run_vol_regime_backtest(
        frame,
        candles,
        rr=RR_RESEARCH,
        config_id="ATR2.5_RR0.8",
    )
    print(f"  A overall_pf={track_a['overall_pf']} gate={track_a['gate_pass']}", flush=True)

    print("BACKTEST_GATE B: VOL_REGIME production RR=2.5 ...", flush=True)
    track_b = _run_vol_regime_backtest(
        frame,
        candles,
        rr=RR_PRODUCTION,
        use_production=False,
        config_id=f"ATR{ATR_MULT}_RR{RR_PRODUCTION}",
    )
    print(f"  B overall_pf={track_b['overall_pf']} gate={track_b['gate_pass']}", flush=True)

    pf_drop = round(track_a["overall_pf"] - track_b["overall_pf"], 4)

    print("BACKTEST_GATE C: ML v8 TREND retrain ...", flush=True)
    track_c = _run_ml_v8_trend_gate()
    print(f"  C AUC={track_c.get('mean_auc')} honestPF={track_c.get('mean_pf_honest_30')} gate={track_c.get('gate_pass')}", flush=True)

    print("BACKTEST_GATE D: ML on VOL_REGIME entries ...", flush=True)
    track_d = _run_ml_vol_regime_entries(frame, candles)
    print(f"  D ml_beats_rule={track_d.get('ml_beats_rule_only')} rule_pf={track_d.get('rule_only', {}).get('overall_pf')}", flush=True)

    next_step = _determine_next_step(track_a, track_b, track_c, track_d)
    overall_verdict = "GATE_PASS" if next_step["paper_resume_allowed"] else "GATE_FAIL"

    return {
        "phase": "BACKTEST_GATE",
        "title": "Strict Pre-Paper Backtest Gate",
        "title_fa": "gate سخت backtest پیش از paper",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": overall_verdict,
        "research_only": True,
        "paper_status": "PAUSED_FOR_BACKTEST_GATE",
        "symbol": symbol,
        "timeframe": timeframe,
        "year_range": [year_start, year_end],
        "candle_source": {
            "canonical_path": candle_audit.get("canonical_path"),
            "source_used": candle_source_used,
            "audit": candle_audit,
        },
        "methodology": {
            "future_window_bars": FUTURE_WINDOW,
            "hypothesis": HYPOTHESIS_ID,
            "gate_a": f"PF>={GATE_PF} in {GATE_MIN_YEARS_PASS}+ years, {GATE_MIN_TRADES_YEAR}+ trades/year, overall PF>={OVERALL_PF_MIN}",
            "gate_b": "Same gate with ATR2.5 RR=2.5 (production path)",
            "gate_c": f"AUC>={ML_AUC_MIN} AND honest PF@30>={ML_HONEST_PF_MIN}",
            "gate_d": "ML filtered PF > rule-only VOL_REGIME on v8 label_v3_rr1 entries",
        },
        "track_A_vol_regime_rr08": track_a,
        "track_B_vol_regime_production_rr25": {
            **track_b,
            "pf_drop_vs_rr08": pf_drop,
            "rr08_overall_pf": track_a["overall_pf"],
            "production_rr_overall_pf": track_b["overall_pf"],
            "tq_patch_spec": "tradingbot/ml/research/live_l6/tq_rr_research_patch_spec.json",
        },
        "track_C_ml_v8_trend": track_c,
        "track_D_ml_vol_regime_entries": track_d,
        "next_step": next_step,
        "production_deploy": "BLOCKED",
        "paper_resume_allowed": next_step["paper_resume_allowed"],
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_backtest_gate()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    print(f"Verdict: {data.get('verdict')} next_step: {data.get('next_step', {}).get('next_step')}", flush=True)
    return data


if __name__ == "__main__":
    main()
