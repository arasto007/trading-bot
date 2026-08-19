"""Phase 24A — live shadow validation tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VERDICT_OPTIONS = {
    "READY_FOR_PAPER_TRADING",
    "NEEDS_INVESTIGATION",
    "PRODUCTION_BLOCKED",
}


class TestPhase24AProfiles(unittest.TestCase):
    def test_hold_categories_defined(self) -> None:
        from tradingbot.ml.research.phase24a.live_shadow_validator import HOLD_CATEGORIES

        self.assertIn("profitability_filter", HOLD_CATEGORIES)
        self.assertIn("health_gate", HOLD_CATEGORIES)

    def test_classify_hold_buy_is_none(self) -> None:
        from tradingbot.ml.research.phase24a.live_shadow_validator import _classify_hold

        self.assertIsNone(
            _classify_hold(
                final_signal="BUY",
                hold_stage=None,
                raw_action="BUY",
                calibrated_action="BUY",
                risk_allowed=True,
                quality_allowed=True,
                filter_passed=True,
                feature_validation_failed=False,
                health_error=None,
                regime="RANGE",
            )
        )

    def test_classify_health_gate(self) -> None:
        from tradingbot.ml.research.phase24a.live_shadow_validator import _classify_hold

        reason = _classify_hold(
            final_signal="HOLD",
            hold_stage=None,
            raw_action="HOLD",
            calibrated_action="HOLD",
            risk_allowed=True,
            quality_allowed=True,
            filter_passed=None,
            feature_validation_failed=False,
            health_error="unified_frame_empty",
            regime="RANGE",
        )
        self.assertEqual(reason, "health_gate")


class TestPhase24AAnalysis(unittest.TestCase):
    def test_hold_analysis_percentages(self) -> None:
        from tradingbot.ml.research.phase24a.live_shadow_validator import build_hold_analysis

        rows = [
            {"final_signal": "HOLD", "hold_reason": "decision_gate"},
            {"final_signal": "HOLD", "hold_reason": "profitability_filter"},
            {"final_signal": "BUY", "hold_reason": None},
        ]
        out = build_hold_analysis(rows)
        self.assertEqual(out["hold_bars"], 2)
        self.assertAlmostEqual(out["category_percentages"]["decision_gate"], 33.3333, places=2)

    def test_confidence_distribution(self) -> None:
        from tradingbot.ml.research.phase24a.live_shadow_validator import build_confidence_distribution

        rows = [
            {"final_signal": "BUY", "confidence": 0.6},
            {"final_signal": "SELL", "confidence": 0.7},
            {"final_signal": "HOLD", "confidence": 0.2},
        ]
        out = build_confidence_distribution(rows)
        self.assertEqual(out["buy_signals"]["count"], 1)
        self.assertEqual(out["sell_signals"]["count"], 1)


class TestPhase24AIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase24a.live_shadow_validator import (
            build_confidence_distribution,
            build_hold_analysis,
            build_latency_report,
            build_probability_distribution,
            collect_production_decisions,
        )

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        records, runtime_meta = collect_production_decisions(
            base_dir=base_dir,
            tail_only=300,
            stride=10,
            warmup_bars=120,
        )
        cls.result = {
            "verdict": "NEEDS_INVESTIGATION",
            "runtime_statistics": {
                "execution_enabled": False,
                "order_send": False,
                **runtime_meta,
            },
            "hold_analysis": build_hold_analysis(records),
            "latency_report": build_latency_report(records, runtime_meta),
            "health_score": {"overall_health": 75.0},
            "research_vs_runtime": {"checks": {}},
        }
        cls.records = records

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result["verdict"], VERDICT_OPTIONS)

    def test_runtime_no_execution(self) -> None:
        stats = self.result["runtime_statistics"]
        self.assertFalse(stats["execution_enabled"])
        self.assertFalse(stats["order_send"])

    def test_hold_analysis_present(self) -> None:
        self.assertIn("category_percentages", self.result["hold_analysis"])

    def test_latency_report(self) -> None:
        self.assertIn("tick_arrival_to_output", self.result["latency_report"])

    def test_health_score(self) -> None:
        self.assertIn("overall_health", self.result["health_score"])

    def test_research_compare_structure(self) -> None:
        cmp = self.result["research_vs_runtime"]
        self.assertIn("checks", cmp)


class TestPhase24ADeliverables(unittest.TestCase):
    def test_files_exist(self) -> None:
        out = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24a"
        required = (
            "live_shadow_report.json",
            "runtime_statistics.json",
            "hold_analysis.json",
            "latency_report.json",
            "probability_distribution.json",
            "confidence_distribution.json",
            "health_score.json",
            "research_vs_runtime.json",
            "phase24a_final_report.json",
        )
        missing = [n for n in required if not (out / n).is_file()]
        if missing:
            import tradingbot.ml.research.phase24a.run_validation as runner

            runner.main(["--quick"])
        for name in required:
            self.assertTrue((out / name).is_file(), msg=f"missing {name}")
            payload = json.loads((out / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "24A")


if __name__ == "__main__":
    unittest.main()
