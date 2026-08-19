"""Phase 8.5 training readiness report — pre-training gate summary."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.data.paths import reports_dir, train_readiness_report_path
from tradingbot.ml.dataset.feature_analysis import analyze_features
from tradingbot.ml.dataset.label_analysis import analyze_label_distribution
from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor
from tradingbot.ml.dataset.regime_analysis import analyze_regimes
from tradingbot.ml.dataset.sanity_gate import DatasetSanityGate
from tradingbot.ml.dataset.splitter import verify_chronological_splits


@dataclass
class TrainReadinessReport:
    symbol: str
    timeframe: str
    generated_at_utc: str
    dataset_valid: bool
    label_balance: str
    feature_quality: str
    leakage_check: str
    regime_coverage: str
    temporal_stability: str
    dataset_size: int
    recommended_for_training: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TrainReadinessAnalyzer:
    """Aggregate sanity, quality, leakage, and regime checks into a training gate."""

    def __init__(self, *, min_samples: int = 500) -> None:
        self._sanity = DatasetSanityGate(min_samples=min_samples)
        self._leakage = DatasetLeakageAuditor()

    def analyze(self, df: pd.DataFrame, symbol: str, timeframe: str) -> TrainReadinessReport:
        now = datetime.now(timezone.utc).isoformat()
        if df is None or df.empty:
            return TrainReadinessReport(
                symbol=symbol.upper(),
                timeframe=timeframe.upper(),
                generated_at_utc=now,
                dataset_valid=False,
                label_balance="imbalanced",
                feature_quality="degraded",
                leakage_check="fail",
                regime_coverage="weak",
                temporal_stability="unstable",
                dataset_size=0,
                recommended_for_training=False,
                details={"error": "empty_dataset"},
            )

        sanity = self._sanity.evaluate(df, symbol, timeframe)
        label = analyze_label_distribution(df, symbol, timeframe)
        features = analyze_features(df, symbol, timeframe)
        leakage = self._leakage.audit(df, symbol, timeframe)
        regimes = analyze_regimes(df, symbol, timeframe)

        label_status = "ok" if label.status in ("healthy", "acceptable") else "imbalanced"
        if any(i.severity == "error" and i.code == "label_imbalance" for i in sanity.issues):
            label_status = "imbalanced"

        feature_quality = "good"
        if features.constant_features or features.missing_features:
            feature_quality = "degraded"
        if any(i.severity == "error" and i.code in ("nan_spike", "inf_values") for i in sanity.issues):
            feature_quality = "degraded"

        leakage_status = leakage.status if leakage.status in ("pass", "fail") else "fail"
        if leakage_status != "pass":
            leakage_status = "fail"

        regime_status = "sufficient"
        vol_buckets = regimes.volatility
        populated = sum(1 for b in vol_buckets.values() if b.get("samples", 0) >= 10)
        if populated < 2:
            regime_status = "weak"

        temporal = "stable"
        if not verify_chronological_splits(df):
            temporal = "unstable"
        if "timestamp" in df.columns and len(df) > 1:
            ts = pd.to_datetime(df["timestamp"], utc=True)
            if ts.dt.tz is not None:
                ts = ts.dt.tz_convert("UTC").dt.tz_localize(None)
            monthly = ts.dt.to_period("M").value_counts()
            if len(monthly) > 1 and monthly.min() < max(5, len(df) * 0.02):
                temporal = "unstable"

        dataset_valid = sanity.passed and leakage_status == "pass" and label_status == "ok"
        recommended = dataset_valid and feature_quality == "good" and regime_status == "sufficient"

        return TrainReadinessReport(
            symbol=symbol.upper(),
            timeframe=timeframe.upper(),
            generated_at_utc=now,
            dataset_valid=dataset_valid,
            label_balance=label_status,
            feature_quality=feature_quality,
            leakage_check=leakage_status,
            regime_coverage=regime_status,
            temporal_stability=temporal,
            dataset_size=len(df),
            recommended_for_training=recommended,
            details={
                "sanity": sanity.to_dict(),
                "label_analysis": label.to_dict(),
                "feature_analysis": features.to_dict(),
                "leakage": leakage.to_dict(),
                "regime_analysis": regimes.to_dict(),
            },
        )

    def analyze_and_save(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        base_dir: str | Path | None = None,
    ) -> tuple[TrainReadinessReport, Path]:
        reports_dir(base_dir).mkdir(parents=True, exist_ok=True)
        report = self.analyze(df, symbol, timeframe)
        path = train_readiness_report_path(symbol, timeframe, base_dir)
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return report, path
