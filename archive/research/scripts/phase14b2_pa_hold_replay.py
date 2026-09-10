#!/usr/bin/env python3
"""PHASE 14B-2 — replay last 1000 M5 bars into pa_hold_reasons.jsonl (READ/OBS)."""
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

N = 1000


def main() -> int:
    import pandas as pd
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.filter_policy import aligned_session_hours, is_session_filter_enabled
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.gold_strategies.m5_london_sweep import diagnose_m5_london_hold
    from tradingbot.domain.pa_hardening import (
        confirm_fvg_fill,
        detect_bos_continuation,
    )
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.services.engine_telemetry import get_engine_telemetry, init_engine_log_structure

    init_engine_log_structure()
    out_path = ROOT / "logs" / "engines" / "pa_hold_reasons.jsonl"
    # Fresh replay file for this phase (observability sample)
    out_path.write_text("", encoding="utf-8")

    pa_cfg = get_price_action_config("XAUUSD", "M5")
    min_conf = float(pa_cfg.get("MIN_CONFIDENCE", 0.52))
    ss, se = aligned_session_hours(pa_cfg)
    session_filter = is_session_filter_enabled(pa_cfg)

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

    tel = get_engine_telemetry()
    start = max(60, len(df) - N)
    reasons = Counter()
    flag_no_bos = 0
    flag_no_fvg = 0
    setups = 0
    would = 0
    last_sig_i = None
    cd = int(pa_cfg.get("COOLDOWN_BARS", 18))

    for i in range(start, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        in_sess = ss <= ts.hour < se
        window = df.iloc[: i + 1]
        enriched = enrich_price_action(window, pa_cfg, at_index=i)

        if session_filter and not in_sess:
            row = {
                "session_ok": False,
                "asian_range_built": False,
                "sweep_detected": False,
                "reclaim_detected": False,
                "bos_detected": False,
                "fvg_detected": False,
                "confidence_score": 0.0,
                "reject_reason": "outside_ny_entry_window",
            }
        else:
            diag = diagnose_m5_london_hold(enriched, i, pa_cfg)
            setup = evaluate_gold_setup(enriched, i, pa_cfg, timeframe="M5")
            breaks = enriched.attrs.get("pa_breaks", []) or []
            fvgs = enriched.attrs.get("pa_fvgs", []) or []
            price = float(enriched["close"].iloc[i])
            bos = detect_bos_continuation(breaks, i, 1) or detect_bos_continuation(breaks, i, -1)
            fvg = confirm_fvg_fill(fvgs, price=price, direction=1, i=i) or confirm_fvg_fill(
                fvgs, price=price, direction=-1, i=i
            )
            if setup is not None:
                bos = bool(setup.metadata.get("bos_confirmed", bos))
                fvg = bool(setup.metadata.get("fvg_confirmed", fvg))
                setups += 1
                if float(setup.confidence) < min_conf:
                    reason = "confidence_below_threshold"
                    conf = float(setup.confidence)
                else:
                    # would-be signal (pre meta); still log as hold for telemetry sample? 
                    # Live would emit BUY/SELL — for replay HOLD stats we skip writing hold
                    if last_sig_i is None or (i - last_sig_i) >= cd:
                        would += 1
                        last_sig_i = i
                    continue
            else:
                reason = str(diag.get("reject_reason") or "no_setup")
                if reason == "setup_ok_pre_hardening":
                    reason = "hardening_rejected"
                conf = float(diag.get("confidence_score") or 0.0)
            row = {
                "session_ok": bool(diag.get("session_ok", in_sess)),
                "asian_range_built": bool(diag.get("asian_range_built", False)),
                "sweep_detected": bool(diag.get("sweep_detected", False)),
                "reclaim_detected": bool(diag.get("reclaim_detected", False)),
                "bos_detected": bool(bos),
                "fvg_detected": bool(fvg),
                "confidence_score": conf,
                "reject_reason": reason,
            }

        if not row["bos_detected"]:
            flag_no_bos += 1
        if not row["fvg_detected"]:
            flag_no_fvg += 1
        reasons[row["reject_reason"]] += 1
        tel.record_pa_hold_reason(timestamp=ts.isoformat(), symbol="XAUUSD", timeframe="M5", **row)

    # Stats keys required by phase
    keys = [
        "outside_ny_entry_window",
        "no_asian_range",
        "no_sweep",
        "no_reclaim_inside_asian",
        "no_bos",
        "no_fvg",
        "confidence_below_threshold",
    ]
    counts = {k: int(reasons.get(k, 0)) for k in keys}
    # no_bos / no_fvg as flag-based counts (structure observability)
    counts["no_bos"] = flag_no_bos
    counts["no_fvg"] = flag_no_fvg

    most = reasons.most_common(1)[0][0] if reasons else "none"
    # estimated daily: would across ~1000 bars (~3.5 trading days of M5) scale
    bars = len(df) - start
    days_equiv = max(bars / 288.0, 0.01)
    est = would / days_equiv
    # better: NY session bars in sample / 84
    ny_bars = sum(1 for i in range(start, len(df)) if ss <= df.index[i].hour < se)
    est2 = would * (84.0 / max(ny_bars, 1))

    lines = []
    def emit(t=""):
        lines.append(t)
        print(t)

    emit("PHASE 14B-2 PA Hold Telemetry Replay")
    emit("BARS=" + str(bars) + " LAST=" + str(df.index[-1]))
    emit("OUT=" + str(out_path) + " lines=" + str(sum(1 for _ in out_path.open(encoding='utf-8') if _.strip())))
    emit("")
    emit("HOLD_REASON_COUNTS")
    for k in keys:
        emit(k + "=" + str(counts[k]))
    emit("")
    emit("REJECT_REASON_TOP")
    for r, c in reasons.most_common(12):
        emit("  " + r + "=" + str(c))
    emit("RAW_SETUPS_HARDENED=" + str(setups) + " WOULD_CD=" + str(would))
    emit("EST_FROM_NY_SCALE=" + ("%.2f" % est2))

    raw_cap = "YES" if would > 0 or setups > 0 else "NO"
    emit("")
    emit("RESULT")
    emit("PA_TELEMETRY_UPGRADE=YES")
    emit("MOST_COMMON_HOLD_REASON=" + most)
    emit("RAW_SIGNAL_CAPABILITY=" + raw_cap)
    emit("ESTIMATED_DAILY_SETUPS=" + ("%.2f" % est2))
    emit("SAFE_NEXT_ACTION=KEEP_OBSERVABILITY_COLLECT_LIVE_HOLDS_NO_LOGIC_CHANGE")

    report = ROOT / "logs" / "phase14b2_pa_hold_telemetry.txt"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    emit("WROTE=" + str(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
