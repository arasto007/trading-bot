"""Phase 15E — signal funnel aggregation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from tradingbot.ml.phase15e_debug.stage_probe import StageProbeResult


def _pct(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


@dataclass
class SignalFunnel:
    probes: list[StageProbeResult] = field(default_factory=list)

    def add(self, probe: StageProbeResult) -> None:
        self.probes.append(probe)

    def build_report(self) -> dict[str, Any]:
        n = len(self.probes)
        unified_ok = sum(1 for p in self.probes if p.unified_ok)
        d141 = sum(1 for p in self.probes if p.decision_14_1_action in ("BUY", "SELL"))
        cal = sum(1 for p in self.probes if p.calibrated_action in ("BUY", "SELL"))
        risk = sum(1 for p in self.probes if p.risk_allowed)
        qual = sum(1 for p in self.probes if p.quality_allowed)
        kernel = sum(1 for p in self.probes if p.kernel_final_action in ("BUY", "SELL"))
        trading = sum(1 for p in self.probes if p.trading_signal in ("BUY", "SELL"))
        legacy = sum(1 for p in self.probes if p.legacy_signal in ("BUY", "SELL"))
        engine_raw = sum(1 for p in self.probes if p.engine_raw_signal in ("BUY", "SELL"))
        policy_blocks = sum(1 for p in self.probes if p.policy_rejection)

        drop_reasons = Counter(p.drop_reason for p in self.probes if p.drop_reason)
        drop_stages = Counter(p.drop_stage for p in self.probes if p.drop_stage)

        stages = [
            ("candles", n),
            ("unified_features", unified_ok),
            ("decision_14_1", d141),
            ("calibration_14_2a", cal),
            ("risk_14_2b", risk),
            ("quality_14_3", qual),
            ("kernel_adapter", kernel),
            ("trading_signal", trading),
        ]

        funnel: list[dict[str, Any]] = []
        prev = n
        for name, count in stages:
            dropped = prev - count if name != "candles" else 0
            funnel.append({
                "stage": name,
                "count_in": prev if name != "candles" else n,
                "count_out": count,
                "dropped": dropped,
                "drop_pct": _pct(dropped, prev if name != "candles" else n),
                "pass_pct": _pct(count, n),
            })
            if name != "candles":
                prev = count

        return {
            "bars_evaluated": n,
            "legacy_signals": legacy,
            "engine_raw_buy_sell": engine_raw,
            "policy_confidence_blocks": policy_blocks,
            "ml_trading_signals": trading,
            "funnel": funnel,
            "drop_stages": dict(drop_stages),
            "drop_reasons_top": drop_reasons.most_common(15),
            "stage_summary": {
                "unified_ok": unified_ok,
                "decision_14_1_buy_sell": d141,
                "calibrated_buy_sell": cal,
                "risk_allowed": risk,
                "quality_allowed": qual,
                "kernel_final_buy_sell": kernel,
                "trading_signal_buy_sell": trading,
                "engine_raw_buy_sell": engine_raw,
                "policy_confidence_blocks": policy_blocks,
            },
        }
