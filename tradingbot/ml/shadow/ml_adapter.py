"""Phase 10 — ML adapter for Phase 9.9 frozen model."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.paper_trading.model_registry import (
    IntegrityResult,
    Phase99Bundle,
    load_phase9_9_bundle,
    verify_bundle_integrity,
)
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

logger = logging.getLogger(__name__)


@dataclass
class MLPrediction:
    probability: float
    direction: str
    confidence: float
    timestamp: str
    features_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "probability": round(self.probability, 6),
            "direction": self.direction,
            "confidence": round(self.confidence, 6),
            "timestamp": self.timestamp,
            "features_hash": self.features_hash,
        }


@dataclass
class ModelValidation:
    status: str
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    dataset_fingerprint: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _features_hash(features: dict[str, float]) -> str:
    payload = json.dumps({k: features[k] for k in sorted(features)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class MLAdapter:
    """Load Phase 9.9 artifacts and produce ML predictions (no execution)."""

    def __init__(self, bundle: Phase99Bundle, *, model_version: str = "phase9_9_best") -> None:
        self.bundle = bundle
        self.model_version = model_version
        self.buy_threshold = float(bundle.config.get("buy_threshold", 0.55))
        self.sell_threshold = float(bundle.config.get("sell_threshold", 0.45))

    @classmethod
    def load(
        cls,
        *,
        base_dir: str | Path | None = None,
        training_df: Any = None,
        seed: int = 42,
        model_version: str = "phase9_9_best",
    ) -> "MLAdapter":
        bundle = load_phase9_9_bundle(
            base_dir=base_dir,
            build_if_missing=False,
        )
        return cls(bundle, model_version=model_version)

    def validate(self, features: dict[str, float] | None = None, *, dataset_df: Any = None) -> ModelValidation:
        checks: dict[str, bool] = {}
        errors: list[str] = []
        fp = ""
        if dataset_df is not None:
            fp = dataset_content_fingerprint(dataset_df)
            meta_fp = str(self.bundle.metadata.get("dataset_fingerprint", ""))
            checks["fingerprint"] = not meta_fp or meta_fp == fp
            if meta_fp and meta_fp != fp:
                errors.append("dataset fingerprint mismatch vs frozen metadata")

        order = self.bundle.feature_order
        checks["feature_order"] = len(order) >= 1
        checks["scaler_dims"] = int(getattr(self.bundle.scaler, "n_features_in_", len(order))) == len(order)

        probe = features or {name: 0.0 for name in order}
        integrity: IntegrityResult = verify_bundle_integrity(self.bundle, probe)
        checks["predict"] = integrity.passed
        errors.extend(integrity.errors)

        status = "PASS" if all(checks.values()) else "FAIL"
        return ModelValidation(status=status, checks=checks, errors=errors, dataset_fingerprint=fp)

    def predict(self, features: dict[str, float], *, timestamp: str | None = None) -> MLPrediction:
        subset = {k: float(features[k]) for k in self.bundle.feature_order if k in features}
        prob = self.bundle.predict_proba(subset)
        direction = self._direction(prob)
        confidence = abs(prob - 0.5) * 2.0
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        return MLPrediction(
            probability=prob,
            direction=direction,
            confidence=confidence,
            timestamp=ts,
            features_hash=_features_hash(subset),
        )

    def _direction(self, probability: float) -> str:
        if probability >= self.buy_threshold:
            return "BUY"
        if probability <= self.sell_threshold:
            return "SELL"
        return "HOLD"
