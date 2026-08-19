"""L2.7 — RR fine-tune + multi-signal sweep at RR~1.0 (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.live_l2.edge_discovery import (
    FUTURE_WINDOW,
    GATE_MIN_TRADES_YEAR,
    GATE_MIN_YEARS_PASS,
    GATE_PF,
)
from tradingbot.ml.research.live_l2.edge_discovery_round2 import (
    HYPOTHESES_R2,
    _prepare_frame_round2,
)
from tradingbot.ml.research.live_l2.sl_tp_sweep import (
    _config_report,
    _make_sl_tp_fn,
    _scan_hypothesis_sl_tp,
)
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles

ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = ROOT / "live_l2_edge_discovery_l27_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
YEAR_START = 2021
YEAR_END = 2026
TOP_SIGNALS = ("PULLBACK_VWAP", "SPREAD_SESSION", "VOL_REGIME")
RR_VALUES = (0.8, 1.0, 1.2, 1.5)
ATR_MULTS = (1.5, 2.0, 2.5)


def _build_l27_configs() -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for atr_mult in ATR_MULTS:
        for rr in RR_VALUES:
            configs.append(
                {
                    "config_id": f"ATR{atr_mult}_RR{rr}",
                    "mode": "atr_rr",
                    "atr_mult": atr_mult,
                    "rr": rr,
                    "description": f"ATR SL x{atr_mult}, RR={rr}",
                }
            )
    return configs


def run_edge_discovery_l27(
    *,
    symbol: str = SYMBOL,
    timeframe: str = TIMEFRAME,
    year_start: int = YEAR_START,
    year_end: int = YEAR_END,
    hypotheses: tuple[str, ...] = TOP_SIGNALS,
) -> dict[str, Any]:
    candles = resolve_fullest_candles(symbol, timeframe)
    if candles is None or candles.empty:
        return {"verdict": "NO_CANDLES", "error": "fullest candle source missing"}

    frame = _prepare_frame_round2(candles)
    frame = frame[(frame.index.year >= year_start) & (frame.index.year <= year_end)]
    configs = _build_l27_configs()

    hypothesis_results: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []

    for hyp_id in hypotheses:
        if hyp_id not in HYPOTHESES_R2:
            continue
        meta = HYPOTHESES_R2[hyp_id]
        signal_fn = meta["signal_fn"]
        stride = meta["stride"]
        config_results: list[dict[str, Any]] = []

        print(f"L2.7: {hyp_id} — {len(configs)} RR/ATR configs ...", flush=True)
        for cfg in configs:
            sl_tp_fn = _make_sl_tp_fn(
                cfg["mode"],
                atr_mult=cfg.get("atr_mult"),
                rr=cfg.get("rr"),
            )
            trades = _scan_hypothesis_sl_tp(
                frame,
                candles,
                signal_fn,
                sl_tp_fn,
                use_production=False,
                stride=stride,
            )
            rep = _config_report(cfg["config_id"], cfg, trades)
            config_results.append(rep)
            all_rows.append(
                {
                    "hypothesis": hyp_id,
                    "config_id": cfg["config_id"],
                    "atr_mult": cfg["atr_mult"],
                    "rr": cfg["rr"],
                    "overall_pf": rep["overall_pf"],
                    "total_trades": rep["total_trades"],
                    "honest_edge": rep["honest_edge"],
                    "years_passed_gate": rep["gate"]["years_passed_gate"],
                }
            )
            if rep["honest_edge"] or rep["overall_pf"] >= 1.0:
                print(
                    f"  {cfg['config_id']}: pf={rep['overall_pf']} "
                    f"years_pass={rep['gate']['years_passed_gate']} gate={rep['honest_edge']}",
                    flush=True,
                )

        config_results.sort(
            key=lambda r: (r["honest_edge"], r["overall_pf"], r["total_trades"]),
            reverse=True,
        )
        hypothesis_results.append(
            {
                "hypothesis_id": hyp_id,
                "title_en": meta["title_en"],
                "stride": stride,
                "configs": config_results,
                "best_config": config_results[0]["config_id"] if config_results else None,
                "best_pf": config_results[0]["overall_pf"] if config_results else 0.0,
                "best_years_passed": config_results[0]["gate"]["years_passed_gate"]
                if config_results
                else 0,
                "any_honest_edge": any(c["honest_edge"] for c in config_results),
            }
        )

    passing = [r for hr in hypothesis_results for r in hr["configs"] if r["honest_edge"]]
    all_rows.sort(key=lambda x: (x["honest_edge"], x["overall_pf"], x["years_passed_gate"]), reverse=True)
    best_overall = all_rows[0] if all_rows else None

    any_pass = bool(passing)
    return {
        "phase": "L2.7",
        "title": "RR Fine-tune + Multi-Signal",
        "title_fa": "تنظیم RR + چند سیگنال",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "EDGE_FOUND" if any_pass else "NO_HONEST_EDGE",
        "research_only": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "year_range": [year_start, year_end],
        "hypotheses_tested": list(hypotheses),
        "methodology": {
            "rr_values_tested": list(RR_VALUES),
            "atr_mult_values_tested": list(ATR_MULTS),
            "future_window_bars": FUTURE_WINDOW,
            "gate_pf": GATE_PF,
            "gate_min_trades_year": GATE_MIN_TRADES_YEAR,
            "gate_min_years": GATE_MIN_YEARS_PASS,
            "config_count_per_hypothesis": len(configs),
        },
        "hypothesis_results": hypothesis_results,
        "ranking": all_rows[:20],
        "best_overall": best_overall,
        "any_config_passes_gate": any_pass,
        "configs_passing_gate": [
            {"hypothesis": c.get("hypothesis"), "config_id": c["config_id"], "overall_pf": c["overall_pf"]}
            for hr in hypothesis_results
            for c in hr["configs"]
            if c["honest_edge"]
        ],
        "recommendation_en": (
            "At least one signal+RR config passes 3-year gate — proceed to L3"
            if any_pass
            else "No config passes 3-year gate — use L2.6 baseline for marginal L3/L4"
        ),
        "recommendation_fa": (
            "حداقل یک پیکربندی gate سه‌ساله را پاس کرد"
            if any_pass
            else "هیچ پیکربندی gate سه‌ساله را پاس نکرد — از baseline L2.6 برای L3/L4 استفاده شود"
        ),
    }


def write_report(data: dict[str, Any], path: Path | None = None) -> Path:
    out = path or REPORT_PATH
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> dict[str, Any]:
    data = run_edge_discovery_l27()
    write_report(data)
    print(f"Report written: {REPORT_PATH}", flush=True)
    return data


if __name__ == "__main__":
    main()
