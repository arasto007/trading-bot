"""Safety guard — block execution layer access at import and runtime."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)

FORBIDDEN_PREFIXES = (
    "tradingbot.kernel",
    "tradingbot.risk",
    "tradingbot.execution",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.risk_gate",
)

FORBIDDEN_MODULES = frozenset(
    {
        "tradingbot.execution",
        "tradingbot.adapters.mt5_execution",
        "tradingbot.adapters.risk_gate",
        "tradingbot.kernel.trading_kernel",
    }
)


class ExecutionAccessError(RuntimeError):
    """Raised when live gate package attempts execution layer access."""


def scan_package_for_forbidden_imports(package_dir: Path) -> list[str]:
    violations: list[str] = []
    for path in package_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                for prefix in FORBIDDEN_PREFIXES:
                    if module.startswith(prefix):
                        violations.append(f"{path.name}: {module}")
    return violations


def assert_no_forbidden_imports(package_dir: Path) -> None:
    violations = scan_package_for_forbidden_imports(package_dir)
    if violations:
        raise ExecutionAccessError(
            "Live gate must not import execution or kernel modules: " + ", ".join(violations)
        )


_EXECUTION_INVOKED = False


def mark_execution_invoked() -> None:
    global _EXECUTION_INVOKED
    _EXECUTION_INVOKED = True


def assert_execution_not_invoked() -> None:
    if _EXECUTION_INVOKED:
        raise ExecutionAccessError("Execution layer invocation is forbidden in live gate mode")


def reset_execution_guard() -> None:
    global _EXECUTION_INVOKED
    _EXECUTION_INVOKED = False


def guard_no_execution(func: F) -> F:
    """Decorator — runtime assertion that execution is never invoked."""

    def wrapper(*args, **kwargs):
        assert_execution_not_invoked()
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
