"""Phase 42 tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TestPhase42(unittest.TestCase):
    def test_event_bias_report(self) -> None:
        from tradingbot.ml.research.phase42.event_bias_audit import event_bias_report

        df = pd.DataFrame({
            "event_type": ["session_transition"] * 80 + ["trading_session"] * 20,
            "label_v3": [1, 0] * 50,
            "label_changed": [0, 1] * 50,
        })
        rep = event_bias_report(df)
        self.assertEqual(rep["verdict"], "SEVERE_EVENT_BIAS")

    def test_build_dataset_v4_smoke(self) -> None:
        from tradingbot.ml.research.phase42.feature_parity import build_dataset_v4

        candles = pd.DataFrame({
            "open": [100.0 + i * 0.01 for i in range(120)],
            "high": [100.5 + i * 0.01 for i in range(120)],
            "low": [99.5 + i * 0.01 for i in range(120)],
            "close": [100.2 + i * 0.01 for i in range(120)],
            "volume": [10] * 120,
        }, index=pd.date_range("2025-01-01", periods=120, freq="5min", tz="UTC"))
        df = pd.DataFrame({
            "timestamp": [candles.index[70]],
            "label_v3": [1],
            "spread_pips": [0.0],
            "spread_zscore": [0.0],
            "spread_spike": [0.0],
        })
        out = build_dataset_v4(df, candles)
        self.assertIn("dataset_version", out.columns)

    def test_deliverables(self) -> None:
        report = PROJECT_ROOT / "phase42_final_report.json"
        if not report.exists():
            self.skipTest("phase42 not run")
        data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data["phase"], "42")


if __name__ == "__main__":
    unittest.main()
