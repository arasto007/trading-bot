"""Phase 22P — forensics tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.research.phase22p.execution_trace import build_execution_trace
from tradingbot.ml.research.phase22p.signal_loss import build_signal_loss_map, rank_filter_effectiveness
from tradingbot.ml.research.phase22p.trade_path import analyze_trade_paths


class TestPhase22P(unittest.TestCase):
    def test_execution_trace_has_18_stages(self):
        trace = build_execution_trace()
        self.assertEqual(trace["stage_count"], 18)
        self.assertTrue(any(s["stage"] == "MT5 order_send" for s in trace["stages"]))

    def test_signal_loss_map_from_hold_chain(self):
        hc = {
            "bars_evaluated": 1000,
            "buy_emitted": 2,
            "sell_emitted": 0,
            "ml_signals": 2,
            "ml_hold_stages": {"decision_hold": 950, "rsi_filter_hold": 10},
            "meta_hold": 0,
            "riskgate_hold": 5,
            "riskgate_block_reasons": {"daily loss limit": 5},
        }
        m = build_signal_loss_map(hold_chain=hc, blocked_events=[], trace_records=[], ohlcv=None)
        self.assertEqual(m["summary"]["hold_chain_bars_evaluated"], 1000)
        self.assertIn("Decision/Engine", m["summary"]["total_module_blocks"])

    def test_filter_ranking_orders_by_blocks(self):
        hc = {
            "ml_hold_stages": {"decision_hold": 400, "rsi_filter_hold": 5},
            "meta_hold": 0,
            "riskgate_hold": 10,
            "riskgate_block_reasons": {},
        }
        r = rank_filter_effectiveness(
            hold_chain=hc,
            backtest_metrics={"profit_factor": 0.0, "max_drawdown_pct": 5.0},
            blocked_events=[],
            ohlcv=None,
            baseline_trades=[],
        )
        self.assertGreater(r["ranked_filters"][0]["signals_removed"], 0)

    def test_trade_path_win_rate(self):
        trades = [{"side": "SELL", "entry_time": "2026-01-01", "pnl": -10.0, "r_multiple": -1}]
        a = analyze_trade_paths(trades, ohlcv=None)
        self.assertEqual(a["summary"]["actual_losses"], 1)


if __name__ == "__main__":
    unittest.main()
