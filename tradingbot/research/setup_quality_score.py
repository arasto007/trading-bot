"""PHASE 15A — Institutional Setup Quality Score (research only).

NO live routing / execution / config changes.
Score components (total 100):
  Sweep Quality ............. 0-20
  Displacement Strength ..... 0-25
  FVG Quality ............... 0-20
  Order Block Quality ....... 0-15
  HTF Bias Alignment ........ 0-10
  Premium/Discount Position . 0-10
"""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]

BUCKETS = (
    (50, 60, "50-60"),
    (60, 70, "60-70"),
    (70, 80, "70-80"),
    (80, 90, "80-90"),
    (90, 101, "90-100"),
)


@dataclass
class SetupScoreBreakdown:
    sweep_quality: float
    displacement_strength: float
    fvg_quality: float
    order_block_quality: float
    htf_bias_alignment: float
    premium_discount: float

    @property
    def total(self) -> float:
        return round(
            self.sweep_quality
            + self.displacement_strength
            + self.fvg_quality
            + self.order_block_quality
            + self.htf_bias_alignment
            + self.premium_discount,
            2,
        )


def _atr_at(df: pd.DataFrame, i: int) -> float:
    if "atr" in df.columns and not pd.isna(df["atr"].iloc[i]):
        v = float(df["atr"].iloc[i])
        if v > 0:
            return v
    row = df.iloc[i]
    return max(float(row["high"]) - float(row["low"]), 1e-9)


def score_sweep_quality(
    df: pd.DataFrame,
    i: int,
    direction: int,
    *,
    asian_hi: float | None = None,
    asian_lo: float | None = None,
    sweep_side: str | None = None,
) -> float:
    """0-20: liquidity / asian sweep depth + reclaim quality."""
    from tradingbot.domain.price_action import _liquidity_sweep

    swings = df.attrs.get("pa_swings", [])
    atr = _atr_at(df, i)
    score = 0.0

    if asian_hi is not None and asian_lo is not None and sweep_side:
        lookback = 12
        start = max(0, i - lookback)
        window = df.iloc[start : i + 1]
        win_high = float(window["high"].max())
        win_low = float(window["low"].min())
        price = float(df["close"].iloc[i])
        if sweep_side == "high" and direction < 0:
            depth = max(0.0, win_high - asian_hi) / atr
            score += 8.0
            score += min(6.0, depth * 4.0)
            if asian_lo < price < asian_hi:
                score += 6.0
        elif sweep_side == "low" and direction > 0:
            depth = max(0.0, asian_lo - win_low) / atr
            score += 8.0
            score += min(6.0, depth * 4.0)
            if asian_lo < price < asian_hi:
                score += 6.0

    sw = _liquidity_sweep(df, swings, i) if swings else None
    if sw == direction:
        score = max(score, 12.0)
        score = min(20.0, score + 4.0)
    elif sw is not None and score < 6.0:
        score = max(score, 4.0)

    return float(max(0.0, min(20.0, round(score, 2))))


def score_displacement_strength(df: pd.DataFrame, i: int, direction: int) -> float:
    """0-25: impulse body / ATR in setup direction (1-3 bars)."""
    atr = _atr_at(df, i)
    best = 0.0
    for n in (1, 2, 3):
        start = max(0, i - n + 1)
        body = 0.0
        for j in range(start, i + 1):
            o = float(df["open"].iloc[j])
            c = float(df["close"].iloc[j])
            signed = c - o
            if direction > 0:
                body += max(0.0, signed)
            else:
                body += max(0.0, -signed)
        best = max(best, body / atr)

    if best <= 0:
        return 0.0
    score = min(25.0, best * 25.0)
    return float(round(score, 2))


def score_fvg_quality(df: pd.DataFrame, i: int, direction: int, price: float) -> float:
    """0-20: presence, fill-zone touch, freshness."""
    fvgs = df.attrs.get("pa_fvgs", []) or []
    best = 0.0
    for gap in reversed(fvgs):
        if gap.direction != direction:
            continue
        if gap.index > i or gap.index < i - 40:
            continue
        s = 8.0
        age = i - gap.index
        if age <= 8:
            s += 5.0
        elif age <= 20:
            s += 2.5
        if gap.bottom <= price <= gap.top:
            s += 7.0
        elif direction > 0 and price <= gap.top + (_atr_at(df, i) * 0.15):
            s += 3.0
        elif direction < 0 and price >= gap.bottom - (_atr_at(df, i) * 0.15):
            s += 3.0
        best = max(best, min(20.0, s))
    return float(round(best, 2))


def score_order_block_quality(df: pd.DataFrame, i: int, direction: int, price: float) -> float:
    """0-15: price inside matching OB + freshness."""
    obs = df.attrs.get("pa_obs", []) or []
    best = 0.0
    for ob in reversed(obs):
        if ob.direction != direction:
            continue
        if ob.index > i or ob.index < i - 40:
            continue
        s = 0.0
        if ob.bottom <= price <= ob.top:
            s = 10.0
            age = i - ob.index
            if age <= 10:
                s += 5.0
            elif age <= 25:
                s += 2.5
        else:
            atr = _atr_at(df, i)
            if abs(price - ob.top) <= atr * 0.2 or abs(price - ob.bottom) <= atr * 0.2:
                s = 5.0
        best = max(best, min(15.0, s))
    return float(round(best, 2))


def score_htf_bias_alignment(htf_bias: int, direction: int) -> float:
    """0-10: H4 (or resampled) bias vs setup direction."""
    if htf_bias == 0:
        return 5.0
    if htf_bias == direction:
        return 10.0
    return 0.0


def score_premium_discount(df: pd.DataFrame, i: int, direction: int) -> float:
    """0-10: buy discount / sell premium."""
    from tradingbot.domain.price_action import price_zone

    zone = price_zone(df, i, lookback=50)
    if direction > 0:
        if zone == "discount":
            return 10.0
        if zone == "equilibrium":
            return 5.0
        return 0.0
    if direction < 0:
        if zone == "premium":
            return 10.0
        if zone == "equilibrium":
            return 5.0
        return 0.0
    return 0.0


def compute_setup_score(
    df: pd.DataFrame,
    i: int,
    *,
    direction: int,
    price: float,
    htf_bias: int = 0,
    asian_hi: float | None = None,
    asian_lo: float | None = None,
    sweep_side: str | None = None,
) -> SetupScoreBreakdown:
    """Compute institutional research score for one setup bar."""
    return SetupScoreBreakdown(
        sweep_quality=score_sweep_quality(
            df, i, direction, asian_hi=asian_hi, asian_lo=asian_lo, sweep_side=sweep_side
        ),
        displacement_strength=score_displacement_strength(df, i, direction),
        fvg_quality=score_fvg_quality(df, i, direction, price),
        order_block_quality=score_order_block_quality(df, i, direction, price),
        htf_bias_alignment=score_htf_bias_alignment(htf_bias, direction),
        premium_discount=score_premium_discount(df, i, direction),
    )


def resample_htf_bias_series(m5: pd.DataFrame, rule: str = "4h") -> pd.Series:
    """Map each M5 bar timestamp to HTF bias from resampled OHLC."""
    from tradingbot.domain.htf_bias import trend_to_bias
    from tradingbot.domain.price_action import find_swings, infer_trend

    ohlc = (
        m5.resample(rule, label="right", closed="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )
    if len(ohlc) < 60:
        return pd.Series(0, index=m5.index, dtype=int)

    biases: list[int] = []
    for k in range(len(ohlc)):
        if k < 30:
            biases.append(0)
            continue
        window = ohlc.iloc[max(0, k - 80) : k + 1]
        swings = find_swings(window, 2, 2)
        biases.append(trend_to_bias(infer_trend(swings)))

    htf = pd.Series(biases, index=ohlc.index, dtype=int)
    aligned = htf.reindex(m5.index, method="ffill").fillna(0).astype(int)
    return aligned


def bucket_label(score: float) -> str | None:
    for lo, hi, name in BUCKETS:
        if lo <= score < hi:
            return name
    return None


def simulate_r(df, i, direction, entry, sl, tp, max_bars=96) -> float:
    risk = abs(entry - sl)
    if risk <= 0:
        return 0.0
    end = min(len(df), i + 1 + max_bars)
    for j in range(i + 1, end):
        hi = float(df["high"].iloc[j])
        lo = float(df["low"].iloc[j])
        if direction > 0:
            if lo <= sl:
                return round((sl - entry) / risk, 4)
            if hi >= tp:
                return round((tp - entry) / risk, 4)
        else:
            if hi >= sl:
                return round((entry - sl) / risk, 4)
            if lo <= tp:
                return round((entry - tp) / risk, 4)
    close = float(df["close"].iloc[end - 1])
    return round(((close - entry) if direction > 0 else (entry - close)) / risk, 4)


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "max_dd": 0.0,
        }
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (999.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(rs),
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
        "profit_factor": round(pf, 3) if pf < 999 else 999.0,
        "expectancy": round(sum(rs) / len(rs), 4),
        "max_dd": round(mdd, 3),
    }


def load_m5_90d() -> pd.DataFrame:
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


def run_phase15a(*, lookback: int = 500) -> dict[str, Any]:
    """Replay historical london_sweep setups, score, export CSV + bucket stats."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)

    from tradingbot.config.dotenv_loader import load_dotenv

    load_dotenv()

    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
    from tradingbot.domain.pa_hardening import apply_setup_hardening
    from tradingbot.domain.price_action import enrich_price_action

    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    df = load_m5_90d()
    print(f"DF bars={len(df)} building HTF bias...", flush=True)
    htf_bias_s = resample_htf_bias_series(df)

    ny_s = int(cfg.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg.get("NY_ENTRY_END_HOUR", 17))
    cd = int(cfg.get("COOLDOWN_BARS", 18))
    max_day = int(cfg.get("MAX_TRADES_PER_DAY", 3))

    rows: list[dict[str, Any]] = []
    scanned = 0

    for i in range(lookback, len(df)):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if not (ny_s <= ts.hour < ny_e):
            continue
        scanned += 1
        if scanned % 1500 == 0:
            print(f"progress={scanned} setups={len(rows)}", flush=True)

        sl = df.iloc[i - lookback + 1 : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, cfg, at_index=local_i)
        setup0 = evaluate_m5_london_sweep(enriched, local_i, cfg)
        if setup0 is None:
            continue
        setup = apply_setup_hardening(enriched, local_i, cfg, setup0, timeframe="M5")
        if setup is None:
            continue

        meta = dict(setup.metadata or {})
        htf = int(htf_bias_s.iloc[i]) if i < len(htf_bias_s) else 0
        br = compute_setup_score(
            enriched,
            local_i,
            direction=int(setup.direction),
            price=float(setup.entry),
            htf_bias=htf,
            asian_hi=meta.get("asian_high"),
            asian_lo=meta.get("asian_low"),
            sweep_side=meta.get("sweep_side"),
        )
        r_mult = simulate_r(
            df,
            i,
            int(setup.direction),
            float(setup.entry),
            float(setup.stop_loss),
            float(setup.take_profit),
        )
        bkt = bucket_label(br.total)
        rows.append(
            {
                "timestamp": ts.isoformat(),
                "bar_index": i,
                "direction": int(setup.direction),
                "entry": float(setup.entry),
                "stop_loss": float(setup.stop_loss),
                "take_profit": float(setup.take_profit),
                "sweep_quality": br.sweep_quality,
                "displacement_strength": br.displacement_strength,
                "fvg_quality": br.fvg_quality,
                "order_block_quality": br.order_block_quality,
                "htf_bias_alignment": br.htf_bias_alignment,
                "premium_discount": br.premium_discount,
                "setup_score": br.total,
                "score_bucket": bkt or "below_50",
                "htf_bias": htf,
                "r_multiple": r_mult,
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

    out_csv = ROOT / "logs" / "phase15a_setup_scores.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "timestamp",
        "bar_index",
        "direction",
        "entry",
        "stop_loss",
        "take_profit",
        "sweep_quality",
        "displacement_strength",
        "fvg_quality",
        "order_block_quality",
        "htf_bias_alignment",
        "premium_discount",
        "setup_score",
        "score_bucket",
        "htf_bias",
        "r_multiple",
        "day",
        "traded",
    ]
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    bucket_stats: dict[str, Any] = {}
    for _lo, _hi, name in BUCKETS:
        rs = [r["r_multiple"] for r in traded if r.get("score_bucket") == name]
        bucket_stats[name] = metrics_from_rs(rs)

    best_name = None
    best_key = (-1e9, -1e9, -1e9)
    for name, m in bucket_stats.items():
        if m["trades"] <= 0:
            continue
        key = (m["profit_factor"], m["expectancy"], m["win_rate"])
        if key > best_key:
            best_key = key
            best_name = name
    if best_name is None:
        best_name = "50-60"
        best_m = bucket_stats[best_name]
    else:
        best_m = bucket_stats[best_name]

    result = {
        "total_setups_scored": len(rows),
        "total_traded": len(traded),
        "buckets": bucket_stats,
        "best_score_bucket": best_name,
        "best_pf": best_m["profit_factor"],
        "best_expectancy": best_m["expectancy"],
        "best_winrate": best_m["win_rate"],
        "csv": str(out_csv),
    }

    lines = [
        "PHASE 15A Institutional Setup Quality Score (Research Only)",
        "DATA=XAUUSD_M5_90d.parquet",
        "PATCH_APPLIED=NO",
        f"TOTAL_SETUPS_SCORED={len(rows)}",
        f"TOTAL_TRADED={len(traded)}",
        f"CSV={out_csv}",
        "",
        "| Bucket | Trades | Win Rate | PF | Expectancy | Max DD |",
        "| ------ | ------ | -------- | -- | ---------- | ------ |",
    ]
    for _lo, _hi, name in BUCKETS:
        m = bucket_stats[name]
        lines.append(
            f"| {name} | {m['trades']} | {m['win_rate']} | {m['profit_factor']} | "
            f"{m['expectancy']} | {m['max_dd']} |"
        )
    lines.append("")
    lines.append("PHASE_15A_RESULT")
    lines.append(f"BEST_SCORE_BUCKET={best_name}")
    lines.append(f"BEST_PF={best_m['profit_factor']}")
    lines.append(f"BEST_EXPECTANCY={best_m['expectancy']}")
    lines.append(f"BEST_WINRATE={best_m['win_rate']}")

    text = "\n".join(lines) + "\n"
    out_txt = ROOT / "logs" / "phase15a_setup_quality.txt"
    out_txt.write_text(text, encoding="utf-8")
    (ROOT / "logs" / "phase15a_setup_quality.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(text)
    print("WROTE", out_csv)
    print("WROTE", out_txt)
    return result


if __name__ == "__main__":
    raise SystemExit(0 if run_phase15a() else 1)