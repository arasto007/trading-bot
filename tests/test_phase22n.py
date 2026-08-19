"""Phase 22N — automated ML data refresh tests."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.scheduled_ml_refresh import StoreSnapshot, verify_refresh


class TestPhase22N(unittest.TestCase):
    def test_verify_passes_healthy_snapshots(self):
        snap = StoreSnapshot(
            path="/tmp/x.parquet",
            exists=True,
            row_count=5000,
            max_timestamp_utc="2026-07-03T12:00:00+00:00",
            mtime_utc="2026-07-03T12:00:00+00:00",
            feature_count=120,
        )
        ds = StoreSnapshot(
            path="/tmp/d.parquet",
            exists=True,
            row_count=5724,
            max_timestamp_utc="2026-07-03T11:55:00+00:00",
            mtime_utc="2026-07-03T12:00:00+00:00",
            feature_count=120,
        )
        before = {"candle_store_m5": snap, "dataset_v2": ds}
        after = {
            "candle_store_m5": StoreSnapshot(
                path=snap.path,
                exists=True,
                row_count=5100,
                max_timestamp_utc="2026-07-04T12:00:00+00:00",
                mtime_utc="2026-07-04T12:00:00+00:00",
                feature_count=120,
            ),
            "dataset_v2": StoreSnapshot(
                path=ds.path,
                exists=True,
                row_count=5800,
                max_timestamp_utc="2026-07-04T11:55:00+00:00",
                mtime_utc="2026-07-04T12:00:00+00:00",
                feature_count=120,
            ),
        }
        passed, report = verify_refresh(before, after, symbol="XAUUSD", timeframe="M5")
        self.assertTrue(passed)
        self.assertTrue(report["candle_store_advanced"])
        self.assertTrue(report["dataset_advanced"])

    def test_verify_fails_on_regression(self):
        before = {
            "candle_store_m5": StoreSnapshot("/a", True, 100, "2026-07-01T00:00:00+00:00", None, 0),
            "dataset_v2": StoreSnapshot("/b", True, 1000, "2026-07-01T00:00:00+00:00", None, 50),
        }
        after = {
            "candle_store_m5": StoreSnapshot("/a", True, 100, "2026-06-01T00:00:00+00:00", None, 0),
            "dataset_v2": StoreSnapshot("/b", True, 100, "2026-06-01T00:00:00+00:00", None, 10),
        }
        passed, report = verify_refresh(before, after, symbol="XAUUSD", timeframe="M5")
        self.assertFalse(passed)
        self.assertIn("dataset_timestamp_regressed", report["errors"])

    def test_staleness_warning_does_not_block_verify_script(self):
        os.environ["USE_ML_KERNEL"] = "true"
        os.environ["ML_DATASET_MAX_LAG_HOURS"] = "0.001"
        with patch("scripts.verify_ml_live_ready._dataset_staleness_warning") as mock_warn:
            mock_warn.return_value = ("DATASET_STALE|WARN|lag 999h", {"lag_hours": 999.0})
            with patch("tradingbot.ml.integration.config.is_ml_kernel_enabled", return_value=False):
                from scripts.verify_ml_live_ready import main

                code = main()
                self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
