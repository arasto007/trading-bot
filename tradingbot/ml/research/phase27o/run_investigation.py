"""Phase 27O — out-of-sample hybrid exit validation (read-only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase27o.metrics import (
    build_final_report,
    build_generalization_gap,
    build_montecarlo_validation,
    build_oos_metrics,
    build_oos_ranking,
    build_overfitting_check,
    build_split_results,
    determine_verdict,
    strategy_metrics,
)
from tradingbot.ml.research.phase27o.split import split_trades_chronological
from tradingbot.ml.research.phase27o.window_runner import COMPARE_STRATEGIES, WINDOWS, process_window

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


def run_phase27o(*, base_dir: str | Path | None = None, windows: tuple[int, ...] = WINDOWS) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    root = Path(base_dir or PROJECT_ROOT)

    all_train_trades: list[dict[str, Any]] = []
    all_train_sim: list[dict[str, Any]] = []
    all_val_trades: list[dict[str, Any]] = []
    all_val_sim: list[dict[str, Any]] = []
    window_splits: dict[int, dict[str, Any]] = {}
    val_trades_30: list[dict[str, Any]] = []
    val_sim_30: list[dict[str, Any]] = []
    frame_30 = None

    for days in windows:
        print(f"[phase27o] processing {days}-day window...")
        trades, sim_results, frame, meta = process_window(
            base_dir=root,
            phase27m_cache=PHASE27M_CACHE,
            days=days,
            phase27f_cache=PHASE27F_CACHE,
        )
        if not trades:
            print(f"[phase27o] skip {days}d — {meta.get('error', 'no trades')}")
            continue

        train_t, val_t, train_s, val_s = split_trades_chronological(trades, sim_results)
        all_train_trades.extend(train_t)
        all_train_sim.extend(train_s)
        all_val_trades.extend(val_t)
        all_val_sim.extend(val_s)

        train_strats = {s: strategy_metrics(train_t, train_s, s) for s in COMPARE_STRATEGIES} if train_s else {}
        val_strats = {s: strategy_metrics(val_t, val_s, s) for s in COMPARE_STRATEGIES} if val_s else {}
        window_splits[days] = {
            "train_trade_count": len(train_t),
            "val_trade_count": len(val_t),
            "train_strategies": train_strats,
            "val_strategies": val_strats,
            "meta": {k: meta[k] for k in meta if k != "portfolio_timeline"},
        }
        if days == 30:
            val_trades_30 = val_t
            val_sim_30 = val_s
            frame_30 = frame
        print(f"[phase27o] {days}d — train={len(train_t)} val={len(val_t)}")

    train_results = build_split_results(
        split_name="train_70pct",
        trades=all_train_trades,
        sim_results=all_train_sim,
        per_window={str(k): v.get("train_strategies", {}) for k, v in window_splits.items()},
    )
    train_results["generated_utc"] = ts

    validation_results = build_split_results(
        split_name="validation_30pct",
        trades=all_val_trades,
        sim_results=all_val_sim,
        per_window={str(k): v.get("val_strategies", {}) for k, v in window_splits.items()},
    )
    validation_results["generated_utc"] = ts

    generalization = build_generalization_gap(train_results, validation_results)
    generalization["generated_utc"] = ts

    oos_metrics = build_oos_metrics(window_splits)
    oos_metrics["generated_utc"] = ts

    montecarlo = build_montecarlo_validation(
        all_val_trades,
        all_val_sim,
        raw_trades=val_trades_30,
        frame=frame_30,
    )
    montecarlo["generated_utc"] = ts

    ranking = build_oos_ranking(validation_results, generalization)
    ranking["generated_utc"] = ts

    overfitting = build_overfitting_check(generalization, ranking)

    verdict, blockers = determine_verdict(
        ranking=ranking,
        generalization=generalization,
        overfitting=overfitting,
    )
    final = build_final_report(
        verdict=verdict,
        blockers=blockers,
        ranking=ranking,
        generalization=generalization,
        overfitting=overfitting,
    )
    final["generated_utc"] = ts

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "train_results.json": train_results,
        "validation_results.json": validation_results,
        "generalization_gap.json": generalization,
        "out_of_sample_metrics.json": oos_metrics,
        "montecarlo_validation.json": montecarlo,
        "ranking.json": ranking,
        "phase27o_final_report.json": final,
    }
    for name, payload in outputs.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase27o()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") == "HYBRID_READY_FOR_IMPLEMENTATION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
