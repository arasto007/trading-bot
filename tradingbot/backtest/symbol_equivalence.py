"""Deterministic XAUUSD ↔ XAUUSD_i economic comparison — evidence only."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

COMPARISON_FIELDS: tuple[str, ...] = (
    "contract_size",
    "point",
    "digits",
    "tick_size",
    "tick_value",
    "tick_value_profit",
    "tick_value_loss",
    "volume_min",
    "volume_max",
    "volume_step",
    "stops_level",
    "freeze_level",
    "execution_mode",
    "calculation_mode",
    "currency_profit",
    "currency_margin",
    "swap_long",
    "swap_short",
)

SPEC_FIELD_MAP: dict[str, tuple[str, ...]] = {
    "contract_size": ("trade_contract_size", "contract_size"),
    "point": ("point",),
    "digits": ("digits",),
    "tick_size": ("trade_tick_size", "tick_size"),
    "tick_value": ("trade_tick_value", "tick_value"),
    "tick_value_profit": ("trade_tick_value_profit", "tick_value_profit"),
    "tick_value_loss": ("trade_tick_value_loss", "tick_value_loss"),
    "volume_min": ("volume_min",),
    "volume_max": ("volume_max",),
    "volume_step": ("volume_step",),
    "stops_level": ("trade_stops_level", "stops_level"),
    "freeze_level": ("trade_freeze_level", "freeze_level"),
    "execution_mode": ("trade_exemode", "execution_mode"),
    "calculation_mode": ("trade_calc_mode", "calculation_mode"),
    "currency_profit": ("currency_profit",),
    "currency_margin": ("currency_margin",),
    "swap_long": ("swap_long",),
    "swap_short": ("swap_short",),
}


class FieldComparison(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class EquivalenceConclusion(str, Enum):
    PROVEN = "PROVEN"
    DISPROVEN = "DISPROVEN"
    NOT_PROVEN = "NOT_PROVEN"


@dataclass
class SymbolSpecSnapshot:
    symbol: str
    exists: bool
    visible: bool | None = None
    environment: str = ""
    server: str = ""
    evidence_artifact: str = ""
    evidence_timestamp: str = ""
    spec: dict[str, Any] = field(default_factory=dict)


@dataclass
class FieldComparisonResult:
    field: str
    left_symbol: str
    right_symbol: str
    left_value: Any = None
    right_value: Any = None
    classification: str = FieldComparison.UNKNOWN.value


@dataclass
class SymbolEquivalenceAudit:
    schema_version: int = 1
    generated_at: str = ""
    environment: str = ""
    server: str = ""
    left_symbol: str = "XAUUSD"
    right_symbol: str = "XAUUSD_i"
    left_exists: bool = False
    right_exists: bool = False
    both_on_same_environment: bool = False
    field_comparisons: list[FieldComparisonResult] = field(default_factory=list)
    ev_eq_01: str = EquivalenceConclusion.NOT_PROVEN.value
    rationale: str = ""
    evidence_artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "environment": self.environment,
            "server": self.server,
            "left_symbol": self.left_symbol,
            "right_symbol": self.right_symbol,
            "left_exists": self.left_exists,
            "right_exists": self.right_exists,
            "both_on_same_environment": self.both_on_same_environment,
            "field_comparisons": [asdict(f) for f in self.field_comparisons],
            "ev_eq_01": self.ev_eq_01,
            "rationale": self.rationale,
            "evidence_artifacts": self.evidence_artifacts,
        }


def _extract_spec_value(spec: dict[str, Any], field_name: str) -> Any:
    for key in SPEC_FIELD_MAP.get(field_name, (field_name,)):
        if key in spec and spec[key] is not None:
            val = spec[key]
            if isinstance(val, str) and val.strip().upper() in ("NOT AVAILABLE", "N/A", "NA", "UNKNOWN", ""):
                return None
            return val
    return None


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 10)
    if isinstance(value, (int, str, bool)):
        return value
    return value


def compare_field(
    field_name: str,
    left_spec: dict[str, Any],
    right_spec: dict[str, Any],
    *,
    left_symbol: str,
    right_symbol: str,
) -> FieldComparisonResult:
    left_val = _extract_spec_value(left_spec, field_name)
    right_val = _extract_spec_value(right_spec, field_name)
    if left_val is None and right_val is None:
        classification = FieldComparison.NOT_AVAILABLE
    elif left_val is None or right_val is None:
        classification = FieldComparison.UNKNOWN
    elif _normalize_value(left_val) == _normalize_value(right_val):
        classification = FieldComparison.MATCH
    else:
        classification = FieldComparison.MISMATCH
    return FieldComparisonResult(
        field=field_name,
        left_symbol=left_symbol,
        right_symbol=right_symbol,
        left_value=left_val,
        right_value=right_val,
        classification=classification.value,
    )


def conclude_equivalence(
    comparisons: list[FieldComparisonResult],
    *,
    left_exists: bool,
    right_exists: bool,
    same_environment: bool,
) -> tuple[str, str]:
    """Deterministic EV-EQ-01 conclusion."""
    if not left_exists or not right_exists:
        return (
            EquivalenceConclusion.NOT_PROVEN.value,
            "both symbols must exist on the same broker/server/environment for comparison",
        )
    if not same_environment:
        return (
            EquivalenceConclusion.NOT_PROVEN.value,
            "comparison requires same environment — cross-terminal inference not allowed",
        )

    mismatches = [c for c in comparisons if c.classification == FieldComparison.MISMATCH.value]
    if mismatches:
        fields = ", ".join(c.field for c in mismatches)
        return (
            EquivalenceConclusion.DISPROVEN.value,
            f"economic field mismatch: {fields}",
        )

    critical = (
        "contract_size",
        "point",
        "digits",
        "tick_size",
        "tick_value",
        "volume_min",
        "volume_max",
        "volume_step",
    )
    critical_comparisons = [c for c in comparisons if c.field in critical]
    if not critical_comparisons:
        return EquivalenceConclusion.NOT_PROVEN.value, "no critical fields compared"

    unavailable = [
        c
        for c in critical_comparisons
        if c.classification in (FieldComparison.UNKNOWN.value, FieldComparison.NOT_AVAILABLE.value)
    ]
    if unavailable:
        fields = ", ".join(c.field for c in unavailable)
        return (
            EquivalenceConclusion.NOT_PROVEN.value,
            f"insufficient critical field evidence: {fields}",
        )

    non_match = [c for c in critical_comparisons if c.classification != FieldComparison.MATCH.value]
    if non_match:
        return EquivalenceConclusion.NOT_PROVEN.value, "critical fields not all MATCH"

    non_critical_unknown = [
        c
        for c in comparisons
        if c.field not in critical and c.classification == FieldComparison.MISMATCH.value
    ]
    if non_critical_unknown:
        return EquivalenceConclusion.NOT_PROVEN.value, "non-critical mismatch present"

    return (
        EquivalenceConclusion.PROVEN.value,
        "all critical economic fields MATCH on same environment with observed specs",
    )


def build_equivalence_audit(
    left: SymbolSpecSnapshot,
    right: SymbolSpecSnapshot,
    *,
    same_environment: bool = True,
) -> SymbolEquivalenceAudit:
    comparisons = [
        compare_field(f, left.spec, right.spec, left_symbol=left.symbol, right_symbol=right.symbol)
        for f in COMPARISON_FIELDS
    ]
    conclusion, rationale = conclude_equivalence(
        comparisons,
        left_exists=left.exists,
        right_exists=right.exists,
        same_environment=same_environment,
    )
    return SymbolEquivalenceAudit(
        generated_at=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        environment=left.environment or right.environment,
        server=left.server or right.server,
        left_symbol=left.symbol,
        right_symbol=right.symbol,
        left_exists=left.exists,
        right_exists=right.exists,
        both_on_same_environment=same_environment and left.exists and right.exists,
        field_comparisons=comparisons,
        ev_eq_01=conclusion,
        rationale=rationale,
        evidence_artifacts=sorted({a for a in (left.evidence_artifact, right.evidence_artifact) if a}),
    )


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def _spec_from_evidence(data: dict[str, Any], symbol: str) -> tuple[bool, dict[str, Any]]:
    block = data.get(symbol)
    if block == "NOT AVAILABLE — absent from symbol_info and symbols_get on this Demo terminal":
        return False, {}
    if isinstance(block, str) and "NOT AVAILABLE" in block.upper():
        return False, {}
    if isinstance(block, dict):
        if block.get("exists") is False:
            return False, {}
        spec = block.get("spec") if isinstance(block.get("spec"), dict) else block
        return True, dict(spec) if isinstance(spec, dict) else {}
    return False, {}


def audit_from_operator_artifacts(
    *,
    base_dir: str | Path | None = None,
    demo_path: str = "logs/operator_broker_evidence_demo_raw.json",
    real_path: str = "logs/operator_broker_evidence_raw.json",
) -> list[SymbolEquivalenceAudit]:
    """Build per-environment equivalence audits from existing operator evidence files."""
    root = Path(base_dir or Path.cwd())
    audits: list[SymbolEquivalenceAudit] = []
    for rel, env in ((demo_path, "DEMO"), (real_path, "REAL")):
        data = _load_json(root / rel)
        if data is None:
            continue
        account = data.get("account") or {}
        server = str(account.get("server") or data.get("server") or "")
        ts = str(data.get("collection_utc") or "")
        left_exists, left_spec = _spec_from_evidence(data, "XAUUSD")
        right_exists, right_spec = _spec_from_evidence(data, "XAUUSD_i")
        left = SymbolSpecSnapshot(
            symbol="XAUUSD",
            exists=left_exists,
            visible=_visibility(data, "XAUUSD"),
            environment=env,
            server=server,
            evidence_artifact=rel,
            evidence_timestamp=ts,
            spec=left_spec,
        )
        right = SymbolSpecSnapshot(
            symbol="XAUUSD_i",
            exists=right_exists,
            visible=_visibility(data, "XAUUSD_i"),
            environment=env,
            server=server,
            evidence_artifact=rel,
            evidence_timestamp=ts,
            spec=right_spec,
        )
        audits.append(build_equivalence_audit(left, right, same_environment=True))
    return audits


def _visibility(data: dict[str, Any], symbol: str) -> bool | None:
    vis = data.get("visibility") or {}
    raw = vis.get(symbol)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().upper()
    if text == "YES":
        return True
    if text == "NO":
        return False
    return None


def write_equivalence_audit_report(
    audits: list[SymbolEquivalenceAudit],
    output_path: str | Path,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    overall = EquivalenceConclusion.NOT_PROVEN.value
    rationales: list[str] = []
    for audit in audits:
        rationales.append(f"{audit.environment}:{audit.ev_eq_01} — {audit.rationale}")
        if audit.ev_eq_01 == EquivalenceConclusion.DISPROVEN.value:
            overall = EquivalenceConclusion.DISPROVEN.value
        elif audit.ev_eq_01 == EquivalenceConclusion.PROVEN.value and overall != EquivalenceConclusion.DISPROVEN.value:
            overall = EquivalenceConclusion.PROVEN.value

    if overall == EquivalenceConclusion.PROVEN.value and len(audits) < 2:
        overall = EquivalenceConclusion.NOT_PROVEN.value
        rationales.append("PROVEN requires consistent evidence — single-environment only is insufficient for EV-EQ-01")

    if any(a.ev_eq_01 == EquivalenceConclusion.NOT_PROVEN.value for a in audits):
        if overall != EquivalenceConclusion.DISPROVEN.value:
            overall = EquivalenceConclusion.NOT_PROVEN.value

    payload = {
        "schema_version": 1,
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "ev_eq_01_overall": overall,
        "environment_audits": [a.to_dict() for a in audits],
        "rationale_summary": "; ".join(rationales),
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out
