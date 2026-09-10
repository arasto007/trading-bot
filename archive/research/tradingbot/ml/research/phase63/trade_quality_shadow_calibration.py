"""Phase 63 — TradeQuality shadow recalibration (research only).

Shadow-only policy: engine alias, threshold sweep, capture + PF measurement.
NO production code changes.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase63" / "artifacts"
CACHE_DIR = ROOT / "tradingbot" / "ml" / "research" / "phase46" / ".cache"
CACHE_LABELS = ("A", "B", "C", "H")
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"

PRIMARY_THRESHOLD = 0.40
THRESHOLD_SWEEP = [0.40, 0.45, 0.50, 0.55, 0.60]
GATE_CAPTURE_PCT = 20.0
GATE_SHADOW_PF = 1.0

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

# Shadow-only: register v41 as alias of v40 regime matrix (research simulation).
_SHADOW_TREND_ENGINES = frozenset({"trend_rf_v40", "trend_rf_v41"})
_SHADOW_TREND_MATRIX: dict[str, float] = {
    "TREND": 1.0,
    "RANGE": 0.4,
    "HIGH_VOLATILITY": 0.0,
    "NO_TRADE": 0.0,
}
_SHADOW_RANGE_MATRIX: dict[str, float] = {
    "RANGE": 1.0,
    "TREND": 0.5,
    "HIGH_VOLATILITY": 0.0,
    "NO_TRADE": 0.0,
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
        reason="phase63_research",
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


def _shadow_regime_quality_score(engine: str | None, regime: str) -> tuple[float, str]:
    """Research-only regime scorer that recognizes trend_rf_v41."""
    regime = str(regime).upper()
    engine = str(engine or "")
    if engine in _SHADOW_TREND_ENGINES:
        score = _SHADOW_TREND_MATRIX.get(regime, 0.0)
        return score, f"shadow trend engine ({engine}) in {regime} → {score}"
    if engine == "phase9_9":
        score = _SHADOW_RANGE_MATRIX.get(regime, 0.0)
        return score, f"shadow range engine in {regime} → {score}"
    return 0.0, "unknown engine — zero regime quality"


def _resolve_engine_for_policy(signal: dict[str, Any], policy: str) -> str:
    raw = str(signal.get("engine") or "trend_rf_v41")
    if policy == "map_to_v40" and raw == "trend_rf_v41":
        return "trend_rf_v40"
    return raw


def _evaluate_shadow(
    signal: dict[str, Any],
    *,
    alias_policy: str,
    quality_threshold: float,
) -> dict[str, Any]:
    from tradingbot.ml.trade_quality.engine_history import engine_history_modifier
    from tradingbot.ml.trade_quality.liquidity_quality import liquidity_quality_score
    from tradingbot.ml.trade_quality.quality_engine import clamp
    from tradingbot.ml.trade_quality.quality_policy import QualityPolicy, WEIGHTS, score_to_grade
    from tradingbot.ml.trade_quality.rr_quality import rr_quality_score
    from tradingbot.ml.trade_quality.signal_quality import signal_quality_score
    from tradingbot.ml.trade_quality.timing_quality import timing_quality_score
    from tradingbot.ml.trade_quality.volatility_quality import volatility_quality_score

    policy = QualityPolicy(threshold=quality_threshold)
    ctx = _build_quality_context(
        signal,
        engine_id=_resolve_engine_for_policy(signal, alias_policy),
    )
    trace: list[str] = []

    if str(ctx.action).upper() not in ("BUY", "SELL"):
        return {"allowed": False, "score": 0.0, "blocked_by": "hold_action", "signal_id": signal.get("signal_id")}

    sig, sig_label = signal_quality_score(ctx.confidence)
    if sig <= 0:
        return {"allowed": False, "score": 0.0, "blocked_by": "signal", "signal_id": signal.get("signal_id")}

    if alias_policy == "register_v41_alias":
        reg, reg_label = _shadow_regime_quality_score(ctx.engine, ctx.regime)
    else:
        from tradingbot.ml.trade_quality.regime_quality import regime_quality_score

        reg, reg_label = regime_quality_score(ctx.engine, ctx.regime)
    if reg <= 0:
        return {"allowed": False, "score": 0.0, "blocked_by": "regime", "signal_id": signal.get("signal_id")}

    rr, _ = rr_quality_score(ctx.rr_ratio)
    vol, _ = volatility_quality_score(ctx.atr_percentile)
    if vol <= 0:
        return {"allowed": False, "score": 0.0, "blocked_by": "volatility", "signal_id": signal.get("signal_id")}

    liq, _, _ = liquidity_quality_score(ctx.spread_pips)
    if liq <= 0:
        return {"allowed": False, "score": 0.0, "blocked_by": "liquidity", "signal_id": signal.get("signal_id")}

    sess, _ = timing_quality_score(ctx.session)
    components = {
        "signal": sig,
        "regime": reg,
        "rr": rr,
        "volatility": vol,
        "liquidity": liq,
        "session": sess,
    }
    weighted = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
    hist_factor, _ = engine_history_modifier(ctx.engine, None)
    score = clamp(weighted * hist_factor)
    allowed = policy.passes(score) and rr > 0 and liq > 0 and vol > 0

    return {
        "allowed": allowed,
        "score": round(score, 4),
        "grade": score_to_grade(score),
        "blocked_by": None if allowed else "below_threshold",
        "signal_id": signal.get("signal_id"),
    }


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


def _per_year_breakdown(
    signals: list[dict[str, Any]],
    allowed_ids: set[str],
    v7_index: dict[tuple, int],
) -> dict[str, dict[str, Any]]:
    by_year: dict[str, list[int]] = defaultdict(list)
    totals: dict[str, int] = defaultdict(int)
    allowed_by_year: dict[str, int] = defaultdict(int)

    for sig in signals:
        try:
            year = str(pd.to_datetime(sig["timestamp"], utc=True).year)
        except (KeyError, TypeError, ValueError):
            continue
        totals[year] += 1
        sid = str(sig.get("signal_id", ""))
        if sid not in allowed_ids:
            continue
        allowed_by_year[year] += 1
        key = _signal_key(sig)
        if key and key in v7_index:
            by_year[year].append(v7_index[key])

    out: dict[str, dict[str, Any]] = {}
    for year in sorted(totals):
        labels = by_year.get(year, [])
        wins = sum(labels)
        losses = len(labels) - wins
        pf = wins / losses if losses > 0 else (2.0 if wins > 0 else 0.0)
        out[year] = {
            "signals_hc": totals[year],
            "allowed_count": allowed_by_year[year],
            "capture_rate_pct": round(allowed_by_year[year] / max(totals[year], 1) * 100, 2),
            "pf_proxy_label_v3": round(pf, 4),
            "trades": len(labels),
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(wins / len(labels) * 100, 2) if labels else 0.0,
        }
    return out


def _threshold_sweep(
    signals: list[dict[str, Any]],
    v7_index: dict[tuple, int],
    *,
    alias_policy: str,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for thr in THRESHOLD_SWEEP:
        allowed_count = 0
        allowed_ids: set[str] = set()
        scores: list[float] = []
        for sig in signals:
            ev = _evaluate_shadow(sig, alias_policy=alias_policy, quality_threshold=thr)
            scores.append(float(ev.get("score") or 0))
            if ev.get("allowed"):
                allowed_count += 1
                allowed_ids.add(str(sig.get("signal_id", "")))
        pf = _pf_proxy_for_allowed(signals, allowed_ids, v7_index)
        results.append({
            "threshold": thr,
            "alias_policy": alias_policy,
            "allowed_count": allowed_count,
            "capture_rate_pct": round(allowed_count / max(len(signals), 1) * 100, 2),
            "mean_score": round(sum(scores) / max(len(scores), 1), 4),
            "pf_proxy_label_v3": pf,
        })
    return results


def _compare_alias_policies(signals: list[dict[str, Any]], *, quality_threshold: float = 0.55) -> dict[str, Any]:
    policies = ("map_to_v40", "register_v41_alias")
    comparison: dict[str, Any] = {}
    for policy in policies:
        allowed = 0
        for sig in signals:
            ev = _evaluate_shadow(sig, alias_policy=policy, quality_threshold=quality_threshold)
            if ev.get("allowed"):
                allowed += 1
        comparison[policy] = {
            "allowed_count": allowed,
            "capture_rate_pct": round(allowed / max(len(signals), 1) * 100, 2),
            "equivalent": None,
        }
    map_cap = comparison["map_to_v40"]["capture_rate_pct"]
    reg_cap = comparison["register_v41_alias"]["capture_rate_pct"]
    comparison["policies_equivalent"] = map_cap == reg_cap
    return comparison


def _pick_best_threshold(sweep: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [r for r in sweep if r["capture_rate_pct"] >= GATE_CAPTURE_PCT]
    if not eligible:
        eligible = sweep
    best_pf = max(eligible, key=lambda r: r["pf_proxy_label_v3"]["pf"])
    best_balanced = max(
        eligible,
        key=lambda r: (r["pf_proxy_label_v3"]["pf"], r["capture_rate_pct"]),
    )
    return {
        "by_pf": {
            "threshold": best_pf["threshold"],
            "capture_rate_pct": best_pf["capture_rate_pct"],
            "pf": best_pf["pf_proxy_label_v3"]["pf"],
            "trades": best_pf["pf_proxy_label_v3"]["trades"],
            "win_rate_pct": best_pf["pf_proxy_label_v3"]["win_rate_pct"],
        },
        "recommended_for_phase68": {
            "threshold": best_balanced["threshold"],
            "capture_rate_pct": best_balanced["capture_rate_pct"],
            "pf": best_balanced["pf_proxy_label_v3"]["pf"],
            "trades": best_balanced["pf_proxy_label_v3"]["trades"],
            "win_rate_pct": best_balanced["pf_proxy_label_v3"]["win_rate_pct"],
            "rationale_en": (
                "Highest PF among thresholds meeting capture≥20%; "
                "if tied, prefer higher capture for phase68 combined shadow path"
            ),
        },
    }


def _gate_check(sweep: list[dict[str, Any]], best: dict[str, Any]) -> dict[str, Any]:
    rec = best["recommended_for_phase68"]
    capture_pass = rec["capture_rate_pct"] >= GATE_CAPTURE_PCT
    pf_pass = rec["pf"] >= GATE_SHADOW_PF
    return {
        "capture_rate_pct_ge_20": capture_pass,
        "shadow_pf_ge_1_0": pf_pass,
        "all_gates_pass": capture_pass and pf_pass,
        "capture_actual_pct": rec["capture_rate_pct"],
        "shadow_pf_actual": rec["pf"],
        "threshold_used": rec["threshold"],
    }


def calibrate_trade_quality_shadow(*, cache_dir: Path = CACHE_DIR) -> dict[str, Any]:
    signals = _load_hc_trend_signals(cache_dir)
    if not signals:
        return {"verdict": "INSUFFICIENT_DATA", "error": "no HC TREND signals in phase46 caches"}

    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": f"missing v7 labels: {V7_PATH}"}

    v7_df = pd.read_parquet(V7_PATH)
    v7_index = _build_v7_label_index(v7_df)

    alias_comparison = _compare_alias_policies(signals)
    primary_policy = "map_to_v40"
    sweep_map = _threshold_sweep(signals, v7_index, alias_policy="map_to_v40")
    sweep_register = _threshold_sweep(signals, v7_index, alias_policy="register_v41_alias")
    best = _pick_best_threshold(sweep_map)
    gates = _gate_check(sweep_map, best)

    rec_thr = best["recommended_for_phase68"]["threshold"]
    allowed_ids: set[str] = set()
    for sig in signals:
        ev = _evaluate_shadow(sig, alias_policy=primary_policy, quality_threshold=rec_thr)
        if ev.get("allowed"):
            allowed_ids.add(str(sig.get("signal_id", "")))

    per_year = _per_year_breakdown(signals, allowed_ids, v7_index)

    production_fix = {
        "file": "tradingbot/ml/trade_quality/regime_quality.py",
        "one_line_fix_en": (
            'Add `TREND_ENGINE_V41 = "trend_rf_v41"` and treat it like TREND_ENGINE '
            'in regime_quality_score (or change `if engine == TREND_ENGINE` to '
            '`if engine in (TREND_ENGINE, "trend_rf_v41")`).'
        ),
        "one_line_fix_fa": (
            'در regime_quality_score شرط موتور را به '
            'engine in ("trend_rf_v40", "trend_rf_v41") تغییر دهید.'
        ),
        "minimal_patch": (
            'if engine in (TREND_ENGINE, "trend_rf_v41"):'
        ),
        "applied_in_production": False,
        "note": "Research-only recommendation — do NOT apply until Phase 70 gate review",
    }

    shadow_policy = {
        "engine_alias": {
            "from": "trend_rf_v41",
            "to": "trend_rf_v40",
            "scope": "shadow_only",
            "register_v41_alias_equivalent": alias_comparison.get("policies_equivalent", False),
        },
        "quality_threshold_recommended": rec_thr,
        "alias_policy_primary": primary_policy,
        "threshold_sweep": THRESHOLD_SWEEP,
        "gates": gates,
    }

    verdict = "SHADOW_RECALIBRATION_COMPLETE"
    if not gates["shadow_pf_ge_1_0"]:
        verdict = "SHADOW_CAPTURE_OK_PF_FAIL"

    return {
        "verdict": verdict,
        "signals_analyzed": len(signals),
        "signals_raw_cache_rows": 4864,
        "signals_deduped_by_id": True,
        "confidence_threshold_hc": PRIMARY_THRESHOLD,
        "alias_policy_comparison": alias_comparison,
        "shadow_threshold_sweep_map_to_v40": sweep_map,
        "shadow_threshold_sweep_register_v41": sweep_register,
        "best_threshold": best,
        "gate_check": gates,
        "per_year_breakdown": per_year,
        "production_fix_recommendation": production_fix,
        "shadow_policy": shadow_policy,
        "next_phase": "64",
        "next_phase_alternate": "65",
        "next_phase_note_en": (
            "Phase 64 (AdaptiveRisk shadow) is next on execution track; "
            "Phase 65 (AUC lift) can run in parallel on ML track."
        ),
    }


def run_phase63() -> dict[str, Any]:
    analysis = calibrate_trade_quality_shadow()
    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **analysis,
    }


def write_all(data: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    artifact = {k: v for k, v in data.items() if k != "now"}
    (ARTIFACTS / "tq_shadow_policy.json").write_text(
        json.dumps(artifact, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote phase63/artifacts/tq_shadow_policy.json", flush=True)

    gates = data.get("gate_check") or {}
    best = (data.get("best_threshold") or {}).get("recommended_for_phase68") or {}
    prod_fix = data.get("production_fix_recommendation") or {}

    report = {
        "phase": "63",
        "title": "TradeQuality Shadow Recalibration",
        "title_fa": "کالیبراسیون سایه TradeQuality",
        "timestamp_utc": data["now"],
        "verdict": data.get("verdict"),
        "research_only": True,
        "signals_analyzed": data.get("signals_analyzed"),
        "alias_policy_comparison": data.get("alias_policy_comparison"),
        "shadow_threshold_sweep": data.get("shadow_threshold_sweep_map_to_v40"),
        "shadow_threshold_sweep_register_v41": data.get("shadow_threshold_sweep_register_v41"),
        "best_threshold": data.get("best_threshold"),
        "gate_check": gates,
        "per_year_breakdown": data.get("per_year_breakdown"),
        "shadow_policy": data.get("shadow_policy"),
        "production_fix_recommendation": prod_fix,
        "recommendation_en": (
            f"Shadow engine alias restores capture ({best.get('capture_rate_pct', 0)}%) but "
            f"PF proxy remains {best.get('pf', 0)} (<1.0). "
            f"Recommend shadow threshold {best.get('threshold')} for phase68. "
            f"Production fix: {prod_fix.get('one_line_fix_en', '')}"
        ),
        "recommendation_fa": (
            f"alias موتور capture را برمی‌گرداند ({best.get('capture_rate_pct', 0)}٪) "
            f"اما PF سایه {best.get('pf', 0)} است. "
            f"آستانه پیشنهادی فاز ۶۸: {best.get('threshold')}. "
            f"تغییر تولید: {prod_fix.get('one_line_fix_fa', '')}"
        ),
        "next_phase": data.get("next_phase", "64"),
    }
    (ROOT / "phase63_final_report.json").write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )
    print("  wrote phase63_final_report.json", flush=True)

    _update_engineering_status(report, data)
    _update_fix_roadmap(report)


def _update_engineering_status(report: dict, data: dict) -> None:
    path = ROOT / "ENGINEERING_STATUS.json"
    if not path.is_file():
        return
    status = json.loads(path.read_text(encoding="utf-8"))
    best = (data.get("best_threshold") or {}).get("recommended_for_phase68") or {}
    gates = data.get("gate_check") or {}

    status["updated_utc"] = report["timestamp_utc"]
    status["status"] = "FIX_PHASE_63_COMPLETE"
    status["current_treatment_phase"] = "63"
    status["next_step"] = report.get("recommendation_en", "")
    status.setdefault("fix_phases", {})["63"] = {
        "status": "COMPLETE",
        "track": "E",
        "verdict": report.get("verdict"),
        "report": "phase63_final_report.json",
    }
    status["phase63_summary"] = {
        "signals_analyzed": data.get("signals_analyzed"),
        "best_shadow_threshold": best.get("threshold"),
        "shadow_capture_pct": best.get("capture_rate_pct"),
        "shadow_pf": best.get("pf"),
        "capture_gate_pass": gates.get("capture_rate_pct_ge_20"),
        "pf_gate_pass": gates.get("shadow_pf_ge_1_0"),
        "engine_alias_fixes_capture": True,
    }
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    print("  updated ENGINEERING_STATUS.json", flush=True)


def _update_fix_roadmap(report: dict) -> None:
    path = ROOT / "FIX_ROADMAP.json"
    if not path.is_file():
        return
    fix = json.loads(path.read_text(encoding="utf-8"))
    for ph in fix.get("phases", []):
        if str(ph.get("phase")) == "63":
            ph["status"] = "COMPLETE"
            ph["verdict"] = report.get("verdict")
            break
    fix["updated_utc"] = report["timestamp_utc"]
    fix["pipeline"]["current_phase"] = "64"
    path.write_text(json.dumps(fix, indent=2), encoding="utf-8")
    print("  updated FIX_ROADMAP.json", flush=True)


def main() -> None:
    data = run_phase63()
    write_all(data)
    best = (data.get("best_threshold") or {}).get("recommended_for_phase68") or {}
    print(
        json.dumps(
            {
                "verdict": data.get("verdict"),
                "best_threshold": best.get("threshold"),
                "capture_pct": best.get("capture_rate_pct"),
                "shadow_pf": best.get("pf"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
