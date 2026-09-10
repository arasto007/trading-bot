"""Phase 24J — READ ONLY final production audit before paper trading.

Generates JSON deliverables from static evidence catalog.
Does NOT modify production code.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PHASE_DIR = Path(__file__).resolve().parent

DELIVERABLES = [
    "production_failure_catalog.json",
    "recovery_matrix.json",
    "restart_matrix.json",
    "execution_failure_matrix.json",
    "broker_failure_matrix.json",
    "risk_failure_matrix.json",
    "thread_safety_report.json",
    "state_recovery_report.json",
    "paper_trading_readiness.json",
    "phase24j_final_report.json",
]


def main() -> int:
    missing = [name for name in DELIVERABLES if not (PHASE_DIR / name).is_file()]
    report = {
        "phase": "24J",
        "mode": "READ_ONLY",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "deliverables_present": len(DELIVERABLES) - len(missing),
        "deliverables_missing": missing,
        "verdict": json.loads((PHASE_DIR / "paper_trading_readiness.json").read_text(encoding="utf-8"))[
            "verdict"
        ]
        if (PHASE_DIR / "paper_trading_readiness.json").is_file()
        else "UNKNOWN",
    }
    out = PHASE_DIR / "run_summary.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
