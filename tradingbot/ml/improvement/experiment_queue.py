"""Experiment queue for proposed offline research."""

from __future__ import annotations

import json
from dataclasses import dataclass

from tradingbot.ml.improvement.recommendation import experiment_queue_path
from tradingbot.ml.improvement.schema import ExperimentQueueItem, QueueStatus, new_queue_id, utc_now_iso


@dataclass
class ExperimentQueue:
    """Store prioritized offline experiment proposals."""

    base_dir: str | None = None

    @property
    def path(self):
        return experiment_queue_path(self.base_dir)

    def _load(self) -> list[ExperimentQueueItem]:
        if not self.path.is_file():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        items = data.get("queue", [])
        return [ExperimentQueueItem.from_dict(i) for i in items]

    def _save(self, items: list[ExperimentQueueItem]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": utc_now_iso(), "queue": [i.to_dict() for i in items]}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, item: ExperimentQueueItem) -> ExperimentQueueItem:
        items = self._load()
        if not item.id:
            item.id = new_queue_id()
        if not item.created_at:
            item.created_at = utc_now_iso()
        items.append(item)
        items.sort(key=lambda x: x.priority, reverse=True)
        self._save(items)
        return item

    def list_all(self) -> list[ExperimentQueueItem]:
        return self._load()

    def populate_from_opportunities(self, opportunities: list, *, base_priority: int = 50) -> list[ExperimentQueueItem]:
        items = self._load()
        existing_hypotheses = {i.hypothesis for i in items}
        added: list[ExperimentQueueItem] = []
        for idx, opp in enumerate(opportunities[:10]):
            if isinstance(opp, dict):
                issue = opp.get("issue", "")
                rec = opp.get("recommendation", "")
                conf = float(opp.get("confidence", 0.5))
                impact = opp.get("expected_impact", "TBD")
            else:
                issue = opp.issue
                rec = opp.recommendation
                conf = float(opp.confidence)
                impact = opp.expected_impact or "TBD"
            hypothesis = f"{issue} -> {rec}"
            if hypothesis in existing_hypotheses:
                continue
            item = ExperimentQueueItem(
                id=new_queue_id(),
                hypothesis=hypothesis,
                expected_improvement=str(impact),
                priority=base_priority + int(conf * 100) - idx,
                required_resources=["dataset", "offline_runner", "research_tracker"],
                status=QueueStatus.PENDING.value,
                created_at=utc_now_iso(),
            )
            items.append(item)
            added.append(item)
        items.sort(key=lambda x: x.priority, reverse=True)
        self._save(items)
        return added

    def clear_completed(self) -> int:
        items = self._load()
        remaining = [i for i in items if i.status != QueueStatus.COMPLETE.value]
        removed = len(items) - len(remaining)
        self._save(remaining)
        return removed
