"""Phase 8.2 dataset quality and research audit tests (no MT5 required)."""

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

from tradingbot.ml.data.paths import (
    dataset_release_dir,
    feature_quality_report_path,
    label_quality_report_path,
    research_audit_report_path,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.feature_analysis import analyze_features
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.label_analysis import analyze_label_distribution
from tradingbot.ml.dataset.label_research import run_label_research
from tradingbot.ml.dataset.regime_analysis import analyze_regimes
from tradingbot.ml.dataset.release_manager import DatasetReleaseManager
from tradingbot.ml.dataset.research_audit import DatasetResearchAudit
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION, DatasetBuildConfig
from tradingbot.ml.dataset.session_analysis import analyze_sessions
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.dataset.validation import validate_dataset_schema
from tradingbot.ml.features import feature_names

DATASET_PKG = ROOT / "tradingbot" / "ml" / "dataset"
PHASE82_FILES = (
    "research_audit.py",
    "label_analysis.py",
    "feature_analysis.py",
    "session_analysis.py",
    "regime_analysis.py",
    "label_research.py",
    "release_manager.py",
)
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
    "MetaTrader5",
)


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


def _ohlcv(n: int = 200, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = 2300 + np.cumsum(rng.normal(0, 0.3, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": rng.integers(5, 50, n),
        },
        index=idx,
    )


def _synthetic_dataset(n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(7)
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
        "split": rng.choice(["train", "validation", "test"], size=n),
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "session_asia": (ts.hour < 7).astype(int),
        "session_london": ((ts.hour >= 7) & (ts.hour < 12)).astype(int),
        "session_ny": ((ts.hour >= 12) & (ts.hour < 17)).astype(int),
        "session_off": (ts.hour >= 17).astype(int),
        "volatility_regime": rng.choice([0.0, 0.5, 1.0], size=n),
        "trend_strength": rng.uniform(0, 80, n),
        "h4_trend_bias": rng.choice([-1.0, 0.0, 1.0], size=n),
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    rows["dead_feature"] = 42.0
    return pd.DataFrame(rows)


class TestSchemaAudit(unittest.TestCase):
    def test_dataset_schema_audit(self):
        df = _synthetic_dataset(80)
        errors = validate_dataset_schema(df)
        self.assertEqual(errors, [], msg=str(errors))
        overview = DatasetResearchAudit("XAUUSD", "M5").build_overview(df)
        self.assertEqual(overview["rows"], 80)
        self.assertGreater(overview["features_count"], 40)


class TestLabelDistribution(unittest.TestCase):
    def test_label_distribution_calculation(self):
        df = _synthetic_dataset(100)
        report = analyze_label_distribution(df, "XAUUSD", "M5")
        self.assertEqual(report.total_samples, 100)
        self.assertIn("0", report.class_distribution)
        self.assertIn("1", report.class_distribution)
        self.assertGreater(report.win_rate, 0)
        self.assertIn(report.status, ("healthy", "acceptable", "warning"))


class TestFeatureMissing(unittest.TestCase):
    def test_feature_missing_detection(self):
        df = _synthetic_dataset(50)
        df = df.drop(columns=["spread_zscore"])
        report = analyze_features(df, "XAUUSD", "M5")
        self.assertIn("spread_zscore", report.missing_features)
        self.assertEqual(report.features["spread_zscore"]["missing"], 100.0)


class TestConstantFeature(unittest.TestCase):
    def test_constant_feature_detection(self):
        df = _synthetic_dataset(50)
        df["atr_14"] = 1.5
        report = analyze_features(df, "XAUUSD", "M5")
        self.assertIn("atr_14", report.constant_features)
        self.assertTrue(report.features["atr_14"]["constant"])


class TestCorrelation(unittest.TestCase):
    def test_correlation_calculation(self):
        df = _synthetic_dataset(100)
        df.loc[df["label"].isin([0, 1]), "rsi_14"] = df.loc[df["label"].isin([0, 1]), "label"].astype(float)
        report = analyze_features(df, "XAUUSD", "M5")
        self.assertGreater(abs(report.features["rsi_14"]["correlation"]), 0.9)


class TestMutualInformation(unittest.TestCase):
    def test_mutual_information_calculation(self):
        df = _synthetic_dataset(200)
        df["label"] = (df["rsi_14"] > df["rsi_14"].median()).astype(int)
        report = analyze_features(df, "XAUUSD", "M5")
        self.assertGreater(report.features["rsi_14"]["mutual_information"], 0)


class TestSessionAnalysis(unittest.TestCase):
    def test_session_analysis(self):
        df = _synthetic_dataset(100)
        report = analyze_sessions(df, "XAUUSD", "M5")
        self.assertIn("London", report.sessions)
        self.assertGreater(report.sessions["London"]["samples"], 0)


class TestRegimeAnalysis(unittest.TestCase):
    def test_regime_analysis(self):
        df = _synthetic_dataset(100)
        report = analyze_regimes(df, "XAUUSD", "M5")
        self.assertIn("low", report.volatility)
        self.assertIn("weak", report.trend)
        self.assertIn("bullish", report.market_condition)


class TestResearchReport(unittest.TestCase):
    def test_research_report_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _synthetic_dataset(80)
            DatasetStore(tmp).store("XAUUSD", "M5", df)
            result = DatasetResearchAudit("XAUUSD", "M5", base_dir=tmp).run_full_audit(
                include_label_research=False
            )
            self.assertIn(result.status, ("pass", "warn"))
            self.assertIn("rows", result.overview)
            self.assertTrue(research_audit_report_path("XAUUSD", "M5", tmp).is_file())
            self.assertTrue(label_quality_report_path("XAUUSD", "M5", tmp).is_file())


class TestFingerprint(unittest.TestCase):
    def test_fingerprint_generation(self):
        df = _synthetic_dataset(60)
        cfg = DatasetBuildConfig()
        fp1 = compute_dataset_fingerprint(df, cfg)
        fp2 = compute_dataset_fingerprint(df, cfg)
        self.assertEqual(fp1.dataset_hash, fp2.dataset_hash)
        self.assertTrue(fp1.feature_hash)


class TestReleaseCreation(unittest.TestCase):
    def test_release_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _synthetic_dataset(60)
            audit = DatasetResearchAudit("XAUUSD", "M5", base_dir=tmp).run_full_audit(
                include_label_research=False
            )
            release = DatasetReleaseManager("XAUUSD", "M5", base_dir=tmp).create_release(
                df, version="1", research_report=audit.to_dict()
            )
            release_dir = dataset_release_dir("XAUUSD", "M5", "1", tmp)
            self.assertTrue(release_dir.is_dir())
            self.assertTrue((release_dir / "dataset.parquet").is_file())
            self.assertTrue((release_dir / "fingerprint.json").is_file())
            self.assertTrue((release_dir / "feature_schema.json").is_file())
            self.assertTrue((release_dir / "label_config.json").is_file())
            self.assertTrue((release_dir / "research_report.json").is_file())
            fp = json.loads((release_dir / "fingerprint.json").read_text(encoding="utf-8"))
            self.assertEqual(len(fp["parquet_sha256"]), 64)
            self.assertEqual(release.dataset_hash, fp["parquet_sha256"])


class TestLabelResearch(unittest.TestCase):
    def test_label_research_with_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = _ohlcv(200)
            CandleStore(tmp).store("XAUUSD", "M5", candles)
            df = _synthetic_dataset(30)
            df["event_time"] = candles.index[:30]
            report = run_label_research(df, "XAUUSD", "M5", base_dir=tmp)
            self.assertEqual(len(report.simulations), 9)
            self.assertIn("win_rate", report.simulations[0])


class TestForbiddenImports(unittest.TestCase):
    def test_forbidden_import_scan(self):
        violations = _scan_files(PHASE82_FILES)
        self.assertEqual(violations, [], msg=str(violations))


if __name__ == "__main__":
    unittest.main()
