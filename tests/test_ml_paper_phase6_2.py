"""Phase 6.2 paper trading engine tests."""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.memory.schema import DecisionRecord, new_decision_id
from tradingbot.ml.paper._types import PaperConfig, SignalMode
from tradingbot.ml.paper.broker_sim import BrokerSim
from tradingbot.ml.paper.engine import PaperTradingEngine
from tradingbot.ml.paper.metrics import compute_metrics
from tradingbot.ml.paper.portfolio import Portfolio
from tradingbot.ml.paper.slippage_model import SlippageModel
from tradingbot.ml.paper.spread_model import SpreadModel
from tradingbot.ml.paper.trade_executor import TradeExecutor
from tradingbot.ml.paper.walk_forward_runner import WalkForwardRunner

PAPER_PKG = ROOT / "tradingbot" / "ml" / "paper"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _candles(n: int = 80, base: float = 2000.0, tp_hit: bool = True) -> pd.DataFrame:
    rows = []
    price = base
    for i in range(n):
        o = price
        if i == 16 and tp_hit:
            h = price + 20.0
            l = price + 0.1
            c = price + 15.0
        elif i == 16 and not tp_hit:
            h = price - 0.1
            l = price - 20.0
            c = price - 15.0
        else:
            h = price + 0.5
            l = price - 0.5
            c = price
        rows.append(
            {
                "timestamp": pd.Timestamp("2024-03-01", tz="UTC") + pd.Timedelta(minutes=5 * i),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
            }
        )
        price = c
    return pd.DataFrame(rows)


def _decision(ts: str, *, hybrid: str = "BUY", score: float = 0.75) -> DecisionRecord:
    return DecisionRecord(
        decision_id=new_decision_id(),
        timestamp=ts,
        symbol="XAUUSD",
        timeframe="M5",
        model_name="logistic",
        ml_probability=0.8,
        ml_prediction=1,
        rule_signal="BUY",
        hybrid_decision=hybrid,
        confidence="HIGH",
        final_score=score,
        features_version="2.0",
        dataset_version="1.0",
        entry_price=2000.0,
        direction=1,
        session="london",
        regime="trend",
        features_snapshot={"volatility_regime": 0.4},
    )


class TestIsolation(unittest.TestCase):
    def test_no_kernel_imports(self):
        for path in PAPER_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._safe(node.module)

    def test_no_risk_imports(self):
        for path in PAPER_PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.adapters.risk_gate", text)
            self.assertNotIn("tradingbot.risk", text)

    def test_no_execution_imports(self):
        for path in PAPER_PKG.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("tradingbot.execution", text)
            self.assertNotIn("tradingbot.adapters.mt5_execution", text)

    def _safe(self, module: str) -> None:
        for prefix in FORBIDDEN:
            self.assertFalse(module.startswith(prefix), module)


class TestModels(unittest.TestCase):
    def test_spread_model_correctness(self):
        model = SpreadModel()
        london = model.spread("london")
        asia = model.spread("asia")
        self.assertLess(london, asia)
        bid, ask = model.bid_ask(2000.0, "london")
        self.assertLess(bid, ask)
        self.assertAlmostEqual((ask - bid), london, places=4)

    def test_slippage_variability(self):
        model = SlippageModel()
        london, slip_l = model.slippage_price(2000.0, 1, session="london")
        asia, slip_a = model.slippage_price(2000.0, 1, session="asia")
        news, slip_n = model.slippage_price(2000.0, 1, session="london", news_event=True)
        self.assertGreater(slip_a, slip_l)
        self.assertGreater(slip_n, slip_l)
        self.assertGreater(london, 2000.0)

    def test_deterministic_mode(self):
        cfg = PaperConfig(deterministic=True, random_seed=7)
        b1 = BrokerSim(deterministic=True, seed=7, rejection_probability=0.0)
        b2 = BrokerSim(deterministic=True, seed=7, rejection_probability=0.0)
        r1 = b1.simulate_entry(2000.0, 1, session="london")
        r2 = b2.simulate_entry(2000.0, 1, session="london")
        self.assertEqual(r1["entry_price"], r2["entry_price"])
        self.assertEqual(r1["delay_bars"], r2["delay_bars"])


class TestTradeExecution(unittest.TestCase):
    def test_tp_sl_simulation(self):
        candles = _candles(tp_hit=True)
        executor = TradeExecutor(PaperConfig(future_window_bars=30))
        trade = executor.open_trade(
            timestamp="2024-03-01T01:40:00+00:00",
            symbol="XAUUSD",
            direction=1,
            entry_price=2000.0,
            signal_source="hybrid",
            session="london",
            risk_unit=10.0,
        )
        resolved = executor.resolve_trade_on_candles(trade, candles, 15)
        self.assertEqual(resolved.exit_reason, "TP")
        self.assertEqual(resolved.r_multiple, 2.0)

        candles_sl = _candles(tp_hit=False)
        trade2 = executor.open_trade(
            timestamp="2024-03-01T01:40:00+00:00",
            symbol="XAUUSD",
            direction=1,
            entry_price=2000.0,
            signal_source="hybrid",
            session="london",
            risk_unit=10.0,
        )
        resolved2 = executor.resolve_trade_on_candles(trade2, candles_sl, 15)
        self.assertEqual(resolved2.exit_reason, "SL")
        self.assertEqual(resolved2.r_multiple, -1.0)

    def test_trade_lifecycle(self):
        portfolio = Portfolio(initial_balance_r=100.0)
        executor = TradeExecutor()
        trade = executor.open_trade(
            timestamp="t",
            symbol="XAUUSD",
            direction=1,
            entry_price=2000.0,
            signal_source="hybrid",
            session="london",
            risk_unit=5.0,
        )
        portfolio.add_open(trade)
        self.assertEqual(len(portfolio.open_trades), 1)
        trade.r_multiple = 2.0
        portfolio.close_trade(trade)
        self.assertEqual(len(portfolio.open_trades), 0)
        self.assertEqual(len(portfolio.closed_trades), 1)
        self.assertEqual(portfolio.total_return_r, 2.0)


class TestEngine(unittest.TestCase):
    def test_no_lookahead_bias(self):
        candles = _candles(n=60, tp_hit=True)
        entry_idx = 10
        executor = TradeExecutor(PaperConfig(future_window_bars=40))
        trade = executor.open_trade(
            timestamp="t",
            symbol="XAUUSD",
            direction=1,
            entry_price=float(candles["close"].iloc[entry_idx]),
            signal_source="hybrid",
            session="london",
        )
        before = executor.resolve_trade_on_candles(trade, candles, entry_idx)
        altered = candles.copy()
        altered.loc[:entry_idx, "high"] = 0.0
        trade2 = executor.open_trade(
            timestamp="t",
            symbol="XAUUSD",
            direction=1,
            entry_price=float(candles["close"].iloc[entry_idx]),
            signal_source="hybrid",
            session="london",
        )
        after = executor.resolve_trade_on_candles(trade2, altered, entry_idx)
        self.assertEqual(before.exit_reason, after.exit_reason)

    def test_reproducibility(self):
        candles = _candles()
        ts = str(candles["timestamp"].iloc[12])
        decisions = [_decision(ts)]
        cfg = PaperConfig(deterministic=True, random_seed=99)
        e1 = PaperTradingEngine(
            config=cfg,
            signal_mode=SignalMode.HYBRID,
            broker=BrokerSim(deterministic=True, seed=99, rejection_probability=0.0),
        )
        e2 = PaperTradingEngine(
            config=cfg,
            signal_mode=SignalMode.HYBRID,
            broker=BrokerSim(deterministic=True, seed=99, rejection_probability=0.0),
        )
        r1 = e1.run(candles, decisions)
        r2 = e2.run(candles, decisions)
        self.assertEqual(r1["metrics"], r2["metrics"])
        self.assertEqual(r1["equity_curve"], r2["equity_curve"])

    def test_equity_curve_logic(self):
        portfolio = Portfolio(initial_balance_r=0.0)
        self.assertEqual(portfolio.equity_curve, [0.0])
        for r in (2.0, -1.0, 2.0):
            trade = TradeExecutor().open_trade(
                timestamp="t",
                symbol="XAUUSD",
                direction=1,
                entry_price=1.0,
                signal_source="hybrid",
                session="london",
            )
            trade.r_multiple = r
            portfolio.close_trade(trade)
        self.assertEqual(len(portfolio.equity_curve), 4)
        self.assertEqual(portfolio.equity_curve[0], 0.0)
        self.assertEqual(portfolio.equity_curve[-1], portfolio.equity_r)
        self.assertEqual(portfolio.total_return_r, 3.0)


class TestWalkForward(unittest.TestCase):
    def test_walk_forward_correctness(self):
        candles = _candles(n=120)
        decisions = [
            _decision(str(candles["timestamp"].iloc[i]))
            for i in range(10, 100, 15)
        ]
        cfg = PaperConfig(deterministic=True, random_seed=1)
        runner = WalkForwardRunner(window_sizes=(50, 100), config=cfg)
        results = runner.run(
            candles,
            decisions,
            signal_mode=SignalMode.HYBRID,
        )
        self.assertEqual(len(results), 2)
        for wf in results:
            self.assertGreaterEqual(wf.end_index, wf.start_index)
            self.assertGreaterEqual(len(wf.equity_curve), 1)
            self.assertIn("total_return_r", wf.metrics)


class TestMetrics(unittest.TestCase):
    def test_metrics_computation(self):
        portfolio = Portfolio(initial_balance_r=0.0)
        for r in (2.0, -1.0, 2.0, -1.0, 2.0):
            t = TradeExecutor().open_trade(
                timestamp="t",
                symbol="XAUUSD",
                direction=1,
                entry_price=1.0,
                signal_source="hybrid",
                session="london",
            )
            t.r_multiple = r
            portfolio.close_trade(t)
        m = compute_metrics(portfolio)
        self.assertEqual(m.trade_frequency, 5)
        self.assertAlmostEqual(m.win_rate, 0.6)
        self.assertGreater(m.profit_factor, 1.0)


if __name__ == "__main__":
    unittest.main()
