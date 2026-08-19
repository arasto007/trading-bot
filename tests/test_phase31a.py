"""Phase 31A — edge optimization master audit tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase31a"

DELIVERABLES = [
    "trade_clusters.json",
    "winner_clusters.json",
    "loser_clusters.json",
    "feature_importance.json",
    "interaction_matrix.json",
    "edge_concentration.json",
    "edge_dilution.json",
    "root_cause_ranking.json",
    "expected_edge_gain.json",
    "implementation_priority.json",
    "phase31a_final_report.json",
]

VERDICTS = {"EDGE_ALREADY_NEAR_MAXIMUM", "MAJOR_EDGE_AVAILABLE"}


class TestPhase31A(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase31a_final_report.json").is_file():
            from tradingbot.ml.research.phase31a.run_investigation import run_phase31a

            run_phase31a()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_final_verdict(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31a_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(doc["verdict"], VERDICTS)
        self.assertFalse(doc.get("production_modified", True))
        self.assertGreaterEqual(doc["trades_analyzed"], 400)

    def test_clusters_discovered_automatically(self) -> None:
        doc = json.loads((PHASE_DIR / "trade_clusters.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(doc["cluster_count"], 4)
        for c in doc["clusters"]:
            self.assertIn("discovered_name", c)
            self.assertIn("pf", c)
            self.assertIn("trade_count", c)

    def test_winner_loser_clusters_split(self) -> None:
        winners = json.loads((PHASE_DIR / "winner_clusters.json").read_text(encoding="utf-8"))
        losers = json.loads((PHASE_DIR / "loser_clusters.json").read_text(encoding="utf-8"))
        self.assertGreater(winners["count"], 0)
        self.assertGreater(losers["count"], 0)

    def test_feature_importance_ranked(self) -> None:
        doc = json.loads((PHASE_DIR / "feature_importance.json").read_text(encoding="utf-8"))
        feats = doc["features"]
        self.assertGreaterEqual(len(feats), 10)
        self.assertEqual(feats[0]["rank"], 1)
        self.assertGreaterEqual(feats[0]["importance_mean"], feats[-1]["importance_mean"])

    def test_interaction_matrix_populated(self) -> None:
        doc = json.loads((PHASE_DIR / "interaction_matrix.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(doc["interactions"]), 5)
        ix = doc["interactions"][0]
        self.assertIn("dimension_a", ix)
        self.assertIn("lift_vs_baseline", ix)

    def test_root_cause_top20(self) -> None:
        doc = json.loads((PHASE_DIR / "root_cause_ranking.json").read_text(encoding="utf-8"))
        causes = doc["causes"]
        self.assertGreaterEqual(len(causes), 10)
        self.assertLessEqual(len(causes), 20)
        self.assertEqual(causes[0]["rank"], 1)
        for key in ("money_lost", "pf_improvement_estimate", "why", "confidence"):
            self.assertIn(key, causes[0])

    def test_edge_concentration_metrics(self) -> None:
        doc = json.loads((PHASE_DIR / "edge_concentration.json").read_text(encoding="utf-8"))
        self.assertIn("herfindahl_index", doc)
        self.assertIn("top_loser_clusters", doc)

    def test_edge_dilution_segments(self) -> None:
        doc = json.loads((PHASE_DIR / "edge_dilution.json").read_text(encoding="utf-8"))
        self.assertIn("dilution_segments", doc)

    def test_expected_edge_gain(self) -> None:
        doc = json.loads((PHASE_DIR / "expected_edge_gain.json").read_text(encoding="utf-8"))
        self.assertIn("baseline_pf", doc)
        self.assertIn("estimated_monthly_edge_gain_usd", doc)

    def test_implementation_priority_ranked(self) -> None:
        doc = json.loads((PHASE_DIR / "implementation_priority.json").read_text(encoding="utf-8"))
        pri = doc["priorities"]
        self.assertGreaterEqual(len(pri), 5)
        self.assertIn("priority_rank", pri[0])

    def test_master_frame_loads(self) -> None:
        from tradingbot.ml.research.phase31a.data_loader import build_master_frame

        df, meta = build_master_frame()
        self.assertGreaterEqual(len(df), 400)
        self.assertIn("counter_trend_score", df.columns)
        self.assertIn("capture_efficiency", df.columns)

    def test_clustering_deterministic_k(self) -> None:
        from tradingbot.ml.research.phase31a.clustering import discover_clusters
        from tradingbot.ml.research.phase31a.data_loader import build_master_frame

        df, _ = build_master_frame()
        _, m1, k1 = discover_clusters(df)
        _, m2, k2 = discover_clusters(df)
        self.assertEqual(k1, k2)
        self.assertEqual(len(m1), len(m2))

    def test_permutation_importance_runs(self) -> None:
        from tradingbot.ml.research.phase31a.data_loader import build_master_frame
        from tradingbot.ml.research.phase31a.importance import compute_permutation_importance

        df, _ = build_master_frame()
        imp = compute_permutation_importance(df)
        self.assertGreater(len(imp), 5)

    def test_outcome_explanations_present(self) -> None:
        doc = json.loads((PHASE_DIR / "trade_clusters.json").read_text(encoding="utf-8"))
        exp = doc["explanations"]
        for key in ("why_winners_happen", "why_losers_happen", "why_mediocre_happen"):
            self.assertIn(key, exp)
            self.assertGreater(len(exp[key]), 20)


if __name__ == "__main__":
    unittest.main()
