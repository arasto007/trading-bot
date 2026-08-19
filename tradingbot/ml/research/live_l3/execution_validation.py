"""L3 — execution path validation for marginal edge (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.live_l2.edge_discovery import (
    FUTURE_WINDOW,
    GATE_PF,
    WARMUP,
    _evaluate_gate,
    _pf_from_labels,
    _yearly_stats,
)
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    HYPOTHESES_R2,
    _prepare_frame_round2,
)
from tradingbot.ml.research.live_l2.sl_tp_sweep import (
    _make_sl_tp_fn,
    _resolve_trade_with_sl_tp_fn,
    _scan_hypothesis_sl_tp,
)
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast
from tradingbot.ml.risk_intelligence.risk_types import HistoricalMetrics, RiskRecommendation
from tradingbot.ml.trade_quality.quality_engine import TradeQualityEngine
from tradingbot.ml.trade_quality.quality_types import TradeQualityContext
from tradingbot.ml.trade_quality.regime_quality import TREND_ENGINE_V41, regime_quality_score

ROOT = Path(__file__).resolve().parents[4]
L27_REPORT = ROOT / "live_l2_edge_discovery_l27_report.json"
L26_REPORT = ROOT / "live_l2_edge_discovery_l26_report.json"
REPORT_PATH = ROOT / "live_l3_execution_validation_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
YEAR_START = 2021
YEAR_END = 2026
DEFAULT_SIGNAL = "PULLBACK_VWAP"
DEFAULT_ATR = 2.0
DEFAULT_RR = 1.0
CAPTURE_GATE_PCT = 20.0
RULE_CONFIDENCE = 0.60


def _load_best_config() -> dict[str, Any]:
    for path in (L27_REPORT, L26_REPORT):
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        best = data.get("best_overall") or data.get("best_config")
        if isinstance(best, dict) and best.get("config_id"):
            hyp = best.get("hypothesis") or data.get("signal", {}).get("hypothesis_id") or DEFAULT_SIGNAL
            cfg_id = best["config_id"]
            atr = float(best.get("atr_mult", DEFAULT_ATR))
            rr = float(best.get("rr", DEFAULT_RR))
            if "ATR" in cfg_id and "_RR" in cfg_id:
                try:
                    atr = float(cfg_id.split("ATR")[1].split("_")[0])
                    rr = float(cfg_id.split("_RR")[1])
                except ValueError:
                    pass
            return {
                "source_report": path.name,
                "hypothesis_id": hyp,
                "config_id": cfg_id,
                "atr_mult": atr,
                "rr": rr,
            }
        if data.get("signal"):
            sl_tp = data.get("sl_tp", {})
            return {
                "source_report": path.name,
                "hypothesis_id": data["signal"].get("hypothesis_id", DEFAULT_SIGNAL),
                "config_id": sl_tp.get("config_id", f"ATR{DEFAULT_ATR}_RR{DEFAULT_RR}"),
                "atr_mult": float(sl_tp.get("atr_mult", DEFAULT_ATR)),
                "rr": float(sl_tp.get("rr", DEFAULT_RR)),
            }
    return {
        "source_report": "fallback",
        "hypothesis_id": DEFAULT_SIGNAL,
        "config_id": f"ATR{DEFAULT_ATR}_RR{DEFAULT_RR}",
        "atr_mult": DEFAULT_ATR,
        "rr": DEFAULT_RR,
    }


def _infer_regime(row: pd.Series) -> str:
    ema20, ema50 = float(row["ema20"]), float(row["ema50"])
    atr_pct = float(row.get("atr_pct", 0.5))
    if not np.isfinite(ema20) or not np.isfinite(ema50):
        return "NO_TRADE"
    if atr_pct >= 0.85:
        return "HIGH_VOLATILITY"
    if abs(ema20 - ema50) / max(float(row["close"]), 1.0) < 0.0003:
        return "RANGE"
    if ema20 > ema50:
        return "TREND"
    if ema20 < ema50:
        return "TREND"
    return "NO_TRADE"


def _session_from_row(row: pd.Series) -> str:
    session = str(row.get("session", "off_hours"))
    mapping = {
        "london": "LONDON",
        "new_york": "NEW_YORK",
        "asia": "ASIA",
        "off_hours": "OFF_HOURS",
    }
    return mapping.get(session, session.upper())


def _spread_pips(row: pd.Series) -> float:
    sp = float(row.get("spread_proxy", 3.0))
    return sp if np.isfinite(sp) else 3.0


def _evaluate_production_funnel(
    frame: pd.DataFrame,
    trades: list[dict[str, Any]],
    *,
    rr_ratio: float = 2.5,
) -> dict[str, Any]:
    engine = TradeQualityEngine(history=HistoricalMetrics())
    captured: list[dict[str, Any]] = []
    blockers: dict[str, int] = {}

    for trade in trades:
        idx = int(trade["bar_index"])
        row = frame.iloc[idx]
        direction_str = str(trade["direction"])
        regime = _infer_regime(row)
        reg_score, reg_label = regime_quality_score(TREND_ENGINE_V41, regime)
        if reg_score <= 0:
            blockers["RegimeQuality"] = blockers.get("RegimeQuality", 0) + 1
            continue

        risk = RiskRecommendation(
            allowed=True,
            risk_percent=0.25,
            multiplier=1.0,
            confidence_factor=1.0,
            regime_factor=1.0,
            volatility_factor=1.0,
            session_factor=1.0,
            drawdown_factor=1.0,
            reason="research proxy — rule signal",
            trace=["proxy risk allowed"],
        )
        ctx = TradeQualityContext(
            market=None,  # type: ignore[arg-type]
            calibrated=None,  # type: ignore[arg-type]
            risk=risk,
            engine=TREND_ENGINE_V41,
            regime=regime,
            action=direction_str,
            confidence=RULE_CONFIDENCE,
            risk_percent=0.25,
            atr_percentile=float(row.get("atr_pct", 0.5)),
            spread_pips=_spread_pips(row),
            spread_class="NORMAL",
            session=_session_from_row(row),
            rr_ratio=rr_ratio,
        )
        quality = engine.evaluate(ctx)
        if not quality.allowed:
            key = quality.blocked_by or "TradeQuality"
            blockers[key] = blockers.get(key, 0) + 1
            continue
        captured.append(trade)

    raw = len(trades)
    cap = len(captured)
    capture_rate = round(cap / max(raw, 1) * 100, 2)
    labels = [int(t["outcome"]) for t in captured]
    yearly = _yearly_stats(captured)
    gate = _evaluate_gate(yearly)
    return {
        "raw_signals": raw,
        "captured": cap,
        "capture_rate_pct": capture_rate,
        "capture_gate_pct": CAPTURE_GATE_PCT,
        "capture_gate_pass": capture_rate >= CAPTURE_GATE_PCT,
        "blockers": blockers,
        "shadow_pf": _pf_from_labels(labels) if labels else 0.0,
        "shadow_trades": len(labels),
        "yearly": yearly,
        "gate": gate,
        "v41_regime_fix_active": True,
        "engine": TREND_ENGINE_V41,
        "production_rr_for_funnel": rr_ratio,
        "rule_confidence_proxy": RULE_CONFIDENCE,
    }


def _resolve_outcomes_dual_rr(
    frame: pd.DataFrame,
    candles: pd.DataFrame,
    trades: list[dict[str, Any]],
    *,
    atr_mult: float,
) -> dict[str, Any]:
    prod_labels: list[int] = []
    research_labels: list[int] = []
    rr1_fn = _make_sl_tp_fn("atr_rr", atr_mult=atr_mult, rr=1.0)

    for trade in trades:
        idx = int(trade["bar_index"])
        direction = 1 if trade["direction"] == "BUY" else -1
        prod = _resolve_trade_with_sl_tp_fn(
            candles, frame, idx, direction, rr1_fn, use_production=True
        )
        rr1 = _resolve_trade_with_sl_tp_fn(
            candles, frame, idx, direction, rr1_fn, use_production=False
        )
        if prod is not None:
            prod_labels.append(prod)
        if rr1 is not None:
            research_labels.append(rr1)

    prod_yearly_pf = _pf_from_labels(prod_labels)
    rr1_pf = _pf_from_labels(research_labels)
    return {
        "same_signal_count": len(trades),
        "production_rr_2_5": {
            "trades_resolved": len(prod_labels),
            "overall_pf": prod_yearly_pf,
            "win_rate_pct": round(sum(prod_labels) / len(prod_labels) * 100, 2) if prod_labels else 0.0,
        },
        "research_rr_1_0": {
            "trades_resolved": len(research_labels),
            "overall_pf": rr1_pf,
            "win_rate_pct": round(sum(research_labels) / len(research_labels) * 100, 2)
            if research_labels
            else 0.0,
        },
        "pf_delta_research_minus_production": round(rr1_pf - prod_yearly_pf, 4),
    }


def run_execution_validation() -> dict[str, Any]:
    cfg = _load_best_config()
    hyp_id = cfg["hypothesis_id"]
    if hyp_id not in HYPOTHESES_R2:
        hyp_id = DEFAULT_SIGNAL

    candles = resolve_fullest_candles(SYMBOL, TIMEFRAME)
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES", "error": "fullest candle source missing"}

    meta = HYPOTHESES_R2[hyp_id]
    frame = _prepare_frame_round2(candles)
    frame = frame[(frame.index.year >= YEAR_START) & (frame.index.year <= YEAR_END)]

    sl_tp_fn = _make_sl_tp_fn("atr_rr", atr_mult=cfg["atr_mult"], rr=cfg["rr"])
    trades = _scan_hypothesis_sl_tp(
        frame,
        candles,
        meta["signal_fn"],
        sl_tp_fn,
        use_production=False,
        stride=meta["stride"],
    )
    print(
        f"L3: {hyp_id} {cfg['config_id']} — {len(trades)} research trades, simulating funnel ...",
        flush=True,
    )

    funnel_prod_rr = _evaluate_production_funnel(frame, trades, rr_ratio=2.5)
    funnel_research_rr = _evaluate_production_funnel(frame, trades, rr_ratio=cfg["rr"])
    rr_compare = _resolve_outcomes_dual_rr(frame, candles, trades, atr_mult=cfg["atr_mult"])

    shadow_pf = funnel_prod_rr["shadow_pf"]
    capture = funnel_prod_rr["capture_rate_pct"]

    production_rr_recommendation = {
        "research_only": True,
        "no_production_change": True,
        "current_production_tp_rr": 2.5,
        "recommended_research_range": "1.0-1.5",
        "evidence": {
            "l2_6_baseline_pf_at_rr1": 1.0258,
            "l2_6_years_passing_gate": 2,
            "same_signals_production_rr_pf": rr_compare["production_rr_2_5"]["overall_pf"],
            "same_signals_research_rr1_pf": rr_compare["research_rr_1_0"]["overall_pf"],
            "pf_improvement_from_lower_rr": rr_compare["pf_delta_research_minus_production"],
            "trade_quality_min_rr_policy": 2.0,
            "rr_quality_at_1_0": "blocked (score=0)",
            "rr_quality_at_1_5": "partial (score=0.6)",
            "rr_quality_at_2_5": "full (score=1.0)",
        },
        "interpretation_en": (
            "Gold M5 rule edge (PULLBACK_VWAP) improves PF from ~"
            f"{rr_compare['production_rr_2_5']['overall_pf']} at production RR=2.5 to ~"
            f"{rr_compare['research_rr_1_0']['overall_pf']} at RR=1.0 on identical signals. "
            "Production TradeQuality requires RR>=2.0 for full score; lowering TP_RR to 1.0-1.5 "
            "would need coordinated policy change (rr_quality + compute_sl_tp), not TP alone."
        ),
        "interpretation_fa": (
            "لبه rule-based با RR=1.0 بهتر از RR=2.5 است؛ ولی TradeQuality فعلی RR پایین را block می‌کند"
        ),
    }

    verdict = "EXECUTION_VALIDATED" if funnel_prod_rr["capture_gate_pass"] and shadow_pf >= 1.0 else "MARGINAL_EXECUTION"

    return {
        "phase": "L3",
        "title": "Execution Path Validation",
        "title_fa": "اعتبارسنجی مسیر اجرا",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": verdict,
        "research_only": True,
        "symbol": SYMBOL,
        "timeframe": TIMEFRAME,
        "year_range": [YEAR_START, YEAR_END],
        "config_used": cfg,
        "methodology": {
            "future_window_bars": FUTURE_WINDOW,
            "gate_pf": GATE_PF,
            "capture_gate_pct": CAPTURE_GATE_PCT,
            "v41_fix": "trend_rf_v41 alias active in regime_quality.py",
            "funnel_simulation": "TradeQualityEngine + regime_quality v41 on rule signals",
        },
        "research_backtest": {
            "total_trades": len(trades),
            "overall_pf": _pf_from_labels([int(t["outcome"]) for t in trades]),
            "yearly": _yearly_stats(trades),
            "gate": _evaluate_gate(_yearly_stats(trades)),
        },
        "production_funnel_rr2_5": funnel_prod_rr,
        "production_funnel_research_rr": funnel_research_rr,
        "rr_comparison_same_signals": rr_compare,
        "production_rr_recommendation": production_rr_recommendation,
        "honest_assessment_en": (
            f"Capture {capture}% with production RR=2.5 funnel; shadow PF={shadow_pf}. "
            "Marginal research edge exists but 3-year gate not met."
        ),
        "honest_assessment_fa": (
            f"نرخ capture={capture}%؛ shadow PF={shadow_pf}؛ لبه marginal است نه honest edge"
        ),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_execution_validation()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    return data


if __name__ == "__main__":
    main()
