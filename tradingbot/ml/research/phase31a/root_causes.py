"""Root cause ranking and expected edge gain estimates."""

from __future__ import annotations

from typing import Any

import pandas as pd

from tradingbot.ml.research.phase31a.importance import _pf


def _baseline_metrics(df: pd.DataFrame) -> dict[str, float]:
    wins = df[df["pnl"] > 0]["pnl"].sum()
    losses = abs(df[df["pnl"] <= 0]["pnl"].sum())
    pf = float(wins / losses) if losses > 0 else 999.0
    return {
        "trade_count": len(df),
        "pf": pf,
        "expectancy": float(df["pnl"].mean()),
        "win_rate": float((df["pnl"] > 0).mean()),
        "total_pnl": float(df["pnl"].sum()),
    }


def rank_root_causes(df: pd.DataFrame, cluster_meta: list[dict], interactions: list[dict]) -> list[dict[str, Any]]:
    baseline = _baseline_metrics(df)
    causes: list[dict[str, Any]] = []

    # Loser clusters as discovered causes
    for c in cluster_meta:
        if c["expectancy"] >= 0:
            continue
        causes.append(_cause_from_cluster(c, baseline))

    # Forensic segments
    segments = [
        ("momentum_failure_losers", df[df.get("false_signal_class") == "momentum_failure"] if "false_signal_class" in df else pd.DataFrame()),
        ("ever_profitable_still_lost", df[(df.get("ever_profitable") == True) & (df["pnl"] <= 0)] if "ever_profitable" in df else pd.DataFrame()),
        ("high_mfe_low_capture", df[(df.get("mfe_r", 0) > 1.0) & (df["pnl_r"] < 0)] if "mfe_r" in df else pd.DataFrame()),
        ("counter_trend_london", df[(df.get("counter_trend_score", 0) >= 55) & (df.get("session") == "London")] if "session" in df else pd.DataFrame()),
        ("weak_breakout_high_conf", df[(df.get("false_breakout_score", 0) >= 60) & (df["confidence"] >= 0.95)]),
        ("min_lot_oversize_risk", df[(df.get("min_lot_limit_applied") == True) & (df["pnl"] <= 0)] if "min_lot_limit_applied" in df else pd.DataFrame()),
        ("range_regime_losers", df[(df["regime"] == "RANGE") & (df["pnl"] <= 0)]),
        ("overlap_session_losers", df[(df.get("session") == "Overlap") & (df["pnl"] <= 0)] if "session" in df else pd.DataFrame()),
        ("sl_exit_high_mfe", df[(df["exit_reason"] == "sl") & (df.get("mfe_r", 0) > 0.5)] if "mfe_r" in df else pd.DataFrame()),
        ("time_exit_undercaptured", df[(df["exit_reason"] == "time") & (df.get("capture_efficiency", 1) < 0.3)] if "capture_efficiency" in df else pd.DataFrame()),
    ]

    for name, sub in segments:
        if sub is None or len(sub) < 5:
            continue
        if float(sub["pnl"].mean()) >= 0:
            continue
        if len(sub) > len(df) * 0.9:
            continue
        causes.append(_cause_from_segment(name, sub, baseline))

    # Top harmful interactions
    for ix in interactions[:10]:
        if ix["expectancy"] >= 0:
            continue
        sub = df[
            (df.get(ix["dimension_a"], pd.Series(dtype=str)).astype(str) == ix["value_a"])
            & (df.get(ix["dimension_b"], pd.Series(dtype=str)).astype(str) == ix["value_b"])
        ] if ix["dimension_a"] in df.columns and ix["dimension_b"] in df.columns else pd.DataFrame()
        if len(sub) >= 5:
            causes.append(_cause_from_segment(
                f"interaction_{ix['dimension_a']}_{ix['value_a']}_x_{ix['dimension_b']}_{ix['value_b']}",
                sub, baseline, extra={"interaction": ix},
            ))

    causes.sort(key=lambda x: x["money_lost"], reverse=True)
    for i, c in enumerate(causes[:20]):
        c["rank"] = i + 1
    return causes[:20]


def _cause_from_cluster(c: dict, baseline: dict) -> dict[str, Any]:
    lost = abs(min(c["total_pnl"], 0))
    return {
        "cause_id": f"cluster_{c['cluster_id']}",
        "name": c["discovered_name"],
        "trade_count": c["trade_count"],
        "money_lost": round(lost, 2),
        "pf": c["pf"],
        "expectancy": c["expectancy"],
        "avg_mae": c["avg_mae"],
        "avg_mfe": c["avg_mfe"],
        "avg_holding_bars": c["avg_duration_bars"],
        "confidence": c["confidence_cluster"],
        "importance": c["importance"],
        "statistical_significance": c["statistical_significance"],
        "why": _explain_cluster(c),
        "pf_improvement_estimate": _est_pf_gain(c, baseline),
        "drawdown_reduction_estimate_pct": round(min(30, c["importance"] * 0.5), 2),
        "trade_reduction_estimate_pct": round(c["trade_count"] / max(baseline["trade_count"], 1) * 100 * 0.5, 2),
        "expected_edge_gain_usd": round(lost * 0.35, 2),
        "implementation_complexity": "MEDIUM",
    }


def _cause_from_segment(name: str, sub: pd.DataFrame, baseline: dict, extra: dict | None = None) -> dict[str, Any]:
    lost = abs(float(sub[sub["pnl"] <= 0]["pnl"].sum()))
    pf = _pf(sub)
    exp = float(sub["pnl"].mean())
    cause = {
        "cause_id": name,
        "name": name,
        "trade_count": int(len(sub)),
        "money_lost": round(lost, 2),
        "pf": round(pf, 4),
        "expectancy": round(exp, 4),
        "avg_mae": round(float(sub["mae"].mean()), 4) if "mae" in sub else None,
        "avg_mfe": round(float(sub["mfe"].mean()), 4) if "mfe" in sub else None,
        "avg_holding_bars": round(float(sub["duration_bars"].mean()), 2),
        "confidence": round(min(90, 40 + len(sub)), 1),
        "importance": round(lost / max(abs(baseline["total_pnl"]), 1) * 100, 2),
        "statistical_significance": "HIGH" if len(sub) >= 25 else "MEDIUM" if len(sub) >= 10 else "LOW",
        "why": _explain_segment(name, sub),
        "pf_improvement_estimate": _est_pf_gain_segment(sub, baseline),
        "drawdown_reduction_estimate_pct": round(min(25, lost / max(abs(baseline["total_pnl"]), 1) * 100), 2),
        "trade_reduction_estimate_pct": round(len(sub) / max(baseline["trade_count"], 1) * 100, 2),
        "expected_edge_gain_usd": round(lost * 0.4, 2),
        "implementation_complexity": _complexity(name),
    }
    if extra:
        cause.update(extra)
    return cause


def _explain_cluster(c: dict) -> str:
    tops = c.get("centroid_top_features", [])
    feats = ", ".join(f"{t['feature']} z={t['z_score']}" for t in tops[:3])
    return f"Discovered cluster {c['discovered_name']}: dominant features [{feats}]. PF={c['pf']}, n={c['trade_count']}."


def _explain_segment(name: str, sub: pd.DataFrame) -> str:
    explanations = {
        "momentum_failure_losers": "Price moved favorably early then reversed — momentum did not sustain.",
        "ever_profitable_still_lost": "Trade was in profit but exit path gave back gains — exit/timing issue.",
        "high_mfe_low_capture": "Large favorable excursion uncaptured — exit policy leaves R on table.",
        "counter_trend_london": "Counter-trend entries during London volatility fail more often.",
        "weak_breakout_high_conf": "ML confidence high but market structure quality low — false breakout.",
        "min_lot_oversize_risk": "Min lot constraint forces 3.4% risk vs 0.29% configured — loss amplification.",
        "range_regime_losers": "RANGE regime trades disproportionately lose — regime-strategy mismatch.",
        "overlap_session_losers": "Overlap session adds volatility without directional follow-through.",
        "sl_exit_high_mfe": "Stopped out despite meaningful MFE — stop too tight or noise.",
        "time_exit_undercaptured": "Time-based exit closes before TP with poor capture efficiency.",
    }
    base = explanations.get(name, f"Segment {name} underperforms baseline.")
    wr = float((sub["pnl"] > 0).mean())
    return f"{base} Win rate={wr:.1%}, n={len(sub)}."


def _est_pf_gain(c: dict, baseline: dict) -> float:
    if c["expectancy"] >= 0:
        return 0.0
    removable = c["trade_count"] / max(baseline["trade_count"], 1)
    return round(removable * 0.15, 4)


def _est_pf_gain_segment(sub: pd.DataFrame, baseline: dict) -> float:
    if float(sub["pnl"].mean()) >= 0:
        return 0.0
    share = len(sub) / max(baseline["trade_count"], 1)
    return round(share * 0.2, 4)


def _complexity(name: str) -> str:
    if "min_lot" in name:
        return "HIGH"
    if "interaction" in name:
        return "MEDIUM"
    if "exit" in name or "capture" in name or "mfe" in name:
        return "HIGH"
    return "LOW"


def build_expected_edge_gain(causes: list[dict], baseline: dict) -> dict[str, Any]:
    total_gain = sum(c["expected_edge_gain_usd"] for c in causes[:10])
    pf_gain = sum(c["pf_improvement_estimate"] for c in causes[:10])
    return {
        "baseline_pf": round(baseline["pf"], 4),
        "baseline_expectancy": round(baseline["expectancy"], 4),
        "estimated_pf_if_top5_causes_addressed": round(baseline["pf"] + pf_gain * 0.5, 4),
        "estimated_monthly_edge_gain_usd": round(total_gain, 2),
        "confidence": "MEDIUM-HIGH" if total_gain > 50 else "LOW",
        "note": "Estimates are forensic projections — no optimization performed in Phase 31A",
    }


def build_implementation_priority(causes: list[dict]) -> list[dict]:
    scored = []
    for c in causes:
        score = (
            c["money_lost"] * 0.4
            + c["pf_improvement_estimate"] * 100
            + (30 if c["statistical_significance"] == "HIGH" else 10)
            - (20 if c["implementation_complexity"] == "HIGH" else 0)
        )
        scored.append({**c, "priority_score": round(score, 2)})
    scored.sort(key=lambda x: x["priority_score"], reverse=True)
    for i, s in enumerate(scored[:15]):
        s["priority_rank"] = i + 1
    return scored[:15]
