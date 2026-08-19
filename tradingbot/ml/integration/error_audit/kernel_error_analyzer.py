"""Phase 10.5 — kernel shadow error classification utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

RISK_BLOCK_PREFIX = "Risk blocked:"
STAGE_EXCEPTION_RE = re.compile(r"^(DataStage|IndicatorStage|SignalStage|RiskStage|ExecutionStage):")


@dataclass
class ClassifiedError:
    timestamp: str
    component: str
    exception: str
    root_cause: str
    severity: str
    fix_required: bool
    category: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "component": self.component,
            "exception": self.exception,
            "root_cause": self.root_cause,
            "severity": self.severity,
            "fix_required": self.fix_required,
            "category": self.category,
        }


@dataclass
class ErrorAuditSummary:
    total_logged: int = 0
    risk_blocks: int = 0
    pipeline_failures: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    records: list[ClassifiedError] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_logged": self.total_logged,
            "risk_blocks": self.risk_blocks,
            "pipeline_failures": self.pipeline_failures,
            "by_category": dict(self.by_category),
            "records": [r.to_dict() for r in self.records],
        }


def is_risk_block_message(message: str) -> bool:
    return str(message).startswith(RISK_BLOCK_PREFIX)


def split_kernel_errors(errors: list[str]) -> tuple[list[str], list[str]]:
    """Return (pipeline_failures, risk_blocks)."""
    pipeline: list[str] = []
    risk: list[str] = []
    for msg in errors:
        if is_risk_block_message(msg):
            risk.append(msg)
        else:
            pipeline.append(msg)
    return pipeline, risk


def classify_error_message(message: str, *, timestamp: str = "") -> ClassifiedError:
    msg = str(message)
    if is_risk_block_message(msg):
        reason = msg[len(RISK_BLOCK_PREFIX) :].strip()
        category = "risk_input"
        if "spread" in reason.lower():
            category = "risk_input"
        elif "atr" in reason.lower() or "volatility" in reason.lower():
            category = "risk_input"
        elif "friday" in reason.lower() or "session" in reason.lower():
            category = "risk_input"
        return ClassifiedError(
            timestamp=timestamp,
            component="RiskStage",
            exception=msg,
            root_cause="Expected RiskGate rejection — not a pipeline failure",
            severity="info",
            fix_required=False,
            category=category,
        )

    if "Insufficient data" in msg or "missing" in msg.lower():
        category = "data" if "data" in msg.lower() or "ohlcv" in msg.lower() else "kernel_integration"
        return ClassifiedError(
            timestamp=timestamp,
            component=_extract_component(msg),
            exception=msg,
            root_cause="Market data or enriched frame unavailable for cycle",
            severity="warning",
            fix_required=True,
            category="data" if "ohlcv" in msg.lower() or "data" in msg.lower() else category,
        )

    if "NaN" in msg or "feature" in msg.lower():
        return ClassifiedError(
            timestamp=timestamp,
            component=_extract_component(msg),
            exception=msg,
            root_cause="Feature computation or alignment issue",
            severity="error",
            fix_required=True,
            category="feature",
        )

    if STAGE_EXCEPTION_RE.match(msg):
        return ClassifiedError(
            timestamp=timestamp,
            component=_extract_component(msg),
            exception=msg,
            root_cause="Pipeline stage failure",
            severity="error",
            fix_required=True,
            category="kernel_integration",
        )

    return ClassifiedError(
        timestamp=timestamp,
        component=_extract_component(msg),
        exception=msg,
        root_cause="Unclassified shadow pipeline message",
        severity="warning",
        fix_required=True,
        category="kernel_integration",
    )


def _extract_component(message: str) -> str:
    match = STAGE_EXCEPTION_RE.match(message)
    if match:
        return match.group(1)
    if message.startswith(RISK_BLOCK_PREFIX):
        return "RiskStage"
    return "TradingKernel"


class KernelErrorAnalyzer:
    """Analyze kernel_context / events artifacts from shadow runs."""

    def analyze_contexts(self, contexts: list[dict[str, Any]]) -> ErrorAuditSummary:
        summary = ErrorAuditSummary()
        for row in contexts:
            ts = str(row.get("timestamp", ""))
            errors = list(row.get("errors") or [])
            if not errors:
                continue
            for msg in errors:
                summary.total_logged += 1
                record = classify_error_message(msg, timestamp=ts)
                summary.records.append(record)
                summary.by_category[record.category] = summary.by_category.get(record.category, 0) + 1
                if is_risk_block_message(msg):
                    summary.risk_blocks += 1
                else:
                    summary.pipeline_failures += 1
        return summary

    def analyze_events(self, events: list[dict[str, Any]]) -> ErrorAuditSummary:
        contexts = [
            {"timestamp": e.get("timestamp"), "errors": e.get("errors", [])}
            for e in events
            if e.get("errors")
        ]
        return self.analyze_contexts(contexts)
