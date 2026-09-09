"""Explicit dataset symbol ↔ broker instrument contract — no silent equivalence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tradingbot.domain.broker_economics import BrokerEconomics

from tradingbot.backtest.instrument import resolve_backtest_economics

MAPPING_SOURCE_MATCH = "match"
MAPPING_SOURCE_EXPLICIT = "explicit_map"
MAPPING_SOURCE_NONE = "none"

STATUS_MATCH = "MATCH"
STATUS_EXPLICIT_MAP = "EXPLICIT_MAP"
STATUS_MISSING_MAP = "MISSING_MAP"
STATUS_INVALID_MAP = "INVALID_MAP"
STATUS_UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"


class InstrumentContractError(Exception):
    """Dataset symbol cannot be bound to broker economics without explicit mapping."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class DatasetInstrumentContract:
    """Deterministic binding between a dataset label and broker economics."""

    dataset_symbol: str
    broker_symbol: str
    economics: BrokerEconomics
    mapping_source: str  # match | explicit_map | economics_override


@dataclass(frozen=True)
class DatasetBinding:
    """Auditable dataset→broker binding. POLICY ≠ EV-EQ-01 evidence."""

    logical_symbol: str
    configured_symbol: str
    mapped_broker_symbol: str | None
    mapping_source: str
    mapping_status: str
    blocked: bool
    reason: str
    map_entry_used: dict[str, str] | None = None
    ev_eq_01: str = "NOT_PROVEN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_symbol": self.logical_symbol,
            "configured_symbol": self.configured_symbol,
            "mapped_broker_symbol": self.mapped_broker_symbol,
            "mapping_source": self.mapping_source,
            "mapping_status": self.mapping_status,
            "blocked": self.blocked,
            "reason": self.reason,
            "map_entry_used": self.map_entry_used,
            "ev_eq_01": self.ev_eq_01,
        }


def normalize_instrument_symbol(symbol: str) -> str:
    """Strip and normalize the XAUUSD_i spelling. Does not invent aliases."""
    raw = str(symbol).strip()
    if raw.upper().replace(" ", "") == "XAUUSD_I":
        return "XAUUSD_i"
    return raw


def _lookup_map(dataset_symbol_map: dict[str, str], logical: str) -> tuple[str, str] | None:
    if logical in dataset_symbol_map:
        return logical, dataset_symbol_map[logical]
    for key, value in dataset_symbol_map.items():
        if normalize_instrument_symbol(str(key)) == logical:
            return str(key), value
    return None


def validate_dataset_symbol_map(
    dataset_symbol_map: dict[str, str] | None,
    *,
    configured_symbol: str,
    available_broker_symbols: set[str] | frozenset[str] | None = None,
) -> None:
    """Fail closed on empty, malformed, unavailable, or non-canonical map targets.

    An explicit alias is valid only when the target equals the configured
    instrument. This never proves EV-EQ-01.
    """
    cfg = normalize_instrument_symbol(configured_symbol)
    if not cfg:
        raise InstrumentContractError("CONFIGURED_SYMBOL_EMPTY", "configured instrument symbol is empty")
    if dataset_symbol_map is None:
        return
    if not isinstance(dataset_symbol_map, dict):
        raise InstrumentContractError(
            "INVALID_MAP",
            f"dataset_symbol_map must be a dict, got {type(dataset_symbol_map).__name__}",
        )
    available = None
    if available_broker_symbols is not None:
        available = {normalize_instrument_symbol(str(s)) for s in available_broker_symbols if str(s).strip()}
    for raw_key, raw_val in dataset_symbol_map.items():
        if not isinstance(raw_key, str) or (raw_val is not None and not isinstance(raw_val, str)):
            raise InstrumentContractError(
                "INVALID_MAP",
                f"dataset_symbol_map entry {raw_key!r}->{raw_val!r} is malformed",
            )
        source = normalize_instrument_symbol(raw_key)
        target = normalize_instrument_symbol(raw_val if raw_val is not None else "")
        if not source:
            raise InstrumentContractError("INVALID_MAP", "dataset_symbol_map source is empty")
        if not target:
            raise InstrumentContractError(
                "INVALID_MAP",
                f"dataset_symbol_map target for {source!r} is empty",
            )
        if target != cfg:
            raise InstrumentContractError(
                "INVALID_MAP",
                f"dataset_symbol_map {source!r}→{target!r} does not bind to configured {cfg!r}",
            )
        if available is not None and target not in available:
            raise InstrumentContractError(
                "INVALID_MAP",
                f"dataset_symbol_map {source!r}→{target!r} target is unavailable",
            )


def resolve_broker_symbol_for_dataset(
    dataset_symbol: str,
    *,
    configured_symbol: str,
    dataset_symbol_map: dict[str, str] | None = None,
) -> tuple[str, str]:
    """
    Map dataset label to broker symbol without silent alias guessing.

    Returns (broker_symbol, mapping_source).
    Raises InstrumentContractError on mismatch without explicit map,
    or when the provided map is invalid.
    """
    ds = normalize_instrument_symbol(dataset_symbol)
    cfg = normalize_instrument_symbol(configured_symbol)
    if not ds:
        raise InstrumentContractError("DATASET_SYMBOL_EMPTY", "dataset symbol is empty")
    if not cfg:
        raise InstrumentContractError("CONFIGURED_SYMBOL_EMPTY", "configured instrument symbol is empty")

    raw_map = dict(dataset_symbol_map or {})
    validate_dataset_symbol_map(raw_map, configured_symbol=cfg)

    found = _lookup_map(raw_map, ds)
    if found is not None:
        return cfg, MAPPING_SOURCE_EXPLICIT
    if ds == cfg:
        return cfg, MAPPING_SOURCE_MATCH
    raise InstrumentContractError(
        "SYMBOL_MISMATCH",
        f"dataset symbol {ds!r} != configured {cfg!r}; explicit dataset_symbol_map required",
    )


def classify_dataset_binding(
    dataset_symbol: str,
    *,
    configured_symbol: str,
    dataset_symbol_map: dict[str, str] | None = None,
) -> DatasetBinding:
    """Classify a binding without converting missing/invalid maps into success."""
    logical = normalize_instrument_symbol(dataset_symbol)
    configured = normalize_instrument_symbol(configured_symbol)
    try:
        broker, source = resolve_broker_symbol_for_dataset(
            logical,
            configured_symbol=configured,
            dataset_symbol_map=dataset_symbol_map,
        )
        status = STATUS_EXPLICIT_MAP if source == MAPPING_SOURCE_EXPLICIT else STATUS_MATCH
        used = None
        if source == MAPPING_SOURCE_EXPLICIT:
            hit = _lookup_map(dict(dataset_symbol_map or {}), logical)
            if hit is not None:
                used = {hit[0]: normalize_instrument_symbol(str(hit[1]))}
        return DatasetBinding(
            logical_symbol=logical,
            configured_symbol=configured,
            mapped_broker_symbol=broker,
            mapping_source=source,
            mapping_status=status,
            blocked=False,
            reason="ok",
            map_entry_used=used,
        )
    except InstrumentContractError as exc:
        if exc.code == "INVALID_MAP":
            status = STATUS_INVALID_MAP
        elif exc.code in ("DATASET_SYMBOL_EMPTY", "CONFIGURED_SYMBOL_EMPTY"):
            status = STATUS_UNKNOWN_SYMBOL
        else:
            status = STATUS_MISSING_MAP
        return DatasetBinding(
            logical_symbol=logical or str(dataset_symbol),
            configured_symbol=configured,
            mapped_broker_symbol=None,
            mapping_source=MAPPING_SOURCE_NONE,
            mapping_status=status,
            blocked=True,
            reason=exc.message,
        )


def resolve_dataset_instrument(
    dataset_symbol: str,
    *,
    configured_symbol: str,
    legacy_config: dict[str, Any] | None = None,
    dataset_symbol_map: dict[str, str] | None = None,
    economics_override: dict[str, dict[str, Any]] | None = None,
    allow_offline_fallback: bool = True,
) -> DatasetInstrumentContract:
    """Resolve economics for a dataset symbol; fail closed when economics missing."""
    broker_symbol, mapping_source = resolve_broker_symbol_for_dataset(
        dataset_symbol,
        configured_symbol=configured_symbol,
        dataset_symbol_map=dataset_symbol_map,
    )

    cfg = dict(legacy_config or {})
    if economics_override:
        catalog = dict(cfg.get("BROKER_SYMBOL_CATALOG") or {})
        for sym, entry in economics_override.items():
            catalog[sym] = {**catalog.get(sym, {}), **entry}
        cfg["BROKER_SYMBOL_CATALOG"] = catalog

    economics = resolve_backtest_economics(
        broker_symbol,
        cfg,
        allow_offline_fallback=allow_offline_fallback,
    )
    if economics is None:
        raise InstrumentContractError(
            "ECONOMICS_UNAVAILABLE",
            f"no BrokerEconomics for broker symbol {broker_symbol!r}",
        )

    ok, reason = economics.validate_for_sizing()
    if not ok:
        raise InstrumentContractError("INVALID_ECONOMICS", reason)

    source = mapping_source
    if economics_override and broker_symbol in economics_override:
        source = "economics_override"

    return DatasetInstrumentContract(
        dataset_symbol=dataset_symbol,
        broker_symbol=broker_symbol,
        economics=economics,
        mapping_source=source,
    )


def validate_dataset_frames(
    frames: dict[str, Any],
    *,
    configured_symbol: str,
    legacy_config: dict[str, Any] | None = None,
    dataset_symbol_map: dict[str, str] | None = None,
    economics_override: dict[str, dict[str, Any]] | None = None,
) -> dict[str, DatasetInstrumentContract]:
    """Validate every injected dataset frame has resolvable instrument economics."""
    contracts: dict[str, DatasetInstrumentContract] = {}
    for dataset_symbol in frames:
        contracts[dataset_symbol] = resolve_dataset_instrument(
            dataset_symbol,
            configured_symbol=configured_symbol,
            legacy_config=legacy_config,
            dataset_symbol_map=dataset_symbol_map,
            economics_override=economics_override,
        )
    return contracts
