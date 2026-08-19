#!/usr/bin/env python3
"""PHASE 17A — PA session heatmap + last-500 live forensic replay (research only)."""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT_DIR = ROOT / "logs" / "phase17a"
LOOKBACK_ENRICH = 500
REPLAY_BARS = 500
QUALITY_MIN = 55


def load_m5():
    import pandas as pd

    for name in ("XAUUSD_M5_90d.parquet", "XAUUSD_M5_180d.parquet", "XAUUSD_M5_60d.parquet"):
        path = ROOT / "data" / "cache" / name
        if path.exists():
            df = pd.read_parquet(path)
            src = name
            break
    else:
        raise FileNotFoundError("No XAUUSD M5 parquet cache found")
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
    return df, src


def score_meta(meta, setup, enriched, ts):
    try:
        from tradingbot.domain.enums import SignalDirection
        from tradingbot.domain.models import TradingSignal

        direction = SignalDirection.BUY if setup.direction > 0 else SignalDirection.SELL
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
        return float(
            meta.score(
                sig,
                {"symbol": "XAUUSD", "timeframe": "M5", "regime": "TREND", "ohlcv": enriched},
                "TREND",
            )
        )
    except Exception:
        return None


def drop_pct(prev: int, nxt: int) -> float:
    if prev <= 0:
        return 0.0
    return round(100.0 * max(0, prev - nxt) / prev, 2)


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.gold_strategies import evaluate_gold_setup
    from tradingbot.domain.gold_strategies.m5_london_sweep import diagnose_m5_london_hold
    from tradingbot.domain.pa_hardening import confirm_fvg_fill, detect_bos_continuation
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.research.phase17a_forensic import (
        is_near_miss,
        record_pa_forensic_decision,
    )
    from tradingbot.services.meta_labeler import MetaLabeler, reload_meta_labeler

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # Fresh forensic files for this replay (live daemon may append later)
    (OUT_DIR / "pa_live_decisions.jsonl").write_text("", encoding="utf-8")
    (OUT_DIR / "pa_near_miss.jsonl").write_text("", encoding="utf-8")

    reload_meta_labeler()
    meta = MetaLabeler()
    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    meta_th = float(cfg.get("META_LABEL_THRESHOLD", 0.38))
    min_q = int(cfg.get("MIN_QUALITY_SCORE", QUALITY_MIN) or QUALITY_MIN)
    cd = int(cfg.get("COOLDOWN_BARS", 18))
    max_day = int(cfg.get("MAX_TRADES_PER_DAY", 3))
    ny_s = int(cfg.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg.get("NY_ENTRY_END_HOUR", 17))

    df, src = load_m5()
    n = min(REPLAY_BARS, max(0, len(df) - LOOKBACK_ENRICH))
    start = len(df) - n
    print(f"DATA={src} bars={len(df)} replay={n} start={start}", flush=True)

    reasons = Counter()
    hour_bars = Counter()
    hour_raw = Counter()
    hour_near = Counter()
    hour_final = Counter()

    funnel = {
        "raw": 0,
        "sweep": 0,
        "reclaim": 0,
        "bos": 0,
        "fvg": 0,
        "confidence": 0,
        "quality": 0,
        "meta": 0,
        "riskgate": 0,
    }
    raw_setups = 0
    near_miss = 0
    last_trade_i = -10_000
    day_counts: Counter[str] = Counter()
    rows_funnel: list[dict[str, Any]] = []

    for i in range(start, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        hour = int(ts.hour)
        hour_bars[hour] += 1
        funnel["raw"] += 1

        sl = df.iloc[max(0, i - LOOKBACK_ENRICH + 1) : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, cfg, at_index=local_i)
        diag = diagnose_m5_london_hold(enriched, local_i, cfg)
        setup = evaluate_gold_setup(enriched, local_i, cfg, timeframe="M5")

        breaks = enriched.attrs.get("pa_breaks", []) or []
        fvgs = enriched.attrs.get("pa_fvgs", []) or []
        price = float(enriched["close"].iloc[local_i])
        bos = detect_bos_continuation(breaks, local_i, 1) or detect_bos_continuation(
            breaks, local_i, -1
        )
        fvg = confirm_fvg_fill(fvgs, price=price, direction=1, i=local_i) or confirm_fvg_fill(
            fvgs, price=price, direction=-1, i=local_i
        )
        conf = float(diag.get("confidence_score") or 0.0)
        qscore = 0.0
        if setup is not None:
            bos = bool(setup.metadata.get("bos_confirmed", bos))
            fvg = bool(setup.metadata.get("fvg_confirmed", fvg))
            conf = float(setup.confidence)
            qscore = float((setup.metadata or {}).get("quality_score", 0) or 0)

        session_ok = bool(diag.get("session_ok", False))
        asian = bool(diag.get("asian_range_built", False))
        sweep = bool(diag.get("sweep_detected", False))
        reclaim = bool(diag.get("reclaim_detected", False))

        if sweep:
            funnel["sweep"] += 1
        if sweep and reclaim:
            funnel["reclaim"] += 1
            raw_setups += 1
            hour_raw[hour] += 1
        if sweep and reclaim and bos:
            funnel["bos"] += 1
        if sweep and reclaim and bos and fvg:
            funnel["fvg"] += 1
        if setup is not None and conf >= min_conf:
            funnel["confidence"] += 1
        if setup is not None and conf >= min_conf and qscore >= min_q:
            funnel["quality"] += 1

        meta_ok = False
        meta_prob = None
        if setup is not None and conf >= min_conf and qscore >= min_q:
            meta_prob = score_meta(meta, setup, enriched, ts)
            if meta_prob is not None and meta_prob >= meta_th:
                meta_ok = True
                funnel["meta"] += 1

        risk_ok = False
        if meta_ok:
            day = str(ts.date())
            if i - last_trade_i >= cd and day_counts[day] < max_day:
                risk_ok = True
                funnel["riskgate"] += 1
                last_trade_i = i
                day_counts[day] += 1
                hour_final[hour] += 1

        nm = is_near_miss(
            sweep_ok=sweep,
            reclaim_ok=reclaim,
            bos_ok=bos,
            fvg_ok=fvg,
            quality_score=qscore,
        )
        if nm:
            near_miss += 1
            hour_near[hour] += 1

        if setup is None:
            reason = str(diag.get("reject_reason") or "no_setup")
            if reason == "setup_ok_pre_hardening":
                reason = "hardening_rejected"
        elif conf < min_conf:
            reason = "confidence_below_threshold"
        elif qscore < min_q:
            reason = "quality_below_min"
        elif not meta_ok:
            reason = "meta_rejected"
        elif not risk_ok:
            reason = "riskgate_cooldown_or_day_cap"
        else:
            reason = "signal_emitted"
        reasons[reason] += 1

        record_pa_forensic_decision(
            timestamp=ts,
            symbol="XAUUSD",
            timeframe="M5",
            session_ok=session_ok,
            asian_range_ready=asian,
            sweep_detected=sweep,
            reclaim_ok=reclaim,
            bos_ok=bos,
            fvg_ok=fvg,
            confidence=conf,
            quality_score=qscore,
            reject_reason=reason,
            extra={
                "event": "pa_signal" if reason == "signal_emitted" else "pa_hold",
                "meta_prob": meta_prob,
                "bar_index": i,
            },
        )

        rows_funnel.append(
            {
                "i": i,
                "hour": hour,
                "session_ok": session_ok,
                "sweep": sweep,
                "reclaim": reclaim,
                "bos": bos,
                "fvg": fvg,
                "confidence": conf,
                "quality": qscore,
                "meta_ok": meta_ok,
                "risk_ok": risk_ok,
                "reason": reason,
            }
        )
        if (i - start + 1) % 100 == 0:
            print(f"progress={i - start + 1}/{n}", flush=True)

    # Heatmap table
    heat_lines = [
        "| UTC Hour | Bars | Raw Setups | Near Miss | Final Signal |",
        "| -------- | ---- | ---------- | --------- | ------------ |",
    ]
    hour_score = {}
    for h in range(24):
        bars = int(hour_bars[h])
        raw_h = int(hour_raw[h])
        nm_h = int(hour_near[h])
        fin_h = int(hour_final[h])
        heat_lines.append(f"| {h:02d} | {bars} | {raw_h} | {nm_h} | {fin_h} |")
        if bars > 0:
            hour_score[h] = (raw_h + fin_h * 5, raw_h, fin_h, nm_h)

    best_h = max(hour_score, key=lambda k: hour_score[k]) if hour_score else -1
    # worst among hours that have bars in NY window preferentially
    ny_hours = [h for h in hour_score if ny_s <= h < ny_e]
    pool = ny_hours if ny_hours else list(hour_score)
    worst_h = min(pool, key=lambda k: (hour_score[k][1], hour_score[k][2])) if pool else -1

    f = funnel
    drops = {
        "sweep": drop_pct(f["raw"], f["sweep"]),
        "reclaim": drop_pct(f["sweep"], f["reclaim"]),
        "bos": drop_pct(f["reclaim"], f["bos"]),
        "fvg": drop_pct(f["bos"], f["fvg"]),
        "quality": drop_pct(f["confidence"], f["quality"]),
        "meta": drop_pct(f["quality"], f["meta"]),
    }
    # confidence drop vs fvg stage (setups that had fvg vs passed conf)
    drops["confidence"] = drop_pct(f["fvg"], f["confidence"])

    top3 = reasons.most_common(3)
    while len(top3) < 3:
        top3.append(("n/a", 0))

    # Volume-based truth: top reject reasons, not tiny-n funnel 100% drops
    skip_reasons = {"signal_emitted", "n/a"}
    ranked_reasons = [r for r, _c in top3 if r not in skip_reasons]
    primary = ranked_reasons[0] if ranked_reasons else "unknown"
    secondary = ranked_reasons[1] if len(ranked_reasons) > 1 else primary

    recovery_map = {
        "outside_ny_entry_window": "observe_only_no_live_patch",
        "kill_zone_blocked": "observe_only_no_live_patch",
        "no_sweep": "sweep_sensitivity_research",
        "no_reclaim": "reclaim_softening_research",
        "no_bos": "bos_sensitivity_research",
        "no_fvg": "fvg_optional_research",
        "quality_gate": "quality_threshold_research",
        "meta_gate": "meta_threshold_research",
        "no_reclaim_inside_asian": "reclaim_softening_research",
        "hardening_rejected": "quality_threshold_research",
        "meta_rejected": "meta_threshold_research",
    }
    # In-session recovery target: do not recommend live session widening
    safe_target = recovery_map.get(secondary, recovery_map.get(primary, "observe_only_no_live_patch"))

    funnel_json = {
        "data": src,
        "live_bars_analyzed": n,
        "funnel_counts": f,
        "funnel_drop_pct": drops,
        "raw_setups": raw_setups,
        "near_miss_count": near_miss,
        "reject_reasons": dict(reasons.most_common()),
        "heatmap": {
            str(h): {
                "bars": int(hour_bars[h]),
                "raw_setups": int(hour_raw[h]),
                "near_miss": int(hour_near[h]),
                "final_signal": int(hour_final[h]),
            }
            for h in range(24)
        },
        "config": {
            "min_confidence": min_conf,
            "meta_threshold": meta_th,
            "min_quality": min_q,
            "cooldown_bars": cd,
            "ny_window": f"{ny_s}-{ny_e}",
        },
    }
    (OUT_DIR / "pa_funnel_500.json").write_text(
        json.dumps(funnel_json, indent=2), encoding="utf-8"
    )

    lines = [
        "PHASE 17A PA Live Forensic Truth Engine",
        f"DATA={src}",
        "PATCH_APPLIED=NO",
        "",
        "SESSION HEATMAP (last 500 M5 bars)",
        *heat_lines,
        "",
        f"FUNNEL raw={f['raw']} sweep={f['sweep']} reclaim={f['reclaim']} bos={f['bos']} "
        f"fvg={f['fvg']} confidence={f['confidence']} quality={f['quality']} "
        f"meta={f['meta']} riskgate={f['riskgate']}",
        "",
        "TOP_REJECT_REASONS",
    ]
    for k, (r, c) in enumerate(top3, 1):
        lines.append(f"{k}. {r}={c}")
    lines.append("")
    lines.append("PHASE_17A_RESULT")
    lines.append("")
    lines.append(f"LIVE_BARS_ANALYZED={n}")
    lines.append(f"RAW_SETUPS={raw_setups}")
    lines.append(f"NEAR_MISS_COUNT={near_miss}")
    lines.append("")
    lines.append("TOP_REJECT_REASONS=")
    for k, (r, c) in enumerate(top3, 1):
        lines.append(f"{k}. {r}={c}")
    lines.append("")
    lines.append(f"FUNNEL_DROP_PCT_SWEEP={drops['sweep']}")
    lines.append(f"FUNNEL_DROP_PCT_RECLAIM={drops['reclaim']}")
    lines.append(f"FUNNEL_DROP_PCT_BOS={drops['bos']}")
    lines.append(f"FUNNEL_DROP_PCT_FVG={drops['fvg']}")
    lines.append(f"FUNNEL_DROP_PCT_QUALITY={drops['quality']}")
    lines.append(f"FUNNEL_DROP_PCT_META={drops['meta']}")
    lines.append("")
    lines.append(f"BEST_UTC_HOUR={best_h:02d}" if best_h >= 0 else "BEST_UTC_HOUR=NA")
    lines.append(f"WORST_UTC_HOUR={worst_h:02d}" if worst_h >= 0 else "WORST_UTC_HOUR=NA")
    lines.append("")
    lines.append(f"PRIMARY_LIVE_BLOCKER={primary}")
    lines.append(f"SECONDARY_BLOCKER={secondary}")
    lines.append(f"SAFE_RECOVERY_TARGET={safe_target}")
    lines.append("PATCH_APPLIED=NO")
    text = "\n".join(lines) + "\n"
    (OUT_DIR / "phase17a_result.txt").write_text(text, encoding="utf-8")
    print(text)
    print("WROTE", OUT_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
