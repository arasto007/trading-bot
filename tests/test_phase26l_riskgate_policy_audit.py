"""Phase 26L — RiskGate policy audit tests (static / artifact-only)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG
from tradingbot.backtest.phase26i_full_tail_attribution import EXPECTED_CURSORS
from tradingbot.backtest.phase26l_riskgate_policy_audit import (
    EXPECTED_BASELINE,
    PHASE26G_JSON,
    PHASE26H_JSON,
    PHASE26L_JSON,
    _verify_baseline_artifacts,
    audit_atr_policy,
    audit_lot_policy,
    audit_meta_policy,
    run_phase26l_collection,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.domain.broker_economics import BrokerEconomics, lot_from_broker_economics


class TestPhase26LBaselineArtifacts(unittest.TestCase):
    def test_baseline_3_10_6_0(self) -> None:
        root = Path(__file__).resolve().parents[1]
        g26 = json.loads((root / PHASE26G_JSON).read_text(encoding="utf-8"))
        h26 = json.loads((root / PHASE26H_JSON).read_text(encoding="utf-8"))
        result = _verify_baseline_artifacts(g26, h26)
        self.assertTrue(result["passed"], msg=str(result["issues"]))
        self.assertEqual(result["expected"]["ALLOWED"], 0)

    def test_nineteen_candidate_set_constant(self) -> None:
        self.assertEqual(len(EXPECTED_CURSORS), 19)


class TestPhase26LLotPolicy(unittest.TestCase):
    def test_volume_min_preserved(self) -> None:
        self.assertEqual(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"]["volume_min"], 0.01)

    def test_alias_target_is_xauusd_i(self) -> None:
        self.assertEqual(PRIMARY_SYMBOL, "XAUUSD_i")

    def test_lot_floor_fails_closed_below_min(self) -> None:
        econ = BrokerEconomics.from_mapping("XAUUSD_i", OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])
        lot, reason = lot_from_broker_economics(1000.0, 0.005, 4018.27, 4007.663, econ)
        self.assertIsNone(lot)
        self.assertEqual(reason, "VOLUME_BELOW_MIN")

    def test_no_hidden_round_up_to_min(self) -> None:
        econ = BrokerEconomics.from_mapping("XAUUSD_i", OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])
        stepped = econ.floor_to_volume_step(0.004)
        self.assertLess(stepped, econ.volume_min)


class TestPhase26LMetaAndATR(unittest.TestCase):
    def test_meta_threshold_source_identified(self) -> None:
        root = Path(__file__).resolve().parents[1]
        from tradingbot.backtest.phase26b_controlled_validation import build_frozen_baseline_configuration

        meta = audit_meta_policy(root, build_frozen_baseline_configuration())
        self.assertIn("effective_threshold_ranging", meta)
        self.assertIsNotNone(meta["configured_base_threshold"])

    def test_atr_policy_source_identified(self) -> None:
        root = Path(__file__).resolve().parents[1]
        atr = audit_atr_policy(root)
        self.assertEqual(atr["lookback_bars"], 252)
        self.assertTrue(atr["hard_block"])
        self.assertIn("market_filters", atr["implementation"])


class TestPhase26LCollection(unittest.TestCase):
    def test_audit_generates_artifact_without_engine(self) -> None:
        root = Path(__file__).resolve().parents[1]
        report = run_phase26l_collection(root)
        self.assertEqual(report["production_changes"], "NONE")
        self.assertFalse(report["safety"]["BACKTEST_EXECUTED"])
        self.assertFalse(report["safety"]["FULL_ENGINE_EXECUTED"])
        self.assertTrue((root / PHASE26L_JSON).is_file())
        self.assertEqual(report["final_classification"], "B — COHERENT BUT EXTREMELY RESTRICTIVE")

    def test_baseline_constants(self) -> None:
        self.assertEqual(EXPECTED_BASELINE["LOT"], 3)
        self.assertEqual(EXPECTED_BASELINE["META"], 10)
        self.assertEqual(EXPECTED_BASELINE["ATR"], 6)


if __name__ == "__main__":
    unittest.main()
