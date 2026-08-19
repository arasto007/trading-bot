"""HistorySync — incremental deal and order history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tradingbot.ml.research.phase30f.collectors.base import BaseCollector
from tradingbot.ml.research.phase30f.storage.parquet_store import ParquetStore


class HistorySync(BaseCollector):
    name = "HistorySync"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._parquet = ParquetStore(self.config.data_root / "history")

    def _last_sync_ms(self) -> int:
        raw = self.state.get_checkpoint(self.name, "last_sync_ms", "")
        if raw:
            return int(raw)
        return int((datetime.now(timezone.utc) - timedelta(days=7)).timestamp() * 1000)

    def run_once(self) -> None:
        now = datetime.now(timezone.utc)
        start_ms = self._last_sync_ms()
        date_from = datetime.fromtimestamp(start_ms / 1000.0, tz=timezone.utc)
        deals = self.client.history_deals_get(date_from, now)
        orders = self.client.history_orders_get(date_from, now)

        if deals:
            path = self._parquet.write_table("deals.parquet", deals)
            self.manifest.register_file(path, kind="deals", symbol=self.config.symbol)
            self.stats.rows_written += len(deals)

        if orders:
            path = self._parquet.write_table("orders_history.parquet", orders)
            self.manifest.register_file(path, kind="orders_history", symbol=self.config.symbol)
            self.stats.rows_written += len(orders)

        self.state.set_checkpoint(self.name, "last_sync_ms", str(int(now.timestamp() * 1000)))
        self.stats.metadata["deals"] = len(deals)
        self.stats.metadata["orders"] = len(orders)
