"""Phase 27.29 — Real-account swap evidence tests."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_model import CostCompleteness
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.swap_policy import (
    POLICY,
    broker_rate_only_is_not_historical,
    cost_completeness_from_broker_rates_only,
    record_broker_swap_rates,
    realized_zero_is_not_verified_zero,
)
from tradingbot.backtest.phase27_29_swap_evidence import (
    GRADE_C,
    GRADE_D,
    GRADE_E,
    NOT_IDENTIFIABLE,
    PHASE2729_JSON,
    PHASE2729_MD,
    REQUIRED_ARTIFACT_KEYS,
    classify_swap_evidence_grade,
    crossed_weekday,
    derive_historical_swap_rate,
    is_overnight_hold,
    parse_utc,
    run_phase27_29_collection,
)


FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")


def setUpModule() -> None:
    run_phase27_29_collection(Path(__file__).resolve().parents[1])


class TestPhase2729SwapEvidence(unittest.TestCase):
    def test_current_broker_swap_can_be_recorded_but_is_not_historical(self) -> None:
        evidence = record_broker_swap_rates(
            {"swap_long": -89.136, "swap_short": 3.45, "swap_rollover3days": 3},
            symbol="XAUUSD_i",
            source="unit_test",
        )
        self.assertEqual(evidence.swap_long, -89.136)
        self.assertEqual(evidence.swap_short, 3.45)
        self.assertEqual(evidence.triple_swap_weekday, "Wednesday")
        self.assertEqual(evidence.evidence_class, POLICY)
        self.assertEqual(evidence.historical_swap_series, "UNKNOWN")
        self.assertTrue(broker_rate_only_is_not_historical(evidence))
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2729_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["current_rate_is_historical"])
        self.assertFalse(payload["historical_swap_proven"])

    def test_zero_realized_swap_does_not_prove_historical_zero(self) -> None:
        self.assertTrue(realized_zero_is_not_verified_zero([0.0] * 50))
        self.assertEqual(
            classify_swap_evidence_grade(
                current_rates_proven=False,
                historical_account_applicable=False,
                historical_product_specific=False,
                overnight_count=0,
                rollover_crossing_count=0,
                zero_swap_count=50,
                nonzero_swap_count=0,
            ),
            GRADE_D,
        )
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2729_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["deal_forensics"]["proves_historical_zero"])
        self.assertFalse(payload["safety_confirmation"]["zero_treated_as_historical_zero"])

    def test_rollover_crossing_and_overnight_detection(self) -> None:
        short_start = parse_utc("2026-08-10T15:00:00Z")
        short_end = parse_utc("2026-08-10T15:10:00Z")
        self.assertFalse(is_overnight_hold(short_start, short_end))
        overnight = is_overnight_hold(
            datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc),
            datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(overnight)
        wed = crossed_weekday(
            datetime(2026, 8, 11, 20, 0, tzinfo=timezone.utc),  # Tuesday
            datetime(2026, 8, 12, 22, 0, tzinfo=timezone.utc),  # Wednesday
            2,
        )
        self.assertTrue(wed)
        self.assertFalse(is_overnight_hold(None, short_end))

    def test_insufficient_overnight_and_missing_variables_not_identifiable(self) -> None:
        self.assertEqual(
            classify_swap_evidence_grade(
                current_rates_proven=False,
                historical_account_applicable=False,
                historical_product_specific=False,
                overnight_count=0,
                rollover_crossing_count=0,
                zero_swap_count=0,
                nonzero_swap_count=0,
            ),
            GRADE_E,
        )
        derived = derive_historical_swap_rate(
            realized_swap=0.0,
            volume=None,
            financing_days=None,
            rollover_multiplier=None,
            duration_sufficient=False,
            applicability_established=False,
        )
        self.assertFalse(derived["identifiable"])
        self.assertEqual(derived["status"], NOT_IDENTIFIABLE)
        self.assertIn("volume", derived["missing"])
        payload = json.loads((Path(__file__).resolve().parents[1] / PHASE2729_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["historical_rate_identifiable"])
        self.assertIsNone(payload["historical_rate"])

    def test_broker_rate_only_does_not_complete_and_datasets_unchanged(self) -> None:
        self.assertNotEqual(cost_completeness_from_broker_rates_only(), CostCompleteness.COMPLETE)
        self.assertEqual(BacktestConfig().swap_status, "UNKNOWN")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2729_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["implementation_audit"]["broker_rate_only_blocks_complete"])
        self.assertFalse(payload["implementation_audit"]["current_rate_can_become_historical"])
        self.assertFalse(payload["datasets_changed"])
        self.assertEqual(payload["canonical_fingerprint_before"], payload["canonical_fingerprint_after"])
        self.assertFalse(payload["complete_costs_required_weakened"])
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        if payload["current_broker_rate_proven"]:
            self.assertEqual(payload["evidence_grade"], GRADE_C)

    def test_artifact_schema_and_no_credentials(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2729_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        lowered = raw.lower()
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, lowered)
        self.assertEqual(payload["phase"], "27.29")
        self.assertIn("STOP after Phase 27.29", (root / PHASE2729_MD).read_text(encoding="utf-8"))
        src = (root / "tradingbot" / "backtest" / "swap_policy.py").read_text(encoding="utf-8")
        self.assertNotIn("symbol_select(", src)
        self.assertNotIn("order_send(", src)
        self.assertNotIn("load_dotenv", src)
