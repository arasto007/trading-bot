#!/usr/bin/env python3
"""PHASE 14A-2 PA No-Signal Deep Audit (READ-ONLY). No config changes."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "logs" / "phase14a2_pa_no_signal_audit.txt"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

N_BARS = 200
WARMUP = 400


def emit(lines: list[str], text: str = "") -> None:
    lines.append(text)
    print(text)


def read_jsonl_tail(path: Path, n: int = 500) -> list[dict]:
    if not path.is_file():
        return []
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = min(size, 2_000_000)
            f.seek(size - block)
            chunk = f.read().decode("utf-8", errors="replace")
        raw_lines = chunk.splitlines()[-n:]
    except Exception:
        raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]
    rows = []
    for ln in raw_lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return rows


def load_m5_df():
    import pandas as pd

    mt5_err = "not_tried"
    try:
        import MetaTrader5 as mt5
        from tradingbot.adapters.legacy_loader import load_legacy_config
        from tradingbot.adapters.mt5_utils import attach_mt5_session
        from tradingbot.adapters.symbols import resolve_broker_symbol
        from tradingbot.services.runtime_truth import mt5_rates_to_ohlcv_dataframe

        cfg = load_legacy_config()
        sym = resolve_broker_symbol("XAUUSD", cfg)
        attach_mt5_session(cfg, strict_account=False, use_lock=False)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M5, 0, WARMUP + N_BARS + 50)
        if rates is not None and len(rates) > N_BARS + 60:
            df = mt5_rates_to_ohlcv_dataframe(rates, timeframe_minutes=5)
            return df, "mt5", str(df.index[-1])
        mt5_err = "empty_rates"
    except Exception as e:
        mt5_err = str(e)

    cache = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
    if not cache.is_file():
        cache = ROOT / "data" / "cache" / "XAUUSD_M5_90d.parquet"
    df = pd.read_parquet(cache)
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("time", "timestamp", "datetime"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True)
                df = df.set_index(col)
                break
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    return df, "cache:" + cache.name, str(df.index[-1]) + " | mt5_err=" + mt5_err


def diagnose_london_reject(df, i: int, cfg: dict[str, Any]) -> str:
    import pandas as pd
    from tradingbot.domain.gold_strategies.m5_london_sweep import (
        _in_entry_window,
        asian_range,
    )
    from tradingbot.domain.price_action import _engulfing, _pin_bar

    if i < 30 or i >= len(df):
        return "warmup_or_oob"
    if not _in_entry_window(df, i, cfg):
        return "outside_ny_entry_window"
    asian_start = int(cfg.get("ASIAN_START_HOUR", 0))
    asian_end = int(cfg.get("ASIAN_END_HOUR", 7))
    bounds = asian_range(df, i, start_hour=asian_start, end_hour=asian_end, min_bars=4)
    if bounds is None:
        return "no_asian_range"
    asian_hi, asian_lo = bounds
    row = df.iloc[i]
    price = float(row["close"])
    atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else price * 0.001
    if atr <= 0:
        return "atr_invalid"
    min_range = atr * float(cfg.get("MIN_RANGE_ATR", 0.25))
    if (asian_hi - asian_lo) < min_range:
        return "asian_range_too_small"
    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf = atr * float(cfg.get("SWEEP_BUFFER_ATR", 0.15))
    start_j = max(0, i - lookback)
    window = df.iloc[start_j : i + 1]
    win_high = float(window["high"].max())
    win_low = float(window["low"].min())
    min_rr = float(cfg.get("MIN_RR", 1.8))
    sl_pad = atr * float(cfg.get("SL_ATR_MULT", 0.35))

    direction = None
    risk = 0.0
    tp = 0.0
    if win_high > asian_hi + buf and asian_lo < price < asian_hi and float(row["close"]) < asian_hi:
        direction = -1
        sl = win_high + sl_pad
        risk = sl - price
        tp = price - max(price - asian_lo, risk * min_rr)
    elif win_low < asian_lo - buf and asian_lo < price < asian_hi and float(row["close"]) > asian_lo:
        direction = 1
        sl = win_low - sl_pad
        risk = price - sl
        tp = price + max(asian_hi - price, risk * min_rr)
    else:
        swept_hi = win_high > asian_hi + buf
        swept_lo = win_low < asian_lo - buf
        inside = asian_lo < price < asian_hi
        if not (swept_hi or swept_lo):
            return "sweep_missing_vs_asian"
        if not inside:
            return "no_reclaim_inside_asian"
        return "sweep_pattern_incomplete"

    require_reject = bool(cfg.get("M5_REQUIRE_REJECTION", True))
    if require_reject and not (_engulfing(df, i) == direction or _pin_bar(row, direction)):
        return "rejection_candle_fail"
    if risk <= 0:
        return "risk_invalid"
    rr = abs(tp - price) / risk
    if rr < min_rr * 0.95:
        return "rr_below_min"
    return "setup_ok_pre_hardening"


def structure_flags(df, i: int, setup):
    from tradingbot.domain.pa_hardening import (
        confirm_fvg_fill,
        detect_bos_continuation,
        detect_liquidity_sweep_flag,
    )

    if setup is not None:
        return (
            bool(setup.metadata.get("bos_confirmed", False)),
            bool(setup.metadata.get("liquidity_sweep", False)),
            bool(setup.metadata.get("fvg_confirmed", False)),
        )
    breaks = df.attrs.get("pa_breaks", []) or []
    swings = df.attrs.get("pa_swings", []) or []
    fvgs = df.attrs.get("pa_fvgs", []) or []
    price = float(df["close"].iloc[i])
    bos = detect_bos_continuation(breaks, i, 1) or detect_bos_continuation(breaks, i, -1)
    sweep = detect_liquidity_sweep_flag(df, swings, i)
    fvg = confirm_fvg_fill(fvgs, price=price, direction=1, i=i) or confirm_fvg_fill(
        fvgs, price=price, direction=-1, i=i
    )
    return bos, sweep, fvg


def main() -> int:
    lines: list[str] = []
    emit(lines, "=" * 72)
    emit(lines, "PHASE 14A-2 PA No-Signal Deep Audit (READ-ONLY)")
    emit(lines, "generated_at_utc=" + datetime.now(timezone.utc).isoformat())
    emit(lines, "=" * 72)

    paths = {
        "strategies/priceaction.py": ROOT / "tradingbot" / "strategies" / "priceaction.py",
        "strategies/pa_symbol_tf_presets.py": ROOT
        / "tradingbot"
        / "strategies"
        / "pa_symbol_tf_presets.py",
        "config/pa_symbol_tf_presets.py": ROOT / "tradingbot" / "config" / "pa_symbol_tf_presets.py",
        "engine/strategies/price_action_strategy.py": ROOT
        / "engine"
        / "strategies"
        / "price_action_strategy.py",
        "domain/gold_strategies/m5_london_sweep.py": ROOT
        / "tradingbot"
        / "domain"
        / "gold_strategies"
        / "m5_london_sweep.py",
        "logs/router_decisions.jsonl": ROOT / "logs" / "router_decisions.jsonl",
        "logs/rejection_events.jsonl": ROOT / "logs" / "rejection_events.jsonl",
        "logs/engines/pa_events.jsonl": ROOT / "logs" / "engines" / "pa_events.jsonl",
    }
    emit(lines, "")
    emit(lines, "FILE_PRESENCE")
    for k, p in paths.items():
        emit(lines, "  " + k + ": " + ("YES" if p.is_file() else "NO"))

    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.filter_policy import aligned_session_hours, is_session_filter_enabled
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
    from tradingbot.domain.pa_hardening import apply_setup_hardening
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.services.meta_labeler import MetaLabeler

    pa_cfg = get_price_action_config("XAUUSD", "M5")
    min_conf = float(pa_cfg.get("MIN_CONFIDENCE", 0.52))
    meta_th = float(pa_cfg.get("META_LABEL_THRESHOLD", 0.38))
    min_quality = int(pa_cfg.get("MIN_QUALITY_SCORE", 0))
    sess_start, sess_end = aligned_session_hours(pa_cfg)
    session_filter = is_session_filter_enabled(pa_cfg)

    emit(lines, "")
    emit(lines, "PA_PRESET_SNAPSHOT")
    for k in (
        "PRESET",
        "GOLD_STRATEGY_MODE",
        "MIN_CONFIDENCE",
        "META_LABEL_THRESHOLD",
        "MIN_QUALITY_SCORE",
        "SESSION_START_HOUR",
        "SESSION_END_HOUR",
        "M5_USE_NY_SESSION",
        "NY_ENTRY_START_HOUR",
        "NY_ENTRY_END_HOUR",
        "M5_USE_LONDON_SESSION",
        "MIN_RR",
        "COOLDOWN_BARS",
    ):
        emit(lines, "  " + k + "=" + str(pa_cfg.get(k)))

    df, source, note = load_m5_df()
    emit(lines, "")
    emit(lines, "DATA_SOURCE=" + source)
    emit(lines, "DATA_NOTE=" + note)
    emit(lines, "DF_LEN=" + str(len(df)) + " FIRST=" + str(df.index[0]) + " LAST=" + str(df.index[-1]))

    if "atr" not in df.columns:
        df = df.copy()
        tr = (df["high"] - df["low"]).abs()
        df["atr"] = tr.rolling(14, min_periods=1).mean()

    meta = MetaLabeler()
    meta_ready = bool(meta.is_ready_for("M5"))

    start = max(60, len(df) - N_BARS)
    rows_out: list[dict[str, Any]] = []
    reject_counter: Counter[str] = Counter()

    counts = {
        "BOS missing": 0,
        "Sweep missing": 0,
        "FVG missing": 0,
        "Session blocked": 0,
        "Confidence below threshold": 0,
        "Meta would reject": 0,
        "Would become BUY": 0,
        "Would become SELL": 0,
    }
    confs_with_setup: list[float] = []

    for i in range(start, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        session_ok = True
        if session_filter and not (sess_start <= ts.hour < sess_end):
            session_ok = False

        window = df.iloc[: i + 1]
        enriched = enrich_price_action(window, pa_cfg, at_index=i)

        reject_reason = "ok"
        setup = None

        if not session_ok:
            reject_reason = "session_blocked"
        else:
            raw = evaluate_m5_london_sweep(enriched, i, pa_cfg)
            if raw is None:
                reject_reason = diagnose_london_reject(enriched, i, pa_cfg)
            else:
                setup = apply_setup_hardening(enriched, i, pa_cfg, raw, timeframe="M5")
                if setup is None:
                    reject_reason = "hardening_min_quality<" + str(min_quality)
                elif float(setup.confidence) < min_conf:
                    reject_reason = "confidence_below_" + str(min_conf)
                else:
                    if meta_ready:
                        try:
                            from tradingbot.domain.enums import SignalDirection
                            from tradingbot.domain.models import TradingSignal

                            direction = (
                                SignalDirection.BUY if setup.direction > 0 else SignalDirection.SELL
                            )
                            sig = TradingSignal(
                                direction=direction,
                                confidence=float(setup.confidence),
                                symbol="XAUUSD",
                                timeframe="M5",
                                strategy_name="priceaction",
                                stop_loss=float(setup.stop_loss),
                                take_profit=float(setup.take_profit),
                                metadata=dict(setup.metadata or {}),
                                created_at=ts,
                            )
                            snap = {
                                "symbol": "XAUUSD",
                                "timeframe": "M5",
                                "regime": "TREND",
                                "ohlcv": enriched,
                            }
                            meta_prob = float(meta.score(sig, snap, "TREND"))
                            if meta_prob < meta_th:
                                reject_reason = "meta_below_" + str(meta_th)
                            else:
                                reject_reason = "would_signal"
                        except Exception as ex:
                            reject_reason = "would_signal_meta_err:" + type(ex).__name__
                    else:
                        reject_reason = "would_signal_meta_not_ready"

        if session_ok:
            gold = evaluate_gold_setup(enriched, i, pa_cfg, timeframe="M5")
            if gold is not None and setup is None:
                setup = gold

        bos, sweep, fvg = structure_flags(enriched, i, setup)
        conf = float(getattr(setup, "confidence", 0) or 0) if setup else 0.0
        if setup:
            confs_with_setup.append(conf)

        if not bos:
            counts["BOS missing"] += 1
        if not sweep:
            counts["Sweep missing"] += 1
        if not fvg:
            counts["FVG missing"] += 1
        if not session_ok:
            counts["Session blocked"] += 1
        if setup is not None and conf < min_conf:
            counts["Confidence below threshold"] += 1
        if reject_reason.startswith("meta_below"):
            counts["Meta would reject"] += 1
        if reject_reason.startswith("would_signal"):
            if setup and setup.direction > 0:
                counts["Would become BUY"] += 1
            elif setup and setup.direction < 0:
                counts["Would become SELL"] += 1

        reject_counter[reject_reason] += 1
        rows_out.append(
            {
                "bar_time": ts.isoformat(),
                "bos_detected": bos,
                "sweep_detected": sweep,
                "fvg_detected": fvg,
                "session_ok": session_ok,
                "confidence_score": round(conf, 4),
                "reject_reason": reject_reason,
                "direction": (
                    "BUY"
                    if setup and setup.direction > 0
                    else ("SELL" if setup and setup.direction < 0 else "HOLD")
                ),
                "quality": int((setup.metadata or {}).get("quality_score", 0)) if setup else 0,
            }
        )

    emit(lines, "")
    emit(lines, "LAST_" + str(N_BARS) + "_M5_BAR_EXTRACT (tail 15 shown)")
    for r in rows_out[-15:]:
        emit(
            lines,
            "  BAR="
            + r["bar_time"]
            + " bos="
            + str(r["bos_detected"])
            + " sweep="
            + str(r["sweep_detected"])
            + " fvg="
            + str(r["fvg_detected"])
            + " session_ok="
            + str(r["session_ok"])
            + " conf="
            + ("%.3f" % r["confidence_score"])
            + " reject="
            + r["reject_reason"]
            + " dir="
            + r["direction"],
        )
    if len(rows_out) > 15:
        emit(lines, "  ... (" + str(len(rows_out) - 15) + " earlier bars in full extract)")

    emit(lines, "")
    emit(lines, "CONDITION_COUNTS")
    emit(lines, "| Condition                  | Count |")
    emit(lines, "| -------------------------- | ----- |")
    for k, v in counts.items():
        emit(lines, "| " + k.ljust(26) + " | " + str(v).rjust(5) + " |")

    emit(lines, "")
    emit(lines, "REJECT_REASON_TOP")
    for reason, c in reject_counter.most_common(20):
        emit(lines, "  " + reason + ": " + str(c))

    emit(lines, "")
    emit(lines, "LOG_CROSSCHECK (recent tails)")
    pa_ev = read_jsonl_tail(ROOT / "logs" / "engines" / "pa_events.jsonl", 400)
    router = read_jsonl_tail(ROOT / "logs" / "router_decisions.jsonl", 400)
    rej = read_jsonl_tail(ROOT / "logs" / "rejection_events.jsonl", 400)
    pa_reasons = Counter(str(e.get("reason", "")) for e in pa_ev if e.get("event") == "rejection")
    pa_signals = sum(1 for e in pa_ev if e.get("event") == "signal")
    router_pa = Counter(str(r.get("pa_signal", "")) for r in router)
    router_rej = Counter(str(r.get("rejection_reason", "")) for r in router)
    emit(
        lines,
        "  pa_events_tail="
        + str(len(pa_ev))
        + " signals="
        + str(pa_signals)
        + " rejection_reasons="
        + str(dict(pa_reasons)),
    )
    emit(
        lines,
        "  router_tail="
        + str(len(router))
        + " pa_signal="
        + str(dict(router_pa))
        + " rejection="
        + str(dict(router_rej.most_common(8))),
    )
    emit(lines, "  rejection_events_tail=" + str(len(rej)))

    would = counts["Would become BUY"] + counts["Would become SELL"]
    most_common_reject = reject_counter.most_common(1)[0][0]
    can_produce = "YES" if would > 0 else "NO"
    session_bars = sum(1 for r in rows_out if r["session_ok"])
    est = would * (84.0 / max(session_bars, 1)) if session_bars else 0.0

    if confs_with_setup:
        passed = [
            r["confidence_score"]
            for r in rows_out
            if r["reject_reason"].startswith("would_signal")
        ]
        if passed:
            lowest_safe = round(min(passed), 3)
        elif max(confs_with_setup) < min_conf:
            lowest_safe = round(max(0.40, max(confs_with_setup) - 0.01), 3)
        else:
            lowest_safe = min_conf
    else:
        lowest_safe = "N/A_NO_SETUP"

    in_sess_rows = [r for r in rows_out if r["session_ok"]]
    if in_sess_rows:
        in_c = Counter(r["reject_reason"] for r in in_sess_rows)
        top_in = in_c.most_common(1)[0][0]
        if top_in.startswith("sweep") or top_in in (
            "no_reclaim_inside_asian",
            "sweep_pattern_incomplete",
        ):
            primary_final = "SWEEP_MISSING_VS_ASIAN_RANGE"
        elif top_in.startswith("hardening"):
            primary_final = "MIN_QUALITY_HARDENING"
        elif top_in.startswith("confidence"):
            primary_final = "CONFIDENCE_BELOW_THRESHOLD"
        elif top_in.startswith("meta"):
            primary_final = "META_LABEL_REJECT"
        elif most_common_reject == "session_blocked" and session_bars < N_BARS * 0.35:
            primary_final = "SESSION_BLOCKED_OUTSIDE_10_17; IN_SESSION_TOP=" + top_in.upper()
        else:
            primary_final = top_in.upper()
    else:
        primary_final = "SESSION_BLOCKED_OUTSIDE_10_17"

    in_top = (
        Counter(r["reject_reason"] for r in in_sess_rows).most_common(1)[0][0]
        if in_sess_rows
        else ""
    )
    if would > 0:
        recovery = "NO_CONFIG_CHANGE_NEEDED_WAIT_FOR_PATTERN_RECURRENCE"
    elif in_top.startswith("sweep") or in_top in (
        "no_reclaim_inside_asian",
        "sweep_pattern_incomplete",
    ):
        recovery = "KEEP_PRESET_WAIT_FOR_ASIAN_SWEEP_RECLAIM_NO_CONFIG_CHANGE"
    elif most_common_reject.startswith("hardening") or in_top.startswith("hardening"):
        recovery = "RESEARCH_ONLY_MIN_QUALITY_REVIEW_NO_LIVE_CHANGE"
    elif most_common_reject.startswith("confidence") or in_top.startswith("confidence"):
        recovery = "RESEARCH_ONLY_CONFIDENCE_FLOOR_REVIEW_NO_LIVE_CHANGE"
    elif most_common_reject.startswith("meta") or in_top.startswith("meta"):
        recovery = "RESEARCH_ONLY_META_THRESHOLD_REVIEW_NO_LIVE_CHANGE"
    else:
        recovery = "KEEP_PA_PRODUCTION_LOCK_NO_CONFIG_CHANGE"

    emit(lines, "")
    emit(lines, "RESULT")
    emit(lines, "PRIMARY_PA_BLOCKER=" + primary_final)
    emit(lines, "MOST_COMMON_REJECT_REASON=" + most_common_reject)
    emit(lines, "PA_CAN_PRODUCE_SIGNAL=" + can_produce)
    emit(lines, "ESTIMATED_SIGNALS_PER_DAY=" + ("%.2f" % est))
    emit(lines, "LOWEST_SAFE_CONFIDENCE=" + str(lowest_safe))
    emit(lines, "SAFE_RECOVERY_ACTION=" + recovery)
    emit(
        lines,
        "META_READY="
        + str(meta_ready)
        + " MIN_CONF="
        + str(min_conf)
        + " META_TH="
        + str(meta_th),
    )
    emit(
        lines,
        "RAW_SETUPS_HARDENED="
        + str(len(confs_with_setup))
        + " WOULD="
        + str(would)
        + " SESSION_BARS="
        + str(session_bars),
    )

    extract_path = ROOT / "logs" / "phase14a2_last200_extract.json"
    extract_path.write_text(json.dumps(rows_out, indent=2), encoding="utf-8")
    emit(lines, "EXTRACT_JSON=" + str(extract_path))

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("")
    print("Wrote " + str(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
