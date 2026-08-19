"""Base collector interface."""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.research.phase30f.config import CollectorConfig
from tradingbot.ml.research.phase30f.mt5_client import Mt5ResearchClient
from tradingbot.ml.research.phase30f.storage.manifest import ManifestStore
from tradingbot.ml.research.phase30f.storage.sqlite_store import SqliteStateStore

logger = logging.getLogger(__name__)


@dataclass
class CollectorStats:
    name: str
    ticks_collected: int = 0
    rows_written: int = 0
    errors: int = 0
    restarts: int = 0
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseCollector(abc.ABC):
    name: str = "base"

    def __init__(
        self,
        client: Mt5ResearchClient,
        config: CollectorConfig,
        state: SqliteStateStore,
        manifest: ManifestStore,
    ) -> None:
        self.client = client
        self.config = config
        self.state = state
        self.manifest = manifest
        self.stats = CollectorStats(name=self.name)
        self._running = False

    @abc.abstractmethod
    def run_once(self) -> None:
        """Single collection cycle."""

    def start(self) -> None:
        self._running = True
        if not self.client.is_connected() and not self.client.connect():
            self.stats.errors += 1
            self.stats.last_error = "connect failed"
            self._heartbeat("error")
            return
        try:
            self.run_once()
            self._heartbeat("ok")
        except Exception as exc:
            self.stats.errors += 1
            self.stats.last_error = str(exc)
            logger.exception("%s failed", self.name)
            self._heartbeat("error")

    def stop(self) -> None:
        self._running = False

    def _heartbeat(self, status: str) -> None:
        self.state.upsert_heartbeat(
            self.name,
            status=status,
            ticks_collected=self.stats.ticks_collected,
            errors=self.stats.errors,
            restarts=self.stats.restarts,
            metadata=self.stats.metadata,
        )
