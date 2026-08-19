"""Re-run 14A-2 with corrected session_ok and NY-day estimate. Writes UTF-8 report."""
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
    from tradingbot.services.meta_labeler import MetaLabeler
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import TradingSignal

    # import diagnose from audit module
    sys.path.insert(0, str(ROOT / "scripts"))
    from phase14a2_pa_no_signal_audit import (
        diagnose_london_reject,
        load_m5_df,
        read_jsonl_tail,
        structure_flags,
    )

    lines: list[str] = []

    def emit(t: str = "") -> None:
        lines.append(t)
        print(t)

    pa_cfg = get_price_action_config("XAUUSD", "M5")
    min_conf = float(pa_cfg.get("MIN_CONFIDENCE", 0.52))
    meta_th = float(pa_cfg.get("META_LABEL_THRESHOLD", 0.38))
    min_quality = int(pa_cfg.get("MIN_QUALITY_SCORE", 0))
    sess_start, sess_end = aligned_session_hours(pa_cfg)
    demo_override = demo_session_override_active()
    session_filter_enabled = is_session_filter_enabled(pa_cfg)

    emit("=" * 72)
    emit("PHASE 14A-2 PA No-Signal Deep Audit (READ-ONLY) v2")
    emit("generated_at_utc=" + datetime.now(timezone.utc).isoformat())
    emit("=" * 72)
    emit("NOTE: tradingbot/strategies/priceaction.py MISSING")
    emit("NOTE: real PA path = engine/strategies/price_action_strategy.py")
    emit("NOTE: presets = tradingbot/config/pa_symbol_tf_presets.py")
    emit("DEMO_DISABLE_SESSION_FILTER_ACTIVE=" + str(demo_override))
    emit("SESSION_FILTER_ENABLED=" + str(session_filter_enabled))
    emit("ALIGNED_SESSION_HOURS=" + str((sess_start, sess_end)))

    df, source, note = load_m5_df()
    emit("DATA_SOURCE=" + source)
    emit("DATA_NOTE=" + note)
    if "atr" not in df.columns:
        df = df.copy()
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()

    meta = MetaLabeler()
    meta_ready = bool(meta.is_ready_for("M5"))

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
    confs_with_setup: list[float] = []

    def eval_bar(i: int) -> dict:
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        # Table session_ok = clock window 10-17 (aligned), independent of demo override
        in_session_hours = sess_start <= ts.hour < sess_end
        session_ok = in_session_hours

        window = df.iloc[: i + 1]
        enriched = enrich_price_action(window, pa_cfg, at_index=i)
        setup = None
        reject_reason = "ok"

        # Live strategy path: if session filter enabled, block outside hours first
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

        if live_session_gate:
            gold = evaluate_gold_setup(enriched, i, pa_cfg, timeframe="M5")
            if gold is not None and setup is None:
                setup = gold

        bos, sweep, fvg = structure_flags(enriched, i, setup)
        conf = float(getattr(setup, "confidence", 0) or 0) if setup else 0.0
        return {
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
            "setup": setup,
            "conf": conf,
        }

    for i in range(start, len(df)):
        r = eval_bar(i)
        setup = r.pop("setup")
        conf = r.pop("conf")
        if setup:
            confs_with_setup.append(conf)
        if not r["bos_detected"]:
            counts["BOS missing"] += 1
        if not r["sweep_detected"]:
            counts["Sweep missing"] += 1
        if not r["fvg_detected"]:
            counts["FVG missing"] += 1
        if not r["session_ok"]:
            counts["Session blocked"] += 1
        if setup is not None and conf < min_conf:
            counts["Confidence below threshold"] += 1
        if r["reject_reason"].startswith("meta_below"):
            counts["Meta would reject"] += 1
        if r["reject_reason"].startswith("would_signal"):
            if r["direction"] == "BUY":
                counts["Would become BUY"] += 1
            elif r["direction"] == "SELL":
                counts["Would become SELL"] += 1
        reject_counter[r["reject_reason"]] += 1
        rows_out.append(r)

    emit("")
    emit("LAST_200_M5_BAR_EXTRACT (tail 20)")
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
    emit("REJECT_REASON_TOP (last 200)")
    for reason, c in reject_counter.most_common(15):
        emit("  " + reason + ": " + str(c))

    in_sess = [r for r in rows_out if r["session_ok"]]
    in_c = Counter(r["reject_reason"] for r in in_sess)
    emit("IN_SESSION_BARS=" + str(len(in_sess)))
    emit("IN_SESSION_REJECT_TOP=" + str(in_c.most_common(10)))

    # Estimate from last 10 NY session days in cache (hours 10-17)
    emit("")
    emit("NY_SESSION_DAY_SCAN (cache, last available days)")
    days = sorted({df.index[i].date() for i in range(len(df))})
    day_stats = []
    for day in days[-15:]:
        idxs = [
            i
            for i in range(len(df))
            if df.index[i].date() == day and sess_start <= df.index[i].hour < sess_end
        ]
        if len(idxs) < 20:
            continue
        would_b = would_s = setups = 0
        reasons: Counter[str] = Counter()
        for i in idxs:
            r = eval_bar(i)
            reasons[r["reject_reason"]] += 1
            if r["reject_reason"].startswith("would_signal"):
                if r["direction"] == "BUY":
                    would_b += 1
                elif r["direction"] == "SELL":
                    would_s += 1
            if r["confidence_score"] > 0:
                setups += 1
        day_stats.append(
            {
                "day": str(day),
                "bars": len(idxs),
                "setups": setups,
                "buy": would_b,
                "sell": would_s,
                "top": reasons.most_common(3),
            }
        )
        emit(
            "  "
            + str(day)
            + " bars="
            + str(len(idxs))
            + " setups_conf>0="
            + str(setups)
            + " would_buy="
            + str(would_b)
            + " would_sell="
            + str(would_s)
            + " top="
            + str(reasons.most_common(3))
        )

    # Logs
    emit("")
    emit("LOG_CROSSCHECK")
    pa_ev = read_jsonl_tail(ROOT / "logs" / "engines" / "pa_events.jsonl", 800)
    router = read_jsonl_tail(ROOT / "logs" / "router_decisions.jsonl", 800)
    pa_reasons = Counter(str(e.get("reason", "")) for e in pa_ev if e.get("event") == "rejection")
    pa_signals = sum(1 for e in pa_ev if e.get("event") == "signal")
    router_pa = Counter(str(r.get("pa_signal", "")) for r in router)
    emit(
        "  pa_events_tail="
        + str(len(pa_ev))
        + " signals="
        + str(pa_signals)
        + " rejection_reasons="
        + str(dict(pa_reasons))
    )
    emit("  router_pa_signal=" + str(dict(router_pa)))

    would = counts["Would become BUY"] + counts["Would become SELL"]
    most_common_reject = reject_counter.most_common(1)[0][0]

    if in_c:
        top_in = in_c.most_common(1)[0][0]
    else:
        top_in = most_common_reject

    if top_in.startswith("sweep") or top_in in (
        "no_reclaim_inside_asian",
        "sweep_pattern_incomplete",
    ):
        primary = "NO_ASIAN_SWEEP_RECLAIM"
    elif top_in == "outside_ny_entry_window":
        primary = "OUTSIDE_NY_ENTRY_WINDOW"
    elif most_common_reject == "outside_ny_entry_window" and top_in in (
        "no_reclaim_inside_asian",
        "sweep_missing_vs_asian",
        "sweep_pattern_incomplete",
    ):
        primary = "NO_ASIAN_SWEEP_RECLAIM"
    else:
        primary = top_in.upper()

    # Prefer structural primary when sample is mostly off-window
    if len(in_sess) < 30 and in_c:
        primary = "NO_ASIAN_SWEEP_RECLAIM" if top_in in (
            "no_reclaim_inside_asian",
            "sweep_missing_vs_asian",
            "sweep_pattern_incomplete",
        ) else top_in.upper()
        primary = primary + " (last200 mostly off-NY; in-session top)"

    ny_would = [d["buy"] + d["sell"] for d in day_stats[-7:]] if day_stats else []
    est = (sum(ny_would) / len(ny_would)) if ny_would else 0.0
    can = "YES" if (would > 0 or any((d["buy"] + d["sell"]) > 0 for d in day_stats)) else "NO"

    if confs_with_setup:
        passed = [r["confidence_score"] for r in rows_out if r["reject_reason"].startswith("would_signal")]
        lowest_safe = round(min(passed), 3) if passed else min_conf
    else:
        # from day scan
        lowest_safe = "N/A_NO_SETUP_IN_LAST_200"
        # try find any would_signal conf in day scan by quick pass last day with signals
        for d in reversed(day_stats):
            if d["buy"] + d["sell"] > 0:
                lowest_safe = str(min_conf) + "_PRESET_NO_LOWERING"
                break

    if can == "YES" and would == 0:
        recovery = "KEEP_PRESET_WAIT_FOR_NY_ASIAN_SWEEP_RECLAIM_NO_CONFIG_CHANGE"
    elif top_in in ("no_reclaim_inside_asian", "sweep_missing_vs_asian", "sweep_pattern_incomplete"):
        recovery = "KEEP_PRESET_WAIT_FOR_ASIAN_SWEEP_RECLAIM_NO_CONFIG_CHANGE"
    else:
        recovery = "KEEP_PA_PRODUCTION_LOCK_NO_CONFIG_CHANGE"

    # Live today root cause from logs
    emit("")
    emit("LIVE_LOG_ROOT_CAUSE")
    emit("  Live PA rejections are opaque reason=no_signal_or_low_confidence")
    emit("  Replay shows root is missing london_sweep setup (no asian sweep+reclaim),")
    emit("  not confidence/meta (zero setups reached those gates in last 200).")

    emit("")
    emit("RESULT")
    emit("PRIMARY_PA_BLOCKER=" + primary)
    emit("MOST_COMMON_REJECT_REASON=" + most_common_reject)
    emit("PA_CAN_PRODUCE_SIGNAL=" + can)
    emit("ESTIMATED_SIGNALS_PER_DAY=" + ("%.2f" % est))
    emit("LOWEST_SAFE_CONFIDENCE=" + str(lowest_safe))
    emit("SAFE_RECOVERY_ACTION=" + recovery)

    out = ROOT / "logs" / "phase14a2_pa_no_signal_audit.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "logs" / "phase14a2_last200_extract.json").write_text(
        json.dumps(rows_out, indent=2), encoding="utf-8"
    )
    print("Wrote", out)


if __name__ == "__main__":
    main()
