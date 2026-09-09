"""Phase 27.30 — Real-account historical slippage evidence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostAvailability, CostCompleteness, availability_blocks_completeness
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.slippage_policy import (
    IMPLEMENTATION_LABEL,
    POLICY,
    cost_completeness_from_modeled_slippage_only,
    modeled_is_not_realized,
    mt5_deviation_is_realized_slippage,
)
from tradingbot.backtest.phase27_30_slippage_evidence import (
    GRADE_A,
    GRADE_B,
    GRADE_D,
    NOT_IDENTIFIABLE,
    PHASE2714_JSON,
    PHASE2724_JSON,
    PHASE2730_JSON,
    PHASE2730_MD,
    REQUIRED_ARTIFACT_KEYS,
    UNKNOWN,
    classify_realized_grade,
    genuine_requested_price,
    pair_genuine_requested_vs_fill,
    price_open_is_not_requested_price,
    run_phase27_30_collection,
)


FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "Path('.env')",
)


def setUpModule() -> None:
    run_phase27_30_collection(Path(__file__).resolve().parents[1])


class TestPhase2730SlippageEvidence(unittest.TestCase):
    def test_price_open_and_entry_price_are_not_requested(self) -> None:
        self.assertTrue(price_open_is_not_requested_price("price_open"))
        self.assertTrue(price_open_is_not_requested_price("entry_price"))
        self.assertIsNone(
            genuine_requested_price(
                {
                    "requested_price": 4400.0,
                    "requested_price_source": "price_open",
                    "price": 4401.0,
                }
            )
        )
        self.assertIsNone(
            genuine_requested_price(
                {
                    "requested_price": 4154.17,
                    "requested_price_source": "entry_price",
                    "entry_price": 4154.17,
                }
            )
        )
        self.assertIsNone(
            genuine_requested_price(
                {"requested_price": 4414.32, "price": 4414.32}
            )
        )
        pending_pairs = pair_genuine_requested_vs_fill(
            [{"ticket": 2, "order": 11, "price": 4401.0, "type": 0, "time_utc": "2026-01-01T00:00:00Z"}],
            [{"ticket": 11, "type": 2, "price_open": 4400.0}],
        )
        self.assertEqual(pending_pairs, [])

    def test_zero_pairs_are_not_identifiable(self) -> None:
        self.assertEqual(classify_realized_grade(0), GRADE_D)
        self.assertEqual(classify_realized_grade(3), GRADE_B)
        self.assertEqual(classify_realized_grade(10), GRADE_A)
        pairs = pair_genuine_requested_vs_fill(
            [{"ticket": 1, "price": 4430.2, "requested_price": None, "type": 0}],
            [{"ticket": 10, "type": 0, "price_open": 4430.1}],
        )
        self.assertEqual(pairs, [])
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2730_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["sample_count"], 0)
        self.assertFalse(payload["identifiable"])
        self.assertIn(NOT_IDENTIFIABLE, payload["realized_slippage_status"])
        self.assertEqual(payload["evidence_grade"], GRADE_D)
        self.assertFalse(payload["derivable_historical_model"])
        self.assertGreaterEqual(payload.get("inspected_artifact_deal_count") or 0, 0)
        self.assertEqual(payload["account_type"], "REAL")
        self.assertEqual(payload["broker"], "LiteFinance Global LLC")
        self.assertEqual(payload["server"], "LiteFinance-MT5-Live")

    def test_modeled_proxy_is_not_realized_and_cannot_complete(self) -> None:
        self.assertTrue(modeled_is_not_realized())
        self.assertEqual(POLICY, "MODELED")
        self.assertEqual(IMPLEMENTATION_LABEL, "MODELED_PROXY")
        self.assertNotEqual(cost_completeness_from_modeled_slippage_only(), CostCompleteness.COMPLETE)
        self.assertTrue(availability_blocks_completeness(CostAvailability.MODELED_PROXY))
        self.assertFalse(mt5_deviation_is_realized_slippage())
        self.assertEqual(BacktestConfig().slippage_status, "MODELED_PROXY")
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2730_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["modeled_policy"], POLICY)
        self.assertEqual(payload["modeled_implementation"], IMPLEMENTATION_LABEL)
        self.assertFalse(payload["modeled_can_become_realized"])
        self.assertFalse(payload["modeled_can_satisfy_complete"])
        self.assertFalse(payload["complete_costs_satisfied"])
        self.assertFalse(payload["complete_costs_required_weakened"])
        self.assertFalse(payload["mt5_deviation_is_realized"])
        self.assertTrue(payload["implementation_audit"]["modeled_blocks_complete"])

    def test_datasets_and_prior_artifacts_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2730_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["datasets_changed"])
        self.assertEqual(payload["canonical_fingerprint_before"], payload["canonical_fingerprint_after"])
        self.assertEqual(payload["phase27_14_fingerprint_before"], payload["phase27_14_fingerprint_after"])
        self.assertEqual(payload["phase27_24_fingerprint_before"], payload["phase27_24_fingerprint_after"])
        self.assertTrue(payload["phase27_14_preserved"])
        self.assertTrue(payload["phase27_24_preserved"])
        self.assertFalse(payload["production_code_changed"])
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertTrue((root / PHASE2714_JSON).is_file())
        self.assertTrue((root / PHASE2724_JSON).is_file())

    def test_artifact_schema_and_no_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2730_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        lowered = raw.lower()
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, lowered)
        self.assertEqual(payload["phase"], "27.30")
        self.assertIn(payload["status"], {"PASS", "PASS_WITH_DEFERRAL"})
        self.assertIn("STOP after Phase 27.30", (root / PHASE2730_MD).read_text(encoding="utf-8"))
        src = (root / "tradingbot" / "backtest" / "phase27_30_slippage_evidence.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        self.assertFalse(payload["safety_confirmation"]["price_open_used_as_requested"])
        self.assertFalse(payload["safety_confirmation"]["modeled_labeled_realized"])
        self.assertFalse(payload["safety_confirmation"]["phase_27_31_started"])

    def test_explicit_requested_vs_fill_is_countable(self) -> None:
        pairs = pair_genuine_requested_vs_fill(
            [
                {
                    "ticket": 99,
                    "order": 88,
                    "price": 4401.5,
                    "requested_price": 4400.0,
                    "requested_price_source": "deal.requested_price",
                    "type": 0,
                    "volume": 0.01,
                    "time_utc": "2026-08-01T12:00:00Z",
                    "symbol": "XAUUSD_i",
                }
            ],
            [
                {
                    "ticket": 88,
                    "type": 2,
                    "requested_price": 4400.0,
                    "volume_initial": 0.01,
                }
            ],
            point=0.01,
            tick_size=0.01,
        )
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["signed_slippage"], 1.5)
        self.assertEqual(pairs[0]["absolute_slippage"], 1.5)
        self.assertEqual(pairs[0]["points"], 150.0)
        self.assertEqual(UNKNOWN, "UNKNOWN")
