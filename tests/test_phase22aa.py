"""Phase 22AA — impact radius forensics tests."""

from __future__ import annotations

import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _imports_in_file(rel_path: str) -> set[str]:
    tree = ast.parse((ROOT / rel_path).read_text(encoding="utf-8"))
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
    return mods


class TestPhase22AAForensics(unittest.TestCase):
    def test_freeze_not_in_acceptance_chain(self):
        from tradingbot.ml.research.phase22aa.impact_forensics import build_call_chain

        chain = build_call_chain()
        not_in = {x["function"] for x in chain["explicitly_not_in_chain"] if "function" in x}
        self.assertIn("freeze_phase9_9_artifacts", not_in)

    def test_health_gate_classified_safe(self):
        from tradingbot.ml.research.phase22aa.impact_forensics import build_impact_radius

        radius = build_impact_radius()
        health = next(i for i in radius["items"] if i["id"] == "health_gate")
        self.assertEqual(health["classification"], "SAFE")

    def test_evaluate_acceptance_critical(self):
        from tradingbot.ml.research.phase22aa.impact_forensics import build_impact_radius

        radius = build_impact_radius()
        critical = [i for i in radius["items"] if i["classification"] == "CRITICAL"]
        self.assertTrue(any(i["function"] == "evaluate_acceptance" for i in critical))

    def test_model_registry_does_not_import_evaluate_acceptance(self):
        mods = _imports_in_file("tradingbot/ml/paper_trading/model_registry.py")
        joined = " ".join(mods)
        self.assertNotIn("report_generator", joined)
        self.assertNotIn("evaluate_acceptance", joined)


class TestPhase22AADeliverables(unittest.TestCase):
    def test_deliverables_exist(self):
        out = ROOT / "tradingbot" / "ml" / "research" / "phase22aa"
        for name in (
            "dependency_graph.json",
            "call_chain.json",
            "threshold_map.json",
            "impact_radius.json",
            "architecture_boundary.json",
            "duplicate_logic.json",
            "phase22aa_final_report.json",
        ):
            path = out / name
            if not path.is_file():
                self.skipTest("run phase22aa run_investigation.py first")
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))

        final = json.loads((out / "phase22aa_final_report.json").read_text(encoding="utf-8"))
        self.assertFalse(final["freeze_in_acceptance_chain"])
        self.assertFalse(final["health_gate_in_acceptance_chain"])


if __name__ == "__main__":
    unittest.main()
