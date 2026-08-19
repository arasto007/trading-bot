"""Phase 18C — environment validation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from tradingbot.ml.phase17d.config import TREND_VERSION_ENV
from tradingbot.ml.phase18c.config import REQUIRED_DIRS, REQUIRED_PACKAGES


def _status(ok: bool, *, warn: bool = False) -> str:
    if ok:
        return "PASS"
    return "WARN" if warn else "FAIL"


def validate_environment(*, project_root: Path) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}

    items["python"] = {
        "status": _status(sys.version_info >= (3, 10)),
        "version": sys.version.split()[0],
        "executable": sys.executable,
    }

    items["virtual_environment"] = {
        "status": "PASS" if (sys.prefix != getattr(sys, "base_prefix", sys.prefix) or "VIRTUAL_ENV" in os.environ) else "WARN",
        "prefix": sys.prefix,
        "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV"),
    }

    packages: dict[str, Any] = {}
    missing: list[str] = []
    for name in REQUIRED_PACKAGES:
        try:
            mod = __import__(name if name != "sklearn" else "sklearn")
            packages[name] = getattr(mod, "__version__", "present")
        except ImportError:
            missing.append(name)
            packages[name] = None
    items["dependencies"] = {
        "status": _status(len(missing) == 0),
        "packages": packages,
        "missing": missing,
    }

    # Optional MT5 package — WARN if missing (may still connect later)
    try:
        import MetaTrader5 as mt5  # noqa: F401
        mt5_pkg = getattr(mt5, "__version__", "present")
        mt5_status = "PASS"
    except ImportError:
        mt5_pkg = None
        mt5_status = "WARN"
    items["mt5_python_package"] = {"status": mt5_status, "version": mt5_pkg}

    config_candidates = [
        project_root / ".env",
        project_root / ".env.example",
        project_root / "config",
    ]
    present_cfg = [str(p.relative_to(project_root)) for p in config_candidates if p.exists()]
    items["configuration_files"] = {
        "status": _status(len(present_cfg) > 0, warn=True),
        "present": present_cfg,
    }

    items["environment_variables"] = {
        "status": "PASS",
        "TREND_MODEL_VERSION": os.environ.get(TREND_VERSION_ENV, "default:v41"),
        "rollback_env": TREND_VERSION_ENV,
    }

    dir_status: dict[str, bool] = {}
    for rel in REQUIRED_DIRS:
        p = project_root / rel
        dir_status[rel] = p.is_dir()
        if not p.is_dir() and rel in ("logs",):
            try:
                p.mkdir(parents=True, exist_ok=True)
                dir_status[rel] = p.is_dir()
            except OSError:
                pass
    items["directory_structure"] = {
        "status": _status(all(dir_status.values())),
        "dirs": dir_status,
    }

    # Permissions: write probe in reports and logs
    writable = True
    for rel in ("logs", "data/ml"):
        probe = project_root / rel / ".phase18c_write_probe"
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except OSError:
            writable = False
    items["permissions"] = {"status": _status(writable), "writable": writable}

    statuses = [v["status"] for v in items.values()]
    passed = all(s in ("PASS", "WARN") for s in statuses) and "FAIL" not in statuses
    # Hard fail only on python/deps/dirs/permissions
    hard = all(
        items[k]["status"] == "PASS"
        for k in ("python", "dependencies", "directory_structure", "permissions")
    )
    return {
        "phase": "18C",
        "passed": hard and passed,
        "items": items,
        "summary": {
            "pass": sum(1 for s in statuses if s == "PASS"),
            "warn": sum(1 for s in statuses if s == "WARN"),
            "fail": sum(1 for s in statuses if s == "FAIL"),
        },
    }
