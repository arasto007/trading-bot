#!/usr/bin/env python3
from __future__ import annotations
import os, sys
from collections import Counter
from datetime import timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from tradingbot.config.dotenv_loader import load_dotenv
load_dotenv()

def main() -> int:
    import pandas as pd
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.filter_policy import aligned_session_hours
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.gold_strategies.m5_london_sweep import (
        diagnose_m5_london_hold,
        _in_entry_window,
    )
    from tradingbot.domain.pa_hardening import confirm_fvg_fill, detect_bos_continuation
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.services.engine_telemetry import get_engine_telemetry, init_engine_log_structure

    init_engine_log_structure()
    out = ROOT / "logs" / "engines" / "pa_hold_reasons.jsonl"
    out.write_text("", encoding="utf-8")
    pa = get_price_action_config("XAUUSD", "M5")
    min_conf = float(pa.get("MIN_CONFIDENCE", 0.52))
    ss, se = aligned_session_hours(pa)
    cd = int(pa.get("COOLDOWN_BARS", 18))
    df = pd.read_parquet(ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet")
    if not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    if "atr" not in df.columns:
        df = df.copy()
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()

    tel = get_engine_telemetry()
    N = 1000
    start = max(60, len(df) - N)
    reasons = Counter()
    flag_no_bos = 0
    flag_no_fvg = 0
    setups = 0
    would = 0
    last = None
    ny_bars = 0

    for i in range(start, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ss <= ts.hour < se:
            ny_bars += 1
        if not _in_entry_window(df, i, pa):
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
            en = enrich_price_action(df.iloc[: i + 1], pa, at_index=i)
            diag = diagnose_m5_london_hold(en, i, pa)
            setup = evaluate_gold_setup(en, i, pa, timeframe="M5")
            breaks = en.attrs.get("pa_breaks", []) or []
            fvgs = en.attrs.get("pa_fvgs", []) or []
            price = float(en["close"].iloc[i])
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
                    if last is None or (i - last) >= cd:
                        would += 1
                        last = i
                    continue
            else:
                reason = str(diag.get("reject_reason") or "no_setup")
                if reason == "setup_ok_pre_hardening":
                    reason = "hardening_rejected"
                conf = float(diag.get("confidence_score") or 0.0)
            row = {
                "session_ok": bool(diag.get("session_ok", True)),
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
        tel.record_pa_hold_reason(
            timestamp=ts.isoformat(), symbol="XAUUSD", timeframe="M5", **row
        )
        if (i - start + 1) % 200 == 0:
            print("progress", i - start + 1, flush=True)

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
    counts["no_bos"] = flag_no_bos
    counts["no_fvg"] = flag_no_fvg
    most = reasons.most_common(1)[0][0] if reasons else "none"
    est = would * (84.0 / max(ny_bars, 1))
    raw = "YES" if (would > 0 or setups > 0) else "NO"
    nlines = sum(1 for ln in out.open(encoding="utf-8") if ln.strip())

    lines = [
        "PHASE 14B-2 PA Hold Telemetry Replay",
        "HOLD_REASON_COUNTS",
    ]
    for k in keys:
        lines.append(k + "=" + str(counts[k]))
    lines.append("")
    lines.append("REJECT_TOP")
    for r, c in reasons.most_common(10):
        lines.append("  " + r + "=" + str(c))
    lines.extend(
        [
            "",
            "RESULT",
            "PA_TELEMETRY_UPGRADE=YES",
            "MOST_COMMON_HOLD_REASON=" + most,
            "RAW_SIGNAL_CAPABILITY=" + raw,
            "ESTIMATED_DAILY_SETUPS=" + ("%.2f" % est),
            "SAFE_NEXT_ACTION=KEEP_OBSERVABILITY_COLLECT_LIVE_HOLDS_NO_LOGIC_CHANGE",
            "WOULD_CD=" + str(would) + " SETUPS=" + str(setups) + " NY_BARS=" + str(ny_bars),
            "OUT_LINES=" + str(nlines),
        ]
    )
    text = "\n".join(lines) + "\n"
    print(text)
    (ROOT / "logs" / "phase14b2_pa_hold_telemetry.txt").write_text(text, encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
