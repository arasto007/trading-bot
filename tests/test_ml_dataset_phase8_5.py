"""Phase 8.5 dataset sanity and training-readiness tests (no MT5)."""

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

from tradingbot.ml.data.paths import dataset_v2_path, train_readiness_report_path
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.sanity_gate import DatasetSanityGate
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, DatasetBuildConfig
from tradingbot.ml.dataset.splitter import assign_purged_split_column, verify_chronological_splits
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.train_readiness_report import TrainReadinessAnalyzer
from tradingbot.ml.features import feature_names

DATASET_PKG = ROOT / "tradingbot" / "ml" / "dataset"
PHASE85_FILES = ("sanity_gate.py", "production_dataset_v2.py", "train_readiness_report.py")
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


def _synthetic_dataset(n: int = 200, *, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    labels = rng.choice([0, 1, -1], size=n, p=[0.45, 0.45, 0.10])
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": rng.choice(["bos", "choch", "fvg"], size=n),
        "event_time": ts - pd.Timedelta(minutes=5),
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
        "split": "train",
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "volatility_regime": rng.choice([0.0, 0.5, 1.0], size=n),
        "trend_strength": rng.uniform(10, 80, n),
        "h4_trend_bias": rng.choice([-1.0, 0.0, 1.0], size=n),
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    return pd.DataFrame(rows)


class TestNanRejection(unittest.TestCase):
    def test_reject_dataset_with_nan_spikes(self):
        df = _synthetic_dataset(150)
        for col in feature_names()[:10]:
            if col in df.columns:
                df.loc[df.index[:80], col] = np.nan
        gate = DatasetSanityGate(min_samples=TEST_MIN_SAMPLES, max_feature_nan_pct=1.0)
        report = gate.evaluate(df, "XAUUSD", "M5")
        self.assertTrue(report.blocked)
        self.assertTrue(any(i.code == "nan_spike" for i in report.issues))


class TestImbalancedLabels(unittest.TestCase):
    def test_reject_imbalanced_labels(self):
        df = _synthetic_dataset(150)
        df["label"] = 1
        gate = DatasetSanityGate(min_samples=TEST_MIN_SAMPLES, imbalance_fail=0.20)
        report = gate.evaluate(df, "XAUUSD", "M5")
        self.assertTrue(report.blocked)
        self.assertTrue(any(i.code == "label_imbalance" for i in report.issues))


class TestFeatureCorruption(unittest.TestCase):
    def test_detect_constant_feature(self):
        df = _synthetic_dataset(120)
        df["atr_14"] = 3.14
        gate = DatasetSanityGate(min_samples=TEST_MIN_SAMPLES)
        report = gate.evaluate(df, "XAUUSD", "M5")
        self.assertIn("atr_14", report.feature_health.get("constant_features", []))

    def test_detect_inf_corruption(self):
        df = _synthetic_dataset(120)
        df["rsi_14"] = np.inf
        gate = DatasetSanityGate(min_samples=TEST_MIN_SAMPLES)
        report = gate.evaluate(df, "XAUUSD", "M5")
        self.assertTrue(any(i.code == "inf_values" for i in report.issues))


class TestSplitStability(unittest.TestCase):
    def test_validate_chronological_split(self):
        df = _synthetic_dataset(200)
        df = assign_purged_split_column(df, purge_bars=72, timeframe="M5")
        df = df[df["split"] != "purge"]
        self.assertTrue(verify_chronological_splits(df))


class TestLeakageFree(unittest.TestCase):
    def test_leakage_blocks_training_ready(self):
        df = _synthetic_dataset(150)
        df["timestamp"] = pd.to_datetime(df["event_time"], utc=True) + pd.Timedelta(minutes=10)
        audit = DatasetLeakageAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(audit.status, "fail")
        readiness = TrainReadinessAnalyzer(min_samples=TEST_MIN_SAMPLES).analyze(df, "XAUUSD", "M5")
        self.assertEqual(readiness.leakage_check, "fail")
        self.assertFalse(readiness.recommended_for_training)


class TestDeterministicRebuild(unittest.TestCase):
    def test_same_input_same_fingerprint(self):
        df = _synthetic_dataset(200, seed=99)
        cfg = DatasetBuildConfig()
        fp1 = compute_dataset_fingerprint(df, cfg).dataset_hash
        fp2 = compute_dataset_fingerprint(df.sort_values("timestamp"), cfg).dataset_hash
        self.assertEqual(fp1, fp2)

    def test_v2_build_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = _synthetic_dataset(200, seed=42)
            DatasetStore(tmp).store("XAUUSD", "M5", source)
            builder = ProductionDatasetV2Builder(
                "XAUUSD",
                base_dir=tmp,
                min_samples=TEST_MIN_SAMPLES,
            )
            r1 = builder.build_v2()
            DatasetStore(tmp).resolve_v2_path("XAUUSD", "M5").unlink()
            r2 = builder.build_v2()
            self.assertEqual(r1.fingerprint["dataset_hash"], r2.fingerprint["dataset_hash"])


class TestV2Build(unittest.TestCase):
    def test_v2_dataset_build_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _synthetic_dataset(200))
            result = ProductionDatasetV2Builder(
                "XAUUSD",
                base_dir=tmp,
                min_samples=TEST_MIN_SAMPLES,
            ).build_v2()
            self.assertIn(result.status, ("pass", "warn"))
            self.assertTrue(dataset_v2_path("XAUUSD", "M5", tmp).is_file())
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            assert df is not None
            self.assertEqual(df.index.duplicated().sum() if isinstance(df.index, pd.DatetimeIndex) else 0, 0)
            if "timestamp" in df.columns:
                self.assertEqual(df["timestamp"].duplicated().sum(), 0)


class TestTrainReadinessReport(unittest.TestCase):
    def test_train_readiness_report_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _synthetic_dataset(200)
            report, path = TrainReadinessAnalyzer(min_samples=TEST_MIN_SAMPLES).analyze_and_save(
                df, "XAUUSD", "M5", tmp
            )
            self.assertEqual(path, train_readiness_report_path("XAUUSD", "M5", tmp))
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("dataset_valid", payload)
            self.assertIn("recommended_for_training", payload)
            self.assertIn(report.label_balance, ("ok", "imbalanced"))


class TestSanityGateBlocksBad(unittest.TestCase):
    def test_sanity_blocks_too_small_dataset(self):
        df = _synthetic_dataset(20)
        report = DatasetSanityGate(min_samples=TEST_MIN_SAMPLES).evaluate(df, "XAUUSD", "M5")
        self.assertTrue(report.blocked)


class TestForbiddenImports(unittest.TestCase):
    def test_no_forbidden_imports(self):
        violations = _scan_files(PHASE85_FILES)
        self.assertEqual(violations, [], msg=str(violations))


if __name__ == "__main__":
    unittest.main()
