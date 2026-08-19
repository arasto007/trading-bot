"""Phase 6.0 A/B shadow integration tests."""

from __future__ import annotations

import ast
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.abtest.comparator import ABComparator
from tradingbot.ml.abtest.logger import ABTestLogger, ab_records_path
from tradingbot.ml.abtest.metrics import compute_arm_metrics, hybrid_r_series, rule_r_series
from tradingbot.ml.abtest.report import ABReportGenerator, ab_test_report_path
from tradingbot.ml.abtest.schema import (
    ABDecisionRecord,
    STATUS_INSUFFICIENT,
    WINNER_HYBRID,
    WINNER_RULE,
    WINNER_TIE,
)
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord, new_decision_id, utc_now_iso
from tradingbot.ml.memory.store import DecisionMemoryStore

AB_PKG = ROOT / "tradingbot" / "ml" / "abtest"
FORBIDDEN = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)


def _decision(
    i: int,
    *,
    rule: str = "BUY",
    hybrid: str = "BUY",
    prob: float = 0.7,
    score: float = 0.75,
    hybrid_wins: bool = True,
) -> tuple[DecisionRecord, OutcomeRecord]:
    d = DecisionRecord(
        decision_id=new_decision_id(),
        timestamp=f"2024-02-{1 + i // 10:02d}T{10 + i % 10:02d}:00:00+00:00",
        symbol="XAUUSD",
        timeframe="M5",
        model_name="logistic",
        ml_probability=prob,
        ml_prediction=1,
        rule_signal=rule,
        hybrid_decision=hybrid,
        confidence="HIGH",
        final_score=score,
        features_version="2.0",
        dataset_version="1.0",
        direction=1,
        session="london",
        regime="trend",
    )
    r = 2.0 if hybrid_wins else -1.0
    o = OutcomeRecord(
        decision_id=d.decision_id,
        evaluated_at=utc_now_iso(),
        future_return=0.01,
        tp_hit=r > 0,
        sl_hit=r < 0,
        max_favorable_excursion=2.0,
        max_adverse_excursion=0.5,
        r_multiple=r,
        label=1 if r > 0 else 0,
    )
    return d, o


def _build(n: int = 120, hybrid_better: bool = True) -> tuple[list[DecisionRecord], dict[str, OutcomeRecord]]:
    decisions: list[DecisionRecord] = []
    outcomes: dict[str, OutcomeRecord] = {}
    for i in range(n):
        if hybrid_better and i % 2 == 0:
            d, o = _decision(i, rule="BUY", hybrid="WAIT", score=0.4, hybrid_wins=False)
        elif hybrid_better:
            d, o = _decision(i, rule="BUY", hybrid="BUY", score=0.8, hybrid_wins=True)
        else:
            d, o = _decision(i, rule="BUY", hybrid="BUY", score=0.75, hybrid_wins=False)
        decisions.append(d)
        outcomes[d.decision_id] = o
    return decisions, outcomes


class TestSchema(unittest.TestCase):
    def test_schema_creation(self):
        rec = ABDecisionRecord(
            timestamp="2024-01-01T00:00:00+00:00",
            symbol="XAUUSD",
            timeframe="M5",
            rule_decision="BUY",
            hybrid_decision="BUY",
            rule_score=0.8,
            hybrid_score=0.78,
            rule_outcome="WIN",
            hybrid_outcome="WIN",
            rule_R=2.0,
            hybrid_R=2.0,
            winner=WINNER_TIE,
        )
        restored = ABDecisionRecord.from_dict(rec.to_dict())
        self.assertEqual(restored.rule_decision, "BUY")


class TestMetrics(unittest.TestCase):
    def test_metric_calculations(self):
        records = [
            ABDecisionRecord(
                "t", "XAUUSD", "M5", "BUY", "BUY", 0.8, 0.75,
                "WIN", "WIN", 2.0, 2.0, WINNER_TIE,
            ),
            ABDecisionRecord(
                "t2", "XAUUSD", "M5", "BUY", "BUY", 0.8, 0.75,
                "LOSS", "LOSS", -1.0, -1.0, WINNER_TIE,
            ),
        ]
        rule_m = compute_arm_metrics(rule_r_series(records))
        self.assertAlmostEqual(rule_m.expected_R, 0.5)
        self.assertAlmostEqual(rule_m.win_rate, 0.5)


class TestComparator(unittest.TestCase):
    def test_comparator_calculations(self):
        decisions, outcomes = _build(n=10, hybrid_better=True)
        records = ABComparator(min_samples=5).build_records(decisions, outcomes)
        self.assertEqual(len(records), 10)
        self.assertGreater(records[0].rule_score, 0)

    def test_winner_detection_hybrid(self):
        decisions, outcomes = _build(n=120, hybrid_better=True)
        report = ABComparator(min_samples=100, winner_margin=0.05).compare(
            ABComparator().build_records(decisions, outcomes)
        )
        self.assertEqual(report.status, "COMPLETE")
        self.assertEqual(report.winner, WINNER_HYBRID)
        self.assertGreater(report.hybrid_expected_R, report.rule_expected_R)

    def test_minimum_sample_protection(self):
        decisions, outcomes = _build(n=20)
        report = ABComparator(min_samples=100).compare(
            ABComparator().build_records(decisions, outcomes)
        )
        self.assertEqual(report.status, STATUS_INSUFFICIENT)


class TestNoLeakage(unittest.TestCase):
    def test_chronological_order(self):
        decisions, outcomes = _build(n=15)
        records = ABComparator().build_records(decisions, outcomes)
        timestamps = [r.timestamp for r in records]
        self.assertEqual(timestamps, sorted(timestamps))


class TestReports(unittest.TestCase):
    def test_report_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = DecisionMemoryStore("XAUUSD", tmp)
            decisions, outcomes = _build(n=120)
            for d in decisions:
                store.append_decision(d)
            for o in outcomes.values():
                store.append_outcome(o)
            payload = ABReportGenerator(min_samples=100, base_dir=tmp).run_from_store(store)
            self.assertTrue(ab_test_report_path(tmp).is_file())
            self.assertIn("hybrid_expected_R", payload)
            self.assertTrue(ab_records_path("XAUUSD", tmp).is_file())
            rows = ABTestLogger("XAUUSD", tmp).read_all()
            self.assertEqual(len(rows), 120)


class TestIsolation(unittest.TestCase):
    def test_no_kernel_imports(self):
        for path in AB_PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self._safe(alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    self._safe(node.module)

    def _safe(self, module: str) -> None:
        for prefix in FORBIDDEN:
            self.assertFalse(module.startswith(prefix), module)

    def test_kernel_unchanged(self):
        from tradingbot.kernel.trading_kernel import TradingKernel  # noqa: F401


if __name__ == "__main__":
    unittest.main()
