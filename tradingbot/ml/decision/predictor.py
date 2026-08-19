"""ML predictor — load model artifacts and produce MLDecision (deterministic)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.decision.confidence import ConfidenceConfig, confidence_from_probability
from tradingbot.ml.decision.explain import explain_decision
from tradingbot.ml.decision.policy import DecisionPolicy
from tradingbot.ml.decision.schema import MLDecision, direction_label, utc_now_iso
from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION
from tradingbot.ml.features.scaling import ScalerMetadata, load_scaler_metadata, transform_with_metadata
from tradingbot.ml.models.artifacts import model_metadata_path, read_metadata
from tradingbot.ml.models.registry import get_model_entry
from tradingbot.ml.models.training import load_model


def _features_hash(values: dict[str, float]) -> str:
    payload = json.dumps(values, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_threshold(model_name: str, base_dir: str | Path | None) -> float:
    path = reports_dir(base_dir) / "optimal_threshold.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("model", "").lower() == model_name.lower():
            return float(data.get("best_threshold", 0.5))
    return 0.5


class MLPredictor:
    """
    Offline inference — loads trained model, schema, scaler metadata, threshold.

    Deterministic: fixed feature column order from training metadata.
    """

    def __init__(
        self,
        symbol: str,
        timeframe: str,
        model_name: str,
        *,
        base_dir: str | Path | None = None,
        model_version: str = "1.0",
        confidence_config: ConfidenceConfig | None = None,
        policy: DecisionPolicy | None = None,
        apply_scaler: bool = False,
    ) -> None:
        self.symbol = symbol.upper()
        self.timeframe = timeframe.upper()
        self.model_name = model_name.lower()
        self.base_dir = base_dir
        self.model_version = model_version
        self.confidence_config = confidence_config or ConfidenceConfig()
        self.policy = policy or DecisionPolicy()
        self.apply_scaler = apply_scaler

        self._model = None
        self._metadata: dict[str, Any] = {}
        self._feature_columns: list[str] = []
        self._threshold = 0.5
        self._scaler_meta: ScalerMetadata | None = None
        self._dataset_version = ""
        self._loaded = False

    def load(self) -> "MLPredictor":
        meta_path = model_metadata_path(self.model_name, self.base_dir)
        if not meta_path.is_file():
            raise FileNotFoundError(f"Model metadata not found: {meta_path}")

        self._metadata = read_metadata(meta_path)
        self._feature_columns = list(self._metadata.get("feature_columns") or [])
        if not self._feature_columns and self._model is not None:
            self._feature_columns = list(getattr(self._model, "feature_names_", []))

        self._model = load_model(self.model_name, self.base_dir)
        if not self._feature_columns:
            self._feature_columns = list(getattr(self._model, "feature_names_", []))
        if not self._feature_columns:
            raise ValueError("No feature columns available from model metadata")

        self._threshold = _load_threshold(self.model_name, self.base_dir)
        registry = get_model_entry(self.model_name, self.model_version, self.base_dir)
        self._dataset_version = (
            (registry or {}).get("feature_version")
            or self._metadata.get("feature_schema_version")
            or FEATURE_SCHEMA_VERSION
        )

        scaler_raw = load_scaler_metadata(self.symbol, self.timeframe, self.base_dir)
        if scaler_raw:
            from tradingbot.ml.features.scaling import ColumnScalerMeta, ScalerMetadata

            columns = [
                ColumnScalerMeta(**c) for c in scaler_raw.get("columns", []) if isinstance(c, dict)
            ]
            self._scaler_meta = ScalerMetadata(
                symbol=scaler_raw.get("symbol", self.symbol),
                timeframe=scaler_raw.get("timeframe", self.timeframe),
                feature_schema_version=scaler_raw.get("feature_schema_version", FEATURE_SCHEMA_VERSION),
                methods=scaler_raw.get("methods", ["standard"]),
                columns=columns,
                row_count=int(scaler_raw.get("row_count", 0)),
                generated_at_utc=scaler_raw.get("generated_at_utc", ""),
            )

        self._loaded = True
        return self

    @property
    def feature_columns(self) -> list[str]:
        return list(self._feature_columns)

    @property
    def threshold(self) -> float:
        return self._threshold

    def predict_row(self, row: dict[str, Any] | pd.Series) -> MLDecision:
        """Run inference on a single feature row (dict or Series)."""
        if not self._loaded:
            self.load()
        assert self._model is not None

        data = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        ts = str(data.get("timestamp") or utc_now_iso())
        raw_direction = data.get("direction")

        feat_values: dict[str, float] = {}
        for col in self._feature_columns:
            val = data.get(col, 0.0)
            feat_values[col] = 0.0 if pd.isna(val) else float(val)

        frame = pd.DataFrame([feat_values], columns=self._feature_columns)
        if self.apply_scaler and self._scaler_meta is not None:
            method = self._scaler_meta.methods[0] if self._scaler_meta.methods else "standard"
            frame = transform_with_metadata(frame, self._scaler_meta, method=method)  # type: ignore[arg-type]

        proba = self._model.predict_proba(frame)
        pred = int(self._model.predict(frame)[0])
        win_prob = float(proba[0, 1])

        confidence = confidence_from_probability(win_prob, self.confidence_config)
        direction = direction_label(raw_direction)

        decision = MLDecision(
            timestamp=ts,
            symbol=self.symbol,
            timeframe=self.timeframe,
            model_name=self.model_name,
            model_version=self.model_version,
            prediction=pred,
            probability=round(win_prob, 4),
            direction=direction,
            confidence=confidence,
            threshold_used=round(self._threshold, 4),
            accepted=False,
            reason="",
            features_hash=_features_hash(feat_values),
            dataset_version=str(self._dataset_version),
            explanation=explain_decision(feat_values, direction=direction, prediction=pred),
        )

        policy_result = self.policy.evaluate(
            decision,
            feature_row=data,
            required_features=self._feature_columns,
            model_valid=True,
        )
        decision.accepted = policy_result.accepted
        decision.reason = policy_result.reason
        return decision
