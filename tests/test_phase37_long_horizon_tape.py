"""Phase 37 — long-horizon XAUUSD_i tape tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    load_parquet_utc,
)
from tradingbot.backtest.phase37_long_horizon_tape import (
    BLOCKED,
    CANONICAL_SYMBOL,
    PHASE,
    PHASE37_JSON,
    PHASE37_M5,
    PHASE37_MD,
    REQUIRED_ARTIFACT_KEYS,
    audit_dataset,
    content_fingerprint,
    run_phase37_collection,
    strategy_window_coverage,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
    "terminal64.exe",
)


def setUpModule() -> None:
    run_phase37_collection(Path(__file__).resolve().parents[1])


def _synthetic_ohlc(*, duplicate: bool = False, impossible: bool = False) -> pd.DataFrame:
    idx = pd.date_range("2026-08-20 15:00", periods=4, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [2000.0, 2001.0, 2002.0, 2003.0],
            "high": [2001.0, 2002.0, 2003.0, 2004.0],
            "low": [1999.0, 2000.0, 2001.0, 2002.0],
            "close": [2000.5, 2001.5, 2002.5, 2003.5],
            "volume": [10.0, 11.0, 12.0, 13.0],
        },
        index=idx,
    )
    if impossible:
        df.loc[df.index[0], "high"] = 1990.0
        df.loc[df.index[0], "low"] = 2010.0
    if duplicate:
        df = pd.concat([df, df.iloc[[0]]])
    return df


class TestPhase37LongHorizonTape(unittest.TestCase):
    def test_frozen_fingerprint_binding_and_quality_helpers(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE37_JSON).read_text(encoding="utf-8"))
        frozen = root / CANONICAL_PARQUET
        self.assertEqual(file_fingerprint(frozen), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(payload["fingerprints"]["phase28_m5_file"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertTrue(payload["fingerprints"]["phase28_m5_unchanged"])
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["safety"]["CANONICAL_M5_OVERWRITTEN"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertTrue(payload["dataset_binding"]["empty_map"])
        self.assertFalse(payload["dataset_binding"]["xauusd_merged"])
        self.assertFalse(payload["dataset_binding"]["logical_xauusd_used"])
        self.assertEqual(payload["dataset_binding"]["canonical_symbol"], CANONICAL_SYMBOL)
        frozen_df = load_parquet_utc(frozen)
        self.assertEqual(str(frozen_df.index.tz), "UTC")
        fp_a = content_fingerprint(frozen_df)
        fp_b = content_fingerprint(frozen_df)
        self.assertEqual(fp_a, fp_b)
        self.assertEqual(fp_a, payload["fingerprints"]["phase28_m5_content"])
        dups = audit_dataset(_synthetic_ohlc(duplicate=True), timeframe="M5", path="mem")
        self.assertGreater(dups["duplicate_timestamps"], 0)
        bad = audit_dataset(_synthetic_ohlc(impossible=True), timeframe="M5", path="mem")
        self.assertGreater(bad["impossible_ohlc"], 0)
        good = audit_dataset(_synthetic_ohlc(), timeframe="M5", path="mem")
        self.assertEqual(good["duplicate_timestamps"], 0)
        self.assertEqual(good["impossible_ohlc"], 0)
        self.assertTrue(good["timezone_consistent_utc"])
        win = strategy_window_coverage(_synthetic_ohlc(), step_minutes=5)
        self.assertIn("ny_15_16_utc", win)
        self.assertFalse(win["strategy_validation_coverage_claimed"])
        if payload["m5"].get("path"):
            self.assertEqual(payload["m5"]["path"], PHASE37_M5)
            self.assertNotEqual(payload["m5"]["path"], CANONICAL_PARQUET)
            phase37 = load_parquet_utc(root / PHASE37_M5)
            self.assertEqual(str(phase37.index.tz), "UTC")
            self.assertEqual(content_fingerprint(phase37), payload["fingerprints"]["phase37_m5_content"])
            self.assertEqual(content_fingerprint(phase37), content_fingerprint(phase37))

    def test_attach_only_no_trading_no_phase_38(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE37_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertTrue(payload["terminal"]["attach_only"])
        self.assertFalse(payload["terminal"]["mt5_started_by_script"])
        self.assertFalse(payload["terminal"]["symbol_select_called"])
        self.assertFalse(payload["terminal"]["orders_sent"])
        self.assertFalse(payload["terminal"]["env_accessed"])
        self.assertIn(payload["terminal"]["status"], {"ATTACHED", "NOT_ATTACHED", "BLOCKED"})
        if payload["terminal"]["status"] == "BLOCKED":
            self.assertEqual(payload["status"], "BLOCKED")
            self.assertFalse(payload["targets"]["preferred_180d_met"])
        self.assertEqual(payload["production_changes"], "NONE")
        self.assertFalse(payload["strategy_evaluated"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["phase_38_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        self.assertEqual(payload["symbols"]["XAUUSD"].get("broker_wide_absence_concluded"), False)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase37_long_horizon_tape.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            if token == "terminal64.exe":
                self.assertNotIn("launch terminal64.exe", src.lower())
                continue
            self.assertNotIn(token, src)
        self.assertNotIn("order_check(", src)
        md = (root / PHASE37_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 37", md)
        self.assertIn("DO NOT START PHASE 38", md)
        self.assertIn("PRODUCTION_CHANGES", md)
        self.assertNotIn("phase38_", src.lower())
        self.assertTrue((root / CANONICAL_PARQUET).is_file())
        self.assertNotEqual(PHASE37_M5, CANONICAL_PARQUET)
