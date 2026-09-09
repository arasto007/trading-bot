"""Phase 27.24 — realized swap / slippage / execution forensic tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_24_execution_cost_forensics import (
    BLOCKED,
    BROKER_RATE_ONLY,
    HISTORICAL,
    PARTIAL,
    PHASE2724_JSON,
    PHASE2724_MD,
    UNKNOWN,
    classify_execution,
    classify_slippage_evidence,
    classify_swap_treatment,
    entry_price_is_not_requested_price,
    genuine_requested_price,
    realized_slippage_pairs,
    run_phase27_24_collection,
)
from tradingbot.backtest.slippage_policy import mt5_deviation_is_realized_slippage
from tradingbot.backtest.swap_policy import verified_zero_swap_from_realized


FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "Path('.env')",
)


def setUpModule() -> None:
    run_phase27_24_collection(Path(__file__).resolve().parents[1])


class TestPhase2724ExecutionCostForensics(unittest.TestCase):
    def test_artifact_and_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2724_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.24")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["locked_policy"]["swap"], BROKER_RATE_ONLY)
        self.assertEqual(payload["locked_policy"]["slippage"], "MODELED")
        self.assertEqual(payload["locked_policy"]["validation"], "COMPLETE_COSTS_REQUIRED")
        self.assertNotEqual(payload["swap"]["classification_treatment"], HISTORICAL)
        self.assertFalse(payload["swap"]["realized_zero_proves_verified_zero"])

    def test_zero_swap_is_not_verified_zero_or_historical(self) -> None:
        self.assertFalse(verified_zero_swap_from_realized([0.0] * 50))
        self.assertEqual(
            classify_swap_treatment(has_broker_rates=True, has_historical_series=False),
            BROKER_RATE_ONLY,
        )
        self.assertEqual(
            classify_swap_treatment(has_broker_rates=False, has_historical_series=False),
            UNKNOWN,
        )
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2724_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["swap"]["historical_swap_series"], UNKNOWN)
        self.assertFalse(payload["swap"]["series_synthesized"])
        self.assertFalse(payload["swap"]["sufficient_for_historical_behavior"])

    def test_entry_price_and_market_price_open_are_not_requested(self) -> None:
        self.assertTrue(
            entry_price_is_not_requested_price(
                {"entry_price": 4154.17, "actual_fill_price": 4154.17, "requested_price": "NOT AVAILABLE"}
            )
        )
        self.assertIsNone(genuine_requested_price({"type": 0, "price_open": 4430.10}))
        self.assertIsNone(genuine_requested_price({"type": 1, "price_open": 0.0}))
        self.assertEqual(genuine_requested_price({"type": 2, "price_open": 4400.0}), 4400.0)
        market_pairs = realized_slippage_pairs(
            [{"ticket": 1, "order": 10, "price": 4430.2, "type": 0, "time_utc": "2026-01-01T00:00:00Z"}],
            [{"ticket": 10, "type": 0, "price_open": 4430.1}],
        )
        self.assertEqual(market_pairs, [])
        pending_pairs = realized_slippage_pairs(
            [{"ticket": 2, "order": 11, "price": 4401.0, "type": 0, "time_utc": "2026-01-01T00:00:00Z", "symbol": "XAUUSD_i", "volume": 0.01}],
            [{"ticket": 11, "type": 2, "price_open": 4400.0}],
        )
        self.assertEqual(len(pending_pairs), 1)
        self.assertEqual(pending_pairs[0]["requested_source"], "pending_order.price_open")

    def test_no_genuine_pairs_means_unknown_slippage(self) -> None:
        self.assertEqual(classify_slippage_evidence(0), UNKNOWN)
        self.assertEqual(classify_slippage_evidence(3), PARTIAL)
        self.assertNotEqual(classify_slippage_evidence(0), "PROVEN")
        self.assertFalse(mt5_deviation_is_realized_slippage())
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2724_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["slippage"]["entry_price_used_as_requested"])
        self.assertFalse(payload["slippage"]["deviation_used_as_slippage"])
        self.assertFalse(payload["slippage"]["modeled_used_as_realized"])
        if payload["slippage"]["realized_sample_count"] == 0:
            self.assertEqual(payload["final_output"]["realized_slippage"], UNKNOWN)

    def test_execution_not_from_simulated_broker(self) -> None:
        self.assertEqual(
            classify_execution(
                gold_deals=0, gold_orders=0, filled=0, partials=0, rejected=0, from_simulation=True
            ),
            UNKNOWN,
        )
        self.assertEqual(
            classify_execution(
                gold_deals=10, gold_orders=4, filled=4, partials=0, rejected=0, from_simulation=False
            ),
            PARTIAL,
        )
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2724_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["execution"]["simulated_broker_is_not_evidence"])
        self.assertFalse(payload["execution"]["simulated_broker_used"])
        self.assertEqual(payload["execution"]["gate_model_unchanged"]["status"], UNKNOWN)
        self.assertIn(payload["final_output"]["execution"], (PARTIAL, UNKNOWN, "REALIZED_EXECUTION_EVIDENCE"))
        self.assertNotEqual(payload["final_output"]["execution"], "COMPLETE")

    def test_gate_not_changed(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2724_JSON).read_text(encoding="utf-8"))
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["cost_gate_impact"]["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertFalse(payload["cost_gate_impact"]["gate_changed"])
        self.assertFalse(payload["cost_gate_impact"]["complete_costs_required_weakened"])
        self.assertFalse(payload["cost_gate_impact"]["swap_blocker_improved"])
        self.assertFalse(payload["cost_gate_impact"]["slippage_blocker_improved"])
        self.assertFalse(payload["cost_gate_impact"]["execution_gate_improved"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")

    def test_safety_and_source(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_24_execution_cost_forensics.py"
        ).read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2724_JSON).read_text(encoding="utf-8").lower()
        self.assertNotIn("password", raw)
        self.assertNotIn("mt5_password", raw)
        payload = json.loads((root / PHASE2724_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["orders_sent"])
        self.assertFalse(safety["symbol_select_called"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["phase_27_25_started"])
        text = (root / PHASE2724_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.24", text)
        self.assertIn("COMPLETE_COSTS_REQUIRED", text)
        self.assertIn("BROKER_RATE_ONLY", text)


if __name__ == "__main__":
    unittest.main()
