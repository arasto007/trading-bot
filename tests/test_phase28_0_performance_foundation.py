"""Phase 28.0 — performance foundation tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.dataset_contract import STATUS_MISSING_MAP
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    MIN_RESOLVED_FOR_SUFFICIENCY,
    PHASE,
    PHASE280_BASELINE_JSON,
    PHASE280_MANIFEST_JSON,
    PHASE280_MD,
    PRIMARY_SYMBOL,
    REQUIRED_BASELINE_KEYS,
    REQUIRED_MANIFEST_KEYS,
    classify_performance_eligibility,
    classify_statistical_sufficiency,
    run_phase28_0_collection,
    theoretical_outcome,
)
from tradingbot.config.live import PRIMARY_SYMBOL as LIVE_PRIMARY

import pandas as pd

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)
STRATEGY_SOURCES = (
    "engine/strategies/price_action_strategy.py",
    "tradingbot/domain/gold_strategies/m5_london_sweep.py",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/backtest/risk.py",
)


def setUpModule() -> None:
    run_phase28_0_collection(Path(__file__).resolve().parents[1])


class TestPhase280PerformanceFoundation(unittest.TestCase):
    def test_canonical_is_best_dataset(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / PHASE280_MANIFEST_JSON).read_text(encoding="utf-8"))
        baseline = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        best = manifest["best_dataset"]
        self.assertIsNotNone(best)
        self.assertEqual(best["symbol"], LIVE_PRIMARY)
        self.assertEqual(best["timeframe"], "M5")
        self.assertTrue(str(best["path"]).replace("\\", "/").endswith("data/XAUUSD_i_5m.parquet"))
        self.assertEqual(best["performance_eligibility"], "ELIGIBLE_ENTRY")
        self.assertEqual(baseline["best_dataset"], CANONICAL_PARQUET)
        self.assertEqual(manifest["canonical_symbol"], "XAUUSD_i")
        self.assertEqual(LIVE_PRIMARY, "XAUUSD_i")

    def test_logical_xauusd_blocked_without_map(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / PHASE280_MANIFEST_JSON).read_text(encoding="utf-8"))
        self.assertEqual(manifest["dataset_symbol_map"], {})
        self.assertFalse(manifest["silent_xauusd_mapping"])
        blocked = manifest["blocked"]
        self.assertGreater(len(blocked), 0)
        self.assertTrue(all(row["performance_eligibility"].startswith("BLOCKED") for row in blocked))
        logical = [row for row in blocked if row.get("symbol") == "XAUUSD"]
        self.assertGreater(len(logical), 0)
        self.assertTrue(all(row["mapping_status"] == STATUS_MISSING_MAP for row in logical))
        evidence_symbols = {row.get("symbol") for row in manifest["evidence_backed"]}
        self.assertNotIn("XAUUSD", evidence_symbols)
        self.assertIn("XAUUSD_i", evidence_symbols)
        eligibility = classify_performance_eligibility(
            inferred_symbol="XAUUSD",
            inferred_timeframe="M5",
            binding_status=STATUS_MISSING_MAP,
            blocked=True,
            ohlc_present=True,
        )
        self.assertEqual(eligibility, "BLOCKED_MISSING_EXPLICIT_MAP")

    def test_fingerprint_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / PHASE280_MANIFEST_JSON).read_text(encoding="utf-8"))
        baseline = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        self.assertFalse(manifest["datasets_changed"])
        self.assertEqual(manifest["canonical_fingerprint_before"], manifest["canonical_fingerprint_after"])
        self.assertEqual(manifest["canonical_fingerprint_after"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(baseline["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        can = manifest["canonical_audit"]
        self.assertEqual(can["row_count"], 3000)
        self.assertTrue(can["fingerprint_match"])
        self.assertEqual(can["bidask_coverage"], "PROXY_OHLC_ONLY")

    def test_signal_vs_executable_split(self) -> None:
        root = Path(__file__).resolve().parents[1]
        baseline = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        sig = baseline["raw_signal_results"]
        exe = baseline["executable_results"]
        for key in (
            "setups",
            "BUY",
            "SELL",
            "wins",
            "losses",
            "win_rate",
            "expectancy_R",
            "profit_factor",
            "max_drawdown_R",
            "trade_frequency",
        ):
            self.assertIn(key, sig)
        for key in ("candidates", "allowed", "rejected", "rejection_reasons", "trades"):
            self.assertIn(key, exe)
        self.assertEqual(exe["candidates"], sig["setups"])
        self.assertEqual(exe["allowed"] + exe["rejected"], exe["candidates"])
        cfg = baseline["research_configuration"]
        self.assertEqual(cfg["dataset_symbol_map_explicit"], {})
        self.assertEqual(cfg["commission_status"], "UNKNOWN")
        self.assertEqual(cfg["risk_per_trade"], 0.005)
        self.assertEqual(cfg["min_rr"], 1.5)
        self.assertFalse(cfg["parameters_optimized"])
        self.assertFalse(cfg["strategy_changed"])
        self.assertFalse(cfg["riskgate_changed"])

    def test_lookahead_closed_bar_and_sl_before_tp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        baseline = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        look = baseline["lookahead"]
        self.assertTrue(look["official_results_closed_bars_only"])
        self.assertFalse(look["features_use_future_candles"])
        self.assertFalse(look["signal_generation_uses_future_high_low"])
        self.assertTrue(look["exits_may_use_future_bars_after_entry"])
        self.assertTrue(look["forming_bar_excluded"])
        idx = pd.date_range("2026-08-20", periods=4, freq="5min", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [2000.0, 2001.0, 2002.0, 2003.0],
                "high": [2000.5, 2010.0, 2002.5, 2003.5],
                "low": [1999.5, 1990.0, 2001.5, 2002.5],
                "close": [2000.2, 2005.0, 2002.2, 2003.2],
            },
            index=idx,
        )
        # Signal on bar 0; bar 1 hits both SL and TP — SL must win.
        out = theoretical_outcome(df, 0, "BUY", 2000.0, 1995.0, 2008.0)
        self.assertEqual(out["outcome"], "loss")
        self.assertEqual(out["r_multiple"], -1.0)
        self.assertTrue(out["same_bar_sl_and_tp"])
        self.assertEqual(out["exit_index"], 1)

    def test_data_insufficient_and_not_no_edge(self) -> None:
        root = Path(__file__).resolve().parents[1]
        baseline = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        suff = baseline["statistical_sufficiency"]
        self.assertEqual(suff["classification"], "DATA_INSUFFICIENT")
        self.assertFalse(suff["confidence_invented"])
        self.assertTrue(suff["zero_trades_is_not_no_edge"])
        self.assertLess(suff["resolved"], MIN_RESOLVED_FOR_SUFFICIENCY)
        self.assertIn("DATA_INSUFFICIENT", baseline["conclusion"])
        self.assertIn("not proof", baseline["conclusion"].lower())
        empty = classify_statistical_sufficiency(resolved=0, calendar_days=15, setups=0)
        self.assertEqual(empty["classification"], "DATA_INSUFFICIENT")
        exe = baseline["executable_results"]
        if exe["allowed"] == 0:
            self.assertIsNone(exe["expectancy_R"])

    def test_deterministic_reproducibility(self) -> None:
        root = Path(__file__).resolve().parents[1]
        baseline = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        det = baseline["deterministic_reproducibility"]
        self.assertTrue(det["signal_scan_repeated"])
        self.assertTrue(det["setups_fingerprint_match"])
        self.assertTrue(str(det["fingerprint"]))

    def test_no_live_authorization_and_gate_blocked(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / PHASE280_MANIFEST_JSON).read_text(encoding="utf-8"))
        baseline = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        self.assertTrue(baseline["research_only"])
        self.assertFalse(baseline["live_trading_authorized"])
        self.assertFalse(baseline["cost_adjusted_metrics_allowed"])
        self.assertEqual(baseline["FINAL_GATE"], BLOCKED)
        self.assertEqual(baseline["ev_eq_01"], "NOT_PROVEN")
        self.assertEqual(baseline["cost_completeness"], BLOCKED)
        self.assertFalse(baseline["phase_28_1_started"])
        self.assertFalse(manifest["safety"]["PHASE_28_1_STARTED"])
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")

    def test_artifact_schema_safety_and_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        manifest_raw = (root / PHASE280_MANIFEST_JSON).read_text(encoding="utf-8")
        baseline_raw = (root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8")
        manifest = json.loads(manifest_raw)
        baseline = json.loads(baseline_raw)
        for key in REQUIRED_MANIFEST_KEYS:
            self.assertIn(key, manifest)
        for key in REQUIRED_BASELINE_KEYS:
            self.assertIn(key, baseline)
        lowered = (manifest_raw + baseline_raw).lower()
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, lowered)
        src = (root / "tradingbot" / "backtest" / "phase28_0_performance_foundation.py").read_text(
            encoding="utf-8"
        )
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE280_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 28.0", md)
        self.assertIn("DO NOT START PHASE 28.1", md)
        self.assertIn("RESEARCH ONLY", md)
        self.assertEqual(manifest["phase"], PHASE)
        self.assertEqual(PRIMARY_SYMBOL, "XAUUSD_i")
        for rel in STRATEGY_SOURCES:
            self.assertTrue((root / rel).is_file())
        self.assertNotIn("order_send(", src)
        self.assertFalse(manifest["safety"]["MT5_STARTED"])
        self.assertFalse(manifest["safety"]["ENV_ACCESSED"])
        self.assertFalse(manifest["safety"]["STRATEGY_CHANGED"])
        self.assertFalse(manifest["safety"]["RISKGATE_CHANGED"])
