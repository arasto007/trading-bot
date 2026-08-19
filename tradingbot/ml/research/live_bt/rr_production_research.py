"""RR_PRODUCTION_RESEARCH — VOL_REGIME RR sweep + TQ counterfactual (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from tradingbot.ml.research.live_bt.backtest_gate import (
    ATR_MULT,
    HYPOTHESIS_ID,
    OVERALL_PF_MIN,
    RR_PRODUCTION,
    YEAR_END,
    YEAR_START,
    _evaluate_vol_regime_gate,
    _run_vol_regime_backtest,
)
from tradingbot.ml.research.live_l2.edge_discovery import (
    FUTURE_WINDOW,
    GATE_MIN_TRADES_YEAR,
    GATE_MIN_YEARS_PASS,
    GATE_PF,
    _pf_from_labels,
    _yearly_stats,
)
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    HYPOTHESES_R2,
    _prepare_frame_round2,
)
from tradingbot.ml.research.live_l2.sl_tp_sweep import (
    _make_sl_tp_fn,
    _scan_hypothesis_sl_tp,
)
from tradingbot.ml.research.live_l3.execution_validation import (
    CAPTURE_GATE_PCT,
    RULE_CONFIDENCE,
    _evaluate_production_funnel,
    _infer_regime,
    _session_from_row,
    _spread_pips,
)
from tradingbot.ml.research.phase39.candle_sources import audit_report, resolve_fullest_candles
from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics
from tradingbot.ml.trade_quality.quality_policy import QUALITY_THRESHOLD, WEIGHTS
from tradingbot.ml.trade_quality.quality_engine import clamp
from tradingbot.ml.trade_quality.regime_quality import TREND_ENGINE_V41, regime_quality_score
from tradingbot.ml.trade_quality.rr_quality import rr_quality_score

ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = ROOT / "live_rr_production_research_report.json"
TQ_PATCH_SPEC = ROOT / "tradingbot" / "ml" / "research" / "live_l6" / "tq_rr_research_patch_spec.json"
BT_GATE_REPORT = ROOT / "live_backtest_gate_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
RR_SWEEP = (0.8, 1.0, 1.2, 1.5, 2.0, 2.5)
VOL_REGIME_ENGINE = "vol_regime"
SHADOW_PF_MIN = 1.0


def _rr_quality_vol_regime_patch(rr_ratio: float) -> tuple[float, str]:
    """Simulate engine-scoped TQ patch from tq_rr_research_patch_spec.json."""
    rr = float(rr_ratio)
    if rr < 0.8:
        return 0.0, f"RR {rr:.2f} below vol_regime research floor 0.8"
    if rr <= 1.0:
        return 0.85, f"RR {rr:.2f} vol_regime research band (0.8-1.0)"
    if rr <= 1.5:
        return 0.90, f"RR {rr:.2f} vol_regime upper research band (1.0-1.5)"
    if rr <= 2.0:
        return 0.95, f"RR {rr:.2f} vol_regime transition band (1.5-2.0)"
    return 1.0, f"RR {rr:.2f} meets production minimum 1:2"


def _document_tq_rr_blocks() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for rr in RR_SWEEP:
        score, label = rr_quality_score(rr)
        patch_score, patch_label = _rr_quality_vol_regime_patch(rr)
        rows.append(
            {
                "rr": rr,
                "current_score": score,
                "current_label": label,
                "current_blocked": score <= 0,
                "current_partial": 0 < score < 1.0,
                "vol_regime_patch_score": patch_score,
                "vol_regime_patch_label": patch_label,
                "vol_regime_patch_blocked": patch_score <= 0,
            }
        )
    blocked_current = [r["rr"] for r in rows if r["current_blocked"]]
    allowed_patch = [r["rr"] for r in rows if not r["vol_regime_patch_blocked"]]
    return {
        "policy_file": "tradingbot/ml/trade_quality/rr_quality.py",
        "quality_threshold": QUALITY_THRESHOLD,
        "rr_weight": WEIGHTS["rr"],
        "per_rr": rows,
        "current_production_blocks_rr_below": 1.5,
        "current_blocked_rr_values": blocked_current,
        "vol_regime_patch_allows_rr_range": [0.8, 1.5],
        "vol_regime_patch_allowed_rr_values": allowed_patch,
        "patch_spec": "tradingbot/ml/research/live_l6/tq_rr_research_patch_spec.json",
    }


def _evaluate_funnel_custom_rr(
    frame: pd.DataFrame,
    trades: list[dict[str, Any]],
    *,
    rr_ratio: float,
    rr_score_fn: Callable[[float], tuple[float, str]],
    engine: str = TREND_ENGINE_V41,
) -> dict[str, Any]:
    """Production funnel with injectable RR scoring — clean implementation."""
    from tradingbot.ml.trade_quality.engine_history import engine_history_modifier
    from tradingbot.ml.trade_quality.liquidity_quality import liquidity_quality_score
    from tradingbot.ml.trade_quality.signal_quality import signal_quality_score
    from tradingbot.ml.trade_quality.timing_quality import timing_quality_score
    from tradingbot.ml.trade_quality.volatility_quality import volatility_quality_score

    history = HistoricalMetrics()
    captured: list[dict[str, Any]] = []
    blockers: dict[str, int] = {}

    for trade in trades:
        idx = int(trade["bar_index"])
        row = frame.iloc[idx]
        direction_str = str(trade["direction"])
        regime = _infer_regime(row)
        reg_score, _ = regime_quality_score(engine, regime)
        if reg_score <= 0:
            blockers["RegimeQuality"] = blockers.get("RegimeQuality", 0) + 1
            continue

        rr_score, _ = rr_score_fn(rr_ratio)
        sig, _ = signal_quality_score(RULE_CONFIDENCE)
        if sig <= 0:
            blockers["signal"] = blockers.get("signal", 0) + 1
            continue

        vol, _ = volatility_quality_score(float(row.get("atr_pct", 0.5)))
        if vol <= 0:
            blockers["volatility"] = blockers.get("volatility", 0) + 1
            continue

        liq, _, _ = liquidity_quality_score(_spread_pips(row))
        if liq <= 0:
            blockers["liquidity"] = blockers.get("liquidity", 0) + 1
            continue

        sess, _ = timing_quality_score(_session_from_row(row))
        components = {
            "signal": sig,
            "regime": reg_score,
            "rr": rr_score,
            "volatility": vol,
            "liquidity": liq,
            "session": sess,
        }
        weighted = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
        hist_factor, _ = engine_history_modifier(engine, history)
        score = clamp(weighted * hist_factor)
        allowed = score >= QUALITY_THRESHOLD and rr_score > 0 and liq > 0 and vol > 0

        if not allowed:
            key = "below_threshold" if rr_score > 0 else "rr_blocked"
            blockers[key] = blockers.get(key, 0) + 1
            continue
        captured.append(trade)

    raw = len(trades)
    cap = len(captured)
    capture_rate = round(cap / max(raw, 1) * 100, 2)
    labels = [int(t["outcome"]) for t in captured]
    shadow_pf = _pf_from_labels(labels) if labels else 0.0
    yearly = _yearly_stats(captured)
    gate = _evaluate_vol_regime_gate(yearly, shadow_pf)
    prod_like = capture_rate >= CAPTURE_GATE_PCT and shadow_pf >= SHADOW_PF_MIN and gate["gate_pass"]
    return {
        "raw_signals": raw,
        "captured": cap,
        "capture_rate_pct": capture_rate,
        "capture_gate_pct": CAPTURE_GATE_PCT,
        "capture_gate_pass": capture_rate >= CAPTURE_GATE_PCT,
        "blockers": blockers,
        "shadow_pf": shadow_pf,
        "shadow_trades": len(labels),
        "yearly": yearly,
        "gate": gate,
        "gate_pass": gate["gate_pass"],
        "shadow_pf_gate_pass": shadow_pf >= SHADOW_PF_MIN,
        "production_like_pass": prod_like,
        "v41_regime_fix_active": engine == TREND_ENGINE_V41,
        "engine": engine,
        "rr_ratio": rr_ratio,
        "rr_policy": "vol_regime_patch" if rr_score_fn is _rr_quality_vol_regime_patch else "current_production",
    }


def _find_minimum_passing_rr(sweep: list[dict[str, Any]]) -> dict[str, Any] | None:
    passing = [s for s in sweep if s["backtest"]["gate_pass"]]
    if not passing:
        return None
    best = min(passing, key=lambda x: x["rr"])
    return {
        "rr": best["rr"],
        "config_id": best["config_id"],
        "overall_pf": best["backtest"]["overall_pf"],
        "years_passed_gate": best["backtest"]["gate"]["years_passed_gate"],
    }


def _determine_next_step(
    production_like: dict[str, Any],
    min_rr: dict[str, Any] | None,
    baseline_rr25: dict[str, Any],
) -> dict[str, Any]:
    prod_pass = bool(production_like.get("production_like_pass"))
    if prod_pass:
        return {
            "next_step": "PAPER_RESUME",
            "paper_resume_allowed": True,
            "reason_en": (
                f"Production-like path passes: VOL_REGIME RR={production_like.get('rr')} "
                f"with vol_regime TQ patch — shadow PF={production_like.get('shadow_pf')}, "
                f"capture={production_like.get('capture_rate_pct')}%."
            ),
            "reason_fa": (
                f"مسیر production-like پاس شد — RR={production_like.get('rr')} "
                f"با patch TQ vol_regime؛ paper قابل ازسرگیری است."
            ),
        }

    min_rr_val = min_rr["rr"] if min_rr else None
    if min_rr_val is not None and min_rr_val < RR_PRODUCTION:
        return {
            "next_step": "SL_TP_PRODUCTION_CHANGE",
            "paper_resume_allowed": False,
            "reason_en": (
                f"Backtest gate passes at RR={min_rr_val} but production-like funnel fails. "
                "Requires vol_regime-scoped TQ patch (tq_rr_research_patch_spec.json) before paper."
            ),
            "reason_fa": (
                f"backtest در RR={min_rr_val} پاس است ولی funnel production-like نه — patch TQ vol_regime لازم."
            ),
        }

    return {
        "next_step": "NEW_HYPOTHESIS",
        "paper_resume_allowed": False,
        "reason_en": (
            f"No RR in sweep passes backtest gate with production RR={RR_PRODUCTION} baseline PF="
            f"{baseline_rr25.get('overall_pf')}. VOL_REGIME edge not viable at production RR."
        ),
        "reason_fa": "هیچ RR در sweep gate را پاس نمی‌کند — فرضیه جدید لازم است.",
    }


def run_rr_production_research(
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    year_start: int = YEAR_START,
    year_end: int = YEAR_END,
) -> dict[str, Any]:
    candle_audit = audit_report(symbol, timeframe)
    candles = resolve_fullest_candles(symbol, timeframe)
    if candles is None or candles.empty:
        return {
            "verdict": "NO_CANDLES",
            "candle_audit": candle_audit,
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    frame = _prepare_frame_round2(candles)
    frame = frame[(frame.index.year >= year_start) & (frame.index.year <= year_end)]
    candle_source_used = candle_audit.get("fullest_source") or {}

    tq_doc = _document_tq_rr_blocks()
    sweep_results: list[dict[str, Any]] = []

    print("RR_PRODUCTION_RESEARCH: sweeping VOL_REGIME RR values ...", flush=True)
    for rr in RR_SWEEP:
        config_id = f"ATR{ATR_MULT}_RR{rr}"
        print(f"  RR={rr} ...", flush=True)
        backtest = _run_vol_regime_backtest(frame, candles, rr=rr, config_id=config_id)

        meta = HYPOTHESES_R2[HYPOTHESIS_ID]
        sl_tp_fn = _make_sl_tp_fn("atr_rr", atr_mult=ATR_MULT, rr=rr)
        trades = _scan_hypothesis_sl_tp(
            frame,
            candles,
            meta["signal_fn"],
            sl_tp_fn,
            use_production=False,
            stride=int(meta.get("stride", 6)),
        )
        funnel_current = _evaluate_production_funnel(frame, trades, rr_ratio=rr)
        funnel_patch = _evaluate_funnel_custom_rr(
            frame,
            trades,
            rr_ratio=rr,
            rr_score_fn=_rr_quality_vol_regime_patch,
            engine=TREND_ENGINE_V41,
        )
        rr_score, rr_label = rr_quality_score(rr)

        sweep_results.append(
            {
                "rr": rr,
                "config_id": config_id,
                "backtest": {
                    k: backtest[k]
                    for k in (
                        "config_id",
                        "hypothesis_id",
                        "mode",
                        "atr_mult",
                        "rr",
                        "total_trades",
                        "overall_pf",
                        "overall_win_rate_pct",
                        "yearly",
                        "gate",
                        "gate_pass",
                    )
                    if k in backtest
                },
                "tq_current": {
                    "rr_score": rr_score,
                    "rr_label": rr_label,
                    "blocked": rr_score <= 0,
                },
                "funnel_current_tq": funnel_current,
                "funnel_vol_regime_patch": funnel_patch,
            }
        )
        print(
            f"    backtest_pf={backtest['overall_pf']} gate={backtest['gate_pass']} "
            f"capture_current={funnel_current['capture_rate_pct']}% "
            f"capture_patch={funnel_patch['capture_rate_pct']}% shadow_patch_pf={funnel_patch['shadow_pf']}",
            flush=True,
        )

    min_rr = _find_minimum_passing_rr(sweep_results)
    passing_rrs = [s for s in sweep_results if s["backtest"]["gate_pass"]]
    best_backtest = max(passing_rrs, key=lambda x: x["backtest"]["overall_pf"]) if passing_rrs else None
    best_rr = min_rr["rr"] if min_rr else (best_backtest["rr"] if best_backtest else 0.8)

    baseline = next((s for s in sweep_results if s["rr"] == RR_PRODUCTION), sweep_results[-1])
    counterfactual_band = [
        s
        for s in sweep_results
        if 0.8 <= s["rr"] <= 1.5
    ]

    print(f"RR_PRODUCTION_RESEARCH: production-like path at RR={best_rr} ...", flush=True)
    best_sweep = next(s for s in sweep_results if s["rr"] == best_rr)
    production_like = best_sweep["funnel_vol_regime_patch"]
    production_like["backtest_pf"] = best_sweep["backtest"]["overall_pf"]
    production_like["backtest_gate_pass"] = best_sweep["backtest"]["gate_pass"]
    production_like["config_id"] = best_sweep["config_id"]
    production_like["rr"] = best_rr
    production_like["description"] = (
        "VOL_REGIME + best passing RR + v41 regime fix + vol_regime TQ RR patch simulation"
    )

    baseline_funnel = baseline["funnel_current_tq"]
    next_step = _determine_next_step(production_like, min_rr, baseline["backtest"])

    verdict = "PRODUCTION_LIKE_PASS" if production_like.get("production_like_pass") else "RESEARCH_RR_ONLY"
    if not min_rr:
        verdict = "NO_VIABLE_RR"

    recommendation_en = (
        f"Minimum RR passing backtest gate: {min_rr['rr'] if min_rr else 'none'} "
        f"(PF={min_rr['overall_pf'] if min_rr else 0}). "
        f"Current TQ blocks RR below 1.5 globally — values blocked: {tq_doc['current_blocked_rr_values']}. "
        f"Vol_regime-only patch allows RR 0.8-1.5 without global relaxation. "
        f"Production RR={RR_PRODUCTION} backtest PF={baseline['backtest']['overall_pf']:.4f} (FAIL). "
        f"Best production-like shadow PF={production_like.get('shadow_pf')} at RR={best_rr} with patch."
    )
    recommendation_fa = (
        f"حداقل RR پاس gate: {min_rr['rr'] if min_rr else 'هیچ'}. "
        f"TQ فعلی RR زیر 1.5 را block می‌کند. "
        f"patch vol_regime فقط برای موتور VOL_REGIME RR 0.8-1.5 را مجاز می‌کند. "
        f"RR production={RR_PRODUCTION} شکست خورد (PF={baseline['backtest']['overall_pf']:.2f})."
    )

    return {
        "phase": "RR_PRODUCTION_RESEARCH",
        "title": "VOL_REGIME RR Production Research Sweep",
        "title_fa": "تحقیق RR production برای VOL_REGIME",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "research_only": True,
        "production_deploy": "BLOCKED",
        "paper_status": "PAUSED_FOR_BACKTEST_GATE" if not next_step["paper_resume_allowed"] else "READY_FOR_PAPER_RESUME",
        "symbol": symbol,
        "timeframe": timeframe,
        "year_range": [year_start, year_end],
        "candle_source": {
            "canonical_path": candle_audit.get("canonical_path"),
            "source_used": candle_source_used,
            "audit": candle_audit,
        },
        "methodology": {
            "hypothesis": HYPOTHESIS_ID,
            "atr_mult": ATR_MULT,
            "rr_values_swept": list(RR_SWEEP),
            "future_window_bars": FUTURE_WINDOW,
            "gate_backtest": (
                f"PF>={GATE_PF} in {GATE_MIN_YEARS_PASS}+ years, "
                f"{GATE_MIN_TRADES_YEAR}+ trades/year, overall PF>={OVERALL_PF_MIN}"
            ),
            "gate_production_like": (
                f"capture>={CAPTURE_GATE_PCT}%, shadow PF>={SHADOW_PF_MIN}, backtest gate pass"
            ),
            "funnel_simulation": "TradeQualityEngine + trend_rf_v41 v41 fix + injectable RR policy",
            "tq_patch_spec": "tradingbot/ml/research/live_l6/tq_rr_research_patch_spec.json",
            "ml_status": "SKIP — L4/BT-gate ML v8 failed (AUC 0.52)",
        },
        "tq_rr_block_analysis": tq_doc,
        "sweep_results": sweep_results,
        "minimum_rr_passing_gate": min_rr,
        "best_backtest_pf": {
            "rr": best_backtest["rr"] if best_backtest else None,
            "config_id": best_backtest["config_id"] if best_backtest else None,
            "overall_pf": best_backtest["backtest"]["overall_pf"] if best_backtest else None,
        },
        "counterfactual_rr_08_to_15": {
            "description_en": "If vol_regime engine allowed RR 0.8-1.5 via TQ patch",
            "description_fa": "counterfactual: patch TQ vol_regime برای RR 0.8-1.5",
            "per_rr": [
                {
                    "rr": s["rr"],
                    "capture_pct_patch": s["funnel_vol_regime_patch"]["capture_rate_pct"],
                    "shadow_pf_patch": s["funnel_vol_regime_patch"]["shadow_pf"],
                    "capture_pct_current": s["funnel_current_tq"]["capture_rate_pct"],
                    "shadow_pf_current": s["funnel_current_tq"]["shadow_pf"],
                }
                for s in counterfactual_band
            ],
        },
        "production_like_path": production_like,
        "baseline_production_rr25": {
            "rr": RR_PRODUCTION,
            "config_id": f"ATR{ATR_MULT}_RR{RR_PRODUCTION}",
            "backtest": baseline["backtest"],
            "funnel_current_tq": baseline_funnel,
            "gate_pass": baseline["backtest"]["gate_pass"],
        },
        "comparison_production_like_vs_rr25": {
            "backtest_pf_delta": round(
                production_like.get("backtest_pf", 0) - baseline["backtest"]["overall_pf"], 4
            ),
            "shadow_pf_delta": round(
                production_like.get("shadow_pf", 0) - baseline_funnel.get("shadow_pf", 0), 4
            ),
            "capture_delta_pct": round(
                production_like.get("capture_rate_pct", 0) - baseline_funnel.get("capture_rate_pct", 0), 2
            ),
        },
        "recommendation": {
            "minimum_rr_change_en": (
                f"Deploy vol_regime-only RR={best_rr} (ATR{ATR_MULT}) — NOT global RR={RR_PRODUCTION} relaxation."
            ),
            "minimum_rr_change_fa": (
                f"فقط VOL_REGIME با RR={best_rr} — نه relax سراسری RR={RR_PRODUCTION}."
            ),
            "safe_patch_scope_en": (
                "Engine-scoped TQ patch per tq_rr_research_patch_spec.json — vol_regime engine only, "
                "no_global_relaxation=true, other engines remain blocked below RR 1.5."
            ),
            "safe_patch_scope_fa": "پچ TQ فقط vol_regime — بدون relax سراسری.",
            "paper_resume_en": (
                "YES — paper may resume" if next_step["paper_resume_allowed"] else "NO — paper stays PAUSED"
            ),
            "paper_resume_fa": (
                "بله — paper قابل ازسرگیری" if next_step["paper_resume_allowed"] else "خیر — paper متوقف"
            ),
            "ml_skipped_en": "YES — ML v8 failed BT-gate (AUC 0.52); rule-only VOL_REGIME path.",
            "ml_skipped_fa": "بله — ML v8 در BT-gate fail شد؛ مسیر rule-only VOL_REGIME.",
            "summary_en": recommendation_en,
            "summary_fa": recommendation_fa,
        },
        "next_step": next_step,
        "paper_resume_allowed": next_step["paper_resume_allowed"],
        "backtest_gate_reference": str(BT_GATE_REPORT),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_rr_production_research()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    print(
        f"Verdict: {data.get('verdict')} next_step: {data.get('next_step', {}).get('next_step')} "
        f"paper_resume: {data.get('paper_resume_allowed')}",
        flush=True,
    )
    return data


if __name__ == "__main__":
    main()
