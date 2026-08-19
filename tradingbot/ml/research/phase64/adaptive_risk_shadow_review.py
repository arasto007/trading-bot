"""Phase 64 — AdaptiveRisk shadow review (research only).

Analyze AR-blocked TREND HC signals from phase46 caches; quantify incremental
impact of AR bypass on top of phase63 TradeQuality alias policy.
NO production code changes.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase64" / "artifacts"
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"
CACHE_LABELS = ("A", "B", "C", "H")
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"
PHASE63_POLICY = ROOT / "tradingbot" / "ml" / "research" / "phase63" / "artifacts" / "tq_shadow_policy.json"

PRIMARY_THRESHOLD = 0.40
TQ_SHADOW_THRESHOLD = 0.40
TQ_ALIAS_POLICY = "map_to_v40"
MIN_CONFIDENCE_FOR_RISK = 0.55

VOLATILITY_TO_ATR: dict[str, float] = {
    "LOW_VOL": 15.0,
    "NORMAL": 45.0,
    "HIGH_VOL": 75.0,
}

SESSION_MAP: dict[str, str] = {
    "asian": "asia",
    "london": "london",
    "overlap": "london",
    "new york": "new_york",
    "new_york": "new_york",
}


def _infer_session(timestamp: str) -> str:
    from tradingbot.execution.execution_costs import session_from_hour

    ts = pd.to_datetime(timestamp, utc=True)
    raw = session_from_hour(int(ts.hour)).lower()
    return SESSION_MAP.get(raw, "off_session")


def _infer_atr_percentile(signal: dict[str, Any]) -> float:
    vol_state = str(signal.get("volatility_state") or "NORMAL").upper()
    return VOLATILITY_TO_ATR.get(vol_state, 45.0)


def _pf_from_labels(labels: list[int]) -> dict[str, float | int]:
    if not labels:
        return {"pf": 0.0, "trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0}
    wins = sum(labels)
    losses = len(labels) - wins
    pf = wins / losses if losses > 0 else (2.0 if wins > 0 else 0.0)
    return {
        "pf": round(pf, 4),
        "trades": len(labels),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": round(wins / len(labels) * 100, 2),
    }


def _signal_key(signal: dict[str, Any]) -> tuple | None:
    direction = str(signal.get("direction") or "")
    if direction not in ("BUY", "SELL"):
        return None
    try:
        ts = pd.to_datetime(signal["timestamp"], utc=True)
    except (KeyError, TypeError, ValueError):
        return None
    return ts, direction


def _build_v7_label_index(df: pd.DataFrame) -> dict[tuple, int]:
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work["dir_str"] = work["direction"].map({1: "BUY", -1: "SELL"})
    index: dict[tuple, int] = {}
    for _, row in work.iterrows():
        if pd.isna(row.get("label_v3")) or row["label_v3"] not in (0, 1):
            continue
        key = (row["timestamp"], row["dir_str"])
        index[key] = int(row["label_v3"])
    return index


def _load_hc_trend_signals(cache_dir: Path, *, confidence_threshold: float = PRIMARY_THRESHOLD) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for label in CACHE_LABELS:
        path = cache_dir / f"ml_signals_fullest_{label}.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for sig in payload.get("signals") or []:
            if str(sig.get("regime")) != "TREND":
                continue
            if float(sig.get("probability") or 0) < confidence_threshold:
                continue
            sid = str(sig.get("signal_id", ""))
            if sid and sid in seen_ids:
                continue
            if sid:
                seen_ids.add(sid)
            rec = dict(sig)
            rec["source_cache"] = label
            signals.append(rec)
    return signals


def _attach_v7_labels(
    signals: list[dict[str, Any]],
    label_index: dict[tuple, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    unmatched = 0
    for sig in signals:
        key = _signal_key(sig)
        if key is None or key not in label_index:
            unmatched += 1
            continue
        rec = dict(sig)
        rec["label_v3"] = label_index[key]
        rec["year"] = int(key[0].year)
        rec["session"] = _infer_session(str(sig.get("timestamp", "")))
        enriched.append(rec)
    return enriched, {
        "total_signals": len(signals),
        "matched_v7_labels": len(enriched),
        "unmatched": unmatched,
        "match_rate_pct": round(len(enriched) / max(len(signals), 1) * 100, 2),
    }


def _evaluate_shadow_tq(signal: dict[str, Any], *, quality_threshold: float = TQ_SHADOW_THRESHOLD) -> dict[str, Any]:
    from tradingbot.ml.research.phase63.trade_quality_shadow_calibration import _evaluate_shadow

    return _evaluate_shadow(
        signal,
        alias_policy=TQ_ALIAS_POLICY,
        quality_threshold=quality_threshold,
    )


def _build_ar_context(signal: dict[str, Any]) -> Any:
    from tradingbot.ml.decision_engine.decision_types import EngineSignal, MarketContext
    from tradingbot.ml.risk_intelligence.risk_types import AccountState, AdaptiveRiskContext, HistoricalMetrics

    ts = pd.to_datetime(signal["timestamp"], utc=True)
    direction = str(signal.get("direction") or "HOLD")
    prob = float(signal.get("probability") or 0)
    confidence = float(signal.get("confidence") or prob)
    engine_sig = EngineSignal(
        signal=direction if direction in ("BUY", "SELL") else "HOLD",
        confidence=confidence,
        model=str(signal.get("engine") or "trend_rf_v41"),
        probability=prob,
    )
    session = _infer_session(str(signal.get("timestamp", "")))
    market = MarketContext(
        symbol=str(signal.get("symbol") or "XAUUSD"),
        timeframe=str(signal.get("timeframe") or "M5"),
        features={},
        regime=str(signal.get("regime") or "TREND"),
        regime_strength=float(signal.get("adx") or 50.0) / 100.0,
        range_signal=engine_sig,
        trend_signal=engine_sig,
        volatility=_infer_atr_percentile(signal),
        session=session,
        timestamp=ts.to_pydatetime(),
    )
    return AdaptiveRiskContext(
        market=market,
        calibrated_confidence=confidence,
        action=direction,
        engine=str(signal.get("engine") or "trend_rf_v41"),
        regime=str(signal.get("regime") or "TREND"),
        atr_percentile=_infer_atr_percentile(signal),
        session=session,
        account=AccountState(),
        history=HistoricalMetrics(),
        timestamp=ts.to_pydatetime(),
    )


def _re_evaluate_adaptive_risk(signal: dict[str, Any]) -> dict[str, Any]:
    from tradingbot.ml.risk_intelligence.adaptive_risk_engine import AdaptiveRiskEngine

    ctx = _build_ar_context(signal)
    rec = AdaptiveRiskEngine().recommend(ctx)
    return {
        "allowed": rec.allowed,
        "risk_percent": rec.risk_percent,
        "blocked_by": rec.blocked_by,
        "reason": rec.reason,
        "confidence_factor": rec.confidence_factor,
        "regime_factor": rec.regime_factor,
        "volatility_factor": rec.volatility_factor,
        "session_factor": rec.session_factor,
        "drawdown_factor": rec.drawdown_factor,
        "engine_factor": rec.engine_factor,
        "trace": list(rec.trace or []),
    }


def _infer_block_reason(signal: dict[str, Any], ar_eval: dict[str, Any]) -> str:
    blocked_by = str(ar_eval.get("blocked_by") or "")
    if blocked_by:
        return blocked_by
    if not signal.get("risk_allowed", True):
        conf = float(signal.get("confidence") or signal.get("probability") or 0)
        if conf < MIN_CONFIDENCE_FOR_RISK:
            return "low_confidence"
    return "unknown"


def _numeric_stats(subset: list[dict[str, Any]], field: str) -> dict[str, float | None]:
    vals = [float(s[field]) for s in subset if s.get(field) is not None]
    if not vals:
        return {"mean": None, "median": None, "min": None, "max": None}
    arr = np.array(vals)
    return {
        "mean": round(float(arr.mean()), 4),
        "median": round(float(np.median(arr)), 4),
        "min": round(float(arr.min()), 4),
        "max": round(float(arr.max()), 4),
    }


def _identify_ar_blocked(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        s for s in signals
        if str(s.get("first_blocking_filter") or "") == "AdaptiveRisk"
        and float(s.get("probability") or 0) >= PRIMARY_THRESHOLD
    ]


def _characterize_ar_blocked(ar_blocked: list[dict[str, Any]]) -> dict[str, Any]:
    ar_evals: list[dict[str, Any]] = []
    block_reasons: Counter[str] = Counter()
    prob_bands: Counter[str] = Counter()
    conf_bands: Counter[str] = Counter()

    for sig in ar_blocked:
        ev = _re_evaluate_adaptive_risk(sig)
        reason = _infer_block_reason(sig, ev)
        ev["inferred_reason"] = reason
        ar_evals.append({"signal_id": sig.get("signal_id"), **ev})
        block_reasons[reason] += 1

        prob = float(sig.get("probability") or 0)
        conf = float(sig.get("confidence") or prob)
        if prob < 0.45:
            prob_bands["0.40-0.45"] += 1
        elif prob < 0.50:
            prob_bands["0.45-0.50"] += 1
        elif prob < 0.55:
            prob_bands["0.50-0.55"] += 1
        elif prob < 0.60:
            prob_bands["0.55-0.60"] += 1
        else:
            prob_bands["0.60+"] += 1

        if conf < MIN_CONFIDENCE_FOR_RISK:
            conf_bands[f"below_{MIN_CONFIDENCE_FOR_RISK}"] += 1
        else:
            conf_bands[f"at_or_above_{MIN_CONFIDENCE_FOR_RISK}"] += 1

    shadow_tq_pass = 0
    shadow_tq_fail = 0
    for sig in ar_blocked:
        if _evaluate_shadow_tq(sig).get("allowed"):
            shadow_tq_pass += 1
        else:
            shadow_tq_fail += 1

    return {
        "count": len(ar_blocked),
        "direction_distribution": dict(Counter(str(s.get("direction") or "") for s in ar_blocked)),
        "session_distribution": dict(Counter(str(s.get("session") or "unknown") for s in ar_blocked)),
        "source_cache_distribution": dict(Counter(str(s.get("source_cache") or "") for s in ar_blocked)),
        "volatility_state_distribution": dict(
            Counter(str(s.get("volatility_state") or "UNKNOWN") for s in ar_blocked)
        ),
        "probability_bands": dict(prob_bands),
        "confidence_bands": dict(conf_bands),
        "probability_stats": _numeric_stats(ar_blocked, "probability"),
        "confidence_stats": _numeric_stats(ar_blocked, "confidence"),
        "risk_allowed_distribution": dict(Counter(bool(s.get("risk_allowed")) for s in ar_blocked)),
        "quality_allowed_distribution": dict(Counter(bool(s.get("quality_allowed")) for s in ar_blocked)),
        "block_reasons": dict(block_reasons.most_common()),
        "primary_block_reason": block_reasons.most_common(1)[0][0] if block_reasons else None,
        "shadow_tq_alias_pass_count": shadow_tq_pass,
        "shadow_tq_alias_fail_count": shadow_tq_fail,
        "shadow_tq_alias_pass_pct": round(shadow_tq_pass / max(len(ar_blocked), 1) * 100, 2),
        "numeric_profile": {
            f: _numeric_stats(ar_blocked, f)
            for f in ("adx", "atr", "rsi", "spread_pips", "probability", "confidence", "quality_score")
        },
        "high_rsi_blocked_pct": round(
            sum(1 for s in ar_blocked if float(s.get("rsi") or 0) > 70) / max(len(ar_blocked), 1) * 100,
            2,
        ),
        "high_adx_blocked_pct": round(
            sum(1 for s in ar_blocked if float(s.get("adx") or 0) > 40) / max(len(ar_blocked), 1) * 100,
            2,
        ),
        "per_signal_ar_re_eval_sample": ar_evals[:5],
    }


def _passes_path_b64(signal: dict[str, Any]) -> bool:
    """Phase63 TQ alias + production AdaptiveRisk must allow."""
    if not _evaluate_shadow_tq(signal).get("allowed"):
        return False
    return bool(signal.get("risk_allowed"))


def _passes_path_c64(signal: dict[str, Any]) -> bool:
    """Phase63 TQ alias; AdaptiveRisk bypassed."""
    return bool(_evaluate_shadow_tq(signal).get("allowed"))


def _path_metrics(
    signals: list[dict[str, Any]],
    path_name: str,
    path_filter,
) -> dict[str, Any]:
    captured = [s for s in signals if path_filter(s)]
    labels = [int(s["label_v3"]) for s in captured]
    pf = _pf_from_labels(labels)
    blockers = Counter(
        str(s.get("first_blocking_filter") or "none")
        for s in signals
        if not path_filter(s)
    )
    ar_only_blocked = sum(
        1 for s in signals
        if not path_filter(s)
        and _evaluate_shadow_tq(s).get("allowed")
        and not s.get("risk_allowed")
    )
    return {
        "path": path_name,
        "signals_total_hc": len(signals),
        "signals_captured": len(captured),
        "capture_rate_pct": round(len(captured) / max(len(signals), 1) * 100, 2),
        "pf_proxy_label_v3": pf,
        "blockers_remaining": dict(blockers),
        "ar_only_blocked_after_tq_alias": ar_only_blocked,
    }


def _per_year_breakdown(signals: list[dict[str, Any]], path_filter) -> dict[str, dict[str, Any]]:
    by_year: dict[str, list[int]] = defaultdict(list)
    totals: dict[str, int] = defaultdict(int)
    allowed_by_year: dict[str, int] = defaultdict(int)

    for sig in signals:
        year = str(sig.get("year", "unknown"))
        totals[year] += 1
        if not path_filter(sig):
            continue
        allowed_by_year[year] += 1
        by_year[year].append(int(sig["label_v3"]))

    out: dict[str, dict[str, Any]] = {}
    for year in sorted(totals):
        labels = by_year.get(year, [])
        pf = _pf_from_labels(labels)
        out[year] = {
            "signals_hc": totals[year],
            "captured_count": allowed_by_year[year],
            "capture_rate_pct": round(allowed_by_year[year] / max(totals[year], 1) * 100, 2),
            **pf,
        }
    return out


def _load_phase63_policy() -> dict[str, Any]:
    if PHASE63_POLICY.is_file():
        return json.loads(PHASE63_POLICY.read_text(encoding="utf-8"))
    return {
        "shadow_policy": {
            "quality_threshold_recommended": TQ_SHADOW_THRESHOLD,
            "alias_policy_primary": TQ_ALIAS_POLICY,
        }
    }


def _phase68_shadow_policy_recommendation(
    path_b: dict[str, Any],
    path_c: dict[str, Any],
    ar_char: dict[str, Any],
) -> dict[str, Any]:
    pf_b = float((path_b.get("pf_proxy_label_v3") or {}).get("pf") or 0)
    pf_c = float((path_c.get("pf_proxy_label_v3") or {}).get("pf") or 0)
    cap_b = float(path_b.get("capture_rate_pct") or 0)
    cap_c = float(path_c.get("capture_rate_pct") or 0)
    pf_delta = round(pf_c - pf_b, 4)
    cap_delta = round(cap_c - cap_b, 2)
    primary_reason = ar_char.get("primary_block_reason") or "low_confidence"

    worth_fixing = pf_delta > 0.05 or cap_delta > 5.0
    if primary_reason == "low_confidence" and pf_delta <= 0:
        recommendation = "keep_production_ar"
        rationale_en = (
            f"AR blocks {ar_char.get('count')} signals primarily due to {primary_reason} "
            f"(HC proxy 0.40 vs AR floor {MIN_CONFIDENCE_FOR_RISK}). "
            f"Bypassing AR adds {cap_delta}% capture but PF drops {abs(pf_delta):.4f} — "
            "keep production AR; align HC threshold with AR floor in phase68 if needed."
        )
        rationale_fa = (
            f"AR عمدتاً به‌خاطر {primary_reason} مسدود می‌کند. "
            f"bypass فقط {cap_delta}٪ capture اضافه می‌کند و PF را {abs(pf_delta):.4f} کاهش می‌دهد. "
            "AR تولید را نگه دارید."
        )
    elif worth_fixing:
        recommendation = "shadow_ar_relax_for_phase68"
        rationale_en = (
            "AR bypass shows material capture lift with acceptable PF delta — "
            "test relaxed AR policy in phase68 shadow only."
        )
        rationale_fa = "bypass AR در سایه capture بیشتری می‌دهد — فقط در فاز ۶۸ تست shadow."
    else:
        recommendation = "keep_production_ar"
        rationale_en = (
            "Minimal PF/capture delta between path B (TQ alias) and path C (TQ+AR bypass). "
            "No AR policy change recommended for phase68."
        )
        rationale_fa = (
            "تفاوت PF/capture بین مسیر B و C ناچیز است. "
            "تغییر policy AdaptiveRisk برای فاز ۶۸ پیشنهاد نمی‌شود."
        )

    return {
        "recommendation": recommendation,
        "worth_fixing": worth_fixing,
        "phase68_policy": {
            "trade_quality": {
                "engine_alias": "map_to_v40",
                "quality_threshold": TQ_SHADOW_THRESHOLD,
                "scope": "shadow_only",
            },
            "adaptive_risk": {
                "action": "keep_production" if recommendation == "keep_production_ar" else "shadow_relax",
                "min_confidence_floor": MIN_CONFIDENCE_FOR_RISK,
                "note_en": rationale_en,
            },
        },
        "rationale_en": rationale_en,
        "rationale_fa": rationale_fa,
        "path_comparison": {
            "path_b_capture_pct": cap_b,
            "path_c_capture_pct": cap_c,
            "capture_delta_pct": cap_delta,
            "path_b_pf": pf_b,
            "path_c_pf": pf_c,
            "pf_delta": pf_delta,
        },
    }


def analyze_adaptive_risk_shadow(*, cache_dir: Path = CACHE_DIR) -> dict[str, Any]:
    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": f"missing v7 labels: {V7_PATH}"}

    v7_df = pd.read_parquet(V7_PATH)
    label_index = _build_v7_label_index(v7_df)
    hc_signals = _load_hc_trend_signals(cache_dir)
    enriched, match_stats = _attach_v7_labels(hc_signals, label_index)
    if not enriched:
        return {"verdict": "INSUFFICIENT_DATA", "error": "no v7-matched HC TREND signals"}

    ar_blocked = _identify_ar_blocked(enriched)
    ar_characterization = _characterize_ar_blocked(ar_blocked)

    path_b64 = _path_metrics(enriched, "B_tq_alias_ar_production", _passes_path_b64)
    path_c64 = _path_metrics(enriched, "C_tq_alias_ar_bypass", _passes_path_c64)

    ar_labels = [int(s["label_v3"]) for s in ar_blocked]
    path_b_labels = [int(s["label_v3"]) for s in enriched if _passes_path_b64(s)]
    path_c_labels = [int(s["label_v3"]) for s in enriched if _passes_path_c64(s)]

    ar_only_recovered = [
        s for s in enriched
        if _passes_path_c64(s) and not _passes_path_b64(s)
    ]
    ar_only_labels = [int(s["label_v3"]) for s in ar_only_recovered]

    phase68_rec = _phase68_shadow_policy_recommendation(path_b64, path_c64, ar_characterization)
    phase63_policy = _load_phase63_policy()

    pf_b = float((path_b64.get("pf_proxy_label_v3") or {}).get("pf") or 0)
    pf_c = float((path_c64.get("pf_proxy_label_v3") or {}).get("pf") or 0)

    verdict = "AR_REVIEW_COMPLETE"
    if ar_characterization.get("count", 0) == 0:
        verdict = "NO_AR_BLOCKS_FOUND"

    return {
        "verdict": verdict,
        "research_only": True,
        "confidence_threshold_hc": PRIMARY_THRESHOLD,
        "tq_shadow_policy": {
            "alias_policy": TQ_ALIAS_POLICY,
            "quality_threshold": TQ_SHADOW_THRESHOLD,
            "source": str(PHASE63_POLICY.relative_to(ROOT)) if PHASE63_POLICY.is_file() else "defaults",
            "phase63_policy_loaded": PHASE63_POLICY.is_file(),
        },
        "signal_source": {
            "cache_hc_count_deduped": len(hc_signals),
            "v7_matched_count": len(enriched),
            "v7_label_match": match_stats,
        },
        "adaptive_risk_characterization": ar_characterization,
        "execution_paths": {
            "B_tq_alias_ar_production": path_b64,
            "C_tq_alias_ar_bypass": path_c64,
        },
        "path_comparison": {
            "phase61_reference": {
                "path_b_pf": 0.3741,
                "path_c_pf": 0.371,
                "pf_delta": -0.0031,
                "note": "phase61 used production TQ bypass, not phase63 alias",
            },
            "phase64_tq_alias": {
                "path_b_pf": pf_b,
                "path_c_pf": pf_c,
                "pf_delta": round(pf_c - pf_b, 4),
                "path_b_capture_pct": path_b64.get("capture_rate_pct"),
                "path_c_capture_pct": path_c64.get("capture_rate_pct"),
                "capture_delta_pct": round(
                    float(path_c64.get("capture_rate_pct") or 0) - float(path_b64.get("capture_rate_pct") or 0),
                    2,
                ),
            },
        },
        "ar_bypass_counterfactual": {
            "ar_blocked_count": len(ar_blocked),
            "ar_only_recovered_count": len(ar_only_recovered),
            "pf_ar_blocked_cohort": _pf_from_labels(ar_labels),
            "pf_ar_only_recovered": _pf_from_labels(ar_only_labels),
            "pf_path_b": _pf_from_labels(path_b_labels),
            "pf_path_c": _pf_from_labels(path_c_labels),
            "incremental_pf_if_ar_bypassed": round(pf_c - pf_b, 4),
        },
        "per_year_path_b": _per_year_breakdown(enriched, _passes_path_b64),
        "per_year_path_c": _per_year_breakdown(enriched, _passes_path_c64),
        "phase68_shadow_policy_recommendation": phase68_rec,
        "phase63_policy_snapshot": phase63_policy.get("shadow_policy"),
        "next_phase": "65",
        "next_phase_alternate": "68",
    }


def run_phase64() -> dict[str, Any]:
    analysis = analyze_adaptive_risk_shadow()
    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **analysis,
    }


def write_all(data: dict[str, Any]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    artifact = {k: v for k, v in data.items() if k != "now"}
    (ARTIFACTS / "adaptive_risk_shadow.json").write_text(
        json.dumps(artifact, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote phase64/artifacts/adaptive_risk_shadow.json", flush=True)

    paths = data.get("execution_paths") or {}
    path_b = paths.get("B_tq_alias_ar_production") or {}
    path_c = paths.get("C_tq_alias_ar_bypass") or {}
    ar_char = data.get("adaptive_risk_characterization") or {}
    phase68 = data.get("phase68_shadow_policy_recommendation") or {}

    report = {
        "phase": "64",
        "title": "AdaptiveRisk Shadow Review",
        "title_fa": "بررسی سایه AdaptiveRisk",
        "timestamp_utc": data["now"],
        "verdict": data.get("verdict"),
        "research_only": True,
        "signal_source": data.get("signal_source"),
        "adaptive_risk_characterization": ar_char,
        "execution_paths": paths,
        "path_comparison": data.get("path_comparison"),
        "ar_bypass_counterfactual": data.get("ar_bypass_counterfactual"),
        "per_year_path_b": data.get("per_year_path_b"),
        "per_year_path_c": data.get("per_year_path_c"),
        "phase68_shadow_policy_recommendation": phase68,
        "recommendation_en": phase68.get("rationale_en", ""),
        "recommendation_fa": phase68.get("rationale_fa", ""),
        "next_phase": data.get("next_phase", "65"),
    }
    (ROOT / "phase64_final_report.json").write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote phase64_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_fix_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    paths = data.get("execution_paths") or {}
    path_b = paths.get("B_tq_alias_ar_production") or {}
    path_c = paths.get("C_tq_alias_ar_bypass") or {}
    ar_char = data.get("adaptive_risk_characterization") or {}
    cmp64 = (data.get("path_comparison") or {}).get("phase64_tq_alias") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "FIX_PHASE_64_COMPLETE"
    status["current_treatment_phase"] = "64"
    status["next_step"] = report.get("recommendation_en", "")
    status.setdefault("fix_phases", {})["64"] = {
        "status": "COMPLETE",
        "track": "E",
        "verdict": report.get("verdict"),
        "report": "phase64_final_report.json",
    }
    status["phase64_summary"] = {
        "ar_blocked_count": ar_char.get("count"),
        "primary_block_reason": ar_char.get("primary_block_reason"),
        "path_b_capture_pct": path_b.get("capture_rate_pct"),
        "path_c_capture_pct": path_c.get("capture_rate_pct"),
        "path_b_pf": (path_b.get("pf_proxy_label_v3") or {}).get("pf"),
        "path_c_pf": (path_c.get("pf_proxy_label_v3") or {}).get("pf"),
        "pf_delta_path_c_vs_b": cmp64.get("pf_delta"),
        "worth_fixing_ar": (data.get("phase68_shadow_policy_recommendation") or {}).get("worth_fixing"),
        "phase68_ar_policy": (data.get("phase68_shadow_policy_recommendation") or {}).get("recommendation"),
    }
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_fix_roadmap(report: dict) -> None:
    path = ROOT / "FIX_ROADMAP.json"
    if not path.is_file():
        return
    fix = json.loads(path.read_text(encoding="utf-8"))
    for ph in fix.get("phases", []):
        if str(ph.get("phase")) == "64":
            ph["status"] = "COMPLETE"
            ph["verdict"] = report.get("verdict")
            break
    fix["updated_utc"] = report["timestamp_utc"]
    fix["pipeline"]["current_phase"] = "65"
    fix.setdefault("current_baseline", {})["shadow_pf_path_b"] = (
        (report.get("execution_paths") or {}).get("B_tq_alias_ar_production") or {}
    ).get("pf_proxy_label_v3", {}).get("pf")
    path.write_text(json.dumps(fix, indent=2), encoding="utf-8")
    print("  updated FIX_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase64()
    write_all(data)
    ar = data.get("adaptive_risk_characterization") or {}
    cmp64 = (data.get("path_comparison") or {}).get("phase64_tq_alias") or {}
    print(
        json.dumps(
            {
                "verdict": data.get("verdict"),
                "ar_blocked": ar.get("count"),
                "primary_block_reason": ar.get("primary_block_reason"),
                "path_b_pf": cmp64.get("path_b_pf"),
                "path_c_pf": cmp64.get("path_c_pf"),
                "pf_delta": cmp64.get("pf_delta"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
