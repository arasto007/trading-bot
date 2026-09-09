"""Phase 27.21 — evidence synthesis lightweight tests (no backtest, no MT5)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_21_evidence_synthesis import (
    BLOCKED,
    PHASE2721_JSON,
    PHASE2721_MD,
    PROVEN,
    classify_execution_model,
    classify_historical_spread_coverage,
    commission_verified,
    ev_eq_01_can_close,
    mapping_justified_from_filename_or_environment,
    run_phase27_21_collection,
    slippage_under_modeled,
    swap_under_broker_rate_only,
)


def setUpModule() -> None:
    run_phase27_21_collection(Path(__file__).resolve().parents[1])


class TestPhase2721EvidenceSynthesis(unittest.TestCase):
    def test_artifact_and_final_gate_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2721_JSON).read_text(encoding="utf-8"))
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.21")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["FINAL_GATE"], "BLOCKED")
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertFalse(payload["gates_weakened"])
        self.assertFalse(payload["cost_ready_for_validation"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")

    def test_spread_coverage_not_conflated(self) -> None:
        cov = classify_historical_spread_coverage(
            tape_valid=True, tape_bars=82, production_has_historical_bid_ask=False
        )
        self.assertEqual(cov["A_historical_bid_ask_exists"], PROVEN)
        self.assertEqual(cov["B_full_canonical_dataset_spread"], BLOCKED)
        self.assertEqual(cov["C_cost_aware_validation_coverage"], BLOCKED)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2721_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["spread_coverage"]["A_historical_bid_ask_exists"], PROVEN)
        self.assertEqual(payload["spread_coverage"]["B_full_canonical_dataset_spread"], BLOCKED)
        self.assertEqual(payload["spread_coverage"]["C_cost_aware_validation_coverage"], BLOCKED)

    def test_ev_eq_01_not_closed_from_absence(self) -> None:
        result = ev_eq_01_can_close(
            xauusd_exists=False,
            xauusd_i_exists=True,
            both_on_same_environment=False,
            field_match=False,
        )
        self.assertFalse(result["can_close"])
        self.assertEqual(result["evidence_status"], "NOT_PROVEN")
        self.assertTrue(result["xauusd_absent_does_not_prove_equivalence"])
        self.assertTrue(result["xauusd_absent_does_not_prove_broker_wide_absence"])

    def test_no_filename_mapping(self) -> None:
        self.assertFalse(mapping_justified_from_filename_or_environment())
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2721_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_mapping"]["logical_xauusd_blocked"], 30)
        self.assertTrue(payload["dataset_mapping"]["remain_blocked"])
        self.assertFalse(payload["dataset_mapping"]["maps_inserted"])

    def test_commission_observed_zero_not_verified(self) -> None:
        result = commission_verified(
            account_product_type="UNKNOWN",
            basis="UNKNOWN",
            effective_date="UNKNOWN",
            applicability_established=False,
            observed_zero=True,
        )
        self.assertFalse(result["verified"])
        self.assertEqual(result["classification"], BLOCKED)
        self.assertIn("account_product_type", result["missing"])

    def test_swap_and_slippage_do_not_complete(self) -> None:
        swap = swap_under_broker_rate_only(
            rates_present=True, rollover_present=True, historical_series="UNKNOWN"
        )
        self.assertEqual(swap["broker_rates"], PROVEN)
        self.assertEqual(swap["historical_series"], "UNKNOWN")
        self.assertTrue(swap["complete_requires_historical_series"])
        self.assertTrue(swap["broker_rate_only_blocks_completeness"])
        slip = slippage_under_modeled(realized_samples=0, statistically_sufficient=False)
        self.assertFalse(slip["modeled_satisfies_complete_under_current_code"])
        self.assertTrue(slip["lack_of_realized_blocks_complete"])

    def test_execution_model_not_reclassified(self) -> None:
        exe = classify_execution_model()
        self.assertEqual(exe["status"], "UNKNOWN")
        self.assertFalse(exe["documentation_only"])
        self.assertTrue(exe["kind"]["A_missing_required_evidence"])
        self.assertTrue(exe["kind"]["B_missing_documented_simulation_classification"])
        self.assertTrue(exe["kind"]["C_dependent_on_realized_execution_data"])

    def test_no_mt5_or_production_changes(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_21_evidence_synthesis.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("symbol_select(", src)
        self.assertNotIn("order_send(", src)
        self.assertNotIn("import MetaTrader5", src)
        self.assertNotIn("mt5.copy_ticks_range", src)
        self.assertNotIn("load_dotenv", src)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2721_JSON).read_text(encoding="utf-8"))
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["phase_27_22_started"])
        text = (root / PHASE2721_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.21", text)
        self.assertIn("FINAL_GATE", text)


if __name__ == "__main__":
    unittest.main()
