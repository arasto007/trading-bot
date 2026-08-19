"""Phase 27D deliverable presence and post-cache-fix validation."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27d"

DELIVERABLES = [
    "trading_statistics.json",
    "performance_statistics.json",
    "profitability.json",
    "risk_statistics.json",
    "signal_statistics.json",
    "engine_statistics.json",
    "regime_statistics.json",
    "journal_statistics.json",
    "pipeline_statistics.json",
    "hold_funnel.json",
    "latency_statistics.json",
    "cache_statistics.json",
    "final_report.json",
]

VERDICTS = {"READY_FOR_PAPER", "NOT_READY_FOR_PAPER"}


class TestPhase27DDeliverables(unittest.TestCase):
    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_post_cache_fix_replay(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        cfg = report.get("replay_config") or {}
        self.assertTrue(cfg.get("post_phase27c_cache_fix"))
        self.assertEqual(cfg.get("replay_days"), 30)
        self.assertEqual(cfg.get("warmup_bars"), 300)

    def test_cache_uniqueness_improved_vs_27a(self) -> None:
        cache = json.loads((PHASE_DIR / "cache_statistics.json").read_text(encoding="utf-8"))
        self.assertGreater(cache.get("unique_prediction_checksums", 0), 3)
        self.assertGreater(cache.get("prediction_uniqueness_pct", 0), 10.0)

    def test_hold_funnel_structure(self) -> None:
        funnel = json.loads((PHASE_DIR / "hold_funnel.json").read_text(encoding="utf-8"))
        self.assertIn("funnel", funnel)
        self.assertIn("top_10_hold_reasons", funnel)
        self.assertGreaterEqual(len(funnel.get("funnel") or []), 5)


if __name__ == "__main__":
    unittest.main()
