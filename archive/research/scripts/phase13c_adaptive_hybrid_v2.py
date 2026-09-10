#!/usr/bin/env python3
"""
PHASE 13C - Adaptive Quality v2 + ML Hybrid Certification (RESEARCH ONLY).

Does NOT modify PA_PRODUCTION_LOCK, USE_ML_KERNEL, ADAPTIVE_REGIME_ENABLED,
live routing, or order execution.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "logs" / "phase13c_adaptive_hybrid_v2.txt"
LOG_DIR = ROOT / "logs" / "phase13c"
MATRIX_PATH = LOG_DIR / "threshold_matrix.json"

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.update(
    {
        "USE_ML_KERNEL": "false",
        "TRADINGBOT_DISABLE_JOURNAL": "1",
        "TRADINGBOT_SIGNAL_FILTER": "OFF",
        "TRADINGBOT_DRY_RUN": "1",
    }
)
warnings.filterwarnings("ignore")

THRESHOLDS = [60, 62, 65, 68, 70]
ABLATION_THRESHOLDS = [65, 70]
SESSION_START, SESSION_END = 7, 21
WARMUP = 500
COOLDOWN = 6
MAX_TRADES_PER_DAY = 5
SPREAD_PIPS = 4.0
SLIP_PIPS = 1.0
ML_SKIP_CEILING = 60.0  # if base + ml_budget < watchlist floor, skip ML

GATE = {
    "trades_min": 120,
    "pf_min": 1.30,
    "expectancy_min": 0.15,
    "max_dd_max": 10.0,
    "max_month_profit_share": 0.50,
}


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def load_m5() -> tuple[pd.DataFrame, Path]:
    candidates = [
        ROOT / "data" / "cache" / "XAUUSD_M5_90d.parquet",
        ROOT / "data" / "cache" / "XAUUSD_M5_180d.parquet",
        ROOT / "data" / "backtest" / "XAUUSD_M5_90d.parquet",
        ROOT / "data" / "backtest" / "XAUUSD_M5_180d.parquet",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        df = pd.read_parquet(path)
        if not isinstance(df.index, pd.DatetimeIndex):
            if "time" in df.columns:
                df = df.set_index("time")
            df.index = pd.to_datetime(df.index, utc=True)
        df = df.rename(columns={c: c.lower() for c in df.columns})
        if "tick_volume" in df.columns and "volume" not in df.columns:
            df["volume"] = df["tick_volume"]
        need = ["open", "high", "low", "close"]
        for c in need:
            if c not in df.columns:
                raise RuntimeError(f"{path.name} missing {c}")
        if "volume" not in df.columns:
            df["volume"] = 0.0
        df = df[["open", "high", "low", "close", "volume"]].dropna().sort_index()
        return df, path
    raise RuntimeError("No XAUUSD M5 90d/180d parquet found")


def _r_metrics(rs: list[float], qualities: list[float] | None = None) -> dict[str, Any]:
    if not rs:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "pf": 0.0,
            "expectancy_r": 0.0,
            "max_dd_r": 0.0,
            "avg_quality": 0.0,
        }
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
        "pf": round(min(pf, 999.0), 3),
        "expectancy_r": round(sum(rs) / len(rs), 3),
        "max_dd_r": round(mdd, 2),
        "avg_quality": round(float(np.mean(qualities)) if qualities else 0.0, 2),
    }


def month_profit_concentration(trade_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Max share of sum(positive R) attributable to a single entry month."""
    by_month: dict[str, float] = defaultdict(float)
    for t in trade_rows:
        r = float(t["r_multiple"])
        if r <= 0:
            continue
        month = str(pd.Timestamp(t["entry_time"]).strftime("%Y-%m"))
        by_month[month] += r
    total_pos = sum(by_month.values())
    if total_pos <= 0:
        return {
            "max_month": None,
            "max_month_profit_r": 0.0,
            "total_positive_r": 0.0,
            "max_month_share": 0.0,
            "pass": True,
            "by_month": {},
        }
    max_month = max(by_month, key=by_month.get)
    share = by_month[max_month] / total_pos
    return {
        "max_month": max_month,
        "max_month_profit_r": round(by_month[max_month], 3),
        "total_positive_r": round(total_pos, 3),
        "max_month_share": round(share, 4),
        "pass": share <= GATE["max_month_profit_share"],
        "by_month": {k: round(v, 3) for k, v in sorted(by_month.items())},
    }


def institutional_pass(m: dict[str, Any], conc: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "trades_gte_120": int(m["trades"]) >= GATE["trades_min"],
        "pf_gte_130": float(m["pf"]) >= GATE["pf_min"],
        "expectancy_gte_015": float(m["expectancy_r"]) >= GATE["expectancy_min"],
        "max_dd_lte_10r": float(m["max_dd_r"]) <= GATE["max_dd_max"],
        "month_concentration_ok": bool(conc.get("pass", False)),
    }
    return {"checks": checks, "certified": all(checks.values())}


def build_sl_tp(frame: pd.DataFrame, idx: int, direction: int) -> tuple[float, float] | None:
    from tradingbot.domain.signal_helpers import compute_sl_tp
    from tradingbot.ml.decision_engine.decision_policy import VOL_REGIME_RULE_CONFIDENCE

    sl, tp, _ = compute_sl_tp(
        frame.iloc[: idx + 1],
        direction,
        VOL_REGIME_RULE_CONFIDENCE,
        symbol="XAUUSD",
        strategy_name="adaptive_quality",
        timeframe="M5",
    )
    if sl is None or tp is None:
        return None
    if float(sl) == 0.0 or float(tp) == 0.0:
        return None
    return float(sl), float(tp)


def scan_hybrid_records(
    frame: pd.DataFrame,
    models: dict[str, Any],
    *,
    include_ml: bool = True,
    progress_every: int = 2000,
    only_indices: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Single pass: build raw evaluation records (ML fast-path + bounded lookback)."""
    from tradingbot.ml.research.phase13c.adaptive_quality_v2 import (
        WATCHLIST_HI,
        WATCHLIST_LO,
        compute_quality_v2,
        score_ml_shadow,
        try_watchlist_promotion,
    )
    from tradingbot.strategies.adaptive_regime import classify_regime as _classify
    from tradingbot.strategies.adaptive_quality_engine import resolve_candidate_direction as _resolve
    import tradingbot.ml.feature_store as feature_store

    # Bound feature-store lookback so ML scoring stays ~O(1) per bar.
    _orig_truncated = feature_store.truncated_df
    _LOOKBACK = 400

    def _truncated_bounded(df, index, min_rows=30):
        if df is None or len(df) == 0:
            return None
        if index < 0 or index >= len(df):
            return None
        start_i = max(0, int(index) - _LOOKBACK + 1)
        work = df.iloc[start_i : int(index) + 1]
        if len(work) < min_rows:
            return None
        return work

    feature_store.truncated_df = _truncated_bounded

    records: list[dict[str, Any]] = []
    start = max(WARMUP, 60)
    n = len(frame)
    ml_calls = 0
    ml_skips = 0
    scanned = 0
    ml_cache: dict[int, Any] = {}

    try:
        indices = (
            range(start, n)
            if only_indices is None
            else sorted(i for i in only_indices if start <= i < n)
        )

        for i in indices:
            scanned += 1
            if progress_every and scanned % progress_every == 0:
                emit(
                    f"    scan progress {scanned} bars | i={i}/{n} "
                    f"records={len(records)} ml_calls={ml_calls} ml_skips={ml_skips}"
                )

            ts = pd.Timestamp(frame.index[i])
            hour = int(ts.hour)
            if not (SESSION_START <= hour < SESSION_END):
                continue

            row = frame.iloc[i]
            regime = _classify(row)
            if regime == "NO_TRADE":
                continue

            direction = _resolve(frame, i)
            if direction is None:
                continue

            total_base, comps_base, budget, _ = compute_quality_v2(
                frame, i, direction, ml=None, bar_open=ts
            )
            ml_view = None
            components = dict(comps_base)
            total = float(total_base)

            if include_ml:
                if total_base + float(budget.get("ml", 0)) < ML_SKIP_CEILING:
                    ml_skips += 1
                else:
                    if i in ml_cache:
                        ml_view = ml_cache[i]
                    else:
                        ml_view = score_ml_shadow(
                            frame, i, models, adaptive_regime=regime
                        )
                        ml_cache[i] = ml_view
                        ml_calls += 1
                    total, components, budget, _ = compute_quality_v2(
                        frame, i, direction, ml=ml_view, bar_open=ts
                    )

            promoted = False
            promo_reasons: tuple[str, ...] = ()
            if WATCHLIST_LO <= total <= WATCHLIST_HI:
                promoted, promo_reasons = try_watchlist_promotion(
                    frame, i, direction, total
                )

            levels = build_sl_tp(frame, i, direction)
            if levels is None:
                continue
            sl, tp = levels
            entry = float(frame.iloc[i]["close"])

            records.append(
                {
                    "bar_index": i,
                    "bar_time": str(ts),
                    "hour": hour,
                    "direction": "BUY" if direction > 0 else "SELL",
                    "entry": entry,
                    "stop_loss": sl,
                    "take_profit": tp,
                    "quality_score": float(total),
                    "base_score": float(total_base),
                    "score_components": {
                        k: round(float(v), 4) for k, v in components.items()
                    },
                    "weight_budget": dict(budget),
                    "regime": regime,
                    "promoted_ok": bool(promoted),
                    "promotion_reasons": list(promo_reasons),
                    "ml": None
                    if ml_view is None
                    else {
                        "probability": round(ml_view.probability, 4),
                        "expected_edge_r": round(ml_view.expected_edge_r, 4),
                        "confidence_bucket": ml_view.confidence_bucket,
                        "regime": ml_view.regime,
                        "model_name": ml_view.model_name,
                    },
                    "include_ml": include_ml,
                }
            )
    finally:
        feature_store.truncated_df = _orig_truncated

    emit(
        f"    scan done include_ml={include_ml} records={len(records)} "
        f"ml_calls={ml_calls} ml_skips={ml_skips}"
    )
    return records


def filter_candidates(records: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
    from tradingbot.ml.research.phase13c.adaptive_quality_v2 import WATCHLIST_HI, WATCHLIST_LO

    out: list[dict[str, Any]] = []
    for r in records:
        q = float(r["quality_score"])
        if q >= threshold:
            out.append({**r, "via": "threshold"})
        elif WATCHLIST_LO <= q <= WATCHLIST_HI and r.get("promoted_ok"):
            out.append({**r, "via": "watchlist_promotion"})
    return out


def replay(
    df: pd.DataFrame,
    candidates: list[dict[str, Any]],
    *,
    cooldown_bars: int = COOLDOWN,
    max_trades_per_day: int = MAX_TRADES_PER_DAY,
) -> tuple[list[Any], list[dict[str, Any]], dict[str, Any]]:
    from tradingbot.ml.research.phase9a.pm_v2_research import profile_for_mode, simulate_pm_entry

    profile = profile_for_mode("36a")
    trades = []
    trade_rows: list[dict[str, Any]] = []
    last_entry = -9999
    open_until = -1
    day_counts: dict[str, int] = {}
    qualities: list[float] = []

    for cand in sorted(candidates, key=lambda c: c["bar_index"]):
        i = int(cand["bar_index"])
        if i <= open_until or i - last_entry < cooldown_bars:
            continue
        day = str(pd.Timestamp(df.index[i]).date())
        if day_counts.get(day, 0) >= max_trades_per_day:
            continue
        sim = simulate_pm_entry(
            cand, df, profile, spread_pips=SPREAD_PIPS, slippage_pips=SLIP_PIPS
        )
        if sim is None:
            continue
        trades.append(sim)
        q = float(cand.get("quality_score", 0.0))
        qualities.append(q)
        trade_rows.append(
            {
                "r_multiple": float(sim.r_multiple),
                "entry_time": sim.entry_time,
                "exit_time": sim.exit_time,
                "quality_score": q,
                "bar_index": i,
                "via": cand.get("via"),
            }
        )
        open_until = int(sim.exit_bar_index)
        last_entry = i
        day_counts[day] = day_counts.get(day, 0) + 1

    metrics = _r_metrics([float(t.r_multiple) for t in trades], qualities)
    return trades, trade_rows, metrics


def watchlist_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    from tradingbot.ml.research.phase13c.adaptive_quality_v2 import WATCHLIST_HI, WATCHLIST_LO

    band = [r for r in records if WATCHLIST_LO <= float(r["quality_score"]) <= WATCHLIST_HI]
    promoted = [r for r in band if r.get("promoted_ok")]
    reason_fail = Counter()
    for r in band:
        if r.get("promoted_ok"):
            continue
        reasons = r.get("promotion_reasons") or ["unknown"]
        reason_fail[str(reasons[0] if reasons else "unknown")] += 1
    reason_ok = Counter()
    for r in promoted:
        for reason in r.get("promotion_reasons") or []:
            reason_ok[str(reason)] += 1
    return {
        "watchlist_band_count": len(band),
        "promoted_count": len(promoted),
        "promotion_rate": round(len(promoted) / len(band), 4) if band else 0.0,
        "fail_reasons": dict(reason_fail.most_common()),
        "success_reason_counts": dict(reason_ok.most_common()),
    }


def main() -> int:
    from tradingbot.config.dotenv_loader import load_dotenv
    from tradingbot.ml.research.phase13c.adaptive_quality_v2 import (
        WEIGHT_MATRIX,
        WEIGHT_RANGES,
        load_phase11a_regime_models,
    )
    from tradingbot.strategies.adaptive_regime import prepare_adaptive_frame

    load_dotenv()
    # Keep research-safe env after dotenv
    os.environ["USE_ML_KERNEL"] = "false"
    os.environ["TRADINGBOT_DISABLE_JOURNAL"] = "1"
    os.environ["TRADINGBOT_DRY_RUN"] = "1"

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    emit(f"PHASE 13C Adaptive Hybrid v2 | UTC {datetime.now(timezone.utc).isoformat()}")
    emit("RESEARCH ONLY — no production flag changes")

    raw, src = load_m5()
    emit(f"  data={src} bars_raw={len(raw)}")
    frame = prepare_adaptive_frame(raw)
    emit(f"  prepared bars={len(frame)} range={frame.index.min()} -> {frame.index.max()}")

    models = load_phase11a_regime_models()
    emit(f"  phase11a models={list(models.keys())}")
    if not models:
        emit("ERROR: no Phase 11A models loaded")
        return 1

    emit("SCAN 1 — hybrid v2 with ML (fast-path skip when base+ml_budget < 60)")
    records_ml = scan_hybrid_records(frame, models, include_ml=True, progress_every=2000)
    wl = watchlist_stats(records_ml)

    # Ablation: derive no-ML scores from scan-1 base components (budgets keep ml slot at 0 pts)
    emit("SCAN 2 — derive no-ML ablation from base scores (no second ML pass)")
    from tradingbot.ml.research.phase13c.adaptive_quality_v2 import (
        WATCHLIST_HI,
        WATCHLIST_LO,
        try_watchlist_promotion,
    )

    records_noml = []
    for r in records_ml:
        q = float(r["base_score"])
        comps = dict(r.get("score_components") or {})
        comps["ml"] = 0.0
        promoted = False
        promo_reasons: tuple[str, ...] = ()
        direction = 1 if r["direction"] == "BUY" else -1
        if WATCHLIST_LO <= q <= WATCHLIST_HI:
            promoted, promo_reasons = try_watchlist_promotion(
                frame, int(r["bar_index"]), direction, q
            )
        records_noml.append(
            {
                **r,
                "quality_score": q,
                "score_components": comps,
                "promoted_ok": bool(promoted),
                "promotion_reasons": list(promo_reasons),
                "ml": None,
                "include_ml": False,
            }
        )
    noml_by_idx = {int(r["bar_index"]): r for r in records_noml}
    emit(f"    no-ML records={len(records_noml)}")

    # Threshold sweep with ML
    sweep: list[dict[str, Any]] = []
    certified_rows: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None

    for th in THRESHOLDS:
        cands = filter_candidates(records_ml, th)
        trades, trade_rows, metrics = replay(frame, cands)
        conc = month_profit_concentration(trade_rows)
        gate = institutional_pass(metrics, conc)
        promoted_used = sum(1 for t in trade_rows if t.get("via") == "watchlist_promotion")
        row = {
            "threshold": th,
            "include_ml": True,
            "candidates": len(cands),
            **metrics,
            "month_concentration": conc,
            "gate": gate,
            "promoted_trades": promoted_used,
        }
        sweep.append(row)
        emit(
            f"  th={th} cands={len(cands)} trades={metrics['trades']} "
            f"PF={metrics['pf']} exp={metrics['expectancy_r']} "
            f"dd={metrics['max_dd_r']} avgQ={metrics['avg_quality']} "
            f"certified={gate['certified']}"
        )
        if gate["certified"]:
            certified_rows.append(row)
        # Best = highest PF among those with trades, prefer certified then pf*exp
        score = (
            (1000.0 if gate["certified"] else 0.0)
            + float(metrics["pf"]) * 10
            + float(metrics["expectancy_r"])
            + min(int(metrics["trades"]), 200) / 200.0
        )
        if metrics["trades"] > 0 and (best is None or score > best.get("_score", -1e9)):
            best = {**row, "_score": score}

    # ML contribution at ablation thresholds
    ml_contrib: list[dict[str, Any]] = []
    improved_any = False
    for th in ABLATION_THRESHOLDS:
        cands_ml = filter_candidates(records_ml, th)
        cands_noml = filter_candidates(records_noml, th)
        _, _, m_ml = replay(frame, cands_ml)
        _, _, m_noml = replay(frame, cands_noml)
        improved = (float(m_ml["pf"]) > float(m_noml["pf"])) and (
            float(m_ml["expectancy_r"]) >= float(m_noml["expectancy_r"])
        )
        # also count mild improvement on expectancy alone at similar PF
        if float(m_ml["pf"]) >= float(m_noml["pf"]) and float(m_ml["expectancy_r"]) > float(
            m_noml["expectancy_r"]
        ):
            improved = True
        improved_any = improved_any or improved
        ml_contrib.append(
            {
                "threshold": th,
                "with_ml": m_ml,
                "without_ml": m_noml,
                "pf_delta": round(float(m_ml["pf"]) - float(m_noml["pf"]), 3),
                "exp_delta": round(float(m_ml["expectancy_r"]) - float(m_noml["expectancy_r"]), 3),
                "improved_edge": improved,
            }
        )
        emit(
            f"  ML contrib th={th}: PF {m_noml['pf']}->{m_ml['pf']} "
            f"exp {m_noml['expectancy_r']}->{m_ml['expectancy_r']} improved={improved}"
        )

    # Also compare all thresholds for richer analysis
    for th in THRESHOLDS:
        if th in ABLATION_THRESHOLDS:
            continue
        cands_ml = filter_candidates(records_ml, th)
        # approximate no-ml from stored base components on ML records
        approx = []
        for r in records_ml:
            comps = r.get("score_components") or {}
            q_noml = float(comps.get("h1", 0) + comps.get("atr", 0) + comps.get("ema", 0) + comps.get("session", 0))
            # promotion based on no-ml score band is approximate; use noml record if present
            alt = noml_by_idx.get(int(r["bar_index"]))
            if alt is not None:
                approx.append(alt)
            else:
                approx.append({**r, "quality_score": q_noml, "promoted_ok": False})
        cands_noml = filter_candidates(approx, th)
        _, _, m_ml = replay(frame, cands_ml)
        _, _, m_noml = replay(frame, cands_noml)
        improved = float(m_ml["pf"]) > float(m_noml["pf"]) and float(m_ml["expectancy_r"]) >= float(
            m_noml["expectancy_r"]
        )
        if float(m_ml["pf"]) >= float(m_noml["pf"]) and float(m_ml["expectancy_r"]) > float(
            m_noml["expectancy_r"]
        ):
            improved = True
        improved_any = improved_any or improved
        ml_contrib.append(
            {
                "threshold": th,
                "with_ml": m_ml,
                "without_ml": m_noml,
                "pf_delta": round(float(m_ml["pf"]) - float(m_noml["pf"]), 3),
                "exp_delta": round(float(m_ml["expectancy_r"]) - float(m_noml["expectancy_r"]), 3),
                "improved_edge": improved,
                "approx_noml": True,
            }
        )

    if best is None:
        best = {
            "threshold": None,
            "trades": 0,
            "pf": 0.0,
            "expectancy_r": 0.0,
            "max_dd_r": 0.0,
            "gate": {"certified": False},
        }

    n_certified = len(certified_rows)
    production_ready = n_certified > 0
    # Secondary engine recommendation: best certified, else best overall with note
    if certified_rows:
        rec = max(certified_rows, key=lambda r: (float(r["pf"]), float(r["expectancy_r"])))
    else:
        rec = best

    matrix = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_source": str(src),
        "session_utc": f"{SESSION_START}-{SESSION_END}",
        "replay": {
            "profile": "36a",
            "cooldown_bars": COOLDOWN,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
            "spread_pips": SPREAD_PIPS,
            "slippage_pips": SLIP_PIPS,
        },
        "weight_matrix": WEIGHT_MATRIX,
        "weight_ranges": WEIGHT_RANGES,
        "watchlist_promotion": wl,
        "ml_contribution": ml_contrib,
        "threshold_sweep": [{k: v for k, v in r.items() if k != "_score"} for r in sweep],
        "certified": [{k: v for k, v in r.items() if k != "_score"} for r in certified_rows],
        "recommended": {k: v for k, v in rec.items() if k != "_score"},
        "records_with_ml": len(records_ml),
        "records_without_ml": len(records_noml),
    }
    MATRIX_PATH.write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8")

    # Report sections 1-6
    lines: list[str] = []
    lines.append("PHASE 13C — Adaptive Quality v2 + ML Hybrid (RESEARCH ONLY)")
    lines.append(f"Generated UTC: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Data: {src.name} bars={len(frame)}")
    lines.append(f"Models: {list(models.keys())}")
    lines.append(f"Replay: profile=36a cooldown={COOLDOWN} max/day={MAX_TRADES_PER_DAY} spread={SPREAD_PIPS} slip={SLIP_PIPS}")
    lines.append("")
    lines.append("==== 1. QUALITY WEIGHT MATRIX ====")
    for regime, weights in WEIGHT_MATRIX.items():
        lines.append(f"  {regime}: {weights} sum={sum(weights.values())}")
    lines.append(f"  ranges: {WEIGHT_RANGES}")
    lines.append("")
    lines.append("==== 2. WATCHLIST PROMOTION RESULTS ====")
    lines.append(f"  band_60_69: {wl['watchlist_band_count']}")
    lines.append(f"  promoted: {wl['promoted_count']} rate={wl['promotion_rate']}")
    lines.append(f"  fail_reasons: {wl['fail_reasons']}")
    lines.append(f"  success_reason_counts: {wl['success_reason_counts']}")
    lines.append("")
    lines.append("==== 3. ML CONTRIBUTION ANALYSIS ====")
    for row in sorted(ml_contrib, key=lambda x: x["threshold"]):
        wm, wn = row["with_ml"], row["without_ml"]
        lines.append(
            f"  th={row['threshold']}: "
            f"noML(trades={wn['trades']} PF={wn['pf']} exp={wn['expectancy_r']}) -> "
            f"ML(trades={wm['trades']} PF={wm['pf']} exp={wm['expectancy_r']}) "
            f"dPF={row['pf_delta']} dExp={row['exp_delta']} improved={row['improved_edge']}"
            + (" [approx_noml]" if row.get("approx_noml") else "")
        )
    lines.append(f"  ML_CONFIRMATION_IMPROVED_EDGE={'YES' if improved_any else 'NO'}")
    lines.append("")
    lines.append("==== 4. THRESHOLD SWEEP TABLE ====")
    lines.append(
        "| th | cands | trades | win% | PF | expR | maxDD | avgQ | month_share | certified |"
    )
    lines.append("|----|-------|--------|------|----|------|-------|------|-------------|-----------|")
    for r in sweep:
        share = r["month_concentration"].get("max_month_share", 0.0)
        lines.append(
            f"| {r['threshold']} | {r['candidates']} | {r['trades']} | {r['win_rate']} | "
            f"{r['pf']} | {r['expectancy_r']} | {r['max_dd_r']} | {r['avg_quality']} | "
            f"{share:.2%} | {'YES' if r['gate']['certified'] else 'NO'} |"
        )
    lines.append("")
    lines.append("==== 5. CERTIFIED CONFIGURATIONS ====")
    if not certified_rows:
        lines.append("  (none)")
    else:
        for r in certified_rows:
            lines.append(
                f"  th={r['threshold']} trades={r['trades']} PF={r['pf']} "
                f"exp={r['expectancy_r']} maxDD={r['max_dd_r']} avgQ={r['avg_quality']} "
                f"month_share={r['month_concentration'].get('max_month_share')}"
            )
            lines.append(f"    checks={r['gate']['checks']}")
    lines.append("")
    lines.append("==== 6. RECOMMENDED SECONDARY ENGINE ====")
    lines.append(
        f"  threshold={rec.get('threshold')} trades={rec.get('trades')} PF={rec.get('pf')} "
        f"exp={rec.get('expectancy_r')} maxDD={rec.get('max_dd_r')} "
        f"certified={rec.get('gate', {}).get('certified')}"
    )
    lines.append(
        f"  SECONDARY_ENGINE_PRODUCTION_READY={'YES' if production_ready else 'NO'}"
    )
    lines.append("  KEEP_RESEARCH_ONLY=YES")
    lines.append("  Note: no live unlock; Adaptive remains research-gated.")
    lines.append("")
    lines.append("PHASE_13C_RESULT")
    lines.append(f"TOTAL_CONFIGS_TESTED={len(THRESHOLDS)}")
    lines.append(f"CERTIFIED_CONFIGS={n_certified}")
    lines.append(f"BEST_THRESHOLD={rec.get('threshold')}")
    lines.append(f"BEST_PF={rec.get('pf')}")
    lines.append(f"BEST_EXPECTANCY_R={rec.get('expectancy_r')}")
    lines.append(f"BEST_MAX_DD_R={rec.get('max_dd_r')}")
    lines.append(f"TRADES_AT_BEST_CONFIG={rec.get('trades')}")
    lines.append(f"ML_CONFIRMATION_IMPROVED_EDGE={'YES' if improved_any else 'NO'}")
    lines.append(f"SECONDARY_ENGINE_PRODUCTION_READY={'YES' if production_ready else 'NO'}")
    lines.append("KEEP_RESEARCH_ONLY=YES")
    lines.append("")

    REPORT.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    emit(f"Wrote {REPORT}")
    emit(f"Wrote {MATRIX_PATH}")
    emit("")
    # echo final block
    in_block = False
    for line in lines:
        if line.strip() == "PHASE_13C_RESULT":
            in_block = True
        if in_block:
            emit(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
