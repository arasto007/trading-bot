"""Phase 27B — root cause investigation for zero trades (READ ONLY)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase27b.bar_tracer import run_bar_trace
from tradingbot.ml.research.phase27b.metrics import (
    build_buy_sell_filter_statistics,
    build_distribution_analysis,
    build_engine_statistics,
    build_feature_quality,
    build_filter_location,
    build_final_report,
    build_pre_post_filter_statistics,
    build_root_cause_rank,
    build_rsi_hold_log,
    build_stage_funnel,
    build_threshold_sensitivity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = PHASE_DIR / "_cache"
PHASE27A_CACHE = PHASE_DIR.parent / "phase27a" / "_cache"

REPLAY_DAYS = 30
WARMUP_BARS = 300
STRIDE = 1

DELIVERABLES = [
    "filter_location.json",
    "rsi_hold_log.json",
    "buy_sell_filter_statistics.json",
    "pre_post_filter_statistics.json",
    "distribution_analysis.json",
    "threshold_sensitivity.json",
    "stage_funnel.json",
    "feature_quality.json",
    "engine_statistics.json",
    "root_cause_rank.json",
    "final_report.json",
]


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return str(obj)
    return obj


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_json_safe(payload), indent=2), encoding="utf-8")


def _load_hold_chain_27a() -> dict[str, Any]:
    path = PHASE27A_CACHE / "hold_chain.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def run_phase27b(*, base_dir: str | Path | None = None, use_cache: bool = True) -> dict[str, Any]:
    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"

    root = Path(base_dir or PROJECT_ROOT)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    trace_cache = CACHE_DIR / "bar_trace.json"

    if use_cache and trace_cache.is_file():
        trace_payload = json.loads(trace_cache.read_text(encoding="utf-8"))
        print(f"[phase27b] loaded cached bar trace ({trace_payload.get('bars_traced')} bars)")
    else:
        trace_payload = run_bar_trace(
            days=REPLAY_DAYS,
            warmup_bars=WARMUP_BARS,
            stride=STRIDE,
            base_dir=str(root),
        )
        trace_cache.write_text(json.dumps(_json_safe(trace_payload)), encoding="utf-8")
        print(f"[phase27b] cached bar trace to {trace_cache}")

    records = trace_payload.get("records") or []
    hold_chain_27a = _load_hold_chain_27a()

    filter_location = build_filter_location(project_root=root)
    rsi_hold_log = build_rsi_hold_log(records)
    buy_sell = build_buy_sell_filter_statistics(records)
    pre_post = build_pre_post_filter_statistics(records)
    distribution = build_distribution_analysis(records)
    threshold = build_threshold_sensitivity(records)
    funnel = build_stage_funnel(records, hold_chain_27a=hold_chain_27a)
    feature_quality = build_feature_quality(records)
    engine_stats = build_engine_statistics(records)
    root_causes = build_root_cause_rank(
        records=records,
        hold_chain_27a=hold_chain_27a,
        filter_location=filter_location,
        buy_sell=buy_sell,
        pre_post=pre_post,
        threshold=threshold,
        project_root=root,
    )
    final_report = build_final_report(
        root_causes=root_causes,
        pre_post=pre_post,
        buy_sell=buy_sell,
        hold_chain_27a=hold_chain_27a,
        trace_meta=trace_payload,
    )

    outputs = {
        "filter_location.json": filter_location,
        "rsi_hold_log.json": rsi_hold_log,
        "buy_sell_filter_statistics.json": buy_sell,
        "pre_post_filter_statistics.json": pre_post,
        "distribution_analysis.json": distribution,
        "threshold_sensitivity.json": threshold,
        "stage_funnel.json": funnel,
        "feature_quality.json": feature_quality,
        "engine_statistics.json": engine_stats,
        "root_cause_rank.json": root_causes,
        "final_report.json": final_report,
    }
    for name, payload in outputs.items():
        _write(PHASE_DIR / name, payload)

    summary = {
        "phase": "27B",
        "audit_mode": "READ_ONLY",
        "production_modified": False,
        "deliverables": DELIVERABLES,
        "bars_traced": len(records),
        "verdict": final_report.get("verdict"),
        "primary_root_cause": final_report.get("primary_root_cause"),
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write(PHASE_DIR / "phase27b_summary.json", summary)
    return summary


def main() -> int:
    use_cache = "--no-cache" not in sys.argv
    summary = run_phase27b(use_cache=use_cache)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
