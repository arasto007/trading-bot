"""GapExtractor — weekend, session, and large tick jumps."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from tradingbot.ml.research.phase30f.collectors.base import BaseCollector
from tradingbot.ml.research.phase30f.storage.parquet_store import ParquetStore
from tradingbot.ml.research.phase30f.validation.integrity import detect_tick_gaps


class GapExtractor(BaseCollector):
    name = "GapExtractor"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._parquet = ParquetStore(self.config.tick_store)

    def extract(self, df: pd.DataFrame | None = None) -> list[dict]:
        if df is None:
            df = self._parquet.read_ticks(self.config.symbol)
        if df.empty:
            return []

        events: list[dict] = []
        gaps = detect_tick_gaps(df, self.config.gap_threshold_ms)
        for g in gaps:
            g["type"] = "time_gap"
            events.append(g)

        df = df.sort_values("timestamp_ms")
        for i in range(1, len(df)):
            prev_bid = float(df.iloc[i - 1]["bid"])
            cur_bid = float(df.iloc[i]["bid"])
            jump = abs(cur_bid - prev_bid)
            if jump >= self.config.large_jump_points:
                events.append(
                    {
                        "type": "large_jump",
                        "symbol": self.config.symbol,
                        "timestamp_ms": int(df.iloc[i]["timestamp_ms"]),
                        "jump_points": jump,
                        "prev_bid": prev_bid,
                        "cur_bid": cur_bid,
                    }
                )

        # Weekend gaps: Friday -> Sunday/Monday boundary
        df["dt"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
        df["weekday"] = df["dt"].dt.weekday
        fri = df[df["weekday"] == 4]
        sun_mon = df[df["weekday"].isin([6, 0])]
        if not fri.empty and not sun_mon.empty:
            close_row = fri.iloc[-1]
            open_row = sun_mon.iloc[0]
            gap_pts = float(open_row["ask"]) - float(close_row["bid"])
            if abs(gap_pts) >= 0.01:
                events.append(
                    {
                        "type": "weekend_gap",
                        "symbol": self.config.symbol,
                        "close_ts_ms": int(close_row["timestamp_ms"]),
                        "open_ts_ms": int(open_row["timestamp_ms"]),
                        "close_bid": float(close_row["bid"]),
                        "open_ask": float(open_row["ask"]),
                        "gap_points": round(gap_pts, 5),
                    }
                )

        return events

    def run_once(self) -> None:
        events = self.extract()
        out = self.config.data_root / "gaps" / "gap_events.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")
        if events:
            self.manifest.register_file(out, kind="gaps", symbol=self.config.symbol)
        self.stats.rows_written = len(events)
        self.stats.metadata["gap_count"] = len(events)
