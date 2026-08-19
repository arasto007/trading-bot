"""Feature research analysis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.models.dataset_loader import RESOLVED_LABELS, resolve_feature_columns


@dataclass
class FeatureResearchAnalyzer:
    """Analyze feature importance, stability, drift, and regime/session contribution."""

    base_dir: str | Path | None = None
    stability_threshold: float = 0.15
    drift_threshold: float = 0.20

    def analyze(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        symbol = symbol.upper()
        timeframe = timeframe.upper()
        df = self._load_dataset(symbol, timeframe)

        if df is None or df.empty:
            return self._empty_report(symbol, timeframe)

        feature_cols = resolve_feature_columns(df)
        if not feature_cols:
            return self._empty_report(symbol, timeframe, reason="no_features")

        importance = self._feature_importance_proxy(df, feature_cols)
        stability = self._feature_stability(df, feature_cols)
        drift = self._feature_drift(df, feature_cols)
        correlations = self._correlation_changes(df, feature_cols)
        regime_dep = self._regime_contribution(df, feature_cols)
        session_dep = self._session_contribution(df, feature_cols)

        best = sorted(importance, key=importance.get, reverse=True)[:10]
        unstable = [f for f, score in stability.items() if score < self.stability_threshold]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "feature_count": len(feature_cols),
            "best_features": best,
            "unstable_features": unstable,
            "importance": importance,
            "stability_scores": stability,
            "drift_scores": drift,
            "correlation_changes": correlations,
            "regime_dependency": regime_dep,
            "session_dependency": session_dep,
        }

    def write_report(self, symbol: str, timeframe: str = "M5") -> dict[str, Any]:
        payload = self.analyze(symbol, timeframe)
        path = reports_dir(self.base_dir) / "feature_research_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            __import__("json").dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return payload

    def _load_dataset(self, symbol: str, timeframe: str) -> pd.DataFrame | None:
        store = DatasetStore(self.base_dir)
        df = store.load(symbol, timeframe)
        if df is None or df.empty:
            return None
        work = df[df["label"].isin(RESOLVED_LABELS)].copy() if "label" in df.columns else df.copy()
        if "timestamp" in work.columns:
            work = work.sort_values("timestamp").reset_index(drop=True)
        return work

    @staticmethod
    def _empty_report(symbol: str, timeframe: str, reason: str = "no_dataset") -> dict[str, Any]:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "feature_count": 0,
            "best_features": [],
            "unstable_features": [],
            "regime_dependency": {},
            "session_dependency": {},
            "reason": reason,
        }

    @staticmethod
    def _feature_importance_proxy(df: pd.DataFrame, cols: list[str]) -> dict[str, float]:
        if "label" not in df.columns:
            return {c: 0.0 for c in cols}
        y = df["label"].astype(float)
        scores: dict[str, float] = {}
        for col in cols:
            x = df[col].astype(float).fillna(0.0)
            if x.std() < 1e-9:
                scores[col] = 0.0
                continue
            corr = abs(float(x.corr(y)))
            scores[col] = round(corr if not np.isnan(corr) else 0.0, 4)
        return scores

    @staticmethod
    def _feature_stability(df: pd.DataFrame, cols: list[str]) -> dict[str, float]:
        if len(df) < 20:
            return {c: 1.0 for c in cols}
        mid = len(df) // 2
        first = df.iloc[:mid]
        second = df.iloc[mid:]
        scores: dict[str, float] = {}
        for col in cols:
            m1 = float(first[col].astype(float).mean())
            m2 = float(second[col].astype(float).mean())
            std = float(df[col].astype(float).std()) or 1.0
            drift = abs(m1 - m2) / std
            scores[col] = round(max(0.0, 1.0 - min(1.0, drift)), 4)
        return scores

    @staticmethod
    def _feature_drift(df: pd.DataFrame, cols: list[str]) -> dict[str, float]:
        if len(df) < 30:
            return {c: 0.0 for c in cols}
        window = max(10, len(df) // 5)
        scores: dict[str, float] = {}
        for col in cols:
            series = df[col].astype(float).fillna(0.0)
            rolling_mean = series.rolling(window, min_periods=1).mean()
            rolling_std = series.rolling(window, min_periods=1).std().fillna(1.0)
            z = ((series - rolling_mean) / rolling_std.replace(0, 1)).abs()
            scores[col] = round(float(z.mean()), 4)
        return scores

    @staticmethod
    def _correlation_changes(df: pd.DataFrame, cols: list[str]) -> dict[str, float]:
        if len(df) < 20 or len(cols) < 2:
            return {}
        mid = len(df) // 2
        changes: dict[str, float] = {}
        subset = cols[: min(20, len(cols))]
        c1 = df.iloc[:mid][subset].astype(float).corr()
        c2 = df.iloc[mid:][subset].astype(float).corr()
        for col in subset:
            if col in c1.columns and col in c2.columns:
                diff = (c1[col] - c2[col]).abs().mean()
                changes[col] = round(float(diff) if not np.isnan(diff) else 0.0, 4)
        return changes

    @staticmethod
    def _regime_contribution(df: pd.DataFrame, cols: list[str]) -> dict[str, dict[str, float]]:
        if "regime" not in df.columns or "label" not in df.columns:
            return {}
        out: dict[str, dict[str, float]] = {}
        for regime, group in df.groupby("regime"):
            if len(group) < 5:
                continue
            y = group["label"].astype(float)
            scores = {}
            for col in cols[:15]:
                x = group[col].astype(float).fillna(0.0)
                if x.std() < 1e-9:
                    continue
                corr = x.corr(y)
                if not np.isnan(corr):
                    scores[col] = round(abs(float(corr)), 4)
            if scores:
                out[str(regime)] = scores
        return out

    @staticmethod
    def _session_contribution(df: pd.DataFrame, cols: list[str]) -> dict[str, dict[str, float]]:
        session_col = next((c for c in ("session", "session_name") if c in df.columns), None)
        if session_col is None or "label" not in df.columns:
            return {}
        out: dict[str, dict[str, float]] = {}
        for session, group in df.groupby(session_col):
            if len(group) < 5:
                continue
            y = group["label"].astype(float)
            scores = {}
            for col in cols[:15]:
                x = group[col].astype(float).fillna(0.0)
                if x.std() < 1e-9:
                    continue
                corr = x.corr(y)
                if not np.isnan(corr):
                    scores[col] = round(abs(float(corr)), 4)
            if scores:
                out[str(session)] = scores
        return out
