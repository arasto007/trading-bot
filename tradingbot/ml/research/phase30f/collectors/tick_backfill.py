"""TickBackfill — copy_ticks_range gap repair."""

from __future__ import annotations

from datetime import datetime, timezone

from tradingbot.ml.research.phase30f.collectors.base import BaseCollector
from tradingbot.ml.research.phase30f.storage.parquet_store import ParquetStore
from tradingbot.ml.research.phase30f.validation.schema import validate_tick_row


class TickBackfill(BaseCollector):
    name = "TickBackfill"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._parquet = ParquetStore(self.config.tick_store)

    def repair_gap(self, gap_start_ms: int, gap_end_ms: int) -> int:
        date_from = datetime.fromtimestamp(gap_start_ms / 1000.0, tz=timezone.utc)
        date_to = datetime.fromtimestamp(gap_end_ms / 1000.0, tz=timezone.utc)
        quotes = self.client.copy_ticks_range(self.config.broker_symbol, date_from, date_to)
        rows = []
        for q in quotes:
            if self.state.tick_exists(self.config.symbol, q.time_msc):
                continue
            spread = round(q.ask - q.bid, 5)
            row = {
                "symbol": self.config.symbol,
                "timestamp_ms": q.time_msc,
                "bid": q.bid,
                "ask": q.ask,
                "last": q.last,
                "volume": q.volume,
                "spread_points": spread,
                "session": "",
                "flags": q.flags,
                "collector_seq": -1,
                "source": "backfill",
            }
            if validate_tick_row(row):
                continue
            rows.append(row)

        if not rows:
            return 0

        n, path = self._parquet.write_ticks(rows, dedupe_key="timestamp_ms")
        if path:
            self.manifest.register_file(path, kind="ticks_backfill", symbol=self.config.symbol)
            for r in rows:
                self.state.register_tick(self.config.symbol, int(r["timestamp_ms"]), str(path))
            self.stats.rows_written += n
            self.stats.ticks_collected += n
        return n

    def run_once(self) -> None:
        gaps = self.state.pending_gaps(limit=10)
        repaired = 0
        for gap in gaps:
            repaired += self.repair_gap(int(gap["gap_start_ms"]), int(gap["gap_end_ms"]))
            self.state.mark_gap_done(int(gap["id"]))
        self.stats.metadata["gaps_repaired"] = repaired

    def verify_partition(self, path) -> dict:
        return self._parquet.verify_file(path)
