"""Phase 28E — run drawdown/equity audit against Phase 28D deliverables."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase28e.auditors import (
    audit_balance,
    audit_consistency,
    audit_drawdown,
    audit_equity,
    audit_margin,
    audit_pnl_scaling,
    audit_position_size,
    audit_risk,
    build_final_report,
    recalculate_performance,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE28D_DIR = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase28d"
PHASE_DIR = Path(__file__).resolve().parent


def _load_json(name: str, *, base: Path = PHASE28D_DIR) -> Any:
    return json.loads((base / name).read_text(encoding="utf-8"))


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def run_phase28e(*, phase28d_dir: Path | None = None) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    src = Path(phase28d_dir or PHASE28D_DIR)
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    trade_log = _load_json("trade_log.json", base=src)
    trades = trade_log.get("trades") or []
    reported_perf = _load_json("performance_metrics.json", base=src)
    equity_curve = _load_json("equity_curve.json", base=src).get("curve") or []
    balance_curve = _load_json("balance_curve.json", base=src).get("curve") or []
    meta = _load_json("phase28d_final_report.json", base=src).get("meta") or {}
    records = _load_json("_cache/replay_records.json", base=src)

    audits = {
        "drawdown": audit_drawdown(trades, reported=reported_perf),
        "equity": audit_equity(trades, reported_curve=equity_curve),
        "balance": audit_balance(trades, reported_curve=balance_curve),
        "risk": audit_risk(trades),
        "margin": audit_margin(trades),
        "position_size": audit_position_size(trades),
        "pnl_scaling": audit_pnl_scaling(trades, meta=meta),
        "consistency": audit_consistency(trades, records, reported_perf=reported_perf),
        "performance": recalculate_performance(trades, reported=reported_perf),
    }

    for key, payload in audits.items():
        payload["generated_utc"] = ts

    final = build_final_report(audits)
    final["generated_utc"] = ts

    deliverables = {
        "drawdown_audit.json": audits["drawdown"],
        "equity_audit.json": audits["equity"],
        "balance_audit.json": audits["balance"],
        "risk_audit.json": audits["risk"],
        "margin_audit.json": audits["margin"],
        "position_size_audit.json": audits["position_size"],
        "pnl_scaling_audit.json": audits["pnl_scaling"],
        "consistency_audit.json": audits["consistency"],
        "performance_recalculation.json": audits["performance"],
        "phase28e_final_report.json": final,
    }
    for name, payload in deliverables.items():
        _write(name, payload)

    return final


def main() -> int:
    report = run_phase28e()
    print(json.dumps(report["answers"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
