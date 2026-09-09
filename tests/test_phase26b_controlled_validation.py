"""Phase 26B — controlled logic validation tests (offline; no MT5)."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.phase26b_controlled_validation import (
    ECONOMIC_VALIDATION_STATUS,
    PHASE26B_BASELINE_JSON,
    PHASE26B_FINAL_JSON,
    PHASE26B_RECOVERY_JSON,
    RESEARCH_COMMISSION_LABEL,
    VALIDATION_CLASS,
    build_frozen_baseline_configuration,
    build_phase26b_recovery_report,
    recover_phase26b,
    run_phase26b_collection,
    run_spread_stress,
)
from tradingbot.config.live import PRIMARY_SYMBOL


def _sample_result(trades: int = 3) -> BacktestResult:
    cfg = BacktestConfig()
    closed = []
    for i in range(trades):
        from tradingbot.backtest.models import ClosedTrade

        closed.append(
            ClosedTrade(
                symbol="XAUUSD",
                is_buy=True,
                volume=0.01,
                entry_price=2400.0,
                exit_price=2401.0 if i % 2 == 0 else 2399.0,
                entry_time=pd.Timestamp("2024-06-01 15:00", tz="UTC") + pd.Timedelta(hours=i * 24),
                exit_time=pd.Timestamp("2024-06-01 16:00", tz="UTC") + pd.Timedelta(hours=i * 24),
                pnl=1.0 if i % 2 == 0 else -0.5,
                reason="tp" if i % 2 == 0 else "sl",
            )
        )
    return BacktestResult(
        config=cfg,
        initial_balance=1000.0,
        final_balance=1000.0 + sum(t.pnl for t in closed),
        trades=closed,
    )


def _m5_parquet(root: Path, bars: int = 450) -> None:
    out = root / "data" / "backtest" / "XAUUSD_M5_test.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2024-01-01 00:00", periods=bars, freq="5min", tz="UTC")
    close = pd.Series([2400.0 + (i % 50) * 0.5 for i in range(bars)], index=idx)
    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 100.0,
        },
        index=idx,
    )
    df.to_parquet(out)


class TestFrozenConfig(unittest.TestCase):
    def test_fingerprint_stable(self) -> None:
        a = build_frozen_baseline_configuration()
        b = build_frozen_baseline_configuration()
        self.assertEqual(a["configuration_fingerprint"], b["configuration_fingerprint"])
        self.assertEqual(a["configured_instrument_symbol"], PRIMARY_SYMBOL)
        self.assertIn("XAUUSD", a["dataset_symbol_map_explicit"])

    def test_commission_research_label(self) -> None:
        cfg = build_frozen_baseline_configuration()
        self.assertEqual(cfg["commission_label"], RESEARCH_COMMISSION_LABEL)

    def test_ev_eq_not_proven_in_frozen_map_note(self) -> None:
        cfg = build_frozen_baseline_configuration()
        self.assertIn("NOT_PROVEN", cfg["dataset_symbol_map_note"])


class TestOfflineSafety(unittest.TestCase):
    _tmp: tempfile.TemporaryDirectory[str]
    root: Path
    report: object

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        _m5_parquet(cls.root, bars=450)
        sample = _sample_result(5)
        diag = {"risk_journal_entries": 2, "risk_accepted": 1, "risk_rejected": 1, "rejection_reasons": {"cooldown": 1}}
        with patch(
            "tradingbot.backtest.phase26b_controlled_validation.run_backtest_on_frame",
            new=AsyncMock(return_value=(sample, diag)),
        ):
            cls.report = run_phase26b_collection(
                base_dir=cls.root, max_bars=400, min_bars=350, stress_bars=350, quick_mode=True
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_no_mt5_or_credentials(self) -> None:
        self.assertFalse(self.report.safety["MT5_STARTED"])
        self.assertFalse(self.report.safety["ENV_ACCESSED"])
        self.assertFalse(self.report.safety["CREDENTIALS_ACCESSED"])
        self.assertFalse(self.report.safety["SYMBOL_SELECT"])

    def test_artifacts_created(self) -> None:
        self.assertTrue((self.root / PHASE26B_FINAL_JSON).is_file())
        self.assertTrue((self.root / PHASE26B_BASELINE_JSON).is_file())

    def test_cost_gate_false(self) -> None:
        self.assertFalse(self.report.cost_gate["cost_adjusted_metrics"])

    def test_economic_validation_blocked(self) -> None:
        self.assertEqual(self.report.economic_validation["status"], ECONOMIC_VALIDATION_STATUS)

    def test_validation_class_research_only(self) -> None:
        data = json.loads((self.root / PHASE26B_BASELINE_JSON).read_text())
        self.assertEqual(data["validation_class"], VALIDATION_CLASS)

    def test_reproducibility_deterministic(self) -> None:
        repro = json.loads((self.root / "logs" / "phase26b_reproducibility.json").read_text())
        self.assertTrue(repro.get("deterministic"))

    def test_skipped_analyses_not_successful(self) -> None:
        wf = json.loads((self.root / "logs" / "phase26b_walkforward_results.json").read_text())
        self.assertEqual(wf.get("status"), "SKIPPED")

    def test_immutability(self) -> None:
        self.assertTrue(self.report.immutability_ok)

    def test_spread_stress_labeled_synthetic(self) -> None:
        empty = BacktestResult(config=BacktestConfig(), initial_balance=1000.0, final_balance=1000.0, trades=[])
        idx = pd.date_range("2024-01-01", periods=50, freq="5min", tz="UTC")
        df = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]}, index=idx[:1])
        frozen = build_frozen_baseline_configuration()
        with patch(
            "tradingbot.backtest.phase26b_controlled_validation.run_backtest_on_frame",
            new=AsyncMock(return_value=(empty, {})),
        ):
            data = asyncio.run(run_spread_stress(df, frozen))
        self.assertIn("SYNTHETIC", data["stress_type"])
        self.assertEqual(len(data["scenarios"]), 5)

    def test_no_silent_mapping(self) -> None:
        from tradingbot.backtest.dataset_contract import InstrumentContractError, resolve_broker_symbol_for_dataset

        with self.assertRaises(InstrumentContractError):
            resolve_broker_symbol_for_dataset("XAUUSD", configured_symbol=PRIMARY_SYMBOL, dataset_symbol_map={})


class TestPhase26BRecovery(unittest.TestCase):
    def test_recovery_report_from_temp_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / "logs"
            logs.mkdir()
            baseline = {
                "configuration_fingerprint": "abc",
                "dataset": {"filename": "XAUUSD_M5_183d.parquet"},
                "data_quality": {"bars_used": 100, "date_start": "2026-01-01", "date_end": "2026-01-02"},
                "logic_validation": {"risk_journal_entries": 0},
                "metrics": {"total_trades": 0, "win_rate_pct": 0.0, "net_profit": 0, "expectancy": 0.0, "max_drawdown_pct": 0.0},
                "cost_assumptions": {"spread_mode": "AUTO", "commission_status": "ZERO"},
            }
            (logs / "phase26b_baseline_results.json").write_text(json.dumps(baseline), encoding="utf-8")
            (logs / "phase26b_walkforward_results.json").write_text(
                json.dumps({"periods": [{"label": "TRAIN"}, {"label": "VALIDATION"}, {"label": "OOS"}]}),
                encoding="utf-8",
            )
            (logs / "phase26b_reproducibility.json").write_text(
                json.dumps({"deterministic": True, "run1": {}, "run2": {}}),
                encoding="utf-8",
            )
            report = build_phase26b_recovery_report(root)
            self.assertEqual(report["recovery_mode"], "READ_ONLY_REUSE")
            self.assertIn("baseline", report["completed_items"])
            self.assertEqual(report["newly_computed_results"], [])

            out = recover_phase26b(root)
            self.assertTrue((root / PHASE26B_RECOVERY_JSON).is_file())
            self.assertEqual(out["phase"], "26B")


if __name__ == "__main__":
    unittest.main()
