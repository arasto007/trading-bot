"""Order queue with execution delay."""

from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field
from typing import Any

from tradingbot.execution.execution_models import ExecutionContext, ExecutionProfile


@dataclass(order=True)
class QueuedOrder:
    priority: float
    order_id: str = field(compare=False)
    context: ExecutionContext = field(compare=False)
    enqueue_ms: float = field(compare=False, default=0.0)


class OrderQueue:
    """Simple priority queue simulating broker order backlog."""

    def __init__(self) -> None:
        self._heap: list[QueuedOrder] = []
        self._counter = 0

    def enqueue(self, order_id: str, ctx: ExecutionContext, *, now_ms: float = 0.0) -> None:
        self._counter += 1
        heapq.heappush(self._heap, QueuedOrder(priority=now_ms + self._counter * 0.001, order_id=order_id, context=ctx, enqueue_ms=now_ms))

    def dequeue_ready(self, *, now_ms: float) -> QueuedOrder | None:
        if not self._heap:
            return None
        head = self._heap[0]
        if head.priority <= now_ms:
            return heapq.heappop(self._heap)
        return None

    def __len__(self) -> int:
        return len(self._heap)


def sample_queue_delay_ms(
    ctx: ExecutionContext,
    profile: ExecutionProfile,
    rng: random.Random,
    *,
    queue_depth: int = 0,
) -> float:
    base = 5.0 + queue_depth * 3.0
    if ctx.is_fast_market:
        base *= 1.6
    if ctx.session == "Asian":
        base *= 1.2
    liq_factor = 1.0 + (1.0 - ctx.liquidity_score) * 0.8
    delay = rng.expovariate(1.0 / (base * liq_factor))
    return round(delay * profile.delay_multiplier, 3)
