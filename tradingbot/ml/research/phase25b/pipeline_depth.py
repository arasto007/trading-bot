"""Stage-by-stage pipeline depth comparison: legacy research vs production paper."""

from __future__ import annotations

from typing import Any


def build_pipeline_depth_comparison() -> dict[str, Any]:
    stages = [
        {
            "stage": "Data",
            "research_legacy": "CandleStore slice norm_candles[bar-W:bar+1] direct",
            "production_paper": "DataStage → ReplayMarketDataAdapter.get_ohlcv(300)",
            "status": "different",
            "module": "phase24a/live_shadow_validator.py:218 vs pipeline/data_stage.py:20",
        },
        {
            "stage": "Indicator",
            "research_legacy": "skipped",
            "production_paper": "IndicatorStage.enrich_for_market",
            "status": "skipped_in_research",
            "module": "pipeline/indicator_stage.py:20",
        },
        {
            "stage": "Unified Frame",
            "research_legacy": "Pre-built attach_top5(build_unified_frame(window))",
            "production_paper": "PipelineCache.get_unified_frame(closed_candles) per tick",
            "status": "different",
            "module": "phase24a:172 vs ml/integration/pipeline_cache.py:92",
        },
        {
            "stage": "Regime Detection",
            "research_legacy": "build_market_context inside produce_unified_signal",
            "production_paper": "same via KernelAdapter.produce_unified_signal",
            "status": "identical_when_same_input",
            "module": "ml/decision_engine/validation.py",
        },
        {
            "stage": "Feature Resolution",
            "research_legacy": "Unified row from pre-built frame (position align fallback)",
            "production_paper": "PipelineCache unified row iloc[-1] on closed bars",
            "status": "different",
            "module": "phase24a:206-216 vs kernel_adapter.py:188",
        },
        {
            "stage": "Model",
            "research_legacy": "EngineRegistry via KernelAdapter",
            "production_paper": "EngineRegistry via MLKernelRegistry → KernelAdapter",
            "status": "identical",
            "module": "ml/integration/kernel_adapter.py",
        },
        {
            "stage": "Decision",
            "research_legacy": "DecisionOrchestrator via quality.evaluate",
            "production_paper": "same",
            "status": "identical",
            "module": "ml/integration/kernel_adapter.py:219",
        },
        {
            "stage": "Calibration",
            "research_legacy": "CalibratedDecisionAdapter inside quality.evaluate",
            "production_paper": "same",
            "status": "identical",
            "module": "ml/trade_quality/adapter.py",
        },
        {
            "stage": "AdaptiveRisk",
            "research_legacy": "AdaptiveRiskAdapter inside quality.evaluate",
            "production_paper": "same",
            "status": "identical",
            "module": "ml/risk_intelligence/validator.py",
        },
        {
            "stage": "TradeQuality",
            "research_legacy": "TradeQualityAdapter inside quality.evaluate",
            "production_paper": "same",
            "status": "identical",
            "module": "ml/trade_quality/adapter.py",
        },
        {
            "stage": "Profitability Filters",
            "research_legacy": "apply_profitability_filters post-hoc in collect_production_decisions",
            "production_paper": "apply_profitability_filters inside KernelAdapter",
            "status": "duplicated_logic",
            "module": "phase24a:281 vs kernel_adapter.py:254",
        },
        {
            "stage": "Legacy RiskGate",
            "research_legacy": "skipped",
            "production_paper": "RiskStage → RiskGate.evaluate",
            "status": "skipped_in_research",
            "module": "pipeline/risk_stage.py:35",
        },
        {
            "stage": "Execution",
            "research_legacy": "skipped",
            "production_paper": "ExecutionStage → Mt5ExecutionAdapter paper branch",
            "status": "skipped_in_research",
            "module": "pipeline/execution_stage.py:21",
        },
        {
            "stage": "Forming Bar Alignment",
            "research_legacy": "Timestamp = norm_candles.index[bar_index] (no exclude_forming_bar)",
            "production_paper": "exclude_forming_bar → closed.index[-1]",
            "status": "different",
            "module": "domain/ohlcv.py:61 vs phase24a:205",
        },
    ]
    repaired = {
        "stage": "Phase25B Unified Replay",
        "path": "TradingKernel full pipeline on ParityReplayMarketDataAdapter",
        "depth": "Data → Indicator → Signal → Risk → Execution",
        "matches_production_paper": True,
        "module": "ml/research/phase25b/unified_pipeline_replay.py",
    }
    return {
        "legacy_research_vs_production_paper": stages,
        "repaired_research_path": repaired,
        "summary": {
            "legacy_identical_stages": sum(1 for s in stages if s["status"] == "identical"),
            "legacy_different_stages": sum(1 for s in stages if s["status"] == "different"),
            "legacy_skipped_in_research": sum(1 for s in stages if s["status"] == "skipped_in_research"),
            "repaired_pipeline_depth_matches_paper": True,
        },
    }
