"""Read-only operator broker/deal evidence parsing — no MT5, no credentials."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

_REDACT_KEYS = frozenset(
    {
        "login",
        "password",
        "mt5_password",
        "mt5_login",
        "server_password",
        "token",
        "api_key",
    }
)

DEFAULT_EVIDENCE_PATHS: tuple[str, ...] = (
    "logs/operator_broker_evidence_demo_raw.json",
    "logs/operator_broker_evidence_raw.json",
    "logs/operator_broker_symbol_catalog_raw.json",
)


class FieldAvailability(str, Enum):
    OBSERVED = "OBSERVED"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class SwapEvidenceClass(str, Enum):
    OBSERVED_REALIZED = "OBSERVED_REALIZED"
    BROKER_RATE_ONLY = "BROKER_RATE_ONLY"
    UNKNOWN = "UNKNOWN"


class SlippageEvidenceClass(str, Enum):
    REALIZED = "REALIZED"
    MODELED_PROXY = "MODELED_PROXY"
    UNKNOWN = "UNKNOWN"


@dataclass
class DealFieldStatus:
    field: str
    availability: str
    value: Any = None


@dataclass
class DealTapeRecord:
    source_artifact: str
    symbol: str | None = None
    side: str | None = None
    requested_volume: DealFieldStatus | None = None
    filled_volume: DealFieldStatus | None = None
    requested_price: DealFieldStatus | None = None
    actual_fill_price: DealFieldStatus | None = None
    exit_price: DealFieldStatus | None = None
    commission: DealFieldStatus | None = None
    swap: DealFieldStatus | None = None
    profit: DealFieldStatus | None = None
    open_time: DealFieldStatus | None = None
    close_time: DealFieldStatus | None = None
    partial_fill: DealFieldStatus | None = None
    realized_slippage: DealFieldStatus | None = None
    slippage_class: str = SlippageEvidenceClass.UNKNOWN.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def _sanitize_value(key: str, value: Any) -> Any:
    if key.lower() in _REDACT_KEYS or "password" in key.lower():
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _sanitize_value(k, v) for k, v in value.items()}
    return value


def _field_status(key: str, raw: Any) -> DealFieldStatus:
    if raw is None:
        return DealFieldStatus(key, FieldAvailability.ABSENT.value)
    text = str(raw).strip().upper()
    if text in ("NOT AVAILABLE", "N/A", "NA", "UNKNOWN", ""):
        return DealFieldStatus(key, FieldAvailability.ABSENT.value)
    return DealFieldStatus(key, FieldAvailability.OBSERVED.value, _sanitize_value(key, raw))


def _extract_spec(evidence: dict[str, Any]) -> dict[str, Any]:
    for key in ("XAUUSD_i", "symbol_info", "spec"):
        block = evidence.get(key)
        if isinstance(block, dict):
            if "spec" in block and isinstance(block["spec"], dict):
                return block["spec"]
            return block
    return {}


def parse_closed_deal(evidence: dict[str, Any], *, source: str) -> DealTapeRecord | None:
    deal = evidence.get("closed_deal") or evidence.get("closed_deals")
    if not isinstance(deal, dict):
        return None

    requested_price = deal.get("requested_price")
    actual_fill = deal.get("actual_fill_price") or deal.get("fill_price")
    entry_price = deal.get("entry_price")

    rec = DealTapeRecord(
        source_artifact=source,
        symbol=str(deal.get("symbol")) if deal.get("symbol") else None,
        side=str(deal.get("side")) if deal.get("side") else None,
        requested_volume=_field_status("requested_volume", deal.get("requested_volume")),
        filled_volume=_field_status("filled_volume", deal.get("filled_volume")),
        requested_price=_field_status("requested_price", requested_price),
        actual_fill_price=_field_status("actual_fill_price", actual_fill),
        exit_price=_field_status("exit_price", deal.get("exit_price")),
        commission=_field_status("commission", deal.get("commission")),
        swap=_field_status("swap", deal.get("swap")),
        profit=_field_status("profit", deal.get("profit")),
        open_time=_field_status("open_timestamp_utc", deal.get("open_timestamp_utc")),
        close_time=_field_status("close_timestamp_utc", deal.get("close_timestamp_utc")),
        partial_fill=_field_status("partial_fill", deal.get("partial_fill")),
    )

    req_p = rec.requested_price
    fill_p = rec.actual_fill_price
    if (
        deal.get("requested_price") is not None
        and (deal.get("actual_fill_price") is not None or deal.get("fill_price") is not None)
        and req_p
        and fill_p
        and req_p.availability == FieldAvailability.OBSERVED.value
        and fill_p.availability == FieldAvailability.OBSERVED.value
    ):
        try:
            delta = float(fill_p.value) - float(req_p.value)
            rec.realized_slippage = DealFieldStatus(
                "realized_slippage",
                FieldAvailability.OBSERVED.value,
                delta,
            )
            rec.slippage_class = SlippageEvidenceClass.REALIZED.value
        except (TypeError, ValueError):
            rec.slippage_class = SlippageEvidenceClass.UNKNOWN.value
    else:
        rec.slippage_class = SlippageEvidenceClass.UNKNOWN.value

    return rec


@dataclass
class CommissionEvidenceSummary:
    status: str
    sample_count: int
    observed_values: list[float] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_commission(deals: list[DealTapeRecord]) -> CommissionEvidenceSummary:
    observed: list[float] = []
    for d in deals:
        if d.commission and d.commission.availability == FieldAvailability.OBSERVED.value:
            try:
                observed.append(float(d.commission.value))
            except (TypeError, ValueError):
                continue
    if not observed:
        return CommissionEvidenceSummary(
            status="UNKNOWN",
            sample_count=0,
            note="no observed commission in deal evidence",
        )
    if all(v == 0.0 for v in observed):
        return CommissionEvidenceSummary(
            status="UNKNOWN",
            sample_count=len(observed),
            observed_values=observed,
            note=(
                f"{len(observed)} deal(s) with commission=0.0 — insufficient for universal schedule; "
                "OBSERVED_ZERO_NOT_PROVEN; status remains UNKNOWN"
            ),
        )
    return CommissionEvidenceSummary(
        status="OBSERVED",
        sample_count=len(observed),
        observed_values=observed,
        note="observed values only — not a universal broker schedule",
    )


@dataclass
class SwapEvidenceSummary:
    status: str
    deal_swap_observed: bool
    broker_swap_long: float | None = None
    broker_swap_short: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarize_swap(deals: list[DealTapeRecord], spec: dict[str, Any]) -> SwapEvidenceSummary:
    deal_swap = any(
        d.swap and d.swap.availability == FieldAvailability.OBSERVED.value for d in deals
    )
    long_rate = spec.get("swap_long")
    short_rate = spec.get("swap_short")
    if long_rate is None and isinstance(spec.get("spec"), dict):
        long_rate = spec["spec"].get("swap_long")
        short_rate = spec["spec"].get("swap_short")

    broker_rates = long_rate is not None or short_rate is not None
    if deal_swap:
        return SwapEvidenceSummary(
            status=SwapEvidenceClass.OBSERVED_REALIZED.value,
            deal_swap_observed=True,
            broker_swap_long=_float_or_none(long_rate),
            broker_swap_short=_float_or_none(short_rate),
            note="deal-level swap observed — not projected as historical series",
        )
    if broker_rates:
        return SwapEvidenceSummary(
            status=SwapEvidenceClass.BROKER_RATE_ONLY.value,
            deal_swap_observed=False,
            broker_swap_long=_float_or_none(long_rate),
            broker_swap_short=_float_or_none(short_rate),
            note="broker spec swap rates only — not historical realized swap",
        )
    return SwapEvidenceSummary(status=SwapEvidenceClass.UNKNOWN.value, deal_swap_observed=False)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_operator_evidence_bundle(
    base_dir: str | Path | None = None,
    paths: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    deals: list[DealTapeRecord] = []
    artifacts: list[str] = []
    specs: dict[str, dict[str, Any]] = {}

    for rel in paths or DEFAULT_EVIDENCE_PATHS:
        path = root / rel
        data = _safe_load_json(path)
        if data is None:
            continue
        artifacts.append(str(path))
        deal = parse_closed_deal(data, source=str(path))
        if deal:
            deals.append(deal)
        spec = _extract_spec(data)
        if spec:
            specs[rel] = {k: _sanitize_value(k, v) for k, v in spec.items() if k.lower() not in _REDACT_KEYS}

    commission = summarize_commission(deals)
    combined_spec = {}
    for s in specs.values():
        combined_spec.update(s)
    swap = summarize_swap(deals, combined_spec)

    return {
        "artifacts_found": artifacts,
        "deal_count": len(deals),
        "deals": [d.to_dict() for d in deals],
        "commission": commission.to_dict(),
        "swap": swap.to_dict(),
        "slippage_classes": sorted({d.slippage_class for d in deals}) if deals else ["UNKNOWN"],
        "credentials_exposed": False,
    }
