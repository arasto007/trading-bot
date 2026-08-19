"""Unified validation report — aggregates all Phase 4.1 analyses."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.artifacts import feature_importance_report_path
from tradingbot.ml.validation.calibration import run_calibration
from tradingbot.ml.validation.cross_validation import run_cross_validation
from tradingbot.ml.validation.feature_ablation import run_feature_ablation
from tradingbot.ml.validation.regime_test import run_regime_analysis
from tradingbot.ml.validation.robustness import run_robustness_tests
from tradingbot.ml.validation.threshold_optimizer import optimize_threshold
from tradingbot.ml.validation.trading_simulator import run_trading_simulation
from tradingbot.ml.validation.walk_forward import run_walk_forward
from tradingbot.ml.validation._utils import write_json_report


@dataclass
class ValidationSummary:
    model: str
    symbol: str
    timeframe: str
    walk_forward: dict[str, Any] = field(default_factory=dict)
    cross_validation: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    optimal_threshold: dict[str, Any] = field(default_factory=dict)
    robustness: dict[str, Any] = field(default_factory=dict)
    regime_performance: dict[str, Any] = field(default_factory=dict)
    feature_ablation: dict[str, Any] = field(default_factory=dict)
    feature_importance: list[dict[str, float]] = field(default_factory=list)
    trading_simulation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_feature_importance(model_name: str, base_dir: str | Path | None) -> list[dict[str, float]]:
    path = feature_importance_report_path(model_name, base_dir)
    if not path.is_file():
        return []
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def run_full_validation(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    model_params: dict[str, Any] | None = None,
    skip_ablation: bool = False,
    save: bool = True,
) -> ValidationSummary:
    """Run complete offline validation pipeline and write unified summary."""
    wf = run_walk_forward(
        symbol, timeframe, model_name,
        base_dir=base_dir, model_params=model_params, save=save,
    )
    cv_expanding = run_cross_validation(
        symbol, timeframe, model_name,
        mode="expanding", base_dir=base_dir, model_params=model_params, save=False,
    )
    cv_blocked = run_cross_validation(
        symbol, timeframe, model_name,
        mode="blocked", base_dir=base_dir, model_params=model_params, save=save,
    )
    cal = run_calibration(symbol, timeframe, model_name, base_dir=base_dir, save=save)
    threshold = optimize_threshold(symbol, timeframe, model_name, base_dir=base_dir, save=save)
    best_thr = threshold.best_threshold

    robust = run_robustness_tests(
        symbol, timeframe, model_name, base_dir=base_dir, threshold=best_thr, save=save,
    )
    regime = run_regime_analysis(
        symbol, timeframe, model_name, base_dir=base_dir, threshold=best_thr, save=save,
    )
    ablation = None
    if not skip_ablation:
        ablation = run_feature_ablation(
            symbol, timeframe, model_name,
            base_dir=base_dir, model_params=model_params, save=save,
        )
    sim = run_trading_simulation(
        symbol, timeframe, model_name,
        base_dir=base_dir, split="test", threshold=best_thr, save=False,
    )
    importance = _load_feature_importance(model_name, base_dir)

    summary = ValidationSummary(
        model=model_name.lower(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        walk_forward=wf.to_dict(),
        cross_validation={
            "expanding": cv_expanding.to_dict(),
            "blocked": cv_blocked.to_dict(),
        },
        calibration=cal.to_dict(),
        optimal_threshold=threshold.to_dict(),
        robustness=robust.to_dict(),
        regime_performance=regime.to_dict(),
        feature_ablation=ablation.to_dict() if ablation else {},
        feature_importance=importance,
        trading_simulation=sim.to_dict(),
    )

    if save:
        write_json_report(
            reports_dir(base_dir) / "model_validation_summary.json",
            summary.to_dict(),
        )

    return summary
