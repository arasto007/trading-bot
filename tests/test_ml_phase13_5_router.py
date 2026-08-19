"""Phase 13.5 — regime router research tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import phase13_5_router_report_path
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.regime_router.config import RouterConfig, WALK_FORWARD_YEARS
from tradingbot.ml.research.regime_router.regime_router import route_regime
from tradingbot.ml.research.regime_router.report_generator import run_phase13_5_router
from tradingbot.ml.research.regime_router.router_validator import validate_router_components
from tradingbot.ml.research.regime_router.signal_aggregator import aggregate_signal
from tradingbot.ml.research.regime_router.walk_forward_router import build_year_windows, run_walk_forward_router
from tradingbot.ml.research.research_utils import dataset_content_fingerprint

ROUTER_PKG = ROOT / "tradingbot" / "ml" / "research" / "regime_router"
FORBIDDEN = ("tradingbot.kernel", "mt5_execution", "order_send", "risk_gate")
FORBIDDEN_STRINGS = ("order_send", "trade_request", "mt5_execution")


def _candles(n: int = 1200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2021-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300.0 + rng.normal(0, 0.5, n).cumsum()
    return pd.DataFrame(
        {
            "open": close,
            "high": close + rng.uniform(0.2, 1.2, n),
            "low": close - rng.uniform(0.2, 1.2, n),
            "close": close,
        },
        index=ts,
    )


def _setup(tmp: str) -> None:
    store = DatasetStore(tmp)
    ts = pd.date_range("2021-01-01", periods=400, freq="5min", tz="UTC")
    store.store_v2(
        "XAUUSD",
        "M5",
        pd.DataFrame(
            {
                "timestamp": ts,
                "symbol": "XAUUSD",
                "timeframe": "M5",
                "label": [0, 1] * 200,
                "dataset_schema_version": DATASET_SCHEMA_VERSION,
            }
        ),
    )
    CandleStore(tmp).store("XAUUSD", "M5", _candles(1200))


class TestPhase135Router(unittest.TestCase):
    def test_regime_routing_rules(self):
        self.assertEqual(route_regime("RANGE"), "RANGE")
        self.assertEqual(route_regime("TREND"), "TREND")
        self.assertEqual(route_regime("HIGH_VOLATILITY"), "BLOCK")
        self.assertEqual(route_regime("NO_TRADE"), "BLOCK")

    def test_signal_aggregator_block_priority(self):
        blocked = aggregate_signal(
            {"action": "BLOCK", "regime": "NO_TRADE", "reason": "regime_no_trade"},
        )
        self.assertEqual(blocked["final_signal"], "HOLD")
        self.assertEqual(blocked["block_reason"], "regime_no_trade")

    def test_walk_forward_years(self):
        windows = build_year_windows()
        self.assertEqual(len(windows), len(WALK_FORWARD_YEARS))
        self.assertEqual(windows[0]["test_year"], 2021)

    def test_no_forbidden_imports(self):
        for py in ROUTER_PKG.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for token in FORBIDDEN:
                        self.assertNotIn(token, node.module)

    def test_no_execution_strings(self):
        for py in ROUTER_PKG.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for token in FORBIDDEN_STRINGS:
                self.assertNotIn(token, text)

    def test_components_load_on_production(self):
        if not (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
            self.skipTest("phase9_9 artifacts missing")
        candles = _candles(800)
        config = RouterConfig()
        result = validate_router_components(candles, config=config, base_dir=None)
        self.assertTrue(result["checks"]["phase9_9_loaded"])
        self.assertTrue(result["checks"]["trend_engine_loaded"])
        self.assertTrue(result["checks"]["regime_routing"])

    def test_walk_forward_integrity(self):
        if not (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
            self.skipTest("phase9_9 artifacts missing")
        wf = run_walk_forward_router(_candles(1500), config=RouterConfig(), base_dir=None)
        self.assertTrue(wf["chronological"])
        self.assertFalse(wf["shuffle"])

    def test_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
                self.skipTest("phase9_9 artifacts missing")
            fp_before = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            run_phase13_5_router(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp)
            fp_after = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp_before, fp_after)

    def test_full_pipeline_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            if not (ROOT / "data" / "ml" / "research" / "phase9_9_best" / "model.pkl").is_file():
                self.skipTest("phase9_9 artifacts missing")
            result = run_phase13_5_router(symbol="XAUUSD", timeframe="M5", seed=42, base_dir=tmp)
            self.assertIn(result.status, ("PASS", "NEEDS_REVIEW"))
            self.assertTrue(Path(result.reports["final_phase13_5_report"]).is_file())
            report = json.loads(phase13_5_router_report_path(tmp).read_text(encoding="utf-8"))
            self.assertTrue(report["fingerprint_unchanged"])
            self.assertFalse(report["connected_to_live_trading"])
            self.assertTrue(report["ready_for_phase14"])


if __name__ == "__main__":
    unittest.main()
