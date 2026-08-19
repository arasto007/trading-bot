"""Runtime configuration — shadow mode defaults."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import metadata_root


def runtime_config_path(base_dir: str | Path | None = None) -> Path:
    return metadata_root(base_dir) / "runtime_config.json"


@dataclass
class RuntimeConfig:
    active_model_name: str = "xgboost"
    threshold: float = 0.60
    confidence_requirement: str = "MEDIUM"
    shadow_mode: bool = True
    live_enabled: bool = False
    symbol: str = "XAUUSD"
    timeframe: str = "M5"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeConfig":
        fields = cls.__dataclass_fields__
        cfg = cls(**{k: data[k] for k in fields if k in data})
        cfg.shadow_mode = True if data.get("shadow_mode", True) else False
        cfg.live_enabled = False if not data.get("live_enabled", False) else False
        return cfg

    def validate_safety(self) -> list[str]:
        violations: list[str] = []
        if not self.shadow_mode:
            violations.append("shadow_mode must remain True")
        if self.live_enabled:
            violations.append("live_enabled must remain False")
        return violations


class RuntimeConfigLoader:
    """Load and persist central ML runtime configuration."""

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = base_dir

    @property
    def path(self) -> Path:
        return runtime_config_path(self.base_dir)

    def load(self) -> RuntimeConfig:
        if not self.path.is_file():
            return RuntimeConfig()
        data = json.loads(self.path.read_text(encoding="utf-8"))
        cfg = RuntimeConfig.from_dict(data)
        cfg.live_enabled = False
        cfg.shadow_mode = True
        return cfg

    def save(self, config: RuntimeConfig) -> Path:
        config.live_enabled = False
        config.shadow_mode = True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return self.path

    def defaults(self) -> RuntimeConfig:
        return RuntimeConfig(shadow_mode=True, live_enabled=False)
