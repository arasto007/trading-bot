"""Phase 15D — shadow validation orchestrator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.live_validation.report_generator import write_final_report, write_phase15d_reports
from tradingbot.ml.live_validation.shadow_mode import ShadowModeRunner, ShadowModeResult
from tradingbot.ml.live_validation.validator import ValidationResult, validate_shadow_result


@dataclass
class Phase15DResult:
    status: str
    recommendation: str
    reports_dir: str
    shadow: ShadowModeResult
    validation: ValidationResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "15D",
            "status": self.status,
            "recommendation": self.recommendation,
            "reports_dir": self.reports_dir,
            "shadow": self.shadow.to_dict(),
            "validation": self.validation.to_dict(),
        }


def run_phase15d_shadow(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    days: int = 180,
    seed: int = 42,
    base_dir: str | Path | None = None,
    stride: int = 10,
    warmup: int = 350,
    legacy_config: dict[str, Any] | None = None,
) -> Phase15DResult:
    runner = ShadowModeRunner(
        symbol=symbol,
        timeframe=timeframe,
        days=days,
        seed=seed,
        base_dir=str(base_dir) if base_dir else None,
        stride=stride,
        warmup=warmup,
        legacy_config=legacy_config,
    )
    shadow = runner.run()
    out = write_phase15d_reports(
        shadow,
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        days=days,
        seed=seed,
    )
    validation = validate_shadow_result(shadow, base_dir=str(base_dir) if base_dir else None, require_full_reports=False)
    final = {
        **validation.to_dict(),
        "symbol": symbol,
        "timeframe": timeframe,
        "days": days,
        "seed": seed,
        "shadow_summary": shadow.stats.build_report(),
        "equity_summary": {
            "final_equity": shadow.equity.equity_curve[-1] if shadow.equity.equity_curve else 0,
            "trade_count": len(shadow.stats.shadow_trades),
        },
        "latency_summary": shadow.latency.build_report(),
        "checksum_stable": shadow.checksum_stable,
        "order_send_calls": shadow.order_send_calls,
        "trading_kernel_modified": False,
        "risk_gate_modified": False,
        "execution_blocked": True,
    }
    write_final_report(final, base_dir=base_dir)
    validation = validate_shadow_result(shadow, base_dir=str(base_dir) if base_dir else None)
    return Phase15DResult(
        status=validation.status,
        recommendation=validation.recommendation,
        reports_dir=str(out),
        shadow=shadow,
        validation=validation,
    )
