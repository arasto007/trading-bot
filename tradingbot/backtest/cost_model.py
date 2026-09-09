"""Explicit backtest cost availability — never silently substitute zero for unknown."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from tradingbot.domain.session_logic import variable_spread_pips, variable_slippage_pips


class CostAvailability(str, Enum):
    MODELED = "MODELED"
    ZERO = "ZERO"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BROKER_RATE_ONLY = "BROKER_RATE_ONLY"
    MODELED_PROXY = "MODELED_PROXY"
    OBSERVED_ZERO_NOT_PROVEN = "OBSERVED_ZERO_NOT_PROVEN"
    VERIFIED_SCHEDULE = "VERIFIED_SCHEDULE"


def availability_blocks_completeness(availability: CostAvailability | str) -> bool:
    """Proxy / rate-only / unverified statuses are recorded, not historical completeness."""
    value = availability.value if isinstance(availability, CostAvailability) else str(availability).upper()
    return value in (
        CostAvailability.UNKNOWN.value,
        CostAvailability.BROKER_RATE_ONLY.value,
        CostAvailability.MODELED_PROXY.value,
        CostAvailability.OBSERVED_ZERO_NOT_PROVEN.value,
        CostAvailability.VERIFIED_SCHEDULE.value,
    )


class SpreadMode(str, Enum):
    DATASET = "DATASET"
    PROXY = "PROXY"
    CONFIGURED = "CONFIGURED"
    UNKNOWN = "UNKNOWN"


class CostCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class CostPhase(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ROUND_TRIP = "ROUND_TRIP"


@dataclass(frozen=True)
class CostTrace:
    component: str
    phase: CostPhase
    availability: CostAvailability
    mode: str
    source: str
    value: float | None = None
    unit: str = ""
    evidence_class: str = ""
    sample_count: int | None = None
    timestamp_range: str = ""


@dataclass(frozen=True)
class CostComponent:
    availability: CostAvailability
    value: float | None = None
    source: str = ""
    mode: str = ""


BID_ASK_COLUMN_PAIRS: tuple[tuple[str, str], ...] = (
    ("ask", "bid"),
    ("ask_price", "bid_price"),
    ("Ask", "Bid"),
)


@dataclass(frozen=True)
class SpreadValidationResult:
    """Deterministic spread classification for a dataset frame."""

    spread_mode: SpreadMode
    spread_source: str
    unit: str
    sample_count: int = 0
    mean_spread_price: float | None = None
    errors: tuple[str, ...] = ()


def validate_dataset_spread(
    df: pd.DataFrame | None,
    *,
    digits: int | None = None,
    point: float | None = None,
) -> SpreadValidationResult:
    """
    Classify spread evidence from frame columns — never infer from OHLC range.

    bid+ask -> DATASET (price units); explicit spread column only when units verifiable.
    OHLC-only -> PROXY. Ambiguous -> UNKNOWN.
    """
    if df is None or df.empty:
        return SpreadValidationResult(
            SpreadMode.UNKNOWN,
            "empty_frame",
            "unknown",
            errors=("empty_frame",),
        )

    cols = {str(c).lower(): c for c in df.columns}
    bid_col = cols.get("bid") or cols.get("bid_price")
    ask_col = cols.get("ask") or cols.get("ask_price")

    if bid_col is not None and ask_col is not None:
        bid = pd.to_numeric(df[bid_col], errors="coerce")
        ask = pd.to_numeric(df[ask_col], errors="coerce")
        spread = ask - bid
        valid = spread.notna() & (spread >= 0)
        if not valid.any():
            return SpreadValidationResult(
                SpreadMode.UNKNOWN,
                "bid_ask_invalid",
                "price",
                errors=("no_valid_bid_ask_rows",),
            )
        if (spread[valid] < 0).any():
            return SpreadValidationResult(
                SpreadMode.UNKNOWN,
                "bid_ask_negative",
                "price",
                errors=("negative_spread_detected",),
            )
        mean_sp = float(spread[valid].mean())
        return SpreadValidationResult(
            SpreadMode.DATASET,
            "bid_ask_columns",
            "price",
            sample_count=int(valid.sum()),
            mean_spread_price=mean_sp,
        )

    if bid_col is not None and ask_col is None:
        return SpreadValidationResult(SpreadMode.UNKNOWN, "missing_ask", "unknown", errors=("missing_ask",))
    if ask_col is not None and bid_col is None:
        return SpreadValidationResult(SpreadMode.UNKNOWN, "missing_bid", "unknown", errors=("missing_bid",))

    spread_col = cols.get("spread") or cols.get("tick_spread")
    if spread_col is not None:
        raw = pd.to_numeric(df[spread_col], errors="coerce")
        if raw.isna().all():
            return SpreadValidationResult(
                SpreadMode.UNKNOWN,
                "spread_column_nan",
                "unknown",
                errors=("spread_column_all_nan",),
            )
        if (raw < 0).any():
            return SpreadValidationResult(
                SpreadMode.UNKNOWN,
                "spread_column_negative",
                "unknown",
                errors=("negative_spread_column",),
            )
        close_col = cols.get("close")
        close = pd.to_numeric(df[close_col], errors="coerce") if close_col else None
        if close is not None and close.median() > 100 and raw.median() < 50:
            return SpreadValidationResult(
                SpreadMode.CONFIGURED,
                "spread_column_pips_not_historical_bid_ask",
                "pips",
                sample_count=int(raw.notna().sum()),
                mean_spread_price=float(raw.mean()),
            )
        return SpreadValidationResult(
            SpreadMode.CONFIGURED,
            "spread_column_not_historical_bid_ask",
            "price",
            sample_count=int(raw.notna().sum()),
            mean_spread_price=float(raw.mean()),
        )

    if _column_names_present(df, "open", "high", "low", "close"):
        return SpreadValidationResult(SpreadMode.PROXY, "ohlc_only", "proxy")

    return SpreadValidationResult(SpreadMode.UNKNOWN, "no_price_columns", "unknown", errors=("no_price_columns",))


def _column_names_present(df: pd.DataFrame, *names: str) -> bool:
    cols = {str(c).lower() for c in df.columns}
    return all(n.lower() in cols for n in names)


def frame_has_historical_bid_ask(df: pd.DataFrame | None) -> bool:
    """True only when bid and ask columns exist with at least one valid pair.

    A live tick, OHLC range, proxy multiplier, or spread column is not historical bid/ask.
    """
    if df is None or df.empty:
        return False
    cols = {str(c).lower(): c for c in df.columns}
    bid_col = cols.get("bid") or cols.get("bid_price")
    ask_col = cols.get("ask") or cols.get("ask_price")
    if bid_col is None or ask_col is None:
        return False
    bid = pd.to_numeric(df[bid_col], errors="coerce")
    ask = pd.to_numeric(df[ask_col], errors="coerce")
    valid = bid.notna() & ask.notna() & (ask >= bid)
    return bool(valid.any())


def detect_spread_mode_from_frame(df: pd.DataFrame | None) -> SpreadMode:
    """DATASET only when historical bid/ask columns exist. Spread/OHLC is not DATASET."""
    if df is None or df.empty:
        return SpreadMode.UNKNOWN
    if frame_has_historical_bid_ask(df):
        return SpreadMode.DATASET
    cols = {str(c).lower() for c in df.columns}
    if "open" in cols and "high" in cols and "low" in cols and "close" in cols:
        return SpreadMode.PROXY
    return SpreadMode.UNKNOWN


def spread_price_from_bar(bar: Any, *, pip: float) -> tuple[float | None, str]:
    """
    Return spread in price units from bar row.

    Prefer ask-bid; fall back to explicit spread columns (converted via pip when in pips).
    """
    if bar is None:
        return None, "missing_bar"

    def _get(name: str) -> float | None:
        if hasattr(bar, "get"):
            val = bar.get(name)
        elif hasattr(bar, name):
            val = getattr(bar, name)
        else:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    ask = _get("ask") or _get("ask_price")
    bid = _get("bid") or _get("bid_price")
    if ask is not None and bid is not None and ask >= bid:
        return ask - bid, "dataset_ask_bid"

    spread_raw = _get("spread") or _get("tick_spread")
    if spread_raw is not None and spread_raw >= 0:
        # Assume pips when spread column is small relative to price scale
        close = _get("close") or 0.0
        if close > 100 and spread_raw < 50:
            return spread_raw * pip, "dataset_spread_pips"
        return spread_raw, "dataset_spread_price"

    return None, "no_spread_columns"


def spread_pips_from_bar(bar: Any, *, symbol: str, pip: float | None = None) -> float | None:
    from tradingbot.domain.position_logic import pip_size

    pip_val = pip if pip is not None else pip_size(symbol)
    spread_price, _ = spread_price_from_bar(bar, pip=pip_val)
    if spread_price is None or pip_val <= 0:
        return None
    return spread_price / pip_val


@dataclass(frozen=True)
class BacktestCostModel:
    """Offline cost model status for backtest execution parity reporting."""

    spread: CostComponent
    commission: CostComponent
    swap: CostComponent
    slippage: CostComponent
    spread_mode: SpreadMode = SpreadMode.PROXY
    completeness: CostCompleteness = CostCompleteness.UNKNOWN
    traces: tuple[CostTrace, ...] = field(default_factory=tuple)

    def spread_pips_at_hour(self, hour: int) -> float | None:
        if self.spread.availability not in (CostAvailability.MODELED, CostAvailability.ZERO):
            return None
        base = float(self.spread.value or 0.0)
        if self.spread_mode == SpreadMode.PROXY and self.spread.source == "variable_proxy":
            return variable_spread_pips(base, hour)
        return base

    def slippage_pips_at_hour(self, hour: int) -> float | None:
        if self.slippage.availability not in (
            CostAvailability.MODELED,
            CostAvailability.MODELED_PROXY,
            CostAvailability.ZERO,
        ):
            return None
        base = float(self.slippage.value or 0.0)
        if self.slippage.source == "variable_proxy":
            return variable_slippage_pips(base, hour)
        return base

    def trace_for(self, component: str, phase: CostPhase) -> CostTrace | None:
        for t in self.traces:
            if t.component == component and t.phase == phase:
                return t
        return None


@dataclass(frozen=True)
class RoundTripCostEstimate:
    """Conceptual round-trip cost — spread counted entry+exit halves, no double full spread."""

    entry_traces: tuple[CostTrace, ...]
    exit_traces: tuple[CostTrace, ...]
    completeness: CostCompleteness
    total_modeled_pips: float | None = None

    @property
    def round_trip_traces(self) -> tuple[CostTrace, ...]:
        return self.entry_traces + self.exit_traces


def estimate_round_trip_cost(model: BacktestCostModel, *, hour: int = 12) -> RoundTripCostEstimate:
    """
    Aggregate entry + exit costs without double-counting full spread at one leg.

    Spread: half at entry + half at exit = one full spread width (not 2× full spread).
    Commission: entry only unless configured per-side (not implemented — single charge).
    Slippage: modeled per leg when MODELED.
    Swap: UNKNOWN unless historical series exists.
    """
    entry: list[CostTrace] = []
    exit_traces: list[CostTrace] = []
    total_pips: float | None = 0.0
    any_unknown = False
    any_modeled = False

    spread_pips = model.spread_pips_at_hour(hour)
    if spread_pips is not None:
        half = spread_pips / 2.0
        entry.append(
            CostTrace("spread", CostPhase.ENTRY, CostAvailability.MODELED, model.spread_mode.value, model.spread.source, half, "pips")
        )
        exit_traces.append(
            CostTrace("spread", CostPhase.EXIT, CostAvailability.MODELED, model.spread_mode.value, model.spread.source, half, "pips")
        )
        any_modeled = True
        assert total_pips is not None
        total_pips += spread_pips
    elif model.spread.availability == CostAvailability.UNKNOWN:
        any_unknown = True
        entry.append(CostTrace("spread", CostPhase.ENTRY, CostAvailability.UNKNOWN, SpreadMode.UNKNOWN.value, model.spread.source, None, "pips"))
        total_pips = None

    if model.commission.availability == CostAvailability.MODELED:
        val = float(model.commission.value or 0.0)
        entry.append(
            CostTrace("commission", CostPhase.ENTRY, CostAvailability.MODELED, "configured", model.commission.source, val, "per_lot")
        )
        any_modeled = True
    elif model.commission.availability == CostAvailability.ZERO:
        entry.append(
            CostTrace("commission", CostPhase.ENTRY, CostAvailability.ZERO, "explicit_zero", model.commission.source, 0.0, "per_lot")
        )
    else:
        any_unknown = True
        entry.append(CostTrace("commission", CostPhase.ENTRY, CostAvailability.UNKNOWN, "unknown", model.commission.source, None, "per_lot"))
        total_pips = None

    slip = model.slippage_pips_at_hour(hour)
    if slip is not None:
        slip_avail = model.slippage.availability
        slip_mode = model.slippage.mode or "modeled_proxy"
        entry.append(CostTrace("slippage", CostPhase.ENTRY, slip_avail, slip_mode, model.slippage.source, slip, "pips"))
        exit_traces.append(CostTrace("slippage", CostPhase.EXIT, slip_avail, slip_mode, model.slippage.source, slip, "pips"))
        any_modeled = True
        if total_pips is not None:
            total_pips += 2 * slip
        if availability_blocks_completeness(slip_avail):
            any_unknown = True
    elif model.slippage.availability == CostAvailability.UNKNOWN or availability_blocks_completeness(
        model.slippage.availability
    ):
        any_unknown = True
        total_pips = None

    if availability_blocks_completeness(model.swap.availability):
        any_unknown = True

    if any_unknown and any_modeled:
        completeness = CostCompleteness.PARTIAL
    elif any_unknown:
        completeness = CostCompleteness.UNKNOWN
    else:
        completeness = CostCompleteness.COMPLETE

    return RoundTripCostEstimate(
        entry_traces=tuple(entry),
        exit_traces=tuple(exit_traces),
        completeness=completeness,
        total_modeled_pips=total_pips,
    )


def assess_cost_completeness(model: BacktestCostModel) -> CostCompleteness:
    unknowns = [
        model.spread.availability == CostAvailability.UNKNOWN,
        availability_blocks_completeness(model.commission.availability)
        or model.commission.availability == CostAvailability.UNKNOWN,
        availability_blocks_completeness(model.swap.availability),
        availability_blocks_completeness(model.slippage.availability)
        or model.slippage.availability == CostAvailability.UNKNOWN,
    ]
    modeled = [
        model.spread.availability == CostAvailability.MODELED,
        model.commission.availability in (CostAvailability.MODELED, CostAvailability.ZERO),
        model.slippage.availability
        in (CostAvailability.MODELED, CostAvailability.MODELED_PROXY, CostAvailability.ZERO),
    ]
    if all(not u for u in unknowns):
        return CostCompleteness.COMPLETE
    if any(modeled):
        return CostCompleteness.PARTIAL
    return CostCompleteness.UNKNOWN


def cost_source_summary(traces: list[dict[str, Any]] | tuple) -> dict[str, str]:
    """Summarize cost component sources for metrics/reporting."""
    summary: dict[str, str] = {}
    for raw in traces:
        comp = str(raw.get("component", "")) if isinstance(raw, dict) else getattr(raw, "component", "")
        if not comp:
            continue
        if isinstance(raw, dict):
            summary[comp] = f"{raw.get('mode', 'UNKNOWN')}:{raw.get('source', 'unknown')}"
        else:
            summary[comp] = f"{raw.mode}:{raw.source}"
    return summary


def build_backtest_cost_model(
    cfg: Any,
    *,
    spread_mode: str | SpreadMode | None = None,
    frame: pd.DataFrame | None = None,
) -> BacktestCostModel:
    """
    Build cost model from BacktestConfig.

    spread_mode AUTO: detect bid/ask in frame → DATASET else PROXY.
    Commission ZERO only when commission_status='ZERO' (explicit evidence).
    Observed zeros and VERIFIED_SCHEDULE-without-applicability stay fail-closed.
    """
    if spread_mode is None or str(spread_mode).upper() == "AUTO":
        detected = detect_spread_mode_from_frame(frame)
        mode = detected if detected != SpreadMode.UNKNOWN else SpreadMode.PROXY
    else:
        mode = SpreadMode(str(spread_mode).upper())

    spread_val = float(getattr(cfg, "spread_pips", 0.0))
    slip_val = float(getattr(cfg, "slippage_pips", 0.0))
    comm_val = float(getattr(cfg, "commission_per_lot", 0.0))
    comm_status = str(getattr(cfg, "commission_status", "UNKNOWN")).upper()
    slip_status = str(getattr(cfg, "slippage_status", "UNKNOWN")).upper()
    swap_status = str(getattr(cfg, "swap_status", "UNKNOWN")).upper()

    if mode == SpreadMode.UNKNOWN:
        spread = CostComponent(CostAvailability.UNKNOWN, source="no_spread_data", mode=SpreadMode.UNKNOWN.value)
    elif mode == SpreadMode.DATASET:
        spread = CostComponent(CostAvailability.MODELED, value=spread_val, source="dataset_bid_ask", mode=SpreadMode.DATASET.value)
    elif mode == SpreadMode.CONFIGURED:
        spread = CostComponent(CostAvailability.MODELED, value=spread_val, source="configured_series", mode=SpreadMode.CONFIGURED.value)
    else:
        spread = CostComponent(
            CostAvailability.MODELED,
            value=spread_val,
            source="variable_proxy",
            mode=SpreadMode.PROXY.value,
        )

    if comm_status == "ZERO":
        commission = CostComponent(CostAvailability.ZERO, value=0.0, source="explicit_zero_evidence", mode="ZERO")
    elif comm_status == "MODELED" and comm_val > 0:
        commission = CostComponent(CostAvailability.MODELED, value=comm_val, source="configured_per_lot", mode="MODELED")
    elif comm_status == "MODELED":
        commission = CostComponent(CostAvailability.MODELED, value=comm_val, source="configured_per_lot", mode="MODELED")
    elif comm_status == CostAvailability.OBSERVED_ZERO_NOT_PROVEN.value:
        commission = CostComponent(
            CostAvailability.OBSERVED_ZERO_NOT_PROVEN,
            value=None,
            source="observed_zero_not_verified_schedule",
            mode=CostAvailability.OBSERVED_ZERO_NOT_PROVEN.value,
        )
    elif comm_status == CostAvailability.VERIFIED_SCHEDULE.value:
        commission = CostComponent(
            CostAvailability.VERIFIED_SCHEDULE,
            value=None,
            source="verified_schedule_policy_without_applicable_schedule",
            mode=CostAvailability.VERIFIED_SCHEDULE.value,
        )
    else:
        commission = CostComponent(CostAvailability.UNKNOWN, source="no_commission_evidence", mode="UNKNOWN")

    if swap_status == "MODELED":
        swap = CostComponent(CostAvailability.MODELED, value=float(getattr(cfg, "swap_per_lot_per_day", 0.0)), source="configured", mode="MODELED")
    elif swap_status == "ZERO":
        swap = CostComponent(CostAvailability.ZERO, value=0.0, source="explicit_zero_evidence", mode="ZERO")
    elif swap_status == CostAvailability.BROKER_RATE_ONLY.value:
        swap = CostComponent(
            CostAvailability.BROKER_RATE_ONLY,
            value=None,
            source="broker_spec_rate_not_historical_series",
            mode=CostAvailability.BROKER_RATE_ONLY.value,
        )
    else:
        swap = CostComponent(CostAvailability.UNKNOWN, source="no_historical_swap_data", mode="UNKNOWN")

    if slip_status == "ZERO":
        slippage = CostComponent(CostAvailability.ZERO, value=0.0, source="explicit_zero_evidence", mode="ZERO")
    elif slip_status in ("MODELED", "MODELED_PROXY") and slip_val > 0:
        slippage = CostComponent(
            CostAvailability.MODELED_PROXY,
            value=slip_val,
            source="variable_proxy",
            mode=CostAvailability.MODELED_PROXY.value,
        )
    elif slip_status in ("MODELED", "MODELED_PROXY"):
        slippage = CostComponent(
            CostAvailability.UNKNOWN,
            source="modeled_parameter_non_positive_not_silent_zero",
            mode="UNKNOWN",
        )
    elif slip_status == "REALIZED":
        slippage = CostComponent(
            CostAvailability.UNKNOWN,
            source="realized_claimed_without_fill_distribution",
            mode="UNKNOWN",
        )
    else:
        slippage = CostComponent(CostAvailability.UNKNOWN, source="no_slippage_evidence", mode="UNKNOWN")

    model = BacktestCostModel(
        spread=spread,
        commission=commission,
        swap=swap,
        slippage=slippage,
        spread_mode=mode,
    )
    completeness = assess_cost_completeness(model)
    rt = estimate_round_trip_cost(model)
    return BacktestCostModel(
        spread=spread,
        commission=commission,
        swap=swap,
        slippage=slippage,
        spread_mode=mode,
        completeness=completeness,
        traces=rt.round_trip_traces,
    )
