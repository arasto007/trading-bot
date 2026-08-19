"""Phase 10 — ML shadow integration configuration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ShadowMode = Literal["replay", "live_shadow"]


@dataclass
class ShadowConfig:
    symbol: str = "XAUUSD"
    timeframe: str = "M5"
    model_alias: str = "phase9_9_best"
    mode: ShadowMode = "replay"
    risk_pct: float = 0.005
    shadow_days: int = 30
    max_replay_bars: int = 250
    buy_threshold: float = 0.55
    sell_threshold: float = 0.45
    tp_r: float = 2.0
    sl_r: float = 1.0
    initial_equity: float = 10_000.0
    seed: int = 42
    use_mt5: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_bundle_config(cls, bundle_cfg: dict[str, Any], **overrides: Any) -> "ShadowConfig":
        base = cls(
            buy_threshold=float(bundle_cfg.get("buy_threshold", 0.55)),
            sell_threshold=float(bundle_cfg.get("sell_threshold", 0.45)),
            tp_r=float(bundle_cfg.get("tp_r", 2.0)),
            sl_r=float(bundle_cfg.get("sl_r", 1.0)),
            risk_pct=float(bundle_cfg.get("risk_pct", 0.005)),
        )
        for key, value in overrides.items():
            if hasattr(base, key):
                setattr(base, key, value)
        return base
