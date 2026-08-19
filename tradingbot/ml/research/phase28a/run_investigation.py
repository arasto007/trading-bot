"""Phase 28A — paper trading A/B validation runner (read-only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase28a.metrics import (
    build_decision_matrix,
    build_equity_comparison,
    build_final_report,
    build_head_to_head,
    build_montecarlo_comparison,
    build_paired_trade_comparison,
    build_risk_comparison,
    build_strategy_results,
    determine_verdict,
)
from tradingbot.ml.research.phase28a.window_runner import WINDOWS, process_window

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


def run_phase28a(*, base_dir: str | Path | None = None, windows: tuple[int, ...] = WINDOWS) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)

    all_trades: list[dict[str, Any]] = []
    all_sim: list[dict[str, Any]] = []
    window_data: dict[int, dict[str, Any]] = {}
    sim_30: list[dict[str, Any]] = []
    trades_30: list[dict[str, Any]] = []
    frame_30 = None

    for days in windows:
        print(f"[phase28a] processing {days}-day window...")
        trades, sim_results, frame, meta = process_window(
            base_dir=root,
            phase27m_cache=PHASE27M_CACHE,
            days=days,
            phase27f_cache=PHASE27F_CACHE,
        )
        if not trades:
            print(f"[phase28a] skip {days}d — {meta.get('error', 'no trades')}")
            continue
        all_trades.extend(trades)
        all_sim.extend(sim_results)
        window_data[days] = {"trades": trades, "sim": sim_results, "meta": meta}
        if days == 30:
            sim_30 = sim_results
            trades_30 = trades
            frame_30 = frame
        print(f"[phase28a] {days}d — {len(trades)} paired trades")

    strategy_a = build_strategy_results(
        strategy="hybrid_b",
        label="Hybrid B — Partial 50% @1R + Time Exit 72b",
        window_data=window_data,
        aggregate_trades=all_trades,
        aggregate_sim=all_sim,
    )
    strategy_a["generated_utc"] = ts

    strategy_b = build_strategy_results(
        strategy="time_exit",
        label="Time Exit — Full position 72 bars",
        window_data=window_data,
        aggregate_trades=all_trades,
        aggregate_sim=all_sim,
    )
    strategy_b["generated_utc"] = ts

    paired = build_paired_trade_comparison(all_sim)
    paired["generated_utc"] = ts

    head_to_head = build_head_to_head(all_sim)
    head_to_head["generated_utc"] = ts

    equity = build_equity_comparison(sim_30, window_days=30)
    equity["generated_utc"] = ts

    risk = build_risk_comparison(all_sim)
    risk["generated_utc"] = ts

    montecarlo = build_montecarlo_comparison(all_sim, trades_30, frame_30)
    montecarlo["generated_utc"] = ts

    decision = build_decision_matrix(strategy_a, strategy_b, paired, montecarlo, equity)
    decision["generated_utc"] = ts

    verdict, blockers = determine_verdict(decision, paired)
    final = build_final_report(verdict=verdict, blockers=blockers, decision=decision, paired=paired)
    final["generated_utc"] = ts

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "strategy_a_results.json": strategy_a,
        "strategy_b_results.json": strategy_b,
        "paired_trade_comparison.json": paired,
        "head_to_head.json": head_to_head,
        "equity_comparison.json": equity,
        "risk_comparison.json": risk,
        "montecarlo_comparison.json": montecarlo,
        "decision_matrix.json": decision,
        "phase28a_final_report.json": final,
    }
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase28a()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") in ("HYBRID_B_IS_BEST", "NO_STATISTICAL_DIFFERENCE") else 1


if __name__ == "__main__":
    raise SystemExit(main())
