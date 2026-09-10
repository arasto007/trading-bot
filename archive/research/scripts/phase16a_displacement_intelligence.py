#!/usr/bin/env python3
"""PHASE 16A runner — Institutional Displacement Intelligence (research only)."""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from copy import deepcopy
from datetime import timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.research.displacement_intelligence import (
    BUCKETS,
    bucket_label,
    compute_displacement_score,
    metrics_from_trades,
    path_mfe_mae_final,
)


LOOKBACK = 500


def load_df():
    import pandas as pd

    path = ROOT / "data" / "cache" / "XAUUSD_M5_90d.parquet"
    df = pd.read_parquet(path)
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
    return df


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
    from tradingbot.domain.pa_hardening import apply_setup_hardening
    from tradingbot.domain.price_action import enrich_price_action

    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    df = load_df()
    ny_s = int(cfg.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg.get("NY_ENTRY_END_HOUR", 17))
    cd = int(cfg.get("COOLDOWN_BARS", 18))
    max_day = int(cfg.get("MAX_TRADES_PER_DAY", 3))

    print(f"DF bars={len(df)} window={ny_s}-{ny_e}", flush=True)

    rows: list[dict[str, Any]] = []
    scanned = 0
    for i in range(LOOKBACK, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if not (ny_s <= ts.hour < ny_e):
            continue
        scanned += 1
        if scanned % 1500 == 0:
            print(f"progress={scanned} setups={len(rows)}", flush=True)

        sl = df.iloc[i - LOOKBACK + 1 : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, cfg, at_index=local_i)
        setup0 = evaluate_m5_london_sweep(enriched, local_i, cfg)
        if setup0 is None:
            continue
        setup = apply_setup_hardening(enriched, local_i, cfg, setup0, timeframe="M5")
        if setup is None:
            continue

        direction = int(setup.direction)
        sc = compute_displacement_score(enriched, local_i, direction=direction)
        feats = sc.features
        mfe, mae, final_r = path_mfe_mae_final(
            df,
            i,
            direction=direction,
            entry=float(setup.entry),
            sl=float(setup.stop_loss),
            tp=float(setup.take_profit),
        )
        bkt = bucket_label(sc.total)
        rows.append(
            {
                "timestamp": ts.isoformat(),
                "bar_index": i,
                "direction": direction,
                "entry": float(setup.entry),
                "stop_loss": float(setup.stop_loss),
                "take_profit": float(setup.take_profit),
                "body_atr": feats.body_atr,
                "close_near_high": feats.close_near_high,
                "close_near_low": feats.close_near_low,
                "range_expansion": feats.range_expansion,
                "fvg_size_atr": feats.fvg_size_atr,
                "follow_through_2": feats.follow_through_2,
                "displacement_velocity": feats.displacement_velocity,
                "close_near_extreme": feats.close_near_extreme,
                "body_atr_pts": sc.body_atr_pts,
                "range_expansion_pts": sc.range_expansion_pts,
                "close_near_extreme_pts": sc.close_near_extreme_pts,
                "fvg_size_atr_pts": sc.fvg_size_atr_pts,
                "follow_through_2_pts": sc.follow_through_2_pts,
                "displacement_score": sc.total,
                "score_bucket": bkt or "below_50",
                "MFE_R": mfe,
                "MAE_R": mae,
                "final_R": final_r,
                "day": str(ts.date()),
            }
        )

    rows.sort(key=lambda r: r["bar_index"])
    traded: list[dict[str, Any]] = []
    last = -10000
    open_until = -1
    day_counts: Counter[str] = Counter()
    for r in rows:
        ii = r["bar_index"]
        if ii <= open_until or ii - last < cd:
            r["traded"] = 0
            continue
        if day_counts[r["day"]] >= max_day:
            r["traded"] = 0
            continue
        r["traded"] = 1
        traded.append(r)
        last = ii
        open_until = ii + 12
        day_counts[r["day"]] += 1

    out_csv = ROOT / "logs" / "phase16a_displacement_scores.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) + (["traded"] if rows and "traded" not in rows[0] else [])
    # ensure traded in fieldnames
    if "traded" not in fieldnames:
        fieldnames.append("traded")
    # unique preserve order
    seen = set()
    fieldnames = [f for f in fieldnames if not (f in seen or seen.add(f))]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    bucket_stats: dict[str, Any] = {}
    for _lo, _hi, name in BUCKETS:
        subset = [r for r in traded if r.get("score_bucket") == name]
        bucket_stats[name] = metrics_from_trades(subset)

    # Best by PF then expectancy then MFE
    best_name = None
    best_key = (-1e9, -1e9, -1e9)
    for name, m in bucket_stats.items():
        if m["trades"] <= 0:
            continue
        key = (m["profit_factor"], m["expectancy_R"], m["mean_MFE_R"])
        if key > best_key:
            best_key = key
            best_name = name
    if best_name is None:
        best_name = "50-60"
        best_m = bucket_stats[best_name]
    else:
        best_m = bucket_stats[best_name]

    # Validity: best bucket has trades, PF>=1.0 and expectancy>0, OR
    # score monotonic improvement vs lowest non-empty bucket
    nonempty = [(n, bucket_stats[n]) for _, _, n in BUCKETS if bucket_stats[n]["trades"] > 0]
    valid = False
    if best_m["trades"] >= 5 and best_m["profit_factor"] >= 1.0 and best_m["expectancy_R"] > 0:
        valid = True
    elif len(nonempty) >= 2:
        low = nonempty[0][1]
        high = nonempty[-1][1]
        if high["profit_factor"] > low["profit_factor"] and high["expectancy_R"] > low["expectancy_R"]:
            valid = True

    # Recommended min score = lower bound of best bucket if valid, else None/keep current
    rec_min = int(best_name.split("-")[0]) if valid else int(best_name.split("-")[0])

    lines = [
        "PHASE 16A Institutional Displacement Intelligence (Research Only)",
        "DATA=XAUUSD_M5_90d.parquet",
        "PATCH_APPLIED=NO",
        f"TOTAL_SETUPS_SCORED={len(rows)}",
        f"TOTAL_TRADED={len(traded)}",
        f"CSV={out_csv}",
        "",
        "SCORE_WEIGHTS: body_atr=25 range_expansion=25 close_near_extreme=15 fvg_size_atr=20 follow_through_2=15",
        "",
        "| Bucket | Trades | Win Rate | PF | Expectancy R | Max DD | Mean MFE | Mean MAE |",
        "| ------ | ------ | -------- | -- | ------------ | ------ | -------- | -------- |",
    ]
    for _lo, _hi, name in BUCKETS:
        m = bucket_stats[name]
        lines.append(
            f"| {name} | {m['trades']} | {m['win_rate']} | {m['profit_factor']} | "
            f"{m['expectancy_R']} | {m['max_drawdown_R']} | {m['mean_MFE_R']} | {m['mean_MAE_R']} |"
        )
    lines.append("")
    lines.append("PHASE_16A_RESULT")
    lines.append(f"BEST_DISPLACEMENT_BUCKET={best_name}")
    lines.append(f"BEST_PF={best_m['profit_factor']}")
    lines.append(f"BEST_EXPECTANCY_R={best_m['expectancy_R']}")
    lines.append(f"BEST_MFE_R={best_m['mean_MFE_R']}")
    lines.append(f"BEST_MAE_R={best_m['mean_MAE_R']}")
    lines.append(f"DISPLACEMENT_SCORE_VALID={'YES' if valid else 'NO'}")
    lines.append(f"RECOMMENDED_MIN_SCORE={rec_min}")

    text = "\n".join(lines) + "\n"
    out_txt = ROOT / "logs" / "phase16a_displacement_result.txt"
    out_txt.write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase16a_displacement_result.json").write_text(
        json.dumps(
            {
                "buckets": bucket_stats,
                "best_bucket": best_name,
                "valid": valid,
                "recommended_min_score": rec_min,
                "total_setups": len(rows),
                "total_traded": len(traded),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(text)
    print("WROTE", out_csv)
    print("WROTE", out_txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())