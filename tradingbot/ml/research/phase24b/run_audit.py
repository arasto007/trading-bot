"""Phase 24B — generate architecture JSON deliverables (no production changes)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradingbot.ml.research.phase24b.architecture_audit import build_all_artifacts

PHASE_DIR = Path(__file__).resolve().parent

REQUIRED_FILES = (
    "architecture_overview.json",
    "module_inventory.json",
    "call_graph.json",
    "execution_graph.json",
    "feature_graph.json",
    "probability_graph.json",
    "confidence_graph.json",
    "decision_graph.json",
    "hold_graph.json",
    "filter_graph.json",
    "risk_graph.json",
    "runtime_vs_research.json",
    "ownership_matrix.json",
    "dependency_matrix.json",
    "configuration_inventory.json",
    "threshold_inventory.json",
    "live_pipeline_trace.json",
    "research_pipeline_trace.json",
    "architecture_findings.json",
    "phase24b_final_report.json",
)


def write_artifacts(*, base_dir: str | None = None, out_dir: Path | None = None) -> dict:
    out = out_dir or PHASE_DIR
    out.mkdir(parents=True, exist_ok=True)
    artifacts = build_all_artifacts(base_dir=base_dir)
    written: list[str] = []
    for name in REQUIRED_FILES:
        if name not in artifacts:
            raise KeyError(f"Missing artifact builder output: {name}")
        path = out / name
        path.write_text(json.dumps(artifacts[name], indent=2), encoding="utf-8")
        written.append(str(path))
    return {
        "written": written,
        "count": len(written),
        "verdict": artifacts["phase24b_final_report.json"]["verdict"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 24B architecture audit")
    parser.add_argument("--base-dir", default=None, help="ML base dir for artifact probes")
    parser.add_argument("--out", default=str(PHASE_DIR), help="Output directory")
    args = parser.parse_args()
    result = write_artifacts(base_dir=args.base_dir, out_dir=Path(args.out))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
