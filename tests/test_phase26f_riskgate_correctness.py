"""Phase 26F — RiskGate economics alias correctness tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG, merge_broker_catalog, resolve_backtest_economics
from tradingbot.backtest.phase26f_riskgate_correctness import (
    CODE_CHANGE,
    PHASE26F_JSON,
    run_phase26f_collection,
)
from tradingbot.backtest.risk import BacktestRiskGate
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.domain.broker_economics import lot_from_broker_economics
from tradingbot.domain.risk_logic import regime_position_multiplier


def _legacy_with_catalog() -> dict:
    legacy = load_legacy_config()
    legacy = merge_broker_catalog(legacy, {"XAUUSD_i": dict(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])})
    legacy["symbol_aliases"] = {"XAUUSD": PRIMARY_SYMBOL}
    return legacy


class TestPhase26FAliasResolution(unittest.TestCase):
    def test_xauusd_resolves_to_xauusd_i_economics(self) -> None:
        legacy = _legacy_with_catalog()
        resolved = resolve_broker_symbol("XAUUSD", legacy)
        self.assertEqual(resolved, PRIMARY_SYMBOL)
        econ = resolve_backtest_economics(resolved, legacy)
        self.assertIsNotNone(econ)
        assert econ is not None
        self.assertEqual(econ.symbol, "XAUUSD_i")

    def test_missing_economics_fails_closed(self) -> None:
        legacy = _legacy_with_catalog()
        gate = BacktestRiskGate(BacktestConfig(), legacy)
        lot = gate._position_size(1000.0, 2400.0, 2390.0, "EURUSD", regime="RANGING")
        self.assertEqual(lot, 0.0)

    def test_no_hardcoded_xauusd_i_in_risk_module(self) -> None:
        src = (Path(__file__).resolve().parents[1] / "tradingbot" / "backtest" / "risk.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('"XAUUSD_i"', src)
        self.assertNotIn("'XAUUSD_i'", src)

    def test_position_size_uses_alias_not_raw_symbol(self) -> None:
        legacy = _legacy_with_catalog()
        gate = BacktestRiskGate(BacktestConfig(), legacy)
        # Direct lookup on label still misses; _position_size must resolve alias.
        self.assertIsNone(resolve_backtest_economics("XAUUSD", legacy))
        lot = gate._position_size(
            1000.0,
            4018.27,
            4007.663,
            "XAUUSD",
            regime="STRONG_TREND_DOWN",
        )
        self.assertEqual(lot, 0.0)


class TestPhase26FCandidateLots(unittest.TestCase):
    """Lot expectations from Phase 26E candidate evidence."""

    _CASES = (
        (354, 4018.27, 4007.663, "STRONG_TREND_DOWN"),
        (355, 4021.41, 4007.5682500000003, "STRONG_TREND_DOWN"),
        (356, 4020.91, 4007.4922500000002, "VOLATILE"),
    )

    def test_candidates_raw_lot_below_min(self) -> None:
        legacy = _legacy_with_catalog()
        econ = resolve_backtest_economics("XAUUSD_i", legacy)
        assert econ is not None
        for _cursor, entry, sl, regime in self._CASES:
            lot, reason = lot_from_broker_economics(
                1000.0,
                0.005,
                entry,
                sl,
                econ,
                regime_multiplier=regime_position_multiplier(regime),
            )
            self.assertIsNone(lot)
            self.assertEqual(reason, "VOLUME_BELOW_MIN")

    def test_candidate_354_position_size_still_zero(self) -> None:
        legacy = _legacy_with_catalog()
        gate = BacktestRiskGate(BacktestConfig(), legacy)
        lot = gate._position_size(
            1000.0,
            4018.27,
            4007.663,
            "XAUUSD",
            regime="STRONG_TREND_DOWN",
        )
        self.assertEqual(lot, 0.0)


class TestPhase26FReplay(unittest.TestCase):
    def test_replay_when_artifacts_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / "logs" / "phase26e_riskgate_audit.json").is_file():
            self.skipTest("Phase 26E artifact missing")
        if not (root / "data" / "backtest" / "XAUUSD_M5_183d.parquet").is_file():
            self.skipTest("parquet missing")

        report = run_phase26f_collection(root)
        self.assertEqual(report["rejection_counts"]["after_phase26f"]["allowed"], 0)
        self.assertEqual(report["rejection_counts"]["after_phase26f"]["lot/min-volume"], 3)
        self.assertEqual(report["rejection_counts"]["after_phase26f"]["meta"], 10)
        self.assertEqual(report["rejection_counts"]["after_phase26f"]["atr"], 6)
        self.assertEqual(report["alias_fix_conclusion"], "rejection-reason-only")
        self.assertEqual(report["ev_eq_01"], "NOT_PROVEN")
        self.assertFalse(report["safety"]["RISKGATE_POLICY_CHANGED"])
        self.assertTrue((root / PHASE26F_JSON).is_file())

    def test_meta_and_atr_unchanged_vs_phase26e(self) -> None:
        root = Path(__file__).resolve().parents[1]
        e26 = root / "logs" / "phase26e_riskgate_audit.json"
        f26 = root / PHASE26F_JSON
        if not e26.is_file() or not f26.is_file():
            self.skipTest("artifacts missing")
        before = json.loads(e26.read_text(encoding="utf-8"))
        after = json.loads(f26.read_text(encoding="utf-8"))
        before_meta = [r for r in before["decision_table"] if r.get("meta_labeler") == "reject"]
        after_meta = [r for r in after["candidate_replay"] if r.get("meta_result") == "reject"]
        self.assertEqual(len(before_meta), 10)
        self.assertEqual(len(after_meta), 10)
        before_atr = [r for r in before["decision_table"] if r.get("atr_filter") == "reject"]
        after_atr = [r for r in after["candidate_replay"] if r.get("atr_result") == "reject"]
        self.assertEqual(len(before_atr), 6)
        self.assertEqual(len(after_atr), 6)


class TestPhase26FCodeChange(unittest.TestCase):
    def test_code_change_location(self) -> None:
        self.assertEqual(CODE_CHANGE["file"], "tradingbot/backtest/risk.py")
        self.assertEqual(CODE_CHANGE["function"], "BacktestRiskGate._position_size")


if __name__ == "__main__":
    unittest.main()
