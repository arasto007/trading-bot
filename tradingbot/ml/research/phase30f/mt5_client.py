"""MT5 research client — read-only interface with mock for tests."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


@dataclass(frozen=True)
class TickQuote:
    bid: float
    ask: float
    time_msc: int
    last: float = 0.0
    volume: float = 0.0
    flags: int = 0


@dataclass(frozen=True)
class ShadowOrderResult:
    retcode: int
    price: float
    volume: float
    comment: str = ""
    deal: int = 0
    order: int = 0
    bid: float = 0.0
    ask: float = 0.0


class Mt5ResearchClient(Protocol):
    def connect(self) -> bool: ...
    def reconnect(self) -> bool: ...
    def is_connected(self) -> bool: ...
    def symbol_info_tick(self, symbol: str) -> TickQuote | None: ...
    def copy_ticks_range(
        self, symbol: str, date_from: datetime, date_to: datetime
    ) -> list[TickQuote]: ...
    def history_deals_get(self, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]: ...
    def history_orders_get(self, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]: ...
    def symbol_info(self, symbol: str) -> dict[str, Any] | None: ...
    def account_info(self) -> dict[str, Any] | None: ...
    def terminal_info(self) -> dict[str, Any] | None: ...


def _serialize_named(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "_asdict"):
        return dict(obj._asdict())
    return dict(obj)


class LiveMt5ResearchClient:
    """Read-only MT5 wrapper — never calls order_send."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._connected = False

    def connect(self) -> bool:
        from tradingbot.adapters.mt5_utils import ensure_mt5_connected

        sym = self._config.get("symbol", "XAUUSD")
        ok = ensure_mt5_connected(self._config, symbols=[sym], strict_account=False)
        self._connected = bool(ok)
        return self._connected

    def reconnect(self) -> bool:
        self._connected = False
        time.sleep(0.1)
        return self.connect()

    def is_connected(self) -> bool:
        if not self._connected:
            return False
        try:
            import MetaTrader5 as mt5

            return bool(mt5.terminal_info())
        except Exception:
            return False

    def symbol_info_tick(self, symbol: str) -> TickQuote | None:
        import MetaTrader5 as mt5

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        t_msc = int(getattr(tick, "time_msc", 0) or 0)
        if t_msc <= 0:
            t_msc = int(getattr(tick, "time", 0) or 0) * 1000
        return TickQuote(
            bid=float(tick.bid),
            ask=float(tick.ask),
            time_msc=t_msc,
            last=float(getattr(tick, "last", 0.0) or 0.0),
            volume=float(getattr(tick, "volume", 0.0) or 0.0),
            flags=int(getattr(tick, "flags", 0) or 0),
        )

    def copy_ticks_range(
        self, symbol: str, date_from: datetime, date_to: datetime
    ) -> list[TickQuote]:
        import MetaTrader5 as mt5

        if date_from.tzinfo is None:
            date_from = date_from.replace(tzinfo=timezone.utc)
        if date_to.tzinfo is None:
            date_to = date_to.replace(tzinfo=timezone.utc)
        rows = mt5.copy_ticks_range(symbol, date_from, date_to, mt5.COPY_TICKS_ALL)
        if rows is None or len(rows) == 0:
            return []
        out: list[TickQuote] = []
        for row in rows:
            t_msc = int(row["time_msc"]) if "time_msc" in row.dtype.names else int(row["time"]) * 1000
            out.append(
                TickQuote(
                    bid=float(row["bid"]),
                    ask=float(row["ask"]),
                    time_msc=t_msc,
                    last=float(row.get("last", 0.0) or 0.0),
                    volume=float(row.get("volume", 0.0) or 0.0),
                    flags=int(row.get("flags", 0) or 0),
                )
            )
        return out

    def history_deals_get(self, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        import MetaTrader5 as mt5

        deals = mt5.history_deals_get(date_from, date_to)
        if deals is None:
            return []
        return [_serialize_named(d) for d in deals]

    def history_orders_get(self, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        import MetaTrader5 as mt5

        orders = mt5.history_orders_get(date_from, date_to)
        if orders is None:
            return []
        return [_serialize_named(o) for o in orders]

    def symbol_info(self, symbol: str) -> dict[str, Any] | None:
        import MetaTrader5 as mt5

        info = mt5.symbol_info(symbol)
        return _serialize_named(info) if info else None

    def account_info(self) -> dict[str, Any] | None:
        import MetaTrader5 as mt5

        info = mt5.account_info()
        return _serialize_named(info) if info else None

    def terminal_info(self) -> dict[str, Any] | None:
        import MetaTrader5 as mt5

        info = mt5.terminal_info()
        return _serialize_named(info) if info else None


class MockMt5ResearchClient:
    """Deterministic mock for unit tests — no MT5 terminal required."""

    def __init__(self, ticks: list[TickQuote] | None = None) -> None:
        self._connected = False
        self._ticks = list(ticks or [])
        self._idx = 0
        self.connect_calls = 0
        self.reconnect_calls = 0

    def connect(self) -> bool:
        self.connect_calls += 1
        self._connected = True
        return True

    def reconnect(self) -> bool:
        self.reconnect_calls += 1
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def symbol_info_tick(self, symbol: str) -> TickQuote | None:
        if not self._ticks:
            now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            return TickQuote(bid=2000.0, ask=2000.3, time_msc=now_ms)
        tick = self._ticks[min(self._idx, len(self._ticks) - 1)]
        self._idx += 1
        return tick

    def copy_ticks_range(
        self, symbol: str, date_from: datetime, date_to: datetime
    ) -> list[TickQuote]:
        f_ms = int(date_from.timestamp() * 1000)
        t_ms = int(date_to.timestamp() * 1000)
        return [t for t in self._ticks if f_ms <= t.time_msc <= t_ms]

    def history_deals_get(self, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        return [
            {
                "ticket": 1,
                "order": 1,
                "time_msc": int(date_from.timestamp() * 1000) + 1000,
                "type": 0,
                "entry": 0,
                "volume": 0.01,
                "price": 2000.1,
                "commission": 0.0,
                "swap": 0.0,
                "symbol": "XAUUSD",
            }
        ]

    def history_orders_get(self, date_from: datetime, date_to: datetime) -> list[dict[str, Any]]:
        return [
            {
                "ticket": 1,
                "time_msc": int(date_from.timestamp() * 1000) + 500,
                "type": 0,
                "state": 4,
                "volume": 0.01,
                "price": 2000.0,
                "symbol": "XAUUSD",
            }
        ]

    def symbol_info(self, symbol: str) -> dict[str, Any] | None:
        return {
            "name": symbol,
            "digits": 2,
            "point": 0.01,
            "spread": 30,
            "trade_stops_level": 0,
            "trade_freeze_level": 0,
            "volume_min": 0.01,
            "volume_step": 0.01,
            "volume_max": 100.0,
        }

    def account_info(self) -> dict[str, Any] | None:
        return {
            "balance": 10000.0,
            "equity": 10000.0,
            "margin": 0.0,
            "margin_free": 10000.0,
            "margin_level": 0.0,
            "leverage": 100,
            "currency": "USD",
        }

    def terminal_info(self) -> dict[str, Any] | None:
        return {"connected": True, "ping": 12, "company": "MockBroker", "name": "MockTerminal"}
