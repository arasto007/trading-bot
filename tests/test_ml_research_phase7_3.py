"""Phase 7.3 ML research intelligence tests."""

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

from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.features.registry import feature_names
from tradingbot.ml.research.experiment_runner import ExperimentConfig, ResearchExperimentRunner
from tradingbot.ml.research.experiment_tracker import ExperimentTracker
from tradingbot.ml.research.feature_research import FeatureResearchAnalyzer
from tradingbot.ml.research.hypothesis import HypothesisManager
from tradingbot.ml.research.model_comparison import ModelComparisonEngine
from tradingbot.ml.research.ranking import ResearchRanker
from tradingbot.ml.research.reproducibility import build_reproducibility_bundle, dataset_fingerprint, verify_reproducibility
from tradingbot.ml.research.reports import ResearchReportGenerator
from tradingbot.ml.research.schema import ExperimentRecord, utc_now_iso

RESEARCH_PKG = ROOT / "tradingbot" / "ml" / "research"

# Forbidden LIVE execution / broker-send dependencies.
# tradingbot.execution.* is the offline cost/fill simulator — not a live order path.
FORBIDDEN_LIVE_EXECUTION = (
    "tradingbot.adapters.mt5_execution",
    "tradingbot.application.live_runner",
    "tradingbot.services.mt5_order_guard",
)

# Offline research may import kernel / RiskGate / the execution adapter for
# backtest, replay, or latency measurement. These files do not place live orders.
# New research modules that import these prefixes must be added here explicitly.
OFFLINE_ALLOWED = {
    "tradingbot.kernel": frozenset({
        "phase22e/portfolio.py",
        "phase25b/unified_pipeline_replay.py",
    }),
    "tradingbot.adapters.risk_gate": frozenset({
        "phase24c/latency_profiler.py",
        "phase25a/run_investigation.py",
        "phase25b/unified_pipeline_replay.py",
        "phase6a/fault_injection_live.py",
        "phase9a/pm_v2_research.py",
        # Offline audit/trace hooks (from-import). Not live startup.
        "phase22b/run_capability_audit.py",
        "phase22f/trace.py",
    }),
    "tradingbot.adapters.mt5_execution": frozenset({
        "phase25a/run_investigation.py",
        "phase25b/unified_pipeline_replay.py",
    }),
}

# Import-probe only — not an allowlist. These files dynamically load live
# modules for audit and must stay classified as PROBE, not safe execution.
DELIBERATE_IMPORT_PROBES = {
    "phase_final_audit/run_investigation.py": frozenset({
        "tradingbot.application.live_runner",
        "tradingbot.adapters.mt5_execution",
        "tradingbot.services.mt5_order_guard",
    }),
}


def _call_func_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _list_string_constants(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        out: list[str] = []
        for elt in node.elts:
            value = _const_str(elt)
            if value is not None:
                out.append(value)
        return out
    return []


def _iter_import_modules(tree: ast.AST) -> list[str]:
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
            for alias in node.names:
                if alias.name != "*":
                    mods.append(f"{node.module}.{alias.name}")
    return mods


_DYNAMIC_IMPORT_FUNCS = frozenset({"import_module", "__import__"})


def _dynamic_func_aliases(tree: ast.AST) -> frozenset[str]:
    """Statically obvious aliases of import_module / __import__."""
    aliases = set(_DYNAMIC_IMPORT_FUNCS)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        aliases.add(alias.asname or alias.name)
            if node.module in (None, "builtins"):
                for alias in node.names:
                    if alias.name == "__import__":
                        aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            val = node.value
            is_import_module_attr = isinstance(val, ast.Attribute) and val.attr == "import_module"
            is_dunder_import = isinstance(val, ast.Name) and val.id == "__import__"
            if is_import_module_attr or is_dunder_import:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        aliases.add(target.id)
    return frozenset(aliases)


def _iter_dynamic_import_modules(tree: ast.AST) -> list[str]:
    """Detect obvious static dynamic-import forms.

    Covered:
    - importlib.import_module("literal") including multiline Call args
    - __import__("literal")
    - from importlib import import_module as im; im("literal")
    - name = "literal"; import_module(name) / __import__(name)
    - names = ["literal"]; for n in names: import_module(n)

    Not covered: arbitrary data-flow, comments, or bare documentation strings.
    """
    dynamic_names = _dynamic_func_aliases(tree)
    assigned_lists: dict[str, list[str]] = {}
    assigned_strings: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        values = _list_string_constants(node.value)
        literal = _const_str(node.value)
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if values:
                assigned_lists[target.id] = values
            elif literal is not None:
                assigned_strings[target.id] = literal

    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            iter_name = node.iter.id if isinstance(node.iter, ast.Name) else None
            target_name = node.target.id if isinstance(node.target, ast.Name) else None
            if iter_name and target_name and iter_name in assigned_lists:
                for child in ast.walk(node):
                    if not isinstance(child, ast.Call):
                        continue
                    if _call_func_name(child.func) not in dynamic_names:
                        continue
                    if child.args and isinstance(child.args[0], ast.Name) and child.args[0].id == target_name:
                        found.extend(assigned_lists[iter_name])
        if not isinstance(node, ast.Call):
            continue
        if _call_func_name(node.func) not in dynamic_names or not node.args:
            continue
        arg = node.args[0]
        literal = _const_str(arg)
        if literal is not None:
            found.append(literal)
            continue
        if isinstance(arg, ast.Name):
            if arg.id in assigned_lists:
                found.extend(assigned_lists[arg.id])
            elif arg.id in assigned_strings:
                found.append(assigned_strings[arg.id])
    return found


def _modules_for_scan(tree: ast.AST) -> list[str]:
    return _iter_import_modules(tree) + _iter_dynamic_import_modules(tree)


def _scan_forbidden(
    package_dir: Path,
    prefixes: tuple[str, ...],
    *,
    allowlist: dict[str, frozenset[str]] | None = None,
    exclude_rels: frozenset[str] | None = None,
) -> list[str]:
    """AST import scan including obvious importlib forms. Comments/strings ignored."""
    allowlist = allowlist or {}
    exclude_rels = exclude_rels or frozenset()
    violations: list[str] = []
    for path in package_dir.rglob("*.py"):
        rel = path.relative_to(package_dir).as_posix()
        if rel in exclude_rels:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _modules_for_scan(tree):
            for prefix in prefixes:
                if not module.startswith(prefix):
                    continue
                allowed = allowlist.get(prefix, frozenset())
                if rel in allowed:
                    continue
                violations.append(f"{rel}: {module}")
    return violations


def _scan_package(package_dir: Path) -> list[str]:
    return _scan_forbidden(
        package_dir,
        FORBIDDEN_LIVE_EXECUTION,
        allowlist=OFFLINE_ALLOWED,
        exclude_rels=frozenset(DELIBERATE_IMPORT_PROBES),
    )


def _scan_probes(package_dir: Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for rel, expected in DELIBERATE_IMPORT_PROBES.items():
        path = package_dir / rel
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        hits = {
            module
            for module in _iter_dynamic_import_modules(tree)
            if any(module.startswith(p) for p in FORBIDDEN_LIVE_EXECUTION)
        }
        found[rel] = hits & set(expected) if expected else hits
    return found


def _make_dataset(n: int = 120, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    n_train = int(n * 0.70)
    n_val = int(n * 0.15)
    splits = ["train"] * n_train + ["validation"] * n_val + ["test"] * (n - n_train - n_val)
    labels = rng.choice([0, 1], size=n, p=[0.45, 0.55])
    row: dict = {
        "timestamp": ts,
        "symbol": "XAUUSD",
        "timeframe": "M5",
        "label": labels,
        "split": splits,
        "regime": rng.choice(["trend", "range"], n),
        "session": rng.choice(["london", "asia"], n),
    }
    for feat in feature_names()[:10]:
        row[feat] = rng.normal(0, 1, n)
    row["h4_trend_bias"] = np.where(labels == 1, 1.0, -1.0) + rng.normal(0, 0.1, n)
    row["liquidity_sweep"] = rng.normal(0, 1, n)
    return pd.DataFrame(row)


class TestIsolation(unittest.TestCase):
    def test_no_kernel_imports(self):
        violations = _scan_forbidden(
            RESEARCH_PKG,
            ("tradingbot.kernel",),
            allowlist=OFFLINE_ALLOWED,
            exclude_rels=frozenset(DELIBERATE_IMPORT_PROBES),
        )
        self.assertEqual(violations, [])

    def test_no_risk_imports(self):
        violations = _scan_forbidden(
            RESEARCH_PKG,
            ("tradingbot.adapters.risk_gate",),
            allowlist=OFFLINE_ALLOWED,
            exclude_rels=frozenset(DELIBERATE_IMPORT_PROBES),
        )
        self.assertEqual(violations, [])

    def test_no_execution_imports(self):
        violations = _scan_package(RESEARCH_PKG)
        self.assertEqual(violations, [])

    def test_static_import_live_runner_detected(self):
        tree = ast.parse("import tradingbot.application.live_runner\n")
        self.assertIn("tradingbot.application.live_runner", _iter_import_modules(tree))

    def test_from_import_live_runner_detected(self):
        tree = ast.parse("from tradingbot.application import live_runner\n")
        self.assertIn("tradingbot.application", _iter_import_modules(tree))
        self.assertIn("tradingbot.application.live_runner", _iter_import_modules(tree))

    def test_from_import_live_runner_alias_detected(self):
        tree = ast.parse("from tradingbot.application import live_runner as lr\n")
        self.assertIn("tradingbot.application.live_runner", _iter_import_modules(tree))

    def test_aliased_import_module_detected(self):
        tree = ast.parse(
            "from importlib import import_module as im\n"
            'im("tradingbot.application.live_runner")\n'
        )
        self.assertIn("tradingbot.application.live_runner", _iter_dynamic_import_modules(tree))

    def test_unbound_dynamic_variable_not_detected(self):
        tree = ast.parse(
            "import importlib\n"
            "importlib.import_module(unknown_module)\n"
        )
        self.assertEqual(_iter_dynamic_import_modules(tree), [])

    def test_dynamic_import_live_runner_detected(self):
        tree = ast.parse('import importlib\nimportlib.import_module("tradingbot.application.live_runner")\n')
        self.assertIn("tradingbot.application.live_runner", _iter_dynamic_import_modules(tree))

    def test_dynamic_import_bound_string_detected(self):
        tree = ast.parse(
            "import importlib\n"
            'module = "tradingbot.application.live_runner"\n'
            "importlib.import_module(module)\n"
        )
        self.assertIn("tradingbot.application.live_runner", _iter_dynamic_import_modules(tree))

    def test_dynamic_import_literal_list_loop_detected(self):
        tree = ast.parse(
            "import importlib\n"
            "modules = [\n"
            '    "tradingbot.application.live_runner",\n'
            "]\n"
            "for name in modules:\n"
            "    importlib.import_module(name)\n"
        )
        self.assertIn("tradingbot.application.live_runner", _iter_dynamic_import_modules(tree))

    def test_builtin_import_literal_detected(self):
        tree = ast.parse('__import__("tradingbot.application.live_runner")\n')
        self.assertIn("tradingbot.application.live_runner", _iter_dynamic_import_modules(tree))

    def test_dynamic_import_multiline_literal_detected(self):
        tree = ast.parse(
            "import importlib\n"
            "importlib.import_module(\n"
            '    "tradingbot.application.live_runner"\n'
            ")\n"
        )
        self.assertIn("tradingbot.application.live_runner", _iter_dynamic_import_modules(tree))

    def test_dynamic_import_mt5_execution_detected(self):
        tree = ast.parse('import importlib\nimportlib.import_module("tradingbot.adapters.mt5_execution")\n')
        self.assertIn("tradingbot.adapters.mt5_execution", _iter_dynamic_import_modules(tree))

    def test_dynamic_import_mt5_order_guard_detected(self):
        tree = ast.parse('import importlib\nimportlib.import_module("tradingbot.services.mt5_order_guard")\n')
        self.assertIn("tradingbot.services.mt5_order_guard", _iter_dynamic_import_modules(tree))

    def test_documentation_strings_not_detected(self):
        tree = ast.parse(
            '"""Mentions tradingbot.application.live_runner and mt5_execution."""\n'
            "x = 'tradingbot.services.mt5_order_guard'\n"
        )
        self.assertEqual(_iter_dynamic_import_modules(tree), [])
        self.assertEqual(_iter_import_modules(tree), [])

    def test_offline_allowlist_unchanged(self):
        self.assertIn("phase25a/run_investigation.py", OFFLINE_ALLOWED["tradingbot.adapters.mt5_execution"])
        self.assertIn("phase25b/unified_pipeline_replay.py", OFFLINE_ALLOWED["tradingbot.adapters.mt5_execution"])
        self.assertNotIn("phase_final_audit/run_investigation.py", OFFLINE_ALLOWED["tradingbot.adapters.mt5_execution"])
        for files in OFFLINE_ALLOWED.values():
            self.assertNotIn("phase_final_audit/run_investigation.py", files)

    def test_final_audit_is_deliberate_probe_not_allowlist(self):
        probes = _scan_probes(RESEARCH_PKG)
        rel = "phase_final_audit/run_investigation.py"
        self.assertIn(rel, probes)
        self.assertGreaterEqual(probes[rel], set(DELIBERATE_IMPORT_PROBES[rel]))
        self.assertNotIn(rel, OFFLINE_ALLOWED.get("tradingbot.application.live_runner", frozenset()))


class TestExperimentTracker(unittest.TestCase):
    def test_experiment_logging(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ExperimentTracker(tmp)
            record = ExperimentRecord(
                experiment_id="exp-1",
                timestamp=utc_now_iso(),
                dataset_hash="abc",
                feature_version="2.0",
                model_name="logistic",
                model_version="1.0",
                parameters={"threshold": 0.5},
                validation_method="chronological_split",
                metrics={"roc_auc": 0.7},
                expected_R=0.2,
            )
            tracker.append(record)
            rows = tracker.read_all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["experiment_id"], "exp-1")

    def test_append_only_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ExperimentTracker(tmp)
            tracker.append({"experiment_id": "a", "timestamp": utc_now_iso(), "dataset_hash": "x", "feature_version": "2.0", "model_name": "logistic", "model_version": "1.0", "parameters": {}, "validation_method": "walk_forward", "metrics": {}, "expected_R": 0.0})
            tracker.append({"experiment_id": "b", "timestamp": utc_now_iso(), "dataset_hash": "x", "feature_version": "2.0", "model_name": "xgboost", "model_version": "1.0", "parameters": {}, "validation_method": "walk_forward", "metrics": {}, "expected_R": 0.1})
            original = tracker.path.read_text(encoding="utf-8")
            tracker.append({"experiment_id": "c", "timestamp": utc_now_iso(), "dataset_hash": "x", "feature_version": "2.0", "model_name": "lightgbm", "model_version": "1.0", "parameters": {}, "validation_method": "walk_forward", "metrics": {}, "expected_R": 0.2})
            updated = tracker.path.read_text(encoding="utf-8")
            self.assertTrue(updated.startswith(original))
            self.assertEqual(tracker.count(), 3)


class TestFeatureResearch(unittest.TestCase):
    def test_feature_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            report = FeatureResearchAnalyzer(tmp).analyze("XAUUSD", "M5")
            self.assertGreater(report["feature_count"], 0)
            self.assertIn("best_features", report)
            self.assertIn("regime_dependency", report)


class TestModelComparison(unittest.TestCase):
    def test_model_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            from tradingbot.ml.data.paths import reports_dir

            reports_dir(tmp).mkdir(parents=True, exist_ok=True)
            payload = {
                "metrics": {"roc_auc": 0.72, "pr_auc": 0.65, "stability_score": 0.8, "calibration_error": 0.08},
                "trading": {"expected_R": 0.25},
                "simulated": {"trades_taken": 100, "profit_factor": 1.4, "max_drawdown": 5.0},
            }
            (reports_dir(tmp) / "XAUUSD_M5_logistic_evaluation.json").write_text(json.dumps(payload), encoding="utf-8")
            result = ModelComparisonEngine(tmp).compare("XAUUSD", "M5")
            self.assertFalse(result["auto_replacement"])
            if result["rankings"]:
                self.assertIn("overall_score", result["rankings"][0])


class TestRanking(unittest.TestCase):
    def test_ranking_consistency(self):
        with tempfile.TemporaryDirectory() as tmp:
            tracker = ExperimentTracker(tmp)
            for i, er in enumerate((0.1, 0.3, 0.2)):
                tracker.append({
                    "experiment_id": f"e{i}",
                    "timestamp": utc_now_iso(),
                    "dataset_hash": "x",
                    "feature_version": "2.0",
                    "model_name": "logistic",
                    "model_version": "1.0",
                    "parameters": {},
                    "validation_method": "chronological_split",
                    "metrics": {"roc_auc": 0.5 + i * 0.1, "f1": 0.5},
                    "expected_R": er,
                })
            ranks = ResearchRanker(tmp).rank_all("XAUUSD", "M5")
            exp_ranks = ranks["experiments"]
            self.assertEqual(exp_ranks[0]["expected_R"], 0.3)


class TestReproducibility(unittest.TestCase):
    def test_reproducibility_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            bundle = build_reproducibility_bundle("XAUUSD", "M5", model_name="logistic", model_version="1.0", parameters={"threshold": 0.5}, base_dir=tmp)
            self.assertIn("dataset_fingerprint", bundle)
            self.assertIn("feature_schema", bundle)
            self.assertIn("git_commit", bundle)

    def test_no_random_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            runner = ResearchExperimentRunner("XAUUSD", "M5", base_dir=tmp)
            record = runner.run(ExperimentConfig(model_name="logistic", validation_method="chronological_split"))
            self.assertEqual(record.validation_method, "chronological_split")
            self.assertNotIn("shuffle", json.dumps(record.parameters))


class TestExperimentRunner(unittest.TestCase):
    def test_offline_experiment(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            runner = ResearchExperimentRunner("XAUUSD", "M5", base_dir=tmp)
            record = runner.run()
            self.assertEqual(runner.tracker.count(), 1)
            self.assertIn("roc_auc", record.metrics)


class TestReports(unittest.TestCase):
    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            DatasetStore(tmp).store("XAUUSD", "M5", _make_dataset())
            payload = ResearchReportGenerator(base_dir=tmp).run("XAUUSD", "M5")
            self.assertIn("summary", payload)
            self.assertTrue(Path(payload["feature_research_report"]).is_file())


if __name__ == "__main__":
    unittest.main()
