"""Phase 9.1 production dataset build tests."""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import dataset_v2_path, reports_dir
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor
from tradingbot.ml.dataset.phase9_production_build import (
    Phase91ProductionBuilder,
    archive_deprecated_v1,
)
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, DatasetBuildConfig
from tradingbot.ml.dataset.splitter import assign_purged_split_column, verify_chronological_splits
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry.registry import feature_names

DATASET_PKG = ROOT / "tradingbot" / "ml" / "dataset"
PHASE91_FILES = ("phase9_production_build.py", "sparse_event_builder.py")
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
    "MetaTrader5",
)
TEST_MIN_SAMPLES = 80


def _scan_files(filenames: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for name in filenames:
        path = DATASET_PKG / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            else:
                continue
            for module in mods:
                for prefix in FORBIDDEN:
                    if module.startswith(prefix) or module == prefix:
                        violations.append(f"{name}: {module}")
    return violations


def _synthetic_labeled_dataset(n: int = 200, *, seed: int = 7) -> pd.DataFrame:
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
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    df = pd.DataFrame(rows)
    df = assign_purged_split_column(df, purge_bars=72, timeframe="M5")
    return df[df["split"] != "purge"].copy()


class TestPhase91ForbiddenImports(unittest.TestCase):
    def test_no_forbidden_imports(self):
        violations = _scan_files(PHASE91_FILES)
        self.assertEqual(violations, [], msg=str(violations))


class TestPhase91FeatureCount(unittest.TestCase):
    def test_forty_five_features_present(self):
        df = _synthetic_labeled_dataset(150)
        expected = feature_names()
        present = [c for c in expected if c in df.columns]
        self.assertEqual(len(present), 45)

    def test_critical_columns_present(self):
        df = _synthetic_labeled_dataset(100)
        critical = [
            "timestamp",
            "label",
            "split",
            "event_type",
            "event_id",
            "risk_unit",
            "stop_loss",
            "take_profit",
            "entry_price",
            "direction",
        ]
        for col in critical:
            self.assertIn(col, df.columns, msg=f"missing {col}")


class TestPhase91NoLeakage(unittest.TestCase):
    def test_clean_dataset_passes_leakage(self):
        df = _synthetic_labeled_dataset(500)
        audit = DatasetLeakageAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(audit.status, "pass")

    def test_timestamp_leakage_fails(self):
        df = _synthetic_labeled_dataset(100)
        df["timestamp"] = pd.to_datetime(df["event_time"], utc=True) + pd.Timedelta(minutes=10)
        audit = DatasetLeakageAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(audit.status, "fail")


class TestPhase91SplitCorrectness(unittest.TestCase):
    def test_chronological_splits(self):
        df = _synthetic_labeled_dataset(1200)
        self.assertTrue(verify_chronological_splits(df))
        splits = set(df["split"].unique())
        self.assertTrue({"train", "validation", "test"}.issubset(splits))


class TestPhase91DeterministicFingerprint(unittest.TestCase):
    def test_same_data_same_hash(self):
        df = _synthetic_labeled_dataset(200, seed=11)
        cfg = DatasetBuildConfig()
        h1 = compute_dataset_fingerprint(df, cfg).dataset_hash
        h2 = compute_dataset_fingerprint(df.sort_values("timestamp"), cfg).dataset_hash
        self.assertEqual(h1, h2)


class TestPhase91ArchiveV1(unittest.TestCase):
    def test_archive_moves_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DatasetStore(tmp)
            placeholder = pd.DataFrame(
                {
                    "timestamp": pd.date_range("2024-01-01", periods=10, freq="5min", tz="UTC"),
                    "open": 2000.0,
                    "high": 2001.0,
                    "low": 1999.0,
                    "close": 2000.5,
                    "volume": 100,
                    "dataset_schema_version": "1.0",
                }
            )
            store.store("XAUUSD", "M5", placeholder)
            archived = archive_deprecated_v1("XAUUSD", "M5", tmp)
            self.assertIsNotNone(archived)
            self.assertFalse(store.resolve_path("XAUUSD", "M5").is_file())


class TestPhase91ReportGeneration(unittest.TestCase):
    def test_reports_written_on_success_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _synthetic_labeled_dataset(200)
            store = DatasetStore(tmp)
            store.store("XAUUSD", "M5", source)
            from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder

            v2 = ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
            self.assertIn(v2.status, ("pass", "warn"))
            df = store.load_v2("XAUUSD", "M5")
            assert df is not None

            builder = Phase91ProductionBuilder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES)
            feat_val = builder._validate_features(df)
            self.assertEqual(feat_val["present_count"], 45)
            self.assertEqual(feat_val["status"], "pass")


@unittest.skipUnless(
    dataset_v2_path("XAUUSD", "M5", ROOT / "data").is_file(),
    "production v2 dataset not built yet",
)
class TestPhase91ProductionDatasetOnDisk(unittest.TestCase):
    """Integration checks against real 5Y-built dataset when present."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.df = DatasetStore(ROOT / "data").load_v2("XAUUSD", "M5")
        assert cls.df is not None

    def test_row_count_sufficient(self):
        assert self.df is not None
        self.assertGreaterEqual(len(self.df), 500)

    def test_feature_count_45(self):
        assert self.df is not None
        present = [c for c in feature_names() if c in self.df.columns]
        self.assertEqual(len(present), 45)

    def test_labels_and_splits_exist(self):
        assert self.df is not None
        self.assertIn("label", self.df.columns)
        self.assertIn("split", self.df.columns)
        self.assertTrue({"train", "validation", "test"}.issubset(set(self.df["split"])))

    def test_leakage_pass(self):
        assert self.df is not None
        audit = DatasetLeakageAuditor().audit(self.df, "XAUUSD", "M5")
        self.assertEqual(audit.status, "pass")

    def test_reports_exist(self):
        rep = reports_dir(ROOT / "data")
        for name in (
            "dataset_build_report.json",
            "dataset_quality_report.json",
            "leakage_report.json",
            "label_quality_report.json",
        ):
            path = rep / name
            self.assertTrue(path.is_file(), msg=f"missing {name}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsInstance(payload, dict)
            self.assertGreater(len(payload), 0)


if __name__ == "__main__":
    unittest.main()
