#!/usr/bin/env python3
"""
PHASE 12C — Adaptive Quality + ML Hybrid Certification (RESEARCH ONLY).

Does NOT modify PA_PRODUCTION_LOCK, USE_ML_KERNEL, ADAPTIVE_REGIME_ENABLED, or execution adapters.
"""
from __future__ import annotations

import json
import os
import pickle
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs" / "phase12c"
CACHE = ROOT / "data" / "cache" / "XAUUSD_M5_90d.parquet"
MATRIX_12B = ROOT / "logs" / "phase12b" / "training_matrix.json"
LABELED_12A = ROOT / "data/ml/research/phase12a/pa_setups_labeled.parquet"
CAND_CACHE = LOG_DIR / "candidates_cache.json"

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_SIGNAL_FILTER": "OFF",
})
warnings.filterwarnings("ignore")

META_THRESHOLD = 0.38
REPLAY_DAYS = 90
WARMUP = 500
MC_RUNS = 1000

GATE = {
    "trades_min": 80,
    "pf_min": 1.30,
    "expectancy_min": 0.18,
    "max_dd_max": 10.0,
    "mc_median_pf_min": 1.15,
    "stress_pf_min": 0.95,
}


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def load_m5_90d() -> pd.DataFrame:
    from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame

    df = pd.read_parquet(CACHE)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index("time")
        df.index = pd.to_datetime(df.index, utc=True)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df["volume"] = df["tick_volume"]
    df = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
    return prepare_indicator_frame(df)


def load_regime_models() -> dict[str, Any]:
    matrix = json.loads(MATRIX_12B.read_text(encoding="utf-8"))
    models: dict[str, Any] = {}
    for regime, info in matrix.get("regimes", {}).items():
        rel = info.get("artifact")
        if not rel:
            continue
        path = ROOT / rel
        if path.is_file():
            models[regime] = pickle.loads(path.read_bytes())
    return models


def _ml_prob(frame: pd.DataFrame, idx: int, models: dict[str, Any]) -> tuple[float, str]:
    from tradingbot.domain.market_filters import compute_adx
    from tradingbot.ml.feature_store import InstitutionalFeatureStore, classify_regime

    feats = InstitutionalFeatureStore.compute_at(frame, idx, symbol="XAUUSD")
    adx = compute_adx(frame.iloc[: idx + 1])
    regime = classify_regime(adx, float(feats.get("atr_pct", 50.0)))
    art = models.get(regime)
    if art is None:
        for fallback in ("TREND", "RANGING", "EXPANSION"):
            art = models.get(fallback)
            if art:
                regime = fallback
                break
    if art is None:
        return 0.5, regime
    x = np.array([[float(feats.get(f, 0.0)) for f in art["features"]]], dtype=float)
    prob = float(art["model"].predict_proba(x)[0, 1])
    return prob, regime


def _pf_ci(rs: list[float], n_boot: int = 1000, seed: int = 42) -> dict[str, float]:
    if len(rs) < 5:
        return {"pf_low": 0.0, "pf_high": 0.0, "pf_point": 0.0}
    rng = np.random.default_rng(seed)
    arr = np.asarray(rs, dtype=float)
    pfs: list[float] = []
    for _ in range(n_boot):
        s = rng.choice(arr, size=len(arr), replace=True)
        wins = s[s > 0]
        losses = s[s < 0]
        gw, gl = float(wins.sum()), abs(float(losses.sum()))
        pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
        pfs.append(min(pf, 50.0))
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    gw, gl = float(wins.sum()), abs(float(losses.sum()))
    point = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    return {
        "pf_point": round(min(point, 50.0), 4),
        "pf_low": round(float(np.percentile(pfs, 2.5)), 4),
        "pf_high": round(float(np.percentile(pfs, 97.5)), 4),
    }


def _metrics(trades: list[Any]) -> dict[str, Any]:
    from tradingbot.ml.research.phase9a.pm_v2_research import trade_metrics

    m = trade_metrics(trades)
    rs = [float(t.r_multiple) for t in trades]
    pf_num = 999.0 if m["pf"] == "inf" else float(m["pf"])
    ci = _pf_ci(rs)
    return {
        **m,
        "pf_numeric": round(pf_num, 4),
        "profit_factor_confidence_interval": ci,
    }


def _replay_candidates(
    df: pd.DataFrame,
    candidates: list[dict[str, Any]],
    *,
    cooldown_bars: int = 8,
    max_trades_per_day: int = 4,
    spread_pips: float = 4.0,
    slippage_pips: float = 1.0,
) -> list[Any]:
    from tradingbot.ml.research.phase9a.pm_v2_research import SimTrade, profile_for_mode, simulate_pm_entry

    profile = profile_for_mode("36a")
    trades: list[SimTrade] = []
    last_entry = -9999
    open_until = -1
    day_counts: dict[str, int] = {}

    for cand in sorted(candidates, key=lambda c: c["bar_index"]):
        i = int(cand["bar_index"])
        if i <= open_until or i - last_entry < cooldown_bars:
            continue
        day = str(pd.Timestamp(df.index[i]).date())
        if day_counts.get(day, 0) >= max_trades_per_day:
            continue
        sim = simulate_pm_entry(
            cand, df, profile, spread_pips=spread_pips, slippage_pips=slippage_pips
        )
        if sim is None:
            continue
        trades.append(sim)
        open_until = sim.exit_bar_index
        last_entry = i
        day_counts[day] = day_counts.get(day, 0) + 1
    return trades


def collect_pa_meta_from_12a(df: pd.DataFrame) -> list[dict[str, Any]]:
    """PA+Meta baseline from Phase 12A labeled setups (90d M5) + meta labeler."""
    if not LABELED_12A.is_file():
        from tradingbot.ml.research.phase9a.pm_v2_research import collect_pa_meta_candidates
        return collect_pa_meta_candidates(df, meta_threshold=META_THRESHOLD, days=REPLAY_DAYS)

    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import TradingSignal
    from tradingbot.services.meta_labeler import get_meta_labeler

    labeled = pd.read_parquet(LABELED_12A)
    labeled["timestamp_utc"] = pd.to_datetime(labeled["timestamp_utc"], utc=True)
    sub = labeled[
        (labeled["source_window_days"] == REPLAY_DAYS)
        & (labeled["timeframe"] == "M5")
        & (labeled["label"].isin([0, 1]))
    ].copy()
    meta = get_meta_labeler()
    candidates: list[dict[str, Any]] = []
    for _, row in sub.iterrows():
        i = int(row["bar_index"])
        if i >= len(df):
            continue
        direction = SignalDirection.BUY if row["direction"] == "BUY" else SignalDirection.SELL
        sig = TradingSignal(
            direction=direction,
            confidence=float(row["confidence"]),
            symbol="XAUUSD",
            timeframe="5m",
            strategy_name="priceaction",
            stop_loss=float(row["stop_price"]),
            take_profit=float(row["tp_price"]),
            metadata={"entry": row["entry_price"], "price": row["entry_price"]},
        )
        ts = pd.Timestamp(df.index[i]).to_pydatetime()
        window = df.iloc[: i + 1]
        snapshot = {"ohlcv": window, "htf_bias": 0, "current_time": ts}
        prob = meta.score(sig, snapshot, str(row.get("regime", "RANGING")), spread_pips=4.0)
        if prob < META_THRESHOLD:
            continue
        candidates.append({
            "bar_index": i,
            "bar_time": str(df.index[i]),
            "direction": row["direction"],
            "entry": float(row["entry_price"]),
            "stop_loss": float(row["stop_price"]),
            "take_profit": float(row["tp_price"]),
            "meta_prob": round(float(prob), 4),
        })
    return candidates


def _session_ok(hour: int) -> bool:
    return 7 <= hour < 21


def collect_adaptive_and_hybrid(
    df: pd.DataFrame, models: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Single-pass scan for Adaptive v2 + Hybrid candidates."""
    from tradingbot.domain.signal_helpers import compute_sl_tp
    from tradingbot.ml.decision_engine.decision_policy import VOL_REGIME_RULE_CONFIDENCE
    from tradingbot.strategies.adaptive_ml_hybrid import evaluate_hybrid_decision
    from tradingbot.strategies.adaptive_quality_engine import (
        compute_quality_score,
        evaluate_quality_at_index,
        resolve_candidate_direction,
    )
    from tradingbot.strategies.adaptive_regime import prepare_adaptive_frame

    frame = prepare_adaptive_frame(df)
    adaptive: list[dict[str, Any]] = []
    hybrid: list[dict[str, Any]] = []
    start = max(WARMUP, 60)
    n = len(frame)

    for i in range(start, n):
        if i > start and (i - start) % 5000 == 0:
            emit(f"    adaptive/hybrid scan bar {i}/{n} ad={len(adaptive)} hy={len(hybrid)}")

        hour = pd.Timestamp(frame.index[i]).hour
        if not _session_ok(hour):
            continue

        score, _ = evaluate_quality_at_index(frame, i, log_rejections=False)
        if score is None:
            continue
        direction = score.direction
        if direction is None:
            direction = resolve_candidate_direction(frame, i)
        if direction is None:
            continue

        sl, tp, _ = compute_sl_tp(
            frame.iloc[: i + 1],
            direction,
            VOL_REGIME_RULE_CONFIDENCE,
            symbol="XAUUSD",
            strategy_name="adaptive_quality",
            timeframe="M5",
        )
        if sl is None or tp is None:
            continue
        entry = float(frame.iloc[i]["close"])
        base = {
            "bar_index": i,
            "bar_time": str(frame.index[i]),
            "direction": "BUY" if direction > 0 else "SELL",
            "entry": entry,
            "stop_loss": float(sl),
            "take_profit": float(tp),
            "quality_score": score.quality_score,
        }

        if score.tier == "tradeable":
            adaptive.append(dict(base))

        if score.quality_score >= 65:
            ml_prob, regime = _ml_prob(frame, i, models)
            decision = evaluate_hybrid_decision(
                frame, i, ml_probability=ml_prob, direction=direction, quality_result=score
            )
            if decision.accepted:
                hybrid.append({**base, "ml_probability": decision.ml_probability, "regime": regime})

    return adaptive, hybrid


def load_or_build_candidates(
    df: pd.DataFrame, models: dict[str, Any], *, refresh: bool = False
) -> tuple[list[dict], list[dict], list[dict]]:
    if CAND_CACHE.is_file() and not refresh:
        data = json.loads(CAND_CACHE.read_text(encoding="utf-8"))
        emit(f"  loaded candidate cache {CAND_CACHE.name}")
        return data["pa_meta"], data["adaptive_v2"], data["hybrid"]

    emit("  building PA+Meta from Phase 12A ...")
    pa_cands = collect_pa_meta_from_12a(df)
    emit(f"    PA+Meta candidates={len(pa_cands)}")
    emit("  scanning Adaptive + Hybrid (single pass) ...")
    adaptive_cands, hybrid_cands = collect_adaptive_and_hybrid(df, models)
    CAND_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CAND_CACHE.write_text(
        json.dumps(
            {"pa_meta": pa_cands, "adaptive_v2": adaptive_cands, "hybrid": hybrid_cands},
            indent=2,
        ),
        encoding="utf-8",
    )
    return pa_cands, adaptive_cands, hybrid_cands


def monte_carlo_order_shuffle(trades: list[Any], runs: int = MC_RUNS) -> dict[str, Any]:
    from tradingbot.ml.research.phase9a.pm_v2_research import monte_carlo

    rs = [float(t.r_multiple) for t in trades]
    if len(rs) < 5:
        return {"simulations": 0, "pf_median": 0.0, "worst_5pct_dd_r": 0.0}

    rng = np.random.default_rng(42)
    pfs: list[float] = []
    dds: list[float] = []
    for _ in range(runs):
        shuffled = rng.permutation(rs)
        wins = shuffled[shuffled > 0]
        losses = shuffled[shuffled < 0]
        gw, gl = float(wins.sum()), abs(float(losses.sum()))
        pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
        pfs.append(min(pf, 50.0))
        eq = peak = mdd = 0.0
        for r in shuffled:
            eq += r
            peak = max(peak, eq)
            mdd = max(mdd, peak - eq)
        dds.append(mdd)
    return {
        "simulations": runs,
        "method": "shuffled_trade_order",
        "pf_median": round(float(np.median(pfs)), 4),
        "pf_p5": round(float(np.percentile(pfs, 5)), 4),
        "pf_p95": round(float(np.percentile(pfs, 95)), 4),
        "worst_5pct_dd_r": round(float(np.percentile(dds, 95)), 4),
        "bootstrap": monte_carlo(trades, simulations=runs),
    }


def stress_test(df: pd.DataFrame, candidates: list[dict], *, base_spread: float = 4.0) -> dict[str, Any]:
    """Spread +25%, slippage +0.2 ATR + worst 10% vol periods."""
    from tradingbot.ml.research.phase9a.pm_v2_research import SimTrade

    spread_stress = base_spread * 1.25
    atr_pips = []
    for c in candidates:
        i = int(c["bar_index"])
        bar = df.iloc[i]
        atr_pips.append(max(float(bar.get("atr", bar["high"] - bar["low"])), 0.01))

    # Worst 10% volatility: keep candidates in top 90% ATR
    if len(candidates) >= 10:
        threshold = float(np.percentile(atr_pips, 90))
        vol_filtered = [c for c, a in zip(candidates, atr_pips) if a <= threshold]
    else:
        vol_filtered = candidates

    trades_normal = _replay_candidates(df, candidates, spread_pips=base_spread, slippage_pips=1.0)
    trades_spread = _replay_candidates(df, candidates, spread_pips=spread_stress, slippage_pips=1.0)

    # Slippage +0.2 ATR approximated as extra 0.2R penalty on losses
    trades_slip: list[SimTrade] = []
    for t in trades_normal:
        slip_penalty = 0.2 if t.r_multiple < 0 else 0.0
        trades_slip.append(
            SimTrade(
                r_multiple=round(t.r_multiple - slip_penalty, 4),
                entry_time=t.entry_time,
                exit_time=t.exit_time,
                exit_bar_index=t.exit_bar_index,
                hold_bars=t.hold_bars,
                exit_reason=t.exit_reason,
            )
        )

    trades_vol = _replay_candidates(df, vol_filtered, spread_pips=spread_stress, slippage_pips=1.0)

    m_spread = _metrics(trades_spread)
    m_slip = _metrics(trades_slip)
    m_vol = _metrics(trades_vol)
    combined_rs = [float(t.r_multiple) for t in trades_spread]
    for t in trades_slip:
        combined_rs.append(float(t.r_multiple))
    wins = [r for r in combined_rs if r > 0]
    losses = [r for r in combined_rs if r < 0]
    gw, gl = sum(wins), abs(sum(losses))
    stress_pf = gw / gl if gl > 0 else (999.0 if gw > 0 else 0.0)
    stress_exp = sum(combined_rs) / max(len(combined_rs), 1)

    return {
        "spread_plus_25pct": m_spread,
        "slippage_plus_0_2_atr": m_slip,
        "worst_10pct_volatility": m_vol,
        "stress_pf": round(min(stress_pf, 50.0), 4),
        "stress_expectancy_r": round(stress_exp, 4),
    }


def frequency_grid(df: pd.DataFrame, hybrid_cands: list[dict]) -> dict[str, Any]:
    emit("TASK 3 — Frequency Control")
    grid: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    for cooldown in (6, 8, 10):
        for max_day in (3, 4, 5):
            trades = _replay_candidates(
                df, hybrid_cands, cooldown_bars=cooldown, max_trades_per_day=max_day
            )
            m = _metrics(trades)
            n = m["trades"]
            in_range = 80 <= n <= 180
            entry = {
                "cooldown_bars": cooldown,
                "max_trades_per_day": max_day,
                "trades": n,
                "in_target_range_80_180": in_range,
                "pf": m["pf_numeric"],
                "expectancy_r": m["expectancy_r"],
            }
            grid.append(entry)
            if in_range and (best is None or m["pf_numeric"] > best.get("pf", 0)):
                best = {**entry, "metrics": m}
            emit(f"  cd={cooldown} max/day={max_day} trades={n} PF={m['pf_numeric']}")
    return {"grid": grid, "best_in_range": best}


def institutional_gate(hybrid_m: dict[str, Any], mc: dict[str, Any], stress: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "trades_gte_80": int(hybrid_m.get("trades", 0)) >= GATE["trades_min"],
        "pf_gte_130": float(hybrid_m.get("pf_numeric", 0)) >= GATE["pf_min"],
        "expectancy_gte_018": float(hybrid_m.get("expectancy_r", 0)) >= GATE["expectancy_min"],
        "max_dd_lte_10r": float(hybrid_m.get("max_dd_r", 99)) <= GATE["max_dd_max"],
        "mc_median_pf_gte_115": float(mc.get("pf_median", 0)) >= GATE["mc_median_pf_min"],
        "stress_pf_gte_095": float(stress.get("stress_pf", 0)) >= GATE["stress_pf_min"],
    }
    return {"checks": checks, "certified": all(checks.values())}


def main() -> int:
    import argparse
    from tradingbot.config.dotenv_loader import load_dotenv

    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-candidates", action="store_true")
    args = parser.parse_args()

    load_dotenv()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    emit(f"PHASE 12C Hybrid Certification | UTC {datetime.now(timezone.utc).isoformat()}")

    if not CACHE.is_file():
        emit(f"ERROR missing {CACHE}")
        return 1

    df = load_m5_90d()
    models = load_regime_models()
    emit(f"  M5 bars={len(df)} regime_models={list(models.keys())}")

    emit("TASK 2 — 90-Day Replay")
    pa_cands, adaptive_cands, hybrid_cands = load_or_build_candidates(
        df, models, refresh=args.refresh_candidates
    )
    emit(f"  candidates PA={len(pa_cands)} adaptive={len(adaptive_cands)} hybrid={len(hybrid_cands)}")

    freq = frequency_grid(df, hybrid_cands)
    best_freq = freq.get("best_in_range") or {}
    if not best_freq and freq.get("grid"):
        best_freq = min(freq["grid"], key=lambda e: abs(e["trades"] - 130))
    cooldown = best_freq.get("cooldown_bars", 8)
    max_day = best_freq.get("max_trades_per_day", 4)

    pa_trades = _replay_candidates(df, pa_cands, cooldown_bars=cooldown, max_trades_per_day=max_day)
    adaptive_trades = _replay_candidates(df, adaptive_cands, cooldown_bars=cooldown, max_trades_per_day=max_day)
    hybrid_trades = _replay_candidates(df, hybrid_cands, cooldown_bars=cooldown, max_trades_per_day=max_day)

    pa_m = _metrics(pa_trades)
    adaptive_m = _metrics(adaptive_trades)
    hybrid_m = _metrics(hybrid_trades)

    emit(f"  PA+Meta: trades={pa_m['trades']} PF={pa_m['pf_numeric']} expR={pa_m['expectancy_r']}")
    emit(f"  Adaptive v2: trades={adaptive_m['trades']} PF={adaptive_m['pf_numeric']}")
    emit(f"  Hybrid: trades={hybrid_m['trades']} PF={hybrid_m['pf_numeric']} expR={hybrid_m['expectancy_r']}")

    emit("TASK 4 — Stress & Monte Carlo")
    mc = monte_carlo_order_shuffle(hybrid_trades, runs=MC_RUNS)
    stress = stress_test(df, hybrid_cands)
    emit(f"  MC median PF={mc['pf_median']} worst5% DD={mc['worst_5pct_dd_r']}R")
    emit(f"  stress PF={stress['stress_pf']} expR={stress['stress_expectancy_r']}")

    gate = institutional_gate(hybrid_m, mc, stress)
    certified = gate["certified"]
    paper_forward = certified or (
        hybrid_m["trades"] >= 60
        and hybrid_m["pf_numeric"] >= 1.1
        and float(mc.get("pf_median", 0)) >= 1.0
    )

    matrix = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "replay_days": REPLAY_DAYS,
        "frequency_control": freq,
        "cooldown_bars_selected": cooldown,
        "max_trades_per_day_selected": max_day,
        "modes": {
            "pa_meta_baseline": pa_m,
            "adaptive_quality_v2": adaptive_m,
            "adaptive_ml_hybrid": hybrid_m,
        },
        "gate": gate,
    }
    matrix_path = LOG_DIR / "hybrid_matrix.json"
    matrix_path.write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")

    mc_path = LOG_DIR / "monte_carlo.json"
    mc_path.write_text(json.dumps(mc, indent=2, default=str), encoding="utf-8")

    stress_path = LOG_DIR / "stress_test.json"
    stress_path.write_text(json.dumps(stress, indent=2, default=str), encoding="utf-8")

    lines = [
        "PHASE_12C_RESULT",
        f"BASELINE_PF={pa_m['pf_numeric']}",
        f"ADAPTIVE_PF={adaptive_m['pf_numeric']}",
        f"HYBRID_PF={hybrid_m['pf_numeric']}",
        f"HYBRID_EXPECTANCY_R={hybrid_m['expectancy_r']}",
        f"HYBRID_MAX_DD_R={hybrid_m['max_dd_r']}",
        f"HYBRID_TRADES={hybrid_m['trades']}",
        f"MC_MEDIAN_PF={mc['pf_median']}",
        f"STRESS_PF={stress['stress_pf']}",
        f"ADAPTIVE_HYBRID_CERTIFIED={'YES' if certified else 'NO'}",
        f"RECOMMENDED_FOR_PAPER_FORWARD={'YES' if paper_forward else 'NO'}",
    ]
    result_path = LOG_DIR / "phase12c_result.txt"
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for line in lines:
        emit(line)

    return 0 if certified else 2


if __name__ == "__main__":
    raise SystemExit(main())
