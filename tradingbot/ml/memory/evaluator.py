"""Batch outcome evaluation for decision memory."""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from tradingbot.ml.memory.outcome import OutcomeEvaluator
from tradingbot.ml.memory.schema import DecisionRecord, OutcomeRecord
from tradingbot.ml.memory.store import DecisionMemoryStore


class ShadowDecisionEvaluator:
    """Evaluate pending shadow decisions and persist outcomes."""

    def __init__(
        self,
        store: DecisionMemoryStore,
        *,
        outcome_evaluator: OutcomeEvaluator | None = None,
    ) -> None:
        self.store = store
        self.outcome_evaluator = outcome_evaluator or OutcomeEvaluator()

    def evaluate_pending(
        self,
        candles: pd.DataFrame,
        *,
        decision_ids: Iterable[str] | None = None,
    ) -> list[OutcomeRecord]:
        existing = self.store.load_outcomes_by_id()
        decisions = self.store.load_decisions()
        if decision_ids is not None:
            wanted = set(decision_ids)
            decisions = [d for d in decisions if d.decision_id in wanted]

        results: list[OutcomeRecord] = []
        for record in decisions:
            if record.decision_id in existing:
                continue
            outcome = self.outcome_evaluator.evaluate(record, candles)
            self.store.append_outcome(outcome)
            results.append(outcome)
        return results

    def evaluate_all(self, candles: pd.DataFrame) -> list[OutcomeRecord]:
        return self.evaluate_pending(candles)
