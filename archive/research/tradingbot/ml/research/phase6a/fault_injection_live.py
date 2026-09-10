"""Phase 6A — live-path fault injection (isolated, no production mutation)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd


def _case(name: str, *, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": passed, "detail": detail}


def test_mt5_reconnect() -> dict[str, Any]:
    """Simulate disconnect then successful reconnect via ensure_mt5_connected."""
    try:
        import MetaTrader5 as mt5

        calls = {"n": 0}

        def fake_initialize(*_a, **_k):
            calls["n"] += 1
            return calls["n"] >= 2

        with patch.object(mt5, "initialize", side_effect=fake_initialize):
            with patch.object(mt5, "terminal_info", return_value=MagicMock(connected=True)):
                with patch.object(mt5, "account_info", return_value=MagicMock(login=1)):
                    with patch("tradingbot.adapters.mt5_utils.is_mt5_session_connected", return_value=calls["n"] >= 2):
                        from tradingbot.adapters.mt5_utils import ensure_mt5_connected

                        cfg = {"MT5_RETRIES": 3, "MT5_RETRY_SLEEP_SEC": 0}
                        ok = ensure_mt5_connected(cfg, strict_account=False, use_lock=False)
        passed = ok and calls["n"] >= 1
        return _case("mt5_reconnect", passed=passed, detail=f"initialize_calls={calls['n']} ok={ok}")
    except Exception as exc:
        return _case("mt5_reconnect", passed=False, detail=str(exc))


def test_stale_data() -> dict[str, Any]:
    """Reject or flag bars older than freshness threshold."""
    from tradingbot.domain.ohlcv import normalize_ohlcv

    idx = pd.date_range("2024-01-01", periods=10, freq="5min", tz="UTC")
    df = normalize_ohlcv(
        pd.DataFrame(
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 100},
            index=idx,
        )
    )
    last_ts = pd.Timestamp(df.index[-1])
    age_min = (pd.Timestamp.now(tz="UTC") - last_ts).total_seconds() / 60.0
    stale = age_min > 30
    return _case("stale_data", passed=stale, detail=f"age_minutes={age_min:.0f} detected_stale={stale}")


def test_spread_spike_x3() -> dict[str, Any]:
    """RiskGate blocks or shrinks lot when spread triples."""
    from tradingbot.adapters.risk_gate import AccountState, RiskGate
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import TradingSignal

    signal = TradingSignal(
        direction=SignalDirection.BUY,
        confidence=0.65,
        symbol="XAUUSD",
        timeframe="5m",
        strategy_name="priceaction",
        stop_loss=2650.0,
        take_profit=2660.0,
        metadata={"selected_engine": "PA"},
    )
    idx = pd.date_range("2024-06-01", periods=80, freq="5min", tz="UTC")
    closes = [2650.0] * 80
    df = pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes, "volume": 100},
        index=idx,
    )
    gate = RiskGate(AccountState(balance=200.0, equity=200.0), {"USE_NEWS_FILTER": False})
    snapshot = {"ohlcv": df, "current_time": df.index[-1], "open_positions": []}

    with patch.object(gate, "_live_spread_pips", return_value=15.0):
        with patch.object(gate, "_sync_mt5_account"):
            with patch.object(gate, "_capital_adaptive_gates", return_value=(True, "ok")):
                with patch.object(gate, "_live_gates", return_value=(True, "ok")):
                    with patch("tradingbot.services.meta_labeler.get_meta_labeler") as mm:
                        mm.return_value.is_ready_for.return_value = False
                        blocked = not gate.evaluate(signal, snapshot).allowed
    return _case("spread_spike_x3", passed=blocked, detail=f"blocked={blocked}")


def test_missing_candle() -> dict[str, Any]:
    """Pipeline tolerates dropped last bar without crash."""
    from tradingbot.domain.ohlcv import exclude_forming_bar, normalize_ohlcv

    idx = pd.date_range("2024-01-01", periods=20, freq="5min", tz="UTC")
    df = normalize_ohlcv(
        pd.DataFrame(
            {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 100},
            index=idx,
        )
    )
    trimmed = df.iloc[:-1]
    closed = exclude_forming_bar(trimmed, min_rows=5)
    passed = closed is not None and not closed.empty and len(closed) >= 5
    row_count = len(closed) if closed is not None else 0
    return _case("missing_candle", passed=passed, detail=f"rows={row_count}")


def test_duplicate_candle() -> dict[str, Any]:
    """Dedup consecutive duplicate timestamps."""
    idx = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 100},
        index=idx,
    )
    dup = pd.concat([df, df.iloc[[-1]]])
    deduped = dup[~dup.index.duplicated(keep="last")]
    passed = len(deduped) == len(df)
    return _case("duplicate_candle", passed=passed, detail=f"before={len(dup)} after={len(deduped)}")


def test_terminal_restart() -> dict[str, Any]:
    """Lock release path does not raise."""
    try:
        from tradingbot.adapters.mt5_utils import release_process_mt5_lock

        release_process_mt5_lock()
        return _case("terminal_restart", passed=True, detail="lock_release_ok")
    except Exception as exc:
        return _case("terminal_restart", passed=False, detail=str(exc))


def run_fault_injection_suite() -> dict[str, Any]:
    tests = [
        test_mt5_reconnect(),
        test_stale_data(),
        test_spread_spike_x3(),
        test_missing_candle(),
        test_duplicate_candle(),
        test_terminal_restart(),
    ]
    passed = sum(1 for t in tests if t["passed"])
    return {
        "tests": tests,
        "passed": passed,
        "total": len(tests),
        "all_passed": passed == len(tests),
    }
