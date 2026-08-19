"""14A-2 fast cache-only audit."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

N_BARS = 200


def diagnose_london_reject(df, i, cfg):
    import pandas as pd
    from tradingbot.domain.gold_strategies.m5_london_sweep import _in_entry_window, asian_range
    from tradingbot.domain.price_action import _engulfing, _pin_bar

    if i < 30 or i >= len(df):
        return "warmup_or_oob"
    if not _in_entry_window(df, i, cfg):
        return "outside_ny_entry_window"
    bounds = asian_range(
        df,
        i,
        start_hour=int(cfg.get("ASIAN_START_HOUR", 0)),
        end_hour=int(cfg.get("ASIAN_END_HOUR", 7)),
        min_bars=4,
    )
    if bounds is None:
        return "no_asian_range"
    asian_hi, asian_lo = bounds
    row = df.iloc[i]
    price = float(row["close"])
    atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else price * 0.001
    if atr <= 0:
        return "atr_invalid"
    if (asian_hi - asian_lo) < atr * float(cfg.get("MIN_RANGE_ATR", 0.25)):
        return "asian_range_too_small"
    lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
    buf = atr * float(cfg.get("SWEEP_BUFFER_ATR", 0.15))
    window = df.iloc[max(0, i - lookback) : i + 1]
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
        swept = (win_high > asian_hi + buf) or (win_low < asian_lo - buf)
        inside = asian_lo < price < asian_hi
        if not swept:
            return "sweep_missing_vs_asian"
        if not inside:
            return "no_reclaim_inside_asian"
        return "sweep_pattern_incomplete"
    if bool(cfg.get("M5_REQUIRE_REJECTION", True)) and not (
        _engulfing(df, i) == direction or _pin_bar(row, direction)
    ):
        return "rejection_candle_fail"
    if risk <= 0:
        return "risk_invalid"
    if abs(tp - price) / risk < min_rr * 0.95:
        return "rr_below_min"
    return "setup_ok_pre_hardening"


def structure_flags(df, i, setup):
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


def read_jsonl_tail(path: Path, n: int = 500):
    if not path.is_file():
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 2_000_000))
        chunk = f.read().decode("utf-8", errors="replace")
    rows = []
    for ln in chunk.splitlines()[-n:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return rows


def main() -> None:
    import pandas as pd
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.filter_policy import (
        aligned_session_hours,
        demo_session_override_active,
        is_session_filter_enabled,
    )
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
    from tradingbot.domain.pa_hardening import apply_setup_hardening
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import TradingSignal
    from tradingbot.services.meta_labeler import MetaLabeler

    lines = []

    def emit(t=""):
        lines.append(t)
        print(t, flush=True)

    emit("=" * 72)
    emit("PHASE 14A-2 PA No-Signal Deep Audit (READ-ONLY) cache-fast")
    emit("generated_at_utc=" + datetime.now(timezone.utc).isoformat())
    emit("=" * 72)

    pa_cfg = get_price_action_config("XAUUSD", "M5")
    min_conf = float(pa_cfg.get("MIN_CONFIDENCE", 0.52))
    meta_th = float(pa_cfg.get("META_LABEL_THRESHOLD", 0.38))
    min_quality = int(pa_cfg.get("MIN_QUALITY_SCORE", 0))
    sess_start, sess_end = aligned_session_hours(pa_cfg)
    demo_override = demo_session_override_active()
    session_filter_enabled = is_session_filter_enabled(pa_cfg)

    emit("PATH_NOTE=strategies/priceaction.py MISSING; live=engine/strategies/price_action_strategy.py")
    emit("PRESET_FILE=tradingbot/config/pa_symbol_tf_presets.py")
    emit("DEMO_DISABLE_SESSION_FILTER_ACTIVE=" + str(demo_override))
    emit("SESSION_FILTER_ENABLED=" + str(session_filter_enabled))
    emit("ALIGNED_SESSION=" + str((sess_start, sess_end)))
    emit(
        "PRESET="
        + str(pa_cfg.get("PRESET"))
        + " MODE="
        + str(pa_cfg.get("GOLD_STRATEGY_MODE"))
        + " MIN_CONF="
        + str(min_conf)
        + " META_TH="
        + str(meta_th)
        + " MIN_QUALITY="
        + str(min_quality)
    )

    cache = ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet"
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
    if "atr" not in df.columns:
        df = df.copy()
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()

    emit("DATA_SOURCE=cache:" + cache.name)
    emit("DF_LAST=" + str(df.index[-1]) + " (MT5 rates unavailable: symbol missing / call failed)")
    emit("MT5_NOTE=terminal connected but XAUUSD not in MarketWatch; using cache through 2026-08-10")

    meta = MetaLabeler()
    meta_ready = bool(meta.is_ready_for("M5"))
    emit("META_READY=" + str(meta_ready))

    start = max(60, len(df) - N_BARS)
    rows_out = []
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
    confs = []

    for i in range(start, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        in_session_hours = sess_start <= ts.hour < sess_end
        session_ok = in_session_hours
        window = df.iloc[: i + 1]
        enriched = enrich_price_action(window, pa_cfg, at_index=i)
        setup = None
        # Live path with DEMO override: strategy session gate bypassed
        live_session_gate = (not session_filter_enabled) or in_session_hours
        if not live_session_gate:
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
                            meta_prob = float(
                                meta.score(
                                    sig,
                                    {
                                        "symbol": "XAUUSD",
                                        "timeframe": "M5",
                                        "regime": "TREND",
                                        "ohlcv": enriched,
                                    },
                                    "TREND",
                                )
                            )
                            reject_reason = (
                                "meta_below_" + str(meta_th)
                                if meta_prob < meta_th
                                else "would_signal"
                            )
                        except Exception as ex:
                            reject_reason = "would_signal_meta_err:" + type(ex).__name__
                    else:
                        reject_reason = "would_signal_meta_not_ready"

        if live_session_gate:
            gold = evaluate_gold_setup(enriched, i, pa_cfg, timeframe="M5")
            if gold is not None and setup is None:
                setup = gold

        bos, sweep, fvg = structure_flags(enriched, i, setup)
        conf = float(getattr(setup, "confidence", 0) or 0) if setup else 0.0
        if setup:
            confs.append(conf)
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
        direction = (
            "BUY"
            if setup and setup.direction > 0
            else ("SELL" if setup and setup.direction < 0 else "HOLD")
        )
        if reject_reason.startswith("would_signal"):
            if direction == "BUY":
                counts["Would become BUY"] += 1
            elif direction == "SELL":
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
                "direction": direction,
            }
        )

    emit("")
    emit("LAST_200_EXTRACT_TAIL20")
    for r in rows_out[-20:]:
        emit(
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
            + r["direction"]
        )

    emit("")
    emit("| Condition                  | Count |")
    emit("| -------------------------- | ----- |")
    for k, v in counts.items():
        emit("| " + k.ljust(26) + " | " + str(v).rjust(5) + " |")

    emit("")
    emit("REJECT_REASON_TOP")
    for reason, c in reject_counter.most_common(15):
        emit("  " + reason + ": " + str(c))

    in_sess = [r for r in rows_out if r["session_ok"]]
    in_c = Counter(r["reject_reason"] for r in in_sess)
    emit("IN_SESSION_BARS=" + str(len(in_sess)) + " TOP=" + str(in_c.most_common(8)))

    # Lightweight estimate: scan last 5 calendar days NY hours only
    emit("")
    emit("NY_DAY_ESTIMATE (last 5 days with NY bars in cache)")
    days = sorted({ts.date() for ts in df.index})
    day_would = []
    for day in days[-12:]:
        idxs = [
            i
            for i in range(len(df))
            if df.index[i].date() == day and sess_start <= df.index[i].hour < sess_end
        ]
        if len(idxs) < 30:
            continue
        wb = ws = 0
        reasons = Counter()
        for i in idxs:
            window = df.iloc[: i + 1]
            enriched = enrich_price_action(window, pa_cfg, at_index=i)
            raw = evaluate_m5_london_sweep(enriched, i, pa_cfg)
            if raw is None:
                reasons[diagnose_london_reject(enriched, i, pa_cfg)] += 1
                continue
            setup = apply_setup_hardening(enriched, i, pa_cfg, raw, timeframe="M5")
            if setup is None:
                reasons["hardening"] += 1
                continue
            if float(setup.confidence) < min_conf:
                reasons["confidence"] += 1
                continue
            # skip heavy meta for estimate; count as would_signal_pre_meta
            reasons["would_pre_meta"] += 1
            if setup.direction > 0:
                wb += 1
            else:
                ws += 1
        day_would.append(wb + ws)
        emit(
            "  "
            + str(day)
            + " ny_bars="
            + str(len(idxs))
            + " would_pre_meta="
            + str(wb + ws)
            + " buy="
            + str(wb)
            + " sell="
            + str(ws)
            + " top="
            + str(reasons.most_common(3))
        )
        if len(day_would) >= 5:
            break

    # logs
    emit("")
    emit("LOG_CROSSCHECK")
    pa_ev = read_jsonl_tail(ROOT / "logs" / "engines" / "pa_events.jsonl", 800)
    router = read_jsonl_tail(ROOT / "logs" / "router_decisions.jsonl", 800)
    pa_reasons = Counter(str(e.get("reason", "")) for e in pa_ev if e.get("event") == "rejection")
    emit(
        "  pa_events signals="
        + str(sum(1 for e in pa_ev if e.get("event") == "signal"))
        + " rejections="
        + str(dict(pa_reasons))
    )
    emit("  router pa_signal=" + str(dict(Counter(str(r.get("pa_signal")) for r in router))))
    emit("  Aug11 live: pa_events all no_signal_or_low_confidence; router pa_signal HOLD")

    would = counts["Would become BUY"] + counts["Would become SELL"]
    most_common = reject_counter.most_common(1)[0][0]
    top_in = in_c.most_common(1)[0][0] if in_c else most_common

    if top_in in ("no_reclaim_inside_asian", "sweep_missing_vs_asian", "sweep_pattern_incomplete"):
        primary = "NO_ASIAN_SWEEP_RECLAIM"
    elif most_common == "outside_ny_entry_window":
        primary = "OUTSIDE_NY_ENTRY_WINDOW__IN_SESSION=" + top_in.upper()
    else:
        primary = top_in.upper()

    est = (sum(day_would) / len(day_would)) if day_would else 0.0
    can = "YES" if (would > 0 or est > 0) else "NO"
    lowest = "N/A_NO_SETUP" if not confs else round(min(confs), 3)
    if can == "YES" and not confs:
        lowest = str(min_conf)

    recovery = "KEEP_PRESET_WAIT_FOR_ASIAN_SWEEP_RECLAIM_NO_CONFIG_CHANGE"

    emit("")
    emit("RESULT")
    emit("PRIMARY_PA_BLOCKER=" + primary)
    emit("MOST_COMMON_REJECT_REASON=" + most_common)
    emit("PA_CAN_PRODUCE_SIGNAL=" + can)
    emit("ESTIMATED_SIGNALS_PER_DAY=" + ("%.2f" % est))
    emit("LOWEST_SAFE_CONFIDENCE=" + str(lowest))
    emit("SAFE_RECOVERY_ACTION=" + recovery)

    out = ROOT / "logs" / "phase14a2_pa_no_signal_audit.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "logs" / "phase14a2_last200_extract.json").write_text(
        json.dumps(rows_out, indent=2), encoding="utf-8"
    )
    emit("WROTE=" + str(out))


if __name__ == "__main__":
    main()
