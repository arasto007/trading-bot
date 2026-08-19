"""Phase 9.1.5 deep dataset audit tests (read-only)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.dataset.deep_audit import (
    HEALTH_PASS_THRESHOLD,
    DatasetDeepAuditor,
    deep_audit_report_path,
)
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, Label
from tradingbot.ml.dataset.splitter import assign_purged_split_column
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry import feature_names

TEST_MIN = 120


def _synthetic_v2(n: int = 200, *, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    labels = rng.choice([0, 1, -1], size=n, p=[0.45, 0.45, 0.10])
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": rng.choice(["bos", "choch", "fvg"], size=n),
        "event_time": ts,
        "event_id": [f"e{i}" for i in range(n)],
        "timeframe_role": "entry_execution",
        "entry_price": 2300.0 + rng.normal(0, 1, n),
        "direction": rng.choice([1, -1], size=n),
        "stop_loss": 2290.0,
        "take_profit": 2320.0,
        "label": labels,
        "future_window_bars": 72,
        "tp_hit": labels == 1,
        "sl_hit": labels == 0,
        "mfe": rng.uniform(0, 2, n),
        "mae": rng.uniform(0, 1, n),
        "future_return": rng.normal(0, 0.01, n),
        "risk_unit": rng.uniform(1, 5, n),
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "volatility_regime": rng.choice([0.0, 0.5, 1.0], size=n),
        "trend_strength": rng.uniform(10, 80, n),
        "h4_trend_bias": rng.choice([-1.0, 0.0, 1.0], size=n),
        "bos_state": rng.choice([0.0, 1.0], size=n),
        "h4_structure_direction": rng.choice([-1.0, 0.0, 1.0], size=n),
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    df = pd.DataFrame(rows)
    df = assign_purged_split_column(df, purge_bars=72, timeframe="M5")
    return df[df["split"] != "purge"].copy()


class TestRejectsNanLabels(unittest.TestCase):
    def test_nan_label_is_critical(self):
        df = _synthetic_v2(150)
        df.loc[df.index[:5], "label"] = np.nan
        report = DatasetDeepAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(report.status, "FAIL")
        self.assertTrue(any("nan_in_label" in c for c in report.critical_issues))


class TestSharedBarTimestamps(unittest.TestCase):
    def test_shared_bar_timestamps_are_warning_not_critical(self):
        df = _synthetic_v2(100)
        extra = df.iloc[0:1].copy()
        extra["event_id"] = "extra_event_same_bar"
        extra["event_type"] = "fvg"
        combined = pd.concat([df, extra], ignore_index=True)
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        report = DatasetDeepAuditor().audit(combined, "XAUUSD", "M5")
        self.assertFalse(any(c.startswith("duplicate_timestamp_event_id") for c in report.critical_issues))
        self.assertTrue(
            any("shared_bar_timestamps" in w for w in report.warnings)
            or report.checks["temporal"]["duplicate_timestamps"] >= 1
        )


class TestDetectsShuffledTimestamps(unittest.TestCase):
    def test_non_monotonic_timestamps_fail(self):
        df = _synthetic_v2(150)
        df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
        report = DatasetDeepAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(report.status, "FAIL")
        temporal = report.checks["temporal"]
        self.assertFalse(temporal["monotonic_increasing"])


class TestDetectsLeakagePatterns(unittest.TestCase):
    def test_timestamp_after_event_time_fails(self):
        df = _synthetic_v2(100)
        df["timestamp"] = pd.to_datetime(df["event_time"], utc=True) + pd.Timedelta(minutes=10)
        report = DatasetDeepAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(report.checks["leakage"]["status"], "fail")
        self.assertEqual(report.status, "FAIL")

    def test_split_overlap_fails(self):
        df = _synthetic_v2(200)
        df.loc[df["split"] == "validation", "timestamp"] = pd.to_datetime(
            df.loc[df["split"] == "train", "timestamp"].min(), utc=True
        )
        report = DatasetDeepAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(report.status, "FAIL")
        self.assertTrue(any("split" in c for c in report.critical_issues))


class TestSplitOrdering(unittest.TestCase):
    def test_valid_splits_pass_chronology(self):
        df = _synthetic_v2(400)
        report = DatasetDeepAuditor().audit(df, "XAUUSD", "M5")
        splits = report.checks["splits"]
        self.assertTrue(splits["chronological"])
        self.assertIn("train", splits["distribution"])


class TestDeterministicOutput(unittest.TestCase):
    def test_same_input_same_health_score(self):
        df = _synthetic_v2(180, seed=99)
        a = DatasetDeepAuditor().audit(df, "XAUUSD", "M5").to_dict()
        b = DatasetDeepAuditor().audit(df.sort_values("timestamp"), "XAUUSD", "M5").to_dict()
        self.assertEqual(a["health_score"], b["health_score"])
        self.assertEqual(a["status"], b["status"])


class TestHealthScoreAndReport(unittest.TestCase):
    def test_health_score_exists(self):
        df = _synthetic_v2(200)
        report = DatasetDeepAuditor().audit(df, "XAUUSD", "M5")
        self.assertGreaterEqual(report.health_score, 0.0)
        self.assertLessEqual(report.health_score, 100.0)
        self.assertIn("structure", report.category_scores)

    def test_report_json_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DatasetStore(tmp)
            store.store_v2("XAUUSD", "M5", _synthetic_v2(200))
            auditor = DatasetDeepAuditor()
            report, path = auditor.run_and_save("XAUUSD", "M5", tmp)
            self.assertEqual(path, deep_audit_report_path(tmp))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("health_score", payload)
            self.assertIn("checks", payload)
            self.assertIn(payload["status"], ("PASS", "FAIL"))
            self.assertEqual(set(payload["checks"].keys()), {
                "structure", "temporal", "labels", "features", "splits", "leakage"
            })


class TestInfDetection(unittest.TestCase):
    def test_inf_values_fail(self):
        df = _synthetic_v2(100)
        df.loc[df.index[0], "rsi_14"] = np.inf
        report = DatasetDeepAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(report.status, "FAIL")
        self.assertTrue(any("inf_values" in c for c in report.critical_issues))


@unittest.skipUnless(
    (ROOT / "data" / "ml" / "datasets" / "XAUUSD_M5_dataset_v2.parquet").is_file(),
    "production v2 not on disk",
)
class TestProductionV2DeepAudit(unittest.TestCase):
    def test_production_dataset_audits(self):
        report, path = DatasetDeepAuditor().run_and_save("XAUUSD", "M5", ROOT / "data")
        self.assertTrue(path.is_file())
        self.assertGreater(report.row_count, 500)
        self.assertEqual(report.checks["structure"]["feature_count"], 45)
        self.assertEqual(report.checks["leakage"]["base_audit"]["status"], "pass")
        self.assertNotIn("nan_in_label", str(report.critical_issues))


if __name__ == "__main__":
    unittest.main()
