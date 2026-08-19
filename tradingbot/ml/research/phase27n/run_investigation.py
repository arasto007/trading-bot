"""Phase 27N — hybrid exit architecture validation (read-only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase27n.hybrid_simulators import HYBRID_STRATEGIES
from tradingbot.ml.research.phase27n.metrics import (
    build_comparison_matrix,
    build_equity_comparison,
    build_final_report,
    build_global_ranking,
    build_hybrid_report,
    build_montecarlo_report,
    build_risk_comparison,
    build_stability_report,
    build_window_strategy_map,
    determine_verdict,
)
from tradingbot.ml.research.phase27n.window_runner import WINDOWS, process_window

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE27M_CACHE = PHASE_DIR.parent / "phase27m" / "_cache"
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


def run_phase27n(*, base_dir: str | Path | None = None, windows: tuple[int, ...] = WINDOWS) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)
    window_data: dict[int, dict[str, Any]] = {}
    sim_30: list[dict[str, Any]] = []
    trades_30: list[dict[str, Any]] = []
    frame_30 = None

    for days in windows:
        print(f"[phase27n] processing {days}-day window...")
        trades, sim_results, frame, meta = process_window(
            base_dir=root,
            phase27m_cache=PHASE27M_CACHE,
            days=days,
            phase27f_cache=PHASE27F_CACHE,
        )
        if not trades:
            print(f"[phase27n] skip {days}d — {meta.get('error', 'no trades')}")
            continue
        report = build_window_strategy_map(days=days, trades=trades, sim_results=sim_results, meta=meta)
        report["generated_utc"] = ts
        window_data[days] = report
        if days == 30:
            sim_30 = sim_results
            trades_30 = trades
            frame_30 = frame
        winner = max(
            report["strategies"].items(),
            key=lambda x: float(x[1].get("expectancy") or -1e9),
        )[0]
        print(f"[phase27n] {days}d — {len(trades)} trades, winner={winner}")

    stability = build_stability_report(window_data)
    stability["generated_utc"] = ts
    montecarlo = build_montecarlo_report(trades_30, sim_30, frame_30)
    montecarlo["generated_utc"] = ts
    equity = build_equity_comparison(sim_30)
    equity["generated_utc"] = ts
    risk = build_risk_comparison(sim_30)
    risk["generated_utc"] = ts
    matrix = build_comparison_matrix(window_data)
    matrix["generated_utc"] = ts
    global_ranking = build_global_ranking(stability, montecarlo, equity)
    global_ranking["generated_utc"] = ts
    verdict, blockers = determine_verdict(global_ranking)
    final = build_final_report(
        verdict=verdict,
        blockers=blockers,
        global_ranking=global_ranking,
        window_data=window_data,
    )
    final["generated_utc"] = ts

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    hybrid_files = {
        f"{h}.json": {**build_hybrid_report(h, window_data), "generated_utc": ts} for h in HYBRID_STRATEGIES
    }
    outputs = {
        **hybrid_files,
        "comparison_matrix.json": matrix,
        "equity_comparison.json": equity,
        "risk_comparison.json": risk,
        "stability_report.json": stability,
        "montecarlo_report.json": montecarlo,
        "global_ranking.json": global_ranking,
        "phase27n_final_report.json": final,
    }
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27n()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "HYBRID_EXIT_OUTPERFORMS_ALL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
