"""Phase 10.4 — long-duration shadow run orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.integration.error_audit.error_report import build_error_audit_report, save_error_audit_report
from tradingbot.ml.integration.error_audit.shadow_health_check import ShadowHealthCheck
from tradingbot.ml.integration.live_shadow_runner import LiveShadowConfig, LiveShadowRunner
from tradingbot.ml.monitoring.session_report import save_monitor_session
from tradingbot.ml.monitoring.shadow_monitor import ShadowMonitor
from tradingbot.ml.monitoring.stability_analyzer import StabilityAnalyzer

logger = logging.getLogger(__name__)
WARMUP_BARS = 80


@dataclass
class LongRunConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    model: str = "phase9_9_best"
    risk_pct: float = 0.005
    shadow_days: int = 7
    shadow_hours: int | None = None
    run_id: str = "stability_run_v1"
    seed: int = 42
    skip_preflight: bool = False
    resume: bool = False
    candles_df: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "model": self.model,
            "risk_pct": self.risk_pct,
            "shadow_days": self.shadow_days,
            "shadow_hours": self.shadow_hours,
            "run_id": self.run_id,
            "seed": self.seed,
            "phase": "10.4",
        }


@dataclass
class LongRunResult:
    run_id: str
    decision: str
    duration_hours: float
    shadow_result_status: str
    paths: dict[str, str] = field(default_factory=dict)
    final_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": "10.4",
            "run_id": self.run_id,
            "decision": self.decision,
            "duration_hours": round(self.duration_hours, 4),
            "shadow_result_status": self.shadow_result_status,
            "paths": self.paths,
            "final_report": self.final_report,
            "order_send": False,
        }


class LongRunManager:
    """Run extended shadow validation with monitoring and stability reporting."""

    def __init__(self, *, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir

    def run(self, config: LongRunConfig | None = None) -> LongRunResult:
        cfg = config or LongRunConfig()
        started = datetime.now(timezone.utc)

        monitor = ShadowMonitor(
            run_id=cfg.run_id,
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            risk_percent=cfg.risk_pct,
            base_dir=self.base_dir,
        )

        resume_bar = None
        if cfg.resume:
            checkpoint = ShadowMonitor.load_checkpoint(cfg.run_id, self.base_dir)
            if checkpoint:
                resume_bar = int(checkpoint.get("last_bar_index", WARMUP_BARS))
                logger.info("Resuming from bar index %s", resume_bar)

        mode = "poll" if cfg.shadow_hours else "historical"
        shadow_cfg = LiveShadowConfig(
            symbol=cfg.symbol,
            timeframe=cfg.timeframe,
            model=cfg.model,
            risk_pct=cfg.risk_pct,
            shadow_days=cfg.shadow_days,
            shadow_hours=cfg.shadow_hours,
            mode=mode,
            seed=cfg.seed,
            skip_preflight=cfg.skip_preflight,
            candles_df=cfg.candles_df,
            monitor=monitor,
            resume_from_bar=resume_bar,
        )

        shadow_result = LiveShadowRunner(base_dir=self.base_dir).run(shadow_cfg, run_id=cfg.run_id)
        duration_h = (datetime.now(timezone.utc) - started).total_seconds() / 3600.0

        metrics = shadow_result.metrics
        virtual_trades = _load_virtual_trades(cfg.run_id, self.base_dir)
        contexts = _load_kernel_context(cfg.run_id, self.base_dir)

        health = ShadowHealthCheck().evaluate_artifacts(
            run_id=cfg.run_id,
            contexts=contexts,
            metrics=metrics,
            invalid_trades=len(monitor.invalid_trades),
            recovery=_load_recovery(cfg.run_id, self.base_dir),
        )

        audit_report = build_error_audit_report(
            run_id=cfg.run_id,
            contexts=contexts,
            health=health.to_dict(),
            source_paths={"shadow_result": shadow_result.report_path},
        )
        save_error_audit_report(audit_report, self.base_dir)

        analyzer = StabilityAnalyzer(risk_percent=cfg.risk_pct, base_dir=str(self.base_dir) if self.base_dir else None)
        anomaly_report, verdict = analyzer.analyze(
            metrics=metrics,
            ml_buy=monitor.ml_buy,
            ml_sell=monitor.ml_sell,
            ml_hold=monitor.ml_hold,
            probabilities=monitor.probabilities,
            feature_samples=monitor.feature_samples,
            virtual_trades=virtual_trades,
            invalid_trade_count=len(monitor.invalid_trades),
            pipeline_errors=monitor.pipeline_errors,
            completion_rate=float(health.metrics.get("completion_rate", 1.0)),
        )

        perf = monitor.performance.performance_summary(metrics)
        final_report = {
            "runtime": {
                "duration_hours": round(duration_h, 4),
                "candles_processed": monitor.candles_processed,
                "kernel_cycles": metrics.get("kernel_cycles", monitor.kernel_cycles),
            },
            "ml": monitor.signals_summary(),
            "risk": monitor.risk_summary(),
            "trading": perf,
            "integrity": {
                "invalid_trades": len(monitor.invalid_trades),
                "rr_violations": len([c for c in anomaly_report.critical if c.get("code") == "rr_violation"]),
                "execution_violations": len(
                    [c for c in anomaly_report.critical if c.get("code", "").startswith(("ast_", "execution_"))]
                ),
            },
            "anomalies": anomaly_report.to_dict(),
            "decision": verdict.to_dict(),
            "preflight_pass": shadow_result.preflight_pass,
            "health": health.to_dict(),
        }

        paths = save_monitor_session(
            cfg.run_id,
            config=cfg.to_dict(),
            hourly_metrics=monitor.performance.hourly_metrics(),
            signals_summary=monitor.signals_summary(),
            risk_summary=monitor.risk_summary(),
            trade_quality=monitor.trade_quality,
            anomalies=anomaly_report.to_dict(),
            equity_curve=monitor.performance.state.equity_curve or _load_equity(cfg.run_id, self.base_dir),
            final_report=final_report,
            base_dir=self.base_dir,
        )

        monitor.save_checkpoint()

        return LongRunResult(
            run_id=cfg.run_id,
            decision=verdict.decision,
            duration_hours=duration_h,
            shadow_result_status=shadow_result.status,
            paths={k: str(v) for k, v in paths.items()},
            final_report=final_report,
        )


def _load_virtual_trades(run_id: str, base_dir: str | Path | None) -> list[dict[str, Any]]:
    import json

    from tradingbot.ml.data.paths import ml_live_shadow_virtual_trades_path

    path = ml_live_shadow_virtual_trades_path(run_id, base_dir)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _load_equity(run_id: str, base_dir: str | Path | None) -> list[dict[str, Any]]:
    import json

    from tradingbot.ml.data.paths import ml_live_shadow_equity_path

    path = ml_live_shadow_equity_path(run_id, base_dir)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _load_kernel_context(run_id: str, base_dir: str | Path | None) -> list[dict[str, Any]]:
    import json

    from tradingbot.ml.data.paths import ml_live_shadow_context_path

    path = ml_live_shadow_context_path(run_id, base_dir)
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _load_recovery(run_id: str, base_dir: str | Path | None) -> dict[str, Any] | None:
    import json

    from tradingbot.ml.data.paths import ml_live_shadow_report_path

    path = ml_live_shadow_report_path(run_id, base_dir)
    if not path.is_file():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    return report.get("recovery")
