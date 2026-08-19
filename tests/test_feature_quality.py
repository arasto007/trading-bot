"""Phase 2.1 feature quality, registry, scaling, and reproducibility tests."""

from __future__ import annotations

import copy
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
    feature_build_manifest_path,
    feature_correlation_report_path,
    feature_quality_report_path,
    reports_dir,
    scaler_metadata_path,
    scalers_dir,
)
from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.features import FeatureBuilder, FeatureStore, feature_names, validate_integrity
from tradingbot.ml.features.base import FEATURE_SCHEMA_VERSION
from tradingbot.ml.features.quality import save_reports, validate_feature_dataframe
from tradingbot.ml.features.registry import export_json, validate_json_file
from tradingbot.ml.features.reproducibility import build_manifest, hash_dataframe, load_manifest
from tradingbot.ml.features.scaling import fit_scaler_metadata, load_scaler_metadata, save_scaler_metadata, transform_with_metadata


def _ohlcv(n: int = 130, freq: str = "5min", seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    close = 2300 + np.cumsum(rng.normal(0, 0.3, n))
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + rng.uniform(0.2, 0.8, n),
            "low": close - rng.uniform(0.2, 0.8, n),
            "close": close,
            "volume": rng.integers(5, 50, n),
        },
        index=idx,
    )


class TestRegistryValidation(unittest.TestCase):
    def test_registry_has_dtype_and_nullable(self):
        errors = validate_integrity()
        self.assertEqual(errors, [], msg=str(errors))

    def test_features_json_complete(self):
        export_json()
        errors = validate_json_file()
        self.assertEqual(errors, [], msg=str(errors))
        rows = json.loads(
            (ROOT / "tradingbot/ml/features/registry/features.json").read_text(encoding="utf-8")
        )
        for row in rows:
            for field in ("name", "family", "source", "version", "description", "dtype", "nullable_policy"):
                self.assertIn(field, row)
                self.assertTrue(row[field])


class TestFeatureRanges(unittest.TestCase):
    def test_valid_features_pass_range_checks(self):
        m5 = _ohlcv(130)
        builder = FeatureBuilder("XAUUSD")
        df = builder.build_dataframe(m5, h4_df=_ohlcv(70, "4h", seed=1), m15_df=_ohlcv(90, "15min", seed=2))
        result = validate_feature_dataframe(df)
        errors = [i for i in result.issues if i.code == "invalid_range"]
        self.assertEqual(errors, [], msg=str(errors))

    def test_invalid_rsi_detected(self):
        df = pd.DataFrame({"rsi_14": [0, 50, 150, 30]})
        result = validate_feature_dataframe(df)
        codes = {i.code for i in result.issues}
        self.assertIn("invalid_range", codes)

    def test_session_flags_binary(self):
        m5 = _ohlcv(130)
        builder = FeatureBuilder("XAUUSD")
        df = builder.build_dataframe(m5)
        for col in ("session_london", "session_asia", "in_london_kill", "spread_spike"):
            if col in df.columns:
                vals = set(df[col].dropna().unique())
                self.assertTrue(vals.issubset({0.0, 1.0}), msg=f"{col} has {vals}")


class TestNoLeakage(unittest.TestCase):
    def test_future_corruption_unchanged(self):
        m5 = _ohlcv(150)
        h4 = _ohlcv(70, "4h", seed=1)
        m15 = _ohlcv(90, "15min", seed=2)
        builder = FeatureBuilder("XAUUSD")
        idx = 100
        base = builder.compute_at(m5, idx, h4_df=h4, m15_df=m15)
        corrupted = copy.deepcopy(m5)
        corrupted.iloc[idx + 1 :, corrupted.columns.get_loc("close")] *= 2.0
        after = builder.compute_at(corrupted, idx, h4_df=h4, m15_df=m15)
        for key in feature_names():
            self.assertAlmostEqual(base[key], after[key], places=4, msg=key)


class TestDeterministicBuild(unittest.TestCase):
    def test_identical_builds(self):
        m5 = _ohlcv(120)
        b = FeatureBuilder("XAUUSD")
        df1 = b.build_dataframe(m5)
        df2 = b.build_dataframe(m5)
        pd.testing.assert_frame_equal(df1, df2)


class TestSchemaConsistency(unittest.TestCase):
    def test_parquet_contains_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = FeatureStore(tmp)
            m5 = _ohlcv(80)
            builder = FeatureBuilder("XAUUSD")
            feats = builder.build_dataframe(m5)
            store.store("XAUUSD", "M5", feats)
            loaded = store.load("XAUUSD", "M5")
            assert loaded is not None
            self.assertIn("feature_schema_version", loaded.columns)
            self.assertEqual(FeatureStore.read_schema_version(loaded), FEATURE_SCHEMA_VERSION)
            self.assertTrue(all(v == FEATURE_SCHEMA_VERSION for v in loaded["feature_schema_version"].unique()))


class TestScalingMetadata(unittest.TestCase):
    def test_scaler_metadata_saved_not_applied_to_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            m5 = _ohlcv(100)
            builder = FeatureBuilder("XAUUSD")
            df = builder.build_dataframe(m5)
            raw_sample = df["rsi_14"].iloc[0]
            meta = fit_scaler_metadata(df, "XAUUSD", "M5")
            path = save_scaler_metadata(meta, tmp)
            self.assertTrue(path.is_file())
            self.assertTrue(scalers_dir(tmp).is_dir())
            loaded = load_scaler_metadata("XAUUSD", "M5", tmp)
            self.assertIn("methods", loaded)
            self.assertIn("standard", loaded["methods"])
            scaled = transform_with_metadata(df.head(5), meta, method="standard")
            self.assertNotAlmostEqual(float(df["rsi_14"].iloc[0]), float(scaled["rsi_14"].iloc[0]), places=2)
            self.assertAlmostEqual(raw_sample, float(df["rsi_14"].iloc[0]), places=6)


class TestReproducibilityMetadata(unittest.TestCase):
    def test_build_manifest_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            m5 = _ohlcv(80)
            h4 = _ohlcv(40, "4h")
            manifest = build_manifest(
                "XAUUSD",
                "M5",
                source_candles={"M5": m5, "H4": h4},
                feature_path=Path(tmp) / "features.parquet",
                row_count=10,
                feature_count=45,
                base_dir=tmp,
            )
            for key in (
                "feature_schema_version",
                "feature_registry_version",
                "build_timestamp_utc",
                "source_candle_hashes",
            ):
                self.assertIn(key, manifest)
            self.assertEqual(manifest["feature_schema_version"], FEATURE_SCHEMA_VERSION)
            loaded = load_manifest("XAUUSD", "M5", tmp)
            self.assertEqual(loaded["row_count"], 10)
            self.assertTrue(feature_build_manifest_path("XAUUSD", "M5", tmp).is_file())

    def test_candle_hash_stable(self):
        df = _ohlcv(50)
        self.assertEqual(hash_dataframe(df), hash_dataframe(df.copy()))


class TestQualityReports(unittest.TestCase):
    def test_reports_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            m5 = _ohlcv(100)
            builder = FeatureBuilder("XAUUSD")
            df = builder.build_dataframe(m5)
            paths = save_reports(df, "XAUUSD", "M5", base_dir=tmp)
            self.assertTrue(paths["feature_quality"].is_file())
            self.assertTrue(paths["feature_correlation"].is_file())
            self.assertTrue(reports_dir(tmp).is_dir())
            quality = json.loads(feature_quality_report_path("XAUUSD", "M5", tmp).read_text(encoding="utf-8"))
            corr = json.loads(feature_correlation_report_path("XAUUSD", "M5", tmp).read_text(encoding="utf-8"))
            self.assertIn("validation", quality)
            self.assertIn("highly_correlated_pairs", corr)


class TestPipelineIntegration(unittest.TestCase):
    def test_build_features_writes_metadata_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = CandleStore(tmp)
            candles.store("XAUUSD", "M5", _ohlcv(130))
            candles.store("XAUUSD", "H4", _ohlcv(70, "4h", seed=1))
            candles.store("XAUUSD", "M15", _ohlcv(90, "15min", seed=2))
            pipe = MLDataPipeline({"MT5_LOGIN": None, "MT5_PASSWORD": "", "MT5_SERVER": ""}, base_dir=tmp)
            path = pipe.build_features("XAUUSD")
            self.assertIsNotNone(path)
            self.assertTrue(scaler_metadata_path("XAUUSD", "M5", tmp).is_file())
            self.assertTrue(feature_build_manifest_path("XAUUSD", "M5", tmp).is_file())
            self.assertTrue(feature_quality_report_path("XAUUSD", "M5", tmp).is_file())


if __name__ == "__main__":
    unittest.main()
