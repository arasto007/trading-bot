"""Phase 27.9 — fresh Real read-only broker evidence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tradingbot.backtest.phase27_9_real_broker_evidence import (
    PHASE279_JSON,
    PHASE279_MD,
    classify_session,
    evaluate_ev_eq_01,
    inspect_symbol_readonly,
    login_identity_hash,
    run_phase27_9_collection,
    trade_mode_label,
)
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion


def setUpModule() -> None:
    run_phase27_9_collection(Path(__file__).resolve().parents[1])


class TestPhase279RealBrokerEvidence(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE279_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.9")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["canonical_symbol_policy"], "XAUUSD_i")
        self.assertIn(payload["evidence_status"], {
            "MT5_NOT_ATTACHED",
            "DEMO_ATTACHED_NOT_REAL",
            "REAL_COLLECTED",
            "ATTACHED_ENVIRONMENT_UNKNOWN",
        })

    def test_demo_is_not_labeled_real(self) -> None:
        status, collection = classify_session(True, "DEMO")
        self.assertEqual(status, "DEMO_ATTACHED_NOT_REAL")
        self.assertEqual(collection, "STOPPED_DEMO_ATTACHED")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE279_JSON).read_text(encoding="utf-8"))
        if payload["account_environment"] == "DEMO":
            self.assertFalse(payload["labeled_as_real"])
            self.assertEqual(payload["real_symbol_collection"], "STOPPED_DEMO_ATTACHED")
            self.assertEqual(payload["symbols"]["XAUUSD_i"]["existence"], "UNKNOWN")

    def test_login_identity_not_raw(self) -> None:
        token = login_identity_hash(12345678)
        self.assertTrue(token.startswith("sha256:"))
        self.assertNotIn("12345678", token)
        self.assertEqual(login_identity_hash(None), "UNKNOWN")

    def test_trade_mode_labels(self) -> None:
        self.assertEqual(trade_mode_label(2), "REAL")
        self.assertEqual(trade_mode_label(0), "DEMO")
        self.assertEqual(trade_mode_label(1), "CONTEST")
        self.assertEqual(trade_mode_label(None), "UNKNOWN")

    def test_ev_eq_01_not_inferred_from_one_symbol(self) -> None:
        xaui = {
            "symbol": "XAUUSD_i",
            "existence": "YES",
            "visibility": "YES",
            "digits": 2,
            "point": 0.01,
            "contract_size": 100.0,
            "tick_size": 0.01,
            "tick_value": 1.0,
            "tick_value_profit": 1.0,
            "tick_value_loss": 1.0,
            "volume_min": 0.01,
            "volume_max": 100.0,
            "volume_step": 0.01,
            "stops_level": 0,
            "freeze_level": 0,
            "filling_mode": 1,
            "execution_mode": 2,
            "calc_mode": 2,
            "swap_long": -89.136,
            "swap_short": 3.45,
            "rollover3days": 3,
        }
        xau = {**xaui, "symbol": "XAUUSD", "existence": "NO"}
        ev = evaluate_ev_eq_01(
            xau,
            xaui,
            environment="REAL",
            server="LiteFinance-MT5-Live",
            artifact=PHASE279_JSON,
            timestamp="2026-09-06T00:00:00Z",
        )
        self.assertEqual(ev["status"], EquivalenceConclusion.NOT_PROVEN.value)
        self.assertFalse(ev["inferred"])
        self.assertFalse(ev["both_symbols_present"])

    def test_ev_eq_01_not_evaluated_on_demo(self) -> None:
        ev = evaluate_ev_eq_01(
            None,
            None,
            environment="DEMO",
            server="LiteFinance-MT5-Demo",
            artifact=PHASE279_JSON,
            timestamp="2026-09-06T00:00:00Z",
        )
        self.assertEqual(ev["status"], EquivalenceConclusion.NOT_PROVEN.value)
        self.assertFalse(ev["inferred"])

    def test_inspect_symbol_no_select_and_unknown_fields(self) -> None:
        mt5 = MagicMock()
        mt5.symbol_info.return_value = None
        mt5.symbol_select = MagicMock()
        row = inspect_symbol_readonly(mt5, "XAUUSD")
        mt5.symbol_select.assert_not_called()
        self.assertEqual(row["existence"], "NO")
        self.assertEqual(row["digits"], "UNKNOWN")
        self.assertEqual(row["bid"], "UNKNOWN")

    def test_no_symbol_select_or_env_in_source(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_9_real_broker_evidence.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("symbol_select(", src)
        self.assertNotIn("load_dotenv", src)
        self.assertNotIn('Path(".env")', src)
        self.assertNotIn("order_send", src)

    def test_credentials_absent_from_artifact(self) -> None:
        root = Path(__file__).resolve().parents[1]
        blob = (root / PHASE279_JSON).read_text(encoding="utf-8").lower()
        for key in ("\"login\"", "password", "mt5_password", "api_key"):
            self.assertNotIn(key, blob)
        payload = json.loads((root / PHASE279_JSON).read_text(encoding="utf-8"))
        self.assertIn("login_identity", payload["account"])
        self.assertNotIn("login", payload["account"])

    def test_safety_and_md(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE279_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["symbol_select_called"])
        self.assertFalse(safety["orders_sent"])
        self.assertFalse(safety["env_file_read"])
        self.assertFalse(safety["env_file_written"])
        self.assertFalse(safety["demo_mislabeled_as_real"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")
        self.assertEqual(payload["attach_attempt"]["attempt_count"], 1)
        text = (root / PHASE279_MD).read_text(encoding="utf-8")
        self.assertIn("EV-EQ-01", text)
        self.assertIn("STOP after Phase 27.9", text)
        self.assertIn("UNKNOWN", text)


if __name__ == "__main__":
    unittest.main()
