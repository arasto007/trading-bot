"""Phase 27.23 — historical Bid/Ask coverage expansion tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.backtest.cost_model import SpreadMode, detect_spread_mode_from_frame, frame_has_historical_bid_ask
from tradingbot.backtest.historical_bidask import CANONICAL_SYMBOL, credentials_contaminated
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_18_historical_bidask import (
    EVIDENCE_BLOCKED,
    EVIDENCE_DATASET,
    TAPE_PARQUET as PHASE2718_TAPE,
)
from tradingbot.backtest.phase27_23_bidask_expansion import (
    BLOCKED,
    PHASE2718_KNOWN_FINGERPRINT,
    PHASE2723_JSON,
    PHASE2723_MD,
    PRODUCTION_H4,
    PRODUCTION_M5,
    PROVEN,
    TAPE_PARQUET,
    classify_coverage,
    compare_to_canonical,
    environment_is_required,
    run_phase27_23_collection,
)


FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "Path('.env')",
)


def setUpModule() -> None:
    run_phase27_23_collection(Path(__file__).resolve().parents[1])


class TestPhase2723BidAskExpansion(unittest.TestCase):
    def test_artifact_and_environment_gate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2723_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.23")
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["canonical_symbol"], CANONICAL_SYMBOL)
        self.assertIn(payload["tape"]["status"], (EVIDENCE_DATASET, EVIDENCE_BLOCKED))
        ok, _reason = environment_is_required(
            {"trade_mode_label": "DEMO", "server": "LiteFinance-MT5-Live"}
        )
        self.assertFalse(ok)
        ok, _reason = environment_is_required(
            {"trade_mode_label": "REAL", "server": "Other-Server"}
        )
        self.assertFalse(ok)

    def test_coverage_classes_not_conflated(self) -> None:
        only_exists = classify_coverage(tape_valid=True, tape_bars=200, full_canonical_covered=False)
        self.assertEqual(only_exists["A_historical_bid_ask_exists"], PROVEN)
        self.assertEqual(only_exists["B_bounded_validation_window"], PROVEN)
        self.assertEqual(only_exists["C_full_canonical_dataset"], BLOCKED)
        none = classify_coverage(tape_valid=False, tape_bars=0, full_canonical_covered=False)
        self.assertEqual(none["A_historical_bid_ask_exists"], BLOCKED)
        self.assertEqual(none["B_bounded_validation_window"], BLOCKED)
        self.assertEqual(none["C_full_canonical_dataset"], BLOCKED)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2723_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["coverage"]["C_full_canonical_dataset"], BLOCKED)
        self.assertFalse(payload["canonical_dataset_fully_covered"])
        self.assertFalse(payload["spread_dataset_for_production_parquet"])
        self.assertTrue(payload["full_cost_aware_validation_blocked"])

    def test_canonical_range_not_fully_covered_from_recent_window(self) -> None:
        idx = pd.date_range("2026-09-01", periods=10, freq="5min", tz="UTC")
        tape = pd.DataFrame({"bid": [1.0] * 10, "ask": [1.1] * 10}, index=idx)
        prod = pd.DataFrame(
            {"open": [1.0] * 4},
            index=pd.date_range("2026-08-13 20:20", periods=4, freq="5min", tz="UTC"),
        )
        cmp_ = compare_to_canonical(tape, prod)
        self.assertFalse(cmp_["canonical_fully_covered"])
        self.assertFalse(cmp_["overlap"])
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2723_JSON).read_text(encoding="utf-8"))
        self.assertFalse(payload["canonical_comparison"]["canonical_fully_covered"])

    def test_proxy_not_substituted_and_production_untouched(self) -> None:
        ohlc = pd.DataFrame({"open": [1], "high": [2], "low": [0], "close": [1], "volume": [1]})
        self.assertFalse(frame_has_historical_bid_ask(ohlc))
        self.assertEqual(detect_spread_mode_from_frame(ohlc), SpreadMode.PROXY)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2723_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["proxy_not_substituted"])
        self.assertTrue(payload["original_datasets_untouched"])
        self.assertTrue(payload["protected_production_untouched"])
        self.assertTrue((root / PRODUCTION_M5).is_file())
        self.assertTrue((root / PRODUCTION_H4).is_file())
        if payload["tape"]["path"]:
            self.assertTrue(str(payload["tape"]["path"]).startswith("logs/"))
            self.assertFalse(payload["tape"]["production_dataset"])
            self.assertTrue((root / TAPE_PARQUET).is_file())
            tape = pd.read_parquet(root / TAPE_PARQUET)
            self.assertTrue(frame_has_historical_bid_ask(tape))

    def test_phase27_18_not_overwritten_as_production(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2723_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase27_18_baseline"]["fingerprint"], PHASE2718_KNOWN_FINGERPRINT)
        self.assertTrue((root / PHASE2718_TAPE).is_file())

    def test_no_symbol_select_env_or_credentials(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_23_bidask_expansion.py"
        ).read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE2723_JSON).read_text(encoding="utf-8").lower()
        self.assertNotIn("password", raw)
        self.assertNotIn("mt5_password", raw)
        payload = json.loads((root / PHASE2723_JSON).read_text(encoding="utf-8"))
        self.assertFalse(credentials_contaminated(payload))

    def test_final_gate_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2723_JSON).read_text(encoding="utf-8"))
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertFalse(payload["complete_costs_required_weakened"])
        self.assertEqual(payload["production_readiness"], "BLOCKED")
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["mt5_restarted"])
        self.assertFalse(safety["orders_sent"])
        self.assertFalse(safety["symbol_select_called"])
        self.assertFalse(safety["env_file_read"])
        self.assertFalse(safety["production_parquet_overwritten"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_modified"])
        self.assertFalse(safety["proxy_used_as_historical"])
        self.assertFalse(safety["phase_27_24_started"])
        text = (root / PHASE2723_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.23", text)
        self.assertIn("COMPLETE_COSTS_REQUIRED", text)
        self.assertIn("full canonical", text.lower())


if __name__ == "__main__":
    unittest.main()
