"""Phase 24C — generate latency JSON deliverables (read-only)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingbot.ml.research.phase24c.latency_profiler import build_all_deliverables

PHASE_DIR = Path(__file__).resolve().parent

REQUIRED_FILES = (
    "latency_profile.json",
    "stage_timings.json",
    "cache_statistics.json",
    "pipeline_flamegraph.json",
    "bottleneck_report.json",
    "optimization_candidates.json",
    "phase24c_final_report.json",
)


def write_deliverables(
    *,
    base_dir: str | None = None,
    out_dir: Path | None = None,
    quick: bool = False,
    measure_mt5: bool = False,
) -> dict:
    out = out_dir or PHASE_DIR
    out.mkdir(parents=True, exist_ok=True)
    artifacts = build_all_deliverables(base_dir=base_dir, quick=quick, measure_mt5=measure_mt5)
    written: list[str] = []
    for name in REQUIRED_FILES:
        if name not in artifacts:
            raise KeyError(f"Missing deliverable: {name}")
        path = out / name
        path.write_text(json.dumps(artifacts[name], indent=2), encoding="utf-8")
        written.append(str(path))
    return {
        "written": written,
        "count": len(written),
        "verdict": artifacts["phase24c_final_report.json"]["verdict"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 24C latency profiling")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--out", default=str(PHASE_DIR))
    parser.add_argument("--quick", action="store_true", help="Small window for CI")
    parser.add_argument("--mt5", action="store_true", help="Measure MT5/parquet read latency")
    args = parser.parse_args()
    result = write_deliverables(
        base_dir=args.base_dir,
        out_dir=Path(args.out),
        quick=args.quick,
        measure_mt5=args.mt5,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
