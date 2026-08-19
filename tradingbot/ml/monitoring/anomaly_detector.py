"""Phase 10.4 — anomaly detection for shadow monitoring."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.ml.data.paths import phase9_9_config_path
from tradingbot.ml.integration.live_preflight import scan_live_shadow_ast

PHASE99_BASELINE_PROB = 0.5
PHASE99_FEATURES = ("ema50_slope", "candle_direction", "structure_distance")


@dataclass
class AnomalyReport:
    warnings: list[dict[str, Any]] = field(default_factory=list)
    critical: list[dict[str, Any]] = field(default_factory=list)

    def add(self, *, severity: str, code: str, message: str, **extra: Any) -> None:
        item = {"severity": severity, "code": code, "message": message, **extra}
        if severity == "critical":
            self.critical.append(item)
        else:
            self.warnings.append(item)

    def to_dict(self) -> dict[str, Any]:
        return {"warnings": self.warnings, "critical": self.critical, "total": len(self.warnings) + len(self.critical)}


class AnomalyDetector:
    """Detect signal collapse, drift, integrity issues, and execution safety."""

    def __init__(
        self,
        *,
        risk_percent: float = 0.005,
        target_rr: float = 2.0,
        rr_tolerance: float = 0.05,
        base_dir: str | Path | None = None,
    ) -> None:
        self.risk_percent = risk_percent
        self.target_rr = target_rr
        self.rr_tolerance = rr_tolerance
        self.base_dir = base_dir

    def check_signal_collapse(self, ml_buy: int, ml_sell: int, ml_hold: int, report: AnomalyReport) -> None:
        total = ml_buy + ml_sell + ml_hold
        if total == 0:
            return
        hold_pct = ml_hold / total
        if hold_pct > 0.99:
            report.add(severity="warning", code="signal_collapse", message="HOLD > 99%", hold_pct=round(hold_pct, 4))
        trade_signals = ml_buy + ml_sell
        if trade_signals > 0:
            ratio = ml_buy / trade_signals
            if ratio < 0.05 or ratio > 0.95:
                report.add(
                    severity="warning",
                    code="signal_imbalance",
                    message="BUY/SELL ratio abnormal",
                    buy_ratio=round(ratio, 4),
                )

    def check_probability_drift(self, probabilities: list[float], report: AnomalyReport) -> None:
        if len(probabilities) < 20:
            return
        arr = np.array([p for p in probabilities if p is not None], dtype=np.float64)
        if arr.size < 20:
            return
        mean = float(arr.mean())
        std = float(arr.std())
        baseline = self._load_baseline_prob()
        if abs(mean - baseline) > 0.15:
            report.add(
                severity="warning",
                code="probability_drift",
                message="ML probability mean drifted from Phase 9.9 baseline",
                mean=round(mean, 4),
                baseline=baseline,
            )
        if std < 0.01:
            report.add(
                severity="warning",
                code="probability_collapse",
                message="Probability distribution collapsed (near-constant)",
                std=round(std, 6),
            )

    def check_feature_drift(
        self,
        feature_samples: dict[str, list[float]],
        report: AnomalyReport,
    ) -> None:
        baseline = self._feature_baselines()
        for name in PHASE99_FEATURES:
            samples = feature_samples.get(name, [])
            if len(samples) < 20:
                continue
            mean = float(np.mean(samples))
            base = baseline.get(name, 0.0)
            if abs(mean - base) > max(1.0, abs(base) * 3 + 0.5):
                report.add(
                    severity="warning",
                    code="feature_drift",
                    message=f"Feature {name} drifted from baseline",
                    feature=name,
                    mean=round(mean, 4),
                    baseline=round(base, 4),
                )

    def check_trade_integrity(
        self,
        trades: list[dict[str, Any]],
        invalid_count: int,
        report: AnomalyReport,
    ) -> None:
        if invalid_count > 0:
            report.add(
                severity="critical",
                code="invalid_virtual_trades",
                message="Invalid virtual trades blocked at entry",
                count=invalid_count,
            )
        for trade in trades:
            entry = float(trade.get("entry", 0))
            sl = float(trade.get("sl", 0))
            tp = float(trade.get("tp", 0))
            if abs(entry - sl) < 1e-4:
                report.add(
                    severity="critical",
                    code="entry_equals_sl",
                    message="Virtual trade has entry == SL",
                    timestamp=trade.get("timestamp"),
                )
            rd = abs(entry - sl)
            rw = abs(tp - entry)
            if rd > 0:
                rr = rw / rd
                if abs(rr - self.target_rr) > self.rr_tolerance:
                    report.add(
                        severity="critical",
                        code="rr_violation",
                        message="R:R violation in closed virtual trade",
                        rr=round(rr, 4),
                        timestamp=trade.get("timestamp"),
                    )

    def check_execution_safety(
        self,
        *,
        execution_blocked: int,
        risk_allowed: int,
        report: AnomalyReport,
    ) -> None:
        violations = scan_live_shadow_ast()
        if violations:
            for v in violations:
                report.add(severity="critical", code="ast_violation", message=v)
        if risk_allowed > 0 and execution_blocked < risk_allowed:
            report.add(
                severity="critical",
                code="execution_leak",
                message="Not all risk-approved cycles had execution blocked",
                risk_allowed=risk_allowed,
                execution_blocked=execution_blocked,
            )

    def _load_baseline_prob(self) -> float:
        try:
            path = phase9_9_config_path(self.base_dir)
            if path.is_file():
                cfg = json.loads(path.read_text(encoding="utf-8"))
                buy_t = float(cfg.get("buy_threshold", 0.55))
                sell_t = float(cfg.get("sell_threshold", 0.45))
                return round((buy_t + sell_t) / 2.0, 4)
        except Exception:
            pass
        return PHASE99_BASELINE_PROB

    @staticmethod
    def _feature_baselines() -> dict[str, float]:
        return {name: 0.0 for name in PHASE99_FEATURES}
