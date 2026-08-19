"""ExecutionLogger — shadow mode only, never places trades."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.research.phase30f.collectors.base import BaseCollector
from tradingbot.ml.research.phase30f.storage.parquet_store import ParquetStore
from tradingbot.ml.research.phase30f.validation.schema import validate_execution_row


class ExecutionLogger(BaseCollector):
    """
    Shadow execution logger — records hypothetical fills without order_send.

    For demo calibration, external processes can call log_shadow_execution().
    This collector NEVER calls mt5.order_send.
    """

    name = "ExecutionLogger"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._parquet = ParquetStore(self.config.data_root / "executions")
        self._buffer: list[dict[str, Any]] = []

    def log_shadow_execution(
        self,
        *,
        symbol: str,
        direction: str,
        leg: str,
        requested_price: float,
        fill_price: float,
        requested_lot: float = 0.01,
        filled_lot: float = 0.01,
        retcode: int = 10009,
        quoted_bid: float | None = None,
        quoted_ask: float | None = None,
        send_ms: int | None = None,
        fill_ms: int | None = None,
        send_monotonic_ns: int | None = None,
    ) -> dict[str, Any]:
        if not self.config.shadow_mode:
            raise RuntimeError("ExecutionLogger requires shadow_mode=True — no live orders")

        quote = self.client.symbol_info_tick(self.config.broker_symbol)
        bid = quoted_bid if quoted_bid is not None else (quote.bid if quote else 0.0)
        ask = quoted_ask if quoted_ask is not None else (quote.ask if quote else 0.0)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        t_send = send_ms or now_ms
        t_fill = fill_ms or (t_send + 25)
        mono = send_monotonic_ns or time.perf_counter_ns()

        slip = fill_price - requested_price
        if direction.upper() == "SELL":
            slip = requested_price - fill_price
        spread_at_send = ask - bid
        delay_ms = max(0, t_fill - t_send)

        row = {
            "execution_id": str(uuid.uuid4()),
            "order_id": str(uuid.uuid4()),
            "ticket": 0,
            "symbol": symbol,
            "direction": direction.upper(),
            "leg": leg,
            "requested_price": requested_price,
            "quoted_bid": bid,
            "quoted_ask": ask,
            "fill_price": fill_price,
            "filled_lot": filled_lot,
            "requested_lot": requested_lot,
            "slippage_points": round(slip, 5),
            "entry_slippage_points": round(slip, 5) if leg == "entry" else 0.0,
            "exit_slippage_points": round(slip, 5) if leg == "exit" else 0.0,
            "spread_at_send": round(spread_at_send, 5),
            "execution_delay_ms": delay_ms,
            "retcode": retcode,
            "partial_fill": filled_lot < requested_lot,
            "price_improvement": slip < 0,
            "timestamp_send_ms": t_send,
            "timestamp_fill_ms": t_fill,
            "local_send_monotonic_ns": mono,
            "shadow_mode": True,
        }
        errs = validate_execution_row(row)
        if errs:
            raise ValueError(f"invalid shadow execution: {errs}")
        self._buffer.append(row)
        self.stats.rows_written += 1
        return row

    def flush(self) -> int:
        if not self._buffer:
            return 0
        path = self._parquet.write_table("shadow_executions.parquet", self._buffer)
        self.manifest.register_file(path, kind="executions", symbol=self.config.symbol)
        n = len(self._buffer)
        self._buffer.clear()
        return n

    def run_once(self) -> None:
        # Shadow logger is event-driven; run_once flushes pending buffer.
        self.flush()
