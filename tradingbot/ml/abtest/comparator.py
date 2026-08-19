"""A/B shadow comparator — rule flow vs hybrid flow."""

from __future__ import annotations

from dataclasses import dataclass

from tradingbot.ml.hybrid.schema import DECISION_BUY, DECISION_SELL
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.optimization._sim import rule_strength
from tradingbot.ml.abtest.metrics import ArmMetrics, compute_arm_metrics, hybrid_r_series, rule_r_series
from tradingbot.ml.abtest.schema import (
    ABDecisionRecord,
    ABTestReport,
    STATUS_COMPLETE,
    STATUS_INSUFFICIENT,
    WINNER_HYBRID,
    WINNER_RULE,
    WINNER_TIE,
    outcome_label,
    record_winner,
)


@dataclass
class ABComparator:
    """
    Compare rule-based vs hybrid shadow decisions on historical outcomes.

    Shadow only — no live switching.
    """

    min_samples: int = 100
    winner_margin: float = 0.05
    min_score: float = 0.60

    def build_records(
        self,
        decisions: list[DecisionRecord],
        outcomes: dict[str, OutcomeRecord],
    ) -> list[ABDecisionRecord]:
        pairs = [(d, outcomes[d.decision_id]) for d in decisions if d.decision_id in outcomes]
        pairs.sort(key=lambda x: x[0].timestamp)

        records: list[ABDecisionRecord] = []
        for decision, outcome in pairs:
            records.append(self._to_ab_record(decision, outcome))
        return records

    def compare(self, records: list[ABDecisionRecord]) -> ABTestReport:
        if not records:
            return self._insufficient_report(0)

        rule_metrics = compute_arm_metrics(rule_r_series(records))
        hybrid_metrics = compute_arm_metrics(hybrid_r_series(records))
        sample_size = len(records)

        if sample_size < self.min_samples:
            report = self._insufficient_report(sample_size)
            report.rule_expected_R = rule_metrics.expected_R
            report.hybrid_expected_R = hybrid_metrics.expected_R
            report.rule_win_rate = rule_metrics.win_rate
            report.hybrid_win_rate = hybrid_metrics.win_rate
            return report

        winner, confidence = self._aggregate_winner(rule_metrics, hybrid_metrics)
        improvement = round(hybrid_metrics.expected_R - rule_metrics.expected_R, 4)

        return ABTestReport(
            symbol=records[0].symbol,
            timeframe=records[0].timeframe,
            sample_size=sample_size,
            status=STATUS_COMPLETE,
            rule_expected_R=rule_metrics.expected_R,
            hybrid_expected_R=hybrid_metrics.expected_R,
            rule_win_rate=rule_metrics.win_rate,
            hybrid_win_rate=hybrid_metrics.win_rate,
            rule_average_R=rule_metrics.average_R,
            hybrid_average_R=hybrid_metrics.average_R,
            rule_drawdown=rule_metrics.drawdown,
            hybrid_drawdown=hybrid_metrics.drawdown,
            rule_trade_frequency=rule_metrics.trade_frequency,
            hybrid_trade_frequency=hybrid_metrics.trade_frequency,
            improvement=improvement,
            winner=winner,
            confidence=confidence,
            margin=self.winner_margin,
        )

    def _to_ab_record(self, decision: DecisionRecord, outcome: OutcomeRecord) -> ABDecisionRecord:
        rule_dec = decision.rule_signal.upper()
        hybrid_dec = decision.hybrid_decision.upper()
        rule_took = rule_dec in (DECISION_BUY, DECISION_SELL)
        hybrid_took = (
            hybrid_dec in (DECISION_BUY, DECISION_SELL)
            and decision.ml_prediction == 1
            and decision.final_score >= self.min_score
        )

        rule_r = outcome.r_multiple if rule_took and outcome.r_multiple != 0.0 else 0.0
        hybrid_r = outcome.r_multiple if hybrid_took and outcome.r_multiple != 0.0 else 0.0

        return ABDecisionRecord(
            timestamp=decision.timestamp,
            symbol=decision.symbol,
            timeframe=decision.timeframe,
            rule_decision=rule_dec,
            hybrid_decision=hybrid_dec,
            rule_score=round(rule_strength(decision), 4),
            hybrid_score=round(decision.final_score, 4),
            rule_outcome=outcome_label(rule_r, rule_took),
            hybrid_outcome=outcome_label(hybrid_r, hybrid_took),
            rule_R=rule_r,
            hybrid_R=hybrid_r,
            winner=record_winner(rule_r, hybrid_r, rule_took, hybrid_took),
            decision_id=decision.decision_id,
        )

    def _aggregate_winner(self, rule: ArmMetrics, hybrid: ArmMetrics) -> tuple[str, str]:
        if hybrid.expected_R > rule.expected_R + self.winner_margin:
            conf = "HIGH" if hybrid.samples >= self.min_samples * 2 else "MEDIUM"
            return WINNER_HYBRID, conf
        if rule.expected_R > hybrid.expected_R + self.winner_margin:
            conf = "HIGH" if rule.samples >= self.min_samples else "MEDIUM"
            return WINNER_RULE, conf
        return WINNER_TIE, "LOW"

    def _insufficient_report(self, sample_size: int) -> ABTestReport:
        return ABTestReport(
            symbol="",
            timeframe="",
            sample_size=sample_size,
            status=STATUS_INSUFFICIENT,
            rule_expected_R=0.0,
            hybrid_expected_R=0.0,
            rule_win_rate=0.0,
            hybrid_win_rate=0.0,
            rule_average_R=0.0,
            hybrid_average_R=0.0,
            rule_drawdown=0.0,
            hybrid_drawdown=0.0,
            rule_trade_frequency=0.0,
            hybrid_trade_frequency=0.0,
            improvement=0.0,
            winner=WINNER_TIE,
            confidence="LOW",
            margin=self.winner_margin,
            warnings=[f"minimum sample size not met: {sample_size} < {self.min_samples}"],
        )
