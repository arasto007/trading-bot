"""Phase 9.6 — regime-specialized model training and ranking."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.data.paths import regime_optimization_dataset_path, regime_optimization_datasets_root
from tradingbot.ml.research.model_selection import ModelCandidate, ModelSelector
from tradingbot.ml.research.regime_optimization.regime_utils import (
    REGIMES,
    apply_event_filter,
    assign_market_regime,
    metrics_block,
)
from tradingbot.ml.research.retrain_optimizer import create_research_model
from tradingbot.ml.training.evaluation import TrainingEvaluator
from tradingbot.ml.training.model_factory import DEFAULT_SEED

RESEARCH_MODELS = ("logistic", "random_forest", "xgboost", "lightgbm")
MIN_ROWS = 80
MIN_ROWS_FILTERED = 50
MIN_SPLIT_ROWS = 10


def _train_candidate(
    df: pd.DataFrame,
    feature_cols: list[str],
    *,
    seed: int,
    config_id: str,
    hyperparameters: dict[str, dict[str, Any]],
) -> list[ModelCandidate]:
    ordered = df.sort_values("timestamp").reset_index(drop=True)
    n = len(ordered)
    cut1 = int(n * 0.7)
    cut2 = int(n * 0.85)
    train = ordered.iloc[:cut1]
    val = ordered.iloc[cut1:cut2]
    test = ordered.iloc[cut2:]
    if min(len(train), len(val), len(test)) < MIN_SPLIT_ROWS:
        return []

    cols = [c for c in feature_cols if c in train.columns]
    scaler = StandardScaler()
    X_tr = train.loc[:, cols].astype(np.float64).values
    y_tr = train["label"].astype(int).to_numpy()
    scaler.fit(X_tr)

    arrays = {}
    for name, part in (("train", train), ("validation", val), ("test", test)):
        X = scaler.transform(part.loc[:, cols].astype(np.float64).values)
        y = part["label"].astype(int).to_numpy()
        arrays[name] = (X, y)

    evaluator = TrainingEvaluator()
    candidates: list[ModelCandidate] = []
    X_tr, y_tr = arrays["train"]
    X_va, y_va = arrays["validation"]
    X_te, y_te = arrays["test"]

    for model_name in RESEARCH_MODELS:
        hp = hyperparameters.get(model_name, {})
        model = create_research_model(model_name, seed, hp)
        model.fit(X_tr, y_tr, eval_set=(X_va, y_va))
        val_m = evaluator.evaluate(model, X_va, y_va, split="validation")
        test_m = evaluator.evaluate(model, X_te, y_te, split="test")
        candidates.append(
            ModelCandidate(
                model_name=model_name,
                variant_id=config_id,
                validation=val_m,
                test=test_m,
                hyperparameters=hp,
            )
        )
    return candidates


def run_regime_model_optimization(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    feature_sets: dict[str, list[str]],
    event_schemes: list[str],
    regimes: list[str] | None = None,
    base_dir: str | None = None,
    seed: int = DEFAULT_SEED,
    hyperparameters: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Train models for regime × event × feature-set combinations."""
    hp = hyperparameters or {}
    work = df.copy()
    work["market_regime"] = assign_market_regime(work)
    regime_optimization_datasets_root(base_dir).mkdir(parents=True, exist_ok=True)

    target_regimes = regimes or list(REGIMES)
    selector = ModelSelector()
    all_candidates: list[ModelCandidate] = []
    configs: list[dict[str, Any]] = []
    saved: dict[str, str] = {}

    for regime in target_regimes:
        regime_df = work.loc[work["market_regime"] == regime]
        if len(regime_df) < MIN_ROWS:
            continue
        for scheme in event_schemes:
            filtered = apply_event_filter(regime_df, scheme)
            min_rows = MIN_ROWS if scheme == "A_all_events" else MIN_ROWS_FILTERED
            if len(filtered) < min_rows:
                continue
            for set_name, features in feature_sets.items():
                config_id = f"{regime}__{scheme}__{set_name}"
                try:
                    path = regime_optimization_dataset_path(symbol, timeframe, config_id, base_dir)
                    filtered.to_parquet(path, index=False)
                    saved[config_id] = str(path)
                    candidates = _train_candidate(
                        filtered,
                        features,
                        seed=seed,
                        config_id=config_id,
                        hyperparameters=hp,
                    )
                    if not candidates:
                        continue
                    best = selector.select_best(candidates)
                    all_candidates.extend(candidates)
                    configs.append(
                        {
                            "config_id": config_id,
                            "regime": regime,
                            "event_scheme": scheme,
                            "feature_set": set_name,
                            "rows": len(filtered),
                            "best_model": best.model_name,
                            "validation_roc_auc": best.validation.classification.get("roc_auc"),
                            "test_roc_auc": best.test.classification.get("roc_auc"),
                            "validation_expectancy": best.validation.trading.get("expectancy_R"),
                            "test_expectancy": best.test.trading.get("expectancy_R"),
                            "test_profit_factor": best.test.trading.get("profit_factor_proxy"),
                        }
                    )
                except Exception as exc:
                    configs.append({"config_id": config_id, "error": str(exc)})

    if not all_candidates:
        return {"candidates": [], "configurations": configs}

    best = selector.select_best(all_candidates)
    parts = best.variant_id.split("__")
    return {
        "phase": "9.6",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "configurations": configs,
        "comparison_table": selector.comparison_table(all_candidates),
        "best_candidate": best.to_dict(),
        "best_configuration": {
            "regime": parts[0] if len(parts) > 0 else "",
            "event_scheme": parts[1] if len(parts) > 1 else "",
            "feature_set": parts[2] if len(parts) > 2 else "",
            "model": best.model_name,
        },
        "saved_datasets": saved,
        "validation_roc_auc": best.validation.classification.get("roc_auc"),
        "test_roc_auc": best.test.classification.get("roc_auc"),
        "test_expectancy": best.test.trading.get("expectancy_R"),
        "test_profit_factor": best.test.trading.get("profit_factor_proxy"),
    }
