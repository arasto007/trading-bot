"""Phase 15A — frozen trend RF v40 production bundle."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from tradingbot.ml.data.stores.candle_store import CandleStore
from tradingbot.ml.decision_engine.decision_policy import TREND_ML_THRESHOLD, TREND_MODEL_ID
from tradingbot.ml.phase15a.config import (
    BUNDLE_VERSION,
    DEFAULT_SEED,
    EXPECTED_DATASET_FINGERPRINT,
    trend_rf_checksum_path,
    trend_rf_config_path,
    trend_rf_feature_order_path,
    trend_rf_metadata_path,
    trend_rf_model_path,
    trend_rf_bundle_root,
    trend_rf_scaler_path,
    write_json,
)
from tradingbot.ml.research.phase13_8.trend_label_v2 import build_labeled_samples
from tradingbot.ml.research.phase13_8.trend_ml_retrainer import fit_production_model
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS, build_ml_features

logger = logging.getLogger(__name__)


@dataclass
class TrendRfBundle:
    model: Any
    scaler: Any
    feature_order: list[str]
    config: dict[str, Any]
    metadata: dict[str, Any]
    checksum: dict[str, str] = field(default_factory=dict)

    @property
    def version(self) -> str:
        return str(self.metadata.get("version", BUNDLE_VERSION))

    def transform(self, row: pd.Series | dict[str, float]) -> np.ndarray:
        if isinstance(row, dict):
            frame = pd.DataFrame([{k: row[k] for k in self.feature_order}])
        else:
            frame = pd.DataFrame([row[self.feature_order].astype(np.float64)])
        return self.scaler.transform(frame.values)

    def predict_proba(self, row: pd.Series | dict[str, float]) -> float:
        X = self.transform(row)
        proba = self.model.predict_proba(X)[0]
        return float(proba[1])


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _default_config() -> dict[str, Any]:
    return {
        "engine_id": TREND_MODEL_ID,
        "model": "random_forest",
        "threshold": TREND_ML_THRESHOLD,
        "rule_fn": "evaluate_variant_a",
        "regime": "TREND",
        "seed": DEFAULT_SEED,
    }


def freeze_trend_bundle_from_candles(
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    seed: int = DEFAULT_SEED,
    base_dir: str | Path | None = None,
    dataset_fingerprint: str | None = None,
) -> TrendRfBundle:
    """Serialize current production trend fit — same path as load_production_engines, no hyperparameter change."""
    frame = build_ml_features(candles)
    samples = build_labeled_samples(
        frame, symbol=symbol, rule_fn=evaluate_variant_a, label_key="label_a_tp_before_sl"
    )
    if samples.empty:
        raise ValueError("Insufficient labeled samples to freeze trend bundle")
    model, scaler, feature_order = fit_production_model(samples, model_name="random_forest", seed=seed)
    return _persist_bundle(
        model, scaler, feature_order, seed=seed, base_dir=base_dir,
        train_rows=len(samples), dataset_fingerprint=dataset_fingerprint,
    )


def freeze_trend_bundle(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = DEFAULT_SEED,
    base_dir: str | Path | None = None,
) -> TrendRfBundle:
    from tradingbot.ml.dataset.store import DatasetStore

    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        raise FileNotFoundError(f"Candles not found for {symbol} {timeframe}")
    raw = DatasetStore(base_dir).load_v2(symbol, timeframe)
    fp = dataset_content_fingerprint(raw) if raw is not None and not raw.empty else EXPECTED_DATASET_FINGERPRINT
    return freeze_trend_bundle_from_candles(candles, symbol=symbol, seed=seed, base_dir=base_dir, dataset_fingerprint=fp)


def _persist_bundle(
    model: Any,
    scaler: Any,
    feature_order: list[str],
    *,
    seed: int,
    base_dir: str | Path | None,
    train_rows: int,
    dataset_fingerprint: str | None,
) -> TrendRfBundle:
    root = trend_rf_bundle_root(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, trend_rf_model_path(base_dir))
    joblib.dump(scaler, trend_rf_scaler_path(base_dir))
    write_json(trend_rf_feature_order_path(base_dir), {"feature_order": feature_order})
    cfg = _default_config()
    write_json(trend_rf_config_path(base_dir), cfg)

    model_hash = sha256_file(trend_rf_model_path(base_dir))
    scaler_hash = sha256_file(trend_rf_scaler_path(base_dir))
    bundle_hash = hashlib.sha256((model_hash + scaler_hash).encode()).hexdigest()

    metadata = {
        "phase": "15A",
        "version": BUNDLE_VERSION,
        "engine_id": TREND_MODEL_ID,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "random_forest",
        "feature_columns": feature_order,
        "train_rows": train_rows,
        "dataset_fingerprint": dataset_fingerprint or EXPECTED_DATASET_FINGERPRINT,
        "training_fingerprint": f"rf_seed{seed}_rows{train_rows}",
        "seed": seed,
    }
    write_json(trend_rf_metadata_path(base_dir), metadata)

    checksum = {
        "model_sha256": model_hash,
        "scaler_sha256": scaler_hash,
        "bundle_sha256": bundle_hash,
        "version": BUNDLE_VERSION,
        "created_at_utc": metadata["frozen_at_utc"],
    }
    write_json(trend_rf_checksum_path(base_dir), checksum)
    logger.info("Frozen trend RF bundle at %s", root)
    return TrendRfBundle(model=model, scaler=scaler, feature_order=feature_order, config=cfg, metadata=metadata, checksum=checksum)


def _load_checksum_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if path.suffix == ".sha256" and "=" in text:
        digest = text.split("=", 1)[-1].strip()
        return {"bundle_sha256": digest, "version": None}
    return json.loads(text)


def load_trend_bundle(
    *,
    base_dir: str | Path | None = None,
    build_if_missing: bool = False,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    seed: int = DEFAULT_SEED,
    version: str = "v40",
) -> TrendRfBundle:
    model_path = trend_rf_model_path(base_dir, version=version)
    if not model_path.is_file():
        if build_if_missing and version == "v40":
            return freeze_trend_bundle(symbol=symbol, timeframe=timeframe, seed=seed, base_dir=base_dir)
        raise FileNotFoundError(f"Trend RF bundle not found: {model_path}")

    model = joblib.load(model_path)
    scaler = joblib.load(trend_rf_scaler_path(base_dir, version=version))
    order_payload = json.loads(trend_rf_feature_order_path(base_dir, version=version).read_text(encoding="utf-8"))
    feature_order = list(order_payload.get("feature_order", list(TREND_ML_FEATURE_COLUMNS)))
    config_path = trend_rf_config_path(base_dir, version=version)
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else _default_config()
    meta_path = trend_rf_metadata_path(base_dir, version=version)
    metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    checksum_path = trend_rf_checksum_path(base_dir, version=version)
    checksum = _load_checksum_payload(checksum_path)
    return TrendRfBundle(
        model=model, scaler=scaler, feature_order=feature_order,
        config=config, metadata=metadata, checksum=checksum,
    )


def validate_trend_checksum(
    *,
    base_dir: str | Path | None = None,
    version: str = "v40",
) -> dict[str, Any]:
    model_path = trend_rf_model_path(base_dir, version=version)
    checksum_path = trend_rf_checksum_path(base_dir, version=version)
    if not model_path.is_file() or not checksum_path.is_file():
        return {"valid": False, "reason": "bundle_or_checksum_missing", "version": version}
    stored = _load_checksum_payload(checksum_path)
    model_hash = sha256_file(model_path)
    scaler_hash = sha256_file(trend_rf_scaler_path(base_dir, version=version))
    bundle_hash = hashlib.sha256((model_hash + scaler_hash).encode()).hexdigest()
    stored_bundle = stored.get("bundle_sha256")
    valid = (
        model_hash == stored.get("model_sha256", model_hash)
        and scaler_hash == stored.get("scaler_sha256", scaler_hash)
        and (stored_bundle is None or bundle_hash == stored_bundle)
    )
    return {
        "valid": valid,
        "model_sha256": model_hash,
        "stored_model_sha256": stored.get("model_sha256"),
        "bundle_sha256": bundle_hash,
        "stored_bundle_sha256": stored_bundle,
        "version": stored.get("version"),
        "bundle_version": version,
    }
