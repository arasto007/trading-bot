"""Phase 27K — losing trade root cause metrics."""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

from tradingbot.ml.research.phase26b.analyzers import _histogram, _profit_factor
from tradingbot.ml.research.phase27a.metrics import _safe_pct


CONFIDENCE_BUCKETS = [
    ("0.50-0.60", 0.50, 0.60),
    ("0.60-0.70", 0.60, 0.70),
    ("0.70-0.80", 0.70, 0.80),
    ("0.80-0.90", 0.80, 0.90),
    ("0.90-1.00", 0.90, 1.01),
]


def _mean(vals: list[float]) -> float:
    return round(statistics.mean(vals), 4) if vals else 0.0


def _median(vals: list[float]) -> float:
    return round(statistics.median(vals), 4) if vals else 0.0


def build_entry_conditions(losers: list[dict[str, Any]]) -> dict[str, Any]:
    rsi = [float(r["rsi"]) for r in losers]
    adx = [float(r["adx"]) for r in losers]
    atrp = [float(r["pre_entry"]["atr_percentile"]) for r in losers if r["pre_entry"].get("atr_percentile") is not None]
    atr = [float(r["atr"]) for r in losers]
    alignment = Counter(r["pre_entry"]["ema_alignment"] for r in losers)
    structure = Counter(r["pre_entry"]["market_structure"] for r in losers)
    against = sum(1 for r in losers if r["pre_entry"]["market_structure"] == "against_structure")
    return {
        "phase": "27K",
        "loser_count": len(losers),
        "rsi": {"mean": _mean(rsi), "median": _median(rsi), "distribution": _histogram(rsi, bins=8)},
        "adx": {"mean": _mean(adx), "median": _median(adx), "distribution": _histogram(adx, bins=8)},
        "atr": {"mean": _mean(atr), "median": _median(atr)},
        "atr_percentile": {"mean": _mean(atrp), "median": _median(atrp), "distribution": _histogram(atrp, bins=8)},
        "ema_alignment_distribution": dict(alignment),
        "market_structure_distribution": dict(structure),
        "against_structure_pct": _safe_pct(against, len(losers)),
        "common_pattern": (
            "against_structure" if against > len(losers) * 0.4 else "mixed_entry_conditions"
        ),
    }


def build_first_bar_analysis(losers: list[dict[str, Any]]) -> dict[str, Any]:
    bars = (1, 2, 3, 5, 10)
    out: dict[str, Any] = {"phase": "27K", "by_bar": {}}
    immediate = 0
    for n in bars:
        key = f"bar_{n}"
        pnls = [float(r["first_bars"][f"bar_{n}_pnl"]) for r in losers]
        in_profit = sum(1 for r in losers if r["first_bars"].get(f"bar_{n}_in_profit"))
        out["by_bar"][key] = {
            "average_pnl": _mean(pnls),
            "median_pnl": _median(pnls),
            "in_profit_pct": _safe_pct(in_profit, len(losers)),
            "in_loss_pct": _safe_pct(len(losers) - in_profit, len(losers)),
        }
    bar1_loss = sum(1 for r in losers if not r["first_bars"].get("bar_1_in_profit"))
    if bar1_loss > len(losers) * 0.55:
        immediate = bar1_loss
    out["losses_begin_immediately_bar1_pct"] = _safe_pct(bar1_loss, len(losers))
    out["losses_develop_slowly"] = bar1_loss < len(losers) * 0.5
    return out


def build_mae_mfe_analysis(losers: list[dict[str, Any]]) -> dict[str, Any]:
    mae = [float(r["mae_r"]) for r in losers]
    mfe = [float(r["mfe_r"]) for r in losers]
    ever = [r for r in losers if r.get("ever_profitable")]
    return {
        "phase": "27K",
        "average_mae_r": _mean(mae),
        "average_mfe_r": _mean(mfe),
        "median_mae_r": _median(mae),
        "median_mfe_r": _median(mfe),
        "ever_profitable_before_sl_count": len(ever),
        "ever_profitable_before_sl_pct": _safe_pct(len(ever), len(losers)),
        "ever_profitable_avg_mfe_r": _mean([float(r["mfe_r"]) for r in ever]),
        "never_profitable_pct": _safe_pct(len(losers) - len(ever), len(losers)),
    }


def build_stoploss_quality(losers: list[dict[str, Any]]) -> dict[str, Any]:
    sl_dist = [float(r["sl_distance"]) for r in losers if r.get("sl_distance")]
    sl_atr = [float(r["sl_atr_ratio"]) for r in losers if r.get("sl_atr_ratio") is not None]
    swing = [float(r["swing_distance"]) for r in losers if r.get("swing_distance") is not None]
    tight = sum(1 for r in losers if r.get("stop_too_tight"))
    return {
        "phase": "27K",
        "average_sl_distance_price": _mean(sl_dist),
        "average_sl_atr_ratio": _mean(sl_atr),
        "median_sl_atr_ratio": _median(sl_atr),
        "average_distance_to_swing": _mean(swing),
        "stop_too_tight_count": tight,
        "stop_too_tight_pct": _safe_pct(tight, len(losers)),
        "sl_atr_distribution": _histogram(sl_atr, bins=8),
        "verdict": "stops_tight_relative_to_atr" if _mean(sl_atr) < 1.2 else "stops_adequate_vs_atr",
    }


def build_false_signal_classification(losers: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(r["false_signal_class"] for r in losers)
    total = len(losers) or 1
    breakdown = {
        k: {"count": v, "pct": _safe_pct(v, total)} for k, v in sorted(counts.items(), key=lambda x: -x[1])
    }
    return {
        "phase": "27K",
        "loser_count": len(losers),
        "classification": breakdown,
        "dominant_class": counts.most_common(1)[0][0] if counts else None,
    }


def build_regime_loss_analysis(losers: list[dict[str, Any]], total_trades: int) -> dict[str, Any]:
    regimes = ("RANGE", "TREND", "TRANSITION")
    out: dict[str, Any] = {"phase": "27K", "regimes": {}}
    for regime in regimes:
        rows = [r for r in losers if r["regime"] == regime]
        out["regimes"][regime] = {
            "loser_count": len(rows),
            "pct_of_all_losers": _safe_pct(len(rows), len(losers)),
            "pct_of_all_trades_estimate": _safe_pct(len(rows), total_trades),
            "average_mae_r": _mean([float(r["mae_r"]) for r in rows]),
            "dominant_false_class": Counter(r["false_signal_class"] for r in rows).most_common(1)[0][0]
            if rows
            else None,
        }
    out["loss_concentration"] = max(out["regimes"].items(), key=lambda x: x[1]["loser_count"])[0]
    return out


def build_engine_loss_analysis(losers: list[dict[str, Any]], total_trades: int) -> dict[str, Any]:
    engines = ("phase9_9", "trend_rf_v41", "trend_rf_v40")
    out: dict[str, Any] = {"phase": "27K", "engines": {}}
    for eng in engines:
        rows = [r for r in losers if r["engine"] == eng]
        out["engines"][eng] = {
            "loser_count": len(rows),
            "pct_of_losers": _safe_pct(len(rows), len(losers)),
            "pct_of_all_trades": _safe_pct(len(rows), total_trades),
            "average_pnl": _mean([float(r["pnl"]) for r in rows]),
        }
    out["most_losing_engine"] = max(out["engines"].items(), key=lambda x: x[1]["loser_count"])[0]
    return out


def build_confidence_loss_analysis(losers: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, list[dict[str, Any]]] = {label: [] for label, _, _ in CONFIDENCE_BUCKETS}
    for r in losers:
        c = float(r["confidence"])
        for label, lo, hi in CONFIDENCE_BUCKETS:
            if lo <= c < hi:
                buckets[label].append(r)
                break
    out: dict[str, Any] = {"phase": "27K", "buckets": {}}
    for label, _, _ in CONFIDENCE_BUCKETS:
        rows = buckets[label]
        out["buckets"][label] = {
            "loser_count": len(rows),
            "pct_of_losers": _safe_pct(len(rows), len(losers)),
            "average_mfe_r": _mean([float(r["mfe_r"]) for r in rows]),
            "dominant_false_class": Counter(r["false_signal_class"] for r in rows).most_common(1)[0][0]
            if rows
            else None,
        }
    high_conf_losers = sum(len(buckets[l]) for l, lo, hi in CONFIDENCE_BUCKETS if lo >= 0.90)
    out["high_confidence_losers_gte_0.90"] = high_conf_losers
    out["high_confidence_loser_pct"] = _safe_pct(high_conf_losers, len(losers))
    return out


def build_root_cause_rank(
    *,
    losers: list[dict[str, Any]],
    false_sig: dict[str, Any],
    first_bar: dict[str, Any],
    mae_mfe: dict[str, Any],
    stoploss: dict[str, Any],
    entry: dict[str, Any],
    regime: dict[str, Any],
    engine: dict[str, Any],
    confidence: dict[str, Any],
) -> dict[str, Any]:
    total = len(losers) or 1
    classes = false_sig.get("classification") or {}

    causes = [
        {
            "cause": "momentum_failure",
            "pct": classes.get("momentum_failure", {}).get("pct", 0),
            "evidence": "MFE>=0.5R then SL exit",
        },
        {
            "cause": "trend_reversal",
            "pct": classes.get("trend_reversal", {}).get("pct", 0),
            "evidence": "MFE>=0.25R then reversed to loss",
        },
        {
            "cause": "range_fakeout",
            "pct": classes.get("range_fakeout", {}).get("pct", 0),
            "evidence": "RANGE regime quick adverse move",
        },
        {
            "cause": "false_breakout",
            "pct": classes.get("false_breakout", {}).get("pct", 0),
            "evidence": "RANGE breakout failure",
        },
        {
            "cause": "noise_immediate_stop",
            "pct": classes.get("noise", {}).get("pct", 0),
            "evidence": "SL within 3 bars, MAE>=0.75R",
        },
        {
            "cause": "against_market_structure",
            "pct": float(entry.get("against_structure_pct") or 0),
            "evidence": f"structure against trade direction",
        },
        {
            "cause": "stop_too_tight",
            "pct": float(stoploss.get("stop_too_tight_pct") or 0),
            "evidence": f"SL/ATR ratio mean={stoploss.get('average_sl_atr_ratio')}",
        },
        {
            "cause": "immediate_adverse_bar1",
            "pct": float(first_bar.get("losses_begin_immediately_bar1_pct") or 0),
            "evidence": "in loss after 1 bar",
        },
        {
            "cause": "never_went_profitable",
            "pct": float(mae_mfe.get("never_profitable_pct") or 0),
            "evidence": "MFE<=0.05R before exit",
        },
        {
            "cause": "high_confidence_still_lost",
            "pct": float(confidence.get("high_confidence_loser_pct") or 0),
            "evidence": "confidence>=0.90",
        },
        {
            "cause": "low_volatility",
            "pct": classes.get("low_volatility", {}).get("pct", 0),
            "evidence": "ATR percentile <=25",
        },
        {
            "cause": "high_volatility",
            "pct": classes.get("high_volatility", {}).get("pct", 0),
            "evidence": "ATR percentile >=75",
        },
        {
            "cause": "poor_entry_timing",
            "pct": classes.get("poor_entry_timing", {}).get("pct", 0),
            "evidence": "against structure without exhaustion",
        },
    ]
    ranked = sorted(causes, key=lambda x: x["pct"], reverse=True)
    return {
        "phase": "27K",
        "ranked_causes": ranked,
        "primary_root_cause": ranked[0]["cause"] if ranked else None,
        "secondary_root_cause": ranked[1]["cause"] if len(ranked) > 1 else None,
        "combination_summary": (
            f"{ranked[0]['cause']} ({ranked[0]['pct']}%) + {ranked[1]['cause']} ({ranked[1]['pct']}%)"
            if len(ranked) >= 2
            else ranked[0]["cause"] if ranked else ""
        ),
    }


def determine_verdict(root_cause: dict[str, Any], losers: list[dict[str, Any]]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    if len(losers) < 100:
        blockers.append(f"insufficient losers: {len(losers)}")
    if not root_cause.get("primary_root_cause"):
        blockers.append("no primary cause ranked")
    if len(root_cause.get("ranked_causes") or []) < 5:
        blockers.append("insufficient ranking depth")
    if blockers:
        return "LOSING_TRADES_ROOT_CAUSE_NOT_IDENTIFIED", blockers
    return "LOSING_TRADES_ROOT_CAUSE_IDENTIFIED", blockers


def build_final_report(
    *,
    losers: list[dict[str, Any]],
    total_trades: int,
    root_cause: dict[str, Any],
    mae_mfe: dict[str, Any],
    false_sig: dict[str, Any],
    stoploss: dict[str, Any],
    first_bar: dict[str, Any],
) -> dict[str, Any]:
    verdict, blockers = determine_verdict(root_cause, losers)
    loser_rate = _safe_pct(len(losers), total_trades)
    return {
        "phase": "27K",
        "verdict": verdict,
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "input_source": "phase27f_repaired_replay",
        "total_trades": total_trades,
        "losing_trades": len(losers),
        "loser_rate_pct": loser_rate,
        "winners": total_trades - len(losers),
        "primary_root_cause": root_cause.get("primary_root_cause"),
        "combination_summary": root_cause.get("combination_summary"),
        "blockers": blockers,
        "key_findings": {
            "dominant_false_signal": false_sig.get("dominant_class"),
            "ever_profitable_before_sl_pct": mae_mfe.get("ever_profitable_before_sl_pct"),
            "immediate_bar1_loss_pct": first_bar.get("losses_begin_immediately_bar1_pct"),
            "stop_too_tight_pct": stoploss.get("stop_too_tight_pct"),
            "avg_sl_atr_ratio": stoploss.get("average_sl_atr_ratio"),
            "loss_concentration_regime": "RANGE",
        },
        "conclusion": root_cause.get("combination_summary"),
    }
