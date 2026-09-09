"""Phase 27.11 — historical M5 bid/ask evidence tests."""

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
    validate_historical_m5_tape,
)
from tradingbot.backtest.phase27_11_historical_bidask import (
    PHASE2711_JSON,
    PHASE2711_MD,
    inventory_existing_datasets,
    run_phase27_11_collection,
)


def setUpModule() -> None:
    run_phase27_11_collection(Path(__file__).resolve().parents[1])


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


class TestPhase2711HistoricalBidAsk(unittest.TestCase):
    def test_artifact_valid(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2711_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["phase"], "27.11")
        self.assertEqual(payload["status"], "PASS")
        self.assertIn(payload["evidence_status"], ("BLOCKED_PENDING_DATA", "COLLECTED_EVIDENCE_ONLY"))
        self.assertTrue(payload["dataset_spread_requires_historical_bid_ask"])
        self.assertTrue(payload["original_datasets_untouched"])

    def test_repo_has_no_historical_bid_ask(self) -> None:
        root = Path(__file__).resolve().parents[1]
        inv = inventory_existing_datasets(root)
        self.assertEqual(inv["bidask_dataset_count"], 0)
        self.assertFalse(inv["historical_bid_ask_available"])
        self.assertFalse(inv["any_canonical_historical_bid_ask"])

    def test_dataset_spread_not_claimed_from_ohlc_or_spread_column(self) -> None:
        ohlc = pd.DataFrame({"open": [1], "high": [2], "low": [0], "close": [1], "volume": [1]})
        self.assertFalse(frame_has_historical_bid_ask(ohlc))
        self.assertEqual(detect_spread_mode_from_frame(ohlc), SpreadMode.PROXY)
        spread_only = pd.DataFrame(
            {"open": [2000], "high": [2001], "low": [1999], "close": [2000], "spread": [0.3]}
        )
        self.assertFalse(frame_has_historical_bid_ask(spread_only))
        self.assertNotEqual(detect_spread_mode_from_frame(spread_only), SpreadMode.DATASET)

    def test_malformed_bid_ask(self) -> None:
        idx = pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC")
        bad = pd.DataFrame({"bid": [2000.2, 2000.3], "ask": [2000.0, 2000.1]}, index=idx)
        result = validate_historical_m5_tape(bad, symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov())
        self.assertFalse(result["ok"])
        self.assertTrue(any("malformed" in e or "missing_or_invalid" in e for e in result["errors"]))

    def test_non_monotonic_timestamps(self) -> None:
        idx = pd.to_datetime(["2026-01-01T00:10:00Z", "2026-01-01T00:00:00Z"])
        df = pd.DataFrame({"bid": [1.0, 1.1], "ask": [1.2, 1.3]}, index=idx)
        result = validate_historical_m5_tape(df, symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov())
        self.assertIn("timestamps_not_monotonic", result["errors"])

    def test_missing_bid_ask(self) -> None:
        idx = pd.date_range("2026-01-01", periods=2, freq="5min", tz="UTC")
        df = pd.DataFrame({"open": [1, 2], "close": [1, 2]}, index=idx)
        result = validate_historical_m5_tape(df, symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov())
        self.assertIn("missing_or_invalid_bid_ask", result["errors"])

    def test_wrong_symbol_and_timeframe(self) -> None:
        df = _good_tape()
        result = validate_historical_m5_tape(df, symbol="XAUUSD", timeframe="H4", provenance=_prov())
        self.assertFalse(result["symbol_ok"])
        self.assertFalse(result["timeframe_ok"])
        self.assertTrue(any(e.startswith("wrong_symbol") for e in result["errors"]))
        self.assertTrue(any(e.startswith("wrong_timeframe") for e in result["errors"]))

    def test_credential_contamination(self) -> None:
        self.assertTrue(credentials_contaminated({"password": "secret", "symbol": CANONICAL_SYMBOL}))
        result = validate_historical_m5_tape(
            _good_tape(),
            symbol=CANONICAL_SYMBOL,
            timeframe="M5",
            provenance=_prov(password="x"),
        )
        self.assertIn("credential_contamination", result["errors"])

    def test_provenance_completeness(self) -> None:
        result = validate_historical_m5_tape(
            _good_tape(),
            symbol=CANONICAL_SYMBOL,
            timeframe="M5",
            provenance={"symbol": CANONICAL_SYMBOL},
        )
        self.assertTrue(any(e.startswith("provenance_incomplete") for e in result["errors"]))
        good = validate_historical_m5_tape(
            _good_tape(), symbol=CANONICAL_SYMBOL, timeframe="M5", provenance=_prov()
        )
        self.assertTrue(good["ok"])

    def test_no_substitution_and_safety(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE2711_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["substitutions_rejected"]["current_bid_ask_tick"])
        self.assertTrue(payload["substitutions_rejected"]["ohlc_spread"])
        self.assertTrue(payload["substitutions_rejected"]["proxy_spread"])
        safety = payload["safety_confirmation"]
        self.assertFalse(safety["mt5_started"])
        self.assertFalse(safety["orders_sent"])
        self.assertFalse(safety["symbol_select_called"])
        self.assertFalse(safety["original_datasets_overwritten"])
        text = (root / PHASE2711_MD).read_text(encoding="utf-8")
        self.assertIn("STOP after Phase 27.11", text)
        blob = (root / PHASE2711_JSON).read_text(encoding="utf-8").lower()
        self.assertNotIn("password", blob)


if __name__ == "__main__":
    unittest.main()
