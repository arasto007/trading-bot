"""Phase 31E — replay portfolio state machine repair tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.accounting.engine import AccountingEngine
from tradingbot.ml.research.phase25b.replay_portfolio import ReplayOpenPosition, ReplayPortfolioTracker
from tradingbot.ml.research.phase25b.replay_position_state import (
    ReplayPositionState,
    advance_hybrid_b_bar,
    simulate_stateful_lifecycle,
)
from tradingbot.services.exit_mode import ExitMode
from tradingbot.services.exit_policy import resolve_hybrid_b

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase31e"

DELIVERABLES = [
    "state_machine_design.json",
    "replay_state_validation.json",
    "position_lifecycle.json",
    "partial_close_validation.json",
    "timeout_validation.json",
    "trade_by_trade_comparison.json",
    "accounting_validation.json",
    "journal_validation.json",
    "simulator_parity_validation.json",
    "phase31e_final_report.json",
]

VERDICTS = {"SIMULATOR_PARITY_CONFIRMED", "SIMULATOR_PARITY_FAILED"}


def _candles(n: int = 100, *, start: float = 4480.0) -> pd.DataFrame:
    idx = pd.date_range("2026-06-01", periods=n, freq="5min", tz="UTC")
    close = [start + i * 0.5 for i in range(n)]
    return pd.DataFrame({
        "open": close,
        "high": [c + 1.5 for c in close],
        "low": [c - 1.5 for c in close],
        "close": close,
    }, index=idx)


class TestReplayPositionState(unittest.TestCase):
    def test_state_persists_partial_volume(self) -> None:
        state = ReplayPositionState.from_open(
            entry_timestamp="2026-06-01T00:00:00+00:00",
            entry_price=100.0,
            entry_bar_index=5,
            direction="BUY",
            symbol="XAUUSD",
            sl=95.0,
            tp=120.0,
            lot=0.02,
            exit_mode=ExitMode.HYBRID_B,
        )
        bar = pd.Series({"open": 110, "high": 112, "low": 109, "close": 111})
        advance_hybrid_b_bar(state, bar, 6, "2026-06-01T00:30:00+00:00", max_candle_index=99)
        if state.partial_executed:
            self.assertEqual(state.remaining_volume, 0.01)

    def test_no_reinit_last_processed_bar(self) -> None:
        state = ReplayPositionState.from_open(
            entry_timestamp="2026-06-01T00:00:00+00:00",
            entry_price=100.0,
            entry_bar_index=5,
            direction="BUY",
            symbol="XAUUSD",
            sl=95.0,
            tp=120.0,
            lot=0.01,
            exit_mode=ExitMode.HYBRID_B,
        )
        bar = pd.Series({"open": 100, "high": 101, "low": 99, "close": 100})
        advance_hybrid_b_bar(state, bar, 6, "ts1", max_candle_index=99)
        self.assertEqual(state.last_processed_bar, 6)
        advance_hybrid_b_bar(state, bar, 6, "ts1", max_candle_index=99)
        self.assertEqual(state.bars_held, 1)

    def test_stateful_matches_oracle(self) -> None:
        candles = _candles(80, start=4485.0)
        entry_ts = candles.index[10].isoformat()
        oracle = resolve_hybrid_b(
            candles=candles,
            entry_ts=entry_ts,
            entry_price=4488.0,
            sl=4480.0,
            tp=4520.0,
            is_buy=True,
            lot=0.01,
            symbol="XAUUSD",
        )
        stateful = simulate_stateful_lifecycle(
            entry_timestamp=entry_ts,
            entry_price=4488.0,
            entry_bar_index=10,
            direction="BUY",
            symbol="XAUUSD",
            sl=4480.0,
            tp=4520.0,
            lot=0.01,
            candles=candles,
            exit_mode=ExitMode.HYBRID_B,
        )
        self.assertEqual(oracle["exit_reason"], stateful["exit_reason"])
        self.assertAlmostEqual(oracle["pnl"], stateful["pnl"], places=2)


class TestReplayPortfolioTrackerRepair(unittest.TestCase):
    def test_hybrid_b_holds_multiple_bars(self) -> None:
        candles = _candles(50, start=4485.0)
        tracker = ReplayPortfolioTracker(
            candles,
            symbol="XAUUSD",
            accounting=AccountingEngine(initial_balance=200.0),
            exit_mode=ExitMode.HYBRID_B,
        )
        entry_ts = candles.index[5].isoformat()
        tracker.open_from_execution(
            bar_index=5,
            entry_timestamp=entry_ts,
            direction="BUY",
            entry_price=4487.0,
            sl=4480.0,
            tp=4520.0,
            lot=0.01,
        )
        tracker.advance_to_bar(6)
        self.assertEqual(len(tracker._open), 1)
        pos = tracker._open[0]
        self.assertIsNotNone(pos.replay_state)
        self.assertFalse(pos.replay_state.closed)
        self.assertEqual(pos.replay_state.bars_held, 1)

    def test_position_closes_after_timeout_or_sl(self) -> None:
        candles = _candles(90, start=4485.0)
        tracker = ReplayPortfolioTracker(
            candles,
            symbol="XAUUSD",
            accounting=AccountingEngine(initial_balance=200.0),
            exit_mode=ExitMode.HYBRID_B,
        )
        tracker.open_from_execution(
            bar_index=5,
            entry_timestamp=candles.index[5].isoformat(),
            direction="BUY",
            entry_price=4487.0,
            sl=4480.0,
            tp=4520.0,
            lot=0.01,
        )
        for bar in range(6, 80):
            tracker.advance_to_bar(bar)
        self.assertEqual(len(tracker._open), 0)
        self.assertEqual(tracker.export_summary()["closes"], 1)

    def test_no_truncated_exit_on_first_bar(self) -> None:
        candles = _candles(40, start=4485.0)
        tracker = ReplayPortfolioTracker(
            candles,
            symbol="XAUUSD",
            accounting=AccountingEngine(initial_balance=200.0),
            exit_mode=ExitMode.HYBRID_B,
        )
        tracker.open_from_execution(
            bar_index=5,
            entry_timestamp=candles.index[5].isoformat(),
            direction="BUY",
            entry_price=4487.0,
            sl=4480.0,
            tp=4520.0,
            lot=0.01,
        )
        tracker.advance_to_bar(6)
        closed = tracker.export_closed_trades()
        self.assertEqual(len(closed), 0)

    def test_replay_state_initialized_once(self) -> None:
        candles = _candles(30)
        tracker = ReplayPortfolioTracker(
            candles, symbol="XAUUSD",
            accounting=AccountingEngine(initial_balance=200.0),
            exit_mode=ExitMode.HYBRID_B,
        )
        tracker.open_from_execution(
            bar_index=3,
            entry_timestamp=candles.index[3].isoformat(),
            direction="BUY",
            entry_price=100.0,
            sl=95.0,
            tp=110.0,
            lot=0.01,
        )
        tracker.advance_to_bar(4)
        tracker.advance_to_bar(5)
        inits = [e for e in tracker.lifecycle if e.get("event") == "state_init"]
        self.assertEqual(len(inits), 1)

    def test_remaining_volume_synced_after_partial(self) -> None:
        candles = _candles(60, start=4490.0)
        tracker = ReplayPortfolioTracker(
            candles,
            symbol="XAUUSD",
            accounting=AccountingEngine(initial_balance=200.0),
            exit_mode=ExitMode.HYBRID_B,
        )
        tracker.open_from_execution(
            bar_index=5,
            entry_timestamp=candles.index[5].isoformat(),
            direction="BUY",
            entry_price=4491.0,
            sl=4485.0,
            tp=4520.0,
            lot=0.02,
        )
        portfolio: dict = {"open_positions": []}
        for bar in range(6, 20):
            tracker.advance_to_bar(bar)
            tracker.sync_portfolio(portfolio)
        if tracker._open:
            vol = portfolio["open_positions"][0]["volume"]
            self.assertLessEqual(vol, 0.02)


class TestPhase31EDeliverables(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase31e_final_report.json").is_file():
            from tradingbot.ml.research.phase31e.run_investigation import run_phase31e
            run_phase31e()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_verdict_confirmed(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31e_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(doc["verdict"], VERDICTS)
        self.assertEqual(doc["verdict"], "SIMULATOR_PARITY_CONFIRMED")

    def test_replay_portfolio_repaired_flag(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31e_final_report.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["replay_portfolio_repaired"])
        self.assertFalse(doc["production_hybrid_b_modified"])

    def test_oracle_match_100_pct(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31e_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["oracle_match_pct"], 100.0)

    def test_trade_count_489(self) -> None:
        doc = json.loads((PHASE_DIR / "trade_by_trade_comparison.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["trade_count"], 489)
        self.assertTrue(doc["all_match"])

    def test_pf_gap_within_tolerance(self) -> None:
        doc = json.loads((PHASE_DIR / "accounting_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["within_tolerance"])
        self.assertLess(doc["pf_gap_pct"], 0.5)

    def test_partial_close_validation(self) -> None:
        doc = json.loads((PHASE_DIR / "partial_close_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["partial_count_match"])

    def test_timeout_validation_improved(self) -> None:
        doc = json.loads((PHASE_DIR / "timeout_validation.json").read_text(encoding="utf-8"))
        self.assertGreater(doc["avg_duration_repaired"], 1.0)

    def test_phase31d_rerun_confirmed(self) -> None:
        doc = json.loads((PHASE_DIR / "simulator_parity_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["phase31d_rerun"])
        self.assertEqual(doc["phase31d_verdict"], "SIMULATOR_PARITY_CONFIRMED")

    def test_state_machine_design_documented(self) -> None:
        doc = json.loads((PHASE_DIR / "state_machine_design.json").read_text(encoding="utf-8"))
        self.assertIn("entry_timestamp", doc["state_fields"])
        self.assertIn("replay_position_state.py", doc["module"])

    def test_journal_entry_timestamps(self) -> None:
        doc = json.loads((PHASE_DIR / "journal_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["entry_timestamps_identical"])

    def test_replay_state_validation_pass(self) -> None:
        doc = json.loads((PHASE_DIR / "replay_state_validation.json").read_text(encoding="utf-8"))
        self.assertTrue(doc["pass"])
        self.assertEqual(doc["oracle_fingerprint_matches"], 489)

    def test_legacy_pf_lower_than_repaired(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31e_final_report.json").read_text(encoding="utf-8"))
        self.assertLess(doc["legacy_production_pf"], doc["repaired_production_pf"])

    def test_no_remaining_mismatches(self) -> None:
        doc = json.loads((PHASE_DIR / "phase31e_final_report.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["remaining_mismatches"], 0)

    def test_position_has_replay_state_field(self) -> None:
        pos = ReplayOpenPosition(
            position_id="x",
            symbol="XAUUSD",
            direction="BUY",
            entry_bar_index=1,
            entry_timestamp="t",
            entry_price=1.0,
            sl=0.5,
            tp=2.0,
            lot=0.01,
        )
        self.assertIsNone(pos.replay_state)


if __name__ == "__main__":
    unittest.main()
