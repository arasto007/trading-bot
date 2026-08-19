"""Phase 10.5 kernel shadow error audit tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.integration.error_audit.kernel_error_analyzer import (
    KernelErrorAnalyzer,
    is_risk_block_message,
    split_kernel_errors,
)
from tradingbot.ml.integration.error_audit.error_report import build_error_audit_report, save_error_audit_report
from tradingbot.ml.integration.error_audit.recovery_manager import ShadowRecoveryManager
from tradingbot.ml.integration.error_audit.shadow_health_check import ShadowHealthCheck
from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast


class TestPhase105ErrorAudit(unittest.TestCase):
    def test_risk_block_not_pipeline_failure(self):
        pipeline, risk = split_kernel_errors(
            ["Risk blocked: ATR percentile too high (100>96) (XAUUSD_i)", "DataStage: boom"]
        )
        self.assertEqual(len(risk), 1)
        self.assertEqual(len(pipeline), 1)
        self.assertTrue(is_risk_block_message(risk[0]))

    def test_error_classification(self):
        analyzer = KernelErrorAnalyzer()
        summary = analyzer.analyze_contexts(
            [
                {
                    "timestamp": "2026-06-25T16:35:00+00:00",
                    "errors": ["Risk blocked: friday no entry window (XAUUSD_i)"],
                }
            ]
        )
        self.assertEqual(summary.pipeline_failures, 0)
        self.assertEqual(summary.risk_blocks, 1)
        self.assertFalse(summary.records[0].fix_required)

    def test_recovery_manager_continues(self):
        recovery = ShadowRecoveryManager()

        def ok():
            return "done"

        result = recovery.run_cycle(ok, timestamp="t", bar_index=1)
        self.assertEqual(result, "done")
        self.assertEqual(recovery.state.cycles_completed, 1)

        def fail():
            raise ValueError("test")

        result = recovery.run_cycle(fail, timestamp="t2", bar_index=2)
        self.assertIsNone(result)
        self.assertEqual(recovery.state.recoverable_failures, 1)

    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = build_error_audit_report(
                run_id="test",
                contexts=[{"timestamp": "t", "errors": ["Risk blocked: spread too high"]}],
            )
            path = save_error_audit_report(report, tmp)
            self.assertTrue(path.is_file())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["error_summary"]["pipeline_failures"], 0)

    def test_health_check_passes_with_risk_blocks_only(self):
        health = ShadowHealthCheck().evaluate_artifacts(
            run_id="t",
            contexts=[
                {"timestamp": "t", "errors": ["Risk blocked: friday no entry window"]},
            ],
            metrics={"kernel_cycles": 100, "risk_allowed": 10, "risk_blocked": 1, "ml_predictions": 100},
            invalid_trades=0,
            recovery={"cycles_attempted": 100, "completion_rate": 1.0},
        )
        self.assertTrue(health.checks["pipeline_error_rate_zero"])
        self.assertTrue(health.passed)

    def test_health_check_fails_on_real_pipeline_error(self):
        health = ShadowHealthCheck().evaluate_artifacts(
            run_id="t",
            contexts=[{"timestamp": "t", "errors": ["SignalStage: enriched_ohlcv missing"]}],
            metrics={"kernel_cycles": 1},
            invalid_trades=0,
        )
        self.assertFalse(health.checks["pipeline_error_rate_zero"])
        self.assertFalse(health.passed)

    def test_ast_safety_scan(self):
        self.assertEqual(scan_live_shadow_ast(), [])

    def test_deterministic_audit(self):
        contexts = [{"timestamp": "t", "errors": ["Risk blocked: x"]}]
        a = build_error_audit_report(run_id="r", contexts=contexts)
        b = build_error_audit_report(run_id="r", contexts=contexts)
        self.assertEqual(a["error_summary"], b["error_summary"])

    def test_classify_context_errors(self):
        recovery = ShadowRecoveryManager()
        p, r = recovery.classify_context_errors(
            ["Risk blocked: a", "IndicatorStage: missing"]
        )
        self.assertEqual(len(p), 1)
        self.assertEqual(len(r), 1)


if __name__ == "__main__":
    unittest.main()
