"""Phase 27.18 — historical M5 bid/ask closure tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.backtest.cost_model import (
    SpreadMode,
    detect_spread_mode_from_frame,
    frame_has_historical_bid_ask,
)
from tradingbot.backtest.historical_bidask import (
    CANONICAL_SYMBOL,
    credentials_contaminated,
)
from tradingbot.backtest.phase27_11_historical_bidask import inventory_existing_datasets
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_18_historical_bidask import (
    EVIDENCE_BLOCKED,
    EVIDENCE_DATASET,
    PHASE2718_JSON,
    PHASE2718_MD,
    TAPE_PARQUET,
    classify_frame_spread_mode,
    classify_historical_spread_evidence,
    live_tick_is_not_historical_tape,
    reject_substitution_sources,
    run_phase27_18_collection,
    validate_phase2718_tape,
)


def setUpModule() -> None:
    run_phase27_18_collection(Path(__file__).resolve().parents[1])


def _good_tape() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=4, freq="5min", tz="UTC")
    return pd.DataFrame(
        {"bid": [2000.0, 2000.1, 2000.2, 2000.3], "ask": [2000.2, 2000.3, 2000.4, 2000.5]},
        index=idx,
    )


def _prov(**extra: object) -> dict:
    base = {
        "symbol": CANONICAL_SYMBOL,
        "timeframe": "M5",
        "source": "mt5_copy_ticks_range",
        "collection_method": "copy_ticks_range read-only",
        "row_count": 4,
        "time_range": {"start": "2026-01-01", "end": "2026-01-01"},
        "fingerprint": "abc",
    }
    base.update(extra)
    return base


class TestPhase2718HistoricalBidAsk(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2718_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.18")
        self.assertEqual(payload["status"], "PASS")
        self.assertIn(payload["evidence_status"], (EVIDENCE_BLOCKED, EVIDENCE_DATASET))
        self.assertTrue(payload["dataset_spread_requires_historical_bid_ask"])
        self.assertTrue(payload["proxy_not_equivalent_to_historical_bid_ask"])
        self.assertTrue(payload["original_datasets_untouched"])
        self.assertEqual(payload["canonical_symbol"], CANONICAL_SYMBOL)
        self.assertEqual(payload["canonical_timeframe"], "M5")

    def test_repo_has_no_production_historical_bid_ask(self) -> None:
        root = Path(__file__).resolve().parents[1]
        inv = inventory_existing_datasets(root)
        self.assertEqual(inv["bidask_dataset_count"], 0)
        self.assertFalse(inv["historical_bid_ask_available"])
        self.assertFalse(inv["any_canonical_historical_bid_ask"])
        payload = json.loads((root / PHASE2718_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["cost_provenance"]["production_datasets_spread_mode"], "PROXY")
        self.assertEqual(payload["cost_provenance"]["production_spread_evidence_status"], EVIDENCE_BLOCKED)
        self.assertTrue(payload["cost_provenance"]["logs_tape_is_not_a_production_dataset"])
        self.assertEqual(payload["sidecar_inventory"]["dataset_claimed_without_historical_bid_ask"], [])

    def test_dataset_spread_not_claimed_from_ohlc_proxy_or_spread_column(self) -> None:
        ohlc = pd.DataFrame({"open": [1], "high": [2], "low": [0], "close": [1], "volume": [1]})
        self.assertFalse(frame_has_historical_bid_ask(ohlc))
        self.assertEqual(detect_spread_mode_from_frame(ohlc), SpreadMode.PROXY)
        self.assertEqual(classify_frame_spread_mode(ohlc), SpreadMode.PROXY.value)
        spread_only = pd.DataFrame(
            {"open": [2000], "high": [2001], "low": [1999], "close": [2000], "spread": [0.3]}
        )
        self.assertFalse(frame_has_historical_bid_ask(spread_only))
        self.assertNotEqual(detect_spread_mode_from_frame(spread_only), SpreadMode.DATASET)
        self.assertNotEqual(classify_frame_spread_mode(spread_only), SpreadMode.DATASET.value)

    def test_current_tick_is_not_historical(self) -> None:
        self.assertTrue(live_tick_is_not_historical_tape("symbol_info_tick"))
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2718_JSON).read_text(encoding="utf-8"))
        live = payload["live_tick_rejected"]
        self.assertFalse(live["treated_as_historical_m5_tape"])
        self.assertFalse(live["live_tick_is_historical"])
        self.assertFalse(payload["safety_confirmation"]["current_tick_used_as_historical"])

    def test_classify_dataset_only_when_tape_valid(self) -> None:
        self.assertEqual(classify_historical_spread_evidence(tape_valid=True), EVIDENCE_DATASET)
        self.assertEqual(classify_historical_spread_evidence(tape_valid=False), EVIDENCE_BLOCKED)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2718_JSON).read_text(encoding="utf-8"))
        if payload["tape"]["status"] == EVIDENCE_DATASET:
            self.assertEqual(payload["evidence_status"], EVIDENCE_DATASET)
            self.assertIsNotNone(payload["tape"]["path"])
            self.assertTrue((root / TAPE_PARQUET).is_file())
            tape = pd.read_parquet(root / TAPE_PARQUET)
            self.assertTrue(frame_has_historical_bid_ask(tape))
            self.assertEqual(payload["cost_provenance"]["production_spread_evidence_status"], EVIDENCE_BLOCKED)
            self.assertTrue(payload["tape"]["provenance"].get("not_a_production_dataset"))
        else:
            self.assertEqual(payload["tape"]["status"], EVIDENCE_BLOCKED)
            if payload["evidence_status"] == EVIDENCE_DATASET:
                self.assertTrue(payload["existing_tapes"]["any_existing_valid_tape"])
            else:
                self.assertEqual(payload["evidence_status"], EVIDENCE_BLOCKED)

    def test_malformed_bid_ask(self) -> None:
        idx = pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC")
        bad = pd.DataFrame({"bid": [2000.2, 2000.3], "ask": [2000.0, 2000.1]}, index=idx)
        result = validate_phase2718_tape(bad, symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov())
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("malformed" in e or "missing_or_invalid" in e or "unordered" in e for e in result["errors"])
        )

    def test_non_monotonic_and_non_utc(self) -> None:
        idx = pd.to_datetime(["2026-01-01T00:10:00Z", "2026-01-01T00:00:00Z"])
        df = pd.DataFrame({"bid": [1.0, 1.1], "ask": [1.2, 1.3]}, index=idx)
        result = validate_phase2718_tape(df, symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov())
        self.assertIn("timestamps_not_monotonic", result["errors"])
        naive = pd.DataFrame(
            {"bid": [1.0, 1.1], "ask": [1.2, 1.3]},
            index=pd.date_range("2026-01-01", periods=2, freq="5min"),
        )
        naive_result = validate_phase2718_tape(
            naive, symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov()
        )
        self.assertIn("timestamps_not_utc", naive_result["errors"])

    def test_missing_bid_ask_and_wrong_symbol(self) -> None:
        idx = pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC")
        df = pd.DataFrame({"open": [1, 2], "close": [1, 2]}, index=idx)
        result = validate_phase2718_tape(df, symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov())
        self.assertIn("missing_or_invalid_bid_ask", result["errors"])
        wrong = validate_phase2718_tape(_good_tape(), symbol="XAUUSD", timeframe="H4", provenance=_prov())
        self.assertFalse(wrong["symbol_ok"])
        self.assertFalse(wrong["timeframe_ok"])

    def test_credential_and_provenance(self) -> None:
        self.assertTrue(credentials_contaminated({"password": "secret", "symbol": CANONICAL_SYMBOL}))
        result = validate_phase2718_tape(
            _good_tape(),
            symbol=CANONICAL_SYMBOL,
            timeframe="M5",
            provenance=_prov(password="x"),
        )
        self.assertIn("credential_contamination", result["errors"])
        good = validate_phase2718_tape(
            _good_tape(), symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov()
        )
        self.assertTrue(good["ok"])

    def test_no_substitution_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2718_JSON).read_text(encoding="utf-8"))
        rejected = reject_substitution_sources()
        for key in ("current_bid_ask_tick", "ohlc_spread", "proxy_spread", "spread_column"):
            self.assertTrue(payload["substitutions_rejected"][key])
            self.assertTrue(rejected[key])
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["mt5_restarted"])
        self.assertFalse(safety["orders_sent"])
        self.assertFalse(safety["symbol_select_called"])
        self.assertFalse(safety["original_datasets_overwritten"])
        self.assertFalse(safety["env_file_read"])
        self.assertFalse(safety["strategy_modified"])
        self.assertFalse(safety["riskgate_modified"])
        self.assertFalse(safety["execution_semantics_modified"])
        self.assertFalse(safety["phase_27_19_started"])
        text = (root / PHASE2718_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.18", text)
        blob = (root / PHASE2718_JSON).read_text(encoding="utf-8").lower()
        self.assertNotIn("password", blob)
        self.assertNotIn("mt5_password", blob)

    def test_no_symbol_select_or_env_in_source(self) -> None:
        src = (
            Path(__file__).resolve().parents[1]
            / "tradingbot"
            / "backtest"
            / "phase27_18_historical_bidask.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("symbol_select(", src)
        self.assertNotIn("load_dotenv", src)
        self.assertNotIn('Path(".env")', src)
        self.assertNotIn("order_send(", src)

    def test_originals_and_final_gate_not_weakened(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2718_JSON).read_text(encoding="utf-8"))
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["phase27_16_final_gate_unchanged"], "BLOCKED")
        self.assertEqual(payload["production_readiness"], "BLOCKED")
        if payload["tape"]["path"]:
            self.assertTrue(str(payload["tape"]["path"]).startswith("logs/"))
            self.assertFalse(payload["tape"]["production_dataset"])


if __name__ == "__main__":
    unittest.main()
