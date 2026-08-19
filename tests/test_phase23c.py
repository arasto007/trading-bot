"""Phase 23C — decision gate investigation tests (read-only deliverables)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VERDICT_OPTIONS = {
    "CONFIDENCE_GATE_BLOCKING",
    "DECISION_POLICY_BLOCKING",
    "RISK_GATE_BLOCKING",
    "EXECUTION_GATE_BLOCKING",
    "MULTIPLE_ROOT_CAUSES",
}


class TestPhase23CInvestigation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.ml.data.paths import normalize_ml_base_dir
        from tradingbot.ml.research.phase23c.decision_gate_investigation import run_investigation

        base_dir = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
        cls.result = run_investigation(base_dir=base_dir)

    def test_confidence_formula_0_434(self) -> None:
        example = self.result["confidence_trace"]["sell_probability_0_434"]
        self.assertAlmostEqual(example["probability"], 0.434, places=3)
        self.assertAlmostEqual(example["computed_confidence"], 0.132, places=3)
        self.assertIn("abs(probability - 0.5) * 2.0", example["formula"])
        runtime_sample = self.result["confidence_trace"]["sell_probability_runtime_sample"]
        self.assertAlmostEqual(runtime_sample["computed_confidence"], 0.132712, places=4)

    def test_hold_chain_sites_present(self) -> None:
        sites = self.result["hold_chain_after_predict"]["hold_sites"]
        files = {s["file"] for s in sites}
        self.assertIn("tradingbot/ml/decision_engine/decision_policy.py", files)
        self.assertIn("tradingbot/ml/research/phase14_6/research_calibrator.py", files)

    def test_threshold_inventory_includes_055_and_045(self) -> None:
        values = {t["value"] for t in self.result["threshold_inventory"]["thresholds"]}
        self.assertIn(0.55, values)
        self.assertIn(0.45, values)

    def test_runtime_statistics_structure(self) -> None:
        stats = self.result["runtime_statistics"]
        self.assertNotIn("error", stats)
        counts = stats["counts"]
        self.assertGreater(counts["bars"], 0)
        self.assertIn("blocked_calibration", counts)
        self.assertIn("blocked_decision_policy", counts)

    def test_research_vs_runtime_divergence_documented(self) -> None:
        comp = self.result["research_vs_runtime"]
        self.assertFalse(comp.get("research_path", {}).get("uses_decision_policy"))
        self.assertIn("first_divergence", comp)

    def test_verdict_is_valid(self) -> None:
        self.assertIn(self.result["verdict"], VERDICT_OPTIONS)

    def test_root_cause_matches_verdict(self) -> None:
        self.assertEqual(
            self.result["root_cause_report"]["classification"],
            self.result["verdict"],
        )

    def test_repair_design_not_implemented(self) -> None:
        design = self.result["repair_design"]
        self.assertIn("NOT IMPLEMENTED", design["implementation_status"])

    def test_engine_actionable_after_phase23b(self) -> None:
        counts = self.result["runtime_statistics"]["counts"]
        self.assertGreater(counts.get("predict_proba_called", 0), 0)
        self.assertGreater(counts.get("engine_actionable", 0), 0)


class TestPhase23CDeliverables(unittest.TestCase):
    def test_deliverable_files_exist_after_run(self) -> None:
        out = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase23c"
        required = (
            "confidence_trace.json",
            "decision_policy.json",
            "hold_chain_after_predict.json",
            "threshold_inventory.json",
            "runtime_statistics.json",
            "research_vs_runtime.json",
            "root_cause_report.json",
            "repair_design.json",
            "phase23c_final_report.json",
        )
        missing = [name for name in required if not (out / name).is_file()]
        if missing:
            from tradingbot.adapters.legacy_loader import load_legacy_config
            from tradingbot.ml.data.paths import normalize_ml_base_dir
            import tradingbot.ml.research.phase23c.run_investigation as runner

            runner.main()
        for name in required:
            self.assertTrue((out / name).is_file(), msg=f"missing {name}")
            payload = json.loads((out / name).read_text(encoding="utf-8"))
            self.assertIn("phase", payload)
            self.assertEqual(payload["phase"], "23C")


if __name__ == "__main__":
    unittest.main()
