"""TickPoller — 100ms symbol_info_tick polling."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from tradingbot.ml.research.phase30f.collectors.base import BaseCollector
from tradingbot.ml.research.phase30f.storage.parquet_store import ParquetStore
from tradingbot.ml.research.phase30f.validation.schema import validate_tick_row


def _session_from_hour(hour: int) -> str:
    if 0 <= hour < 7:
        return "Asian"
    if 7 <= hour < 12:
        return "London"
    if 12 <= hour < 17:
        return "Overlap"
    if 17 <= hour < 22:
        return "NY"
    return "Off"


class TickPoller(BaseCollector):
    name = "TickPoller"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._parquet = ParquetStore(self.config.tick_store)
        self._last_ts_ms: int | None = None
        self._seq = int(self.state.get_checkpoint(self.name, "collector_seq", "0"))
        ckpt = self.state.get_checkpoint(self.name, "last_ts_ms", "")
        if ckpt:
            self._last_ts_ms = int(ckpt)

    def poll_once(self) -> int:
        """Poll single tick — exposed for tests."""
        if not self.client.is_connected():
            if not self.client.reconnect():
                self.stats.errors += 1
                return 0

        quote = self.client.symbol_info_tick(self.config.broker_symbol)
        if quote is None:
            self.stats.errors += 1
            return 0

        ts_ms = quote.time_msc or int(datetime.now(timezone.utc).timestamp() * 1000)
        if self._last_ts_ms is not None:
            gap = ts_ms - self._last_ts_ms
            if gap > self.config.gap_threshold_ms:
                self.state.enqueue_gap(self.config.symbol, self._last_ts_ms, ts_ms)
                self.stats.metadata["last_gap_ms"] = gap

        if self.state.tick_exists(self.config.symbol, ts_ms):
            return 0

        self._seq += 1
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        spread = round(quote.ask - quote.bid, 5)
        row = {
            "symbol": self.config.symbol,
            "timestamp_ms": ts_ms,
            "bid": quote.bid,
            "ask": quote.ask,
            "last": quote.last,
            "volume": quote.volume,
            "spread_points": spread,
            "session": _session_from_hour(dt.hour),
            "flags": quote.flags,
            "collector_seq": self._seq,
            "source": "poll",
        }
        errs = validate_tick_row(row)
        if errs:
            self.stats.errors += 1
            self.stats.last_error = ";".join(errs)
            return 0

        n, path = self._parquet.write_ticks([row])
        if path:
            self.state.register_tick(self.config.symbol, ts_ms, str(path))
            self.manifest.register_file(path, kind="ticks", symbol=self.config.symbol)
            self.stats.ticks_collected += n
            self.stats.rows_written += n
            self._last_ts_ms = ts_ms
            self.state.set_checkpoint(self.name, "last_ts_ms", str(ts_ms))
            self.state.set_checkpoint(self.name, "collector_seq", str(self._seq))
        return n

    def run_once(self) -> None:
        """Poll for one interval (single tick in sandbox cycle)."""
        self.poll_once()

    def run_burst(self, count: int, interval_ms: int | None = None) -> int:
        """Poll `count` times — used by supervisor / tests."""
        interval = interval_ms or self.config.poll_interval_ms
        total = 0
        for _ in range(count):
            total += self.poll_once()
            if interval > 0 and count > 1:
                time.sleep(interval / 1000.0)
        return total
