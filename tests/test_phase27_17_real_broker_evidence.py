"""Phase 27.17 — fresh Real read-only broker evidence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_17_real_broker_evidence import (
    PHASE2717_JSON,
    PHASE2717_MD,
    STALE_REAL_JSON,
    classify_session,
    commission_evidence_from_account,
    evaluate_ev_eq_01,
    inspect_symbol_readonly,
    operator_blocker_for,
    run_phase27_17_collection,
    unknown_symbol_row,
)
from tradingbot.backtest.phase27_9_real_broker_evidence import classify_session as classify_27_9
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion


def setUpModule() -> None:
    run_phase27_17_collection(Path(__file__).resolve().parents[1])


class TestPhase2717RealBrokerEvidence(unittest.TestCase):
    def test_artifact_required_fields(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2717_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.17")
        self.assertEqual(payload["status"], "PASS")
        for key in (
            "attach_status",
            "account_environment",
            "broker",
            "server",
            "terminal_build",
            "fresh_timestamp",
            "XAUUSD_status",
            "XAUUSD_i_status",
            "economics",
            "ev_eq_01",
            "commission_evidence_status",
            "stale_vs_fresh",
            "safety_actions_performed",
            "safety_actions_not_performed",
        ):
            self.assertIn(key, payload)
        self.assertIn(
            payload["attach_status"],
            {
                "MT5_NOT_ATTACHED",
                "DEMO_ATTACHED_NOT_REAL",
                "REAL_COLLECTED",
                "ATTACHED_ENVIRONMENT_UNKNOWN",
            },
        )
        self.assertEqual(payload["canonical_symbol_policy"], "XAUUSD_i")
        self.assertEqual(payload["operator_policy"]["DECISION_1"], "XAUUSD_i")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")

    def test_demo_not_labeled_real_and_does_not_overwrite_stale(self) -> None:
        status, collection = classify_session(True, "DEMO")
        self.assertEqual(status, "DEMO_ATTACHED_NOT_REAL")
        self.assertEqual(collection, "STOPPED_DEMO_ATTACHED")
        self.assertEqual(classify_27_9(True, "DEMO"), (status, collection))
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2717_JSON).read_text(encoding="utf-8"))
        stale = payload["stale_vs_fresh"]
        self.assertFalse(stale["demo_used_as_real"])
        self.assertFalse(stale["stale_real_overwritten"])
        self.assertTrue(stale["stale_real_artifact_untouched"])
        self.assertEqual(stale["stale_real"]["artifact"], STALE_REAL_JSON)
        if payload["account_environment"] == "DEMO":
            self.assertFalse(payload["labeled_as_real"])
            self.assertEqual(payload["real_symbol_collection"], "STOPPED_DEMO_ATTACHED")
            self.assertEqual(payload["symbols"]["XAUUSD_i"]["existence"], "UNKNOWN")
            self.assertEqual(payload["XAUUSD_i_status"]["existence"], "UNKNOWN")

    def test_not_attached_is_blocked_pending_operator(self) -> None:
        self.assertEqual(operator_blocker_for("MT5_NOT_ATTACHED"), "BLOCKED_PENDING_OPERATOR")
        self.assertEqual(operator_blocker_for("DEMO_ATTACHED_NOT_REAL"), "BLOCKED_PENDING_OPERATOR")
        self.assertEqual(operator_blocker_for("REAL_COLLECTED"), "NONE")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2717_JSON).read_text(encoding="utf-8"))
        if payload["attach_status"] == "MT5_NOT_ATTACHED":
            self.assertEqual(payload["operator_blocker"], "BLOCKED_PENDING_OPERATOR")
            self.assertEqual(payload["real_symbol_collection"], "NOT_ATTEMPTED")

    def test_commission_not_verified_schedule(self) -> None:
        comm = commission_evidence_from_account(
            {
                "broker": "LiteFinance",
                "server": "LiteFinance-MT5-Live",
                "trade_mode_label": "REAL",
                "currency": "USD",
                "account_product_type": "UNKNOWN",
            },
            collected_real=True,
        )
        self.assertFalse(comm["verified_schedule_found"])
        self.assertFalse(comm["verified_schedule_claimed"])
        self.assertFalse(comm["applicability_established"])
        self.assertIn("basis", comm["missing_applicability_fields"])
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2717_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["commission_evidence_status"]["verified_schedule_found"])
        self.assertFalse(payload["commission_evidence_status"]["verified_schedule_claimed"])

    def test_ev_eq_01_not_inferred_from_absence_or_demo(self) -> None:
        xaui = unknown_symbol_row("XAUUSD_i")
        xaui.update({"existence": "YES", "visibility": "YES", "digits": 2, "point": 0.01, "trade_contract_size": 100.0})
        xau = unknown_symbol_row("XAUUSD")
        xau["existence"] = "NO"
        ev = evaluate_ev_eq_01(
            xau,
            xaui,
            environment="REAL",
            server="LiteFinance-MT5-Live",
            artifact=PHASE2717_JSON,
            timestamp="2026-09-06T00:00:00Z",
        )
        self.assertEqual(ev["status"], EquivalenceConclusion.NOT_PROVEN.value)
        self.assertFalse(ev["inferred"])
        self.assertFalse(ev["both_symbols_present"])
        self.assertTrue(ev["similar_economics_not_sufficient"])
        ev_demo = evaluate_ev_eq_01(
            None, None, environment="DEMO", server="LiteFinance-MT5-Demo",
            artifact=PHASE2717_JSON, timestamp="2026-09-06T00:00:00Z",
        )
        self.assertEqual(ev_demo["status"], EquivalenceConclusion.NOT_PROVEN.value)

    def test_inspect_symbol_no_select(self) -> None:
        mt5 = MagicMock()
        mt5.symbol_info.return_value = None
        mt5.symbol_select = MagicMock()
        row = inspect_symbol_readonly(mt5, "XAUUSD")
        mt5.symbol_select.assert_not_called()
        self.assertEqual(row["existence"], "NO")
        self.assertEqual(row["trade_contract_size"], "UNKNOWN")
        self.assertEqual(row["currency_base"], "UNKNOWN")
        self.assertEqual(row["spread"], "UNKNOWN")

    def test_no_symbol_select_or_env_in_source(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_17_real_broker_evidence.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("symbol_select(", src)
        self.assertNotIn("load_dotenv", src)
        self.assertNotIn('Path(".env")', src)
        self.assertNotIn("order_send(", src)
        self.assertNotIn('STALE_REAL_JSON).write', src)

    def test_credentials_absent_and_stale_file_untouched(self) -> None:
        root = Path(__file__).resolve().parents[1]
        blob = (root / PHASE2717_JSON).read_text(encoding="utf-8").lower()
        for key in ('"login"', "password", "mt5_password", "api_key"):
            self.assertNotIn(key, blob)
        payload = json.loads((root / PHASE2717_JSON).read_text(encoding="utf-8"))
        self.assertNotIn("login", payload["account"])
        self.assertTrue((root / STALE_REAL_JSON).is_file())

    def test_final_gate_not_weakened(self) -> None:
        root = Path(__file__).resolve().parents[1]
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        p17 = json.loads((root / PHASE2717_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(p17["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertEqual(p17["production_readiness"], "BLOCKED")
        self.assertFalse(p17["safety_confirmation"]["phase_27_18_started"])

    def test_safety_and_md(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2717_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["mt5_restarted"])
        self.assertFalse(safety["symbol_select_called"])
        self.assertFalse(safety["orders_sent"])
        self.assertFalse(safety["env_file_read"])
        self.assertFalse(safety["demo_mislabeled_as_real"])
        self.assertFalse(safety["verified_schedule_claimed"])
        self.assertEqual(payload["attach_attempt"]["attempt_count"], 1)
        self.assertIn("start MT5", payload["safety_actions_not_performed"])
        self.assertIn("overwrite stale Real artifact", payload["safety_actions_not_performed"])
        text = (root / PHASE2717_MD).read_text(encoding="utf-8")
        self.assertIn("EV-EQ-01", text)
        self.assertIn("STOP after Phase 27.17", text)
        self.assertIn("FINAL_GATE remains", text)


if __name__ == "__main__":
    unittest.main()
