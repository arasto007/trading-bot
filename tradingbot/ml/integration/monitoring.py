"""Phase 15B — live monitoring logs (decisions, latency, fallback, health)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root


def live_monitoring_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "live"


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def log_kernel_decision(record: dict[str, Any], *, base_dir: str | Path | None = None) -> None:
    out = live_monitoring_dir(base_dir)
    _append_jsonl(out / "kernel_decisions.jsonl", {**record, "logged_at_utc": datetime.now(timezone.utc).isoformat()})


def log_decision_latency(latency_ms: dict[str, float], *, base_dir: str | Path | None = None) -> None:
    out = live_monitoring_dir(base_dir)
    _append_jsonl(out / "decision_latency.jsonl", {
        **latency_ms,
        "logged_at_utc": datetime.now(timezone.utc).isoformat(),
    })


def log_fallback_event(reason: str, *, detail: dict[str, Any] | None = None, base_dir: str | Path | None = None) -> None:
    out = live_monitoring_dir(base_dir)
    _append_jsonl(out / "fallback_events.jsonl", {
        "reason": reason,
        "detail": detail or {},
        "logged_at_utc": datetime.now(timezone.utc).isoformat(),
    })


def write_engine_health(health: dict[str, Any], *, base_dir: str | Path | None = None) -> Path:
    out = live_monitoring_dir(base_dir)
    path = out / "engine_health.json"
    _write_json(path, {**health, "updated_at_utc": datetime.now(timezone.utc).isoformat()})
    return path


def write_pipeline_statistics(stats: dict[str, Any], *, base_dir: str | Path | None = None) -> Path:
    out = live_monitoring_dir(base_dir)
    path = out / "pipeline_statistics.json"
    _write_json(path, {**stats, "updated_at_utc": datetime.now(timezone.utc).isoformat()})
    return path


def export_monitoring_snapshots(*, base_dir: str | Path | None = None) -> dict[str, str]:
    """Materialize JSON aggregates from JSONL logs for reporting."""
    out = live_monitoring_dir(base_dir)
    result: dict[str, str] = {}

    for name in ("kernel_decisions", "decision_latency", "fallback_events"):
        src = out / f"{name}.jsonl"
        dst = out / f"{name}.json"
        rows: list[dict[str, Any]] = []
        if src.is_file():
            for line in src.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        _write_json(dst, {"count": len(rows), "records": rows[-100:]})
        result[name] = str(dst)

    for static in ("engine_health.json", "pipeline_statistics.json"):
        p = out / static
        if p.is_file():
            result[static.replace(".json", "")] = str(p)
    return result
