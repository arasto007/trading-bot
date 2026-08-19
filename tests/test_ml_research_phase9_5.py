"""Phase 9.5 advanced discovery research tests (offline only)."""

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
    advanced_discovery_datasets_root,
    phase9_5_discovery_report_path,
    production_best_model_path,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.deep_audit import deep_audit_report_path
from tradingbot.ml.dataset.production_dataset_v2 import ProductionDatasetV2Builder
from tradingbot.ml.dataset.schema import DATASET_SCHEMA_VERSION
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features import feature_names
from tradingbot.ml.research.advanced_discovery.experimental_features import (
    EXPERIMENTAL_FEATURE_NAMES,
    audit_experimental_features,
    compute_experimental_features,
)
from tradingbot.ml.research.advanced_discovery.experiment_runner import AdvancedDiscoveryRunner
from tradingbot.ml.research.advanced_discovery.feature_discovery import run_feature_discovery
from tradingbot.ml.research.advanced_discovery.label_discovery import run_label_discovery
from tradingbot.ml.research.advanced_discovery.signal_mining import run_signal_mining
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.training.data_loader import assert_no_test_leakage, load_dataset_v2_splits
from tradingbot.ml.training.phase9_production import Phase92ProductionTrainer

try:
    import lightgbm  # noqa: F401
    import xgboost  # noqa: F401

    HAS_BOOSTERS = True
except ImportError:
    HAS_BOOSTERS = False

DISCOVERY_PKG = ROOT / "tradingbot" / "ml" / "research" / "advanced_discovery"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
    "tradingbot.pipeline.execution_stage",
    "MetaTrader5",
)
PHASE95_FILES = (
    "feature_discovery.py",
    "signal_mining.py",
    "experimental_features.py",
    "label_discovery.py",
    "model_discovery.py",
    "experiment_runner.py",
)
TEST_MIN_SAMPLES = 80


def _scan_package() -> list[str]:
    violations: list[str] = []
    for name in PHASE95_FILES:
        path = DISCOVERY_PKG / name
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


def _synthetic_source(n: int = 1100, *, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    labels = rng.choice([0, 1], size=n, p=[0.48, 0.52])
    events = rng.choice(
        ["order_block", "choch", "fvg", "liquidity_sweep", "session_transition", "trading_session"],
        size=n,
    )
    rows: dict[str, object] = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "event_type": events,
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
        "split": "train",
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "volatility_regime": rng.choice([0.0, 0.5, 1.0], size=n),
        "trend_strength": rng.uniform(10, 80, n),
        "h4_trend_bias": rng.choice([-1.0, 0.0, 1.0], size=n),
    }
    for feat in feature_names():
        if feat not in rows:
            rows[feat] = rng.normal(0, 1, n)
    rows["spread_spike"] = 0.0
    rows["h4_trend_bias"] = np.where(labels == 1, 1.0, -1.0) + rng.normal(0, 0.05, n)
    return pd.DataFrame(rows)


def _write_candles(tmp: str, n: int = 1200) -> None:
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    rng = np.random.default_rng(7)
    close = 2300.0 + rng.normal(0, 0.5, n).cumsum()
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close},
        index=ts,
    )
    CandleStore(tmp).store("XAUUSD", "M5", df)


def _write_reports(tmp: str) -> None:
    reports = Path(tmp) / "ml" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "training_comparison_report.json").write_text(
        json.dumps(
            {
                "best_model": "logistic",
                "evaluations": {
                    "logistic": {
                        "validation": {"classification": {"roc_auc": 0.35}},
                        "test": {"classification": {"roc_auc": 0.35}},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (reports / "phase9_4_retraining_report.json").write_text(
        json.dumps({"summary": {"validation_roc_auc": 0.40}}),
        encoding="utf-8",
    )
    (reports / "model_optimization_report.json").write_text(
        json.dumps(
            {
                "models": [
                    {"model": "lightgbm", "best_params": {"learning_rate": 0.05, "n_estimators": 40, "max_depth": 3, "num_leaves": 15}},
                ]
            }
        ),
        encoding="utf-8",
    )


def _write_deep_audit(tmp: str) -> None:
    p = deep_audit_report_path(tmp)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"status": "pass"}), encoding="utf-8")


def _setup(tmp: str, n: int = 1100) -> str:
    store = DatasetStore(tmp)
    store.store("XAUUSD", "M5", _synthetic_source(n))
    ProductionDatasetV2Builder("XAUUSD", base_dir=tmp, min_samples=TEST_MIN_SAMPLES).build_v2()
    _write_candles(tmp, n + 100)
    _write_deep_audit(tmp)
    _write_reports(tmp)
    Phase92ProductionTrainer(base_dir=tmp, seed=42, min_samples=TEST_MIN_SAMPLES).run("XAUUSD", "M5")
    return dataset_content_fingerprint(store.load_v2("XAUUSD", "M5"))


@unittest.skipUnless(HAS_BOOSTERS, "xgboost and lightgbm required")
class TestPhase95Discovery(unittest.TestCase):
    def test_dataset_v2_fingerprint_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            fp = _setup(tmp)
            AdvancedDiscoveryRunner(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            fp2 = dataset_content_fingerprint(DatasetStore(tmp).load_v2("XAUUSD", "M5"))
            self.assertEqual(fp, fp2)

    def test_no_production_files_modified(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            model_path = production_best_model_path(tmp)
            model_mtime_before = model_path.stat().st_mtime if model_path.is_file() else None
            AdvancedDiscoveryRunner(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            if model_mtime_before is not None:
                self.assertEqual(model_path.stat().st_mtime, model_mtime_before)

    def test_no_kernel_imports(self):
        self.assertEqual(_scan_package(), [])

    def test_no_execution_imports(self):
        violations = [v for v in _scan_package() if "execution" in v]
        self.assertEqual(violations, [])

    def test_no_mt5_usage(self):
        violations = [v for v in _scan_package() if "MetaTrader5" in v or "mt5" in v.lower()]
        self.assertEqual(violations, [])

    def test_feature_leakage_detection(self):
        df = _synthetic_source(100)
        audit = audit_experimental_features(compute_experimental_features(df))
        self.assertEqual(audit["status"], "pass")

    def test_experimental_features_deterministic(self):
        df = _synthetic_source(50, seed=1)
        a = compute_experimental_features(df)
        b = compute_experimental_features(df)
        pd.testing.assert_frame_equal(
            a[list(EXPERIMENTAL_FEATURE_NAMES)],
            b[list(EXPERIMENTAL_FEATURE_NAMES)],
        )

    def test_label_experiments_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            r1 = run_label_discovery(df, "XAUUSD", "M5", tmp)
            r2 = run_label_discovery(df, "XAUUSD", "M5", tmp)
            self.assertEqual(r1["experiment_count"], r2["experiment_count"])

    def test_chronological_split_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            assert_no_test_leakage(splits)

    def test_no_future_timestamps_in_experimental_features(self):
        df = _synthetic_source(30)
        enriched = compute_experimental_features(df)
        forbidden = {"label", "tp_hit", "sl_hit", "mfe", "mae", "future_return"}
        for col in EXPERIMENTAL_FEATURE_NAMES:
            self.assertNotIn(col, forbidden)

    def test_feature_ranking_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            splits = load_dataset_v2_splits("XAUUSD", "M5", tmp)
            report = run_feature_discovery(splits, seed=42)
            self.assertIn("rankings", report)
            self.assertGreater(len(report["top_features"]), 0)

    def test_signal_mining_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            df = DatasetStore(tmp).load_v2("XAUUSD", "M5")
            report = run_signal_mining(df)
            self.assertIn("by_event_type", report)
            self.assertTrue(any(e.get("sample_count", 0) > 0 for e in report["by_event_type"]))

    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = AdvancedDiscoveryRunner(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            path = phase9_5_discovery_report_path(tmp)
            self.assertTrue(path.is_file())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "9.5")
            self.assertIn("recommendation", payload)

    def test_full_orchestrator_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = AdvancedDiscoveryRunner(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            self.assertFalse(result.blocked)
            self.assertEqual(result.leakage_status, "pass")
            root = advanced_discovery_datasets_root(tmp)
            self.assertTrue(root.is_dir())

    def test_beats_phase9_4_candidate_evaluated(self):
        with tempfile.TemporaryDirectory() as tmp:
            _setup(tmp)
            result = AdvancedDiscoveryRunner(base_dir=tmp, seed=42).run("XAUUSD", "M5")
            report = json.loads(phase9_5_discovery_report_path(tmp).read_text(encoding="utf-8"))
            self.assertIn("beats_phase9_4", report["model_findings"])


if __name__ == "__main__":
    unittest.main()
