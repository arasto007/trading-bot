"""Collect and enrich completed paper trades (read-only observation)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.ml.research.phase26a.exit_simulator import simulate_trade_exit
from tradingbot.ml.research.phase26a.journal_reader import read_completed_paper_trades, read_paper_executions
from tradingbot.ml.research.phase26a.trade_schema import CompletedPaperTrade


def _load_decisions_index(base_dir: str | None) -> dict[str, dict[str, Any]]:
    path = Path(base_dir or ".") / "data" / "ml" / "live" / "decisions.jsonl"
    if not path.is_file():
        return {}
    index: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("direction") not in ("BUY", "SELL"):
                continue
            key = f"{row.get('symbol')}:{row.get('timeframe')}:{row.get('timestamp', '')[:19]}"
            index[key] = row
    return index


def _indicator_snapshot(
    *,
    base_dir: str | None,
    symbol: str,
    timeframe: str,
    timestamp: str,
) -> dict[str, float | None]:
    try:
        from tradingbot.ml.data.stores.candle_store import CandleStore
        from tradingbot.ml.dataset.store import DatasetStore
        from tradingbot.ml.research.phase13_9.unified_features import build_unified_frame

        candles = CandleStore(base_dir).load(symbol, timeframe)
        dataset = DatasetStore(base_dir).load_v2(symbol, timeframe)
        if candles is None or dataset is None or candles.empty or dataset.empty:
            return {"adx": None, "rsi": None, "atr": None}

        unified = build_unified_frame(candles.tail(500), dataset)
        ts = pd.to_datetime(timestamp, utc=True)
        if ts not in unified.index and "timestamp" in unified.columns:
            rows = unified[unified["timestamp"] == ts]
        else:
            rows = unified.loc[[ts]] if ts in unified.index else unified.iloc[0:0]
        if rows.empty:
            pos = unified.index.searchsorted(ts)
            pos = min(max(pos, 0), len(unified) - 1)
            row = unified.iloc[pos]
        else:
            row = rows.iloc[-1]

        def _pick(*names: str) -> float | None:
            for name in names:
                if name in row.index and pd.notna(row[name]):
                    return float(row[name])
            return None

        return {
            "adx": _pick("adx", "ADX"),
            "rsi": _pick("rsi", "RSI"),
            "atr": _pick("atr", "ATR", "atr14"),
        }
    except Exception:
        return {"adx": None, "rsi": None, "atr": None}


def _filter_profile_name(filter_diag: dict[str, Any] | None, regime: str | None) -> str | None:
    if not filter_diag:
        return regime
    return str(filter_diag.get("profile") or filter_diag.get("regime") or regime or "")


def _from_paper_trade_row(row: dict[str, Any]) -> CompletedPaperTrade:
    """Map closed paper_trades journal row to CompletedPaperTrade."""
    return CompletedPaperTrade(
        timestamp=str(row["time_open"]),
        symbol=str(row["symbol"]),
        timeframe=str(row.get("timeframe") or "M5"),
        regime=str(row.get("regime") or "UNKNOWN"),
        engine=str(row.get("engine") or ""),
        direction=str(row["direction"]),
        probability=float(row["probability"]) if row.get("probability") is not None else None,
        confidence=float(row.get("confidence") or 0.0),
        sl=float(row["sl"]) if row.get("sl") is not None else None,
        tp=float(row["tp"]) if row.get("tp") is not None else None,
        lot=float(row.get("lot") or 0.01),
        rr=float(row["rr"]) if row.get("rr") is not None else None,
        spread=float(row.get("spread") or 0.30),
        adx=None,
        rsi=None,
        atr=None,
        feature_checksum=row.get("checksum"),
        model_checksum=row.get("model_checksum"),
        filter_profile=row.get("filter_profile"),
        decision_source="paper_trades_journal",
        exit_reason=str(row.get("exit_reason") or ""),
        pnl=float(row.get("pnl") or 0.0),
        pnl_r=float(row.get("pnl_r") or 0.0),
        duration_bars=int(row.get("duration_bars") or 0),
        mae=float(row.get("mae") or 0.0),
        mfe=float(row.get("mfe") or 0.0),
        entry_price=float(row.get("entry_price") or row.get("fill_price") or 0.0),
        exit_price=float(row["exit_price"]) if row.get("exit_price") is not None else None,
        exit_timestamp=str(row["time_close"]) if row.get("time_close") else None,
        extra={
            "fill_price": row.get("fill_price"),
            "ticket": row.get("ticket"),
            "magic": row.get("magic"),
            "commission": row.get("commission"),
            "swap": row.get("swap"),
            "risk_percent": row.get("risk_percent"),
            "duration_sec": row.get("duration_sec"),
            "fill_source": row.get("fill_source"),
        },
    )


def _from_journal_execution(
    row: dict[str, Any],
    *,
    candles: pd.DataFrame,
    decisions: dict[str, dict[str, Any]],
    base_dir: str | None,
) -> CompletedPaperTrade | None:
    direction = str(row.get("direction", "HOLD"))
    if direction not in ("BUY", "SELL"):
        return None

    ts = str(row["ts"])
    symbol = str(row.get("symbol") or "XAUUSD")
    timeframe = str(row.get("timeframe") or "M5")
    sl = row.get("sl")
    tp = row.get("tp")
    entry_price = float(row.get("fill_price") or row.get("requested_price") or 0)
    if entry_price <= 0 and sl is not None and tp is not None:
        entry_price = (float(sl) + float(tp)) / 2.0
    lot = float(row.get("lot") or 0.01)
    sl_f = float(sl) if sl is not None else None
    tp_f = float(tp) if tp is not None else None
    is_buy = direction == "BUY"

    exit_info = simulate_trade_exit(
        candles=candles,
        entry_ts=ts,
        entry_price=entry_price,
        sl=sl_f,
        tp=tp_f,
        is_buy=is_buy,
        lot=lot,
        symbol=symbol,
    )

    dkey = f"{symbol}:{timeframe}:{ts[:19]}"
    decision = decisions.get(dkey, {})
    indicators = _indicator_snapshot(base_dir=base_dir, symbol=symbol, timeframe=timeframe, timestamp=ts)

    return CompletedPaperTrade(
        timestamp=ts,
        symbol=symbol,
        timeframe=timeframe,
        regime=str(decision.get("regime") or "UNKNOWN"),
        engine=str(decision.get("engine") or ""),
        direction=direction,
        probability=float(decision.get("confidence") or 0.0) if decision else None,
        confidence=float(decision.get("confidence") or 0.0),
        sl=sl_f,
        tp=tp_f,
        lot=lot,
        rr=exit_info.get("rr"),
        spread=float(exit_info.get("spread") or 0.30),
        adx=indicators.get("adx"),
        rsi=indicators.get("rsi"),
        atr=indicators.get("atr"),
        feature_checksum=decision.get("checksum"),
        model_checksum=decision.get("trace_id") or decision.get("checksum"),
        filter_profile=_filter_profile_name(decision.get("filter_diagnostics"), decision.get("regime")),
        decision_source="live_journal",
        exit_reason=str(exit_info["exit_reason"]),
        pnl=float(exit_info["pnl"]),
        pnl_r=float(exit_info["pnl_r"]),
        duration_bars=int(exit_info["duration_bars"]),
        mae=float(exit_info["mae"]),
        mfe=float(exit_info["mfe"]),
        entry_price=entry_price,
        exit_price=float(exit_info["exit_price"]),
        exit_timestamp=str(exit_info["exit_timestamp"]),
    )


def _from_replay_signal(
    signal: dict[str, Any],
    *,
    candles: pd.DataFrame,
    base_dir: str | None,
) -> CompletedPaperTrade | None:
    direction = str(signal.get("decision", "HOLD"))
    if direction not in ("BUY", "SELL"):
        return None
    if not signal.get("execution_success"):
        return None

    ts = str(signal.get("timestamp"))
    symbol = str(signal.get("symbol") or "XAUUSD")
    timeframe = str(signal.get("timeframe") or "M5")
    sl = signal.get("sl")
    tp = signal.get("tp")
    sl_f = float(sl) if sl is not None else None
    tp_f = float(tp) if tp is not None else None
    lot = float(signal.get("volume") or 0.01)
    is_buy = direction == "BUY"

    entry_idx = candles.index.searchsorted(pd.to_datetime(ts, utc=True))
    entry_idx = min(max(entry_idx, 0), len(candles) - 1)
    entry_price = float(candles.iloc[entry_idx]["close"])

    exit_info = simulate_trade_exit(
        candles=candles,
        entry_ts=ts,
        entry_price=entry_price,
        sl=sl_f,
        tp=tp_f,
        is_buy=is_buy,
        lot=lot,
        symbol=symbol,
    )
    indicators = _indicator_snapshot(base_dir=base_dir, symbol=symbol, timeframe=timeframe, timestamp=ts)
    filt = signal.get("filter_diagnostics") or {}

    return CompletedPaperTrade(
        timestamp=ts,
        symbol=symbol,
        timeframe=timeframe,
        regime=str(signal.get("regime") or "UNKNOWN"),
        engine=str(signal.get("engine") or ""),
        direction=direction,
        probability=float(signal.get("confidence") or 0.0),
        confidence=float(signal.get("confidence") or 0.0),
        sl=sl_f,
        tp=tp_f,
        lot=lot,
        rr=exit_info.get("rr"),
        spread=float(exit_info.get("spread") or 0.30),
        adx=indicators.get("adx"),
        rsi=indicators.get("rsi"),
        atr=indicators.get("atr"),
        feature_checksum=signal.get("feature_vector_checksum"),
        model_checksum=signal.get("feature_vector_checksum"),
        filter_profile=_filter_profile_name(filt if isinstance(filt, dict) else None, signal.get("regime")),
        decision_source=str(signal.get("registry_source") or "unified_pipeline_replay"),
        exit_reason=str(exit_info["exit_reason"]),
        pnl=float(exit_info["pnl"]),
        pnl_r=float(exit_info["pnl_r"]),
        duration_bars=int(exit_info["duration_bars"]),
        mae=float(exit_info["mae"]),
        mfe=float(exit_info["mfe"]),
        entry_price=entry_price,
        exit_price=float(exit_info["exit_price"]),
        exit_timestamp=str(exit_info["exit_timestamp"]),
    )


def collect_completed_paper_trades(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    replay_days: int = 7,
    replay_stride: int = 5,
) -> tuple[list[CompletedPaperTrade], dict[str, Any]]:
    """
    Observation-only collector.

    1. Read live paper fills from trade_journal.db (read-only).
    2. Supplement with unified pipeline replay executed signals when journal is empty.
    """
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.research.phase25b.unified_pipeline_replay import run_unified_pipeline_replay
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
    from tradingbot.services.paper_trade_recorder import PaperTradeRecorder

    meta: dict[str, Any] = {
        "mode": "observation_only",
        "sources": [],
        "journal_executions": 0,
        "replay_signals": 0,
        "completed_trades": 0,
    }

    if base_dir:
        PaperTradeRecorder(base_dir).complete_open_trades()

    paper_trade_rows = read_completed_paper_trades(base_dir)
    meta["paper_trades_closed"] = len(paper_trade_rows)
    if paper_trade_rows:
        meta["sources"].append("paper_trades")
        trades = [_from_paper_trade_row(row) for row in paper_trade_rows]
        meta["valid_journal_trades"] = len(trades)
        meta["completed_trades"] = len(trades)
        return trades, meta

    candles_raw = CandleStore(base_dir).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        return [], {**meta, "error": "candles_unavailable"}

    candles = normalize_candles_for_builder(candles_raw)
    decisions = _load_decisions_index(base_dir)
    trades: list[CompletedPaperTrade] = []

    journal_rows = read_paper_executions(base_dir)
    meta["journal_executions"] = len(journal_rows)
    if journal_rows:
        meta["sources"].append("trade_journal.db")
        for row in journal_rows:
            trade = _from_journal_execution(row, candles=candles, decisions=decisions, base_dir=base_dir)
            if trade is not None:
                trades.append(trade)

    valid_journal = [
        t for t in trades
        if t.exit_reason not in ("no_data",) and (t.entry_price or 0) > 0 and t.duration_bars > 0
    ]
    meta["valid_journal_trades"] = len(valid_journal)

    if valid_journal:
        trades = valid_journal
    else:
        trades = []
        if journal_rows:
            meta["journal_skipped_reason"] = "incomplete_exit_simulation_or_zero_fill"
        meta["sources"] = [s for s in meta["sources"] if s != "unified_pipeline_replay"]
        if "unified_pipeline_replay" not in meta["sources"]:
            meta["sources"].append("unified_pipeline_replay")
        signals, replay_meta = run_unified_pipeline_replay(
            base_dir=base_dir,
            symbol=symbol,
            timeframe=timeframe,
            days=replay_days,
            tail_only=None,
            stride=replay_stride,
        )
        meta["replay_signals"] = len(signals)
        meta["replay_meta"] = replay_meta
        window = candles.tail(int(replay_days * 288) + 500)
        for sig in signals:
            trade = _from_replay_signal(sig, candles=window, base_dir=base_dir)
            if trade is not None:
                trades.append(trade)

    meta["completed_trades"] = len(trades)
    return trades, meta
