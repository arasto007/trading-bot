"""Phase 26M — Operator risk-budget policy audit tests (document/policy only)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase26m_operator_risk_budget_audit import (
    PHASE26M_JSON,
    VALID_CLASSIFICATIONS,
    run_phase26m_collection,
)

FORBIDDEN_INTENT_CLAIMS = (
    "production target is $1000",
    "operator requires $1000",
    "must trade on micro",
    "minimum viable account is",
    "recommend changing risk",
    "recommend new balance",
)


def setUpModule() -> None:
    run_phase26m_collection(Path(__file__).resolve().parents[1])


class TestPhase26MArtifact(unittest.TestCase):
    def test_artifact_exists_and_valid_json(self) -> None:
        root = Path(__file__).resolve().parents[1]
        path = root / PHASE26M_JSON
        self.assertTrue(path.is_file(), msg=f"missing {PHASE26M_JSON}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "26M")
        self.assertIn("operator_intent", payload)
        self.assertIn("policy_alignment", payload)

    def test_classification_values_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26M_JSON).read_text(encoding="utf-8"))
        for key in ("initial_balance", "risk_per_trade", "minimum_executable_lot", "micro_account_support"):
            cls = payload["operator_intent"][key]["classification"]
            self.assertIn(cls, VALID_CLASSIFICATIONS, msg=f"{key}={cls}")

    def test_documentation_alignment_not_false_supported(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26M_JSON).read_text(encoding="utf-8"))
        alignment = payload["policy_alignment"]["documentation_alignment"]
        self.assertIn(alignment, {"SUPPORTED", "UNSUPPORTED", "UNKNOWN", "CONTRADICTED"})
        if payload["operator_intent"]["initial_balance"]["classification"] in {"B", "D"}:
            self.assertNotEqual(alignment, "SUPPORTED")

    def test_unknown_intent_explicit_when_balance_undocumented(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26M_JSON).read_text(encoding="utf-8"))
        bal_cls = payload["operator_intent"]["initial_balance"]["classification"]
        self.assertIn(bal_cls, {"B", "D"})
        rec = payload["recommendation"].lower()
        self.assertIn("unknown", rec)
        self.assertIn("no policy change", rec)

    def test_conclusions_do_not_invent_operator_intent(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26M_JSON).read_text(encoding="utf-8"))
        blob = json.dumps(payload).lower()
        for phrase in FORBIDDEN_INTENT_CLAIMS:
            self.assertNotIn(phrase, blob, msg=f"forbidden claim: {phrase}")


class TestPhase26MSafety(unittest.TestCase):
    def test_no_production_code_changed_flag(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26M_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["production_changes"])
        self.assertFalse(payload["policy_changed"])
        self.assertFalse(payload["safety"]["PRODUCTION_CODE_CHANGED"])
        self.assertFalse(payload["safety"]["CONFIGURATION_CHANGED"])

    def test_no_mt5_or_bot_interaction(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26M_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["mt5_connected"])
        self.assertFalse(payload["bot_started"])
        self.assertFalse(payload["orders_sent"])
        self.assertFalse(payload["safety"]["MT5_CONNECTED"])
        self.assertFalse(payload["safety"]["BACKTEST_EXECUTED"])
        self.assertFalse(payload["safety"]["FULL_ENGINE_EXECUTED"])

    def test_risk_per_trade_documented_not_invented(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26M_JSON).read_text(encoding="utf-8"))
        risk = payload["operator_intent"]["risk_per_trade"]
        self.assertEqual(risk["classification"], "A")
        self.assertIn("0.005", risk["value"])


class TestPhase26MCollection(unittest.TestCase):
    def test_collection_regenerates_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        report = run_phase26m_collection(root)
        self.assertEqual(report["phase"], "26M")
        self.assertEqual(report["final_decision"], "PASS_WITH_DEFERRAL")
        self.assertTrue((root / PHASE26M_JSON).is_file())

    def test_case_2_or_unknown_alignment(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE26M_JSON).read_text(encoding="utf-8"))
        self.assertIn(payload["policy_alignment"]["documentation_alignment"], {"UNKNOWN", "UNSUPPORTED"})
        self.assertIn("CASE", payload["policy_alignment"]["case"])


if __name__ == "__main__":
    unittest.main()
