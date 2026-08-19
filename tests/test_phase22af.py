"""Phase 22AF — freeze pipeline repair design tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class TestPhase22AFDesign(unittest.TestCase):
    def test_authority_chain_has_five_stages(self):
        from tradingbot.ml.research.phase22af.repair_design import build_authority_redesign

        chain = build_authority_redesign()["target_authority_chain"]
        self.assertEqual(len(chain), 5)
        names = [s["name"] for s in chain]
        self.assertEqual(
            names,
            ["Optimizer winner", "Acceptance gate", "Freeze artifact", "Model Registry", "Runtime"],
        )

    def test_freeze_contract_required_fields(self):
        from tradingbot.ml.research.phase22af.repair_design import build_freeze_contract

        fields = build_freeze_contract()["required_fields"]
        for key in (
            "candidate_id",
            "model_type",
            "feature_subset",
            "hyperparameters",
            "thresholds",
            "validation_metrics",
            "probability_metrics",
            "acceptance_status",
        ):
            self.assertIn(key, fields)

    def test_safety_guards_cover_mandatory_rejections(self):
        from tradingbot.ml.research.phase22af.repair_design import build_safety_guard_design

        guards = {g["guard"] for g in build_safety_guard_design()["reject_conditions"]}
        self.assertTrue(
            {
                "no_acceptance",
                "failed_probability_gate",
                "missing_metadata",
                "unknown_candidate",
                "missing_validation_report",
            }.issubset(guards)
        )

    def test_broken_edges_identified(self):
        from tradingbot.ml.research.phase22af.repair_design import build_freeze_repair_design

        design = build_freeze_repair_design()
        self.assertGreaterEqual(len(design["broken_edges"]), 4)
        self.assertGreaterEqual(len(design["required_new_edges"]), 4)

    def test_migration_three_phases(self):
        from tradingbot.ml.research.phase22af.repair_design import build_migration_plan

        plan = build_migration_plan()["migration_phases"]
        self.assertEqual(len(plan), 3)
        self.assertFalse(plan[0]["production_touch"])
        self.assertTrue(plan[1]["production_touch"])

    def test_verdict_ready_for_implementation(self):
        from tradingbot.ml.research.phase22af.repair_design import determine_verdict, run_design

        self.assertEqual(determine_verdict(), "READY_FOR_IMPLEMENTATION")
        self.assertEqual(run_design()["verdict"], "READY_FOR_IMPLEMENTATION")

    def test_minimum_production_surface_includes_registry_and_orchestrator(self):
        from tradingbot.ml.research.phase22af.repair_design import build_required_changes

        surface = build_required_changes()["minimum_production_surface"]
        self.assertIn("model_registry.py", surface)
        self.assertIn("optimization_orchestrator.py", surface)


class TestPhase22AFDeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22af"
        for name in (
            "freeze_repair_design.json",
            "authority_redesign.json",
            "required_changes.json",
            "safety_guard_design.json",
            "migration_plan.json",
            "phase22af_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22af run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22af_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(final["verdict"], "READY_FOR_IMPLEMENTATION")
        self.assertFalse(final["production_modified"])


if __name__ == "__main__":
    unittest.main()
