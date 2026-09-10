"""Phase 27M — exit strategy robustness across market windows (read-only)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase27a.trade_builder import build_completed_trades
from tradingbot.ml.research.phase27l.exit_trace import prepare_indicator_frame
from tradingbot.ml.research.phase27m.metrics import (
    WINDOWS,
    build_final_report,
    build_global_ranking,
    build_montecarlo_analysis,
    build_overfitting_report,
    build_stability_analysis,
    build_walkforward_analysis,
    build_window_report,
    determine_verdict,
)
from tradingbot.ml.research.phase27m.window_runner import (
    load_or_replay_window,
    simulate_window_trades,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = PHASE_DIR / "_cache"
PHASE27F_CACHE = PHASE_DIR.parent / "phase27f" / "_cache" / "replay_records.json"


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return str(obj)
    return obj


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")


def run_phase27m(*, base_dir: str | Path | None = None, windows: tuple[int, ...] = WINDOWS) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    window_reports: dict[int, dict[str, Any]] = {}
    mc_trades: list[dict[str, Any]] = []
    mc_sim: list[dict[str, Any]] = []
    mc_frame = None

    for days in windows:
        print(f"[phase27m] processing {days}-day window...")
        ext = PHASE27F_CACHE if days == 30 else None
        records, window, meta = load_or_replay_window(
            base_dir=root,
            cache_dir=CACHE_DIR,
            days=days,
            external_cache=ext,
        )
        if not records or window.empty:
            print(f"[phase27m] skip {days}d — no data")
            continue
        trades = build_completed_trades(records, window, symbol="XAUUSD")
        frame = prepare_indicator_frame(window)
        sim_results = simulate_window_trades(trades, frame)
        report = build_window_report(days=days, trades=trades, sim_results=sim_results, meta=meta, window=window)
        report["generated_utc"] = ts
        window_reports[days] = report
        _write(f"window_{days}.json", report)
        if days == 30:
            mc_trades = trades
            mc_sim = sim_results
            mc_frame = frame
        print(f"[phase27m] {days}d — {len(trades)} trades, winner={report.get('window_winner')}")

    stability = build_stability_analysis(window_reports)
    montecarlo = build_montecarlo_analysis(mc_trades, mc_sim, mc_frame)
    walkforward = build_walkforward_analysis(window_reports)
    overfitting = build_overfitting_report(window_reports, stability)
    global_ranking = build_global_ranking(window_reports, stability, montecarlo, walkforward)
    verdict, blockers = determine_verdict(
        overfitting=overfitting,
        walkforward=walkforward,
        global_ranking=global_ranking,
        stability=stability,
    )
    final = build_final_report(
        verdict=verdict,
        blockers=blockers,
        global_ranking=global_ranking,
        walkforward=walkforward,
        overfitting=overfitting,
        window_reports=window_reports,
    )
    final["generated_utc"] = ts

    outputs = {
        "stability_analysis.json": {**stability, "generated_utc": ts},
        "montecarlo_analysis.json": {**montecarlo, "generated_utc": ts},
        "walkforward_analysis.json": {**walkforward, "generated_utc": ts},
        "overfitting_report.json": {**overfitting, "generated_utc": ts},
        "global_ranking.json": {**global_ranking, "generated_utc": ts},
        "phase27m_final_report.json": final,
    }
    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27m()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "EXIT_STRATEGY_ROBUST" else 1


if __name__ == "__main__":
    raise SystemExit(main())
