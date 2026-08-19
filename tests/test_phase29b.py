"""Phase 29B — WPSQF production integration tests."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

import pandas as pd

from tradingbot.domain.enums import SignalDirection
from tradingbot.domain.models import TradingSignal
from tradingbot.services.signal_filter_log import clear_log, get_rejections, log_rejection
from tradingbot.services.signal_filter_mode import (
    DEFAULT_THRESHOLD,
    SignalFilterMode,
    resolve_signal_filter_mode,
    resolve_wpsqf_threshold,
)
from tradingbot.services.winner_population_signal_quality_filter import WinnerPopulationSignalQualityFilter
from tradingbot.services.wpsqf_calibration import WINNER_CALIBRATION
from tradingbot.services.wpsqf_scoring import false_signal_score, market_context_score, signal_quality_score

PHASE_DIR = Path(__file__).resolve().parents[1] / "tradingbot" / "ml" / "research" / "phase29b"

DELIVERABLES = [
    "wpsqf_service.json",
    "integration_validation.json",
    "performance_validation.json",
    "latency_validation.json",
    "determinism_validation.json",
    "backward_compatibility.json",
    "signal_filter_log.json",
    "before_after_comparison.json",
    "production_validation.json",
    "phase29b_final_report.json",
]

VERDICTS = {"PRODUCTION_INTEGRATION_VALIDATED", "PRODUCTION_INTEGRATION_NEEDS_REVIEW"}


class TestPhase29B(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (PHASE_DIR / "phase29b_final_report.json").is_file():
            from tradingbot.ml.research.phase29b.run_investigation import run_phase29b

            run_phase29b()

    def test_deliverables_exist(self) -> None:
        for name in DELIVERABLES:
            self.assertTrue((PHASE_DIR / name).is_file(), msg=name)

    def test_signal_filter_mode_defaults(self) -> None:
        old = os.environ.pop("TRADINGBOT_SIGNAL_FILTER", None)
        try:
            self.assertEqual(resolve_signal_filter_mode(), SignalFilterMode.OFF)
        finally:
            if old is not None:
                os.environ["TRADINGBOT_SIGNAL_FILTER"] = old

    def test_wpsqf_threshold_default(self) -> None:
        old = os.environ.pop("TRADINGBOT_WPSQF_THRESHOLD", None)
        try:
            self.assertEqual(resolve_wpsqf_threshold(), DEFAULT_THRESHOLD)
        finally:
            if old is not None:
                os.environ["TRADINGBOT_WPSQF_THRESHOLD"] = old

    def test_calibration_frozen(self) -> None:
        self.assertIn("adx", WINNER_CALIBRATION)
        self.assertIn("confidence", WINNER_CALIBRATION)
        self.assertGreater(WINNER_CALIBRATION["adx"], 0)

    def test_scoring_deterministic(self) -> None:
        features = {
            "adx": 25.0,
            "confidence": 0.9,
            "false_signal_score": 20.0,
            "context_score": 60.0,
            "trend_aligned": True,
            "direction": "BUY",
            "rsi": 55,
            "atr_percentile": 50,
            "range_compression": 0.8,
            "volume_percentile": 50,
            "session": "Overlap",
            "hour_utc": 14,
            "ema20_distance_pct": 0.05,
            "regime": "TREND",
        }
        s1 = signal_quality_score(features)
        s2 = signal_quality_score(features)
        self.assertEqual(s1, s2)
        self.assertTrue(0 <= s1 <= 100)

    def test_filter_rejects_below_threshold(self) -> None:
        filt = WinnerPopulationSignalQualityFilter(threshold=99.0)
        signal = TradingSignal(
            symbol="XAUUSD",
            timeframe="M5",
            direction=SignalDirection.BUY,
            confidence=0.5,
            stop_loss=1990.0,
            take_profit=2010.0,
            strategy_name="test",
            metadata={"confidence": 0.5, "regime": "RANGE"},
        )
        closed = pd.DataFrame(
            {
                "open": [2000.0] * 80,
                "high": [2001.0] * 80,
                "low": [1999.0] * 80,
                "close": [2000.0] * 80,
                "volume": [100.0] * 80,
            },
            index=pd.date_range("2026-01-01", periods=80, freq="5min", tz="UTC"),
        )
        clear_log()
        result = filt.evaluate(signal, closed)
        self.assertFalse(result.allowed)
        self.assertIsNotNone(result.reject_reason)
        self.assertEqual(len(get_rejections()), 1)

    def test_rejection_log_fields(self) -> None:
        clear_log()
        log_rejection(
            {
                "timestamp": "2026-01-01T00:00:00+00:00",
                "symbol": "XAUUSD",
                "direction": "BUY",
                "ml_confidence": 0.8,
                "signal_quality_score": 70.0,
                "false_signal_score": 30.0,
                "market_context_score": 55.0,
                "trend_aligned": True,
                "reject_reason": "below threshold",
                "threshold": 77.56,
            }
        )
        rec = get_rejections()[0]
        for key in (
            "timestamp",
            "symbol",
            "direction",
            "ml_confidence",
            "signal_quality_score",
            "false_signal_score",
            "market_context_score",
            "trend_aligned",
            "reject_reason",
            "threshold",
        ):
            self.assertIn(key, rec)

    def test_production_validation_passes(self) -> None:
        pv = json.loads((PHASE_DIR / "production_validation.json").read_text(encoding="utf-8"))
        self.assertFalse(pv.get("strategy_logic_modified"))
        self.assertFalse(pv.get("ml_models_modified"))

    def test_verdict_valid(self) -> None:
        report = json.loads((PHASE_DIR / "phase29b_final_report.json").read_text(encoding="utf-8"))
        self.assertIn(report.get("verdict"), VERDICTS)


if __name__ == "__main__":
    unittest.main()
