"""SymbolSnapshot — daily symbol, account, terminal snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from tradingbot.ml.research.phase30f.collectors.base import BaseCollector


class SymbolSnapshot(BaseCollector):
    name = "SymbolSnapshot"

    def run_once(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_dir = self.config.data_root / "symbol_info"
        out_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "date_utc": today,
            "symbol": self.config.symbol,
            "symbol_info": self.client.symbol_info(self.config.broker_symbol),
            "account_info": self.client.account_info(),
            "terminal_info": self.client.terminal_info(),
            "captured_utc": datetime.now(timezone.utc).isoformat(),
        }
        path = out_dir / f"{today}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        self.manifest.register_file(path, kind="symbol_snapshot", symbol=self.config.symbol)
        self.stats.rows_written += 1
        self.stats.metadata["snapshot_date"] = today
