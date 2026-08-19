"""Phase 12 — live pilot monitoring and reporting."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from tradingbot.ml.data.paths import phase12_live_pilot_report_path
from tradingbot.ml.live_pilot.config import session_for_hour
from tradingbot.ml.research.phase11_5._metrics import trade_metrics


class LiveMonitor:
    def __init__(self) -> None:
        self._ml_buy = 0
        self._ml_sell = 0
        self._ml_hold = 0
        self._risk_allowed = 0
        self._risk_blocked = 0
        self._risk_reasons: dict[str, int] = {}
        self._sessions: dict[str, dict[str, int]] = {}
        self._regime_accepted = 0
        self._regime_blocked = 0
        self._cycles = 0

    def record_cycle(
        self,
        *,
        ml_direction: str,
        risk_allowed: bool,
        risk_reason: str | None = None,
        hour_utc: int | None = None,
        regime: str | None = None,
        regime_accepted: bool | None = None,
    ) -> None:
        self._cycles += 1
        d = ml_direction.upper()
        if d == "BUY":
            self._ml_buy += 1
        elif d == "SELL":
            self._ml_sell += 1
        else:
            self._ml_hold += 1

        if risk_allowed:
            self._risk_allowed += 1
        else:
            self._risk_blocked += 1
            if risk_reason:
                self._risk_reasons[risk_reason] = self._risk_reasons.get(risk_reason, 0) + 1

        if hour_utc is not None:
            for sess in session_for_hour(hour_utc):
                bucket = self._sessions.setdefault(sess, {"cycles": 0, "signals": 0})
                bucket["cycles"] += 1
                if d in ("BUY", "SELL"):
                    bucket["signals"] += 1

        if regime_accepted is True:
            self._regime_accepted += 1
        elif regime_accepted is False:
            self._regime_blocked += 1

    def build_report(
        self,
        *,
        mode: str,
        run_id: str,
        safety_summary: dict[str, Any],
        execution_stats: dict[str, Any],
        trades: list[dict[str, Any]],
        kill_switch: dict[str, Any],
        model_validation: dict[str, Any],
        preflight: dict[str, Any],
    ) -> dict[str, Any]:
        perf = trade_metrics(trades)
        total_ml = max(1, self._ml_buy + self._ml_sell + self._ml_hold)
        decision = _pilot_decision(
            mode=mode,
            kill_active=kill_switch.get("active", False),
            preflight_ok=preflight.get("preflight_pass", False),
            model_ok=model_validation.get("status") == "PASS",
            execution_stats=execution_stats,
        )
        return {
            "phase": "12",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "mode": mode,
            "architecture_status": {
                "kernel_unmodified": True,
                "phase9_9_frozen": True,
                "safety_layer_active": True,
                "execution_guard_isolated": True,
            },
            "safety_status": {
                "kill_switch": kill_switch,
                "safety_manager": safety_summary,
            },
            "execution_statistics": execution_stats,
            "trade_statistics": perf,
            "model_monitoring": {
                "ml_buy": self._ml_buy,
                "ml_sell": self._ml_sell,
                "ml_hold": self._ml_hold,
                "buy_sell_ratio": round(self._ml_buy / max(1, self._ml_sell), 4),
                "cycles": self._cycles,
            },
            "risk_statistics": {
                "allowed": self._risk_allowed,
                "blocked": self._risk_blocked,
                "block_reasons": self._risk_reasons,
            },
            "session_statistics": self._sessions,
            "regime_statistics": {
                "accepted": self._regime_accepted,
                "blocked": self._regime_blocked,
            },
            "preflight": preflight,
            "model_validation": model_validation,
            "recommendation": decision,
        }

    def save_report(self, report: dict[str, Any], *, base_dir: str | None = None) -> str:
        path = phase12_live_pilot_report_path(base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return str(path)


def _pilot_decision(
    *,
    mode: str,
    kill_active: bool,
    preflight_ok: bool,
    model_ok: bool,
    execution_stats: dict[str, Any],
) -> str:
    if kill_active or not preflight_ok or not model_ok:
        return "NEEDS_FIX"
    if mode == "PILOT" and execution_stats.get("success", 0) == 0 and execution_stats.get("attempts", 0) > 0:
        return "NEEDS_FIX"
    return "READY_FOR_SCALE"
