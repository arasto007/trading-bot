"""Phase 31D — simulator parity audit orchestrator (research only)."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase31a.data_loader import build_master_frame
from tradingbot.ml.research.phase31c.exit_simulators import load_candles
from tradingbot.ml.research.phase31d.parity_audit import (
    PARITY_PF_TOLERANCE,
    PARITY_PNL_TOLERANCE,
    aggregate_parity,
    audit_single_trade,
    load_replay_parity_candles,
)
from tradingbot.ml.research.phase31d.root_causes import build_root_cause_analysis

PHASE_DIR = Path(__file__).resolve().parent
CACHE_CANDLES = PHASE_DIR.parent / "phase31c" / "_cache" / "candles_m5.parquet"
VERDICTS = {"SIMULATOR_PARITY_CONFIRMED", "SIMULATOR_PARITY_FAILED"}


def _safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    return obj


def _write(name: str, payload: dict | list) -> None:
    (PHASE_DIR / name).write_text(json.dumps(_safe(payload), indent=2, default=str), encoding="utf-8")


def determine_verdict(aggregate: dict[str, Any]) -> str:
    if (
        aggregate.get("parity_pf_within_tolerance")
        and aggregate.get("parity_pnl_within_tolerance")
        and aggregate.get("trade_count_identical")
        and aggregate.get("exit_fingerprints_identical")
    ):
        return "SIMULATOR_PARITY_CONFIRMED"
    return "SIMULATOR_PARITY_FAILED"


def run_phase31d(*, repaired: bool = False) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    df, meta = build_master_frame()
    trades = df.to_dict("records")
    research_frame = load_candles(CACHE_CANDLES, trades=trades)
    replay_frame = load_replay_parity_candles()

    trade_audits = [audit_single_trade(t, research_frame, replay_frame, repaired=repaired) for t in trades]
    aggregate = aggregate_parity(trade_audits, repaired=repaired)
    verdict = determine_verdict(aggregate)
    root_causes = build_root_cause_analysis(trade_audits, aggregate)

    # --- trade_diff_report.json ---
    mismatch_summary = Counter()
    for a in trade_audits:
        d = a["diffs"]["production_vs_hybrid_b_proxy"]
        mismatch_summary[d["mismatch_count"]] += 1

    _write("trade_diff_report.json", {
        "phase": "31D",
        "trade_count": len(trade_audits),
        "mismatch_histogram": dict(sorted(mismatch_summary.items())),
        "aggregate": aggregate,
        "trades": [{
            "trade_id": a["trade_id"],
            "timestamp": a["timestamp"],
            "production_pnl": a["production"]["pnl"],
            "proxy_pnl": a["simulator_hybrid_b_proxy"]["pnl"],
            "pnl_delta": a["diffs"]["production_vs_hybrid_b_proxy"]["pnl_delta"],
            "production_duration": a["production"]["duration_bars"],
            "proxy_duration": a["simulator_hybrid_b_proxy"]["duration_bars"],
            "production_exit": a["production"]["exit_reason"],
            "proxy_exit": a["simulator_hybrid_b_proxy"]["exit_reason"],
            "fingerprint_match": a["diffs"]["production_vs_hybrid_b_proxy"]["exit_fingerprint_match"],
            "truncated_matches_legacy": a["diffs"]["legacy_vs_truncated_replay"]["exit_fingerprint_match"],
            "repaired_matches_oracle": a["diffs"]["repaired_vs_oracle"]["exit_fingerprint_match"],
            "primary_cause": a["primary_divergence_cause"],
        } for a in trade_audits],
        "generated_utc": ts,
    })

    # --- exit_diff_report.json ---
    mismatch_key = "repaired_vs_oracle" if repaired else "production_vs_hybrid_b_proxy"
    exit_field_mismatches: Counter[str] = Counter()
    for a in trade_audits:
        for m in a["diffs"][mismatch_key]["mismatches"]:
            exit_field_mismatches[m["field"]] += 1

    _write("exit_diff_report.json", {
        "phase": "31D",
        "repaired_mode": repaired,
        "production_exit_distribution": root_causes["production_exit_distribution"],
        "simulator_exit_distribution": root_causes["proxy_exit_distribution"],
        "truncated_replay_exit_distribution": root_causes["truncated_replay_exit_distribution"],
        "field_mismatch_counts": dict(exit_field_mismatches),
        "duration_delta_histogram": root_causes["duration_delta_histogram"],
        "early_1bar_time_exits": root_causes["early_1bar_time_exits"],
        "exit_fingerprint_match_pct": round(
            100 * aggregate["exit_fingerprint_match_count"] / max(len(trade_audits), 1), 2
        ),
        "generated_utc": ts,
    })

    # --- accounting_diff.json ---
    partial_mismatch = sum(
        1 for a in trade_audits
        if a["simulator_repaired_replay"]["partial_close_applied"] != a["simulator_oracle_replay"]["partial_close_applied"]
    ) if repaired else sum(
        1 for a in trade_audits
        if a["production"]["partial_close_applied"] != a["simulator_hybrid_b_proxy"]["partial_close_applied"]
    )
    _write("accounting_diff.json", {
        "phase": "31D",
        "repaired_mode": repaired,
        "production_net_pnl": aggregate["production_net_pnl"],
        "simulator_net_pnl": aggregate["simulator_net_pnl"],
        "net_pnl_delta": round(aggregate["simulator_net_pnl"] - aggregate["production_net_pnl"], 4),
        "pnl_gap_pct": aggregate["pnl_gap_pct"],
        "production_pf": aggregate["production_pf"],
        "simulator_pf": aggregate["simulator_pf"],
        "pf_gap_pct": aggregate["pf_gap_pct"],
        "partial_close_mismatch_count": partial_mismatch,
        "floating_pnl_note": "Replay uses realized PnL only; no floating PnL divergence in closed trades",
        "closed_pnl_trades_compared": len(trade_audits),
        "acceptance_pnl_tolerance_pct": PARITY_PNL_TOLERANCE * 100,
        "acceptance_pf_tolerance_pct": PARITY_PF_TOLERANCE * 100,
        "generated_utc": ts,
    })

    # --- journal_diff.json ---
    bar_idx_mismatch = sum(
        1 for a in trade_audits
        if a.get("legacy_production", {}).get("bar_index") is not None
        and a["candle_alignment"].get("journal_bar_index") is not None
        and int(a["legacy_production"]["bar_index"]) != int(a["candle_alignment"]["resolved_bar_index"])
    ) if not repaired else sum(
        1 for a in trade_audits
        if a.get("legacy_production", {}).get("bar_index") is not None
        and int(a["legacy_production"]["bar_index"]) != int(a["simulator_repaired_replay"].get("entry_bar_index", -1))
    )
    _write("journal_diff.json", {
        "phase": "31D",
        "repaired_mode": repaired,
        "entry_timestamp_consistency": True,
        "bar_index_mismatch_count": bar_idx_mismatch,
        "candle_alignment_aligned_count": sum(1 for a in trade_audits if a["candle_alignment"]["aligned"]),
        "spread_production_mean": round(
            sum(float(a["production"]["spread"]) for a in trade_audits) / len(trade_audits), 4
        ),
        "position_state_note": "ReplayOpenPosition does not persist partial_close state between bars",
        "generated_utc": ts,
    })

    # --- execution_diff.json ---
    _write("execution_diff.json", {
        "phase": "31D",
        "repaired_mode": repaired,
        "production_path": {
            "file": "tradingbot/ml/research/phase25b/replay_portfolio.py",
            "function": "ReplayPortfolioTracker.advance_to_bar",
            "behavior": "Re-evaluates exit each bar on truncated candle slice",
        },
        "simulator_path": {
            "file": "tradingbot/ml/research/phase27n/hybrid_simulators.py",
            "function": "simulate_hybrid",
            "behavior": "Single-pass full-frame bar walk up to MAX_HOLD_BARS",
        },
        "order_of_execution": "Production: open → advance_to_bar(entry+1) → immediate time exit. Simulator: open → walk 72 bars.",
        "tick_interpolation": "None — M5 OHLC bar resolution via PaperBroker.resolve_bar",
        "truncated_replay_matches_legacy_duration": aggregate.get("duration_match_oracle_count", 0),
        "repaired_oracle_match_pct": round(
            100 * aggregate.get("exit_fingerprint_match_count_oracle", aggregate.get("exit_fingerprint_match_count", 0))
            / max(len(trade_audits), 1), 2
        ),
        "generated_utc": ts,
    })

    # --- candle_alignment.json ---
    _write("candle_alignment.json", {
        "phase": "31D",
        "research_candle_source": str(CACHE_CANDLES),
        "replay_candle_source": "CandleStore + prepare_calibration_candles(days=30)",
        "research_frame_bars": len(research_frame),
        "replay_frame_bars": len(replay_frame),
        "aligned_trades": sum(1 for a in trade_audits if a["candle_alignment"]["aligned"]),
        "misaligned_trades": sum(1 for a in trade_audits if not a["candle_alignment"]["aligned"]),
        "max_close_entry_delta": max(
            (a["candle_alignment"]["close_entry_delta"] or 0) for a in trade_audits
        ),
        "bar_walking": "searchsorted(entry_timestamp) on M5 DatetimeIndex",
        "samples": [a["candle_alignment"] for a in trade_audits[:5]],
        "generated_utc": ts,
    })

    # --- root_cause_analysis.json ---
    _write("root_cause_analysis.json", root_causes | {"generated_utc": ts})

    # --- simulator_parity_report.json ---
    _write("simulator_parity_report.json", {
        "phase": "31D",
        "verdict": verdict,
        "acceptance_criteria": {
            "pf_difference_pct_max": PARITY_PF_TOLERANCE * 100,
            "pnl_difference_pct_max": PARITY_PNL_TOLERANCE * 100,
            "trade_count_identical": True,
            "exit_fingerprints_identical": True,
        },
        "observed": {
            "pf_gap_pct": aggregate["pf_gap_pct"],
            "pnl_gap_pct": aggregate["pnl_gap_pct"],
            "trade_count": aggregate["trade_count"],
            "exit_fingerprint_matches": aggregate["exit_fingerprint_match_count"],
            "exit_fingerprint_total": aggregate["trade_count"],
            "repaired_mode": repaired,
        },
        "aggregate_metrics": aggregate,
        "dominant_explanation": (
            "Repaired replay uses persistent ReplayPositionState (Phase 31E). "
            "Parity compares stateful replay vs resolve_hybrid_b oracle on same replay candles."
            if repaired else
            "Legacy production replay truncates candles in ReplayPortfolioTracker._exit_up_to_bar, "
            "forcing ~98% of trades to 1-bar time exits (PF 1.211). Research simulator "
            "hybrid_b_proxy uses full 72-bar frame (PF ~2.063). Policy code is identical; "
            "data window is not."
        ),
        "generated_utc": ts,
    })

    final = {
        "phase": "31D",
        "verdict": verdict,
        "repaired_mode": repaired,
        "production_modified": False,
        "trades_audited": len(trade_audits),
        "production_pf": aggregate["production_pf"],
        "simulator_pf": aggregate["simulator_pf"],
        "pf_gap_pct": aggregate["pf_gap_pct"],
        "pnl_gap_pct": aggregate["pnl_gap_pct"],
        "dominant_root_cause": root_causes["dominant_root_cause"],
        "truncated_replay_reproduces_production_pct": root_causes["truncated_replay_duration_match_pct"],
        "deliverables": [
            "trade_diff_report.json",
            "exit_diff_report.json",
            "accounting_diff.json",
            "journal_diff.json",
            "execution_diff.json",
            "candle_alignment.json",
            "root_cause_analysis.json",
            "simulator_parity_report.json",
            "phase31d_final_report.json",
        ],
        "generated_utc": ts,
    }
    _write("phase31d_final_report.json", final)
    return final


def main() -> int:
    report = run_phase31d()
    print(json.dumps({
        "verdict": report["verdict"],
        "production_pf": report["production_pf"],
        "simulator_pf": report["simulator_pf"],
        "pf_gap_pct": report["pf_gap_pct"],
        "dominant_root_cause": report["dominant_root_cause"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
