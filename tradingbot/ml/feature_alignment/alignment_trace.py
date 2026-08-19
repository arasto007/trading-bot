"""Phase 16A — explainable alignment traces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AlignmentTrace:
    shifted: list[dict[str, Any]] = field(default_factory=list)
    passthrough: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "shifted_count": len(self.shifted),
            "shifted": self.shifted,
            "passthrough_features": self.passthrough,
        }
