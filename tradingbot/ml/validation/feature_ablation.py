"""Feature ablation — remove one feature family at a time."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.features.registry.registry import all_features
from tradingbot.ml.models.dataset_loader import load_dataset_splits
from tradingbot.ml.models.evaluator import expected_r_from_proba
from tradingbot.ml.models.training import create_model
from tradingbot.ml.validation._utils import write_json_report

FAMILY_ALIASES: dict[str, str] = {
    "trend": "trend",
    "momentum": "momentum",
    "volatility": "volatility",
    "price_action": "price_action",
    "smc": "smc_structure",
    "context": "htf_context",
    "session": "session",
    "microstructure": "microstructure",
}

ABLATION_FAMILIES = tuple(FAMILY_ALIASES.keys())


@dataclass
class AblationEntry:
    removed: str
    registry_family: str
    features_removed: int
    baseline_expected_R: float
    ablated_expected_R: float
    expected_R_drop: float
    importance: str


@dataclass
class FeatureAblationReport:
    model: str
    symbol: str
    timeframe: str
    split: str
    baseline_expected_R: float
    ablations: list[AblationEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _family_feature_map() -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {k: [] for k in FAMILY_ALIASES}
    for defn in all_features():
        for alias, reg_family in FAMILY_ALIASES.items():
            if defn.family == reg_family:
                mapping[alias].append(defn.name)
    return mapping


def _importance_label(drop: float) -> str:
    ad = abs(drop)
    if ad >= 0.15:
        return "high"
    if ad >= 0.05:
        return "medium"
    return "low"


def _expected_r_on_split(
    model_name: str,
    X,
    y,
    feature_cols: list[str],
    model_params: dict[str, Any] | None,
) -> float:
    model = create_model(model_name, model_params)
    model.fit(X[feature_cols], y)
    proba = model.predict_proba(X[feature_cols])
    return round(float(expected_r_from_proba(proba).mean()), 4)


def run_feature_ablation(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    split: str = "validation",
    model_params: dict[str, Any] | None = None,
    save: bool = True,
) -> FeatureAblationReport:
    splits = load_dataset_splits(symbol, timeframe, base_dir)
    split_map = {
        "train": splits.train,
        "validation": splits.validation,
        "test": splits.test,
    }
    df = split_map[split]
    if df.empty:
        raise ValueError(f"Split '{split}' is empty")

    feature_cols = splits.feature_columns
    X = df[feature_cols]
    y = df["label"].astype(int)

    # Train baseline on train split, evaluate on target split
    train_df = splits.train
    if train_df.empty:
        raise ValueError("Training split is empty")

    baseline_model = create_model(model_name, model_params)
    baseline_model.fit(train_df[feature_cols], train_df["label"].astype(int))
    baseline_proba = baseline_model.predict_proba(X)
    baseline_exp_r = round(float(expected_r_from_proba(baseline_proba).mean()), 4)

    family_map = _family_feature_map()
    ablations: list[AblationEntry] = []

    for family in ABLATION_FAMILIES:
        remove_feats = set(family_map.get(family, []))
        keep_cols = [c for c in feature_cols if c not in remove_feats]
        if len(keep_cols) == len(feature_cols):
            continue

        ablated_model = create_model(model_name, model_params)
        ablated_model.fit(train_df[keep_cols], train_df["label"].astype(int))
        ablated_proba = ablated_model.predict_proba(X[keep_cols])
        ablated_exp_r = round(float(expected_r_from_proba(ablated_proba).mean()), 4)
        drop = round(baseline_exp_r - ablated_exp_r, 4)

        ablations.append(
            AblationEntry(
                removed=family,
                registry_family=FAMILY_ALIASES[family],
                features_removed=len(remove_feats),
                baseline_expected_R=baseline_exp_r,
                ablated_expected_R=ablated_exp_r,
                expected_R_drop=drop,
                importance=_importance_label(drop),
            )
        )

    report = FeatureAblationReport(
        model=model_name.lower(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        split=split,
        baseline_expected_R=baseline_exp_r,
        ablations=ablations,
    )

    if save:
        payload = [
            {
                "removed": a.removed,
                "expected_R_drop": a.expected_R_drop,
                "importance": a.importance,
            }
            for a in ablations
        ]
        write_json_report(reports_dir(base_dir) / "feature_ablation.json", {"ablations": payload})

    return report
