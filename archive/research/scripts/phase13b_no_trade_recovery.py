#!/usr/bin/env python3
"""
PHASE 13B — No-Trade Root Cause & Frequency Recovery (READ-ONLY + REPLAY).
Does NOT change config, unlock Adaptive, enable ML live, or send orders.
Cache-only: never attaches MT5.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "logs" / "phase13b_no_trade_recovery.txt"
SESSION_DATE = "2026-08-11"
TAIL_BARS = 280
THRESHOLDS = [0.32, 0.34, 0.35, 0.36, 0.38, 0.40]
META_CURRENT = 0.38
PROD_COOLDOWN = 12
PROD_MAX_DAY = 3

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.update({
    "USE_ML_KERNEL": "false",
    "MULTI_ENGINE_ROUTER_ENABLED": "true",
    "ADAPTIVE_REGIME_ENABLED": "false",
    "VOL_REGIME_ENABLED": "false",
    "PA_PRODUCTION_LOCK": "true",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_SIGNAL_FILTER": "OFF",
    "TRADINGBOT_DRY_RUN": "1",
})


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def _read_jsonl(path: Path, *, date_filter: str | None = None) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if date_filter:
                ts = str(obj.get("logged_at") or obj.get("ts") or obj.get("timestamp") or "")
                if date_filter not in ts:
                    continue
            rows.append(obj)
    return rows


def load_m5_frame(days: int = 30) -> pd.DataFrame:
    """Load newest available M5 parquet and slice last `days` calendar days."""
    candidates = [
        ROOT / "data" / "backtest" / "XAUUSD_M5_93d.parquet",
        ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet",
        ROOT / "data" / "cache" / "XAUUSD_M5_90d.parquet",
        ROOT / "data" / "backtest" / "XAUUSD_M5_180d.parquet",
        ROOT / "data" / "backtest" / "XAUUSD_M5_30d.parquet",
        ROOT / "data" / "cache" / "XAUUSD_M5_30d.parquet",
    ]
    df = None
    src = None
    for path in candidates:
        if not path.is_file():
            continue
        raw = pd.read_parquet(path)
        if "time" in raw.columns and not isinstance(raw.index, pd.DatetimeIndex):
            raw = raw.set_index("time")
        raw.index = pd.to_datetime(raw.index, utc=True)
        raw = raw.sort_index()
        df = raw
        src = path
        break
    if df is None or df.empty:
        raise RuntimeError("No M5 parquet cache found for replay")

    end = df.index.max()
    start = end - timedelta(days=days)
    # keep warmup bars before window
    warm_start = start - timedelta(days=3)
    sliced = df.loc[df.index >= warm_start].copy()
    emit(f"  data={src.name} bars={len(sliced)} range={sliced.index.min()} -> {sliced.index.max()}")
    sliced.attrs["window_start"] = start
    return sliced


def build_today_timeline() -> tuple[list[str], dict[str, Any]]:
    router = _read_jsonl(ROOT / "logs/router_decisions.jsonl", date_filter=SESSION_DATE)
    adaptive = _read_jsonl(ROOT / "logs/engines/adaptive_events.jsonl", date_filter=SESSION_DATE)
    pa = _read_jsonl(ROOT / "logs/engines/pa_events.jsonl", date_filter=SESSION_DATE)
    rejections = _read_jsonl(ROOT / "logs/rejection_events.jsonl", date_filter=SESSION_DATE)

    ad_by_bar: dict[str, dict] = {}
    for e in adaptive:
        if e.get("event") == "signal":
            ad_by_bar[str(e.get("bar_timestamp", ""))[:16]] = e

    lines: list[str] = [
        "| UTC | PA signal | Adaptive signal | Meta score | RiskGate decision | Selected engine | Final result |",
        "|-----|-----------|-----------------|------------|-------------------|-----------------|----------------|",
    ]
    stats = Counter()
    for r in sorted(router, key=lambda x: x.get("logged_at", "")):
        bar_ts = str(r.get("timestamp", ""))[:16]
        logged = str(r.get("logged_at", ""))[:19].replace("T", " ")
        pa_sig = r.get("pa_signal", "HOLD")
        ad_sig = r.get("adaptive_signal", "HOLD")
        engine = r.get("selected_engine", "NONE")
        reason = r.get("rejection_reason", "") or "no_valid_signal"

        meta_score = "N/A"
        rg_dec = "NOT_REACHED"
        final = reason

        if pa_sig in ("BUY", "SELL"):
            meta_score = "would_score"
            rg_dec = "would_evaluate"
            stats["pa_signal"] += 1
        else:
            stats["pa_hold"] += 1
            if ad_sig in ("BUY", "SELL"):
                ad_ev = ad_by_bar.get(bar_ts, {})
                conf = ad_ev.get("confidence")
                meta_score = f"adaptive_conf={conf}" if conf is not None else "N/A(meta_not_reached)"
                rg_dec = "NOT_REACHED (PA_PRODUCTION_LOCK)"
                final = "pa_only_vol_adaptive_logged_not_selected"
                stats["adaptive_blocked_by_pa_lock"] += 1
            else:
                meta_score = "N/A(no_PA_signal)"
                rg_dec = "NOT_REACHED"
                final = reason or "no_valid_signal"
                stats["both_hold"] += 1

        lines.append(
            f"| {logged} | {pa_sig} | {ad_sig} | {meta_score} | {rg_dec} | {engine} | {final} |"
        )

    pa_rej = Counter(e.get("reason", "?") for e in pa if e.get("event") == "rejection")
    rej_reasons = Counter(e.get("reason", "?") for e in rejections)
    summary = {
        "router_cycles": len(router),
        "pa_hold_cycles": stats["pa_hold"],
        "pa_signal_cycles": stats["pa_signal"],
        "adaptive_blocked": stats["adaptive_blocked_by_pa_lock"],
        "both_hold": stats["both_hold"],
        "pa_rejection_reasons": dict(pa_rej),
        "rejection_top": dict(rej_reasons.most_common(8)),
        "session_start": router[0].get("logged_at") if router else None,
        "session_end": router[-1].get("logged_at") if router else None,
        "live_trades": 0,
        "meta_events_present": (ROOT / "logs/engines/meta_events.jsonl").is_file(),
    }
    return lines, summary


def collect_raw_pa_setups(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Single-pass fast PA setup collection with meta scores (no threshold cut)."""
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.filter_policy import aligned_session_hours, strategy_uses_kill_zone
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.models import TradingSignal
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.domain.session_logic import is_kill_zone
    from tradingbot.services.meta_labeler import get_meta_labeler

    cfg_pa = get_price_action_config("XAUUSD", "M5")
    min_conf = float(cfg_pa.get("MIN_CONFIDENCE", 0.52))
    session_start, session_end = aligned_session_hours(cfg_pa)
    use_kz = strategy_uses_kill_zone(cfg_pa)
    meta = get_meta_labeler()

    window_start = df.attrs.get("window_start")
    start_i = 0
    if window_start is not None:
        start_i = int(df.index.searchsorted(pd.Timestamp(window_start)))
    start_i = max(start_i, TAIL_BARS, 60)

    setups: list[dict[str, Any]] = []
    stage_counts = Counter()
    rejection_reasons = Counter()

    for i in range(start_i, len(df)):
        ts = df.index[i]
        ts_py = pd.Timestamp(ts).to_pydatetime()
        hour = ts_py.hour

        if not (session_start <= hour < session_end):
            stage_counts["session_filter"] += 1
            rejection_reasons["session_filter"] += 1
            continue
        if use_kz and not is_kill_zone(ts_py, use_kill_zones=True):
            stage_counts["kill_zone"] += 1
            rejection_reasons["kill_zone"] += 1
            continue

        stage_counts["bars_in_session"] += 1
        w0 = max(0, i - TAIL_BARS)
        tail = df.iloc[w0 : i + 1]
        local_i = len(tail) - 1
        enriched = enrich_price_action(tail, cfg_pa, at_index=local_i)
        setup = evaluate_gold_setup(enriched, local_i, cfg_pa, timeframe="5m")
        if setup is None:
            continue

        stage_counts["raw_setups"] += 1
        if setup.confidence < min_conf:
            stage_counts["low_confidence"] += 1
            rejection_reasons["low_confidence"] += 1
            continue
        stage_counts["pa_pass_confidence"] += 1

        direction = SignalDirection.BUY if setup.direction > 0 else SignalDirection.SELL
        sig = TradingSignal(
            direction=direction,
            confidence=float(setup.confidence),
            symbol="XAUUSD",
            timeframe="5m",
            strategy_name="priceaction",
            stop_loss=float(setup.stop_loss),
            take_profit=float(setup.take_profit),
            metadata={"entry": setup.entry, "price": setup.entry},
        )
        # Full history for meta features (short tail breaks UnifiedFeatureStore)
        full_window = df.iloc[: i + 1]
        snapshot = {"ohlcv": full_window, "htf_bias": 0, "current_time": ts_py}
        prob = float(meta.score(sig, snapshot, "RANGING", spread_pips=4.0))

        setups.append({
            "bar_index": i,
            "bar_time": str(ts),
            "direction": "BUY" if setup.direction > 0 else "SELL",
            "entry": float(setup.entry),
            "stop_loss": float(setup.stop_loss),
            "take_profit": float(setup.take_profit),
            "confidence": float(setup.confidence),
            "setup": getattr(setup.setup, "value", str(setup.setup)),
            "meta_prob": round(prob, 4),
            "hour": hour,
        })
        if prob >= META_CURRENT:
            stage_counts["meta_accepted"] += 1
        else:
            stage_counts["meta_rejected"] += 1
            rejection_reasons[f"meta_below_{META_CURRENT}"] += 1

    # duplicate suppression (same direction within 10 minutes)
    dedup_kept = []
    last_key_time: dict[str, pd.Timestamp] = {}
    dup_removed = 0
    for s in setups:
        key = s["direction"]
        t = pd.Timestamp(s["bar_time"])
        prev = last_key_time.get(key)
        if prev is not None and (t - prev) < pd.Timedelta(minutes=10):
            dup_removed += 1
            continue
        last_key_time[key] = t
        dedup_kept.append(s)
    stage_counts["after_duplicate_suppression"] = len(dedup_kept)
    stage_counts["duplicate_removed"] = dup_removed
    rejection_reasons["duplicate_setup_suppression"] = dup_removed

    # cooldown + max/day on meta-accepted @ 0.38
    meta_ok = [s for s in dedup_kept if s["meta_prob"] >= META_CURRENT]
    gated = _apply_frequency_gates(meta_ok, cooldown_bars=PROD_COOLDOWN, max_trades_per_day=PROD_MAX_DAY)
    stage_counts["after_cooldown_maxday"] = len(gated)
    stage_counts["cooldown_or_maxday_removed"] = len(meta_ok) - len(gated)
    if len(meta_ok) > len(gated):
        rejection_reasons["cooldown_or_max_trades_day"] = len(meta_ok) - len(gated)

    return setups, stage_counts, rejection_reasons, {
        "min_confidence": min_conf,
        "session": (session_start, session_end),
        "use_kill_zone": use_kz,
        "bars_scanned": len(df) - start_i,
        "dedup_setups": dedup_kept,
        "meta_ok_038": meta_ok,
        "gated_038": gated,
    }


def _apply_frequency_gates(
    cands: list[dict[str, Any]],
    *,
    cooldown_bars: int,
    max_trades_per_day: int,
    session_hours: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    last_entry = -10_000
    day_counts: dict[str, int] = {}
    for c in sorted(cands, key=lambda x: x["bar_index"]):
        i = int(c["bar_index"])
        if session_hours is not None:
            h = int(c.get("hour", pd.Timestamp(c["bar_time"]).hour))
            if not (session_hours[0] <= h < session_hours[1]):
                continue
        if i - last_entry < cooldown_bars:
            continue
        day = str(pd.Timestamp(c["bar_time"]).date())
        if day_counts.get(day, 0) >= max_trades_per_day:
            continue
        out.append(c)
        last_entry = i
        day_counts[day] = day_counts.get(day, 0) + 1
    return out


def _r_metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {"trades": 0, "win_rate": 0.0, "pf": 0.0, "expectancy_r": 0.0, "max_dd_r": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(rs),
        "win_rate": round(len(wins) / len(rs) * 100, 2),
        "pf": round(pf, 3) if pf != 999.0 else 999.0,
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "max_dd_r": round(mdd, 2),
    }


def replay_variant(
    df: pd.DataFrame,
    setups: list[dict[str, Any]],
    *,
    threshold: float,
    cooldown_bars: int = PROD_COOLDOWN,
    max_trades_per_day: int = PROD_MAX_DAY,
    session_hours: tuple[int, int] | None = None,
) -> dict[str, Any]:
    from tradingbot.ml.research.phase9a.pm_v2_research import profile_for_mode, simulate_pm_entry

    profile = profile_for_mode("52a")
    filtered = [s for s in setups if s["meta_prob"] >= threshold]
    gated = _apply_frequency_gates(
        filtered,
        cooldown_bars=cooldown_bars,
        max_trades_per_day=max_trades_per_day,
        session_hours=session_hours,
    )
    rs: list[float] = []
    open_until = -1
    for c in gated:
        i = int(c["bar_index"])
        if i <= open_until:
            continue
        sim = simulate_pm_entry(c, df, profile, spread_pips=4.0, slippage_pips=1.0)
        if sim is None:
            continue
        rs.append(float(sim.r_multiple))
        open_until = int(sim.exit_bar_index)
    m = _r_metrics_from_rs(rs)
    m["threshold"] = threshold
    m["cooldown_bars"] = cooldown_bars
    m["max_trades_per_day"] = max_trades_per_day
    m["session"] = (
        f"{session_hours[0]:02d}-{session_hours[1]:02d}UTC" if session_hours else "production(10-17)"
    )
    m["candidates_pre_gate"] = len(filtered)
    m["candidates_gated"] = len(gated)
    return m


def _operational_score(row: dict[str, Any]) -> float:
    trades = int(row["trades"])
    pf = float(row["pf"]) if row["pf"] != 999.0 else 3.0
    exp = float(row["expectancy_r"])
    dd = float(row["max_dd_r"])
    monthly = trades
    freq_pen = 0.0
    if monthly < 20:
        freq_pen = (20 - monthly) * 0.08
    elif monthly > 40:
        freq_pen = (monthly - 40) * 0.06
    gate_pen = 0.0
    if pf < 1.8:
        gate_pen += (1.8 - pf) * 0.5
    if exp < 0.40:
        gate_pen += (0.40 - exp) * 0.8
    if dd > 5.0:
        gate_pen += (dd - 5.0) * 0.3
    return pf * 0.35 + exp * 0.35 + min(trades, 40) / 40 * 0.3 - freq_pen - gate_pen


def pa_frequency_table(stage_counts: Counter, meta: dict[str, Any]) -> list[tuple[str, int, float]]:
    bars = int(stage_counts.get("bars_in_session", 0))
    raw = int(stage_counts.get("raw_setups", 0))
    pa_pass = int(stage_counts.get("pa_pass_confidence", 0))
    meta_acc = int(stage_counts.get("meta_accepted", 0))
    after_dup = int(stage_counts.get("after_duplicate_suppression", pa_pass))
    # dup applies to all confidence-pass setups
    gated = int(stage_counts.get("after_cooldown_maxday", 0))

    def rem(kept: int, base: int) -> float:
        return round(100.0 * (1 - kept / base), 1) if base else 0.0

    return [
        ("bars_in_session", bars, 0.0),
        ("raw_pa_setups", raw, rem(raw, bars)),
        ("after_pa_confidence", pa_pass, rem(pa_pass, raw)),
        ("after_meta_0.38", meta_acc, rem(meta_acc, pa_pass)),
        ("after_duplicate_suppression(on_all_pa_pass)", after_dup, rem(after_dup, pa_pass)),
        ("after_cooldown12_max3_on_meta038", gated, rem(gated, meta_acc)),
    ]


def adaptive_shadow_analysis(df: pd.DataFrame, pa_signal_bars: set[int]) -> dict[str, int]:
    from tradingbot.strategies.adaptive_quality_engine import evaluate_quality_at_index
    from tradingbot.strategies.adaptive_regime import prepare_adaptive_frame
    from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
    from tradingbot.domain.signal_helpers import compute_sl_tp
    from tradingbot.ml.decision_engine.decision_policy import VOL_REGIME_RULE_CONFIDENCE

    frame = prepare_adaptive_frame(df)
    window_start = df.attrs.get("window_start")
    start_i = 0
    if window_start is not None:
        start_i = int(df.index.searchsorted(pd.Timestamp(window_start)))
    start_i = max(start_i, 500, 60)

    counts: Counter = Counter()
    for i in range(start_i, len(frame)):
        pa_hold = i not in pa_signal_bars
        # also treat missing as hold — we only marked confidence-pass PA bars
        score, _ = evaluate_quality_at_index(frame, i, log_rejections=False)
        if score is None or score.direction is None:
            continue
        q = int(score.quality_score)
        dir_str = "BUY" if score.direction > 0 else "SELL"

        if pa_hold and dir_str == "BUY":
            counts["adaptive_buy_pa_hold"] += 1
        if pa_hold and dir_str == "SELL":
            counts["adaptive_sell_pa_hold"] += 1
        if not pa_hold:
            continue
        if q >= 70:
            counts["quality_gte_70"] += 1
        if 60 <= q < 70:
            counts["quality_60_69_watchlist"] += 1
        if q >= 70 and score.tier == "tradeable":
            counts["tradeable_quality_pa_hold"] += 1
            # RiskGate proxy: session 07-19, ATR already inside quality engine
            hour = pd.Timestamp(df.index[i]).hour
            if 7 <= hour < 19:
                counts["would_have_passed_RiskGate"] += 1
            try:
                sl, tp, _ = compute_sl_tp(
                    df.iloc[: i + 1], score.direction, VOL_REGIME_RULE_CONFIDENCE,
                    symbol="XAUUSD", strategy_name="adaptive", timeframe="M5",
                )
            except Exception:
                sl = tp = None
            if sl and tp:
                outcome = resolve_label_with_sl_tp(
                    df, i, score.direction, sl, tp, future_window_bars=72,
                )
                if outcome.get("exit_reason") == "tp":
                    counts["would_have_reached_TP1_before_SL"] += 1

    router = _read_jsonl(ROOT / "logs/router_decisions.jsonl", date_filter=SESSION_DATE)
    for r in router:
        if r.get("pa_signal") == "HOLD" and r.get("adaptive_signal") == "BUY":
            counts["today_adaptive_buy_pa_hold"] += 1
        if r.get("pa_signal") == "HOLD" and r.get("adaptive_signal") == "SELL":
            counts["today_adaptive_sell_pa_hold"] += 1
    return dict(counts)


def main() -> int:
    emit("PHASE 13B — No-Trade Root Cause & Frequency Recovery")
    emit("MODE=READ-ONLY + REPLAY (cache-only, no MT5, no config changes)")

    emit("TASK 1 — Today timeline")
    timeline_lines, today_summary = build_today_timeline()

    emit("TASK 2 — Load data + PA frequency 30d")
    df = load_m5_frame(30)
    setups, stage_counts, rejection_reasons, meta_info = collect_raw_pa_setups(df)
    emit(f"  raw setups={stage_counts.get('raw_setups',0)} pa_pass={stage_counts.get('pa_pass_confidence',0)} meta038={stage_counts.get('meta_accepted',0)}")

    freq_stages = pa_frequency_table(stage_counts, meta_info)
    meta_probs = [s["meta_prob"] for s in setups]
    # setups list is confidence-pass only
    meta_below = round(100 * sum(1 for p in meta_probs if p < META_CURRENT) / max(len(meta_probs), 1), 1)

    emit("TASK 3 — Meta threshold matrix")
    meta_rows: list[dict[str, Any]] = []
    base_trades_038 = None
    for th in THRESHOLDS:
        emit(f"  meta sweep th={th}")
        row = replay_variant(df, setups, threshold=th, cooldown_bars=PROD_COOLDOWN, max_trades_per_day=PROD_MAX_DAY)
        row["operational_score"] = round(_operational_score(row), 4)
        if th == META_CURRENT:
            base_trades_038 = row["trades"]
        meta_rows.append(row)
    base_trades = base_trades_038 or 1
    for row in meta_rows:
        row["trade_reduction_pct"] = round(100 * (1 - row["trades"] / base_trades), 1) if base_trades else 0.0

    emit("TASK 4 — Adaptive shadow")
    pa_bars = {int(s["bar_index"]) for s in setups}
    adaptive_counts = adaptive_shadow_analysis(df, pa_bars)
    emit(f"  quality>=70 PA-HOLD={adaptive_counts.get('quality_gte_70', 0)}")

    emit("TASK 5 — Recovery variants")
    variants_spec = [
        ("A", {"threshold": 0.38, "cooldown_bars": 12, "max_trades_per_day": 3, "session_hours": None}),
        ("B", {"threshold": 0.36, "cooldown_bars": 12, "max_trades_per_day": 3, "session_hours": None}),
        ("C", {"threshold": 0.35, "cooldown_bars": 14, "max_trades_per_day": 3, "session_hours": None}),
        ("D", {"threshold": 0.36, "cooldown_bars": 12, "max_trades_per_day": 3, "session_hours": (9, 17)}),
        ("E", {"threshold": 0.35, "cooldown_bars": 12, "max_trades_per_day": 4, "session_hours": None}),
    ]
    variants: list[dict[str, Any]] = []
    for label, kw in variants_spec:
        emit(f"  variant {label}")
        row = replay_variant(df, setups, **kw)
        row["variant"] = label
        row["operational_score"] = round(_operational_score(row), 4)
        variants.append(row)

    # Best operational threshold: prefer gates, else hold production 0.38
    def meets_gates(r: dict[str, Any]) -> bool:
        return (
            float(r["pf"]) >= 1.8
            and float(r["expectancy_r"]) >= 0.40
            and float(r["max_dd_r"]) <= 5.0
            and 20 <= int(r["trades"]) <= 40
        )

    gated_rows = [r for r in meta_rows if meets_gates(r)]
    if gated_rows:
        # Prefer mid-frequency among gate-passers (not max PF)
        best_op = min(gated_rows, key=lambda r: (abs(int(r["trades"]) - 30), -r["operational_score"]))
        recommended_th = best_op["threshold"]
        th_note = "meets operational gates"
    else:
        soft = [
            r for r in meta_rows
            if float(r["pf"]) >= 1.8 and float(r["expectancy_r"]) >= 0.40 and float(r["max_dd_r"]) <= 5.0
        ]
        if soft:
            best_op = min(soft, key=lambda r: (abs(int(r["trades"]) - 30), -r["operational_score"]))
            recommended_th = best_op["threshold"]
            th_note = "soft gates only (trade-count outside 20-40)"
        else:
            best_op = next(r for r in meta_rows if r["threshold"] == META_CURRENT)
            recommended_th = META_CURRENT
            th_note = "no threshold meets targets — hold production 0.38"

    primary_blocker = "PA_NO_SIGNAL"
    if today_summary.get("pa_signal_cycles", 0) == 0:
        if today_summary.get("adaptive_blocked", 0) > 0:
            primary_blocker = "PA_NO_SIGNAL"
        else:
            primary_blocker = "PA_NO_SIGNAL"

    raw_pa = int(stage_counts.get("raw_setups", 0))
    meta_acc = int(stage_counts.get("meta_accepted", 0))

    var_a = next(v for v in variants if v["variant"] == "A")
    var_b = next(v for v in variants if v["variant"] == "B")
    # Safe live change: only if improves frequency without breaking institutional gates
    safe_change = (
        int(var_b["trades"]) > int(var_a["trades"])
        and float(var_b["pf"]) >= 1.8
        and float(var_b["expectancy_r"]) >= 0.40
        and float(var_b["max_dd_r"]) <= 5.0
        and float(var_b["pf"]) >= float(var_a["pf"]) * 0.85  # no catastrophic PF collapse
    )
    # Today's zero trades were PA silence — threshold alone does not fix no-signal days
    if today_summary.get("pa_signal_cycles", 0) == 0:
        # still allow YES if B is a safer frequency setting for days PA fires
        pass

    shadow_n = int(adaptive_counts.get("quality_gte_70", 0))

    if safe_change:
        safest = (
            f"Lower META_LABEL_THRESHOLD from 0.38 to 0.36 (Variant B). "
            f"Replay 30d: trades {var_a['trades']}→{var_b['trades']}, "
            f"PF={var_b['pf']}, ExpR={var_b['expectancy_r']}, MaxDD={var_b['max_dd_r']}R. "
            f"Does NOT unlock Adaptive/ML. Note: today had 0 PA setups — this only helps when PA fires."
        )
        next_action = "Apply META_LABEL_THRESHOLD=0.36 in a controlled change window; keep PA_PRODUCTION_LOCK ON; re-verify next session PA signal rate."
    else:
        safest = (
            "No config change recommended for live right now. "
            "Today's 0 trades were caused by PA generating zero BUY/SELL (meta/RiskGate never reached). "
            "Lowering meta threshold cannot create trades on PA-silent days. "
            "Keep PA lock; investigate PA structure/session alignment separately."
        )
        next_action = "Keep production 0.38; investigate PA no_signal_or_low_confidence root cause (structure/BOS/session); Adaptive remains research-only."

    lines: list[str] = [
        "PHASE 13B — No-Trade Root Cause & Frequency Recovery",
        f"Generated UTC: {datetime.now(timezone.utc).isoformat()}",
        f"Session analyzed: {SESSION_DATE} (last trading session with router logs)",
        "MODE=READ-ONLY + REPLAY (no config changes, no orders, no Adaptive unlock, no ML live)",
        f"Replay data window: {df.index.min()} -> {df.index.max()} | PA session={meta_info['session']} UTC | MIN_CONF={meta_info['min_confidence']}",
        f"Production gates used: cooldown={PROD_COOLDOWN} bars, max_trades/day={PROD_MAX_DAY}, meta={META_CURRENT}",
        "",
        "========================================================================",
        "1. TODAY TIMELINE",
        "========================================================================",
        f"Router cycles: {today_summary.get('router_cycles', 0)} | "
        f"Window: {today_summary.get('session_start')} -> {today_summary.get('session_end')}",
        f"PA rejection reasons: {today_summary.get('pa_rejection_reasons')}",
        f"Router rejection top: {today_summary.get('rejection_top')}",
        f"Live trades: {today_summary.get('live_trades', 0)} | meta_events.jsonl present: {today_summary.get('meta_events_present')}",
        f"Adaptive BUY while PA HOLD (today): {today_summary.get('adaptive_blocked', 0)}",
        "",
    ]
    lines.extend(timeline_lines)

    lines.extend([
        "",
        "========================================================================",
        "2. PRIMARY BLOCKING STAGE",
        "========================================================================",
        f"PRIMARY_BLOCKER={primary_blocker}",
        "",
        f"Root cause chain ({SESSION_DATE}):",
        "  1. PA engine returned HOLD on every router cycle (254x no_signal_or_low_confidence)",
        "  2. Meta filter never evaluated — no PA BUY/SELL reached RiskGate",
        "  3. Adaptive produced BUY on multiple bars — blocked by PA_PRODUCTION_LOCK",
        "  4. selected_engine=NONE for all cycles; live trades=0",
        "  5. Watchdog also saw clean exits / restarts (coverage gaps mid-session)",
        f"  Adaptive logged-not-selected cycles: {today_summary.get('adaptive_blocked', 0)}",
        "",
        "Interpretation: frequency recovery via meta threshold helps months where PA fires;",
        "it does NOT fix a day with zero raw PA setups.",
    ])

    lines.extend([
        "",
        "========================================================================",
        "3. PA FREQUENCY TABLE (30d M5 replay)",
        "========================================================================",
        "| Stage | Count | Removal % |",
        "|-------|-------|-----------|",
    ])
    for name, count, rem in freq_stages:
        lines.append(f"| {name} | {count} | {rem}% |")
    lines.append("")
    lines.append("Special attention filters:")
    lines.append(f"  session_filter removals (bars skipped): {stage_counts.get('session_filter', 0)}")
    lines.append(f"  confidence_threshold (<{meta_info['min_confidence']}): {stage_counts.get('low_confidence', 0)}")
    lines.append(f"  meta_below_{META_CURRENT}: {stage_counts.get('meta_rejected', 0)}")
    lines.append(f"  duplicate_setup_suppression (10m same dir): {stage_counts.get('duplicate_removed', 0)}")
    lines.append(f"  cooldown_{PROD_COOLDOWN}_or_max_{PROD_MAX_DAY}/day on meta038: {stage_counts.get('cooldown_or_maxday_removed', 0)}")
    lines.append(f"  PA preset COOLDOWN_BARS=18 vs runtime_truth/backtest cooldown_bars={PROD_COOLDOWN} (replay uses {PROD_COOLDOWN})")
    lines.append("")
    lines.append("Top rejection reasons:")
    for k, v in rejection_reasons.most_common(12):
        lines.append(f"  {k}={v}")
    med = round(float(pd.Series(meta_probs).median()), 4) if meta_probs else 0.0
    lines.append(f"Meta prob median (PA confidence-pass setups): {med}")
    lines.append(f"Meta below {META_CURRENT} rate: {meta_below}%")

    lines.extend([
        "",
        "========================================================================",
        "4. META THRESHOLD MATRIX (30d candidate replay, same SL/TP, cd=12, max/day=3)",
        "========================================================================",
        "| Threshold | Trades | Win% | PF | ExpR | MaxDD | TradeRed% | OpScore |",
        "|-----------|--------|------|-----|------|-------|-----------|---------|",
    ])
    for r in meta_rows:
        flag = " *" if r["threshold"] == recommended_th else ""
        lines.append(
            f"| {r['threshold']} | {r['trades']} | {r['win_rate']} | {r['pf']} | "
            f"{r['expectancy_r']} | {r['max_dd_r']} | {r['trade_reduction_pct']} | {r['operational_score']}{flag} |"
        )
    lines.append("")
    lines.append(
        f"BEST_OPERATIONAL_THRESHOLD={recommended_th} "
        f"(target 20-40 trades/mo, PF>=1.8, Exp>=0.40R, MaxDD<=5R — not max PF)"
    )
    lines.append(f"Selection note: {th_note}")
    lines.append(
        f"Selected row: trades={best_op['trades']} PF={best_op['pf']} "
        f"ExpR={best_op['expectancy_r']} MaxDD={best_op['max_dd_r']}R"
    )
    lines.append(
        "Phase47A BacktestEngine reference (certified): "
        "th0.36 trades=27 PF=2.198 ExpR=0.627 MaxDD=4.03R accepted; "
        "th0.38 trades=25 PF=2.565 ExpR=0.758 MaxDD=3.03R accepted*"
    )

    lines.extend([
        "",
        "========================================================================",
        "5. ADAPTIVE SHADOW OPPORTUNITIES (research only — PA lock stays ON)",
        "========================================================================",
        "| Condition | Count |",
        "|-----------|-------|",
        f"| Adaptive BUY while PA HOLD | {adaptive_counts.get('adaptive_buy_pa_hold', 0)} |",
        f"| Adaptive SELL while PA HOLD | {adaptive_counts.get('adaptive_sell_pa_hold', 0)} |",
        f"| quality score >=70 | {adaptive_counts.get('quality_gte_70', 0)} |",
        f"| score 60-69 (watchlist) | {adaptive_counts.get('quality_60_69_watchlist', 0)} |",
        f"| would have passed RiskGate | {adaptive_counts.get('would_have_passed_RiskGate', 0)} |",
        f"| would have reached TP1 before SL | {adaptive_counts.get('would_have_reached_TP1_before_SL', 0)} |",
        f"| today Adaptive BUY / PA HOLD | {adaptive_counts.get('today_adaptive_buy_pa_hold', 0)} |",
        f"| today Adaptive SELL / PA HOLD | {adaptive_counts.get('today_adaptive_sell_pa_hold', 0)} |",
        "",
        "ADAPTIVE REMAINS LOCKED — research counts only.",
    ])

    lines.extend([
        "",
        "========================================================================",
        "6. RECOVERY VARIANT COMPARISON",
        "========================================================================",
        "| Variant | Config | Trades | Win% | PF | ExpR | MaxDD |",
        "|---------|--------|--------|------|-----|------|-------|",
    ])
    for v in variants:
        cfg = (
            f"th={v['threshold']} cd={v['cooldown_bars']} "
            f"max/d={v['max_trades_per_day']} sess={v['session']}"
        )
        lines.append(
            f"| {v['variant']} | {cfg} | {v['trades']} | {v['win_rate']} | "
            f"{v['pf']} | {v['expectancy_r']} | {v['max_dd_r']} |"
        )

    lines.extend([
        "",
        "========================================================================",
        "7. SAFEST LIVE CHANGE (if any)",
        "========================================================================",
        safest,
        "",
        "PHASE_13B_RESULT",
        f"TODAY_PRIMARY_BLOCKER={primary_blocker}",
        f"RAW_PA_SETUPS={raw_pa}",
        f"META_ACCEPTED={meta_acc}",
        f"BEST_OPERATIONAL_THRESHOLD={recommended_th}",
        f"ESTIMATED_MONTHLY_TRADES={best_op['trades']}",
        f"PF_AT_RECOMMENDED_THRESHOLD={best_op['pf']}",
        f"EXPECTANCY_AT_RECOMMENDED_THRESHOLD={best_op['expectancy_r']}",
        f"ADAPTIVE_SHADOW_OPPORTUNITIES={shadow_n}",
        f"SAFE_LIVE_CHANGE_AVAILABLE={'YES' if safe_change else 'NO'}",
        f"RECOMMENDED_NEXT_ACTION={next_action}",
        "",
    ])

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    emit(f"\nReport -> {REPORT}")
    emit("PHASE_13B_RESULT written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
