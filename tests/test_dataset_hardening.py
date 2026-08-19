"""Phase 3.1 dataset hardening tests."""

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

from tradingbot.ml.data.paths import dataset_leakage_audit_path, dataset_statistics_report_path
from tradingbot.ml.data.stores import CandleStore, EventStore
from tradingbot.ml.data.pipeline import MLDataPipeline
from tradingbot.ml.dataset import DatasetBuilder, DatasetBuildConfig, assign_split_column
from tradingbot.ml.dataset.fingerprint import compute_dataset_fingerprint
from tradingbot.ml.dataset.hardening import run_dataset_hardening
from tradingbot.ml.dataset.label_quality import LabelQualityValidator
from tradingbot.ml.dataset.leakage_report import DatasetLeakageAuditor
from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.dataset.splitter import assign_purged_split_column, verify_chronological_splits, verify_purge_gaps
from tradingbot.ml.dataset.statistics import compute_dataset_statistics, save_dataset_statistics
from tradingbot.ml.features import FeatureBuilder, FeatureStore


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
            "volume": 10,
        },
        index=idx,
    )


def _synthetic_dataset(n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    labels = rng.choice([0, 1, -1], size=n, p=[0.35, 0.35, 0.30])
    events = rng.choice(["bos", "choch", "fvg", "order_block"], size=n)
    directions = rng.choice([1, -1], size=n)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": "XAUUSD",
            "timeframe": "M5",
            "event_type": events,
            "event_time": ts,
            "entry_price": 2300.0,
            "timeframe_role": "entry_execution",
            "direction": directions,
            "stop_loss": 2290.0,
            "take_profit": 2320.0,
            "label": labels,
            "future_window_bars": 72,
            "tp_hit": labels == 1,
            "sl_hit": labels == 0,
            "mfe": rng.uniform(0, 2, n),
            "mae": rng.uniform(0, 1, n),
            "future_return": rng.normal(0, 0.01, n),
            "session_london": (ts.hour >= 7) & (ts.hour < 12),
            "session_asia": ts.hour < 7,
            "session_ny": (ts.hour >= 12) & (ts.hour < 17),
            "session_off": ts.hour >= 17,
            "h4_trend_bias": rng.choice([-1, 0, 1], n),
            "rsi_14": rng.uniform(20, 80, n),
        }
    )


class TestDatasetStatistics(unittest.TestCase):
    def test_dataset_statistics_generation(self):
        df = _synthetic_dataset(100)
        stats = compute_dataset_statistics(df, "XAUUSD", "M5")
        self.assertEqual(stats.rows, 100)
        self.assertIn("tp_first", stats.labels)
        self.assertIn("bos", stats.events)
        self.assertGreaterEqual(stats.average_mfe, 0)

    def test_statistics_json_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _synthetic_dataset(50)
            path = save_dataset_statistics(df, "XAUUSD", "M5", tmp)
            self.assertTrue(path.is_file())
            payload = json.loads(dataset_statistics_report_path("XAUUSD", "M5", tmp).read_text())
            self.assertEqual(payload["rows"], 50)


class TestLabelQuality(unittest.TestCase):
    def test_label_balance_detection(self):
        df = _synthetic_dataset(100)
        df["label"] = 1  # all winners — SL class missing
        report = LabelQualityValidator().validate(df)
        self.assertTrue(report.class_imbalance_warnings)
        self.assertEqual(report.status, "warn")

    def test_direction_bias_detection(self):
        df = _synthetic_dataset(200)
        df.loc[df["direction"] > 0, "label"] = 1
        df.loc[df["direction"] < 0, "label"] = 0
        report = LabelQualityValidator().validate(df)
        self.assertIn("buy_winrate", report.direction_bias)
        self.assertEqual(report.direction_bias.get("warning"), "direction imbalance")

    def test_event_bias_detection(self):
        df = _synthetic_dataset(100)
        winners = df["label"] == 1
        df.loc[winners, "event_type"] = "bos"
        report = LabelQualityValidator(min_class_ratio=0.01).validate(df)
        self.assertTrue(report.possible_event_bias)
        self.assertEqual(report.dominant_event_type, "bos")


class TestPurgedSplit(unittest.TestCase):
    def test_purge_split_removes_overlap(self):
        ts = pd.date_range("2024-01-01", periods=500, freq="5min", tz="UTC")
        df = pd.DataFrame({"timestamp": ts, "value": range(500)})
        purged = assign_purged_split_column(df, purge_bars=72, timeframe="M5")
        self.assertIn("purge", purged["split"].unique())
        self.assertTrue(verify_chronological_splits(purged))
        self.assertTrue(verify_purge_gaps(purged, purge_bars=72, timeframe="M5"))

    def test_no_purge_backward_compatible(self):
        ts = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
        df = pd.DataFrame({"timestamp": ts})
        plain = assign_split_column(df, purge_bars=0)
        self.assertNotIn("purge", plain["split"].unique())
        self.assertEqual((plain["split"] == "train").sum(), 70)


class TestFingerprint(unittest.TestCase):
    def test_dataset_hash_changes_when_features_change(self):
        cfg = DatasetBuildConfig(purge_bars=0)
        df1 = _synthetic_dataset(50)
        df2 = df1.copy()
        df2["rsi_14"] = df2["rsi_14"] + 10.0
        h1 = compute_dataset_fingerprint(df1, cfg).dataset_hash
        h2 = compute_dataset_fingerprint(df2, cfg).dataset_hash
        self.assertNotEqual(h1, h2)

    def test_label_config_hash_stable(self):
        cfg = DatasetBuildConfig()
        df = _synthetic_dataset(20)
        fp1 = compute_dataset_fingerprint(df, cfg)
        fp2 = compute_dataset_fingerprint(df, cfg)
        self.assertEqual(fp1.label_config_hash, fp2.label_config_hash)
        self.assertEqual(fp1.label_config["window"], 72)


class TestLeakageAudit(unittest.TestCase):
    def test_dataset_leakage_audit_passes_clean_data(self):
        df = _synthetic_dataset(80)
        df = assign_split_column(df, purge_bars=0)
        result = DatasetLeakageAuditor().audit(df, "XAUUSD", "M5")
        self.assertEqual(result.status, "pass")
        self.assertFalse(result.split_leakage)

    def test_feature_columns_cannot_contain_future_data(self):
        df = _synthetic_dataset(30)
        df["future_signal"] = 1.0
        result = DatasetLeakageAuditor().audit(df, "XAUUSD", "M5")
        self.assertIn("future_signal", result.forbidden_feature_columns)
        self.assertEqual(result.status, "fail")

    def test_split_leakage_detected(self):
        df = _synthetic_dataset(40)
        df = assign_split_column(df, purge_bars=0)
        # Force overlap
        df.loc[df["split"] == "validation", "timestamp"] = df[df["split"] == "train"]["timestamp"].min()
        result = DatasetLeakageAuditor().audit(df, "XAUUSD", "M5")
        self.assertTrue(result.split_leakage)


class TestHardeningIntegration(unittest.TestCase):
    def test_hardening_pipeline_integration(self):
        with tempfile.TemporaryDirectory() as tmp:
            df = _synthetic_dataset(60)
            df = assign_purged_split_column(df, purge_bars=12, timeframe="M5")
            cfg = DatasetBuildConfig(purge_bars=12)
            summary = run_dataset_hardening(df, "XAUUSD", "M5", cfg, base_dir=tmp)
            self.assertIn("statistics_report", summary)
            self.assertIn("fingerprint", summary)
            self.assertIn("leakage_audit_report", summary)
            self.assertTrue(Path(summary["leakage_audit_report"]).is_file())

    def test_build_dataset_writes_hardening_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            candles = CandleStore(tmp)
            features = FeatureStore(tmp)
            m5 = _ohlcv(150)
            candles.store("XAUUSD", "M5", m5)
            feats = FeatureBuilder("XAUUSD").build_dataframe(m5)
            features.store("XAUUSD", "M5", feats)
            from tradingbot.ml.data.schema import MarketEvent

            EventStore(tmp).append(
                [
                    MarketEvent(
                        event_id="h1",
                        event_type="bos",
                        symbol="XAUUSD",
                        timeframe="M5",
                        ts_utc=m5.index[80].isoformat(),
                        direction=1,
                        metadata={"bar_index": 80},
                    )
                ],
                dedupe=False,
            )
            pipe = MLDataPipeline({"MT5_LOGIN": None, "MT5_PASSWORD": "", "MT5_SERVER": ""}, base_dir=tmp)
            path = pipe.build_dataset("XAUUSD")
            self.assertIsNotNone(path)
            from tradingbot.ml.dataset.store import DatasetStore

            store = DatasetStore(tmp)
            manifest = store.load_build_manifest("XAUUSD", "M5")
            self.assertIn("dataset_hash", manifest)
            self.assertIn("label_config", manifest)


class TestKernelUntouched(unittest.TestCase):
    def test_import_kernel_risk_execution(self):
        from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter  # noqa: F401
        from tradingbot.adapters.risk_gate import RiskGate  # noqa: F401
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401


if __name__ == "__main__":
    unittest.main()
