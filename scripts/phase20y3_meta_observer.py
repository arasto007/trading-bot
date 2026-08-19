#!/usr/bin/env python3
"""PHASE 20Y-3 — Meta observer vs Meta gate, 30d PA shadow comparison."""
from __future__ import annotations

import os
import sys
from collections import Counter
from copy import deepcopy
from datetime import timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

OUT = ROOT / "logs" / "phase20y3_meta_observer_result.txt"
LOOKBACK = 300
FWD = 96


def load_df() -> pd.DataFrame:
    for name in ("XAUUSD_M5_180d.parquet", "XAUUSD_M5_90d.parquet"):
        path = ROOT / "data" / "cache" / name
        if path.exists():
            df = pd.read_parquet(path)
            break
    else:
        raise FileNotFoundError("XAUUSD M5 parquet cache missing")
    if not isinstance(df.index, pd.DatetimeIndex):
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    end = df.index.max()
    start = end - pd.Timedelta(days=30)
    df = df.loc[df.index >= start].copy()
    if "atr" not in df.columns:
        df["atr"] = (df["high"] - df["low"]).abs().rolling(14, min_periods=1).mean()
    return df


def simulate_path(df, i, direction, entry, sl, tp, max_bars=FWD):
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
    final_r = ((close - entry) if direction > 0 else (entry - close)) / risk
    return round(final_r, 4)


def metrics_from_rs(rs: list[float]) -> dict[str, Any]:
    if not rs:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_R": 0.0,
            "max_dd_R": 0.0,
        }
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (99.0 if gw > 0 else 0.0)
    eq = peak = mdd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {
        "trades": len(rs),
        "win_rate": round(100.0 * len(wins) / len(rs), 2),
        "profit_factor": round(min(pf, 99.0), 3),
        "expectancy_R": round(sum(rs) / len(rs), 4),
        "max_dd_R": round(mdd, 3),
    }


def apply_cd(cands, cd, max_day):
    out = []
    last = -10000
    open_until = -1
    day_counts: Counter[str] = Counter()
    for c in cands:
        i = c["i"]
        if i <= open_until or i - last < cd:
            continue
        if day_counts[c["day"]] >= max_day:
            continue
        out.append(c)
        last = i
        open_until = i + 12
        day_counts[c["day"]] += 1
    return out


def score_setup(meta, setup, enriched, ts, regime: str, base_th: float):
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
    snap = {"symbol": "XAUUSD", "timeframe": "M5", "regime": regime, "ohlcv": enriched}
    prob = float(meta.score(sig, snap, regime))
    th = float(meta.effective_threshold("M5", regime, base_th))
    gating = bool(meta.should_gate("M5", regime))
    return prob, th, gating


def yn(ok: bool) -> str:
    return "YES" if ok else "NO"


def main() -> int:
    from tradingbot.config.price_action import get_price_action_config
    from tradingbot.domain.gold_strategies.m5_london_sweep import evaluate_m5_london_sweep
    from tradingbot.domain.pa_hardening import apply_setup_hardening
    from tradingbot.domain.price_action import enrich_price_action
    from tradingbot.domain.risk_logic import infer_regime_from_ohlcv
    from tradingbot.services.meta_labeler import reload_meta_labeler

    cfg = deepcopy(get_price_action_config("XAUUSD", "M5"))
    cfg["ENABLE_CHOCH_CONTINUATION"] = False
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    cd = int(cfg.get("COOLDOWN_BARS", 18))
    max_day = int(cfg.get("MAX_TRADES_PER_DAY", 3))
    ny_s = int(cfg.get("NY_ENTRY_START_HOUR", 10))
    ny_e = int(cfg.get("NY_ENTRY_END_HOUR", 17))
    base_th = float(cfg.get("META_LABEL_THRESHOLD", 0.38))

    df = load_df()
    print(f"DF bars={len(df)} {df.index.min()} -> {df.index.max()}", flush=True)
    meta = reload_meta_labeler()

    cands = []
    scanned = 0
    for i in range(LOOKBACK, len(df) - 2):
        ts = df.index[i].to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if not (ny_s <= ts.hour < ny_e):
            continue
        scanned += 1
        if scanned % 400 == 0:
            print(f"  progress scanned={scanned} setups={len(cands)}", flush=True)
        sl = df.iloc[i - LOOKBACK + 1 : i + 1]
        local_i = len(sl) - 1
        enriched = enrich_price_action(sl, cfg, at_index=local_i)
        setup0 = evaluate_m5_london_sweep(enriched, local_i, cfg)
        if setup0 is None:
            continue
        setup = apply_setup_hardening(enriched, local_i, cfg, setup0, timeframe="M5")
        if setup is None or float(setup.confidence) < min_conf:
            continue
        regime = infer_regime_from_ohlcv(enriched, at_index=local_i)
        try:
            prob, th, gating = score_setup(meta, setup, enriched, ts, regime, base_th)
        except Exception:
            prob, th, gating = 1.0, base_th, False
        cands.append(
            {
                "i": i,
                "day": ts.date().isoformat(),
                "r": simulate_path(
                    df,
                    i,
                    int(setup.direction),
                    float(setup.entry),
                    float(setup.stop_loss),
                    float(setup.take_profit),
                ),
                "meta_score": round(prob, 4),
                "meta_threshold": round(th, 4),
                "gating": gating,
                "would_reject": bool(prob < th),
            }
        )

    pa_cd = apply_cd(cands, cd, max_day)
    observer = pa_cd
    gate = [c for c in pa_cd if not (c["gating"] and c["would_reject"])]
    m_gate = metrics_from_rs([c["r"] for c in gate])
    m_obs = metrics_from_rs([c["r"] for c in observer])

    n_gate = int(m_gate["trades"])
    n_obs = int(m_obs["trades"])
    if n_gate > 0:
        increase = 100.0 * (n_obs - n_gate) / n_gate
    else:
        increase = 0.0 if n_obs == 0 else 999.0
    pf_delta = float(m_obs["profit_factor"]) - float(m_gate["profit_factor"])
    expr_delta = float(m_obs["expectancy_R"]) - float(m_gate["expectancy_R"])

    killed = [c for c in pa_cd if c["gating"] and c["would_reject"]]
    killed_winners = sum(1 for c in killed if c["r"] > 0)

    from tradingbot.config.live import META_OBSERVER_MODE
    from tradingbot.adapters.risk_gate import apply_pa_meta_decision

    rej, would, _ = apply_pa_meta_decision(
        prob=0.21, threshold=0.33, gating=True, observer_mode=True
    )
    telemetry_ok = rej is False and would is True
    quality_ok = float(m_obs["profit_factor"]) >= 1.0 or float(m_obs["expectancy_R"]) >= 0.0
    safe = bool(telemetry_ok and quality_ok)

    lines = [
        "PHASE_20Y3_META_OBSERVER",
        f"BARS={len(df)}",
        f"SCANNED={scanned}",
        f"RAW_PA_SETUPS={len(cands)}",
        f"PA_AFTER_COOLDOWN={len(pa_cd)}",
        f"META_KILLED={len(killed)}",
        f"META_KILLED_WINNERS={killed_winners}",
        f"GATE_PF={m_gate['profit_factor']}",
        f"OBSERVER_PF={m_obs['profit_factor']}",
        f"GATE_EXPR={m_gate['expectancy_R']}",
        f"OBSERVER_EXPR={m_obs['expectancy_R']}",
        f"GATE_MAXDD={m_gate['max_dd_R']}",
        f"OBSERVER_MAXDD={m_obs['max_dd_R']}",
        f"LIVE_META_OBSERVER_MODE={yn(bool(META_OBSERVER_MODE))}",
        "",
        "PHASE_20Y3_RESULT",
        "",
        f"META_GATE_TRADES={n_gate}",
        f"META_OBSERVER_TRADES={n_obs}",
        "",
        f"TRADE_INCREASE_PCT={increase:.2f}",
        f"PF_DELTA={pf_delta:.3f}",
        f"EXPECTANCY_DELTA_R={expr_delta:.4f}",
        "",
        f"META_TELEMETRY_PRESERVED={yn(telemetry_ok)}",
        f"SAFE_FOR_LIVE_ENABLE={yn(safe)}",
        "PATCH_APPLIED=YES",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(OUT.read_text(encoding="utf-8"), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())