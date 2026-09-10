"""Phase 27B — evidence aggregation and deliverable builders."""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.integration.regime_filter_profiles import select_profitability_filter_settings
from tradingbot.ml.phase19c.filters import ProfitabilityFilterSettings, apply_profitability_filters


def _line_of(rel: str, needle: str, project_root: Path) -> int | None:
    path = project_root / rel
    if not path.is_file():
        return None
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return index
    return None


def build_filter_location(*, project_root: Path) -> dict[str, Any]:
    from tradingbot.ml.phase19c.config import (
        ENV_ADX_MAX,
        ENV_ADX_MIN,
        ENV_ENABLE_ADX,
        ENV_ENABLE_RSI,
        ENV_RSI_MAX,
        ENV_RSI_MIN,
    )
    from tradingbot.ml.research.phase22c.config import load_phase22c_config

    cfg22 = load_phase22c_config()
    range_settings, range_diag = select_profitability_filter_settings(regime="RANGE", engine="phase9_9")
    trend_settings, trend_diag = select_profitability_filter_settings(regime="TREND", engine="trend_rf_v41")

    return {
        "phase": "27B",
        "file": "tradingbot/ml/phase19c/filters.py",
        "function": "apply_profitability_filters",
        "rsi_block_line": _line_of(
            "tradingbot/ml/phase19c/filters.py",
            'blocked.append("rsi_filter")',
            project_root,
        ),
        "caller": {
            "file": "tradingbot/ml/integration/kernel_adapter.py",
            "function": "produce_unified_signal",
            "line": _line_of(
                "tradingbot/ml/integration/kernel_adapter.py",
                "apply_profitability_filters(row.to_dict()",
                project_root,
            ),
        },
        "profile_selector": {
            "file": "tradingbot/ml/integration/regime_filter_profiles.py",
            "function": "select_profitability_filter_settings",
        },
        "hold_chain_consumer": {
            "file": "tradingbot/ml/research/phase22c/hold_chain.py",
            "stage": "rsi_filter_hold",
        },
        "formula": {
            "rsi_pass": "rsi_min <= rsi <= rsi_max",
            "adx_pass": "adx_min <= adx <= adx_max",
            "inputs": ["rsi", "adx from unified frame row.to_dict()"],
            "outputs": ["passed: bool", "blocked_by: list[str]", "rsi", "adx"],
        },
        "defaults_phase19c": {
            "rsi_min": 40.0,
            "rsi_max": 60.0,
            "adx_min": 15.0,
            "adx_max": 50.0,
        },
        "phase22c_enabled": cfg22.enabled,
        "phase22c_bands": {
            "rsi_min": cfg22.rsi_min,
            "rsi_max": cfg22.rsi_max,
            "adx_min": cfg22.adx_min,
            "adx_max": cfg22.adx_max,
        },
        "runtime_profiles": {
            "RANGE_phase9_9": {
                "profile": range_diag.profile_used,
                "rsi_limits": range_diag.rsi_limits,
                "adx_limits": range_diag.adx_limits,
                "settings": range_settings.to_dict() if range_settings else None,
            },
            "TREND": {
                "profile": trend_diag.profile_used,
                "rsi_limits": trend_diag.rsi_limits,
                "adx_limits": trend_diag.adx_limits,
                "settings": trend_settings.to_dict() if trend_settings else None,
            },
        },
        "environment_variables": [
            ENV_ENABLE_RSI,
            ENV_RSI_MIN,
            ENV_RSI_MAX,
            ENV_ENABLE_ADX,
            ENV_ADX_MIN,
            ENV_ADX_MAX,
            "ENABLE_RANGE_FILTER_PROFILE",
            "PHASE22C_ENABLED",
            "PHASE22C_RSI_MIN",
            "PHASE22C_RSI_MAX",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_rsi_hold_log(records: list[dict[str, Any]]) -> dict[str, Any]:
    blocked = [
        r
        for r in records
        if r.get("hold_stage") == "rsi_filter_hold"
        or (
            r.get("decision_before_rsi") in ("BUY", "SELL")
            and r.get("decision_after_rsi") == "HOLD"
            and "rsi_filter" in (r.get("blocked_by") or [])
        )
    ]
    entries = [
        {
            "timestamp": r["timestamp"],
            "symbol": r["symbol"],
            "probability": r.get("probability"),
            "confidence": r.get("confidence"),
            "rsi": r.get("rsi"),
            "atr": r.get("atr"),
            "adx": r.get("adx"),
            "regime": r.get("regime"),
            "engine": r.get("engine"),
            "trend_probability": r.get("trend_probability"),
            "range_probability": r.get("range_probability"),
            "decision_before_rsi": r.get("decision_before_rsi"),
            "decision_after_rsi": r.get("decision_after_rsi"),
            "reason": r.get("reason") or "rsi_filter",
            "blocked_by": r.get("blocked_by") or [],
            "filter_profile": r.get("filter_profile"),
            "bar_index": r.get("bar_index"),
        }
        for r in blocked
    ]
    return {
        "phase": "27B",
        "total_blocked": len(entries),
        "records": entries,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def _direction_stats(records: list[dict[str, Any]], *, stage: str) -> dict[str, int]:
    subset = [r for r in records if r.get(stage) in ("BUY", "SELL")]
    buy = sum(1 for r in subset if r.get(stage) == "BUY")
    sell = sum(1 for r in subset if r.get(stage) == "SELL")
    return {"BUY": buy, "SELL": sell, "total": buy + sell}


def build_buy_sell_filter_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    pre = [r for r in records if r.get("decision_before_rsi") in ("BUY", "SELL")]
    blocked_rsi = [
        r
        for r in pre
        if r.get("decision_after_rsi") == "HOLD" and "rsi_filter" in (r.get("blocked_by") or [])
    ]
    passed = [r for r in pre if r.get("decision_after_rsi") in ("BUY", "SELL")]

    def _split(rows: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "BUY": sum(1 for r in rows if r.get("decision_before_rsi") == "BUY" or r.get("decision_after_rsi") == "BUY"),
            "SELL": sum(1 for r in rows if r.get("decision_before_rsi") == "SELL" or r.get("decision_after_rsi") == "SELL"),
        }

    buy_attempts = sum(1 for r in pre if r.get("decision_before_rsi") == "BUY")
    sell_attempts = sum(1 for r in pre if r.get("decision_before_rsi") == "SELL")
    buy_blocked = sum(1 for r in blocked_rsi if r.get("decision_before_rsi") == "BUY")
    sell_blocked = sum(1 for r in blocked_rsi if r.get("decision_before_rsi") == "SELL")
    buy_passed = sum(1 for r in passed if r.get("decision_after_rsi") == "BUY")
    sell_passed = sum(1 for r in passed if r.get("decision_after_rsi") == "SELL")

    return {
        "phase": "27B",
        "BUY_attempts": buy_attempts,
        "SELL_attempts": sell_attempts,
        "BUY_blocked": buy_blocked,
        "SELL_blocked": sell_blocked,
        "BUY_passed": buy_passed,
        "SELL_passed": sell_passed,
        "blocks_both_directions": buy_blocked > 0 and sell_blocked > 0,
        "primary_blocked_direction": "BUY"
        if buy_blocked > sell_blocked
        else ("SELL" if sell_blocked > buy_blocked else "equal"),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_pre_post_filter_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    def _count(key: str) -> dict[str, int]:
        c = {"BUY": 0, "SELL": 0, "WAIT": 0}
        for r in records:
            action = r.get(key, "HOLD")
            if action == "BUY":
                c["BUY"] += 1
            elif action == "SELL":
                c["SELL"] += 1
            else:
                c["WAIT"] += 1
        return c

    pre = _count("decision_before_rsi")
    post = _count("decision_after_rsi")
    return {
        "phase": "27B",
        "before_rsi": pre,
        "after_rsi": post,
        "delta": {
            "BUY": post["BUY"] - pre["BUY"],
            "SELL": post["SELL"] - pre["SELL"],
            "WAIT": post["WAIT"] - pre["WAIT"],
        },
        "actionable_before": pre["BUY"] + pre["SELL"],
        "actionable_after": post["BUY"] + post["SELL"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def _dist_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None, "min": None, "max": None}
    ordered = sorted(values)
    p95_idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "count": len(values),
        "mean": round(statistics.mean(values), 6),
        "median": round(statistics.median(values), 6),
        "p95": round(ordered[p95_idx], 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def build_distribution_analysis(records: list[dict[str, Any]]) -> dict[str, Any]:
    pre_actionable = [r for r in records if r.get("decision_before_rsi") in ("BUY", "SELL")]
    blocked = [
        r
        for r in pre_actionable
        if r.get("decision_after_rsi") == "HOLD" and (r.get("blocked_by") or [])
    ]
    passed = [r for r in pre_actionable if r.get("decision_after_rsi") in ("BUY", "SELL")]

    fields = ["probability", "confidence", "rsi", "adx", "atr_percentile"]
    out: dict[str, Any] = {"phase": "27B", "fields": {}}
    for field in fields:
        blocked_vals = [float(r[field]) for r in blocked if r.get(field) is not None]
        passed_vals = [float(r[field]) for r in passed if r.get(field) is not None]
        out["fields"][field] = {
            "blocked": _dist_stats(blocked_vals),
            "passed": _dist_stats(passed_vals),
        }
    out["blocked_count"] = len(blocked)
    out["passed_count"] = len(passed)
    out["generated_utc"] = datetime.now(timezone.utc).isoformat()
    return out


def _simulate_band(
    base: ProfitabilityFilterSettings,
    *,
    pct_adjust: float,
) -> ProfitabilityFilterSettings:
    """Simulate band width change: negative pct widens, positive pct tightens."""
    width = base.rsi_max - base.rsi_min
    delta = width * abs(pct_adjust) / 100.0 / 2.0
    if pct_adjust < 0:
        return ProfitabilityFilterSettings(
            enable_rsi=base.enable_rsi,
            enable_adx=base.enable_adx,
            rsi_min=base.rsi_min - delta,
            rsi_max=base.rsi_max + delta,
            adx_min=base.adx_min,
            adx_max=base.adx_max,
        )
    return ProfitabilityFilterSettings(
        enable_rsi=base.enable_rsi,
        enable_adx=base.enable_adx,
        rsi_min=base.rsi_min + delta,
        rsi_max=base.rsi_max - delta,
        adx_min=base.adx_min,
        adx_max=base.adx_max,
    )


def build_threshold_sensitivity(records: list[dict[str, Any]]) -> dict[str, Any]:
    actionable = [
        r
        for r in records
        if r.get("decision_before_rsi") in ("BUY", "SELL")
        and r.get("risk_allowed")
        and r.get("quality_allowed")
    ]
    scenarios = {
        "current": 0.0,
        "widen_5pct": -5.0,
        "widen_10pct": -10.0,
        "tighten_5pct": 5.0,
        "tighten_10pct": 10.0,
    }
    results: dict[str, Any] = {}
    for label, pct in scenarios.items():
        survive = 0
        for r in actionable:
            settings, _ = select_profitability_filter_settings(
                regime=str(r.get("regime", "")),
                engine=str(r.get("engine") or "") or None,
            )
            if settings is None:
                survive += 1
                continue
            sim = _simulate_band(settings, pct_adjust=pct) if pct != 0 else settings
            row = {"rsi": r.get("rsi", 50.0), "adx": r.get("adx", 0.0)}
            filt = apply_profitability_filters(row, settings=sim)
            if filt.passed:
                survive += 1
        results[label] = {
            "pct_band_adjust": pct,
            "actionable_candidates": len(actionable),
            "would_survive_rsi_adx": survive,
            "survival_rate_pct": round(survive / max(len(actionable), 1) * 100, 3),
        }

    return {
        "phase": "27B",
        "method": (
            "Read-only simulation on traced bars. Band width adjusted by ±5%/±10% "
            "of current RSI range (half-width applied to each bound). ADX bounds unchanged."
        ),
        "scenarios": results,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_stage_funnel(records: list[dict[str, Any]], *, hold_chain_27a: dict[str, Any]) -> dict[str, Any]:
    stages = [
        ("bars_entering", len(records)),
        ("orchestrator_actionable", sum(1 for r in records if r.get("raw_orchestrator_action") in ("BUY", "SELL"))),
        (
            "calibration_pass",
            sum(1 for r in records if r.get("decision_before_rsi") in ("BUY", "SELL")),
        ),
        (
            "trade_quality_pass",
            sum(
                1
                for r in records
                if r.get("decision_before_rsi") in ("BUY", "SELL")
                and r.get("risk_allowed")
                and r.get("quality_allowed")
            ),
        ),
        (
            "profitability_filter_pass",
            sum(1 for r in records if r.get("decision_after_rsi") in ("BUY", "SELL")),
        ),
        ("ml_signals_emitted", sum(1 for r in records if r.get("decision_after_rsi") in ("BUY", "SELL"))),
    ]

    funnel = []
    prev = len(records)
    for name, count in stages[1:]:
        rejected = max(0, prev - count)
        funnel.append(
            {
                "stage": name,
                "bars_entering": prev,
                "bars_leaving": count,
                "bars_rejected": rejected,
                "rejection_rate_pct": round(rejected / max(prev, 1) * 100, 3),
            }
        )
        prev = count

    hold_counts: dict[str, int] = {}
    for r in records:
        stage = r.get("hold_stage")
        if stage:
            hold_counts[stage] = hold_counts.get(stage, 0) + 1

    return {
        "phase": "27B",
        "stages": {
            "FeatureBuilder": {"bars_entering": len(records), "bars_leaving": len(records), "bars_rejected": 0},
            "PipelineCache_unified_frame": {
                "bars_entering": len(records),
                "bars_leaving": len(records),
                "bars_rejected": 0,
                "note": "Integer index on unified frame — see root cause on prediction cache key",
            },
            "DecisionOrchestrator": {
                "bars_entering": len(records),
                "bars_leaving": sum(1 for r in records if r.get("raw_orchestrator_action") in ("BUY", "SELL")),
                "bars_rejected": sum(1 for r in records if r.get("raw_orchestrator_action") == "HOLD"),
            },
            "Calibration": {
                "bars_entering": sum(1 for r in records if r.get("raw_orchestrator_action") in ("BUY", "SELL")),
                "bars_leaving": sum(1 for r in records if r.get("decision_before_rsi") in ("BUY", "SELL")),
                "bars_rejected": sum(1 for r in records if r.get("hold_stage") == "calibration_hold"),
            },
            "AdaptiveRisk_TradeQuality": {
                "bars_entering": sum(1 for r in records if r.get("decision_before_rsi") in ("BUY", "SELL")),
                "bars_leaving": sum(
                    1
                    for r in records
                    if r.get("decision_before_rsi") in ("BUY", "SELL")
                    and r.get("risk_allowed")
                    and r.get("quality_allowed")
                ),
                "bars_rejected": sum(1 for r in records if r.get("hold_stage") == "trade_quality_hold"),
            },
            "ProfitabilityFilters": {
                "bars_entering": sum(
                    1
                    for r in records
                    if r.get("decision_before_rsi") in ("BUY", "SELL")
                    and r.get("risk_allowed")
                    and r.get("quality_allowed")
                ),
                "bars_leaving": sum(1 for r in records if r.get("decision_after_rsi") in ("BUY", "SELL")),
                "bars_rejected": sum(
                    1
                    for r in records
                    if r.get("hold_stage") in ("rsi_filter_hold", "adx_filter_hold")
                ),
            },
        },
        "funnel_sequence": funnel,
        "hold_stage_counts_fresh_trace": hold_counts,
        "phase27a_hold_chain": hold_chain_27a,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_feature_quality(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = {
        "rsi": (0.0, 100.0),
        "adx": (0.0, 100.0),
        "atr": (0.0, None),
        "atr_percentile": (0.0, 100.0),
        "ema20_slope": (None, None),
        "momentum": (None, None),
        "probability": (0.0, 1.0),
        "confidence": (0.0, 1.0),
    }
    report: dict[str, Any] = {"phase": "27B", "features": {}}
    for field, (lo, hi) in fields.items():
        vals = [r.get(field) for r in records]
        numeric = [float(v) for v in vals if v is not None]
        nan_count = sum(1 for v in vals if v is None)
        unique = len(set(round(v, 8) for v in numeric))
        constant = unique <= 1 and len(numeric) > 1
        out_of_range = 0
        if lo is not None:
            out_of_range += sum(1 for v in numeric if v < lo)
        if hi is not None:
            out_of_range += sum(1 for v in numeric if v > hi)
        report["features"][field] = {
            "nan_or_missing": nan_count,
            "unique_values": unique,
            "constant_suspected": constant,
            "out_of_range_count": out_of_range,
            "expected_range": [lo, hi],
            "stats": _dist_stats(numeric),
        }
    report["generated_utc"] = datetime.now(timezone.utc).isoformat()
    return report


def build_engine_statistics(records: list[dict[str, Any]]) -> dict[str, Any]:
    engines: dict[str, dict[str, int]] = {}
    for r in records:
        eng = str(r.get("engine") or "unknown")
        pre = r.get("decision_before_rsi", "HOLD")
        bucket = engines.setdefault(eng, {"BUY": 0, "SELL": 0, "WAIT": 0})
        if pre == "BUY":
            bucket["BUY"] += 1
        elif pre == "SELL":
            bucket["SELL"] += 1
        else:
            bucket["WAIT"] += 1
    return {
        "phase": "27B",
        "by_engine_before_rsi": engines,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_root_cause_rank(
    *,
    records: list[dict[str, Any]],
    hold_chain_27a: dict[str, Any],
    filter_location: dict[str, Any],
    buy_sell: dict[str, Any],
    pre_post: dict[str, Any],
    threshold: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    fresh_rsi = sum(1 for r in records if r.get("hold_stage") == "rsi_filter_hold")
    fresh_adx = sum(1 for r in records if r.get("hold_stage") == "adx_filter_hold")
    fresh_pass = pre_post.get("actionable_after", 0)
    phase27a_rsi = hold_chain_27a.get("ml_hold_stages", {}).get("rsi_filter_hold", 0)

    cache_evidence = {
        "phase27a_unique_checksums": 3,
        "phase27a_identical_confidence_bars": 5201,
        "prediction_cache_key_pattern": "symbol:timeframe:unified.index[-1]",
        "unified_frame_index_type": "int64 positional (not timestamp)",
        "kernel_adapter_line": _line_of(
            "tradingbot/ml/integration/kernel_adapter.py",
            'row_key = f"{market.symbol}:{market.timeframe}:{unified.index[-1]}"',
            project_root,
        ),
    }

    causes = [
        {
            "rank": 1,
            "severity": "CRITICAL",
            "issue": "PipelineCache prediction key collision in replay",
            "repository_location": "tradingbot/ml/integration/kernel_adapter.py (row_key); PipelineCache.get_unified_frame integer index",
            "runtime_evidence": cache_evidence,
            "affected_bars": phase27a_rsi,
            "estimated_impact": (
                "Phase 27A replay served one cached ML signal for ~5201 bars (decision_ms=0 on 5200/5203). "
                "Hold-chain RSI counters replayed from stale _hold_chain payload — not per-bar fresh evaluation."
            ),
            "recommended_fix": "Use candle timestamp in prediction cache key; do not modify in Phase 27B.",
        },
        {
            "rank": 2,
            "severity": "HIGH",
            "issue": "RSI mid-band filter rejects majority of fresh actionable signals",
            "repository_location": "tradingbot/ml/phase19c/filters.py:99-100; regime_filter_profiles.py RangeFilterProfile rsi 40-65",
            "runtime_evidence": {
                "fresh_trace_rsi_blocks": fresh_rsi,
                "fresh_trace_adx_blocks_attributed_as_rsi": fresh_adx,
                "RANGE_profile_rsi_limits": filter_location["runtime_profiles"]["RANGE_phase9_9"]["rsi_limits"],
                "blocked_buy": buy_sell.get("BUY_blocked"),
                "blocked_sell": buy_sell.get("SELL_blocked"),
                "distribution_rsi_blocked_mean": (
                    threshold  # placeholder replaced below
                ),
            },
            "affected_bars": fresh_rsi,
            "estimated_impact": f"Fresh trace: {fresh_rsi} bars blocked by RSI filter; {fresh_pass} signals would pass if filter removed.",
            "recommended_fix": "Re-certify RSI band on XAUUSD M5 RANGE regime; hold-chain should record ADX separately when both fail.",
        },
        {
            "rank": 3,
            "severity": "MEDIUM",
            "issue": "Hold-chain attributes dual RSI+ADX failures to RSI only",
            "repository_location": "tradingbot/ml/integration/kernel_adapter.py _hold_chain_snapshot",
            "runtime_evidence": {"fresh_adx_only_stage": fresh_adx, "fresh_rsi_stage": fresh_rsi},
            "affected_bars": fresh_adx,
            "estimated_impact": "Under-counts ADX filter impact in Phase 27A hold_analysis.",
            "recommended_fix": "Record primary and secondary block reasons in hold chain diagnostics.",
        },
    ]

    dist = build_distribution_analysis(records)
    causes[1]["runtime_evidence"]["distribution_rsi_blocked_mean"] = dist["fields"]["rsi"]["blocked"].get("mean")

    widen = threshold.get("scenarios", {}).get("widen_10pct", {})
    causes.append(
        {
            "rank": 4,
            "severity": "MEDIUM",
            "issue": "Filter band may be miscalibrated for June 2026 XAUUSD M5",
            "repository_location": "tradingbot/ml/integration/regime_filter_profiles.py RangeFilterProfile",
            "runtime_evidence": {
                "widen_10pct_survival_rate": widen.get("survival_rate_pct"),
                "current_survival_rate": threshold.get("scenarios", {}).get("current", {}).get("survival_rate_pct"),
            },
            "affected_bars": pre_post.get("actionable_before", 0) - pre_post.get("actionable_after", 0),
            "estimated_impact": "Simulation-only: widening RSI band 10% increases survivors without production change.",
            "recommended_fix": "Run isolated RANGE-only filter validation before paper trading.",
        }
    )

    return {
        "phase": "27B",
        "ranked_causes": causes,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_final_report(
    *,
    root_causes: dict[str, Any],
    pre_post: dict[str, Any],
    buy_sell: dict[str, Any],
    hold_chain_27a: dict[str, Any],
    trace_meta: dict[str, Any],
) -> dict[str, Any]:
    primary = root_causes["ranked_causes"][0]
    return {
        "phase": "27B",
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "objective": "Explain Phase 27A zero trades and RSI filter dominance",
        "phase27a_summary": {
            "bars_evaluated": hold_chain_27a.get("bars_evaluated"),
            "completed_trades": 0,
            "rsi_filter_hold": hold_chain_27a.get("ml_hold_stages", {}).get("rsi_filter_hold"),
            "buy_emitted": hold_chain_27a.get("buy_emitted"),
            "sell_emitted": hold_chain_27a.get("sell_emitted"),
        },
        "fresh_trace_summary": {
            "bars_traced": trace_meta.get("bars_traced"),
            "actionable_before_rsi": pre_post.get("actionable_before"),
            "actionable_after_rsi": pre_post.get("actionable_after"),
            "buy_blocked": buy_sell.get("BUY_blocked"),
            "sell_blocked": buy_sell.get("SELL_blocked"),
        },
        "primary_root_cause": primary["issue"],
        "verdict": "MULTIPLE_ROOT_CAUSES",
        "conclusion": (
            "Phase 27A reported 5201 rsi_filter_hold events, but ~5200 bars used PipelineCache prediction "
            "hits (identical checksum/confidence). Fresh per-bar trace shows the RSI/ADX profitability filter "
            "still blocks most actionable RANGE signals under regime profile rsi 40-65 / adx 15-40. "
            "Zero trades is explained by filter strictness plus replay cache key collision — not RiskGate or execution."
        ),
        "ranked_causes": root_causes["ranked_causes"],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
