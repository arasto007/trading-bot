"""Phase 31B — counterfactual edge validation tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase31b"

DELIVERABLES = [
    "counterfactual_replay_a.json",
    "counterfactual_replay_b.json",
    "counterfactual_replay_c.json",
    "causal_validation.json",
    "root_cause_confirmation.json",
    "expected_pf_after_each_fix.json",
    "phase31b_final_report.json",
]

VERDICTS = {"ROOT_CAUSES_CONFIRMED", "ROOT_CAUSES_REJECTED"}


class TestPhase31B(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase31b_final_report.json").is_file():
            from tradingbot.ml.research.phase31b.run_investigation import run_phase31b

            run_phase31b()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31b_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(doc["verdict"], VERDICTS)
        self.assertFalse(doc.get("production_modified", True))

    def test_replay_a_removes_range(self) -> None:
        doc = json.loads((PHASE_DIR / "counterfactual_replay_a.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["replay_id"], "A")
        self.assertIn("metrics", doc)
        self.assertIn("isolated_edge_gain", doc)

    def test_replay_b_improves_pf(self) -> None:
        doc = json.loads((PHASE_DIR / "counterfactual_replay_b.json").read_text(encoding="utf-8"))
        self.assertGreater(doc["metrics"]["profit_factor"], doc["baseline_metrics"]["profit_factor"])
        self.assertGreater(doc["isolated_edge_gain"]["net_profit"], 0)

    def test_replay_b_keeps_trade_count(self) -> None:
        doc = json.loads((PHASE_DIR / "counterfactual_replay_b.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["metrics"]["trade_count"], doc["baseline_metrics"]["trade_count"])

    def test_replay_c_scales_net_profit(self) -> None:
        doc = json.loads((PHASE_DIR / "counterfactual_replay_c.json").read_text(encoding="utf-8"))
        self.assertLess(abs(doc["metrics"]["net_profit"]), abs(doc["baseline_metrics"]["net_profit"]))

    def test_causal_validation_findings(self) -> None:
        doc = json.loads((PHASE_DIR / "causal_validation.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(doc["findings"]), 3)
        self.assertEqual(doc["dominant_root_cause"], "time_exit_undercaptured")

    def test_root_cause_confirmation(self) -> None:
        doc = json.loads((PHASE_DIR / "root_cause_confirmation.json").read_text(encoding="utf-8"))
        self.assertEqual(len(doc["phase31a_top3_tested"]), 3)
        results = {x["cause"]: x["result"] for x in doc["phase31a_top3_tested"]}
        self.assertEqual(results["time_exit_undercaptured"], "CONFIRMED")

    def test_expected_pf_ordered(self) -> None:
        doc = json.loads((PHASE_DIR / "expected_pf_after_each_fix.json").read_text(encoding="utf-8"))
        self.assertGreater(doc["after_replay_b"], doc["baseline_pf"])

    def test_replay_metrics_complete(self) -> None:
        for fname in ("counterfactual_replay_a.json", "counterfactual_replay_b.json", "counterfactual_replay_c.json"):
            doc = json.loads((PHASE_DIR / fname).read_text(encoding="utf-8"))
            m = doc["metrics"]
            for key in ("profit_factor", "expectancy", "sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                        "trade_count", "net_profit", "recovery_factor", "win_rate_pct"):
                self.assertIn(key, m)

    def test_counterfactual_transformations(self) -> None:
        from tradingbot.ml.research.phase31a.data_loader import build_master_frame
        from tradingbot.ml.research.phase31b.counterfactuals import (
            replay_a_remove_range,
            replay_b_perfect_capture,
            replay_c_remove_min_lot_distortion,
        )

        df, _ = build_master_frame()
        a, _ = replay_a_remove_range(df)
        b, notes_b = replay_b_perfect_capture(df)
        c, notes_c = replay_c_remove_min_lot_distortion(df)
        self.assertEqual(len(b), len(df))
        self.assertEqual(len(c), len(df))
        self.assertGreater(notes_b["trades_improved"], 0)
        self.assertAlmostEqual(notes_c["avg_scale_ratio"], 0.085, delta=0.02)

    def test_metrics_module(self) -> None:
        from tradingbot.ml.research.phase31b.metrics import compute_metrics

        trades = [{"pnl": 10, "pnl_r": 1, "timestamp": "2026-01-01", "exit_timestamp": "2026-01-02", "duration_bars": 1}]
        m = compute_metrics(trades)
        self.assertEqual(m["trade_count"], 1)
        self.assertEqual(m["net_profit"], 10)

    def test_bootstrap_ci(self) -> None:
        from tradingbot.ml.research.phase31a.data_loader import build_master_frame
        from tradingbot.ml.research.phase31b.counterfactuals import replay_b_perfect_capture
        from tradingbot.ml.research.phase31b.metrics import bootstrap_pf_ci

        df, _ = build_master_frame()
        trades, _ = replay_b_perfect_capture(df)
        ci = bootstrap_pf_ci(trades)
        self.assertIn("pf_low", ci)
        self.assertGreater(ci["pf_low"], 1.0)

    def test_replay_b_production_unchanged_flag(self) -> None:
        doc = json.loads((PHASE_DIR / "counterfactual_replay_b.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["transformation_notes"]["production_exits_unchanged"])

    def test_range_rejected_in_causal(self) -> None:
        doc = json.loads((PHASE_DIR / "causal_validation.json").read_text(encoding="utf-8"))
        range_f = next(f for f in doc["findings"] if f["root_cause"] == "range_regime_losers")
        self.assertEqual(range_f["verdict"], "REJECTED_AS_FILTER")


if __name__ == "__main__":
    unittest.main()
