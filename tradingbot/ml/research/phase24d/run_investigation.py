"""Phase 24D — generate optimization design JSON deliverables (research only)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingbot.ml.research.phase24d.unified_frame_investigation import build_all_deliverables

PHASE_DIR = Path(__file__).resolve().parent

REQUIRED = (
    "unified_frame_trace.json",
    "merge_breakdown.json",
    "duplicate_work_report.json",
    "featurebuilder_analysis.json",
    "cache_key_analysis.json",
    "dataset_usage.json",
    "optimization_simulation.json",
    "risk_analysis.json",
    "recommended_strategy.json",
    "phase24d_final_report.json",
)


def write_deliverables(*, base_dir: str | None = None, out_dir: Path | None = None, quick: bool = False) -> dict:
    out = out_dir or PHASE_DIR
    out.mkdir(parents=True, exist_ok=True)
    artifacts = build_all_deliverables(base_dir=base_dir, quick=quick)
    written: list[str] = []
    for name in REQUIRED:
        path = out / name
        path.write_text(json.dumps(artifacts[name], indent=2), encoding="utf-8")
        written.append(str(path))
    return {
        "written": written,
        "count": len(written),
        "verdict": artifacts["phase24d_final_report.json"]["verdict"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 24D unified frame optimization design")
    parser.add_argument("--base-dir", default=None)
    parser.add_argument("--out", default=str(PHASE_DIR))
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    result = write_deliverables(base_dir=args.base_dir, out_dir=Path(args.out), quick=args.quick)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
