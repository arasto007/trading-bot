"""Phase 24H — duplicate pipeline execution tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase24h"

VERDICTS = {"NO_DUPLICATES_FOUND", "SAFE_DUPLICATE_REMOVAL", "DUPLICATES_REQUIRED"}


class TestPhase24HStaticAnalysis(unittest.TestCase):
    def test_static_inventory_lists_duplicates(self) -> None:
        from tradingbot.ml.research.phase24h.run_investigation import static_duplicate_inventory

        inv = static_duplicate_inventory()
        self.assertGreaterEqual(len(inv), 5)
        health = next(d for d in inv if d["stage"] == "HealthGate")
        self.assertEqual(health["executions_per_closed_candle"], 2)
        self.assertTrue(health["can_eliminate"])


class TestPhase24HRuntimeTrace(unittest.TestCase):
    def test_single_candle_trace_finds_health_gate_duplicate(self) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.stores.candle_store import CandleStore
        import asyncio
        from tradingbot.ml.research.phase24h.run_investigation import trace_one_closed_candle

        base_dir = load_legacy_config().get("BASE_DIR")
        if CandleStore(base_dir).load("XAUUSD", "M5") is None:
            self.skipTest("market data missing")

        result = asyncio.run(trace_one_closed_candle(base_dir=base_dir))
        counts = result.get("execution_counts", {})
        self.assertGreaterEqual(counts.get("HealthGate", 0), 2)
        self.assertEqual(counts.get("PipelineCache.get_unified_frame", 0), 1)
        self.assertEqual(counts.get("RangeEngineAdapter.evaluate", 0), 1)
        self.assertEqual(counts.get("TrendEngine.evaluate", 0), 1)


class TestPhase24HDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        final_path = PHASE_DIR / "phase24h_final_report.json"
        if not final_path.is_file():
            from tradingbot.ml.research.phase24h.run_investigation import write_deliverables

            cls.result = write_deliverables()
        else:
            cls.result = {"verdict": json.loads(final_path.read_text(encoding="utf-8"))["verdict"]}

    def test_verdict_valid(self) -> None:
        self.assertIn(self.result.get("verdict"), VERDICTS)

    def test_deliverables_exist(self) -> None:
        for name in (
            "single_candle_trace.json",
            "execution_counter.json",
            "duplicate_stage_report.json",
            "duplicate_cost.json",
            "optimization_priority.json",
            "phase24h_final_report.json",
        ):
            self.assertTrue((PHASE_DIR / name).is_file(), name)

    def test_duplicate_cost_positive(self) -> None:
        payload = json.loads((PHASE_DIR / "duplicate_cost.json").read_text(encoding="utf-8"))
        self.assertGreater(payload["total_wasted_p95_ms"], 0)

    def test_verdict_safe_duplicate_removal(self) -> None:
        self.assertEqual(self.result.get("verdict"), "SAFE_DUPLICATE_REMOVAL")


if __name__ == "__main__":
    unittest.main()
