"""Phase 9.4 — retraining report generation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import phase9_4_retraining_report_path, training_comparison_report_path
from tradingbot.ml.research.model_selection import ModelCandidate

PHASE = "9.4"


def load_phase92_baseline(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Load Phase 9.2 training comparison report for baseline metrics."""
    path = training_comparison_report_path(base_dir)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    best = payload.get("best_model", "")
    evals = payload.get("evaluations", {})
    best_eval = evals.get(best, {})
    return {
        "phase": payload.get("phase", "9.2"),
        "best_model": best,
        "selection_criteria": payload.get("selection_criteria"),
        "validation": best_eval.get("validation", {}),
        "test": best_eval.get("test", {}),
        "selection_scores": payload.get("selection_scores", {}),
    }


def _extract_cls(metrics: dict[str, Any], key: str) -> float:
    cls = metrics.get("classification", {})
    return float(cls.get(key, 0.0))


def _improved_over_baseline(
    candidate: ModelCandidate,
    baseline: dict[str, Any],
) -> dict[str, Any]:
    base_val = baseline.get("validation", {})
    cand_val = candidate.validation.to_dict()
    base_auc = _extract_cls(base_val, "roc_auc")
    cand_auc = _extract_cls(cand_val, "roc_auc")
    return {
        "validation_roc_auc_delta": round(cand_auc - base_auc, 4),
        "improved_validation_roc_auc": cand_auc > base_auc,
        "validation_precision_delta": round(
            _extract_cls(cand_val, "precision") - _extract_cls(base_val, "precision"),
            4,
        ),
        "validation_recall_delta": round(
            _extract_cls(cand_val, "recall") - _extract_cls(base_val, "recall"),
            4,
        ),
    }


def build_retraining_report(
    *,
    symbol: str,
    timeframe: str,
    seed: int,
    dataset_variant: dict[str, Any],
    features_used: list[str],
    label_config: dict[str, Any],
    candidates: list[ModelCandidate],
    best: ModelCandidate,
    comparison_table: list[dict[str, Any]],
    experimental_dataset_path: str,
    original_fingerprint: str,
    fingerprint_after: str,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    baseline = load_phase92_baseline(base_dir)
    improvement = _improved_over_baseline(best, baseline)

    return {
        "phase": PHASE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "timeframe": timeframe.upper(),
        "seed": seed,
        "status": "PASS" if improvement.get("improved_validation_roc_auc") else "WARN",
        "dataset_variant": dataset_variant,
        "features_used": features_used,
        "feature_count": len(features_used),
        "labels_used": label_config,
        "experimental_dataset_path": experimental_dataset_path,
        "original_dataset_fingerprint": original_fingerprint,
        "fingerprint_unchanged": original_fingerprint == fingerprint_after,
        "best_model": {
            "name": best.model_name,
            "variant_id": best.variant_id,
            "hyperparameters": best.hyperparameters,
            "composite_score": round(best.composite_score, 4),
            "validation_metrics": best.validation.to_dict(),
            "test_metrics": best.test.to_dict(),
        },
        "all_candidates": [c.to_dict() for c in candidates],
        "comparison_table": comparison_table,
        "phase9_2_baseline": baseline,
        "improvement_vs_phase9_2": improvement,
    }


def save_retraining_report(report: dict[str, Any], base_dir: str | Path | None = None) -> Path:
    path = phase9_4_retraining_report_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
