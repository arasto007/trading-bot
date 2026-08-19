"""Phase 10.5 — kernel shadow error audit."""

from tradingbot.ml.integration.error_audit.error_report import build_error_audit_report, save_error_audit_report
from tradingbot.ml.integration.error_audit.kernel_error_analyzer import (
    KernelErrorAnalyzer,
    classify_error_message,
    is_risk_block_message,
    split_kernel_errors,
)
from tradingbot.ml.integration.error_audit.recovery_manager import ShadowRecoveryManager
from tradingbot.ml.integration.error_audit.shadow_health_check import ShadowHealthCheck

__all__ = [
    "KernelErrorAnalyzer",
    "ShadowHealthCheck",
    "ShadowRecoveryManager",
    "build_error_audit_report",
    "classify_error_message",
    "is_risk_block_message",
    "save_error_audit_report",
    "split_kernel_errors",
]
