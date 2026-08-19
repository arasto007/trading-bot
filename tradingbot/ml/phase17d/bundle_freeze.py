"""Phase 17D — freeze validated RF+Top5 as trend_rf_v41 production bundle."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.decision_engine.decision_policy import TREND_ML_THRESHOLD, TREND_MODEL_ID
from tradingbot.ml.phase15a.config import (
    BUNDLE_VERSION_V41,
    DEFAULT_SEED,
    EXPECTED_DATASET_FINGERPRINT,
    TREND_ENGINE_V41_ID,
    trend_rf_bundle_root,
    write_json,
)
from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle, sha256_file
from tradingbot.ml.research.phase17b.config import DEFAULT_TRAIN_DAYS
from tradingbot.ml.research.phase17b.dataset import build_trend_dataset, chronological_split
from tradingbot.ml.research.phase17b.training_lab import train_research_rf
from tradingbot.ml.research.research_utils import dataset_content_fingerprint


def _git_metadata() -> dict[str, str | None]:
    try:
        rev = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True,
        ).strip()
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL, text=True,
        ).strip()
        return {"git_sha": rev, "git_branch": branch}
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return {"git_sha": None, "git_branch": None}


def _feature_statistics(samples: pd.DataFrame, feature_order: list[str]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for col in feature_order:
        if col not in samples.columns:
            continue
        s = samples[col].dropna().astype(float)
        stats[col] = {
            "count": int(len(s)),
            "mean": round(float(s.mean()), 6) if len(s) else 0.0,
            "std": round(float(s.std()), 6) if len(s) else 0.0,
            "min": round(float(s.min()), 6) if len(s) else 0.0,
            "max": round(float(s.max()), 6) if len(s) else 0.0,
        }
    scaler_means = {}
    scaler_scales = {}
    return {
        "distributions": stats,
        "scaler_means": scaler_means,
        "scaler_scales": scaler_scales,
    }


def _training_period(samples: pd.DataFrame) -> dict[str, str | None]:
    if samples.empty or "timestamp" not in samples.columns:
        return {"start": None, "end": None}
    ts = pd.to_datetime(samples["timestamp"], utc=True)
    return {"start": ts.min().isoformat(), "end": ts.max().isoformat()}


def freeze_trend_rf_v41(
    candles: pd.DataFrame,
    *,
    symbol: str = "XAUUSD",
    seed: int = DEFAULT_SEED,
    base_dir: str | Path | None = None,
) -> tuple[TrendRfBundle, dict[str, Any]]:
    """
    Train Phase 17B research RF+Top5 and persist as trend_rf_v41 bundle.
    Never touches trend_rf_bundle (v40).
    """
    raw = DatasetStore(base_dir).load_v2(symbol, "M5")
    fp = dataset_content_fingerprint(raw) if raw is not None and not raw.empty else EXPECTED_DATASET_FINGERPRINT

    samples = build_trend_dataset(candles, symbol=symbol)
    research, training_report = train_research_rf(samples, seed=seed)
    train, _, _ = chronological_split(samples)
    feature_order = list(research.feature_order)
    model = research.model
    scaler = research.scaler

    root = trend_rf_bundle_root(base_dir, version="v41")
    root.mkdir(parents=True, exist_ok=True)

    model_path = root / "model.pkl"
    scaler_path = root / "scaler.pkl"
    joblib.dump(model, model_path)
    joblib.dump(scaler, scaler_path)
    joblib.dump({"model": model, "scaler": scaler, "feature_order": feature_order}, root / "bundle.pkl")

    write_json(root / "feature_order.json", {"feature_order": feature_order})

    feat_stats = _feature_statistics(train, feature_order)
    if hasattr(scaler, "mean_") and hasattr(scaler, "scale_"):
        feat_stats["scaler_means"] = {
            f: round(float(m), 6) for f, m in zip(feature_order, scaler.mean_)
        }
        feat_stats["scaler_scales"] = {
            f: round(float(s), 6) for f, s in zip(feature_order, scaler.scale_)
        }
    write_json(root / "feature_statistics.json", feat_stats)

    frozen_at = datetime.now(timezone.utc).isoformat()
    period = _training_period(train)
    git_meta = _git_metadata()

    metadata = {
        "phase": "17D",
        "version": BUNDLE_VERSION_V41,
        "engine_id": TREND_ENGINE_V41_ID,
        "frozen_at_utc": frozen_at,
        "model": "random_forest",
        "feature_columns": feature_order,
        "feature_count": len(feature_order),
        "train_rows": len(train),
        "total_labeled_rows": len(samples),
        "training_period": period,
        "train_window_days": DEFAULT_TRAIN_DAYS,
        "dataset_fingerprint": fp,
        "training_fingerprint": f"rf_top5_seed{seed}_rows{len(train)}",
        "seed": seed,
        "hyperparameters": training_report.get("hyperparameters", {}),
        "git": git_meta,
        "promoted_from": "phase17c_research_rf_top5",
        "shuffled": False,
    }
    write_json(root / "metadata.json", metadata)

    training_manifest = {
        "phase": "17D",
        "bundle_version": BUNDLE_VERSION_V41,
        "training_report": training_report,
        "chronological": True,
        "scaler_fit_on": "train_only",
        "production_bundle_v40_modified": False,
    }
    write_json(root / "training_manifest.json", training_manifest)

    write_json(root / "version.json", {
        "engine_id": TREND_ENGINE_V41_ID,
        "bundle_version": BUNDLE_VERSION_V41,
        "bundle_dir": str(root),
        "rollback_engine": TREND_MODEL_ID,
        "active_env": "TREND_MODEL_VERSION",
    })

    cfg = {
        "engine_id": TREND_ENGINE_V41_ID,
        "model": "random_forest",
        "threshold": TREND_ML_THRESHOLD,
        "rule_fn": "evaluate_variant_a",
        "regime": "TREND",
        "seed": seed,
        "features": "base_11_plus_top5",
    }
    write_json(root / "config.json", cfg)

    model_hash = sha256_file(model_path)
    scaler_hash = sha256_file(scaler_path)
    bundle_hash = hashlib.sha256((model_hash + scaler_hash).encode()).hexdigest()

    checksum = {
        "model_sha256": model_hash,
        "scaler_sha256": scaler_hash,
        "bundle_sha256": bundle_hash,
        "version": BUNDLE_VERSION_V41,
        "created_at_utc": frozen_at,
    }
    write_json(root / "checksum.json", checksum)
    (root / "checksum.sha256").write_text(f"bundle_sha256={bundle_hash}\n", encoding="utf-8")

    bundle = TrendRfBundle(
        model=model,
        scaler=scaler,
        feature_order=feature_order,
        config=cfg,
        metadata=metadata,
        checksum=checksum,
    )
    manifest = {
        "phase": "17D",
        "bundle_version": BUNDLE_VERSION_V41,
        "engine_id": TREND_ENGINE_V41_ID,
        "bundle_dir": str(root),
        "artifacts": [a for a in BUNDLE_ARTIFACTS if (root / a).is_file()],
        "checksum": checksum,
        "metadata": metadata,
        "training_manifest": training_manifest,
    }
    return bundle, manifest


BUNDLE_ARTIFACTS = (
    "bundle.pkl",
    "model.pkl",
    "scaler.pkl",
    "feature_order.json",
    "feature_statistics.json",
    "metadata.json",
    "training_manifest.json",
    "checksum.sha256",
    "version.json",
    "config.json",
)
