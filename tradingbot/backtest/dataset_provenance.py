"""Read-only dataset audit and metadata sidecar provenance — no dataset mutation."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.cost_model import (
    CostCompleteness,
    SpreadMode,
    detect_spread_mode_from_frame,
    frame_has_historical_bid_ask,
    validate_dataset_spread,
)
from tradingbot.config.live import PRIMARY_SYMBOL


class EconomicsProvenance(str, Enum):
    OBSERVED_BROKER_EVIDENCE = "OBSERVED_BROKER_EVIDENCE"
    EXPLICIT_CONFIG = "EXPLICIT_CONFIG"
    OFFLINE_CATALOG = "OFFLINE_CATALOG"
    DATASET_METADATA = "DATASET_METADATA"
    UNKNOWN = "UNKNOWN"


class MappingStatus(str, Enum):
    MATCH = "MATCH"
    EXPLICIT_MAP = "EXPLICIT_MAP"
    UNKNOWN = "UNKNOWN"
    MISMATCH = "MISMATCH"
    MISSING_MAP = "MISSING_MAP"
    INVALID_MAP = "INVALID_MAP"


class CostEvidenceStatus(str, Enum):
    OBSERVED = "OBSERVED"
    MODELED = "MODELED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BROKER_RATE_ONLY = "BROKER_RATE_ONLY"
    MODELED_PROXY = "MODELED_PROXY"
    OBSERVED_ZERO_NOT_PROVEN = "OBSERVED_ZERO_NOT_PROVEN"
    VERIFIED_SCHEDULE = "VERIFIED_SCHEDULE"


METADATA_SUFFIX = ".metadata.json"
SCHEMA_VERSION = 1

LITEFINANCE_DEMO_EVIDENCE = "logs/operator_broker_evidence_demo_raw.json"
LITEFINANCE_REAL_EVIDENCE = "logs/operator_broker_evidence_raw.json"
LITEFINANCE_EVIDENCE_TIMESTAMP = "2026-09-02T18:31:37Z"

FORBIDDEN_SIDECAR_KEYS = frozenset(
    {
        "login",
        "password",
        "mt5_password",
        "mt5_login",
        "server_password",
        "token",
        "api_key",
        "credentials",
    }
)


class SidecarValidationError(Exception):
    """Sidecar validation failed — fail closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def observed_litefinance_xauusd_i_economics() -> dict[str, Any]:
    """Economics from operator evidence — OBSERVED_BROKER_EVIDENCE only for XAUUSD_i."""
    return {
        "contract_size": 100.0,
        "point": 0.01,
        "digits": 2,
        "tick_size": 0.01,
        "tick_value": 1.0,
        "tick_value_profit": 1.0,
        "tick_value_loss": 1.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "stops_level": 0,
        "freeze_level": 0,
        "execution": "Market",
        "calculation": "CFD",
    }


def validate_sidecar_no_credentials(data: dict[str, Any]) -> bool:
    """Return False if any forbidden credential key appears in sidecar payload."""

    def _walk(obj: Any, prefix: str = "") -> bool:
        if isinstance(obj, dict):
            for k, v in obj.items():
                key_lower = str(k).lower()
                if key_lower in FORBIDDEN_SIDECAR_KEYS or "password" in key_lower:
                    return False
                if not _walk(v, f"{prefix}.{k}"):
                    return False
        elif isinstance(obj, list):
            for item in obj:
                if not _walk(item, prefix):
                    return False
        return True

    return _walk(data)


def validate_sidecar_schema(data: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "sidecar_not_object"
    if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        return False, "unsupported_schema_version"
    if not validate_sidecar_no_credentials(data):
        return False, "credentials_in_sidecar"
    if not str(data.get("dataset_symbol", "")).strip():
        return False, "missing_dataset_symbol"
    return True, "ok"

_SYMBOL_TF_RE = re.compile(
    r"^(?P<symbol>XAUUSD(?:_i)?|GOLD|[A-Z]{6,})_(?P<tf>M\d+|H\d+|D\d+)(?:_(?P<suffix>.+))?$",
    re.IGNORECASE,
)


def metadata_path_for(parquet_path: str | Path) -> Path:
    p = Path(parquet_path)
    return p.with_name(p.stem + METADATA_SUFFIX)


def infer_symbol_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    m = _SYMBOL_TF_RE.match(stem)
    if m:
        sym = m.group("symbol").upper()
        return "XAUUSD_i" if sym == "XAUUSD_I" else sym
    if stem.upper().startswith("XAUUSD"):
        return "XAUUSD" if "_I" not in stem.upper() else "XAUUSD_i"
    return None


def infer_timeframe_from_filename(filename: str) -> str | None:
    stem = Path(filename).stem
    m = _SYMBOL_TF_RE.match(stem)
    if not m:
        return None
    tf = m.group("tf").upper()
    return {"M5": "M5", "M15": "M15", "H4": "H4", "H1": "H1", "D1": "D1"}.get(tf, tf)


def _column_present(df: pd.DataFrame, *names: str) -> bool:
    cols = {str(c).lower() for c in df.columns}
    return any(n.lower() in cols for n in names)


def _datetime_range(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"start": None, "end": None, "timezone": "unknown", "row_count": 0}
    idx = df.index
    tz = getattr(idx, "tz", None)
    tz_label = str(tz) if tz is not None else ("naive" if isinstance(idx, pd.DatetimeIndex) else "unknown")
    start = idx[0]
    end = idx[-1]
    return {
        "start": str(start),
        "end": str(end),
        "timezone": tz_label,
        "row_count": int(len(df)),
    }


def _spread_provenance(df: pd.DataFrame) -> tuple[str, str]:
    if frame_has_historical_bid_ask(df):
        return SpreadMode.DATASET.value, "historical_bid_ask_columns"
    mode = detect_spread_mode_from_frame(df)
    if mode == SpreadMode.DATASET:
        return SpreadMode.UNKNOWN.value, "dataset_without_historical_bid_ask"
    if _column_present(df, "spread", "tick_spread"):
        return SpreadMode.PROXY.value, "spread_column_not_historical_bid_ask"
    if _column_present(df, "open", "high", "low", "close"):
        return SpreadMode.PROXY.value, "ohlc_only"
    return SpreadMode.UNKNOWN.value, "no_price_columns"


def _symbol_equivalence_status(dataset_symbol: str | None, configured: str) -> str:
    """EV-EQ-01 helper — never claims equivalence without metadata proof."""
    if not dataset_symbol:
        return "UNKNOWN"
    if dataset_symbol == configured:
        return "MATCHING_LABEL_ONLY"
    return "NOT_PROVEN"


@dataclass
class DatasetMetadata:
    schema_version: int = SCHEMA_VERSION
    dataset_symbol: str = ""
    configured_instrument_symbol: str = PRIMARY_SYMBOL
    dataset_symbol_map: dict[str, str] = field(default_factory=dict)
    mapping_status: str = MappingStatus.UNKNOWN.value
    economics_source: str = EconomicsProvenance.UNKNOWN.value
    economics_provenance: dict[str, Any] = field(default_factory=dict)
    timeframe: str | None = None
    datetime_range: dict[str, Any] = field(default_factory=dict)
    spread_mode: str = SpreadMode.UNKNOWN.value
    spread_source: str = ""
    spread_status: str = CostEvidenceStatus.UNKNOWN.value
    commission_status: str = CostEvidenceStatus.UNKNOWN.value
    swap_status: str = CostEvidenceStatus.UNKNOWN.value
    slippage_status: str = CostEvidenceStatus.UNKNOWN.value
    historical_bid_ask_available: bool = False
    broker: str | None = None
    server: str | None = None
    server_environment: str | None = None
    account_environment: str | None = None
    evidence_timestamp: str | None = None
    source_artifact: str | None = None
    contract_size: float | None = None
    point: float | None = None
    digits: int | None = None
    tick_size: float | None = None
    tick_value: float | None = None
    tick_value_profit: float | None = None
    tick_value_loss: float | None = None
    volume_min: float | None = None
    volume_max: float | None = None
    volume_step: float | None = None
    stops_level: int | None = None
    freeze_level: int | None = None
    symbol_equivalence: str = "UNKNOWN"
    cost_completeness: str = CostCompleteness.UNKNOWN.value
    provenance_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DatasetMetadata:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


def load_dataset_metadata(parquet_path: str | Path) -> DatasetMetadata | None:
    meta_path = metadata_path_for(parquet_path)
    if not meta_path.is_file():
        return None
    raw = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    ok, reason = validate_sidecar_schema(raw)
    if not ok:
        raise SidecarValidationError("MALFORMED_SIDECAR", reason)
    return DatasetMetadata.from_dict(raw)


def save_dataset_metadata(parquet_path: str | Path, metadata: DatasetMetadata) -> Path:
    """Write sidecar metadata (explicit operator/tool action — not used during read-only audit)."""
    meta_path = metadata_path_for(parquet_path)
    meta_path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
    return meta_path


@dataclass
class DatasetAuditEntry:
    filename: str
    path: str
    row_count: int
    columns: list[str]
    inferred_symbol: str | None
    inferred_timeframe: str | None
    datetime_range: dict[str, Any]
    bid_present: bool
    ask_present: bool
    spread_column_present: bool
    ohlc_present: bool
    volume_present: bool
    tick_data_present: bool
    economics_metadata_present: bool
    metadata_sidecar_present: bool
    spread_mode: str
    spread_source: str
    mapping_status: str
    economics_provenance: str
    symbol_equivalence: str
    cost_completeness: str
    economics_fields: dict[str, Any] = field(default_factory=dict)
    commission: str = CostEvidenceStatus.UNKNOWN.value
    swap: str = CostEvidenceStatus.UNKNOWN.value
    slippage: str = CostEvidenceStatus.UNKNOWN.value

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_parquet_file(
    path: str | Path,
    *,
    configured_symbol: str = PRIMARY_SYMBOL,
    dataset_symbol_map: dict[str, str] | None = None,
) -> DatasetAuditEntry:
    """Read-only parquet audit — does not modify the dataset."""
    p = Path(path)
    df = pd.read_parquet(p)
    inferred_sym = infer_symbol_from_filename(p.name)
    inferred_tf = infer_timeframe_from_filename(p.name)
    sidecar = load_dataset_metadata(p)

    bid = _column_present(df, "bid", "bid_price")
    ask = _column_present(df, "ask", "ask_price")
    spread_col = _column_present(df, "spread", "tick_spread")
    ohlc = _column_present(df, "open", "high", "low", "close")
    volume = _column_present(df, "volume", "tick_volume", "real_volume")
    tick_data = bid and ask

    spread_mode, spread_source = _spread_provenance(df)
    spread_val = validate_dataset_spread(df)
    spread_mode = spread_val.spread_mode.value
    spread_source = spread_val.spread_source

    if sidecar is not None:
        mapping_status = sidecar.mapping_status
        economics_prov = sidecar.economics_source
        sym_eq = sidecar.symbol_equivalence
        cost_comp = sidecar.cost_completeness
        spread_mode = sidecar.spread_mode or spread_mode
        spread_source = sidecar.spread_source or spread_source
        commission = sidecar.commission_status
        swap = sidecar.swap_status
        slippage = sidecar.slippage_status
        econ_fields = {
            k: getattr(sidecar, k)
            for k in (
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
            )
            if getattr(sidecar, k, None) is not None
        }
    else:
        econ_fields = {}
        commission = CostEvidenceStatus.UNKNOWN.value
        swap = CostEvidenceStatus.UNKNOWN.value
        slippage = CostEvidenceStatus.UNKNOWN.value
        ds_sym = inferred_sym or ""
        explicit = (dataset_symbol_map or {}).get(ds_sym)
        if explicit:
            mapping_status = MappingStatus.EXPLICIT_MAP.value
        elif ds_sym and ds_sym == configured_symbol:
            mapping_status = MappingStatus.MATCH.value
        elif ds_sym and ds_sym != configured_symbol:
            mapping_status = MappingStatus.UNKNOWN.value
        else:
            mapping_status = MappingStatus.UNKNOWN.value
        economics_prov = EconomicsProvenance.UNKNOWN.value
        sym_eq = _symbol_equivalence_status(inferred_sym, configured_symbol)
        cost_comp = CostCompleteness.UNKNOWN.value

    return DatasetAuditEntry(
        filename=p.name,
        path=str(p.resolve()),
        row_count=len(df),
        columns=[str(c) for c in df.columns],
        inferred_symbol=inferred_sym,
        inferred_timeframe=inferred_tf,
        datetime_range=_datetime_range(df),
        bid_present=bid,
        ask_present=ask,
        spread_column_present=spread_col,
        ohlc_present=ohlc,
        volume_present=volume,
        tick_data_present=tick_data,
        economics_metadata_present=bool(econ_fields),
        metadata_sidecar_present=sidecar is not None,
        spread_mode=spread_mode,
        spread_source=spread_source,
        mapping_status=mapping_status,
        economics_provenance=economics_prov,
        symbol_equivalence=sym_eq,
        cost_completeness=cost_comp,
        economics_fields=econ_fields,
        commission=commission,
        swap=swap,
        slippage=slippage,
    )


def discover_backtest_parquet_dirs(base_dir: str | Path | None = None) -> list[Path]:
    root = Path(base_dir or Path.cwd())
    dirs = [root / "data" / "backtest"]
    cache = root / "data" / "cache"
    if cache.is_dir():
        dirs.append(cache)
    data_root = root / "data"
    if data_root.is_dir():
        dirs.append(data_root)
    return [d for d in dirs if d.is_dir()]


def audit_backtest_datasets(
    *,
    base_dir: str | Path | None = None,
    configured_symbol: str = PRIMARY_SYMBOL,
    dataset_symbol_map: dict[str, str] | None = None,
) -> list[DatasetAuditEntry]:
    """Audit all *.parquet under known backtest cache locations (read-only)."""
    root = Path(base_dir or Path.cwd())
    seen: set[str] = set()
    entries: list[DatasetAuditEntry] = []
    for directory in discover_backtest_parquet_dirs(root):
        for path in sorted(directory.glob("*.parquet")):
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            entries.append(
                audit_parquet_file(
                    path,
                    configured_symbol=configured_symbol,
                    dataset_symbol_map=dataset_symbol_map,
                )
            )
    return entries


def write_audit_report(
    entries: list[DatasetAuditEntry],
    output_path: str | Path,
    *,
    generated_at: str | None = None,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "dataset_count": len(entries),
        "historical_bid_ask_available": any(e.bid_present and e.ask_present for e in entries),
        "sidecar_count": sum(1 for e in entries if e.metadata_sidecar_present),
        "datasets": [e.to_dict() for e in entries],
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


def compute_dataset_cost_status(
    *,
    spread_mode: str,
    commission_status: str = "UNKNOWN",
    swap_status: str = "UNKNOWN",
    slippage_status: str = "UNKNOWN",
) -> dict[str, str]:
    """Deterministic per-dataset cost component status."""
    spread_status = (
        CostEvidenceStatus.OBSERVED.value
        if spread_mode == SpreadMode.DATASET.value
        else CostEvidenceStatus.MODELED.value
        if spread_mode == SpreadMode.PROXY.value
        else CostEvidenceStatus.UNKNOWN.value
    )
    statuses = {
        "spread_status": spread_status,
        "commission_status": commission_status,
        "swap_status": swap_status,
        "slippage_status": slippage_status,
    }
    incomplete = {
        CostEvidenceStatus.UNKNOWN.value,
        CostEvidenceStatus.BROKER_RATE_ONLY.value,
        CostEvidenceStatus.MODELED_PROXY.value,
        CostEvidenceStatus.OBSERVED_ZERO_NOT_PROVEN.value,
        CostEvidenceStatus.VERIFIED_SCHEDULE.value,
    }
    unknowns = sum(1 for v in statuses.values() if v in incomplete)
    modeled = sum(
        1
        for v in statuses.values()
        if v
        in (
            CostEvidenceStatus.MODELED.value,
            CostEvidenceStatus.MODELED_PROXY.value,
            CostEvidenceStatus.OBSERVED.value,
        )
    )
    if unknowns == 0:
        completeness = CostCompleteness.COMPLETE.value
    elif modeled > 0:
        completeness = CostCompleteness.PARTIAL.value
    else:
        completeness = CostCompleteness.UNKNOWN.value
    return {**statuses, "cost_completeness": completeness}


def validate_sidecar_against_parquet(
    metadata: DatasetMetadata,
    df: pd.DataFrame,
    parquet_path: str | Path,
) -> tuple[bool, str]:
    """Fail closed on symbol mismatch or economics inconsistency with frame."""
    inferred = infer_symbol_from_filename(Path(parquet_path).name)
    ds_sym = metadata.dataset_symbol or inferred or ""
    if inferred and metadata.dataset_symbol and inferred != metadata.dataset_symbol:
        return False, f"sidecar_symbol_mismatch:{metadata.dataset_symbol}!={inferred}"

    spread = validate_dataset_spread(df, digits=metadata.digits, point=metadata.point)
    if metadata.spread_mode == SpreadMode.DATASET.value and spread.spread_mode != SpreadMode.DATASET:
        return False, "sidecar_claims_dataset_spread_but_frame_lacks_bid_ask"
    if spread.spread_mode == SpreadMode.DATASET and metadata.spread_mode != SpreadMode.DATASET.value:
        return False, "frame_has_bid_ask_but_sidecar_not_dataset_mode"

    if metadata.mapping_status == MappingStatus.EXPLICIT_MAP.value:
        explicit = metadata.dataset_symbol_map.get(ds_sym)
        if not explicit:
            return False, "explicit_map_status_without_map_entry"

    if metadata.dataset_symbol_map:
        from tradingbot.backtest.dataset_contract import InstrumentContractError, validate_dataset_symbol_map

        try:
            validate_dataset_symbol_map(
                metadata.dataset_symbol_map,
                configured_symbol=metadata.configured_instrument_symbol or PRIMARY_SYMBOL,
            )
        except InstrumentContractError as exc:
            return False, f"invalid_sidecar_map:{exc.message}"

    return True, "ok"


def build_sidecar_for_parquet(
    path: str | Path,
    *,
    configured_symbol: str = PRIMARY_SYMBOL,
) -> DatasetMetadata:
    """
    Build defensible sidecar metadata for a parquet file.

    XAUUSD_i: OBSERVED_BROKER_EVIDENCE from LiteFinance operator artifacts.
    XAUUSD: economics UNKNOWN, mapping UNKNOWN — never silent equivalence.
    """
    p = Path(path)
    df = pd.read_parquet(p)
    inferred_sym = infer_symbol_from_filename(p.name) or ""
    inferred_tf = infer_timeframe_from_filename(p.name)
    spread_val = validate_dataset_spread(df)
    spread_mode_value = spread_val.spread_mode.value
    spread_source_value = spread_val.spread_source
    if spread_val.spread_mode == SpreadMode.DATASET and not frame_has_historical_bid_ask(df):
        spread_mode_value = SpreadMode.PROXY.value
        spread_source_value = "dataset_claim_without_historical_bid_ask"
    dt_range = _datetime_range(df)
    cost = compute_dataset_cost_status(
        spread_mode=spread_mode_value,
        commission_status=CostEvidenceStatus.UNKNOWN.value,
        swap_status=CostEvidenceStatus.UNKNOWN.value,
        slippage_status=CostEvidenceStatus.UNKNOWN.value,
    )

    meta = DatasetMetadata(
        dataset_symbol=inferred_sym,
        configured_instrument_symbol=configured_symbol,
        timeframe=inferred_tf,
        datetime_range=dt_range,
        spread_mode=spread_mode_value,
        spread_source=spread_source_value,
        spread_status=cost["spread_status"],
        commission_status=cost["commission_status"],
        swap_status=cost["swap_status"],
        slippage_status=cost["slippage_status"],
        cost_completeness=cost["cost_completeness"],
        historical_bid_ask_available=frame_has_historical_bid_ask(df),
    )

    if inferred_sym == "XAUUSD_i":
        econ = observed_litefinance_xauusd_i_economics()
        meta.mapping_status = MappingStatus.MATCH.value
        meta.symbol_equivalence = "MATCHING_LABEL_ONLY"
        meta.economics_source = EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value
        meta.economics_provenance = {
            "source": EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value,
            "artifact": LITEFINANCE_DEMO_EVIDENCE,
            "note": "LiteFinance Demo/Real XAUUSD_i spec — not applied to bare XAUUSD datasets",
        }
        meta.broker = "LiteFinance"
        meta.server = "LiteFinance-MT5-Demo"
        meta.server_environment = "LiteFinance-MT5-Demo"
        meta.account_environment = "DEMO"
        meta.evidence_timestamp = LITEFINANCE_EVIDENCE_TIMESTAMP
        meta.source_artifact = LITEFINANCE_DEMO_EVIDENCE
        for k, v in econ.items():
            if hasattr(meta, k):
                setattr(meta, k, v)
        meta.provenance_summary = (
            "XAUUSD_i label match; OBSERVED_BROKER_EVIDENCE economics; spread "
            f"{spread_val.spread_mode.value}; EV-EQ-01 NOT_PROVEN for bare XAUUSD"
        )
    elif inferred_sym == "XAUUSD":
        meta.mapping_status = MappingStatus.UNKNOWN.value
        meta.symbol_equivalence = "NOT_PROVEN"
        meta.economics_source = EconomicsProvenance.UNKNOWN.value
        meta.provenance_summary = (
            "Bare XAUUSD label — no economics attached; mapping to XAUUSD_i NOT_PROVEN (EV-EQ-01 open)"
        )
    else:
        meta.mapping_status = MappingStatus.UNKNOWN.value
        meta.provenance_summary = "Unknown symbol label — economics and mapping UNKNOWN"

    return meta


def deploy_defensible_sidecars(
    *,
    base_dir: str | Path | None = None,
    configured_symbol: str = PRIMARY_SYMBOL,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Write `.metadata.json` sidecars for all audited parquet datasets.

    Does not modify parquet files. XAUUSD datasets never receive XAUUSD_i economics.
    """
    entries = audit_backtest_datasets(base_dir=base_dir, configured_symbol=configured_symbol)
    created: list[str] = []
    skipped: list[str] = []
    for entry in entries:
        path = Path(entry.path)
        if entry.metadata_sidecar_present and not dry_run:
            skipped.append(entry.filename)
            continue
        meta = build_sidecar_for_parquet(path, configured_symbol=configured_symbol)
        if not dry_run:
            save_dataset_metadata(path, meta)
            created.append(str(metadata_path_for(path)))
        else:
            created.append(f"dry_run:{entry.filename}")
    return {
        "created_count": len(created),
        "skipped_existing": len(skipped),
        "created": created,
        "dry_run": dry_run,
    }


def _parse_parquet_time_bounds(path: Path) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """Best-effort UTC bounds from DatetimeIndex or time/time_msc columns."""
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None, None
    if df.empty:
        return None, None
    if isinstance(df.index, pd.DatetimeIndex):
        start = pd.Timestamp(df.index.min())
        end = pd.Timestamp(df.index.max())
    elif "time_msc" in {str(c).lower() for c in df.columns}:
        col = next(c for c in df.columns if str(c).lower() == "time_msc")
        start = pd.to_datetime(df[col].iloc[0], unit="ms", utc=True)
        end = pd.to_datetime(df[col].iloc[-1], unit="ms", utc=True)
    elif "time" in {str(c).lower() for c in df.columns}:
        col = next(c for c in df.columns if str(c).lower() == "time")
        series = df[col]
        # epoch seconds vs already-datetime
        if pd.api.types.is_numeric_dtype(series):
            start = pd.to_datetime(series.iloc[0], unit="s", utc=True)
            end = pd.to_datetime(series.iloc[-1], unit="s", utc=True)
        else:
            start = pd.to_datetime(series.iloc[0], utc=True)
            end = pd.to_datetime(series.iloc[-1], utc=True)
    else:
        return None, None
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    return start, end


# Phase 114/115 acquisition window — full-horizon historical bid/ask gate.
REQUIRED_HISTORICAL_BIDASK_START = pd.Timestamp("2023-02-26T15:40:00Z")
REQUIRED_HISTORICAL_BIDASK_END = pd.Timestamp("2026-09-07T20:10:00Z")
_M5_TIMEFRAMES = frozenset({"M5", "5M", "5MIN"})


def qualifies_as_complete_historical_m5_bidask(entry: DatasetAuditEntry) -> bool:
    """
    True only for M5 bar tapes with bid+ask that cover the Phase 114/115 horizon.

    Tick / partial / narrow-window bid+ask files may be inventoried but must NOT
    flip historical_bid_ask_available or spread COMPLETE.
    """
    if not (entry.bid_present and entry.ask_present):
        return False
    tf = str(entry.inferred_timeframe or "").upper()
    if tf not in _M5_TIMEFRAMES:
        return False
    start, end = _parse_parquet_time_bounds(Path(entry.path))
    if start is None or end is None:
        return False
    return start <= REQUIRED_HISTORICAL_BIDASK_START and end >= REQUIRED_HISTORICAL_BIDASK_END


def search_historical_bid_ask(*, base_dir: str | Path | None = None) -> dict[str, Any]:
    """Scan local parquet datasets for bid/ask columns — no MT5.

    ``bidask_datasets`` / ``bidask_dataset_count`` list any file with bid+ask columns.
    ``historical_bid_ask_available`` is True only when at least one file qualifies as
    full-horizon M5 historical bid/ask (Phase 114/115 window). Partial tick sidecars
    do not satisfy the gate.
    """
    entries = audit_backtest_datasets(base_dir=base_dir)
    bidask: list[dict[str, Any]] = []
    qualifying: list[dict[str, Any]] = []
    for e in entries:
        if not (e.bid_present and e.ask_present):
            continue
        row = {
            "filename": e.filename,
            "path": e.path,
            "rows": e.row_count,
            "inferred_timeframe": e.inferred_timeframe,
            "qualifies_full_horizon_m5": False,
        }
        if qualifies_as_complete_historical_m5_bidask(e):
            row["qualifies_full_horizon_m5"] = True
            qualifying.append(row)
        bidask.append(row)
    return {
        "historical_bid_ask_available": bool(qualifying),
        "dataset_count": len(entries),
        "bidask_dataset_count": len(bidask),
        "bidask_datasets": bidask,
        "full_horizon_m5_bidask_count": len(qualifying),
        "required_horizon": {
            "start": REQUIRED_HISTORICAL_BIDASK_START.isoformat(),
            "end": REQUIRED_HISTORICAL_BIDASK_END.isoformat(),
            "source": "phase114/phase115 ACQ_START_ISO/ACQ_END_ISO",
        },
    }


def apply_sidecar_to_backtest_config(cfg: Any, metadata: DatasetMetadata) -> None:
    """
    Merge sidecar provenance into BacktestConfig when safe.

    Explicit config fields take precedence — sidecar fills gaps only.
    Sidecar maps are validated fail-closed; invalid maps are not applied.
    """
    if metadata.dataset_symbol_map and not getattr(cfg, "dataset_symbol_map", None):
        from tradingbot.backtest.dataset_contract import validate_dataset_symbol_map

        configured = str(
            getattr(cfg, "configured_instrument_symbol", None)
            or metadata.configured_instrument_symbol
            or PRIMARY_SYMBOL
        )
        validate_dataset_symbol_map(metadata.dataset_symbol_map, configured_symbol=configured)
        cfg.dataset_symbol_map = dict(metadata.dataset_symbol_map)

    for field_name, sidecar_val in (
        ("commission_status", metadata.commission_status),
        ("swap_status", metadata.swap_status),
        ("slippage_status", metadata.slippage_status),
    ):
        current = str(getattr(cfg, field_name, "UNKNOWN")).upper()
        sidecar_upper = str(sidecar_val).upper()
        if current == "UNKNOWN" and sidecar_upper != "UNKNOWN":
            setattr(cfg, field_name, sidecar_upper)

    if metadata.spread_mode and str(getattr(cfg, "spread_mode", "AUTO")).upper() == "AUTO":
        cfg.spread_mode = metadata.spread_mode

    if metadata.economics_source == EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value:
        broker_sym = metadata.configured_instrument_symbol
        if metadata.dataset_symbol == broker_sym or metadata.mapping_status == MappingStatus.MATCH.value:
            catalog_entry = {
                k: getattr(metadata, k)
                for k in (
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
                )
                if getattr(metadata, k, None) is not None
            }
            if catalog_entry:
                existing = dict(getattr(cfg, "broker_economics", None) or {})
                existing.setdefault(broker_sym, {}).update(catalog_entry)
                cfg.broker_economics = existing


def sidecar_economics_override(metadata: DatasetMetadata) -> dict[str, dict[str, Any]] | None:
    """Build economics_override dict for dataset_contract when sidecar is defensible."""
    if metadata.economics_source != EconomicsProvenance.OBSERVED_BROKER_EVIDENCE.value:
        return None
    if metadata.dataset_symbol != metadata.configured_instrument_symbol and metadata.mapping_status != MappingStatus.MATCH.value:
        return None
    sym = metadata.configured_instrument_symbol
    entry = {
        k: getattr(metadata, k)
        for k in (
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
        )
        if getattr(metadata, k, None) is not None
    }
    if not entry:
        return None
    return {sym: entry}

