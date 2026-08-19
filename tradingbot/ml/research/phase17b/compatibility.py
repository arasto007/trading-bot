"""Phase 17B — production compatibility confirmation."""

from __future__ import annotations

from typing import Any


def build_compatibility_report() -> dict[str, Any]:
    return {
        "phase": "17B",
        "production_modified": False,
        "frozen_bundle_modified": False,
        "new_bundle_frozen": False,
        "components_untouched": [
            "TradingKernel",
            "RiskGate",
            "DecisionPolicy",
            "Router",
            "Calibration",
            "ConfidenceMapping",
            "FeatureAlignment_16A",
            "KernelAdapter",
            "Phase9_9_bundle",
            "trend_rf_v40_bundle",
            "MT5",
            "Execution",
            "Live_configuration",
        ],
        "research_only_artifacts": [
            "ResearchRfModel (in-memory)",
            "ResearchTrendEngine (shadow replay only)",
            "phase17b reports under data/ml/reports/phase17b/",
        ],
        "api_changes": False,
        "schema_changes": False,
        "kernel_changes": False,
        "riskgate_changes": False,
        "bundle_replacement": {
            "required_for_promotion": True,
            "performed_in_17b": False,
            "requires_explicit_approval": True,
        },
        "range_engine_isolation": "phase9_9 uses identical path in both frozen and research shadow replays",
        "compatibility_verdict": "fully_compatible_research_layer_only",
    }
