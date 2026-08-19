"""Phase 13.8 — trend failure audit (Phase 13.3 vs router path)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase13_8.config import (
    phase13_3_reports_dir,
    phase13_4_reports_dir,
    phase13_7_reports_dir,
)
from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify
from tradingbot.ml.research.router_optimizer.router_optimizer import prepare_merged_frame
from tradingbot.ml.research.trend_ml.feature_builder import build_ml_features
from tradingbot.ml.research.trend_ml.trend_ml_filter import apply_trend_ml_filter
from tradingbot.ml.research.trend_strategy.trend_backtest import attach_regime_labels
from tradingbot.ml.research.trend_strategy.trend_features import compute_trend_features
from tradingbot.ml.research.trend_strategy.trend_rules import evaluate_trend_rules


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _funnel_on_frame(
    frame: pd.DataFrame,
    *,
    path_name: str,
    ml_model=None,
    ml_scaler=None,
    ml_threshold: float = 0.55,
) -> dict[str, Any]:
    regimes = attach_regime_labels(frame) if path_name == "phase13_3" else rule_classify(frame)
    trend_candles = valid_states = rule_signals = ml_accepted = final_signals = 0
    missing_structure = 0

    for i in range(len(frame)):
        row = frame.iloc[i]
        regime = str(regimes.iloc[i])
        if regime != "TREND":
            continue
        trend_candles += 1

        adx = float(row.get("adx", 0))
        if adx > 0:
            valid_states += 1

        hh = row.get("higher_high_count")
        ll = row.get("lower_low_count")
        if pd.isna(hh) or pd.isna(ll):
            missing_structure += 1

        direction = evaluate_trend_rules(row, regime="TREND")
        if direction in ("BUY", "SELL"):
            rule_signals += 1
            if ml_model is not None and ml_scaler is not None:
                ml = apply_trend_ml_filter(
                    row, model=ml_model, scaler=ml_scaler, model_name="logistic", threshold=ml_threshold
                )
                if ml["allow_trade"]:
                    ml_accepted += 1
                    final_signals += 1
            else:
                ml_accepted += 1
                final_signals += 1

    return {
        "path": path_name,
        "rows": len(frame),
        "funnel": {
            "trend_candles": trend_candles,
            "valid_trend_states": valid_states,
            "rule_signals": rule_signals,
            "ml_accepted": ml_accepted,
            "final_signals": final_signals,
        },
        "missing_structure_columns": missing_structure,
        "regime_distribution": {str(k): int(v) for k, v in regimes.value_counts().to_dict().items()},
    }


def build_trend_failure_audit(
    candles: pd.DataFrame,
    dataset: pd.DataFrame | None,
    *,
    base_dir: str | Path | None = None,
    ml_bundle: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    p33 = _load_json(phase13_3_reports_dir(base_dir) / "trend_strategy_report.json")
    p34 = _load_json(phase13_4_reports_dir(base_dir) / "trend_ml_report.json")
    p37 = _load_json(phase13_7_reports_dir(base_dir) / "trend_routing_debug.json")

    trend_frame = compute_trend_features(candles)
    ml_frame = build_ml_features(candles)
    merged = prepare_merged_frame(candles, dataset)

    ml_model = ml_scaler = None
    if ml_bundle:
        ml_model, ml_scaler = ml_bundle

    funnel_133 = _funnel_on_frame(trend_frame, path_name="phase13_3")
    funnel_ml = _funnel_on_frame(ml_frame, path_name="trend_ml_features")
    funnel_merged = _funnel_on_frame(
        merged,
        path_name="router_merged",
        ml_model=ml_model,
        ml_scaler=ml_scaler,
    )

    p33_trades = int(p33.get("metrics", {}).get("trades", 0))
    p33_signals = funnel_133["funnel"]["rule_signals"]
    router_signals = funnel_merged["funnel"]["rule_signals"]

    signal_loss_ratio = round(1.0 - router_signals / max(p33_signals, 1), 4)
    root_causes = p37.get("root_causes", [])
    if isinstance(root_causes, list):
        root_causes = [str(x) for x in root_causes]
    disappear = [
        "Router uses rule_classify on merged frame; Phase 13.3 uses attach_regime_labels on canonical frame",
        f"Canonical frame: {p33_signals} rule signals vs merged: {router_signals}",
        "Phase 13.4 ML filter at 0.55 blocks remaining router signals",
    ] + root_causes

    return {
        "phase": "13.8",
        "answers": {
            "1_why_phase13_3_5976_trades": (
                f"Phase 13.3 backtest on full trend feature frame ({len(trend_frame)} rows) "
                f"with attach_regime_labels; {p33_signals} rule signals produced {p33_trades} executed trades "
                f"(multi-bar holds, PF {p33.get('metrics', {}).get('profit_factor', 0)})."
            ),
            "2_why_router_only_21": (
                f"Router merged frame ({len(merged)} rows) yields only {router_signals} rule signals "
                f"({signal_loss_ratio:.0%} signal loss vs Phase 13.3 frame). "
                f"Missing/NaN structure features on merged path: {funnel_merged['missing_structure_columns']} bars."
            ),
            "3_where_signals_disappear": disappear,
        },
        "phase13_3_reference": {
            "trades": p33_trades,
            "profit_factor": p33.get("metrics", {}).get("profit_factor"),
            "feature_rows": p33.get("feature_rows"),
        },
        "phase13_4_reference": {
            "threshold": p34.get("threshold"),
            "best_model": p34.get("best_model"),
            "labeled_samples": p34.get("labeled_samples"),
        },
        "phase13_7_reference": p37.get("funnel_answers", {}),
        "funnels": {
            "phase13_3_frame": funnel_133,
            "trend_ml_frame": funnel_ml,
            "router_merged_frame": funnel_merged,
        },
        "trace": [
            "Regime Detector",
            "Trend Feature Builder",
            "Trend Rules",
            "Trend Signal",
            "Trend ML Filter",
            "Router",
        ],
    }
