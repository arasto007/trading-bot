"""Shadow router — route signals to shadow logs only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import ml_root
from tradingbot.ml.live_gate.safety_guard import assert_execution_not_invoked, guard_no_execution
from tradingbot.ml.live_gate.schema import LivePermission


def live_gate_dir(base_dir: str | Path | None = None) -> Path:
    return ml_root(base_dir) / "live_gate"


def shadow_route_log_path(base_dir: str | Path | None = None) -> Path:
    return live_gate_dir(base_dir) / "shadow_routes.jsonl"


class ShadowRouter:
    """
    Ensure all signals remain in shadow mode.

    Never calls execution layer — append-only shadow routing log.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir
        live_gate_dir(base_dir).mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return shadow_route_log_path(self.base_dir)

    @guard_no_execution
    def route(
        self,
        decision: dict[str, Any],
        permission: LivePermission,
    ) -> dict[str, Any]:
        assert_execution_not_invoked()

        payload = {
            "mode": "shadow_only",
            "execution": "disabled",
            "permission_state": permission.state,
            "allowed_mode": permission.allowed_mode,
            "decision": dict(decision),
        }

        if not permission.shadow_routing_allowed:
            payload["routed"] = False
            payload["reason"] = "Shadow routing blocked by live gate"
            return payload

        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

        payload["routed"] = True
        payload["log_path"] = str(self.path)
        return payload

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
        return rows
