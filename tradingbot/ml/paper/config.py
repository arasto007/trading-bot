"""Phase 11 — kernel paper trading configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    phase9_9_config_path,
    phase9_9_feature_order_path,
    phase9_9_metadata_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle


def _load_expected_features(base_dir: str | Path | None = None) -> list[str]:
    path = phase9_9_feature_order_path(base_dir)
    if not path.is_file():
        return []
    order_payload = json.loads(path.read_text(encoding="utf-8"))
    return list(order_payload.get("feature_order") or order_payload.get("features") or [])


@dataclass
class PaperTradingConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    model: str = "phase9_9_best"
    risk_pct: float = 0.005
    paper_days: int = 30
    paper_hours: int | None = None
    mode: str = "replay"  # replay | live
    seed: int = 42
    initial_balance: float = 10_000.0
    tp_r: float = 2.0
    sl_r: float = 1.0
    max_hold_bars: int = 72
    skip_preflight: bool = False
    skip_model_validation: bool = False
    candles_df: Any = None
    poll_interval_sec: float = 30.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "11",
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "model": self.model,
            "risk_pct": self.risk_pct,
            "paper_days": self.paper_days,
            "paper_hours": self.paper_hours,
            "mode": self.mode,
            "seed": self.seed,
            "initial_balance": self.initial_balance,
            "tp_r": self.tp_r,
            "sl_r": self.sl_r,
            "max_hold_bars": self.max_hold_bars,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def validate_frozen_model(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    """Validate Phase 9.9 frozen artifacts; raise on mismatch."""
    paths = {
        "model": phase9_9_model_path(base_dir),
        "scaler": phase9_9_scaler_path(base_dir),
        "feature_order": phase9_9_feature_order_path(base_dir),
        "config": phase9_9_config_path(base_dir),
        "metadata": phase9_9_metadata_path(base_dir),
    }
    missing = [k for k, p in paths.items() if not p.is_file()]
    if missing:
        raise RuntimeError(f"Phase 9.9 artifacts missing: {missing}")

    config = json.loads(paths["config"].read_text(encoding="utf-8"))
    order_payload = json.loads(paths["feature_order"].read_text(encoding="utf-8"))
    features = list(order_payload.get("feature_order") or order_payload.get("features") or [])
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    expected_features = _load_expected_features(base_dir)

    if expected_features and features != expected_features:
        raise RuntimeError(f"Feature order mismatch: {features} != {expected_features}")
    if config.get("features") != features:
        raise RuntimeError("Config features mismatch with frozen Phase 9.9 feature order")
    if metadata.get("phase") not in ("9.9", "9.10", "11"):
        raise RuntimeError(f"Unexpected metadata phase: {metadata.get('phase')}")

    bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    report = {
        "status": "PASS",
        "model_checksum": _sha256(paths["model"]),
        "scaler_checksum": _sha256(paths["scaler"]),
        "feature_order": features,
        "dataset_fingerprint": metadata.get("dataset_fingerprint"),
        "config": config,
    }
    _ = bundle
    return report
