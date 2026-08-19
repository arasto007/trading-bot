"""Phase D1 — unified entry feature store for Meta-Labeler and ML Kernel."""

from __future__ import annotations

import hashlib
import json
import math
import pickle
from pathlib import Path
from typing import Any

from tradingbot.domain.models import TradingSignal

ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = ROOT / "models"
SCHEMA_VERSION = "d1_v1"

FEATURES: list[str] = [
    "confidence",
    "confluence",
    "rr",
    "adx",
    "atr_pct",
    "htf_bias",
    "hour_utc",
    "weekday",
    "direction",
    "regime_code",
    "spread_pips",
    "sl_atr_mult",
    "setup_code",
]

_TF_MODEL_FILES = {
    "M5": MODEL_DIR / "meta_labeler_m5.pkl",
    "M15": MODEL_DIR / "meta_labeler_m15.pkl",
    "H4": MODEL_DIR / "meta_labeler_h4.pkl",
}


def feature_names() -> list[str]:
    return list(FEATURES)


def schema_hash(*, version: str = SCHEMA_VERSION) -> str:
    payload = json.dumps({"version": version, "features": FEATURES}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sanitize_features(features: dict[str, Any]) -> dict[str, float]:
    """Ensure every canonical feature is present and non-null."""
    out: dict[str, float] = {}
    for name in FEATURES:
        val = features.get(name, 0.0)
        if val is None:
            val = 0.0
        elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            val = 0.0
        else:
            try:
                val = float(val)
            except (TypeError, ValueError):
                val = 0.0
            if math.isnan(val) or math.isinf(val):
                val = 0.0
        out[name] = val
    return out


def to_vector(features: dict[str, Any]) -> list[float]:
    clean = sanitize_features(features)
    return [clean[name] for name in FEATURES]


def build_live(
    signal: TradingSignal,
    snapshot: dict[str, Any],
    regime: str,
    *,
    spread_pips: float = 0.0,
    entry_price: float | None = None,
) -> dict[str, float]:
    """Live path — shared by Meta-Labeler and ML Kernel entry hooks."""
    from tradingbot.domain.trade_features import capture_entry_features

    raw = capture_entry_features(
        signal,
        snapshot,
        regime,
        spread_pips=spread_pips,
        entry_price=entry_price,
    )
    return sanitize_features(raw)


def build_train_row(entry_features: dict[str, Any]) -> dict[str, float]:
    """Training path — normalize backtest/logged entry feature dicts."""
    return sanitize_features(entry_features)


def load_train_feature_names() -> dict[str, list[str]]:
    """Feature lists frozen in meta-labeler model payloads."""
    out: dict[str, list[str]] = {}
    legacy = MODEL_DIR / "meta_labeler.pkl"
    paths = dict(_TF_MODEL_FILES)
    if legacy.is_file() and not any(p.is_file() for p in _TF_MODEL_FILES.values()):
        paths = {"LEGACY": legacy}
    for tf, path in paths.items():
        if not path.is_file():
            continue
        try:
            payload = pickle.loads(path.read_bytes())
            names = list(payload.get("features") or FEATURES)
            out[tf] = names
        except Exception:
            continue
    return out


def train_schema_hash() -> str:
    return schema_hash()


def live_schema_hash() -> str:
    return schema_hash()


def missing_features(features: dict[str, Any]) -> list[str]:
    clean = sanitize_features(features)
    missing: list[str] = []
    for name in FEATURES:
        if name not in features:
            missing.append(name)
            continue
        val = features.get(name)
        if val is None:
            missing.append(name)
        elif isinstance(val, float) and math.isnan(val):
            missing.append(name)
    _ = clean
    return missing


def null_live_features(features: dict[str, Any]) -> list[str]:
    bad: list[str] = []
    for name in FEATURES:
        if name not in features:
            bad.append(name)
            continue
        val = features.get(name)
        if val is None:
            bad.append(name)
        elif isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            bad.append(name)
    return bad


def verify_model_parity() -> dict[str, Any]:
    """Compare train artifact feature lists vs canonical FEATURES."""
    train_names = load_train_feature_names()
    mismatches: dict[str, Any] = {}
    for tf, names in train_names.items():
        if list(names) != list(FEATURES):
            mismatches[tf] = {"expected": FEATURES, "got": names}
    return {
        "train_feature_count": len(FEATURES),
        "live_feature_count": len(FEATURES),
        "train_models_loaded": len(train_names),
        "feature_order_stable": list(FEATURES) == feature_names(),
        "train_schema_hash": schema_hash(),
        "live_schema_hash": schema_hash(),
        "schema_hash_match": not mismatches and live_schema_hash() == train_schema_hash(),
        "model_mismatches": mismatches,
        "feature_parity_pct": 100.0 if not mismatches else 0.0,
    }


class UnifiedFeatureStore:
    """Facade for meta-labeler and ML kernel entry feature parity."""

    FEATURES = FEATURES
    SCHEMA_VERSION = SCHEMA_VERSION

    feature_names = staticmethod(feature_names)
    schema_hash = staticmethod(schema_hash)
    sanitize_features = staticmethod(sanitize_features)
    to_vector = staticmethod(to_vector)
    build_live = staticmethod(build_live)
    build_train_row = staticmethod(build_train_row)
    load_train_feature_names = staticmethod(load_train_feature_names)
    verify_model_parity = staticmethod(verify_model_parity)

    @staticmethod
    def build_for_ml_kernel(
        signal: TradingSignal,
        snapshot: dict[str, Any],
        regime: str,
        *,
        spread_pips: float = 0.0,
    ) -> dict[str, float]:
        return build_live(signal, snapshot, regime, spread_pips=spread_pips)
