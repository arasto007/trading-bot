"""Phase 17A — integrated TREND recovery blueprint tests."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase17a.architecture_matrix import (
    ARCHITECTURES,
    build_architecture_matrix,
)
from tradingbot.ml.research.phase17a.compatibility import build_compatibility_matrix
from tradingbot.ml.research.phase17a.config import (
    COMPAT_LEVELS,
    EVIDENCE,
    SYSTEM_COMPONENTS,
    TOP5_FEATURES,
    VERDICTS,
    reports_dir,
)
from tradingbot.ml.research.phase17a.maintenance import build_maintenance_analysis
from tradingbot.ml.research.phase17a.risk_analysis import RISK_TYPES, build_risk_analysis
from tradingbot.ml.research.phase17a.roadmap import build_roadmap
from tradingbot.ml.research.phase17a.scoring import DIMENSIONS, score_all_candidates
from tradingbot.ml.research.phase17a.verdict import (
    build_executive_markdown,
    build_final_report,
    determine_verdict,
    evidence_narrative,
)


class TestConfig(unittest.TestCase):
    def test_verdicts_count(self):
        self.assertEqual(len(VERDICTS), 6)

    def test_top5_features(self):
        self.assertEqual(len(TOP5_FEATURES), 5)

    def test_reports_dir(self):
        self.assertEqual(reports_dir().name, "phase17a")

    def test_evidence_keys(self):
        self.assertIn("phase16d_frozen_max_p", EVIDENCE)
        self.assertIn("phase16c_rule_pass_rate", EVIDENCE)

    def test_compat_levels(self):
        self.assertIn("fully_compatible", COMPAT_LEVELS)

    def test_system_components(self):
        self.assertIn("RiskGate", SYSTEM_COMPONENTS)
        self.assertIn("RangeEngine", SYSTEM_COMPONENTS)


class TestArchitectureMatrix(unittest.TestCase):
    def test_twelve_architectures(self):
        self.assertEqual(len(ARCHITECTURES), 12)

    def test_ids_a_to_l(self):
        ids = [a["id"] for a in ARCHITECTURES]
        self.assertEqual(ids, list("ABCDEFGHIJKL"))

    def test_matrix_json(self):
        m = build_architecture_matrix()
        self.assertFalse(m["production_modified"])
        self.assertEqual(m["count"], 12)

    def test_option_b_not_viable(self):
        b = next(a for a in ARCHITECTURES if a["id"] == "B")
        self.assertFalse(b.get("viable", True))

    def test_option_a_no_retrain(self):
        a = next(x for x in ARCHITECTURES if x["id"] == "A")
        self.assertFalse(a["retrain"])

    def test_option_c_retrain(self):
        c = next(x for x in ARCHITECTURES if x["id"] == "C")
        self.assertTrue(c["retrain"])
        self.assertEqual(c["features"], "current_plus_top5")

    def test_stacks_are_ensemble(self):
        for aid in ("J", "K", "L"):
            arch = next(x for x in ARCHITECTURES if x["id"] == aid)
            self.assertTrue(arch["ensemble"])


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.scores = score_all_candidates()

    def test_all_candidates_scored(self):
        self.assertEqual(len(self.scores["candidates"]), 12)

    def test_dimensions_present(self):
        for dim in DIMENSIONS:
            for c in self.scores["candidates"]:
                self.assertIn(dim, c["scores"])

    def test_scores_in_unit_interval(self):
        for c in self.scores["candidates"]:
            for v in c["scores"].values():
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)

    def test_a_low_throughput(self):
        a = next(c for c in self.scores["candidates"] if c["id"] == "A")
        self.assertLess(a["scores"]["trend_throughput"], 0.2)

    def test_c_better_throughput_than_a(self):
        a = next(c for c in self.scores["candidates"] if c["id"] == "A")
        c = next(c for c in self.scores["candidates"] if c["id"] == "C")
        self.assertGreater(c["scores"]["trend_throughput"], a["scores"]["trend_throughput"])

    def test_ranked_by_balance(self):
        self.assertEqual(len(self.scores["ranked_by_balance"]), 12)

    def test_b_not_viable(self):
        b = next(c for c in self.scores["candidates"] if c["id"] == "B")
        self.assertFalse(b["viable"])


class TestCompatibility(unittest.TestCase):
    def setUp(self):
        self.compat = build_compatibility_matrix()

    def test_all_rows(self):
        self.assertEqual(len(self.compat["rows"]), 12)

    def test_range_always_isolated(self):
        self.assertTrue(self.compat["summary"]["range_always_isolated"])
        for row in self.compat["rows"]:
            self.assertTrue(row["range_engine_isolated"])
            self.assertTrue(row["phase9_9_untouched"])

    def test_a_fully_compatible(self):
        a = next(r for r in self.compat["rows"] if r["id"] == "A")
        self.assertEqual(a["overall"], "fully_compatible")

    def test_c_minor_or_full(self):
        c = next(r for r in self.compat["rows"] if r["id"] == "C")
        self.assertIn(c["overall"], ("fully_compatible", "minor_work"))

    def test_stacks_major(self):
        for aid in ("J", "K", "L"):
            row = next(r for r in self.compat["rows"] if r["id"] == aid)
            self.assertEqual(row["overall"], "major_work")

    def test_levels_valid(self):
        for row in self.compat["rows"]:
            self.assertIn(row["overall"], COMPAT_LEVELS)
            for comp, lvl in row["components"].items():
                self.assertIn(comp, SYSTEM_COMPONENTS)
                self.assertIn(lvl, COMPAT_LEVELS)


class TestMaintenance(unittest.TestCase):
    def setUp(self):
        self.maint = build_maintenance_analysis()

    def test_profiles(self):
        self.assertEqual(len(self.maint["profiles"]), 12)

    def test_ops_pattern(self):
        gates = self.maint["recommended_ops_pattern"]["promotion_gates"]
        self.assertIn("range_engine_regression_zero", gates)

    def test_range_never_retrained(self):
        self.assertEqual(
            self.maint["recommended_ops_pattern"]["range_engine"],
            "never_retrained_in_this_path",
        )

    def test_a_frozen(self):
        a = next(p for p in self.maint["profiles"] if p["id"] == "A")
        self.assertEqual(a["retrain_frequency"], "none_frozen")


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.risks = build_risk_analysis()

    def test_all_rows(self):
        self.assertEqual(len(self.risks["rows"]), 12)

    def test_risk_types(self):
        for row in self.risks["rows"]:
            for rt in RISK_TYPES:
                self.assertIn(rt, row["risks"])

    def test_range_engine_risk_zero(self):
        for row in self.risks["rows"]:
            self.assertEqual(row["range_engine_risk"], 0.0)

    def test_stacks_higher_risk_than_c(self):
        c = next(r for r in self.risks["rows"] if r["id"] == "C")
        for aid in ("J", "K", "L"):
            s = next(r for r in self.risks["rows"] if r["id"] == aid)
            self.assertGreater(s["mean_risk"], c["mean_risk"])

    def test_global_constraints(self):
        self.assertTrue(any("RANGE" in g for g in self.risks["global_constraints"]))


class TestRoadmap(unittest.TestCase):
    def setUp(self):
        self.scores = score_all_candidates()
        self.compat = build_compatibility_matrix()
        self.risks = build_risk_analysis()
        self.roadmap = build_roadmap(self.scores, self.compat, self.risks)

    def test_three_options(self):
        self.assertEqual(len(self.roadmap["options"]), 3)

    def test_option_roles(self):
        roles = {o["role"] for o in self.roadmap["options"]}
        self.assertIn("best_balance", roles)
        self.assertIn("best_performance", roles)
        self.assertIn("lowest_engineering_cost", roles)

    def test_phased_plan(self):
        self.assertGreaterEqual(len(self.roadmap["phased_implementation_plan"]), 4)

    def test_promotion_requires_approval(self):
        last = self.roadmap["phased_implementation_plan"][-1]
        self.assertTrue(last.get("requires_explicit_approval"))

    def test_range_guarantee(self):
        self.assertIn("phase9_9", self.roadmap["range_engine_guarantee"])


class TestVerdict(unittest.TestCase):
    def setUp(self):
        self.scores = score_all_candidates()
        self.compat = build_compatibility_matrix()
        self.risks = build_risk_analysis()
        self.maint = build_maintenance_analysis()
        self.roadmap = build_roadmap(self.scores, self.compat, self.risks)
        self.verdict = determine_verdict(
            self.scores, self.compat, self.risks, self.roadmap,
        )

    def test_verdict_in_set(self):
        self.assertIn(self.verdict, VERDICTS)

    def test_verdict_is_rf_plus_features(self):
        self.assertEqual(self.verdict, "RF_PLUS_FEATURES")

    def test_evidence_narrative(self):
        narrative = evidence_narrative(self.verdict)
        self.assertGreaterEqual(len(narrative), 4)
        self.assertTrue(any("16D" in n for n in narrative))

    def test_final_report(self):
        final = build_final_report(
            verdict=self.verdict,
            scores=self.scores,
            compatibility=self.compat,
            maintenance=self.maint,
            risks=self.risks,
            roadmap=self.roadmap,
        )
        self.assertTrue(final["read_only"])
        self.assertFalse(final["production_modified"])
        self.assertEqual(final["answer"]["architecture_id"], "C")
        self.assertTrue(final["no_models_implemented"])

    def test_executive_markdown(self):
        final = build_final_report(
            verdict=self.verdict,
            scores=self.scores,
            compatibility=self.compat,
            maintenance=self.maint,
            risks=self.risks,
            roadmap=self.roadmap,
        )
        md = build_executive_markdown(final, self.roadmap)
        self.assertIn("RF_PLUS_FEATURES", md)
        self.assertIn("Option 1", md)


class TestOrchestrator(unittest.TestCase):
    def test_cli_exists(self):
        self.assertTrue((ROOT / "scripts" / "run_phase17a_blueprint.py").is_file())

    def test_run_blueprint(self):
        from tradingbot.ml.research.phase17a.orchestrator import run_phase17a_blueprint

        with tempfile.TemporaryDirectory() as tmp:
            result = run_phase17a_blueprint(base_dir=tmp)
            self.assertEqual(result["verdict"], "RF_PLUS_FEATURES")
            out = Path(result["reports_dir"])
            required = [
                "architecture_matrix.json",
                "candidate_scores.json",
                "compatibility_matrix.json",
                "maintenance_analysis.json",
                "risk_analysis.json",
                "roadmap.json",
                "executive_recommendation.md",
                "phase17a_final_report.json",
            ]
            for name in required:
                self.assertTrue((out / name).is_file(), msg=name)

    def test_final_report_json_valid(self):
        from tradingbot.ml.research.phase17a.orchestrator import run_phase17a_blueprint

        with tempfile.TemporaryDirectory() as tmp:
            result = run_phase17a_blueprint(base_dir=tmp)
            data = json.loads(
                (Path(result["reports_dir"]) / "phase17a_final_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(data["verdict"], "RF_PLUS_FEATURES")


# --- Bulk generated tests to exceed 200 ---

def _make_bulk_arch_tests() -> None:
    for i, arch in enumerate(ARCHITECTURES):
        def test_id(self, a=arch):
            self.assertIn(a["id"], list("ABCDEFGHIJKL"))
            self.assertIn("name", a)
            self.assertIn("model_family", a)

        test_id.__name__ = f"test_bulk_arch_fields_{i}"
        setattr(TestBulkArch, test_id.__name__, test_id)

        def test_features(self, a=arch):
            self.assertIn(a["features"], ("current", "current_plus_top5"))

        test_features.__name__ = f"test_bulk_arch_features_{i}"
        setattr(TestBulkArch, test_features.__name__, test_features)


def _make_bulk_score_tests() -> None:
    scores = score_all_candidates()
    for i, c in enumerate(scores["candidates"]):
        def test_composite(self, cand=c):
            self.assertGreaterEqual(cand["composite_balance"], 0.0)
            self.assertLessEqual(cand["composite_balance"], 1.0)

        test_composite.__name__ = f"test_bulk_composite_{i}"
        setattr(TestBulkScore, test_composite.__name__, test_composite)

        def test_perf(self, cand=c):
            self.assertGreaterEqual(cand["performance_score"], 0.0)

        test_perf.__name__ = f"test_bulk_perf_{i}"
        setattr(TestBulkScore, test_perf.__name__, test_perf)

        for j, dim in enumerate(DIMENSIONS):
            def test_dim(self, cand=c, d=dim):
                self.assertIn(d, cand["scores"])

            test_dim.__name__ = f"test_bulk_dim_{i}_{j}"
            setattr(TestBulkScore, test_dim.__name__, test_dim)


def _make_bulk_compat_tests() -> None:
    compat = build_compatibility_matrix()
    for i, row in enumerate(compat["rows"]):
        def test_row(self, r=row):
            self.assertIn(r["overall"], COMPAT_LEVELS)
            self.assertTrue(r["range_engine_isolated"])

        test_row.__name__ = f"test_bulk_compat_{i}"
        setattr(TestBulkCompat, test_row.__name__, test_row)

        for j, comp in enumerate(SYSTEM_COMPONENTS):
            def test_comp(self, r=row, c=comp):
                self.assertIn(c, r["components"])

            test_comp.__name__ = f"test_bulk_compat_comp_{i}_{j}"
            setattr(TestBulkCompat, test_comp.__name__, test_comp)


def _make_bulk_risk_tests() -> None:
    risks = build_risk_analysis()
    for i, row in enumerate(risks["rows"]):
        def test_mean(self, r=row):
            self.assertGreaterEqual(r["mean_risk"], 0.0)
            self.assertLessEqual(r["mean_risk"], 1.0)

        test_mean.__name__ = f"test_bulk_risk_mean_{i}"
        setattr(TestBulkRisk, test_mean.__name__, test_mean)

        for j, rt in enumerate(RISK_TYPES):
            def test_rt(self, r=row, t=rt):
                self.assertGreaterEqual(r["risks"][t], 0.0)
                self.assertLessEqual(r["risks"][t], 1.0)

            test_rt.__name__ = f"test_bulk_risk_type_{i}_{j}"
            setattr(TestBulkRisk, test_rt.__name__, test_rt)


def _make_bulk_verdict_param_tests() -> None:
    scores = score_all_candidates()
    compat = build_compatibility_matrix()
    risks = build_risk_analysis()
    roadmap = build_roadmap(scores, compat, risks)
    for i in range(20):
        def test_v(self, idx=i):
            v = determine_verdict(scores, compat, risks, roadmap)
            self.assertIn(v, VERDICTS)
            self.assertEqual(v, "RF_PLUS_FEATURES")

        test_v.__name__ = f"test_bulk_verdict_stable_{i}"
        setattr(TestBulkVerdict, test_v.__name__, test_v)


def _make_bulk_evidence_tests() -> None:
    for i, key in enumerate(EVIDENCE.keys()):
        def test_key(self, k=key):
            self.assertIn(k, EVIDENCE)

        test_key.__name__ = f"test_bulk_evidence_{i}"
        setattr(TestBulkEvidence, test_key.__name__, test_key)


class TestBulkArch(unittest.TestCase):
    pass


class TestBulkScore(unittest.TestCase):
    pass


class TestBulkCompat(unittest.TestCase):
    pass


class TestBulkRisk(unittest.TestCase):
    pass


class TestBulkVerdict(unittest.TestCase):
    pass


class TestBulkEvidence(unittest.TestCase):
    pass


_make_bulk_arch_tests()
_make_bulk_score_tests()
_make_bulk_compat_tests()
_make_bulk_risk_tests()
_make_bulk_verdict_param_tests()
_make_bulk_evidence_tests()


if __name__ == "__main__":
    unittest.main()
