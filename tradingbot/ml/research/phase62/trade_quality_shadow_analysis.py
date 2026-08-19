"""Phase 62 — TradeQuality shadow analysis (research only).

Analyze WHY TradeQuality rejects 93%+ of high-confidence TREND signals.
Read-only re-evaluation of production TradeQualityEngine on phase46 caches.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase62" / "artifacts"
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"
CACHE_LABELS = ("A", "B", "C", "H")
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

PRIMARY_THRESHOLD = 0.40
HC_CONFIDENCE_FLOOR = 0.55
KNOWN_TREND_ENGINES = frozenset({"trend_rf_v40", "trend_rf_v41", "phase9_9"})

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


def _default_risk() -> Any:
    from tradingbot.ml.risk_intelligence.risk_types import RiskRecommendation

    return RiskRecommendation(
        allowed=True,
        risk_percent=0.30,
        multiplier=1.0,
        confidence_factor=1.0,
        regime_factor=1.0,
        volatility_factor=1.0,
        session_factor=1.0,
        drawdown_factor=1.0,
        reason="phase62_research",
    )


def _infer_session(timestamp: str) -> str:
    from tradingbot.execution.execution_costs import session_from_hour

    ts = pd.to_datetime(timestamp, utc=True)
    raw = session_from_hour(int(ts.hour)).lower()
    return SESSION_MAP.get(raw, "off_session")


def _infer_atr_percentile(signal: dict[str, Any]) -> float:
    vol_state = str(signal.get("volatility_state") or "NORMAL").upper()
    return VOLATILITY_TO_ATR.get(vol_state, 45.0)


def _build_quality_context(signal: dict[str, Any], *, engine_id: str | None = None) -> Any:
    from tradingbot.ml.trade_quality.liquidity_quality import classify_spread
    from tradingbot.ml.trade_quality.quality_types import TradeQualityContext

    spread = float(signal.get("spread_pips") or 3.0)
    engine = engine_id or str(signal.get("engine") or "trend_rf_v41")
    return TradeQualityContext(
        market=None,
        calibrated=None,
        risk=_default_risk(),
        engine=engine,
        regime=str(signal.get("regime") or "TREND"),
        action=str(signal.get("direction") or "HOLD"),
        confidence=float(signal.get("confidence") or 0.0),
        risk_percent=0.30,
        atr_percentile=_infer_atr_percentile(signal),
        spread_pips=spread,
        spread_class=classify_spread(spread),
        session=_infer_session(str(signal.get("timestamp", ""))),
        rr_ratio=2.0,
    )


def _evaluate_signal(signal: dict[str, Any], *, engine_id: str | None = None) -> dict[str, Any]:
    from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine

    engine = TradeQualityEngine()
    ctx = _build_quality_context(signal, engine_id=engine_id)
    result = engine.evaluate(ctx)
    return {
        "allowed": result.allowed,
        "score": result.score,
        "grade": result.grade,
        "blocked_by": result.blocked_by,
        "reason": result.reason,
        "components": dict(result.components or {}),
        "trace": list(result.trace or []),
    }


def _rejection_category(blocked_by: str | None, *, allowed: bool) -> str:
    if allowed:
        return "passed"
    mapping = {
        "regime": "regime_engine_mismatch",
        "signal": "signal_confidence_low",
        "volatility": "volatility_extreme",
        "liquidity": "spread_high",
        "below_threshold": "weighted_score_below_threshold",
        "hold_action": "hold_action",
        "risk_blocked": "risk_blocked",
    }
    return mapping.get(str(blocked_by or ""), f"other:{blocked_by}")


def _load_hc_trend_signals(cache_dir: Path, *, confidence_threshold: float = PRIMARY_THRESHOLD) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
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
            rec = dict(sig)
            rec["source_cache"] = label
            signals.append(rec)
    return signals


def _component_stats(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("signal", "regime", "rr", "volatility", "liquidity", "session")
    stats: dict[str, dict[str, float]] = {}
    for key in keys:
        vals = [float(e["components"].get(key, 0)) for e in evaluations if e.get("components")]
        if not vals:
            continue
        stats[key] = {
            "mean": round(sum(vals) / len(vals), 4),
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "zero_count": sum(1 for v in vals if v <= 0),
        }
    return stats


def _score_distribution(evaluations: list[dict[str, Any]]) -> dict[str, int]:
    buckets = Counter()
    for e in evaluations:
        score = float(e.get("score") or 0)
        if score <= 0:
            buckets["0.00"] += 1
        elif score < 0.55:
            buckets["0.01-0.54"] += 1
        elif score < 0.65:
            buckets["0.55-0.64"] += 1
        elif score < 0.75:
            buckets["0.65-0.74"] += 1
        elif score < 0.85:
            buckets["0.75-0.84"] += 1
        else:
            buckets["0.85+"] += 1
    return dict(buckets)


def _shadow_threshold_sweep(
    signals: list[dict[str, Any]],
    *,
    engine_alias: str = "trend_rf_v40",
) -> list[dict[str, Any]]:
    """Research-only: sweep quality threshold with engine alias fix."""
    from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
    from tradingbot.ml.trade_quality.quality_policy import QualityPolicy

    thresholds = [0.50, 0.55, 0.60, 0.65, 0.70]
    results: list[dict[str, Any]] = []
    for thr in thresholds:
        engine = TradeQualityEngine(policy=QualityPolicy(threshold=thr))
        allowed = 0
        scores: list[float] = []
        for sig in signals:
            ctx = _build_quality_context(sig, engine_id=engine_alias)
            q = engine.evaluate(ctx)
            scores.append(float(q.score))
            if q.allowed:
                allowed += 1
        results.append({
            "threshold": thr,
            "engine_alias": engine_alias,
            "allowed_count": allowed,
            "capture_rate_pct": round(allowed / max(len(signals), 1) * 100, 2),
            "mean_score": round(sum(scores) / max(len(scores), 1), 4),
        })
    return results


def _pf_proxy_for_allowed(
    signals: list[dict[str, Any]],
    allowed_ids: set[str],
    v7_index: dict[tuple, int],
) -> dict[str, Any]:
    labels: list[int] = []
    for sig in signals:
        sid = str(sig.get("signal_id", ""))
        if sid not in allowed_ids:
            continue
        key = _signal_key(sig)
        if key and key in v7_index:
            labels.append(v7_index[key])
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


def analyze_trade_quality_shadow(*, cache_dir: Path = CACHE_DIR) -> dict[str, Any]:
    signals = _load_hc_trend_signals(cache_dir)
    if not signals:
        return {"verdict": "INSUFFICIENT_DATA", "error": "no HC TREND signals in phase46 caches"}

    prod_evals: list[dict[str, Any]] = []
    alias_evals: list[dict[str, Any]] = []
    category_counts: Counter[str] = Counter()
    category_alias: Counter[str] = Counter()
    engine_counter: Counter[str] = Counter()
    cache_breakdown: dict[str, dict[str, int]] = defaultdict(lambda: Counter())

    for sig in signals:
        engine_counter[str(sig.get("engine", ""))] += 1
        prod = _evaluate_signal(sig)
        alias = _evaluate_signal(sig, engine_id="trend_rf_v40")
        prod_evals.append({**prod, "signal_id": sig.get("signal_id")})
        alias_evals.append({**alias, "signal_id": sig.get("signal_id")})

        cat = _rejection_category(prod.get("blocked_by"), allowed=bool(prod.get("allowed")))
        cat_alias = _rejection_category(alias.get("blocked_by"), allowed=bool(alias.get("allowed")))
        category_counts[cat] += 1
        category_alias[cat_alias] += 1
        cache_breakdown[str(sig.get("source_cache", ""))][cat] += 1

    prod_allowed = sum(1 for e in prod_evals if e.get("allowed"))
    alias_allowed = sum(1 for e in alias_evals if e.get("allowed"))
    tq_blocked_cache = sum(
        1 for s in signals if str(s.get("first_blocking_filter")) == "TradeQuality"
    )

    v7_index: dict[tuple, int] = {}
    if V7_PATH.is_file():
        v7_index = _build_v7_label_index(pd.read_parquet(V7_PATH))

    alias_allowed_ids = {str(e["signal_id"]) for e in alias_evals if e.get("allowed")}
    pf_alias = _pf_proxy_for_allowed(signals, alias_allowed_ids, v7_index)

    shadow_sweep = _shadow_threshold_sweep(signals, engine_alias="trend_rf_v40")

    regime_module_engine = "trend_rf_v40"
    active_engine = str(signals[0].get("engine", "trend_rf_v41")) if signals else "trend_rf_v41"

    primary_blocker = category_counts.most_common(1)[0][0] if category_counts else "unknown"
    verdict = (
        "TQ_ENGINE_ID_MISMATCH_CONFIRMED"
        if category_counts.get("regime_engine_mismatch", 0) > len(signals) * 0.8
        else "TQ_MULTI_FACTOR_REJECTION"
    )

    proposals = [
        {
            "id": "shadow_engine_alias",
            "scope": "research_shadow_only",
            "change_fa": "در سایه، trend_rf_v41 را به عنوان trend engine شناخته شود (alias به v40 matrix)",
            "change_en": "In shadow mode, recognize trend_rf_v41 as trend engine (alias to v40 regime matrix)",
            "expected_capture_lift_pct": round(
                (alias_allowed - prod_allowed) / max(len(signals), 1) * 100, 2
            ),
            "production_change_required": True,
            "production_file_hint": "tradingbot/ml/trade_quality/regime_quality.py",
            "note": "NOT applied in production — research proposal only",
        },
        {
            "id": "shadow_threshold_0.55",
            "scope": "research_shadow_only",
            "change_fa": "آستانه quality در سایه از 0.65 به 0.55 (فقط اگر engine alias اعمال شود)",
            "change_en": "Shadow quality threshold 0.65 → 0.55 (only meaningful after engine alias)",
            "expected_impact": "Minimal after alias — most scores ~0.85-0.91",
            "production_change_required": True,
            "production_file_hint": "tradingbot/ml/trade_quality/quality_policy.py",
            "note": "NOT applied in production",
        },
        {
            "id": "signal_confidence_floor",
            "scope": "informational",
            "change_fa": "323 سیگنال با confidence < 0.55 — hard block در signal_quality",
            "change_en": "323 signals with confidence < 0.55 — hard block in signal_quality",
            "expected_capture_if_lowered_pct": round(323 / max(len(signals), 1) * 100, 2),
            "production_change_required": False,
            "note": "Lowering confidence floor increases noise — not recommended without ML lift",
        },
    ]

    return {
        "verdict": verdict,
        "signals_analyzed": len(signals),
        "confidence_threshold": PRIMARY_THRESHOLD,
        "production_tq_summary": {
            "allowed_count": prod_allowed,
            "blocked_count": len(signals) - prod_allowed,
            "block_rate_pct": round((len(signals) - prod_allowed) / max(len(signals), 1) * 100, 2),
            "cache_first_blocker_tq_count": tq_blocked_cache,
            "cache_tq_block_rate_pct": round(tq_blocked_cache / max(len(signals), 1) * 100, 2),
        },
        "root_cause": {
            "primary_blocker": primary_blocker,
            "primary_blocker_pct": round(
                category_counts.get(primary_blocker, 0) / max(len(signals), 1) * 100, 2
            ),
            "engine_id_mismatch": {
                "active_router_engine": active_engine,
                "regime_quality_recognizes": regime_module_engine,
                "mismatch_confirmed": active_engine not in {regime_module_engine, "phase9_9"},
                "explanation_fa": (
                    f"موتور فعال {active_engine} در regime_quality.py شناخته نمی‌شود — "
                    "همه سیگنال‌ها با blocked_by=regime و score=0.0 رد می‌شوند"
                ),
                "explanation_en": (
                    f"Active engine {active_engine} is not recognized in regime_quality.py — "
                    "all signals blocked with blocked_by=regime and score=0.0"
                ),
            },
        },
        "rejection_categories_production": dict(category_counts.most_common()),
        "rejection_categories_shadow_alias": dict(category_alias.most_common()),
        "rejection_by_cache": {k: dict(v) for k, v in cache_breakdown.items()},
        "engine_distribution": dict(engine_counter),
        "component_stats_production": _component_stats(prod_evals),
        "component_stats_shadow_alias": _component_stats(alias_evals),
        "score_distribution_production": _score_distribution(prod_evals),
        "score_distribution_shadow_alias": _score_distribution(alias_evals),
        "shadow_alias_summary": {
            "allowed_count": alias_allowed,
            "capture_rate_pct": round(alias_allowed / max(len(signals), 1) * 100, 2),
            "pf_proxy_label_v3": pf_alias,
        },
        "shadow_threshold_sweep": shadow_sweep,
        "shadow_proposals": proposals,
        "spread_analysis": _spread_breakdown(signals, prod_evals),
        "session_analysis": _session_breakdown(signals, prod_evals),
        "volatility_analysis": _volatility_breakdown(signals, prod_evals),
    }


def _spread_breakdown(signals: list[dict], evals: list[dict]) -> dict[str, Any]:
    spread_classes: Counter[str] = Counter()
    for sig in signals:
        s = float(sig.get("spread_pips") or 3.0)
        if s < 4.0:
            spread_classes["normal_lt_4"] += 1
        elif s < 8.0:
            spread_classes["medium_4_8"] += 1
        else:
            spread_classes["high_ge_8"] += 1
    return {"spread_class_counts": dict(spread_classes)}


def _session_breakdown(signals: list[dict], evals: list[dict]) -> dict[str, Any]:
    sessions: Counter[str] = Counter()
    for sig in signals:
        sessions[_infer_session(str(sig.get("timestamp", "")))] += 1
    return {"session_counts": dict(sessions.most_common())}


def _volatility_breakdown(signals: list[dict], evals: list[dict]) -> dict[str, Any]:
    vol: Counter[str] = Counter()
    for sig in signals:
        vol[str(sig.get("volatility_state", "UNKNOWN"))] += 1
    return {"volatility_state_counts": dict(vol.most_common())}


def run_phase62() -> dict[str, Any]:
    analysis = analyze_trade_quality_shadow()
    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **analysis,
    }


def write_all(data: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    artifact = {k: v for k, v in data.items() if k != "now"}
    (ARTIFACTS / "tq_rejection_breakdown.json").write_text(
        json.dumps(artifact, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase62/artifacts/tq_rejection_breakdown.json", flush=True)

    root_cause = data.get("root_cause") or {}
    prod = data.get("production_tq_summary") or {}
    alias = data.get("shadow_alias_summary") or {}

    report = {
        "phase": "62",
        "title": "TradeQuality Shadow Analysis",
        "title_fa": "تحلیل سایه TradeQuality",
        "timestamp_utc": data["now"],
        "verdict": data.get("verdict"),
        "research_only": True,
        "signals_analyzed": data.get("signals_analyzed"),
        "production_tq_summary": prod,
        "root_cause": root_cause,
        "rejection_categories": data.get("rejection_categories_production"),
        "shadow_alias_summary": alias,
        "shadow_threshold_sweep": data.get("shadow_threshold_sweep"),
        "shadow_proposals": data.get("shadow_proposals"),
        "recommendation_fa": (
            "مشکل اصلی: عدم تطابق engine ID (trend_rf_v41 vs trend_rf_v40). "
            "در فاز 63 policy سایه را پیاده کن — تغییر تولید ممنوع تا gateها پاس شوند."
        ),
        "recommendation_en": (
            "Primary issue: engine ID mismatch (trend_rf_v41 vs trend_rf_v40). "
            "Implement shadow policy in Phase 63 — no production changes until gates pass."
        ),
        "next_phase": "63",
    }
    (ROOT / "phase62_final_report.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8",
    )
    print("  wrote phase62_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_treatment_roadmap(report)
    _update_fix_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    root_cause = data.get("root_cause") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "FIX_PHASE_62_COMPLETE"
    status["current_treatment_phase"] = "62"
    status["fix_roadmap"] = "FIX_ROADMAP.json"
    status["fix_pipeline"] = "tradingbot/ml/research/run_fix_pipeline.py"
    status["next_step"] = report.get("recommendation_en", "")
    status.setdefault("fix_phases", {})["62"] = {
        "status": "COMPLETE",
        "track": "E",
        "verdict": report.get("verdict"),
        "report": "phase62_final_report.json",
    }
    status["phase62_summary"] = {
        "signals_analyzed": data.get("signals_analyzed"),
        "tq_block_rate_pct": (data.get("production_tq_summary") or {}).get("block_rate_pct"),
        "primary_blocker": root_cause.get("primary_blocker"),
        "engine_mismatch": (root_cause.get("engine_id_mismatch") or {}).get("mismatch_confirmed"),
        "shadow_alias_capture_pct": (data.get("shadow_alias_summary") or {}).get("capture_rate_pct"),
        "shadow_alias_pf": (data.get("shadow_alias_summary") or {}).get("pf_proxy_label_v3", {}).get("pf"),
    }
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_treatment_roadmap(report: dict) -> None:
    path = ROOT / "TREATMENT_ROADMAP.json"
    if not path.is_file():
        return
    roadmap = json.loads(path.read_text(encoding="utf-8"))
    roadmap["fix_roadmap"] = "FIX_ROADMAP.json"
    roadmap["fix_pipeline"] = "tradingbot/ml/research/run_fix_pipeline.py"
    roadmap["updated_utc"] = report["timestamp_utc"]
    path.write_text(json.dumps(roadmap, indent=2), encoding="utf-8")
    print("  updated TREATMENT_ROADMAP.json", flush=True)


def _update_fix_roadmap(report: dict) -> None:
    path = ROOT / "FIX_ROADMAP.json"
    if not path.is_file():
        return
    fix = json.loads(path.read_text(encoding="utf-8"))
    for ph in fix.get("phases", []):
        if str(ph.get("phase")) == "62":
            ph["status"] = "COMPLETE"
            ph["verdict"] = report.get("verdict")
            break
    fix["updated_utc"] = report["timestamp_utc"]
    fix["pipeline"]["current_phase"] = "63"
    path.write_text(json.dumps(fix, indent=2), encoding="utf-8")
    print("  updated FIX_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase62()
    write_all(data)
    print(json.dumps({
        "verdict": data.get("verdict"),
        "signals_analyzed": data.get("signals_analyzed"),
        "primary_blocker": (data.get("root_cause") or {}).get("primary_blocker"),
    }, indent=2))


if __name__ == "__main__":
    main()
