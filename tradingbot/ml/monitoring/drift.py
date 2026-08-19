"""Feature drift detection — training vs recent shadow features."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import dataset_path
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry.registry import feature_names
from tradingbot.ml.memory.schema import DecisionRecord


@dataclass
class FeatureDriftEntry:
    feature_name: str
    drift_score: float
    severity: str
    mean_shift: float
    std_shift: float
    psi: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "drift_score": self.drift_score,
            "severity": self.severity,
            "mean_shift": self.mean_shift,
            "std_shift": self.std_shift,
            "psi": self.psi,
        }


@dataclass
class FeatureDriftReport:
    symbol: str
    timeframe: str
    aggregate_score: float
    severity: str
    features: list[FeatureDriftEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "aggregate_score": self.aggregate_score,
            "severity": self.severity,
            "features": [f.to_dict() for f in self.features],
        }


def _psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    if len(expected) == 0 or len(actual) == 0:
        return 0.0
    combined = np.concatenate([expected, actual])
    edges = np.linspace(float(combined.min()), float(combined.max()) + 1e-9, bins + 1)
    e_hist, _ = np.histogram(expected, bins=edges)
    a_hist, _ = np.histogram(actual, bins=edges)
    e_pct = np.clip(e_hist / max(e_hist.sum(), 1), 1e-6, None)
    a_pct = np.clip(a_hist / max(a_hist.sum(), 1), 1e-6, None)
    return float(np.sum((a_pct - e_pct) * np.log(a_pct / e_pct)))


def _severity(score: float) -> str:
    if score >= 0.25:
        return "HIGH"
    if score >= 0.10:
        return "MEDIUM"
    return "LOW"


@dataclass
class FeatureDriftDetector:
    """Compare training dataset feature distributions to recent shadow snapshots."""

    recent_count: int = 200
    mean_shift_threshold: float = 0.5
    std_shift_threshold: float = 0.5

    def analyze(
        self,
        decisions: list[DecisionRecord],
        *,
        symbol: str = "XAUUSD",
        timeframe: str = "M5",
        base_dir: str | None = None,
    ) -> FeatureDriftReport:
        baseline = self._load_baseline_features(symbol, timeframe, base_dir)
        recent = self._recent_feature_matrix(decisions)

        if baseline.empty or recent.empty:
            return FeatureDriftReport(symbol, timeframe, 0.0, "LOW")

        cols = [c for c in feature_names() if c in baseline.columns and c in recent.columns]
        entries: list[FeatureDriftEntry] = []

        for col in cols:
            b = baseline[col].astype(float).dropna().values
            r = recent[col].astype(float).dropna().values
            if len(b) < 5 or len(r) < 5:
                continue
            b_mean, b_std = float(np.mean(b)), max(float(np.std(b)), 1e-6)
            r_mean, r_std = float(np.mean(r)), max(float(np.std(r)), 1e-6)
            mean_shift = abs(r_mean - b_mean) / b_std
            std_shift = abs(r_std - b_std) / b_std
            psi = _psi(b, r)
            drift_score = round(float(max(mean_shift, std_shift, psi)), 4)
            entries.append(
                FeatureDriftEntry(
                    feature_name=col,
                    drift_score=drift_score,
                    severity=_severity(drift_score),
                    mean_shift=round(mean_shift, 4),
                    std_shift=round(std_shift, 4),
                    psi=round(psi, 4),
                )
            )

        aggregate = round(float(np.mean([e.drift_score for e in entries])), 4) if entries else 0.0
        return FeatureDriftReport(
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            aggregate_score=aggregate,
            severity=_severity(aggregate),
            features=sorted(entries, key=lambda e: -e.drift_score),
        )

    def _load_baseline_features(
        self,
        symbol: str,
        timeframe: str,
        base_dir: str | None,
    ) -> pd.DataFrame:
        store = DatasetStore(base_dir)
        df = store.load(symbol, timeframe)
        if df is None or df.empty:
            path = dataset_path(symbol, timeframe, base_dir)
            if path.is_file():
                df = pd.read_parquet(path)
        if df is None or df.empty:
            return pd.DataFrame()
        if "split" in df.columns:
            train = df[df["split"] == "train"]
            if not train.empty:
                return train
        return df

    def _recent_feature_matrix(self, decisions: list[DecisionRecord]) -> pd.DataFrame:
        rows: list[dict[str, float]] = []
        for d in sorted(decisions, key=lambda x: x.timestamp)[-self.recent_count :]:
            if d.features_snapshot:
                rows.append(d.features_snapshot)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)
