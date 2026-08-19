"""Phase 22O — full automatic dataset maintenance tests."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_orchestrator():
    path = ROOT / "scripts" / "live_dataset_orchestrator.py"
    spec = importlib.util.spec_from_file_location("live_dataset_orchestrator", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestPhase22O(unittest.TestCase):
    def setUp(self):
        os.environ["USE_ML_KERNEL"] = "true"
        os.environ["ML_AUTO_DATASET_REFRESH"] = "true"
        os.environ["ML_DATASET_REFRESH_THRESHOLD_HOURS"] = "48"

    def test_needs_refresh_when_lag_above_threshold(self):
        mod = _load_orchestrator()
        info = {"lag_hours": 100.0, "dataset_exists": True}
        self.assertTrue(mod.needs_refresh(info, threshold_hours=48.0))
        info["lag_hours"] = 10.0
        self.assertFalse(mod.needs_refresh(info, threshold_hours=48.0))

    def test_pre_live_skips_when_fresh(self):
        mod = _load_orchestrator()
        fresh = {
            "symbol": "XAUUSD",
            "dataset_exists": True,
            "lag_hours": 1.0,
            "dataset_max_utc": "2026-07-01T00:00:00+00:00",
            "live_max_utc": "2026-07-01T01:00:00+00:00",
        }
        with patch.object(mod, "measure_dataset_lag", return_value=fresh):
            report = mod.run_pre_live_maintenance()
        self.assertEqual(report["action"], "none")
        self.assertFalse(report["refresh_attempted"])

    def test_pre_live_runs_refresh_when_stale(self):
        mod = _load_orchestrator()
        stale = {
            "symbol": "XAUUSD",
            "dataset_exists": True,
            "lag_hours": 120.0,
            "dataset_max_utc": "2026-06-01T00:00:00+00:00",
            "live_max_utc": "2026-07-01T00:00:00+00:00",
        }
        after = dict(stale)
        after["dataset_max_utc"] = "2026-07-01T00:00:00+00:00"
        after["lag_hours"] = 0.0
        with patch.object(mod, "measure_dataset_lag", side_effect=[stale, after]):
            with patch.object(mod, "run_scheduled_refresh", return_value={"exit_code": 0, "success": True, "command": []}):
                report = mod.run_pre_live_maintenance()
        self.assertEqual(report["action"], "refreshed")
        self.assertTrue(report["refresh_success"])

    def test_pre_live_continues_on_refresh_failure(self):
        mod = _load_orchestrator()
        stale = {"dataset_exists": True, "lag_hours": 120.0}
        with patch.object(mod, "measure_dataset_lag", return_value=stale):
            with patch.object(mod, "run_scheduled_refresh", return_value={"exit_code": 1, "success": False, "command": []}):
                report = mod.run_pre_live_maintenance()
        self.assertEqual(report["action"], "refresh_failed_continue")
        self.assertIsNotNone(report.get("warning"))

    def test_pipeline_cache_reloads_dataset_after_reset(self):
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.integration.pipeline_cache import PipelineCache

        mod = _load_orchestrator()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ds_dir = base / "ml" / "datasets"
            ds_dir.mkdir(parents=True)
            ts_old = pd.Timestamp("2026-06-01T12:00:00", tz="UTC")
            ts_new = pd.Timestamp("2026-07-01T12:00:00", tz="UTC")
            path = ds_dir / "XAUUSD_M5_dataset_v2.parquet"

            def _write(ts: pd.Timestamp, slope: float) -> None:
                df = pd.DataFrame(
                    {
                        "timestamp": [ts],
                        "ema50_slope": [slope],
                        "candle_direction": [1],
                        "structure_distance": [0.5],
                        "label": [0],
                        "split": ["train"],
                    },
                )
                df.to_parquet(path, index=False)

            _write(ts_old, 0.1)
            PipelineCache.reset()
            max_old = mod.pipeline_cache_dataset_max(base_dir=str(base))
            store = DatasetStore(str(base))
            row_old = store.load_v2("XAUUSD", "M5").iloc[0]["ema50_slope"]

            _write(ts_new, 0.9)
            PipelineCache.reset()
            max_new = mod.pipeline_cache_dataset_max(base_dir=str(base))
            row_new = store.load_v2("XAUUSD", "M5").iloc[0]["ema50_slope"]

            self.assertEqual(max_old, ts_old.isoformat())
            self.assertEqual(max_new, ts_new.isoformat())
            self.assertEqual(float(row_old), 0.1)
            self.assertEqual(float(row_new), 0.9)


if __name__ == "__main__":
    unittest.main()
