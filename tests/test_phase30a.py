"""Phase 30A — execution simulator unit tests and deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile, ExecutionScenario, OrderSide
from tradingbot.execution.execution_simulator import ExecutionSimulator, execution_quality_score
from tradingbot.execution.execution_costs import compute_spread_points, session_from_hour
from tradingbot.execution.fill_model import PARTIAL_FILL_LEVELS, choose_fill_ratio
from tradingbot.execution.liquidity_model import effective_liquidity
from tradingbot.execution.order_queue import OrderQueue
from tradingbot.execution.execution_latency import sample_total_latency_ms
import random

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase30a"

DELIVERABLES = [
    "execution_pipeline_map.json",
    "spread_distribution.json",
    "slippage_distribution.json",
    "latency_distribution.json",
    "market_impact.json",
    "fill_statistics.json",
    "execution_quality.json",
    "stress_tests.json",
    "execution_breaking_points.json",
    "performance_comparison.json",
    "production_recommendation.json",
    "phase30a_final_report.json",
]

VERDICTS = {
    "EXECUTION_LAYER_VALIDATED",
    "EXECUTION_LAYER_NEEDS_IMPROVEMENT",
    "NOT_READY_FOR_PRODUCTION",
}


def _sample_ctx(**overrides) -> ExecutionContext:
    base = dict(
        symbol="XAUUSD",
        side=OrderSide.BUY,
        requested_lot=0.01,
        reference_price=2000.0,
        timestamp="2026-06-02T12:00:00+00:00",
        session="Overlap",
        atr=1.5,
        atr_percentile=50.0,
        spread_points=0.30,
        liquidity_score=0.8,
    )
    base.update(overrides)
    return ExecutionContext(**base)


class TestPhase30A(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase30a_final_report.json").is_file():
            from tradingbot.ml.research.phase30a.run_investigation import run_phase30a

            run_phase30a()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_pipeline_map_research_only(self) -> None:
        doc = json.loads((PHASE_DIR / "execution_pipeline_map.json").read_text(encoding="utf-8"))
        self.assertTrue(doc.get("research_only"))
        self.assertFalse(doc.get("production_modified"))
        self.assertGreaterEqual(len(doc.get("ideal_assumptions", [])), 8)

    def test_session_from_hour(self) -> None:
        self.assertEqual(session_from_hour(14), "Overlap")
        self.assertEqual(session_from_hour(3), "Asian")

    def test_spread_session_dependent(self) -> None:
        ctx_asian = _sample_ctx(session="Asian")
        ctx_overlap = _sample_ctx(session="Overlap")
        profile = ExecutionProfile()
        self.assertGreater(compute_spread_points(ctx_asian, profile), compute_spread_points(ctx_overlap, profile))

    def test_simulator_deterministic(self) -> None:
        ctx = _sample_ctx()
        profile = ExecutionProfile(seed=99)
        a = ExecutionSimulator(profile).simulate(ctx)
        b = ExecutionSimulator(profile).simulate(ctx)
        self.assertEqual(a.outcome.fill_price, b.outcome.fill_price)
        self.assertEqual(a.outcome.execution_score, b.outcome.execution_score)

    def test_execution_score_bounds(self) -> None:
        score = execution_quality_score(
            spread_points=0.3,
            latency_ms=50,
            slippage_points=0.05,
            fill_ratio=1.0,
            market_impact_points=0.01,
            queue_delay_ms=10,
        )
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_partial_fill_levels(self) -> None:
        self.assertIn(0.25, PARTIAL_FILL_LEVELS)
        self.assertIn(1.0, PARTIAL_FILL_LEVELS)

    def test_low_liquidity_reduces_fill(self) -> None:
        ctx = _sample_ctx(liquidity_score=0.1, requested_lot=0.20)
        profile = ExecutionProfile(scenario=ExecutionScenario.LOW_LIQUIDITY, seed=7)
        ratio = choose_fill_ratio(ctx, profile, random.Random(7))
        self.assertLessEqual(ratio, 1.0)

    def test_order_queue_fifo(self) -> None:
        q = OrderQueue()
        q.enqueue("a", _sample_ctx(), now_ms=0)
        q.enqueue("b", _sample_ctx(), now_ms=0)
        first = q.dequeue_ready(now_ms=100)
        self.assertIsNotNone(first)
        self.assertEqual(first.order_id, "a")

    def test_latency_positive(self) -> None:
        total, _ = sample_total_latency_ms(_sample_ctx(), ExecutionProfile(), random.Random(1))
        self.assertGreater(total, 0)

    def test_stress_tests_cover_scenarios(self) -> None:
        stress = json.loads((PHASE_DIR / "stress_tests.json").read_text(encoding="utf-8"))
        scenarios = stress.get("scenarios", {})
        for name in ("normal", "high_spread", "flash_crash", "weekend"):
            self.assertIn(name, scenarios)

    def test_breaking_points_structure(self) -> None:
        bp = json.loads((PHASE_DIR / "execution_breaking_points.json").read_text(encoding="utf-8"))
        self.assertIn("max_spread_multiplier_before_pf_lt_1", bp)
        self.assertIn("sweep", bp["max_spread_multiplier_before_pf_lt_1"])

    def test_performance_comparison_has_both_paths(self) -> None:
        comp = json.loads((PHASE_DIR / "performance_comparison.json").read_text(encoding="utf-8"))
        self.assertIn("ideal_execution", comp)
        self.assertIn("simulated_normal_execution", comp)
        self.assertEqual(comp.get("trade_count"), 489)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase30a_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)
        self.assertFalse(report.get("production_modified", True))


if __name__ == "__main__":
    unittest.main()
