"""Phase 28.1 — chronological full baseline tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    PHASE280_BASELINE_JSON,
    PHASE280_MANIFEST_JSON,
)
from tradingbot.backtest.phase28_1_full_baseline import (
    ATTRIBUTION_BUCKETS,
    BLOCKED,
    PHASE,
    PHASE281_JSON,
    PHASE281_MD,
    REQUIRED_ARTIFACT_KEYS,
    classify_riskgate_reason,
    run_phase28_1_collection,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase28_1_collection(Path(__file__).resolve().parents[1])


class TestPhase281FullBaseline(unittest.TestCase):
    def test_approved_fingerprint_and_no_silent_xauusd(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE281_JSON).read_text(encoding="utf-8"))
        p28 = json.loads((root / PHASE280_BASELINE_JSON).read_text(encoding="utf-8"))
        manifest = json.loads((root / PHASE280_MANIFEST_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["approved_dataset"]["path"], CANONICAL_PARQUET)
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(payload["dataset_fingerprint"], p28["dataset_fingerprint"])
        self.assertTrue(payload["fingerprint_matches_phase28_0"])
        self.assertFalse(payload["silent_xauusd_mapping"])
        self.assertEqual(payload["research_configuration"]["dataset_symbol_map"], {})
        self.assertFalse(payload["approved_dataset"]["logical_xauusd_used"])
        self.assertNotIn("XAUUSD", {row.get("symbol") for row in manifest["evidence_backed"]})
        self.assertFalse(payload["datasets_changed"])
        self.assertEqual(payload["canonical_fingerprint_before"], payload["canonical_fingerprint_after"])

    def test_lookahead_and_reproducibility(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE281_JSON).read_text(encoding="utf-8"))
        look = payload["lookahead"]
        self.assertTrue(look["official_results_closed_bars_only"])
        self.assertFalse(look["features_use_future_candles"])
        self.assertFalse(look["signal_generation_uses_future_high_low"])
        self.assertTrue(look["exits_may_use_future_bars_after_entry"])
        self.assertEqual(look["status"], "PASS")
        det = payload["deterministic_reproducibility"]
        self.assertTrue(det["signal_scan_repeated"])
        self.assertTrue(det["setups_fingerprint_match"])
        self.assertTrue(det["matches_phase28_0_fingerprint"])
        self.assertFalse(payload["chunking"]["used"])
        self.assertFalse(payload["chunking"]["semantics_changed"])

    def test_raw_and_executable_split(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE281_JSON).read_text(encoding="utf-8"))
        raw = payload["raw_signal"]
        exe = payload["executable"]
        for key in (
            "setups",
            "BUY",
            "SELL",
            "total_trades",
            "wins",
            "losses",
            "win_rate",
            "average_R",
            "expectancy_R",
            "profit_factor",
            "gross_profit_R",
            "gross_loss_R",
            "max_drawdown_R",
            "average_trade_duration_minutes",
            "trades_per_calendar_day",
            "trades_per_ny_session",
            "max_consecutive_losses",
            "monthly_distribution",
            "weekly_distribution",
        ):
            self.assertIn(key, raw)
        self.assertEqual(exe["candidates"], raw["setups"])
        self.assertEqual(exe["allowed"] + exe["rejected"], exe["candidates"])
        self.assertEqual(exe["executed_simulated_fills"], 0)
        self.assertTrue(exe["chronological"])
        self.assertTrue(exe["risk_state_preserved"])
        self.assertGreaterEqual(len(payload["raw_vs_executable_diff"]), 4)
        if exe["allowed"] == 0:
            self.assertIsNone(exe["metrics"]["expectancy_R"])

    def test_riskgate_attribution_buckets(self) -> None:
        self.assertEqual(classify_riskgate_reason("lot too small"), "LOT")
        self.assertEqual(classify_riskgate_reason("meta-labeler rejected (p=0.10)"), "META")
        self.assertEqual(classify_riskgate_reason("ATR percentile too high (100>95)"), "ATR")
        self.assertEqual(classify_riskgate_reason("spread too wide"), "SPREAD")
        self.assertEqual(classify_riskgate_reason("news blackout"), "NEWS")
        self.assertEqual(classify_riskgate_reason("entry cooldown"), "COOLDOWN")
        self.assertEqual(classify_riskgate_reason("something else"), "OTHER")
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE281_JSON).read_text(encoding="utf-8"))
        counts = payload["riskgate_attribution"]["counts"]
        for bucket in ATTRIBUTION_BUCKETS:
            self.assertIn(bucket, counts)
        self.assertEqual(sum(counts.values()), payload["executable"]["rejected"])
        self.assertFalse(payload["riskgate_attribution"]["gates_changed"])
        self.assertIn("monthly_distribution", payload)
        self.assertIn("drawdown", payload)
        self.assertIn("trade_frequency", payload)

    def test_no_optimization_or_live_auth(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE281_JSON).read_text(encoding="utf-8"))
        self.assertTrue(payload["research_only"])
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["monte_carlo"])
        self.assertFalse(payload["strategy_changed"])
        self.assertFalse(payload["riskgate_changed"])
        self.assertFalse(payload["phase_28_2_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["ev_eq_01"], "NOT_PROVEN")
        self.assertEqual(payload["statistical_sufficiency"]["classification"], "DATA_INSUFFICIENT")
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        self.assertEqual(payload["research_configuration"]["commission_status"], "UNKNOWN")
        self.assertEqual(payload["research_configuration"]["risk_per_trade"], 0.005)

    def test_artifact_schema_and_docs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE281_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        lowered = raw.lower()
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, lowered)
        src = (root / "tradingbot" / "backtest" / "phase28_1_full_baseline.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE281_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 28.1", md)
        self.assertIn("DO NOT START PHASE 28.2", md)
        self.assertEqual(payload["phase"], PHASE)
        self.assertFalse(payload["safety"]["MT5_STARTED"])
        self.assertFalse(payload["safety"]["PARAMETERS_OPTIMIZED"])
        self.assertIn("not proof", payload["conclusion"].lower())
