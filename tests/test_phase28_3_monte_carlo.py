"""Phase 28.3 — Monte Carlo robustness tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import numpy as np

from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
)
from tradingbot.backtest.phase28_1_full_baseline import PHASE281_JSON
from tradingbot.backtest.phase28_2_walk_forward import PHASE282_JSON
from tradingbot.backtest.phase28_3_monte_carlo import (
    BLOCKED,
    N_PATHS,
    PHASE,
    PHASE283_JSON,
    PHASE283_MD,
    REQUIRED_ARTIFACT_KEYS,
    RNG_SEED,
    classify_robustness,
    path_metrics,
    run_bootstrap,
    run_phase28_3_collection,
    run_shuffle,
)

FORBIDDEN_ARTIFACT_KEYS = ("password", "mt5_password", "token", "api_key", "investor")
FORBIDDEN_SOURCE_TOKENS = (
    "symbol_select(",
    "order_send(",
    "load_dotenv",
    'Path(".env")',
)


def setUpModule() -> None:
    run_phase28_3_collection(Path(__file__).resolve().parents[1])


class TestPhase283MonteCarlo(unittest.TestCase):
    def test_loads_baseline_only_and_fingerprint_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE283_JSON).read_text(encoding="utf-8"))
        p281 = json.loads((root / PHASE281_JSON).read_text(encoding="utf-8"))
        p282 = json.loads((root / PHASE282_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["dataset_fingerprint"], EXPECTED_CANONICAL_FINGERPRINT)
        self.assertEqual(payload["dataset_fingerprint"], p281["dataset_fingerprint"])
        self.assertEqual(payload["dataset_fingerprint"], p282["dataset_fingerprint"])
        self.assertEqual(file_fingerprint(root / CANONICAL_PARQUET), EXPECTED_CANONICAL_FINGERPRINT)
        self.assertFalse(payload["datasets_changed"])
        self.assertFalse(payload["ohlc_rewalked"])
        self.assertTrue(payload["monte_carlo_used_baseline_only"])
        self.assertEqual(payload["baseline_source"]["phase28_1"], PHASE281_JSON)
        self.assertEqual(payload["baseline_source"]["phase28_2"], PHASE282_JSON)
        self.assertTrue(payload["baseline_source"]["r_series_match"])
        self.assertEqual(payload["trade_count_raw"], 24)
        self.assertEqual(payload["trade_count_executable"], 0)
        self.assertEqual(payload["observed_raw"]["wins"], 1.0)
        self.assertEqual(payload["observed_raw"]["losses"], 23.0)

    def test_percentiles_and_perturbations_are_modeled(self) -> None:
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE283_JSON).read_text(encoding="utf-8"))
        for name in ("shuffle", "bootstrap"):
            block = payload["monte_carlo"][name]
            for key in ("median", "p5", "p25", "p75", "p95"):
                self.assertIn(key, block["final_R"])
                self.assertIn(key, block["max_drawdown_R"])
            self.assertIn("prob_dd_ge_10R", block)
            self.assertIn("prob_dd_ge_20R", block)
            self.assertIn("longest_losing_streak", block)
        self.assertFalse(payload["monte_carlo"]["executable"]["defined"])
        costs = payload["modeled_costs"]
        self.assertEqual(costs["label"], "MODELED")
        self.assertTrue(costs["not_historical_realized"])
        self.assertEqual(costs["spread_status"], "MODELED_PROXY")
        self.assertEqual(costs["slippage_status"], "MODELED_PROXY")
        pert = payload["perturbations"]
        self.assertTrue(pert["all_labeled_MODELED"])
        self.assertTrue(pert["not_historical_realized"])
        for name in (
            "entry_spread_adverse_MODELED",
            "entry_spread_plus_minus_MODELED",
            "slippage_adverse_MODELED",
            "spread_plus_slippage_adverse_MODELED",
        ):
            self.assertIn(name, pert["summary"])
            self.assertEqual(pert["summary"][name]["label"], "MODELED")
            self.assertTrue(pert["summary"][name]["not_realized"])
            for metric in ("expectancy_R", "profit_factor", "max_drawdown_R", "win_rate"):
                self.assertIn(metric, pert["summary"][name])

    def test_conclusion_insufficient_sample_no_optimization(self) -> None:
        root = Path(__file__).resolve().parents[1]
        raw = (root / PHASE283_JSON).read_text(encoding="utf-8")
        payload = json.loads(raw)
        for key in REQUIRED_ARTIFACT_KEYS:
            self.assertIn(key, payload)
        self.assertEqual(payload["conclusion"], "INSUFFICIENT_SAMPLE")
        self.assertEqual(payload["robustness"]["classification"], "INSUFFICIENT_SAMPLE")
        self.assertFalse(payload["robustness"]["confidence_invented"])
        self.assertFalse(payload["parameters_optimized"])
        self.assertFalse(payload["strategy_changed"])
        self.assertFalse(payload["riskgate_changed"])
        self.assertFalse(payload["ml_changed"])
        self.assertFalse(payload["live_trading_authorized"])
        self.assertFalse(payload["phase_28_4_started"])
        self.assertEqual(payload["FINAL_GATE"], BLOCKED)
        self.assertEqual(payload["phase"], PHASE)
        p16 = json.loads((root / PHASE2716_JSON).read_text(encoding="utf-8"))
        self.assertEqual(p16["FINAL_GATE"], "BLOCKED")
        empty = classify_robustness(n_trades=24, n_executable=0)
        self.assertEqual(empty["classification"], "INSUFFICIENT_SAMPLE")
        for secret in FORBIDDEN_ARTIFACT_KEYS:
            self.assertNotIn(secret, raw.lower())
        src = (root / "tradingbot" / "backtest" / "phase28_3_monte_carlo.py").read_text(encoding="utf-8")
        for token in FORBIDDEN_SOURCE_TOKENS:
            self.assertNotIn(token, src)
        md = (root / PHASE283_MD).read_text(encoding="utf-8")
        self.assertIn("STOP AFTER PHASE 28.3", md)
        self.assertIn("DO NOT START PHASE 28.4", md)
        self.assertIn("MODELED", md)
        self.assertNotIn("phase28_4", src.lower())

    def test_seed_is_deterministic(self) -> None:
        r = [-1.0] * 23 + [1.5]
        a = run_shuffle(r, np.random.default_rng(RNG_SEED), 64)
        b = run_shuffle(r, np.random.default_rng(RNG_SEED), 64)
        self.assertEqual([p["final_R"] for p in a], [p["final_R"] for p in b])
        c = run_bootstrap(r, np.random.default_rng(RNG_SEED), 64)
        d = run_bootstrap(r, np.random.default_rng(RNG_SEED), 64)
        self.assertEqual([p["final_R"] for p in c], [p["final_R"] for p in d])
        observed = path_metrics(r)
        self.assertAlmostEqual(observed["final_R"], -21.5)
        self.assertEqual(observed["longest_losing_streak"], 23.0)
        root = Path(__file__).resolve().parents[1]
        payload = json.loads((root / PHASE283_JSON).read_text(encoding="utf-8"))
        self.assertEqual(payload["monte_carlo"]["seed"], RNG_SEED)
        self.assertEqual(payload["monte_carlo"]["n_paths"], N_PATHS)
