"""CollectorSupervisor — orchestration, restart, health."""

from __future__ import annotations

import logging
from typing import Any

from tradingbot.ml.research.phase30f.collectors.base import BaseCollector
from tradingbot.ml.research.phase30f.collectors.execution_logger import ExecutionLogger
from tradingbot.ml.research.phase30f.collectors.gap_extractor import GapExtractor
from tradingbot.ml.research.phase30f.collectors.history_sync import HistorySync
from tradingbot.ml.research.phase30f.collectors.news_joiner import NewsJoiner
from tradingbot.ml.research.phase30f.collectors.symbol_snapshot import SymbolSnapshot
from tradingbot.ml.research.phase30f.collectors.tick_backfill import TickBackfill
from tradingbot.ml.research.phase30f.collectors.tick_poller import TickPoller
from tradingbot.ml.research.phase30f.config import COLLECTOR_VERSION, CollectorConfig
from tradingbot.ml.research.phase30f.mt5_client import Mt5ResearchClient
from tradingbot.ml.research.phase30f.storage.manifest import ManifestStore
from tradingbot.ml.research.phase30f.storage.sqlite_store import SqliteStateStore

logger = logging.getLogger(__name__)

MAX_RESTARTS = 3


class CollectorSupervisor:
    def __init__(self, client: Mt5ResearchClient, config: CollectorConfig) -> None:
        self.client = client
        self.config = config
        self.config.ensure_dirs()
        self.state = SqliteStateStore(config.db_path)
        self.manifest = ManifestStore(config.manifest_path, version=COLLECTOR_VERSION)
        self.collectors: list[BaseCollector] = self._build_collectors()
        self._restart_counts: dict[str, int] = {c.name: 0 for c in self.collectors}

    def _build_collectors(self) -> list[BaseCollector]:
        common = (self.client, self.config, self.state, self.manifest)
        return [
            TickPoller(*common),
            TickBackfill(*common),
            ExecutionLogger(*common),
            HistorySync(*common),
            SymbolSnapshot(*common),
            GapExtractor(*common),
            NewsJoiner(*common),
        ]

    def run_cycle(self, *, tick_polls: int = 1) -> dict[str, Any]:
        """Run one supervisor cycle across all collectors."""
        results: dict[str, Any] = {}
        for collector in self.collectors:
            results[collector.name] = self._run_collector(collector, tick_polls=tick_polls)
        return results

    def _run_collector(self, collector: BaseCollector, *, tick_polls: int) -> dict[str, Any]:
        name = collector.name
        attempts = 0
        while attempts <= MAX_RESTARTS:
            try:
                if isinstance(collector, TickPoller) and tick_polls > 1:
                    n = collector.run_burst(tick_polls, interval_ms=0)
                    collector._heartbeat("ok")
                    return {"status": "ok", "ticks": n, "restarts": self._restart_counts[name]}
                collector.start()
                return {
                    "status": collector.stats.last_error or "ok",
                    "rows": collector.stats.rows_written,
                    "restarts": self._restart_counts[name],
                }
            except Exception as exc:
                attempts += 1
                self._restart_counts[name] += 1
                collector.stats.restarts += 1
                collector.stats.last_error = str(exc)
                logger.warning("Restarting %s attempt %d: %s", name, attempts, exc)
                self.client.reconnect()
        collector._heartbeat("failed")
        return {"status": "failed", "error": collector.stats.last_error, "restarts": self._restart_counts[name]}

    def health_report(self) -> dict[str, Any]:
        beats = self.state.all_heartbeats()
        healthy = sum(1 for b in beats if b["status"] == "ok")
        return {
            "collectors_total": len(self.collectors),
            "healthy": healthy,
            "degraded": sum(1 for b in beats if b["status"] == "error"),
            "failed": sum(1 for b in beats if b["status"] == "failed"),
            "heartbeats": beats,
            "restart_counts": dict(self._restart_counts),
        }

    def get_collector(self, name: str) -> BaseCollector | None:
        for c in self.collectors:
            if c.name == name:
                return c
        return None
