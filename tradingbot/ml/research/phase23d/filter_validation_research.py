"""Phase 23D — read-only RSI/ADX profitability filter scientific evaluation."""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[4]

VERDICT_OPTIONS = (
    "FILTER_CORRECT",
    "FILTER_TOO_STRICT",
    "FILTER_FOR_WRONG_REGIME",
    "FILTER_OUTDATED",
    "MULTIPLE_ROOT_CAUSES",
)


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def _line_of(rel: str, needle: str) -> int | None:
    for index, line in enumerate(_read(rel).splitlines(), 1):
        if needle in line:
            return index
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _report(path: str) -> dict[str, Any]:
    return _load_json(PROJECT_ROOT / path)


def build_filter_history() -> dict[str, Any]:
    phase19b = _report("data/ml/reports/phase19b/phase19b_final_report.json")
    phase19c = _report("data/ml/reports/phase19c/phase19c_final_report.json")
    phase19c_impl = _report("data/ml/reports/phase19c/implementation_report.json")
    phase22c = _report("tradingbot/ml/research/phase22c/phase22c_final_report.json")

    return {
        "phase": "23D",
        "rsi_filter": {
            "introduced_by": "Phase 19C (production integration of Phase 19B research candidate rsi_mid)",
            "research_origin": "Phase 19B discover_filters — candidate rsi_mid (RSI 40–60)",
            "production_file": "tradingbot/ml/phase19c/filters.py",
            "when": "Phase 19C safe profitability upgrade",
            "why": phase19c.get("recommendation", "Improve PF/expectancy vs Phase 19A baseline"),
            "original_design_goal": "Block trades in RSI extreme zones; keep mid-range RSI only",
            "original_model": "Hybrid production stack (phase9_9 RANGE + trend_rf)",
            "original_strategy": "Full ML kernel pipeline (Phase 19A backtest trades)",
            "original_market_regime": "Generic — all regimes in Phase 19B/19C backtest cohort",
            "designed_for": "Hybrid / generic trading (not RANGE-only)",
        },
        "adx_filter": {
            "introduced_by": "Phase 19C (production integration of Phase 19B candidate adx_15_50)",
            "research_origin": "Phase 19B discover_filters — candidate adx_15_50",
            "production_file": "tradingbot/ml/phase19c/filters.py",
            "when": "Phase 19C",
            "why": "Require moderate trend strength band (avoid low/high ADX)",
            "original_design_goal": "ADX band filter on executed pipeline signals",
            "original_model": "Hybrid production stack",
            "original_strategy": "Full ML kernel",
            "original_market_regime": "Generic hybrid cohort",
            "designed_for": "Hybrid / generic trading",
        },
        "profitability_filter_wrapper": {
            "introduced_by": "Phase 19C — apply_profitability_filters",
            "phase22c_override": "Phase 22C widened bands via env (RSI 35–65, ADX 10–55) in KernelAdapter",
            "integration_point": phase19c_impl.get("integration_point", "kernel_adapter.produce_unified_signal"),
            "phase22c_goal": phase22c.get("notes", ["Profitability recovery — lower HOLD rate"])[0]
            if phase22c.get("notes")
            else "Phase 22C profitability recovery",
            "designed_for": "Generic kernel signals post-calibration (all regimes)",
        },
        "timeline": [
            {"phase": "19B", "event": "Research filter discovery on Phase 19A trade records (177 trades, hybrid)"},
            {"phase": "19C", "event": "RSI+ADX filters integrated at KernelAdapter; IMPROVEMENT_ACCEPTED on 3y replay"},
            {"phase": "22C", "event": "Threshold relaxation + hold-chain counters; NEEDS_REVIEW on Jun 2026 audit"},
            {"phase": "23C", "event": "Identified RSI filter as first post-calibration block on RANGE replay"},
        ],
    }


def build_filter_ownership() -> dict[str, Any]:
    from tradingbot.ml.phase19c.config import (
        ENV_ADX_MAX,
        ENV_ADX_MIN,
        ENV_ENABLE_ADX,
        ENV_ENABLE_RSI,
        ENV_RSI_MAX,
        ENV_RSI_MIN,
    )
    from tradingbot.ml.research.phase22c.config import load_phase22c_config

    cfg22 = load_phase22c_config()

    return {
        "phase": "23D",
        "filters": [
            {
                "name": "rsi_filter",
                "file": "tradingbot/ml/phase19c/filters.py",
                "class": "ProfitabilityFilterSettings / apply_profitability_filters",
                "function": "apply_profitability_filters",
                "line": _line_of("tradingbot/ml/phase19c/filters.py", 'blocked.append("rsi_filter")'),
                "caller": "tradingbot/ml/integration/kernel_adapter.py → produce_unified_signal",
                "consumer": "KernelAdapter hold chain (HoldStage.RSI_FILTER)",
                "configuration_source": "load_filter_settings() env vars + Phase22C override in KernelAdapter",
                "defaults_phase19c": {"rsi_min": 40.0, "rsi_max": 60.0},
                "phase22c_runtime_override": {"rsi_min": cfg22.rsi_min, "rsi_max": cfg22.rsi_max},
                "environment_variables": [ENV_ENABLE_RSI, ENV_RSI_MIN, ENV_RSI_MAX],
                "hardcoded_fallback": "40 / 60 in ProfitabilityFilterSettings dataclass",
            },
            {
                "name": "adx_filter",
                "file": "tradingbot/ml/phase19c/filters.py",
                "class": "ProfitabilityFilterSettings / apply_profitability_filters",
                "function": "apply_profitability_filters",
                "line": _line_of("tradingbot/ml/phase19c/filters.py", 'blocked.append("adx_filter")'),
                "caller": "kernel_adapter.produce_unified_signal",
                "consumer": "KernelAdapter hold chain (HoldStage.ADX_FILTER)",
                "configuration_source": "load_filter_settings() + Phase22C KernelAdapter override",
                "defaults_phase19c": {"adx_min": 15.0, "adx_max": 50.0},
                "phase22c_runtime_override": {"adx_min": cfg22.adx_min, "adx_max": cfg22.adx_max},
                "environment_variables": [ENV_ENABLE_ADX, ENV_ADX_MIN, ENV_ADX_MAX],
                "hardcoded_fallback": "15 / 50 in ProfitabilityFilterSettings dataclass",
            },
        ],
        "phase22c_config_file": "tradingbot/ml/research/phase22c/config.py",
        "phase22c_enabled_default": cfg22.enabled,
    }


def load_filter_settings_defaults():
    from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings

    return ProfitabilityFilterSettings()


def build_original_validation() -> dict[str, Any]:
    phase19b = _report("data/ml/reports/phase19b/phase19b_final_report.json")
    phase19c = _report("data/ml/reports/phase19c/phase19c_final_report.json")
    phase19c_filt = _report("data/ml/reports/phase19c/filter_validation.json")
    phase22c = _report("tradingbot/ml/research/phase22c/phase22c_final_report.json")

    return {
        "phase": "23D",
        "phase19b_validation": {
            "validated_against": "Phase 19A production backtest trade records (177 trades)",
            "regime_scope": "Hybrid — includes TREND and RANGE (regime_range_only was a research candidate, not selected alone)",
            "models": "Full kernel path trades from phase19a.backtest",
            "rsi_mid_selected": any(x.get("name") == "rsi_mid" for x in phase19b.get("top_improvements", [])),
            "adx_15_50_selected": any(x.get("name") == "adx_15_50" for x in phase19b.get("top_improvements", [])),
            "verdict": phase19b.get("verdict"),
        },
        "phase19c_validation": {
            "validated_against": "Full production stack replay with filters ON (phase9_9 + trend_rf_v41)",
            "range_engine_named": phase19c_filt.get("filter_settings"),
            "windows_years": list(phase19c.get("windows", {}).keys()),
            "verdict": phase19c.get("verdict"),
            "recommendation": phase19c.get("recommendation"),
            "pf_improvement_vs_19a": phase19c.get("comparison_vs_phase19a", {}).get("delta", {}).get("profit_factor"),
            "validated_phase99_range_only": False,
            "evidence": "phase19c/backtest.py labels range_engine phase9_9 but evaluates all regimes in unified replay",
        },
        "phase22c_revalidation": {
            "validated_against_phase99_range_only": False,
            "threshold_change": "RSI 40–60 → 35–65; ADX 15–50 → 10–55 (config.py defaults)",
            "verdict": phase22c.get("verdict"),
            "m5_rsi_filter_holds": phase22c.get("m5_backtest", {}).get("hold_chain_partial", {}).get("rsi_filter_hold"),
            "note": "Phase 22C changed runtime bands without repository evidence of RANGE-only re-certification",
        },
        "phase99_range_specific_evidence": {
            "found": False,
            "repository_artifacts_searched": [
                "data/ml/reports/phase19c/",
                "data/ml/reports/phase19b/",
                "tradingbot/ml/research/phase22c/",
            ],
            "conclusion": "Filters validated on hybrid ML kernel cohort, not isolated Phase 9.9 RANGE model",
        },
    }


def _phase22c_filter_settings():
    from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings, load_filter_settings
    from tradingbot.ml.research.phase22c.config import load_phase22c_config

    cfg22 = load_phase22c_config()
    base = load_filter_settings()
    if not cfg22.enabled:
        return base
    return ProfitabilityFilterSettings(
        enable_rsi=base.enable_rsi,
        enable_adx=base.enable_adx,
        rsi_min=cfg22.rsi_min,
        rsi_max=cfg22.rsi_max,
        adx_min=cfg22.adx_min,
        adx_max=cfg22.adx_max,
    )


def _filter_off_settings():
    from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings

    return ProfitabilityFilterSettings(enable_rsi=False, enable_adx=False)


def _metrics_from_r(r_values: list[float]) -> dict[str, Any]:
    from tradingbot.ml.phase19a.metrics import (
        compute_performance,
        expectancy_r,
        max_drawdown_r,
        pf_from_r,
        sharpe_r,
    )

    if not r_values:
        return {
            "trades": 0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "win_rate": 0.0,
            "maximum_drawdown_r": 0.0,
            "sharpe_proxy": 0.0,
            "mean_confidence": 0.0,
        }
    perf = compute_performance([{"r_multiple": r} for r in r_values])
    return {
        "trades": len(r_values),
        "profit_factor": pf_from_r(r_values),
        "expectancy_r": expectancy_r(r_values),
        "win_rate": perf.get("win_rate", 0.0),
        "maximum_drawdown_r": max_drawdown_r(r_values),
        "sharpe_proxy": sharpe_r(r_values),
        "mean_confidence": 0.0,
    }


def _collect_range_pipeline_signals(
    *,
    base_dir: str | None = None,
    days: int = 365,
    stride: int = 5,
    tail_only: int | None = None,
    tail_stride: int = 1,
) -> list[dict[str, Any]]:
    """Collect RANGE bars where calibrated pipeline would trade before profitability filter."""
    import os

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.dataset.store import DatasetStore
    from tradingbot.ml.decision_engine.validation import build_market_context
    from tradingbot.ml.integration.factory import build_ml_kernel_stack
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.recovered_calibration import prepare_calibration_candles
    from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
    from tradingbot.ml.phase19c.filters import apply_profitability_filters
    from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame
    from tradingbot.ml.research.phase17b.top5_features import attach_top5_features
    from tradingbot.ml.research.phase14_7.trade_tracker import simulate_outcome
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder

    base_dir = normalize_ml_base_dir(base_dir or load_legacy_config().get("BASE_DIR"))
    candles_raw = CandleStore(base_dir).load("XAUUSD", "M5")
    dataset = DatasetStore(base_dir).load_v2("XAUUSD", "M5")
    if candles_raw is None or candles_raw.empty or dataset is None or dataset.empty:
        return []

    if tail_only:
        norm = normalize_candles_for_builder(candles_raw)
        window = norm.tail(tail_only).copy()
    else:
        window = prepare_calibration_candles(candles_raw, days=days)

    unified = attach_top5_features(build_unified_frame(window, dataset))
    norm_candles = normalize_candles_for_builder(window)

    c = window.copy()
    if not isinstance(c.index, pd.DatetimeIndex):
        if "timestamp" in c.columns:
            c = c.set_index("timestamp")
    c.index = pd.to_datetime(c.index, utc=True)
    c = c.sort_index()
    ts_to_idx = {pd.Timestamp(t): i for i, t in enumerate(c.index)}

    filt_on = _phase22c_filter_settings()
    step = tail_stride if tail_only else stride
    prev = os.environ.get(TREND_VERSION_ENV)
    os.environ[TREND_VERSION_ENV] = "v41"
    PipelineCache.reset()
    records: list[dict[str, Any]] = []

    try:
        stack = build_ml_kernel_stack(base_dir=base_dir, symbol="XAUUSD", use_range_recovery=True)
        adapter = stack  # use stack directly
        from tradingbot.ml.integration.kernel_adapter import KernelAdapter

        ka = KernelAdapter(stack.as_dependencies(base_dir=base_dir, symbol="XAUUSD"))
        range_inner, trend_inner = ka._engine_inners()  # noqa: SLF001

        offset = max(0, len(norm_candles) - len(unified))
        for i in range(0, len(unified), max(1, step)):
            row = unified.iloc[i]
            from tradingbot.ml.research.regime_detector.regime_classifier import rule_classify_row

            regime = rule_classify_row(row)
            if regime != "RANGE":
                continue

            bar_index = offset + i
            if bar_index >= len(norm_candles):
                bar_index = len(norm_candles) - 1

            ctx = build_market_context(
                row,
                symbol="XAUUSD",
                timeframe="M5",
                range_engine=range_inner,
                trend_engine=trend_inner,
                candles=norm_candles,
                bar_index=bar_index,
            )
            cal, risk, quality = stack.quality.evaluate(ctx)
            action = str(cal.final_action)
            if action not in ("BUY", "SELL") or not risk.allowed or not quality.allowed:
                continue

            range_ev = range_inner.evaluate(
                row=row,
                candles=norm_candles,
                bar_index=bar_index,
                timeframe="M5",
            )
            filt = apply_profitability_filters(row.to_dict(), settings=filt_on)
            ts = pd.to_datetime(row.get("timestamp", row.name), utc=True)
            bar_idx = ts_to_idx.get(pd.Timestamp(ts), min(bar_index, len(c) - 1))
            outcome = simulate_outcome(c, bar_idx, action)
            r_mult = float(outcome["r_multiple"])

            records.append(
                {
                    "timestamp": ts.isoformat(),
                    "regime": regime,
                    "raw_probability": float(range_ev.get("probability", 0.5)),
                    "engine_signal": str(range_ev.get("signal", "HOLD")),
                    "calibrated_action": action,
                    "confidence": float(cal.final_confidence),
                    "rsi": filt.rsi,
                    "adx": filt.adx,
                    "filter_passed": filt.passed,
                    "filter_blocked_by": list(filt.blocked_by),
                    "atr_percentile": float(row.get("atr_percentile", row.get("volatility", 0.0))),
                    "spread_pips": float(row.get("spread_pips", 0.0)),
                    "structure_distance": float(row.get("structure_distance", row.get("phase99_structure_distance", 0.0)) or 0.0),
                    "r_multiple": r_mult,
                    "expected_pl_r": r_mult,
                    "outcome_class": "winner" if r_mult > 0 else ("loser" if r_mult < 0 else "breakeven"),
                }
            )
    finally:
        PipelineCache.reset()
        if prev is None:
            os.environ.pop(TREND_VERSION_ENV, None)
        else:
            os.environ[TREND_VERSION_ENV] = prev

    return records


def build_empirical_filter_analysis(*, base_dir: str | None = None) -> dict[str, Any]:
    tail_records = _collect_range_pipeline_signals(base_dir=base_dir, tail_only=300)
    window_records = _collect_range_pipeline_signals(base_dir=base_dir, days=365, stride=5)

    def _summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
        passed = [r for r in records if r["filter_passed"]]
        blocked = [r for r in records if not r["filter_passed"]]
        return {
            "pipeline_actionable_range_signals": len(records),
            "filter_pass": len(passed),
            "filter_blocked": len(blocked),
            "pass_outcomes": {
                "winners": sum(1 for r in passed if r["outcome_class"] == "winner"),
                "losers": sum(1 for r in passed if r["outcome_class"] == "loser"),
                "breakeven": sum(1 for r in passed if r["outcome_class"] == "breakeven"),
                "metrics": _metrics_from_r([r["r_multiple"] for r in passed]),
            },
            "blocked_outcomes": {
                "winners": sum(1 for r in blocked if r["outcome_class"] == "winner"),
                "losers": sum(1 for r in blocked if r["outcome_class"] == "loser"),
                "breakeven": sum(1 for r in blocked if r["outcome_class"] == "breakeven"),
                "metrics": _metrics_from_r([r["r_multiple"] for r in blocked]),
            },
            "records_sample": records[:5],
        }

    return {
        "phase": "23D",
        "filter_settings_phase22c": _phase22c_filter_settings().to_dict(),
        "tail_300_bars": _summarize(tail_records),
        "window_365d_stride5": _summarize(window_records),
        "records_tail": tail_records,
        "records_window": window_records,
    }


def build_counterfactual_analysis(*, empirical: dict[str, Any]) -> dict[str, Any]:
    def _counter(records: list[dict[str, Any]], label: str) -> dict[str, Any]:
        all_r = [r["r_multiple"] for r in records]
        on_r = [r["r_multiple"] for r in records if r["filter_passed"]]
        off_r = all_r
        on_m = _metrics_from_r(on_r)
        off_m = _metrics_from_r(off_r)
        if on_r:
            on_m["mean_confidence"] = round(statistics.mean(r["confidence"] for r in records if r["filter_passed"]), 4)
        if off_r:
            off_m["mean_confidence"] = round(statistics.mean(r["confidence"] for r in records), 4)
        return {
            "label": label,
            "filter_on": on_m,
            "filter_off": off_m,
            "delta_pf": round(on_m["profit_factor"] - off_m["profit_factor"], 4),
            "delta_expectancy": round(on_m["expectancy_r"] - off_m["expectancy_r"], 4),
            "delta_trades": on_m["trades"] - off_m["trades"],
        }

    tail_recs = empirical.get("records_tail", [])
    win_recs = empirical.get("records_window", [])
    return {
        "phase": "23D",
        "method": "Existing simulate_outcome on RANGE pipeline_actionable signals; no production code changes",
        "tail_300_bars": _counter(tail_recs, "tail_300"),
        "window_365d": _counter(win_recs, "365d"),
    }


def build_false_block_analysis(*, empirical: dict[str, Any]) -> dict[str, Any]:
    def _analyze(records: list[dict[str, Any]]) -> dict[str, Any]:
        blocked = [r for r in records if not r["filter_passed"]]
        passed = [r for r in records if r["filter_passed"]]
        true_blocks = sum(1 for r in blocked if r["outcome_class"] == "loser")
        false_blocks = sum(1 for r in blocked if r["outcome_class"] == "winner")
        breakeven_blocks = sum(1 for r in blocked if r["outcome_class"] == "breakeven")
        total_losers = sum(1 for r in records if r["outcome_class"] == "loser")
        precision = round(true_blocks / max(true_blocks + false_blocks, 1), 4)
        recall = round(true_blocks / max(total_losers, 1), 4)
        blocked_by_counts: dict[str, int] = {}
        for r in blocked:
            for key in r.get("filter_blocked_by", []):
                blocked_by_counts[key] = blocked_by_counts.get(key, 0) + 1
        return {
            "blocked_trades": len(blocked),
            "passed_trades": len(passed),
            "true_blocks_loser_would_have_traded": true_blocks,
            "false_blocks_winner_would_have_traded": false_blocks,
            "breakeven_blocks": breakeven_blocks,
            "precision": precision,
            "recall_vs_all_losers": recall,
            "blocked_by_filter": blocked_by_counts,
            "blocked_trade_details": blocked,
        }

    tail = empirical.get("records_tail", [])
    window = empirical.get("records_window", [])
    return {
        "phase": "23D",
        "simulation": "simulate_trade_outcome on blocked direction (counterfactual would-have-traded)",
        "tail_300_bars": _analyze(tail),
        "window_365d": _analyze(window),
    }


def build_regime_analysis(*, empirical: dict[str, Any]) -> dict[str, Any]:
    records = empirical.get("records_window", []) or empirical.get("records_tail", [])

    def _stats(group: list[dict[str, Any]]) -> dict[str, Any]:
        if not group:
            return {"count": 0}
        return {
            "count": len(group),
            "mean_rsi": round(statistics.mean(float(r["rsi"] or 50) for r in group), 2),
            "mean_adx": round(statistics.mean(float(r["adx"] or 0) for r in group), 2),
            "mean_probability": round(statistics.mean(r["raw_probability"] for r in group), 4),
            "mean_confidence": round(statistics.mean(r["confidence"] for r in group), 4),
            "mean_atr_percentile": round(statistics.mean(r["atr_percentile"] for r in group), 2),
            "win_rate": round(sum(1 for r in group if r["outcome_class"] == "winner") / len(group), 4),
        }

    passed = [r for r in records if r["filter_passed"]]
    blocked = [r for r in records if not r["filter_passed"]]
    return {
        "phase": "23D",
        "cohort_regime": "RANGE only (pipeline_actionable after calibration/risk/quality)",
        "passed_trades": _stats(passed),
        "blocked_trades": _stats(blocked),
        "regime_note": (
            "All records are RANGE by construction. Filters were designed on hybrid Phase 19A/19C "
            "cohorts but currently gate RANGE phase9_9 SELL-heavy signals post-Phase23B repair."
        ),
        "transition_or_trend_blocked": 0,
    }


def build_dependency_analysis() -> dict[str, Any]:
    return {
        "phase": "23D",
        "rsi_dependencies": {
            "feature_source": "unified row / dataset_v2 rsi column",
            "read_by": "apply_profitability_filters → _feature_float(features, 'rsi')",
            "default_if_missing": 50.0,
            "affects": ["KernelAdapter.produce_unified_signal direction", "HoldStage.RSI_FILTER counter"],
            "does_not_affect": [
                "RiskGate core",
                "Mt5ExecutionAdapter order_send",
                "FeatureBuilder / predict_proba",
                "HealthGate phase9 artifact checks",
                "Frozen model artifacts",
            ],
        },
        "adx_dependencies": {
            "feature_source": "unified row adx column",
            "read_by": "apply_profitability_filters",
            "default_if_missing": 0.0,
            "affects": ["KernelAdapter direction", "HoldStage.ADX_FILTER counter"],
            "does_not_affect": ["RiskGate SL/TP", "Training pipeline", "Regime detector core"],
        },
        "profitability_filter_dependencies": {
            "module": "tradingbot/ml/phase19c/filters.py",
            "called_from": [
                "tradingbot/ml/integration/kernel_adapter.py",
                "tradingbot/ml/phase19c/backtest.py",
                "tradingbot/ml/research/phase23c/decision_gate_investigation.py",
            ],
            "changing_thresholds_would_affect": [
                "UnifiedSignal.direction (HOLD vs BUY/SELL)",
                "TradingSignal emission (None when HOLD)",
                "Hold chain rsi_filter_hold / adx_filter_hold counters",
                "Phase 19C/22C backtest replay statistics",
            ],
            "changing_would_not_affect": [
                "RangeEngineAdapter predict_proba",
                "DecisionOrchestrator policy thresholds",
                "Platt calibration fit",
                "RiskGate max positions / daily loss (downstream of signal)",
            ],
        },
        "research_replay_isolation": "phase19c/backtest and phase23d use same apply_profitability_filters — read-only simulation safe",
    }


def _classify_verdict(
    *,
    counterfactual: dict[str, Any],
    false_blocks: dict[str, Any],
    original_validation: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    tail_cf = counterfactual.get("tail_300_bars", {})
    win_cf = counterfactual.get("window_365d", {})
    tail_fb = false_blocks.get("tail_300_bars", {})
    win_fb = false_blocks.get("window_365d", {})

    on_pf = tail_cf.get("filter_on", {}).get("profit_factor", 0)
    off_pf = tail_cf.get("filter_off", {}).get("profit_factor", 0)
    on_exp = tail_cf.get("filter_on", {}).get("expectancy_r", 0)
    off_exp = tail_cf.get("filter_off", {}).get("expectancy_r", 0)
    false_block_winners = tail_fb.get("false_blocks_winner_would_have_traded", 0)
    true_block_losers = tail_fb.get("true_blocks_loser_would_have_traded", 0)
    precision = tail_fb.get("precision", 0)

    reasons: list[str] = []
    scores = {
        "FILTER_CORRECT": 0,
        "FILTER_TOO_STRICT": 0,
        "FILTER_FOR_WRONG_REGIME": 0,
        "FILTER_OUTDATED": 0,
    }

    if not original_validation.get("phase99_range_specific_evidence", {}).get("found"):
        scores["FILTER_FOR_WRONG_REGIME"] += 2
        reasons.append("No repository evidence of Phase9.9 RANGE-only filter validation")

    if original_validation.get("phase22c_revalidation", {}).get("validated_against_phase99_range_only") is False:
        scores["FILTER_OUTDATED"] += 1
        reasons.append("Phase22C widened RSI/ADX bands without RANGE re-certification artifact")

    if on_pf > off_pf and on_exp >= off_exp:
        scores["FILTER_CORRECT"] += 3
        reasons.append(f"Tail counterfactual: filter ON PF {on_pf} > OFF PF {off_pf}")
    elif off_pf > on_pf or off_exp > on_exp:
        scores["FILTER_TOO_STRICT"] += 3
        reasons.append(f"Tail counterfactual: filter OFF metrics beat ON (PF {off_pf} vs {on_pf})")

    if false_block_winners > true_block_losers:
        scores["FILTER_TOO_STRICT"] += 2
        reasons.append(f"False blocks ({false_block_winners}) exceed true blocks ({true_block_losers}) on tail")
    elif true_block_losers >= false_block_winners and precision >= 0.5:
        scores["FILTER_CORRECT"] += 2
        reasons.append(f"Blocked trades precision {precision} favors filter")

    win_on = win_cf.get("filter_on", {}).get("profit_factor", 0)
    win_off = win_cf.get("filter_off", {}).get("profit_factor", 0)
    if win_on >= win_off:
        scores["FILTER_CORRECT"] += 1
    else:
        scores["FILTER_TOO_STRICT"] += 1

    top_score = max(scores.values())
    leaders = [k for k, v in scores.items() if v == top_score]
    if len(leaders) > 1 and top_score > 0:
        verdict = "MULTIPLE_ROOT_CAUSES"
    elif leaders:
        verdict = leaders[0]
    else:
        verdict = "FILTER_FOR_WRONG_REGIME"

    return verdict, {"scores": scores, "reasons": reasons, "precision_tail": precision}


def build_root_cause_report(
    *,
    counterfactual: dict[str, Any],
    false_blocks: dict[str, Any],
    original_validation: dict[str, Any],
    empirical: dict[str, Any],
) -> dict[str, Any]:
    verdict, detail = _classify_verdict(
        counterfactual=counterfactual,
        false_blocks=false_blocks,
        original_validation=original_validation,
    )
    tail = empirical.get("tail_300_bars", {})
    return {
        "phase": "23D",
        "classification": verdict,
        "scoring_detail": detail,
        "empirical_headline": {
            "range_pipeline_actionable_tail": tail.get("pipeline_actionable_range_signals"),
            "filter_pass_tail": tail.get("filter_pass"),
            "filter_blocked_tail": tail.get("filter_blocked"),
        },
        "design_assessment": {
            "correctly_designed_mechanism": "RSI mid-band + ADX band gating is coherent for noise reduction",
            "calibration_question": "Phase22C bands differ from Phase19C validated defaults without RANGE replay certificate",
            "regime_fit_question": "Discovery/validation used hybrid kernel trades, not isolated Phase9.9 RANGE model",
        },
        "summary": (
            "Profitability filters originate from Phase 19B hybrid trade analysis and Phase 19C kernel integration. "
            "Empirical RANGE-only counterfactual on latest windows determines whether current Phase22C bands "
            "correctly block losers or incorrectly block winners."
        ),
    }


def build_repair_design(*, root_cause: dict[str, Any]) -> dict[str, Any]:
    classification = root_cause.get("classification", "FILTER_FOR_WRONG_REGIME")
    designs = {
        "FILTER_CORRECT": {
            "minimal_repair": "No threshold change; document RANGE filter pass rate; monitor false block rate in live hold chain",
            "safe_repair": "Optional regime-specific filter profile via approved research phase — do not relax without evidence",
            "rollback": "N/A — keep filters enabled",
            "tests": ["test_phase23d false_block precision stable", "hold_chain kernel_actionable > 0"],
            "risk": "Low — preserve validated hybrid improvement",
        },
        "FILTER_TOO_STRICT": {
            "minimal_repair": "RANGE-only re-calibration study in research/ — tune bands on chronological RANGE cohort only",
            "safe_repair": "Regime-conditional filter bypass for RANGE when empirical PF improves with OFF on RANGE-only replay",
            "rollback": "Restore Phase19C defaults (RSI 40–60, ADX 15–50) via env",
            "tests": ["RANGE counterfactual PF ON >= OFF", "false blocks < true blocks"],
            "risk": "Medium — increased trade count may raise drawdown",
        },
        "FILTER_FOR_WRONG_REGIME": {
            "minimal_repair": "Apply profitability filters only to TREND engine path; skip for phase9_9 RANGE in KernelAdapter (requires approved integration phase)",
            "safe_repair": "Separate filter profiles: hybrid validation does not transfer to RANGE mean-reversion model",
            "rollback": "Disable filters via ENABLE_RSI_FILTER=false ENABLE_ADX_FILTER=false",
            "tests": ["RANGE signals unaffected by RSI mid-band", "TREND still filtered"],
            "risk": "Medium — decouples regimes; needs RiskGate regression",
        },
        "FILTER_OUTDATED": {
            "minimal_repair": "Re-run Phase19C-style validation with Phase22C bands on post-23B feature pipeline; compare to 19C certificate",
            "safe_repair": "Revert Phase22C RSI/ADX overrides to Phase19C validated defaults until re-certified",
            "rollback": "PHASE22C_ENABLED=false or env restore 40/60 and 15/50",
            "tests": ["phase19c filter_validation metrics reproduced on current stack"],
            "risk": "Low for rollback; re-certification required before further relaxation",
        },
        "MULTIPLE_ROOT_CAUSES": {
            "minimal_repair": "Sequential fixes: (1) confirm RANGE validation gap, (2) re-certify bands, (3) measure false blocks",
            "safe_repair": "Do not relax and regime-split in one change",
            "rollback": "Phase19C env disable flags",
            "tests": ["test each hypothesis independently"],
            "risk": "High if multiple knobs changed simultaneously",
        },
    }
    return {
        "phase": "23D",
        "classification": classification,
        "design": designs.get(classification, designs["FILTER_FOR_WRONG_REGIME"]),
        "implementation_status": "NOT IMPLEMENTED — design only per Phase 23D scope",
    }


def run_investigation(*, base_dir: str | None = None) -> dict[str, Any]:
    filter_history = build_filter_history()
    filter_ownership = build_filter_ownership()
    original_validation = build_original_validation()
    empirical = build_empirical_filter_analysis(base_dir=base_dir)
    counterfactual = build_counterfactual_analysis(empirical=empirical)
    false_blocks = build_false_block_analysis(empirical=empirical)
    regime = build_regime_analysis(empirical=empirical)
    dependency = build_dependency_analysis()
    root_cause = build_root_cause_report(
        counterfactual=counterfactual,
        false_blocks=false_blocks,
        original_validation=original_validation,
        empirical=empirical,
    )
    repair_design = build_repair_design(root_cause=root_cause)

    # Strip large record arrays from top-level payloads written to separate fields
    empirical_public = {k: v for k, v in empirical.items() if k not in ("records_tail", "records_window")}
    false_public = {
        "phase": false_blocks["phase"],
        "simulation": false_blocks["simulation"],
        "tail_300_bars": {
            k: v
            for k, v in false_blocks["tail_300_bars"].items()
            if k != "blocked_trade_details"
        },
        "window_365d": {
            k: v
            for k, v in false_blocks["window_365d"].items()
            if k != "blocked_trade_details"
        },
    }

    verdict = root_cause["classification"]
    return {
        "filter_history": filter_history,
        "filter_ownership": filter_ownership,
        "original_validation": original_validation,
        "empirical_filter_analysis": empirical_public,
        "counterfactual_analysis": counterfactual,
        "false_block_analysis": false_public,
        "regime_analysis": regime,
        "dependency_analysis": dependency,
        "root_cause_report": root_cause,
        "repair_design": repair_design,
        "verdict": verdict,
        "_records_tail": empirical.get("records_tail", []),
        "_records_window": empirical.get("records_window", []),
    }
