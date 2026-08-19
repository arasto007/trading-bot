"""Phase 27F — replay portfolio repair unit tests and deliverable checks."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.accounting.engine import AccountingEngine
from tradingbot.ml.research.phase25b.replay_portfolio import ReplayPortfolioTracker

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase27f"

DELIVERABLES = [
    "portfolio_timeline.json",
    "position_lifecycle.json",
    "riskgate_before_after.json",
    "open_position_history.json",
    "execution_statistics.json",
    "portfolio_consistency.json",
    "final_report.json",
]

VERDICTS = {"REPLAY_PORTFOLIO_FIXED", "REPLAY_PORTFOLIO_NOT_FIXED"}


def _synthetic_candles(n: int = 20) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    prices = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 2 for p in prices],
            "close": prices,
        },
        index=idx,
    )


class TestReplayPortfolioTracker(unittest.TestCase):
    def test_position_closes_and_removes_from_open(self) -> None:
        candles = _synthetic_candles(30)
        tracker = ReplayPortfolioTracker(
            candles, symbol="XAUUSD", accounting=AccountingEngine(initial_balance=10_000)
        )
        entry_ts = candles.index[5].isoformat()
        tracker.open_from_execution(
            bar_index=5,
            entry_timestamp=entry_ts,
            direction="BUY",
            entry_price=102.5,
            sl=101.0,
            tp=106.0,
            lot=0.01,
        )
        portfolio: dict = {"balance": 10_000, "open_positions": []}
        tracker.sync_portfolio(portfolio)
        self.assertEqual(len(portfolio["open_positions"]), 1)

        for bar in range(6, 15):
            tracker.advance_to_bar(bar)
            tracker.sync_portfolio(portfolio)

        self.assertEqual(len(portfolio["open_positions"]), 0)
        summary = tracker.export_summary()
        self.assertEqual(summary["opens"], 1)
        self.assertEqual(summary["closes"], 1)

    def test_max_concurrent_respects_limit(self) -> None:
        candles = _synthetic_candles(40)
        tracker = ReplayPortfolioTracker(
            candles, symbol="XAUUSD", accounting=AccountingEngine(initial_balance=10_000)
        )
        portfolio: dict = {"balance": 10_000, "open_positions": []}
        for bar in (5, 7):
            tracker.open_from_execution(
                bar_index=bar,
                entry_timestamp=candles.index[bar].isoformat(),
                direction="BUY",
                entry_price=float(candles.iloc[bar]["close"]),
                sl=float(candles.iloc[bar]["close"]) - 5,
                tp=float(candles.iloc[bar]["close"]) + 10,
                lot=0.01,
            )
            tracker.sync_portfolio(portfolio)
        self.assertEqual(len(portfolio["open_positions"]), 2)
        tracker.advance_to_bar(20)
        tracker.sync_portfolio(portfolio)
        self.assertLessEqual(len(portfolio["open_positions"]), 2)


class TestPhase27FDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "final_report.json").is_file():
            raise unittest.SkipTest("Phase 27F deliverables not generated yet")

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)

    def test_after_executions_exceed_before(self) -> None:
        risk = json.loads(
            (PHASE_DIR / "riskgate_before_after.json").read_text(encoding="utf-8")
        )
        self.assertGreater(risk["after"]["executed"], risk["before"]["executed"])

    def test_max_position_blocks_decreased(self) -> None:
        risk = json.loads(
            (PHASE_DIR / "riskgate_before_after.json").read_text(encoding="utf-8")
        )
        after_blocks = risk["after"]["by_reason"].get("max positions for symbol", 0)
        before_blocks = risk["before"]["by_reason"].get("max positions for symbol", 0)
        self.assertLess(after_blocks, before_blocks)

    def test_portfolio_lifecycle_balanced(self) -> None:
        lifecycle = json.loads(
            (PHASE_DIR / "position_lifecycle.json").read_text(encoding="utf-8")
        )
        self.assertGreater(lifecycle["closes"], 0)
        self.assertGreaterEqual(lifecycle["opens"], lifecycle["closes"])

    def test_portfolio_consistency(self) -> None:
        consistency = json.loads(
            (PHASE_DIR / "portfolio_consistency.json").read_text(encoding="utf-8")
        )
        self.assertEqual(consistency.get("record_timeline_mismatches"), 0)


if __name__ == "__main__":
    unittest.main()
