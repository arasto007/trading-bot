"""NewsJoiner — framework only, no external API."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tradingbot.ml.research.phase30f.collectors.base import BaseCollector
from tradingbot.ml.research.phase30f.storage.parquet_store import ParquetStore


class NewsJoiner(BaseCollector):
    name = "NewsJoiner"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._parquet = ParquetStore(self.config.data_root / "news")

    def run_once(self) -> None:
        calendar_path = self.config.calendar_path
        events: list[dict] = []
        status = "framework_only"

        if calendar_path and Path(calendar_path).is_file():
            raw = json.loads(Path(calendar_path).read_text(encoding="utf-8"))
            events = raw if isinstance(raw, list) else raw.get("events", [])
            status = "local_calendar_loaded"
        else:
            placeholder = self.config.data_root / "news" / "calendar_placeholder.json"
            placeholder.write_text(
                json.dumps(
                    {
                        "status": "awaiting_external_calendar",
                        "note": "Drop FF calendar JSON at config.calendar_path",
                        "events": [],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

        rows = [
            {
                "event_id": e.get("id", f"evt_{i}"),
                "title": e.get("title", ""),
                "impact": e.get("impact", "unknown"),
                "scheduled_utc": e.get("scheduled_utc", ""),
                "joined_utc": datetime.now(timezone.utc).isoformat(),
                "status": status,
            }
            for i, e in enumerate(events)
        ]
        if rows:
            path = self._parquet.write_table("spread_tags.parquet", rows)
            self.manifest.register_file(path, kind="news", symbol=self.config.symbol)
        self.stats.rows_written = len(rows)
        self.stats.metadata["status"] = status
