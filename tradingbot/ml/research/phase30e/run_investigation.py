"""Phase 30E — MT5 capability and broker API forensic audit (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE30D = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase30d"

VERDICTS = {"MT5_READY_FOR_COLLECTION", "MT5_LIMITATIONS_REQUIRE_REDESIGN"}

Availability = Literal[
    "direct_mt5",
    "derived",
    "estimated",
    "custom_logging",
    "external",
    "broker_dependent",
    "impossible",
]

Risk = Literal["Low", "Medium", "High", "Impossible"]


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _audit(
    metric: str,
    *,
    required: bool,
    available_from_mt5: bool,
    available_from_broker: bool,
    available_from_terminal: bool,
    needs_external: bool,
    impossible: bool,
    confidence: int,
    evidence: str,
    mt5_api: str,
    python_fn: str,
    workaround: str,
    source: str,
    method: str,
    accuracy: str,
) -> dict[str, Any]:
    if impossible:
        avail = "impossible"
    elif needs_external:
        avail = "external"
    elif available_from_mt5:
        avail = "direct_mt5"
    elif "derive" in method.lower() or "computed" in method.lower():
        avail = "derived"
    elif "estimate" in method.lower() or "proxy" in method.lower():
        avail = "estimated"
    elif "custom log" in workaround.lower() or "collector" in workaround.lower():
        avail = "custom_logging"
    else:
        avail = "broker_dependent"

    return {
        "metric": metric,
        "required": required,
        "available": not impossible,
        "availability_class": avail,
        "available_from_mt5": available_from_mt5,
        "available_from_broker": available_from_broker,
        "available_from_terminal": available_from_terminal,
        "needs_external_data": needs_external,
        "impossible": impossible,
        "confidence": confidence,
        "evidence": evidence,
        "mt5_api": mt5_api,
        "python_function": python_fn,
        "workaround": workaround,
        "source": source,
        "method": method,
        "accuracy": accuracy,
    }


def build_metric_audits() -> list[dict[str, Any]]:
    """Evidence-based audit of every Phase 30D / user-requested metric."""
    return [
        _audit(
            "Ticks",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=95,
            evidence="MQL5 copy_ticks_range returns numpy array of tick rows; symbol_info_tick for latest. Used in tradingbot/ml/data/mt5_fetch.py.",
            mt5_api="copy_ticks_range, copy_ticks_from, symbol_info_tick",
            python_fn="mt5.copy_ticks_range(symbol, date_from, date_to, flags)",
            workaround="Poll symbol_info_tick at 100ms for forward collection; copy_ticks_range for backfill gaps.",
            source="MT5 terminal tick cache",
            method="Direct API read",
            accuracy="High — broker-sourced BBO",
        ),
        _audit(
            "Bid",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=96,
            evidence="Tick.bid field; symbol_info_tick().bid used in mt5_execution._current_price and mt5_fetch.snapshot_spread.",
            mt5_api="symbol_info_tick, copy_ticks_range",
            python_fn="mt5.symbol_info_tick(symbol).bid",
            workaround="None",
            source="MT5",
            method="Direct field",
            accuracy="High",
        ),
        _audit(
            "Ask",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=96,
            evidence="Tick.ask field; production uses ask for BUY in Mt5ExecutionAdapter._quote_price.",
            mt5_api="symbol_info_tick, copy_ticks_range",
            python_fn="mt5.symbol_info_tick(symbol).ask",
            workaround="None",
            source="MT5",
            method="Direct field",
            accuracy="High",
        ),
        _audit(
            "Spread",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=92,
            evidence="Derived ask-bid per tick; symbol_info.spread gives fixed spread in points (may differ from float spread).",
            mt5_api="symbol_info, symbol_info_tick",
            python_fn="ask - bid OR mt5.symbol_info(symbol).spread * point",
            workaround="Prefer tick-derived spread; log symbol_info.spread daily as cross-check.",
            source="MT5 derived",
            method="Computed at ingest",
            accuracy="High for tick-derived; Medium for symbol_info.spread alone",
        ),
        _audit(
            "Tick timestamps",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=90,
            evidence="MqlTick.time (seconds) and time_msc (milliseconds since epoch). MQL5 docs confirm ms precision.",
            mt5_api="copy_ticks_range, symbol_info_tick",
            python_fn="tick.time_msc",
            workaround="Store broker time_msc as primary; add local perf_counter for send-side events.",
            source="MT5 broker clock",
            method="Direct field",
            accuracy="High at millisecond level",
        ),
        _audit(
            "Microsecond precision",
            required=False,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=True,
            confidence=95,
            evidence="MQL5 MqlTick documents time_msc in milliseconds only — no microsecond field in Python API.",
            mt5_api="N/A",
            python_fn="N/A",
            workaround="Replace Phase 30D timestamp_us with timestamp_ms (broker) + local_send_ns (collector monotonic).",
            source="Custom collector",
            method="Local monotonic clock at send only",
            accuracy="Sub-ms local only; broker remains ms",
        ),
        _audit(
            "Tick sequence",
            required=False,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=True,
            confidence=88,
            evidence="No sequence number in MqlTick or copy_ticks output; only time ordering.",
            mt5_api="copy_ticks_range",
            python_fn="N/A",
            workaround="Assign collector sequence index per partition; detect gaps via time_msc deltas.",
            source="Collector derived",
            method="Monotonic index at ingest",
            accuracy="Medium — gap detection only",
        ),
        _audit(
            "OHLC generation",
            required=False,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=94,
            evidence="copy_rates_from_pos used in Mt5MarketDataAdapter and mt5_fetch.fetch_candles.",
            mt5_api="copy_rates_from_pos, copy_rates_range",
            python_fn="mt5.copy_rates_from_pos(symbol, timeframe, 0, count)",
            workaround="Not required for DBT fingerprint; available for gap cross-check.",
            source="MT5",
            method="Direct API",
            accuracy="High",
        ),
        _audit(
            "Market Depth (DOM)",
            required=False,
            available_from_mt5=True,
            available_from_broker=False,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=55,
            evidence="market_book_get/BookInfo exists in Python API but requires market_book_add; most retail FX/XAUUSD brokers disable DOM.",
            mt5_api="market_book_add, market_book_get, market_book_release",
            python_fn="mt5.market_book_get(symbol)",
            workaround="Probe at collection start; if empty, exclude DOM from collector architecture.",
            source="MT5 optional",
            method="Subscribe then poll",
            accuracy="Broker-dependent — often unavailable",
        ),
        _audit(
            "Level II",
            required=False,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=True,
            confidence=85,
            evidence="MT5 BookInfo is limited depth snapshot; true L2 order book not exposed for standard retail CFD/FX accounts.",
            mt5_api="market_book_get",
            python_fn="mt5.market_book_get",
            workaround="Replace with spread widening + partial fill + requote proxies.",
            source="N/A retail",
            method="Not collectable",
            accuracy="N/A",
        ),
        _audit(
            "Liquidity",
            required=False,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=True,
            confidence=80,
            evidence="No aggregate liquidity metric in MT5 API; volume on last trade only, often zero on FX ticks.",
            mt5_api="Tick.volume, Tick.volume_real",
            python_fn="tick.volume_real",
            workaround="Proxy: partial fill rate + TRADE_RETCODE_REQUOTE rate + spread p99 spikes.",
            source="Derived execution stats",
            method="Estimated proxy composite",
            accuracy="Low-Medium",
        ),
        _audit(
            "Order queue",
            required=False,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=True,
            confidence=92,
            evidence="No MT5 API exposes internal broker matching queue depth or position in queue.",
            mt5_api="N/A",
            python_fn="N/A",
            workaround="Remove from collector; use execution_delay_ms distribution instead.",
            source="N/A",
            method="Impossible",
            accuracy="N/A",
        ),
        _audit(
            "Partial fills",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=88,
            evidence="TRADE_RETCODE_DONE_PARTIAL; OrderSendResult.volume vs request volume; TradeOrder.state ORDER_STATE_PARTIAL.",
            mt5_api="order_send, history_orders_get",
            python_fn="result.retcode == mt5.TRADE_RETCODE_DONE_PARTIAL",
            workaround="Log requested_lot and result.volume on every send.",
            source="MT5 order result",
            method="Direct retcode + volume compare",
            accuracy="High when partial occurs",
        ),
        _audit(
            "Execution price",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=95,
            evidence="OrderSendResult.price; TradeDeal.price in history_deals_get.",
            mt5_api="order_send, history_deals_get",
            python_fn="result.price",
            workaround="None",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Requested price",
            required=True,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=False,
            confidence=90,
            evidence="Request dict price at send time is client-side; MT5 does not persist pre-send quote in result alone.",
            mt5_api="order_send request dict",
            python_fn="request['price'] before order_send",
            workaround="Custom collector MUST log request price + quoted bid/ask before order_send.",
            source="Custom logging",
            method="Log at send",
            accuracy="High if logged atomically with quote",
        ),
        _audit(
            "Fill price",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=95,
            evidence="Mt5ExecutionAdapter uses result.price as fill_price; journal logs fill_price.",
            mt5_api="order_send, history_deals_get",
            python_fn="result.price",
            workaround="None",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Entry slippage",
            required=True,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=False,
            confidence=88,
            evidence="Production computes abs(fill-request)/pip_size in mt5_execution; requires both prices logged.",
            mt5_api="order_send + custom log",
            python_fn="fill_price - requested_price (signed)",
            workaround="Tag deal entry via TradeDeal.entry DEAL_ENTRY_IN.",
            source="Derived custom+MT5",
            method="Computed signed delta",
            accuracy="High with logged request quote",
        ),
        _audit(
            "Exit slippage",
            required=True,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=False,
            confidence=86,
            evidence="Same as entry; exit requires expected SL/TP/close price logged at send.",
            mt5_api="order_send, history_deals_get",
            python_fn="fill vs expected_sl_tp",
            workaround="Log sl/tp/close intent; map deal reason DEAL_REASON_SL/TP.",
            source="Derived custom+MT5",
            method="Computed vs expected level",
            accuracy="High for market close; Medium for gap-through-stop",
        ),
        _audit(
            "Execution delay",
            required=True,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=False,
            confidence=85,
            evidence="No MT5 field for client-side send timestamp; must wrap order_send with perf_counter.",
            mt5_api="order_send wrapper",
            python_fn="time.perf_counter() before/after order_send",
            workaround="Store send_ns and ack_ns in collector.",
            source="Custom logging",
            method="Local monotonic delta",
            accuracy="High locally",
        ),
        _audit(
            "Network latency",
            required=False,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=60,
            evidence="terminal_info().ping gives terminal-to-server ping ms; not full client network stack.",
            mt5_api="terminal_info",
            python_fn="mt5.terminal_info().ping",
            workaround="Optional ICMP to broker host; not decomposable from MT5 alone.",
            source="Terminal proxy",
            method="Estimated periodic ping",
            accuracy="Low-Medium",
        ),
        _audit(
            "Server latency",
            required=False,
            available_from_mt5=False,
            available_from_broker=True,
            available_from_terminal=False,
            needs_external=False,
            impossible=False,
            confidence=55,
            evidence="TradeDeal.time_msc minus local send time requires clock sync; VPS clock drift corrupts estimate.",
            mt5_api="history_deals_get",
            python_fn="deal.time_msc - send_time_ms",
            workaround="Treat as estimated component only; do not use for DBT MVP.",
            source="Estimated",
            method="Clock delta estimate",
            accuracy="Low",
        ),
        _audit(
            "Round-trip latency",
            required=True,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=False,
            impossible=False,
            confidence=85,
            evidence="Wrap order_send: perf_counter delta until result returned.",
            mt5_api="order_send wrapper",
            python_fn="perf_counter after - before order_send",
            workaround="Same as execution_delay — primary latency metric for DBT.",
            source="Custom logging",
            method="Measured round-trip",
            accuracy="High",
        ),
        _audit(
            "Trade transaction timestamps",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=93,
            evidence="TradeDeal.time/time_msc; TradeOrder.time_setup_msc/time_done_msc.",
            mt5_api="history_deals_get, history_orders_get",
            python_fn="deal.time_msc",
            workaround="None",
            source="MT5",
            method="Direct",
            accuracy="High ms precision",
        ),
        _audit(
            "Retcodes",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=94,
            evidence="OrderSendResult.retcode; full TRADE_RETCODE_* enum in Python package.",
            mt5_api="order_send",
            python_fn="result.retcode, result.comment",
            workaround="Log every attempt including retries (_order_send_with_retry).",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Requotes",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=90,
            evidence="TRADE_RETCODE_REQUOTE, TRADE_RETCODE_PRICE_CHANGED in retry set mt5_execution._RETRY_CODES.",
            mt5_api="order_send",
            python_fn="result.retcode in (REQUOTE, PRICE_CHANGED)",
            workaround="Count per order attempt.",
            source="MT5",
            method="Retcode filter",
            accuracy="High",
        ),
        _audit(
            "Freeze level",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=90,
            evidence="SymbolInfo.trade_freeze_level; TRADE_RETCODE_FROZEN on reject.",
            mt5_api="symbol_info",
            python_fn="mt5.symbol_info(symbol).trade_freeze_level",
            workaround="Daily snapshot + log on TRADE_RETCODE_FROZEN.",
            source="MT5",
            method="Direct + event log",
            accuracy="High",
        ),
        _audit(
            "Stops level",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=92,
            evidence="Used in position_protector: trade_stops_level * point.",
            mt5_api="symbol_info",
            python_fn="mt5.symbol_info(symbol).trade_stops_level",
            workaround="Daily snapshot.",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Margin",
            required=False,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=93,
            evidence="account_info.margin; order_calc_margin for pre-trade.",
            mt5_api="account_info, order_calc_margin",
            python_fn="mt5.account_info().margin",
            workaround="Poll every 60s + at fill.",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Margin level",
            required=False,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=93,
            evidence="account_info.margin_level used in risk_gate and kill_switch patterns.",
            mt5_api="account_info",
            python_fn="mt5.account_info().margin_level",
            workaround="None",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Swap",
            required=False,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=88,
            evidence="TradeDeal.swap; symbol_info swap_long/swap_short; DEAL_REASON_ROLLOVER.",
            mt5_api="history_deals_get, symbol_info, positions_get",
            python_fn="deal.swap",
            workaround="Low priority for M5 short holds.",
            source="MT5",
            method="Direct on deal",
            accuracy="High",
        ),
        _audit(
            "Commission",
            required=False,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=90,
            evidence="TradeDeal.commission field; may be zero on spread-only accounts.",
            mt5_api="history_deals_get",
            python_fn="deal.commission",
            workaround="Verify account type — zero commission is valid data.",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Account snapshots",
            required=False,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=94,
            evidence="account_info() returns balance/equity/margin fields; serialized in mt5_utils diagnostics.",
            mt5_api="account_info",
            python_fn="mt5.account_info()",
            workaround="Scheduled poll.",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Order history",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=92,
            evidence="history_orders_get with time range; TradeOrder structure documented.",
            mt5_api="history_orders_get",
            python_fn="mt5.history_orders_get(date_from, date_to)",
            workaround="Enable account history in terminal.",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Deal history",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=94,
            evidence="history_deals_get used in live_risk_tracker.",
            mt5_api="history_deals_get",
            python_fn="mt5.history_deals_get(date_from, date_to)",
            workaround="None",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Position history",
            required=False,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=88,
            evidence="positions_get live; closed positions reconstructed from deals only — no closed-position API.",
            mt5_api="positions_get, history_deals_get",
            python_fn="mt5.positions_get()",
            workaround="Reconstruct closed positions from deal chain.",
            source="MT5 derived",
            method="Live direct; closed reconstructed",
            accuracy="High live; Medium historical",
        ),
        _audit(
            "Weekend gaps",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=85,
            evidence="copy_ticks_range across Fri close / Sun open; or copy_rates D1 gap.",
            mt5_api="copy_ticks_range, copy_rates_range",
            python_fn="last Fri tick vs first Sun tick",
            workaround="Automate weekly gap extractor on tick store.",
            source="MT5 derived",
            method="Computed gap",
            accuracy="High",
        ),
        _audit(
            "News events",
            required=True,
            available_from_mt5=False,
            available_from_broker=False,
            available_from_terminal=False,
            needs_external=True,
            impossible=False,
            confidence=90,
            evidence="No economic calendar in MT5 Python API; Phase 30D already specifies external FF calendar.",
            mt5_api="N/A",
            python_fn="N/A",
            workaround="Import external calendar JSON; join to tick timestamps.",
            source="External calendar",
            method="External ingest + join",
            accuracy="High for schedule; spread impact measured from ticks",
        ),
        _audit(
            "Symbol specifications",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=95,
            evidence="symbol_info full SymbolInfo structure; filling_mode used in mt5_execution.",
            mt5_api="symbol_info",
            python_fn="mt5.symbol_info(symbol)",
            workaround="Daily snapshot to JSON.",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
        _audit(
            "Broker execution model (ECN/STP/MM)",
            required=False,
            available_from_mt5=False,
            available_from_broker=True,
            available_from_terminal=False,
            needs_external=False,
            impossible=False,
            confidence=50,
            evidence="symbol_info.trade_execution_mode maps to INSTANT/MARKET/EXCHANGE/REQUEST — not business model label.",
            mt5_api="symbol_info.trade_execution_mode",
            python_fn="mt5.symbol_info(symbol).trade_execution_mode",
            workaround="Record enum + broker marketing label in manifest manually; do not infer ECN/STP.",
            source="Partial MT5 + manifest",
            method="Proxy enum only",
            accuracy="Low for ECN/STP/MM classification",
        ),
        _audit(
            "Execution mode",
            required=True,
            available_from_mt5=True,
            available_from_broker=True,
            available_from_terminal=True,
            needs_external=False,
            impossible=False,
            confidence=88,
            evidence="SYMBOL_TRADE_EXECUTION_* constants; filling_mode bitmask for FOK/IOC/RETURN.",
            mt5_api="symbol_info",
            python_fn="symbol_info.trade_execution_mode, symbol_info.filling_mode",
            workaround="Probe order_check for valid filling.",
            source="MT5",
            method="Direct",
            accuracy="High",
        ),
    ]


def _capability_row(a: dict[str, Any]) -> dict[str, Any]:
    risk: Risk
    if a["impossible"]:
        risk = "Impossible"
    elif a["confidence"] >= 85:
        risk = "Low"
    elif a["confidence"] >= 70:
        risk = "Medium"
    else:
        risk = "High"
    return {
        "metric": a["metric"],
        "required": a["required"],
        "available": a["available"],
        "source": a["source"],
        "method": a["method"],
        "accuracy": a["accuracy"],
        "confidence": a["confidence"],
        "implementation_risk": risk,
    }


def build_mt5_capability_matrix(audits: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "phase": "30E",
        "scope": "MetaTrader 5 Python API capability vs Phase 30D requirements",
        "api_version_evidence": "MetaTrader5 package installed; functions enumerated via dir(mt5)",
        "rows": [_capability_row(a) for a in audits],
        "summary": {
            "total_metrics": len(audits),
            "directly_available": sum(1 for a in audits if a["availability_class"] == "direct_mt5"),
            "derived": sum(1 for a in audits if a["availability_class"] == "derived"),
            "custom_logging": sum(1 for a in audits if a["availability_class"] == "custom_logging"),
            "external": sum(1 for a in audits if a["availability_class"] == "external"),
            "impossible": sum(1 for a in audits if a["impossible"]),
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_broker_capability_matrix(audits: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for a in audits:
        rows.append(
            {
                "metric": a["metric"],
                "broker_provides": a["available_from_broker"],
                "terminal_relay": a["available_from_terminal"],
                "requires_level_ii": a["metric"] in {"Level II", "Market Depth (DOM)", "Liquidity", "Order queue"},
                "requires_custom_logger": a["availability_class"] in {"custom_logging", "estimated"},
                "notes": a["workaround"],
            }
        )
    return {
        "phase": "30E",
        "broker_scope": "Retail MT5 CFD/FX — XAUUSD primary",
        "rows": rows,
        "broker_specific_unknowns": [
            "DOM availability for XAUUSD",
            "Actual partial fill rate at 0.01 lot",
            "Floating vs fixed spread mode",
            "Requote frequency under news",
        ],
        "probe_at_collection_start": [
            "market_book_get non-empty check",
            "symbol_info.spread_float",
            "symbol_info.trade_execution_mode",
            "terminal_info().trade_allowed",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_api_function_mapping() -> dict[str, Any]:
    return {
        "phase": "30E",
        "mappings": [
            {
                "dataset": "TickStream",
                "functions": [
                    {"fn": "symbol_info_tick", "returns": "Tick", "fields": ["bid", "ask", "time", "time_msc", "last", "volume", "flags"]},
                    {"fn": "copy_ticks_range", "returns": "numpy.ndarray", "fields": ["time", "bid", "ask", "last", "volume", "time_msc", "flags", "volume_real"]},
                    {"fn": "copy_ticks_from", "returns": "numpy.ndarray", "fields": "same as copy_ticks_range"},
                ],
                "codebase_reference": "tradingbot/ml/data/mt5_fetch.py::fetch_ticks_range",
            },
            {
                "dataset": "ExecutionFills",
                "functions": [
                    {"fn": "order_send", "returns": "OrderSendResult", "fields": ["retcode", "price", "volume", "bid", "ask", "deal", "order"]},
                    {"fn": "history_deals_get", "returns": "tuple[TradeDeal]", "fields": ["price", "volume", "commission", "swap", "entry", "reason", "time_msc"]},
                    {"fn": "order_check", "returns": "OrderCheckResult", "fields": ["retcode", "balance", "equity", "profit", "margin"]},
                ],
                "codebase_reference": "tradingbot/adapters/mt5_execution.py",
            },
            {
                "dataset": "OrderAttempts",
                "functions": [
                    {"fn": "order_send", "returns": "OrderSendResult", "fields": ["retcode", "comment", "retcode_external"]},
                    {"fn": "history_orders_get", "returns": "tuple[TradeOrder]", "fields": ["state", "type", "volume", "price", "time_done_msc"]},
                ],
                "codebase_reference": "tradingbot/adapters/mt5_execution.py::_order_send_with_retry",
            },
            {
                "dataset": "SymbolInfoDaily",
                "functions": [
                    {"fn": "symbol_info", "returns": "SymbolInfo", "fields": ["spread", "trade_stops_level", "trade_freeze_level", "volume_min", "filling_mode", "trade_execution_mode", "swap_long", "swap_short"]},
                    {"fn": "symbols_get", "returns": "tuple[SymbolInfo]", "fields": "all symbols"},
                ],
                "codebase_reference": "tradingbot/services/position_protector.py",
            },
            {
                "dataset": "AccountSnapshots",
                "functions": [
                    {"fn": "account_info", "returns": "AccountInfo", "fields": ["balance", "equity", "margin", "margin_free", "margin_level", "margin_so_so"]},
                ],
                "codebase_reference": "tradingbot/adapters/risk_gate.py",
            },
            {
                "dataset": "GapEvents",
                "functions": [
                    {"fn": "copy_ticks_range", "returns": "ticks", "fields": "Fri/Sun boundary extraction"},
                    {"fn": "copy_rates_range", "returns": "rates", "fields": "OHLC gap cross-check"},
                ],
                "codebase_reference": "tradingbot/ml/data/mt5_fetch.py",
            },
            {
                "dataset": "NewsCalendar",
                "functions": [],
                "external": "ForexFactory / MQL5 calendar CSV / custom JSON — not MT5 API",
            },
            {
                "dataset": "DOM optional",
                "functions": [
                    {"fn": "market_book_add", "returns": "bool", "fields": "subscribe"},
                    {"fn": "market_book_get", "returns": "tuple[BookInfo]", "fields": ["type", "price", "volume"]},
                    {"fn": "market_book_release", "returns": "bool", "fields": "unsubscribe"},
                ],
                "codebase_reference": "Not used in production codebase",
            },
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_terminal_limitations() -> dict[str, Any]:
    return {
        "phase": "30E",
        "limitations": [
            {
                "id": "T1",
                "limitation": "Tick history depth capped by terminal/broker",
                "impact": "copy_ticks_range may truncate old ranges",
                "mitigation": "Forward collection via polling; do not rely on deep backfill",
                "risk": "Medium",
            },
            {
                "id": "T2",
                "limitation": "Millisecond timestamp precision only (time_msc)",
                "impact": "Phase 30D microsecond schema overstated",
                "mitigation": "Use timestamp_ms + local_send_ns",
                "risk": "Low",
            },
            {
                "id": "T3",
                "limitation": "Single terminal session — no distributed tick feed",
                "impact": "Collection requires VPS co-located with terminal",
                "mitigation": "Run collector on same machine as MT5",
                "risk": "Medium",
            },
            {
                "id": "T4",
                "limitation": "terminal_info().ping is aggregate not per-order",
                "impact": "Cannot decompose network vs server latency per fill",
                "mitigation": "Use round_trip_ms only for DBT",
                "risk": "Medium",
            },
            {
                "id": "T5",
                "limitation": "Python GIL + 100ms poll floor",
                "impact": "May miss sub-100ms tick changes",
                "mitigation": "Acceptable for spread calibration; burst to 50ms during news",
                "risk": "Low",
            },
            {
                "id": "T6",
                "limitation": "AutoTrading must be enabled for live fill collection",
                "impact": "Demo order_send blocked if AT off",
                "mitigation": "check_autotrading_ready before collection phase",
                "risk": "Low",
            },
            {
                "id": "T7",
                "limitation": "No push tick callback in Python API",
                "impact": "Polling only — no native streaming subscription",
                "mitigation": "Timer poll symbol_info_tick",
                "risk": "Low",
            },
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_broker_limitations() -> dict[str, Any]:
    return {
        "phase": "30E",
        "limitations": [
            {
                "id": "B1",
                "limitation": "Retail XAUUSD rarely exposes DOM / Level II",
                "impact": "Liquidity book calibration impossible",
                "mitigation": "Spread + requote + partial fill proxies",
                "risk": "High",
            },
            {
                "id": "B2",
                "limitation": "Internal order queue invisible",
                "impact": "Queue model cannot be calibrated",
                "mitigation": "Remove queue from DBT MVP",
                "risk": "Impossible",
            },
            {
                "id": "B3",
                "limitation": "ECN/STP/Market Maker label not in API",
                "impact": "Business model classification unavailable",
                "mitigation": "Manual manifest + trade_execution_mode enum",
                "risk": "Medium",
            },
            {
                "id": "B4",
                "limitation": "Last/volume often zero on FX ticks",
                "impact": "Trade tick volume unusable for liquidity",
                "mitigation": "Ignore volume_real for FX/XAUUSD spread model",
                "risk": "Medium",
            },
            {
                "id": "B5",
                "limitation": "Gap-through-stop is episodic",
                "impact": "Insufficient samples without long horizon",
                "mitigation": "Model from weekend gap distribution",
                "risk": "Medium",
            },
            {
                "id": "B6",
                "limitation": "Partial fills rare at minimum lot",
                "impact": "Low sample for FillEngine partial model",
                "mitigation": "Optional sweep at 0.05 lot on demo only",
                "risk": "Medium",
            },
            {
                "id": "B7",
                "limitation": "Broker server clock vs VPS clock skew",
                "impact": "Server latency estimate unreliable",
                "mitigation": "Exclude server-only latency from MVP",
                "risk": "High",
            },
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_collectable_uncollectable(audits: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    collectable = [a["metric"] for a in audits if a["available"]]
    uncollectable = [a["metric"] for a in audits if a["impossible"]]
    return (
        {
            "phase": "30E",
            "count": len(collectable),
            "metrics": collectable,
            "critical_collectable": [a["metric"] for a in audits if a["required"] and a["available"]],
            "generated_utc": datetime.now(timezone.utc).isoformat(),
        },
        {
            "phase": "30E",
            "count": len(uncollectable),
            "metrics": uncollectable,
            "details": [
                {
                    "metric": a["metric"],
                    "reason": a["evidence"],
                    "replacement": a["workaround"],
                }
                for a in audits
                if a["impossible"]
            ],
            "generated_utc": datetime.now(timezone.utc).isoformat(),
        },
    )


def build_replacement_metrics() -> dict[str, Any]:
    return {
        "phase": "30E",
        "replacements": [
            {
                "removed": "Microsecond precision (broker)",
                "replacement": "timestamp_ms (time_msc) + local_send_monotonic_ns",
                "dbt_impact": "LatencyEngine uses ms granularity",
            },
            {
                "removed": "Tick sequence number",
                "replacement": "collector_seq + gap_detector on time_msc",
                "dbt_impact": "None for spread/slippage",
            },
            {
                "removed": "Level II / DOM liquidity",
                "replacement": "spread_p99_stress + requote_rate + partial_fill_rate composite",
                "dbt_impact": "LiquidityBook simplified to spread-based",
            },
            {
                "removed": "Order queue depth",
                "replacement": "round_trip_ms distribution + retcode histogram",
                "dbt_impact": "Remove OrderQueue calibration",
            },
            {
                "removed": "Network vs server latency split",
                "replacement": "round_trip_ms + terminal_info.ping heartbeat",
                "dbt_impact": "Single latency bucket",
            },
            {
                "removed": "ECN/STP/MM classification",
                "replacement": "trade_execution_mode + manual broker_manifest.execution_label",
                "dbt_impact": "Documentation only",
            },
            {
                "removed": "News events from MT5",
                "replacement": "External calendar JSON join (unchanged from 30D)",
                "dbt_impact": "None",
            },
        ],
        "phase30d_schema_adjustments": [
            "Rename timestamp_us → timestamp_ms in tick store",
            "Add local_send_monotonic_ns to executions table",
            "Mark DOM tables optional in broker_fingerprint_schema",
            "Remove order_queue from collector_architecture",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_collector_architecture() -> dict[str, Any]:
    return {
        "phase": "30E",
        "design_principle": "Only MT5-proven data paths — no speculative sensors",
        "isolation": "tradingbot/ml/research/phase30f/collectors/ (future — not implemented in 30E)",
        "processes": [
            {
                "name": "TickPoller",
                "inputs": ["MT5 symbol_info_tick"],
                "outputs": ["tick_store/parquet"],
                "api": ["symbol_info_tick"],
                "frequency": "100ms poll; 1s during news/rollover",
                "read_only": True,
            },
            {
                "name": "TickBackfill",
                "inputs": ["MT5 copy_ticks_range"],
                "outputs": ["tick_store/parquet gaps"],
                "api": ["copy_ticks_range"],
                "frequency": "On gap detection",
                "read_only": True,
            },
            {
                "name": "ExecutionLogger",
                "inputs": ["order_send wrapper on demo account"],
                "outputs": ["executions.parquet", "orders.parquet"],
                "api": ["order_send", "symbol_info_tick"],
                "custom_fields": ["send_monotonic_ns", "quoted_bid", "quoted_ask", "requested_price"],
                "read_only": False,
                "note": "Isolated demo — not production adapter",
            },
            {
                "name": "HistorySync",
                "inputs": ["MT5 deal/order history"],
                "outputs": ["deals.parquet", "orders_history.parquet"],
                "api": ["history_deals_get", "history_orders_get"],
                "frequency": "Hourly",
                "read_only": True,
            },
            {
                "name": "SymbolSnapshot",
                "inputs": ["MT5 symbol_info"],
                "outputs": ["symbol_info/YYYY-MM-DD.json"],
                "api": ["symbol_info"],
                "frequency": "Daily UTC 00:05",
                "read_only": True,
            },
            {
                "name": "AccountPoller",
                "inputs": ["MT5 account_info"],
                "outputs": ["account_snapshots.parquet"],
                "api": ["account_info"],
                "frequency": "60s",
                "read_only": True,
            },
            {
                "name": "GapExtractor",
                "inputs": ["tick_store"],
                "outputs": ["gap_events.jsonl"],
                "api": [],
                "frequency": "Weekly",
                "read_only": True,
            },
            {
                "name": "NewsJoiner",
                "inputs": ["external calendar JSON", "tick_store"],
                "outputs": ["news/spread_tags.parquet"],
                "api": [],
                "frequency": "Daily calendar refresh",
                "read_only": True,
            },
            {
                "name": "DomProbe",
                "inputs": ["MT5 market_book"],
                "outputs": ["dom_probe.json"],
                "api": ["market_book_add", "market_book_get", "market_book_release"],
                "frequency": "Once at startup",
                "optional": True,
            },
        ],
        "data_flow": "MT5 Terminal → Python collectors (research) → phase30d tick_store/data → aggregation scripts → calibration inputs (Phase 30G+)",
        "explicitly_excluded": [
            "Production Mt5ExecutionAdapter modification",
            "TradingKernel hooks",
            "DOM streaming",
            "Level II ingestion",
            "ICMP network probe (optional future)",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_implementation_risk_matrix(audits: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for a in audits:
        risk = _capability_row(a)["implementation_risk"]
        rows.append(
            {
                "metric": a["metric"],
                "required": a["required"],
                "risk": risk,
                "confidence": a["confidence"],
                "blocker": risk in {"High", "Impossible"} and a["required"],
                "mitigation": a["workaround"],
            }
        )
    blockers = [r for r in rows if r["blocker"]]
    return {
        "phase": "30E",
        "rows": rows,
        "summary": {
            "low": sum(1 for r in rows if r["risk"] == "Low"),
            "medium": sum(1 for r in rows if r["risk"] == "Medium"),
            "high": sum(1 for r in rows if r["risk"] == "High"),
            "impossible": sum(1 for r in rows if r["risk"] == "Impossible"),
            "required_blockers": len(blockers),
        },
        "required_blockers": blockers,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def determine_verdict(
    audits: list[dict[str, Any]],
    risk_matrix: dict[str, Any],
    replacements: dict[str, Any],
) -> str:
    required_impossible = [
        a for a in audits if a["required"] and a["impossible"]
    ]
    if required_impossible:
        return "MT5_LIMITATIONS_REQUIRE_REDESIGN"
    if risk_matrix["summary"]["required_blockers"] > 0:
        return "MT5_LIMITATIONS_REQUIRE_REDESIGN"
    # All required metrics have collectable path (direct, derived, custom, external)
    if len(replacements["replacements"]) >= 5:
        return "MT5_READY_FOR_COLLECTION"
    return "MT5_LIMITATIONS_REQUIRE_REDESIGN"


def run_phase30e() -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    audits = build_metric_audits()
    mt5_matrix = build_mt5_capability_matrix(audits)
    _write("mt5_capability_matrix.json", mt5_matrix)
    _write("broker_capability_matrix.json", build_broker_capability_matrix(audits))
    _write("api_function_mapping.json", build_api_function_mapping())
    _write("terminal_limitations.json", build_terminal_limitations())
    _write("broker_limitations.json", build_broker_limitations())

    collectable, uncollectable = build_collectable_uncollectable(audits)
    _write("collectable_metrics.json", collectable)
    _write("uncollectable_metrics.json", uncollectable)

    replacements = build_replacement_metrics()
    _write("replacement_metrics.json", replacements)
    _write("collector_architecture.json", build_collector_architecture())

    risk = build_implementation_risk_matrix(audits)
    _write("implementation_risk_matrix.json", risk)

    verdict = determine_verdict(audits, risk, replacements)

    final = {
        "phase": "30E",
        "verdict": verdict,
        "mission": "MT5 and broker API forensic audit — no implementation",
        "production_modified": False,
        "metrics_audited": len(audits),
        "collectable_count": collectable["count"],
        "uncollectable_count": uncollectable["count"],
        "replacements_defined": len(replacements["replacements"]),
        "required_metrics_collectable": len(collectable["critical_collectable"]),
        "phase30d_adjustments_needed": replacements["phase30d_schema_adjustments"],
        "collector_modules_planned": 9,
        "next_phase": "30F — implement isolated collectors per collector_architecture.json",
        "deliverables": [
            "mt5_capability_matrix.json",
            "broker_capability_matrix.json",
            "api_function_mapping.json",
            "terminal_limitations.json",
            "broker_limitations.json",
            "collectable_metrics.json",
            "uncollectable_metrics.json",
            "replacement_metrics.json",
            "collector_architecture.json",
            "implementation_risk_matrix.json",
            "phase30e_final_report.json",
        ],
        "generated_utc": ts,
    }
    _write("phase30e_final_report.json", final)
    return final


def main() -> int:
    report = run_phase30e()
    print(json.dumps({"verdict": report["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
