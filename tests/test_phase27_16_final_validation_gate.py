"""Phase 27.16 — Final broker/cost validation gate tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY
from tradingbot.backtest.phase27_15_cost_completeness_gate import (
    GATE_COMPONENTS,
    cost_ready_for_validation,
)
from tradingbot.backtest.phase27_16_final_validation_gate import (
    BLOCKED,
    PHASE2716_JSON,
    PHASE2716_MD,
    READY,
    REQUIRED_ARTIFACTS,
    decide_final_gate,
    infer_ready_from_partial_evidence,
    run_phase27_16_collection,
)
from tradingbot.config.live import PRIMARY_SYMBOL


def setUpModule() -> None:
    run_phase27_16_collection(Path(__file__).resolve().parents[1])


def _complete_components() -> dict:
    return {name: {"status": "COMPLETE"} for name in GATE_COMPONENTS}


def _complete_item(name: str = "ok") -> dict:
    return {
        "name": name,
        "value": "COMPLETE",
        "explicit": True,
        "ready_qualifying": True,
        "evidence": "unit",
    }


class TestPhase2716FinalValidationGate(unittest.TestCase):
    def test_artifact_valid_and_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.16")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["final_gate"], BLOCKED)
        self.assertGreater(len(payload["reasons"]), 0)
        self.assertEqual(payload["supporting_artifacts"], [])
        self.assertTrue(payload["not_strategy_approval"])
        self.assertTrue(payload["not_profitability_approval"])
        self.assertTrue(payload["not_real_money_authorization"])
        self.assertEqual(payload["operator_policy"]["decisions"], LOCKED_POLICY)
        self.assertEqual(PRIMARY_SYMBOL, "XAUUSD_i")

    def test_all_required_artifacts_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["required_inputs"]["all_present"])
        self.assertEqual(payload["required_inputs"]["missing"], [])
        for rel in REQUIRED_ARTIFACTS.values():
            self.assertTrue((root / rel).is_file(), rel)

    def test_checklist_is_explicit_but_not_ready(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        by_name = {c["name"]: c for c in payload["checklist"]}
        self.assertTrue(by_name["operator_policy_locked"]["explicit"])
        self.assertTrue(by_name["operator_policy_locked"]["ready_qualifying"])
        self.assertEqual(by_name["canonical_symbol"]["value"], "XAUUSD_i")
        self.assertEqual(by_name["dataset_mapping_policy"]["value"], "ONLY_WITH_EXPLICIT_DATASET_MAP")
        self.assertTrue(by_name["ev_eq_01"]["explicit"])
        self.assertEqual(by_name["ev_eq_01"]["value"], "NOT_PROVEN")
        self.assertFalse(by_name["ev_eq_01"]["ready_qualifying"])
        self.assertTrue(by_name["commission"]["explicit"])
        self.assertFalse(by_name["commission"]["ready_qualifying"])
        self.assertFalse(by_name["phase27_15_cost_ready"]["ready_qualifying"])
        self.assertFalse(any(c["name"] == "ev_eq_01" and c["ready_qualifying"] for c in payload["checklist"]))

    def test_partial_unknown_cannot_become_ready(self) -> None:
        self.assertEqual(infer_ready_from_partial_evidence("PARTIAL"), BLOCKED)
        self.assertEqual(infer_ready_from_partial_evidence("UNKNOWN"), BLOCKED)
        self.assertEqual(infer_ready_from_partial_evidence("BLOCKED"), BLOCKED)
        self.assertEqual(infer_ready_from_partial_evidence("NOT_PROVEN"), BLOCKED)
        self.assertEqual(infer_ready_from_partial_evidence("OBSERVED_ZERO_NOT_PROVEN"), BLOCKED)
        self.assertFalse(cost_ready_for_validation({}))
        partial = _complete_components()
        partial["spread"] = {"status": "PARTIAL"}
        self.assertFalse(cost_ready_for_validation(partial))

    def test_missing_artifact_and_implicit_status_block(self) -> None:
        implicit = [
            {
                "name": "commission",
                "value": None,
                "explicit": False,
                "ready_qualifying": False,
                "evidence": "missing",
            }
        ]
        decision = decide_final_gate(implicit, artifacts_present=False, components=_complete_components())
        self.assertEqual(decision["final_gate"], BLOCKED)
        self.assertIn("One or more required Phase 27 artifacts are missing", decision["reasons"])
        self.assertIn("commission is not explicit", decision["reasons"])

    def test_synthetic_complete_can_be_ready_current_cannot(self) -> None:
        synthetic = decide_final_gate(
            [_complete_item()],
            artifacts_present=True,
            components=_complete_components(),
        )
        self.assertEqual(synthetic["final_gate"], READY)
        degraded = decide_final_gate(
            [
                _complete_item(),
                {
                    "name": "commission",
                    "value": "PARTIAL",
                    "explicit": True,
                    "ready_qualifying": False,
                    "evidence": "unit",
                },
            ],
            artifacts_present=True,
            components=_complete_components(),
        )
        self.assertEqual(degraded["final_gate"], BLOCKED)
        self.assertTrue(any("commission=PARTIAL" in r for r in degraded["reasons"]))

    def test_and_gate_one_unknown_keeps_blocked(self) -> None:
        comps = _complete_components()
        comps["swap"] = {"status": "UNKNOWN"}
        decision = decide_final_gate(
            [_complete_item()],
            artifacts_present=True,
            components=comps,
        )
        self.assertEqual(decision["final_gate"], BLOCKED)
        self.assertTrue(any("component.swap=UNKNOWN" in r for r in decision["reasons"]))

    def test_blocker_matrix_precise(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        blockers = {row["blocker"]: row for row in payload["blocker_matrix"]}
        self.assertEqual(blockers["FINAL_GATE"]["status"], BLOCKED)
        self.assertIn("commission", blockers)
        self.assertIn("ev_eq_01", blockers)
        self.assertIn("historical_spread", blockers)
        self.assertNotIn("operator_policy_locked", blockers)
        self.assertNotIn("canonical_symbol", blockers)

    def test_gate_cannot_accidentally_become_permissive(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        perm = payload["permissive_regression"]
        self.assertTrue(perm["partial_cannot_become_ready"])
        self.assertTrue(perm["unknown_cannot_become_ready"])
        self.assertTrue(perm["one_partial_component_blocks_and"])
        self.assertTrue(perm["current_evidence_is_blocked"])
        self.assertNotEqual(payload["FINAL_GATE"], READY)
        self.assertFalse(payload["safety_confirmation"]["readiness_inferred_from_partial"])
        self.assertFalse(payload["safety_confirmation"]["gate_weakened"])

    def test_no_trading_or_phase28(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        for key in (
            "mt5_started",
            "backtest_run",
            "profitability_analysis_run",
            "strategy_optimization_run",
            "riskgate_modified",
            "execution_modified",
            "strategy_modified",
            "rr_modified",
            "ml_modified",
            "live_trading_configuration_modified",
            "phase_28_started",
        ):
            self.assertFalse(safety[key], key)
        self.assertEqual(payload["deferred"], ["Phase 28+ — not started"])

    def test_md_states_final_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        text = (root / PHASE2716_MD).read_text(encoding="utf-8")
        self.assertIn("FINAL_GATE = `BLOCKED`", text)
        self.assertIn("not** strategy approval", text)
        self.assertIn("STOP.", text)
        self.assertNotIn("FINAL_GATE = `READY_FOR_COST_AWARE_VALIDATION`", text)


if __name__ == "__main__":
    unittest.main()
