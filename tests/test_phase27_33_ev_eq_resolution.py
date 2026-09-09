"""Phase 27.33 — EV-EQ-01 resolution tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.dataset_contract import STATUS_EXPLICIT_MAP, STATUS_MATCH, STATUS_MISSING_MAP
from tradingbot.backtest.phase27_8_policy_lock import LOCKED_POLICY
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion
from tradingbot.backtest.phase27_33_ev_eq_resolution import (
    PHASE2733_JSON,
    PHASE2733_MD,
    REQUIRED_ARTIFACT_KEYS,
    STATE_A,
    STATE_B,
    STATE_C,
    audit_contract_behavior,
    classify_ev_eq_resolution,
    compare_economics,
    policy_authorizes_silent_mapping,
    run_phase27_33_collection,
)


FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase27_33_collection(Path(__file__).resolve().parents[1])


class TestPhase2733EvEqResolution(unittest.TestCase):
    def test_absence_is_not_proven_not_disproven(self) -> None:
        empty = {"matching_count": 0, "differing_count": 0, "unknown_count": 18}
        absent = classify_ev_eq_resolution(
            xauusd_exists=False,
            xauusd_i_exists=True,
            same_real_terminal=True,
            comparison=empty,
            policy_state_b_locked=True,
        )
        self.assertEqual(absent["classification"], EquivalenceConclusion.NOT_PROVEN.value)
        self.assertNotEqual(absent["classification"], EquivalenceConclusion.DISPROVEN.value)
        self.assertEqual(absent["state"], STATE_B)
        self.assertFalse(absent["proven"])
        mismatch = classify_ev_eq_resolution(
            xauusd_exists=True,
            xauusd_i_exists=True,
            same_real_terminal=True,
            comparison={"matching_count": 10, "differing_count": 1, "unknown_count": 0},
            policy_state_b_locked=True,
        )
        self.assertEqual(mismatch["classification"], EquivalenceConclusion.DISPROVEN.value)
        match = classify_ev_eq_resolution(
            xauusd_exists=True,
            xauusd_i_exists=True,
            same_real_terminal=True,
            comparison={"matching_count": 18, "differing_count": 0, "unknown_count": 0},
            policy_state_b_locked=True,
        )
        self.assertEqual(match["classification"], EquivalenceConclusion.PROVEN.value)
        self.assertEqual(match["state"], STATE_A)
        no_policy = classify_ev_eq_resolution(
            xauusd_exists=False,
            xauusd_i_exists=True,
            same_real_terminal=True,
            comparison=empty,
            policy_state_b_locked=False,
        )
        self.assertEqual(no_policy["state"], STATE_C)

    def test_similar_fields_do_not_invent_xauusd(self) -> None:
        cmp_ = compare_economics(
            {"existence": "NO"},
            {"trade_contract_size": 100.0, "trade_tick_value": 1.0, "existence": "YES"},
        )
        self.assertEqual(cmp_["matching_count"], 0)
        self.assertEqual(cmp_["differing_count"], 0)
        self.assertGreater(cmp_["unknown_count"], 0)
        self.assertFalse(policy_authorizes_silent_mapping())
        self.assertEqual(LOCKED_POLICY["DECISION_2"], "ONLY_WITH_EXPLICIT_DATASET_MAP")

    def test_contract_and_inventory(self) -> None:
        contract = audit_contract_behavior()
        self.assertEqual(contract["missing_map"], STATUS_MISSING_MAP)
        self.assertEqual(contract["valid_explicit_map"], STATUS_EXPLICIT_MAP)
        self.assertEqual(contract["direct_XAUUSD_i"], STATUS_MATCH)
        self.assertFalse(contract["silent_conversion"])
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2733_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["contract_behavior"]["missing_map"], "BLOCK")
        self.assertEqual(payload["contract_behavior"]["valid_explicit_map"], "ALLOWED")
        self.assertEqual(payload["contract_behavior"]["direct_XAUUSD_i"], "ALLOWED")
        self.assertFalse(payload["contract_behavior"]["silent_conversion"])
        self.assertEqual(payload["dataset_binding"]["missing_map"], 30)
        self.assertEqual(payload["dataset_binding"]["direct_XAUUSD_i"], 2)
        self.assertEqual(payload["dataset_binding"]["explicit_mapped"], 0)
        self.assertFalse(payload["maps_inserted"])
        self.assertFalse(payload["XAUUSD"]["exists"])
        self.assertTrue(payload["XAUUSD_i"]["exists"])
        self.assertEqual(payload["ev_eq_01"]["classification"], EquivalenceConclusion.NOT_PROVEN.value)
        self.assertEqual(payload["selected_state"], STATE_B)
        self.assertFalse(payload["ev_eq_01"]["proven"])

    def test_immutability_and_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2733_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["datasets_changed"])
        self.assertEqual(payload["canonical_fingerprint_before"], payload["canonical_fingerprint_after"])
        self.assertEqual(
            payload["canonical_fingerprint_after"],
            "ab3e25bab0c6d6689d6654317264cc7774e1b49f88df907a3ea1bd1ade313ed5",
        )
        self.assertFalse(payload["production_code_changed"])
        self.assertEqual(payload["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["cost_completeness"], "BLOCKED")
        self.assertEqual(payload["production_readiness"], "BLOCKED")
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")

    def test_artifact_schema_and_no_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2733_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        lowered = raw.lower()
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, lowered)
        self.assertEqual(payload["phase"], "27.33")
        self.assertIn(payload["status"], {"PASS", "PASS_WITH_DEFERRAL"})
        self.assertIn("STOP after Phase 27.33", (root / PHASE2733_MD).read_text(encoding="utf-8"))
        src = (root / "tradingbot" / "backtest" / "phase27_33_ev_eq_resolution.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        self.assertFalse(payload["safety_confirmation"]["xauusd_economics_invented"])
        self.assertFalse(payload["safety_confirmation"]["phase_27_34_started"])
        self.assertEqual(payload["account_type"], "REAL")
        self.assertEqual(payload["broker"], "LiteFinance Global LLC")
        self.assertEqual(payload["server"], "LiteFinance-MT5-Live")
