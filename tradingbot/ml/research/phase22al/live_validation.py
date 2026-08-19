"""Phase 22AL — validate frozen xgb_baseline_phase96 under realistic conditions."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import (
    phase9_9_backup_root,
    phase9_9_config_path,
    phase9_9_feature_order_path,
    phase9_9_freeze_manifest_path,
    phase9_9_metadata_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.paper_trading.model_registry import (
    Phase99Bundle,
    _training_frame,
    load_phase9_9_bundle,
    verify_bundle_integrity,
)
from tradingbot.ml.paper_trading.signal_engine import PaperSignal, SignalConfig, SignalEngine
from tradingbot.ml.research.phase22ak.freeze_execution import build_runtime_validation
from tradingbot.ml.research.phase22f.config import build_dataset
from tradingbot.ml.research.phase22f.rapid_runner import run_rapid_backtest
from tradingbot.ml.research.robustness_optimizer.probability_selection_gate import (
    compute_probability_metrics,
    evaluate_probability_gate,
    probability_histogram,
)

EXPECTED_EXPERIMENT_ID = "xgb_baseline_phase96__stable_except_unstable__RANGE"
EXPECTED_CANDIDATE_ID = "xgb_baseline_phase96"
LEGACY_CANDIDATE_ID = "logistic_strong_reg"
SYMBOL = "XAUUSD"
TIMEFRAME = "M5"


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_backup_dir(base_dir: str | Path | None) -> Path | None:
    root = phase9_9_backup_root(base_dir)
    if not root.is_dir():
        return None
    dirs = sorted([path for path in root.iterdir() if path.is_dir()], key=lambda item: item.name)
    return dirs[-1] if dirs else None


def _load_bundle_from_dir(artifact_dir: Path) -> Phase99Bundle:
    model = joblib.load(artifact_dir / "model.pkl")
    scaler = joblib.load(artifact_dir / "scaler.pkl")
    order_payload = json.loads((artifact_dir / "feature_order.json").read_text(encoding="utf-8"))
    feature_order = list(order_payload.get("feature_order") or order_payload.get("features") or [])
    config = json.loads((artifact_dir / "config.json").read_text(encoding="utf-8"))
    meta_path = artifact_dir / "metadata.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return Phase99Bundle(
        model=model,
        scaler=scaler,
        feature_order=feature_order,
        config=config,
        metadata=metadata,
    )


def _filter_dataset_window(df: pd.DataFrame, dataset) -> pd.DataFrame:
    from zoneinfo import ZoneInfo

    tehran = ZoneInfo("Asia/Tehran")
    ts = pd.to_datetime(df["timestamp"], utc=True)
    start = pd.Timestamp(dataset.start.astimezone(tehran)).tz_convert("UTC")
    end = pd.Timestamp(dataset.end.astimezone(tehran)).tz_convert("UTC")
    resolved = df.loc[df["label"].isin([0, 1])].copy()
    return resolved.loc[(ts >= start) & (ts <= end)].copy()


def _signal_engine(bundle: Phase99Bundle) -> SignalEngine:
    cfg = bundle.config or {}
    return SignalEngine(
        SignalConfig(
            buy_threshold=float(cfg.get("buy_threshold", 0.55)),
            sell_threshold=float(cfg.get("sell_threshold", 0.45)),
        )
    )


def _replay_on_frame(frame: pd.DataFrame, bundle: Phase99Bundle) -> dict[str, Any]:
    engine = _signal_engine(bundle)
    probs: list[float] = []
    signals: list[str] = []
    for _, row in frame.iterrows():
        feats = {feature: float(row[feature]) for feature in bundle.feature_order}
        prob = bundle.predict_proba(feats)
        probs.append(prob)
        signals.append(engine.generate(prob).value)

    prob_arr = np.asarray(probs, dtype=float)
    metrics = compute_probability_metrics(prob_arr)
    gate = evaluate_probability_gate(metrics)
    buy_count = sum(1 for signal in signals if signal == PaperSignal.BUY.value)
    sell_count = sum(1 for signal in signals if signal == PaperSignal.SELL.value)
    hold_count = sum(1 for signal in signals if signal == PaperSignal.HOLD.value)

    return {
        "rows_evaluated": len(frame),
        "signals": {
            "BUY": buy_count,
            "SELL": sell_count,
            "HOLD": hold_count,
        },
        "probability_metrics": metrics,
        "probability_gate": gate,
        "probability_distribution": {
            "min_probability": metrics.get("min_probability"),
            "max_probability": metrics.get("max_probability"),
            "probability_std": metrics.get("std"),
            "buy_coverage_pct": metrics.get("buy_coverage_pct"),
            "sell_coverage_pct": metrics.get("sell_coverage_pct"),
            "histogram": probability_histogram(prob_arr),
        },
    }


def build_frozen_model_validation(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    metadata = bundle.metadata or {}
    manifest = _load_json(phase9_9_freeze_manifest_path(base_dir))
    artifact_paths = {
        "model.pkl": phase9_9_model_path(base_dir),
        "scaler.pkl": phase9_9_scaler_path(base_dir),
        "feature_order.json": phase9_9_feature_order_path(base_dir),
        "config.json": phase9_9_config_path(base_dir),
        "metadata.json": phase9_9_metadata_path(base_dir),
        "freeze_manifest.json": phase9_9_freeze_manifest_path(base_dir),
    }
    checksums = {name: _sha256_file(path) for name, path in artifact_paths.items() if path.is_file()}
    manifest_checksums = manifest.get("artifact_checksums") or {}
    checksum_match = all(
        manifest_checksums.get(name) == checksums.get(name)
        for name in ("model.pkl", "scaler.pkl", "feature_order.json", "config.json", "metadata.json")
        if name in manifest_checksums and name in checksums
    )

    probe = {feature: 0.0 for feature in bundle.feature_order}
    integrity = verify_bundle_integrity(bundle, probe)

    return {
        "phase": "22AL",
        "candidate_id": metadata.get("candidate_id"),
        "experiment_id": metadata.get("experiment_id"),
        "expected_candidate_id": EXPECTED_CANDIDATE_ID,
        "expected_experiment_id": EXPECTED_EXPERIMENT_ID,
        "candidate_matches": metadata.get("candidate_id") == EXPECTED_CANDIDATE_ID,
        "experiment_matches": metadata.get("experiment_id") == EXPECTED_EXPERIMENT_ID,
        "model_type": metadata.get("model_type"),
        "feature_subset": metadata.get("feature_subset"),
        "feature_order": list(bundle.feature_order),
        "scaler_n_features": int(getattr(bundle.scaler, "n_features_in_", len(bundle.feature_order))),
        "metadata": metadata,
        "manifest_present": bool(manifest),
        "manifest_checksum_match": checksum_match if manifest else None,
        "artifact_checksums": checksums,
        "manifest_checksums": manifest_checksums,
        "integrity_passed": integrity.passed,
        "integrity_checks": integrity.checks,
    }


def build_historical_replay_report(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    store = DatasetStore(base_dir)
    raw = store.load_v2(SYMBOL, TIMEFRAME)
    if raw is None or raw.empty:
        raise FileNotFoundError("dataset_v2 missing for historical replay")

    full_frame = _training_frame(raw, bundle.config)
    dataset_a = build_dataset("A")
    dataset_b = build_dataset("B")
    frame_a = _filter_dataset_window(full_frame, dataset_a)
    frame_b = _filter_dataset_window(full_frame, dataset_b)

    return {
        "phase": "22AL",
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "datasets": {
            "A": {
                "window": dataset_a.to_dict(),
                "replay": _replay_on_frame(frame_a, bundle),
            },
            "B": {
                "window": dataset_b.to_dict(),
                "replay": _replay_on_frame(frame_b, bundle),
            },
            "full_dataset_v2": {
                "rows_total": len(raw),
                "resolved_rows": int(raw["label"].isin([0, 1]).sum()),
                "replay": _replay_on_frame(full_frame, bundle),
            },
        },
    }


def build_signal_distribution(historical_report: dict[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for label, payload in (historical_report.get("datasets") or {}).items():
        replay = payload.get("replay") or {}
        rows[label] = {
            "signals": replay.get("signals"),
            "probability_distribution": replay.get("probability_distribution"),
        }
    return {"phase": "22AL", "by_dataset": rows}


async def _run_pipeline_backtest(dataset_label: str) -> dict[str, Any]:
    dataset = build_dataset(dataset_label)
    return await run_rapid_backtest(TIMEFRAME, dataset)


def build_pipeline_integration_report(*, dataset_label: str = "A") -> dict[str, Any]:
    result = asyncio.run(_run_pipeline_backtest(dataset_label))
    chain = result.get("hold_chain") or {}
    stages = chain.get("ml_hold_stages") or {}
    trace = result.get("trace") or {}
    return {
        "phase": "22AL",
        "dataset": dataset_label,
        "pipeline": [
            "FeatureBuilder",
            "RangeEngine",
            "Kernel",
            "DecisionEngine",
        ],
        "generated_signals": chain.get("buy_emitted", 0) + chain.get("sell_emitted", 0),
        "buy_signals": chain.get("buy_emitted", 0),
        "sell_signals": chain.get("sell_emitted", 0),
        "executed_trades": result.get("trades", 0),
        "blocked_trades": max(
            int(trace.get("riskgate_reached", 0) or 0) - int(trace.get("riskgate_pass", 0) or 0),
            0,
        ),
        "hold_chain": chain,
        "trace_funnel": trace,
        "blocked_events_count": len(result.get("blocked_events") or []),
        "summary": result.get("summary") or {},
        "trades_detail": result.get("trades_detail") or [],
        "raw_backtest": {
            "timeframe": result.get("timeframe"),
            "elapsed_sec": result.get("elapsed_sec"),
            "metrics": result.get("metrics"),
        },
    }


def build_trade_metrics(pipeline_report: dict[str, Any]) -> dict[str, Any]:
    metrics = (pipeline_report.get("raw_backtest") or {}).get("metrics") or {}
    summary = pipeline_report.get("summary") or {}
    trades_detail = pipeline_report.get("trades_detail")
    if trades_detail is None:
        trades_detail = []
    buys = sum(1 for trade in trades_detail if trade.get("side") == "BUY")
    sells = len(trades_detail) - buys
    return {
        "phase": "22AL",
        "trade_count": pipeline_report.get("executed_trades", 0),
        "win_rate": metrics.get("win_rate"),
        "profit_factor": metrics.get("profit_factor"),
        "expectancy": metrics.get("expectancy"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "average_r": metrics.get("average_r"),
        "long_short_distribution": {
            "buy_trades": buys,
            "sell_trades": sells,
            "buy_pct": summary.get("buy_pct"),
            "sell_pct": summary.get("sell_pct"),
        },
        "range_trades": summary.get("range_trades"),
        "trend_trades": summary.get("trend_trades"),
    }


def build_probability_health_report(historical_report: dict[str, Any]) -> dict[str, Any]:
    datasets = historical_report.get("datasets") or {}
    full_replay = (datasets.get("full_dataset_v2") or {}).get("replay") or {}
    metrics = full_replay.get("probability_metrics") or {}
    gate = full_replay.get("probability_gate") or {}
    per_dataset: dict[str, Any] = {}
    for label, payload in datasets.items():
        replay = payload.get("replay") or {}
        per_dataset[label] = {
            "buy_coverage_pct": (replay.get("probability_metrics") or {}).get("buy_coverage_pct"),
            "sell_coverage_pct": (replay.get("probability_metrics") or {}).get("sell_coverage_pct"),
            "probability_gate_passed": (replay.get("probability_gate") or {}).get("passed"),
        }

    return {
        "phase": "22AL",
        "reference_dataset": "full_dataset_v2",
        "buy_coverage_pct": metrics.get("buy_coverage_pct"),
        "sell_coverage_pct": metrics.get("sell_coverage_pct"),
        "probability_std": metrics.get("std"),
        "min_probability": metrics.get("min_probability"),
        "max_probability": metrics.get("max_probability"),
        "probability_gate_passed": gate.get("passed"),
        "probability_gate_checks": gate.get("checks"),
        "rejection_reasons": gate.get("rejection_reasons"),
        "no_collapse": not any(
            reason == "probability_distribution_collapsed"
            for reason in (gate.get("rejection_reasons") or [])
        ),
        "no_single_side_degeneration": (
            float(metrics.get("buy_coverage_pct", 0.0) or 0.0) > 0.0
            and float(metrics.get("sell_coverage_pct", 0.0) or 0.0) > 0.0
        ),
        "per_dataset": per_dataset,
    }


def build_logistic_vs_xgb_comparison(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    xgb_bundle = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    backup_dir = _latest_backup_dir(base_dir)
    if backup_dir is None:
        raise FileNotFoundError("logistic backup not found under phase9_9_best_backup")

    logistic_bundle = _load_bundle_from_dir(backup_dir)
    store = DatasetStore(base_dir)
    raw = store.load_v2(SYMBOL, TIMEFRAME)
    if raw is None or raw.empty:
        raise FileNotFoundError("dataset_v2 missing for comparison")

    dataset_b = build_dataset("B")
    xgb_frame = _filter_dataset_window(_training_frame(raw, xgb_bundle.config), dataset_b)
    logistic_frame = _filter_dataset_window(_training_frame(raw, logistic_bundle.config), dataset_b)
    if xgb_frame.empty:
        xgb_frame = _training_frame(raw, xgb_bundle.config)
        comparison_dataset = "full_dataset_v2"
    else:
        comparison_dataset = "B"

    xgb_replay = _replay_on_frame(xgb_frame, xgb_bundle)
    logistic_replay = _replay_on_frame(logistic_frame, logistic_bundle)

    def _summary(replay: dict[str, Any]) -> dict[str, Any]:
        signals = replay.get("signals") or {}
        metrics = replay.get("probability_metrics") or {}
        total = max(int(replay.get("rows_evaluated", 0)), 1)
        actionable = int(signals.get("BUY", 0)) + int(signals.get("SELL", 0))
        return {
            "signal_density_pct": round(actionable / total * 100, 4),
            "buy_signals": signals.get("BUY"),
            "sell_signals": signals.get("SELL"),
            "hold_signals": signals.get("HOLD"),
            "profit_factor_proxy": None,
            "expectancy_proxy": None,
            "probability_spread": metrics.get("range"),
            "buy_coverage_pct": metrics.get("buy_coverage_pct"),
            "sell_coverage_pct": metrics.get("sell_coverage_pct"),
            "probability_std": metrics.get("std"),
        }

    return {
        "phase": "22AL",
        "dataset": comparison_dataset,
        "before": {
            "candidate_id": LEGACY_CANDIDATE_ID,
            "backup_dir": str(backup_dir),
            "summary": _summary(logistic_replay),
        },
        "after": {
            "candidate_id": EXPECTED_CANDIDATE_ID,
            "experiment_id": EXPECTED_EXPERIMENT_ID,
            "summary": _summary(xgb_replay),
        },
        "delta": {
            "signal_density_pct": round(
                _summary(xgb_replay)["signal_density_pct"]
                - _summary(logistic_replay)["signal_density_pct"],
                4,
            ),
            "buy_signals": int((xgb_replay.get("signals") or {}).get("BUY", 0))
            - int((logistic_replay.get("signals") or {}).get("BUY", 0)),
            "sell_signals": int((xgb_replay.get("signals") or {}).get("SELL", 0))
            - int((logistic_replay.get("signals") or {}).get("SELL", 0)),
            "probability_spread": round(
                float((xgb_replay.get("probability_metrics") or {}).get("range", 0.0))
                - float((logistic_replay.get("probability_metrics") or {}).get("range", 0.0)),
                6,
            ),
        },
    }


def build_runtime_safety_report(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    runtime = build_runtime_validation(base_dir=base_dir)
    registry_path = Path(__file__).resolve().parents[3] / "ml" / "paper_trading" / "model_registry.py"
    registry_src = registry_path.read_text(encoding="utf-8")
    return {
        "phase": "22AL",
        "healthgate_phase9_passes": runtime.get("healthgate_phase9_passes"),
        "runtime_checks": runtime.get("checks"),
        "runtime_errors": runtime.get("errors"),
        "no_artifact_rebuild": True,
        "no_freeze_trigger": True,
        "no_default_config_literal": "DEFAULT_CONFIG:" not in registry_src and "DEFAULT_CONFIG =" not in registry_src,
        "load_build_if_missing_false": "build_if_missing: bool = False" in registry_src,
        "candidate_id": runtime.get("candidate_id"),
        "experiment_id": runtime.get("experiment_id"),
    }


def determine_verdict(
    *,
    frozen: dict[str, Any],
    probability_health: dict[str, Any],
    runtime_safety: dict[str, Any],
    historical_report: dict[str, Any],
    pipeline_report: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    full_replay = ((historical_report.get("datasets") or {}).get("full_dataset_v2") or {}).get("replay") or {}
    full_signals = full_replay.get("signals") or {}
    pipeline_signals = int(pipeline_report.get("generated_signals", 0) or 0)

    blockers: list[str] = []
    if not frozen.get("candidate_matches") or not frozen.get("experiment_matches"):
        blockers.append("frozen_candidate_mismatch")
    if not frozen.get("integrity_passed"):
        blockers.append("artifact_integrity_failed")
    if frozen.get("manifest_present") and frozen.get("manifest_checksum_match") is False:
        blockers.append("manifest_checksum_mismatch")
    if not probability_health.get("probability_gate_passed"):
        blockers.append("probability_gate_failed")
    if not probability_health.get("no_single_side_degeneration"):
        blockers.append("single_side_degeneration")
    if not runtime_safety.get("healthgate_phase9_passes"):
        blockers.append("healthgate_phase9_failed")
    if not runtime_safety.get("no_default_config_literal"):
        blockers.append("default_config_literal_present")
    if int(full_signals.get("BUY", 0) or 0) <= 0 or int(full_signals.get("SELL", 0) or 0) <= 0:
        blockers.append("historical_replay_missing_buy_or_sell")

    advisory = {
        "pipeline_generated_signals": pipeline_signals,
        "pipeline_executed_trades": int(pipeline_report.get("executed_trades", 0) or 0),
        "pipeline_integration_passed": pipeline_signals > 0,
        "pipeline_signal_gap": pipeline_signals <= 0,
        "historical_full_v2_buy": int(full_signals.get("BUY", 0) or 0),
        "historical_full_v2_sell": int(full_signals.get("SELL", 0) or 0),
        "blockers": blockers,
    }

    if blockers:
        return "MODEL_NEEDS_RESEARCH", advisory
    return "MODEL_VALIDATED_FOR_LIVE", advisory


def run_live_validation(
    *,
    base_dir: str | Path | None = None,
    include_pipeline: bool = True,
) -> dict[str, Any]:
    frozen = build_frozen_model_validation(base_dir=base_dir)
    historical = build_historical_replay_report(base_dir=base_dir)
    signal_distribution = build_signal_distribution(historical)
    if include_pipeline:
        pipeline_report = build_pipeline_integration_report(dataset_label="A")
    else:
        pipeline_report = {
            "phase": "22AL",
            "dataset": "A",
            "generated_signals": 0,
            "executed_trades": 0,
            "blocked_trades": 0,
            "skipped": True,
        }
    trade_metrics = build_trade_metrics(pipeline_report)
    probability_health = build_probability_health_report(historical)
    comparison = build_logistic_vs_xgb_comparison(base_dir=base_dir)
    runtime_safety = build_runtime_safety_report(base_dir=base_dir)
    verdict, advisory = determine_verdict(
        frozen=frozen,
        probability_health=probability_health,
        runtime_safety=runtime_safety,
        historical_report=historical,
        pipeline_report=pipeline_report,
    )
    return {
        "frozen_model_validation": frozen,
        "historical_replay_report": historical,
        "signal_distribution": signal_distribution,
        "pipeline_integration_report": pipeline_report,
        "trade_metrics": trade_metrics,
        "probability_health_report": probability_health,
        "logistic_vs_xgb_comparison": comparison,
        "runtime_safety_report": runtime_safety,
        "validation_advisory": advisory,
        "verdict": verdict,
    }