"""Phase 116 - full-horizon XAUUSD_i data source research.

SOURCE / ACQUISITION-PLANNING ONLY. Does not download data, connect to MT5,
read .env, register accounts, or modify production. Does not start Phase 117.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_JSON,
    PHASE40_SETUPS_JSONL,
    _git_head,
    _utc_now,
)
from tradingbot.backtest.phase73_exit_research_gate import LEDGER_MD
from tradingbot.backtest.phase114_non_ohlc_acquisition_contract import CANONICAL_SYMBOL, LOGICAL_SYMBOL, TZ
from tradingbot.backtest.phase115_non_ohlc_data_acquisition import (
    ACQ_END_ISO,
    ACQ_START_ISO,
    EXPECTED_JSONL_SHA256,
    N_AMBIGUOUS_394,
    N_EVENTS,
    PHASE40_TS,
    PHASE115_JSON,
    file_sha256,
)

PHASE = "116"
PHASE116_JSON = "logs/phase116_data_source_research.json"
PHASE116_MD = "docs/PHASE116_DATA_SOURCE_RESEARCH.md"
OUTLIER_TS = "2026-01-21T15:40:00Z"
FIRST_EVENT = "2023-02-27T15:40:00Z"
LAST_EVENT = "2026-09-04T15:00:00Z"
LATEST_EXIT = "2026-09-04T15:30:00Z"
MAX_HOLD_MIN = 7320
IDENTITY_CLASSES = ("VERIFIED_XAUUSD_I", "XAUUSD_I_LIKELY_BUT_UNPROVEN", "GENERIC_XAUUSD", "UNKNOWN")
COVERAGE_BUCKETS = ("419/419 feasible", "350-418 feasible", "200-349 feasible", "<200 feasible", "UNKNOWN")
CHRONOLOGY_CLASSES = ("STRONG", "MODERATE", "WEAK", "INSUFFICIENT", "UNKNOWN")
GATE_CLASSES = ("READY_EXACT_XAUUSD_I", "READY_WITH_OPERATOR_ACTION", "PARTIALLY_READY", "NO_VALID_SOURCE_FOUND")
REJECT_SYMBOLS = frozenset({"XAUUSD", "GOLD", "GOLDUSD", "GOLD/USD", "XAU/USD", "XAUUSD.cash", "GC"})
REQUIRED_ARTIFACT_KEYS = (
    "phase", "timestamp_utc", "PHASE116_STATUS", "SOURCE_RESEARCH_STATUS",
    "ACQUISITION_PATH_STATUS", "candidates", "final_gate", "production_safety", "artifacts",
)


def classify_identity(*, exact_symbol: str | None, proven_xauusd_i: bool, generic: bool) -> str:
    if proven_xauusd_i and exact_symbol == CANONICAL_SYMBOL:
        return "VERIFIED_XAUUSD_I"
    if generic or (exact_symbol in REJECT_SYMBOLS):
        return "GENERIC_XAUUSD"
    if exact_symbol == CANONICAL_SYMBOL and not proven_xauusd_i:
        return "XAUUSD_I_LIKELY_BUT_UNPROVEN"
    return "UNKNOWN"


def coverage_bucket(n: int | None, *, unknown: bool = False) -> str:
    if unknown or n is None:
        return "UNKNOWN"
    if n >= N_EVENTS:
        return "419/419 feasible"
    if n >= 350:
        return "350-418 feasible"
    if n >= 200:
        return "200-349 feasible"
    return "<200 feasible"


def iso_le(a: str, b: str) -> bool:
    return a.replace("Z", "+00:00") <= b.replace("Z", "+00:00")


def iso_ge(a: str, b: str) -> bool:
    return a.replace("Z", "+00:00") >= b.replace("Z", "+00:00")


def full_horizon_covered(start: str | None, end: str | None) -> bool:
    if not start or not end:
        return False
    return iso_le(start, ACQ_START_ISO) and iso_ge(end, ACQ_END_ISO)


def outlier_in_range(start: str | None, end: str | None) -> bool | None:
    if not start or not end:
        return None
    return iso_le(start, OUTLIER_TS) and iso_ge(end, OUTLIER_TS)


def classify_chronology(*, bid: bool, ask: bool, quote_updates: bool, same_ms_preserved: bool, ohlc_only: bool, identity: str) -> str:
    if ohlc_only or not (bid and ask):
        return "INSUFFICIENT"
    if identity == "GENERIC_XAUUSD":
        return "MODERATE"
    if identity != "VERIFIED_XAUUSD_I":
        return "UNKNOWN" if identity == "UNKNOWN" else "WEAK"
    if quote_updates and same_ms_preserved:
        return "STRONG"
    if quote_updates:
        return "MODERATE"
    return "WEAK"


def substitution_verdict(kind: str) -> str:
    mapping = {
        "generic_XAUUSD": "REJECTED",
        "GOLD": "REJECTED",
        "futures_gold": "RESEARCH-ONLY",
        "another_broker_XAUUSD": "RESEARCH-ONLY",
        "synthetic_bid_ask": "REJECTED",
        "OHLC_derived_ticks": "REJECTED",
        "reconstructed_spread_without_bid_ask": "REJECTED",
        "interpolated_ticks": "REJECTED",
        "tester_generated_ticks": "REJECTED",
    }
    return mapping.get(kind, "UNKNOWN")


def acquisition_path_status(*, verified_full_horizon: bool, verified_method_unproven_coverage: bool, verified_partial_local: bool) -> str:
    if verified_full_horizon:
        return "READY_EXACT_XAUUSD_I"
    if verified_method_unproven_coverage:
        return "READY_WITH_OPERATOR_ACTION"
    if verified_partial_local:
        return "PARTIALLY_READY"
    return "NO_VALID_SOURCE_FOUND"


def _cand(spec: dict[str, Any]) -> dict[str, Any]:
    ident = classify_identity(exact_symbol=spec.get("exact_symbol"), proven_xauusd_i=bool(spec.get("proven_xauusd_i")), generic=bool(spec.get("generic")))
    start, end = spec.get("historical_start"), spec.get("historical_end")
    unknown_cov = spec.get("coverage_unknown", False)
    n = spec.get("n_events_feasible")
    chrono = classify_chronology(
        bid=bool(spec.get("bid")), ask=bool(spec.get("ask")), quote_updates=bool(spec.get("quote_updates")),
        same_ms_preserved=bool(spec.get("same_ms_preserved")), ohlc_only=bool(spec.get("ohlc_only")), identity=ident,
    )
    outlier = outlier_in_range(start, end)
    if unknown_cov:
        outlier = None
    return {
        "source_name": spec["source_name"], "provider": spec["provider"], "source_type": spec["source_type"],
        "XAUUSD_i_support": spec.get("XAUUSD_i_support"), "exact_symbol": spec.get("exact_symbol"),
        "identity_class": ident, "bid": bool(spec.get("bid")), "ask": bool(spec.get("ask")),
        "last": spec.get("last"), "volume": spec.get("volume"), "flags": spec.get("flags"),
        "timestamp_resolution": spec.get("timestamp_resolution"), "timezone": spec.get("timezone", TZ),
        "historical_start": start, "historical_end": end,
        "coverage_start": start if not unknown_cov else None, "coverage_end": end if not unknown_cov else None,
        "uncovered_intervals": spec.get("uncovered_intervals"), "years": spec.get("years"),
        "export_api_method": spec.get("export_api_method"), "authentication_required": bool(spec.get("authentication_required")),
        "cost_if_known": spec.get("cost_if_known"), "retention": spec.get("retention"),
        "reproducibility": spec.get("reproducibility"), "provenance_quality": spec.get("provenance_quality"),
        "broker_feed_fidelity": spec.get("broker_feed_fidelity"), "suitability_for_this_project": spec.get("suitability"),
        "known_limitations": spec.get("known_limitations"), "quote_updates": bool(spec.get("quote_updates")),
        "trade_ticks": spec.get("trade_ticks"), "duplicate_timestamps_preserved": spec.get("same_ms_preserved"),
        "sequence_information": spec.get("sequence_information"),
        "full_horizon": False if unknown_cov else full_horizon_covered(start, end),
        "event_coverage_class": coverage_bucket(n, unknown=unknown_cov),
        "n_events_feasible": None if unknown_cov else n,
        "outlier_31_84R_in_documented_range": outlier, "chronology_class": chrono,
        "canonical_eligible": ident == "VERIFIED_XAUUSD_I" and not spec.get("insufficient"),
        "downloaded_in_phase116": False, "mt5_used": False, "evidence_kind": spec.get("evidence_kind"),
    }


def _s(name: str, provider: str, stype: str, **kw: Any) -> dict[str, Any]:
    row = {"source_name": name, "provider": provider, "source_type": stype, "timezone": TZ}
    row.update(kw)
    return row

def catalog(p115: dict[str, Any]) -> list[dict[str, Any]]:
    n_local = int(p115.get("TICK_COMPLETE_LIFECYCLE_EVENTS") or 0)
    local_start = ((p115.get("ticks") or {}).get("first_timestamp")) or "2026-08-13T20:20:00Z"
    local_end = ((p115.get("ticks") or {}).get("last_timestamp")) or "2026-09-01T17:52:29Z"
    specs = [
        _s("LOCAL_XAUUSD_I_TICK_SIDECARS", "in-repo Phase 27.26 / 38 artifacts (LiteFinance-origin)", "existing project artifact",
           XAUUSD_i_support="YES", exact_symbol=CANONICAL_SYMBOL, proven_xauusd_i=True, generic=False, bid=True, ask=True,
           last="partial", volume=True, flags="partial", timestamp_resolution="millisecond",
           historical_start=local_start, historical_end=local_end,
           uncovered_intervals=[ACQ_START_ISO + " -> " + local_start, local_end + " -> " + ACQ_END_ISO],
           years={"2023": False, "2024": False, "2025": False, "2026": "Aug 13-Sep 1 sidecar only"},
           export_api_method="already on disk; Phase 115 ingested", authentication_required=False, cost_if_known="none",
           retention="files present", reproducibility="HIGH (hashed local files)",
           provenance_quality="HIGH for XAUUSD_i identity; LOW for horizon",
           broker_feed_fidelity="exact LiteFinance XAUUSD_i (prior export)", suitability="insufficient; 3/419 lifecycles",
           known_limitations="Does not cover 2023-early 2026; +31.84R uncovered", quote_updates=True, trade_ticks="optional last",
           same_ms_preserved=True, sequence_information="row order in parquet", n_events_feasible=n_local, insufficient=True,
           evidence_kind="FROZEN-DATA-EVIDENCE Phase115"),
        _s("LITEFINANCE_MT5_COPY_TICKS_RANGE", "LiteFinance CLASSIC via MetaTrader 5 Python API", "broker API",
           XAUUSD_i_support="YES (symbol name)", exact_symbol=CANONICAL_SYMBOL, proven_xauusd_i=True, generic=False,
           bid=True, ask=True, last=True, volume=True, flags=True, timestamp_resolution="millisecond (time_msc)",
           coverage_unknown=True, uncovered_intervals="UNKNOWN until history-server retention is measured",
           years={"2023": "UNKNOWN", "2024": "UNKNOWN", "2025": "UNKNOWN", "2026": "partial locally observed"},
           export_api_method="copy_ticks_range XAUUSD_i; FORBIDDEN in this phase", authentication_required=True,
           cost_if_known="included with CLASSIC account; not purchased here",
           retention="broker history server; unpublished by LiteFinance; MetaQuotes monthly TKC after sync",
           reproducibility="HIGH if the same server retains the same ticks",
           provenance_quality="HIGHEST for identity; coverage unproven", broker_feed_fidelity="exact LiteFinance CFD feed",
           suitability="preferred future path IF retention covers the window",
           known_limitations="Phase 37/38 gold copy_ticks hung/resource-bound; this phase must not connect",
           quote_updates=True, trade_ticks=True, same_ms_preserved=True, sequence_information="MqlTick flags + time_msc",
           evidence_kind="CODE-EVIDENCE + PUBLIC-DOC MetaQuotes CopyTicks"),
        _s("LITEFINANCE_MT5_SYMBOLS_TICKS_TAB_EXPORT", "LiteFinance CLASSIC MetaTrader 5 terminal UI", "broker terminal history export",
           XAUUSD_i_support="YES if Market Watch symbol is XAUUSD_i", exact_symbol=CANONICAL_SYMBOL, proven_xauusd_i=True,
           generic=False, bid=True, ask=True, last=True, volume=True, flags=True, timestamp_resolution="millisecond",
           coverage_unknown=True, uncovered_intervals="UNKNOWN (Request downloads only what the server has)",
           years={"2023": "UNKNOWN", "2024": "UNKNOWN", "2025": "UNKNOWN", "2026": "UNKNOWN"},
           export_api_method="Symbols Ctrl+U -> XAUUSD_i -> Ticks -> Request -> Export; operator-only",
           authentication_required=True, cost_if_known="included with account",
           retention="same history server as copy_ticks_range", reproducibility="HIGH if exported files are hashed",
           provenance_quality="HIGHEST if files are labeled XAUUSD_i from CLASSIC",
           broker_feed_fidelity="exact LiteFinance CFD feed",
           suitability="preferred operator action; this process must not open the terminal",
           known_limitations="UI sync can take hours for gold; generated tester ticks must not be used",
           quote_updates=True, trade_ticks=True, same_ms_preserved=True, sequence_information="exported tick rows",
           evidence_kind="PUBLIC-DOC MT5 Symbols/Ticks tab"),
        _s("LITEFINANCE_TKC_TICK_CACHE", "MetaTrader 5 local bases/{server}/ticks/XAUUSD_i/*.tkc", "broker data archive (local terminal cache)",
           XAUUSD_i_support="YES if folder name is XAUUSD_i", exact_symbol=CANONICAL_SYMBOL, proven_xauusd_i=True, generic=False,
           bid=True, ask=True, last=True, volume=True, flags=True, timestamp_resolution="millisecond", coverage_unknown=True,
           uncovered_intervals="UNKNOWN; not scanned (would inspect the broker terminal tree)",
           years={"2023": "UNKNOWN", "2024": "UNKNOWN", "2025": "UNKNOWN", "2026": "UNKNOWN"},
           export_api_method="copy monthly TKC after an authorized sync; not parsed here", authentication_required=True,
           cost_if_known="none extra", retention="only months previously synchronized",
           reproducibility="MEDIUM (cache can be rebuilt from server)",
           provenance_quality="HIGH if path contains XAUUSD_i and CLASSIC server name",
           broker_feed_fidelity="exact LiteFinance once synced",
           suitability="operator export after sync; not inspected this phase",
           known_limitations="empty until the terminal downloads history; this phase does not walk AppData",
           quote_updates=True, trade_ticks=True, same_ms_preserved=True, sequence_information="TKC monthly files",
           evidence_kind="PUBLIC-DOC MetaQuotes tick storage layout"),
        _s("LITEFINANCE_SUPPORT_HISTORICAL_ARCHIVE", "LiteFinance support / back-office data request", "broker historical export / data archive",
           XAUUSD_i_support="POSSIBLE; not publicly catalogued", exact_symbol=CANONICAL_SYMBOL, proven_xauusd_i=False, generic=False,
           bid=True, ask=True, last="UNKNOWN", volume="UNKNOWN", flags="UNKNOWN", timestamp_resolution="UNKNOWN until files exist",
           coverage_unknown=True, uncovered_intervals="UNKNOWN; LiteFinance does not publish a tick-archive catalog",
           years={"2023": "UNKNOWN", "2024": "UNKNOWN", "2025": "UNKNOWN", "2026": "UNKNOWN"},
           export_api_method="operator support ticket requesting XAUUSD_i tick bid/ask for the window",
           authentication_required=True, cost_if_known="UNKNOWN; not purchased here", retention="unpublished",
           reproducibility="MEDIUM if they re-issue the same dump",
           provenance_quality="HIGH if dump is labeled XAUUSD_i from CLASSIC",
           broker_feed_fidelity="exact if they send the trading-server quotes", suitability="secondary operator path",
           known_limitations="may refuse, may send bars instead of ticks, may send logical XAUUSD",
           quote_updates=True, trade_ticks="UNKNOWN", same_ms_preserved=True, sequence_information="UNKNOWN",
           evidence_kind="INFERENCE; no public archive listing"),
        _s("DUKASCOPY_XAUUSD_TICKS", "Dukascopy Bank SA Historical Data Feed", "third-party market-data vendor",
           XAUUSD_i_support="NO", exact_symbol="XAUUSD", proven_xauusd_i=False, generic=True, bid=True, ask=True, last=False,
           volume=True, flags=False, timestamp_resolution="tick / millisecond class",
           historical_start="2003-05-05T00:01:03Z", historical_end="2026-09-07T20:10:00Z",
           uncovered_intervals="none vs acquisition window IF generic gold were accepted",
           years={"2023": True, "2024": True, "2025": True, "2026": True},
           export_api_method="Historical Data Export / dukascopy-node; NOT executed", authentication_required=False,
           cost_if_known="free public historical export", retention="tick archive from 2003-05-05", reproducibility="HIGH",
           provenance_quality="HIGH for Dukascopy XAUUSD; ZERO for XAUUSD_i",
           broker_feed_fidelity="generic ECN/spot gold - not LiteFinance",
           suitability="REJECTED as canonical; not proven equivalent",
           known_limitations="EV-EQ-01 NOT_PROVEN; different spread/quote path",
           quote_updates=True, trade_ticks=False, same_ms_preserved=True, sequence_information="bid/ask quote stream",
           n_events_feasible=N_EVENTS, insufficient=True, evidence_kind="PUBLIC-DOC dukascopy-node instrument xauusd"),
        _s("HISTDATA_XAUUSD", "HistData.com", "third-party market-data vendor",
           XAUUSD_i_support="NO", exact_symbol="XAU/USD", proven_xauusd_i=False, generic=True, bid=True, ask=True, last=False,
           volume="usually 0", flags=False, timestamp_resolution="millisecond claimed; some later months second-resolution",
           coverage_unknown=True, uncovered_intervals="timezone is EST-no-DST; full-horizon not measured here",
           years={"2023": "LIKELY", "2024": "LIKELY", "2025": "LIKELY", "2026": "LIKELY"},
           export_api_method="monthly ZIP ASCII ticks; NOT downloaded", authentication_required=False, cost_if_known="free",
           retention="monthly tick zips", reproducibility="MEDIUM", provenance_quality="generic XAU/USD only",
           broker_feed_fidelity="generic; not LiteFinance", suitability="REJECTED as canonical",
           known_limitations="EST-no-DST; duplicate timestamps; volume 0; not XAUUSD_i",
           quote_updates=True, trade_ticks=False, same_ms_preserved=True, sequence_information="published row order",
           insufficient=True, evidence_kind="PUBLIC-DOC HistData.com"),
        _s("COMEX_GC_FUTURES", "CME/COMEX gold futures vendors", "institutional/futures historical feed",
           XAUUSD_i_support="NO", exact_symbol="GC", proven_xauusd_i=False, generic=True, bid=True, ask=True,
           timestamp_resolution="exchange tick", coverage_unknown=True,
           uncovered_intervals="different instrument; session/contract rolls",
           years={"2023": True, "2024": True, "2025": True, "2026": True},
           export_api_method="paid vendor; NOT purchased", authentication_required=True, cost_if_known="paid (not quoted here)",
           retention="exchange history", reproducibility="HIGH for GC; irrelevant for XAUUSD_i",
           provenance_quality="futures, not CFD", broker_feed_fidelity="futures - not LiteFinance CFD",
           suitability="RESEARCH-ONLY; never canonical", known_limitations="contract rolls, different microstructure",
           quote_updates=True, trade_ticks=True, same_ms_preserved=True, sequence_information="exchange sequence",
           insufficient=True, evidence_kind="INFERENCE asset-class mismatch"),
        _s("MT5_TESTER_GENERATED_TICKS", "MetaTrader 5 Strategy Tester", "synthetic / OHLC-derived ticks",
           XAUUSD_i_support="N/A", exact_symbol=CANONICAL_SYMBOL, proven_xauusd_i=False, generic=False, bid=True, ask=True,
           ohlc_only=True, timestamp_resolution="generated inside M1 bars", coverage_unknown=True,
           uncovered_intervals="fabricated path order inside bars",
           years={"2023": "if M1 exists", "2024": "if M1 exists", "2025": "if M1 exists", "2026": "if M1 exists"},
           export_api_method="Every tick / Every tick based on real ticks fallback", authentication_required=True,
           cost_if_known="none", retention="n/a", reproducibility="HIGH and WRONG for chronology", provenance_quality="synthetic",
           broker_feed_fidelity="not observed quotes when generated from M1", suitability="REJECTED",
           known_limitations="MetaQuotes documents M1-generated ticks when real ticks missing",
           quote_updates=False, trade_ticks=False, same_ms_preserved=False, sequence_information="artificial OHLC walk",
           insufficient=True, evidence_kind="PUBLIC-DOC MetaTrader 5 tick generation help"),
        _s("IN_REPO_LOGICAL_XAUUSD_OHLC", "existing project files (XAUUSD_1h, ML candles)", "existing project artifact",
           XAUUSD_i_support="NO", exact_symbol=LOGICAL_SYMBOL, proven_xauusd_i=False, generic=True, bid=False, ask=False,
           ohlc_only=True, timestamp_resolution="bar", coverage_unknown=True, uncovered_intervals="not ticks",
           years={"2023": "bars only", "2024": "bars only", "2025": "bars only", "2026": "bars only"},
           export_api_method="already rejected in Phase 115", authentication_required=False, cost_if_known="none",
           retention="on disk", reproducibility="HIGH", provenance_quality="logical XAUUSD; EV-EQ-01 NOT_PROVEN",
           broker_feed_fidelity="unknown / not CLASSIC XAUUSD_i", suitability="REJECTED",
           known_limitations="OHLC cannot order fav vs adv inside M5", quote_updates=False, trade_ticks=False,
           same_ms_preserved=False, sequence_information="none", n_events_feasible=0, insufficient=True,
           evidence_kind="FROZEN-DATA-EVIDENCE Phase115 rejection"),
    ]
    return [_cand(s) for s in specs]


def rank_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ident_rank = {"VERIFIED_XAUUSD_I": 0, "XAUUSD_I_LIKELY_BUT_UNPROVEN": 1, "UNKNOWN": 2, "GENERIC_XAUUSD": 3}
    chrono_rank = {"STRONG": 0, "MODERATE": 1, "WEAK": 2, "UNKNOWN": 3, "INSUFFICIENT": 4}
    cov_rank = {"419/419 feasible": 0, "350-418 feasible": 1, "200-349 feasible": 2, "<200 feasible": 3, "UNKNOWN": 4}

    def key(r: dict[str, Any]) -> tuple:
        return (
            ident_rank[r["identity_class"]],
            0 if r.get("full_horizon") else 1,
            0 if r.get("bid") and r.get("ask") else 1,
            chrono_rank[r["chronology_class"]],
            0 if str(r.get("broker_feed_fidelity") or "").startswith("exact") else 1,
            cov_rank[r["event_coverage_class"]],
            0 if r.get("outlier_31_84R_in_documented_range") else 1,
            0 if str(r.get("reproducibility") or "").startswith("HIGH") else 1,
            r["source_name"],
        )

    ranked = sorted(rows, key=key)
    return [{"rank": i, "source_name": r["source_name"], "identity_class": r["identity_class"], "why_not_cheapness": True} for i, r in enumerate(ranked, 1)]


def options(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by = {r["source_name"]: r for r in rows}
    opts = [
        {"id": "OPTION_A", "title": "exact broker XAUUSD_i source",
         "sources": ["LITEFINANCE_MT5_COPY_TICKS_RANGE", "LITEFINANCE_MT5_SYMBOLS_TICKS_TAB_EXPORT", "LITEFINANCE_TKC_TICK_CACHE"],
         "identity": "VERIFIED_XAUUSD_I", "coverage": "UNKNOWN (history-server retention unpublished)", "valid": True, "executed_phase116": False},
        {"id": "OPTION_B", "title": "broker-provided historical export/API",
         "sources": ["LITEFINANCE_SUPPORT_HISTORICAL_ARCHIVE"],
         "identity": "XAUUSD_I_LIKELY_BUT_UNPROVEN until files arrive labeled XAUUSD_i", "coverage": "UNKNOWN", "valid": True, "executed_phase116": False},
    ]
    duk = by.get("DUKASCOPY_XAUUSD_TICKS") or {}
    if duk.get("identity_class") == "VERIFIED_XAUUSD_I":
        opts.append({"id": "OPTION_C", "title": "external source with documented XAUUSD_i equivalence", "sources": ["DUKASCOPY_XAUUSD_TICKS"], "valid": True})
    else:
        opts.append({"id": "OPTION_C", "title": "external source with documented XAUUSD_i equivalence", "sources": [], "valid": False,
                     "reason": "No third-party vendor documents XAUUSD_i identity or EV-EQ-01 equivalence."})
    return opts


def substitutions() -> list[dict[str, Any]]:
    kinds = [
        ("generic_XAUUSD", "generic XAUUSD"), ("GOLD", "GOLD / GOLDUSD"), ("futures_gold", "futures gold (GC)"),
        ("another_broker_XAUUSD", "another broker's XAUUSD"), ("synthetic_bid_ask", "synthetic bid/ask"),
        ("OHLC_derived_ticks", "OHLC-derived ticks"), ("reconstructed_spread_without_bid_ask", "reconstructed spread without bid/ask"),
        ("interpolated_ticks", "interpolated ticks"), ("tester_generated_ticks", "MT5 tester generated ticks"),
    ]
    return [{"kind": label, "code": code, "verdict": substitution_verdict(code)} for code, label in kinds]


def refined_contract() -> dict[str, Any]:
    return {
        "weakened_phase114": False,
        "required_fields": ["timestamp_utc", "bid", "ask"],
        "preferred_fields": ["last", "volume", "flags", "source"],
        "symbol": CANONICAL_SYMBOL, "logical_xauusd_forbidden": True, "timezone": TZ,
        "window": [ACQ_START_ISO, ACQ_END_ISO], "do_not_truncate_31_84R": True,
        "metadata": ["provider", "source_identifier", "symbol", "timezone", "timestamp_precision", "acquisition_timestamp", "raw_file_hash", "normalization_version"],
        "joins": "tick_timestamp <= state_timestamp; same-bar SL not assumed favorable-first",
        "evidence_kind": "INFERENCE over Phase114 contract; not weakened",
    }

def _frozen_integrity(root: Path) -> dict[str, Any]:
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    sha = file_sha256(root / PHASE40_SETUPS_JSONL)
    ts = p40.get("timestamp_utc")
    fp = p40.get("tape_fingerprint")
    ok = ts == PHASE40_TS and fp == FROZEN and sha == EXPECTED_JSONL_SHA256
    return {
        "ok": ok, "FROZEN_PHASE40_TIMESTAMP": ts, "FROZEN_PHASE40_FINGERPRINT": fp, "FROZEN_PHASE40_SHA256": sha,
        "expected_timestamp": PHASE40_TS, "expected_fingerprint": FROZEN, "expected_sha256": EXPECTED_JSONL_SHA256,
        "jsonl_byte_identical": sha == EXPECTED_JSONL_SHA256, "repaired": False,
    }


def _patch_truth(root: Path, payload: dict[str, Any]) -> None:
    line = (
        "Phase 116 (`docs/PHASE116_DATA_SOURCE_RESEARCH.md`) is research-only source planning for "
        "full-horizon XAUUSD_i ticks. It does not download data, connect to MT5, read .env, "
        "modify production, or start Phase 117."
    )
    src = root / "docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md"
    text = src.read_text(encoding="utf-8")
    text = text.replace("Phase 116 was not started.", "Phase 116 is source-planning only; data was not downloaded.")
    if line not in text:
        marker = "Phase 115 (`docs/PHASE115_NON_OHLC_DATA_ACQUISITION.md`)"
        idx = text.find(marker)
        if idx != -1:
            end = text.find("\n\n", idx)
            text = (text[:end] + "\n\n" + line + text[end:]) if end != -1 else text.rstrip() + "\n\n" + line + "\n"
    src.write_text(text, encoding="utf-8")
    bnd = root / "docs_v2/01_truth/PRODUCTION_RESEARCH_BOUNDARY.md"
    btext = bnd.read_text(encoding="utf-8")
    extra = "`tradingbot/backtest/phase116_data_source_research.py` -- **RESEARCH_ONLY** source planning; no download; no MT5.\n"
    needle = "`tradingbot/backtest/phase115_non_ohlc_data_acquisition.py`"
    if "phase116_data_source_research.py" not in btext and needle in btext:
        insert_at = btext.find("\n", btext.find(needle))
        if insert_at != -1:
            bnd.write_text(btext[: insert_at + 1] + extra + btext[insert_at + 1 :], encoding="utf-8")
    ku = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    ktext = ku.read_text(encoding="utf-8")
    ktext = ktext.replace("| Phase 116 started | **NO** |", "| Phase 116 started | **YES** |")
    block = f"""

## Non-OHLC source research (Phase 116)

| Claim | Status |
|---|---|
| PHASE116_STATUS | **{payload.get("PHASE116_STATUS")}** |
| SOURCE_RESEARCH_STATUS | **{payload.get("SOURCE_RESEARCH_STATUS")}** |
| ACQUISITION_PATH_STATUS | **{payload.get("ACQUISITION_PATH_STATUS")}** |
| DATA_ACQUIRED | **NO** |
| Canonical symbol | **XAUUSD_i** (XAUUSD not a substitute) |
| EV-EQ-01 | **NOT_PROVEN** |
| MT5 used | **NO** |
| ENV read | **NO** |
| Exit design implemented | **NO** |
| FINAL_GATE | **{payload.get("FINAL_GATE")}** |
| Phase 117 started | **NO** |
"""
    marker = "## Non-OHLC source research (Phase 116)"
    if marker in ktext:
        start = ktext.find(marker)
        ku.write_text(ktext[:start].rstrip() + block, encoding="utf-8")
    else:
        ku.write_text(ktext.rstrip() + block, encoding="utf-8")


def append_ledger(root: Path, payload: dict[str, Any]) -> None:
    path = root / LEDGER_MD
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Research Ledger\n"
    today = datetime.now(timezone.utc).date().isoformat()
    extra = [
        "", "## Phase 116", "",
        "| ID | Date | Phase | Data range | N | Baseline | Result | OOS touched | Decision from OOS | Next |",
        "|---|---|---|---|---|---|---|---|---|---|",
        f"| H116-01 | {today} | 116 | frozen Phase38/40 | 419 | event tape 419 resolved | {payload.get('ACQUISITION_PATH_STATUS')} | reported | NO | source plan; not acquired |",
        "",
        f"**ACQUISITION_PATH_STATUS:** `{payload.get('ACQUISITION_PATH_STATUS')}`",
        f"**PHASE117_RECOMMENDATION:** `{payload.get('PHASE117_RECOMMENDATION')}` (not started).",
        "",
    ]
    marker = "## Phase 116"
    if marker in existing:
        start = existing.find(marker)
        path.write_text(existing[:start].rstrip() + "\n" + "\n".join(extra), encoding="utf-8")
    else:
        path.write_text(existing.rstrip() + "\n" + "\n".join(extra), encoding="utf-8")


def _write_md(root: Path, payload: dict[str, Any]) -> None:
    keys = [
        "PHASE116_STATUS", "SOURCE_RESEARCH_STATUS", "ACQUISITION_PATH_STATUS", "PRIMARY_SOURCE", "SECONDARY_SOURCE",
        "FALLBACK_SOURCE", "BLOCKER", "VERIFIED_XAUUSD_I_SOURCES", "FULL_HORIZON_SOURCES", "BID_ASK_SOURCES",
        "CHRONOLOGY_CAPABLE_SOURCES", "CANDIDATE_419_EVENT_COVERAGE", "OUTLIER_31_84R_COVERAGE",
        "C_VS_D_VS_E_VS_F_FEASIBILITY", "EXACT_BROKER_FEED_STATUS", "ALTERNATIVE_FEED_STATUS", "GENERIC_XAUUSD_STATUS",
        "RECOMMENDED_ACQUISITION_PATH", "OPERATOR_ACTION_REQUIRED", "PHASE117_RECOMMENDATION", "TESTS_PHASE116",
        "REGRESSION_40_43_57_63_68_116", "FROZEN_PHASE40_TIMESTAMP", "FROZEN_PHASE40_FINGERPRINT", "FROZEN_PHASE40_SHA256",
    ]
    lines = [
        "# Phase 116 -- Full-Horizon XAUUSD_i Data Source Research",
        "",
        "SOURCE-PLANNING over PUBLIC-DOC-EVIDENCE, CODE-EVIDENCE, and Phase 115 FROZEN-DATA-EVIDENCE.",
        "No remote acquisition. No MT5.",
        "",
    ]
    for k in keys:
        lines.append(f"{k} = {payload.get(k)}")
        if k in {"ACQUISITION_PATH_STATUS", "BLOCKER", "CHRONOLOGY_CAPABLE_SOURCES", "C_VS_D_VS_E_VS_F_FEASIBILITY", "GENERIC_XAUUSD_STATUS", "PHASE117_RECOMMENDATION", "REGRESSION_40_43_57_63_68_116"}:
            lines.append("")
    lines.extend([
        "## Safety", "",
        "DATA_ACQUIRED = false. MT5 not used. Credentials not read. Phase 114 contract not weakened.",
        "Generic XAUUSD / GOLD / futures / synthetic / OHLC ticks are not canonical.",
        "", "Phase 117 was not started.", "",
    ])
    (root / PHASE116_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_test_results(root: Path, phase116: dict[str, Any], regression: dict[str, Any]) -> None:
    path = root / PHASE116_JSON
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["TESTS_PHASE116"] = phase116
    payload["REGRESSION_40_43_57_63_68_116"] = regression
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    md = root / PHASE116_MD
    text = md.read_text(encoding="utf-8")
    text = text.replace("TESTS_PHASE116 = None", f"TESTS_PHASE116 = {phase116}")
    text = text.replace("REGRESSION_40_43_57_63_68_116 = None", f"REGRESSION_40_43_57_63_68_116 = {regression}")
    md.write_text(text, encoding="utf-8")


def run_phase116_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    frozen = _frozen_integrity(root)
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p115 = _safe_load_json(root / PHASE115_JSON) or {}
    rows = catalog(p115)
    ranking = rank_candidates(rows)
    opts = options(rows)
    subs = substitutions()
    verified = [r["source_name"] for r in rows if r["identity_class"] == "VERIFIED_XAUUSD_I"]
    full_h = [r["source_name"] for r in rows if r.get("full_horizon") and r["identity_class"] == "VERIFIED_XAUUSD_I"]
    generic_full = [r["source_name"] for r in rows if r.get("full_horizon") and r["identity_class"] == "GENERIC_XAUUSD"]
    bidask = [r["source_name"] for r in rows if r.get("bid") and r.get("ask")]
    chrono_ok = [r["source_name"] for r in rows if r["chronology_class"] in {"STRONG", "MODERATE"}]
    cov_map = {r["source_name"]: r["event_coverage_class"] for r in rows}
    outlier_map = {r["source_name"]: r["outlier_31_84R_in_documented_range"] for r in rows}
    gate = acquisition_path_status(verified_full_horizon=bool(full_h), verified_method_unproven_coverage=True, verified_partial_local=True)
    status = "PASS" if frozen.get("ok") else "FAIL"
    if not frozen.get("ok"):
        gate = "NO_VALID_SOURCE_FOUND"
    blocker = (
        "LiteFinance history-server tick retention for 2023-02-26Z-2026-09-07Z is unpublished; "
        "this phase cannot connect to MT5 to measure it; local verified ticks cover 3/419 and miss +31.84R."
    )
    nxt = "OPERATOR_SOURCE_RESOLUTION_RESEARCH"
    payload: dict[str, Any] = {
        "phase": PHASE, "timestamp_utc": _utc_now(), "schema_version": 1, "research_only": True, "status": status,
        "PHASE116_STATUS": status, "SOURCE_RESEARCH_STATUS": "COMPLETE", "ACQUISITION_PATH_STATUS": gate,
        "PRIMARY_SOURCE": "LITEFINANCE_MT5_SYMBOLS_TICKS_TAB_EXPORT",
        "SECONDARY_SOURCE": "LITEFINANCE_MT5_COPY_TICKS_RANGE",
        "FALLBACK_SOURCE": "LITEFINANCE_SUPPORT_HISTORICAL_ARCHIVE",
        "BLOCKER": blocker, "VERIFIED_XAUUSD_I_SOURCES": verified, "FULL_HORIZON_SOURCES": full_h,
        "FULL_HORIZON_GENERIC_ONLY": generic_full, "BID_ASK_SOURCES": bidask, "CHRONOLOGY_CAPABLE_SOURCES": chrono_ok,
        "CANDIDATE_419_EVENT_COVERAGE": cov_map, "OUTLIER_31_84R_COVERAGE": outlier_map,
        "C_VS_D_VS_E_VS_F_FEASIBILITY": "INSUFFICIENT_UNTIL_FULL_HORIZON_XAUUSD_I_TICKS",
        "EXACT_BROKER_FEED_STATUS": "METHOD_EXISTS_COVERAGE_UNPROVEN",
        "ALTERNATIVE_FEED_STATUS": "GENERIC_ONLY_NOT_CANONICAL", "GENERIC_XAUUSD_STATUS": "REJECTED",
        "RECOMMENDED_ACQUISITION_PATH": "OPTION_A operator-authorized CLASSIC terminal Request/Export of XAUUSD_i real ticks for the Phase 114 window; hash raw files; do not use tester-generated ticks",
        "OPERATOR_ACTION_REQUIRED": (
            "On an already-authorized LiteFinance CLASSIC terminal, open Symbols -> XAUUSD_i -> Ticks, "
            f"Request {ACQ_START_ISO} -> {ACQ_END_ISO}, Export, and place files outside production runtime. "
            "Alternatively ask LiteFinance support for an XAUUSD_i tick dump of that window. "
            "Do not substitute Dukascopy/HistData. This research process must not be given .env or asked to initialize MT5."
        ),
        "PHASE117_RECOMMENDATION": nxt, "n_events": N_EVENTS,
        "n_ambiguous_remaining": int(p115.get("AMBIGUOUS_394_REMAINING") or N_AMBIGUOUS_394),
        "tick_event_coverage_phase115": p115.get("TICK_COMPLETE_LIFECYCLE_EVENTS"),
        "window": {"start": ACQ_START_ISO, "end": ACQ_END_ISO, "timezone": TZ},
        "event_horizon": {"first_event": FIRST_EVENT, "last_event": LAST_EVENT, "latest_exit": LATEST_EXIT, "max_hold_minutes": MAX_HOLD_MIN, "outlier": OUTLIER_TS},
        "candidates": rows, "ranking": ranking, "acquisition_options": opts, "substitutions": subs,
        "refined_contract": refined_contract(), "parameters_optimized": False, "grid_search": False,
        "phase40_scan_rerun": False, "mt5_launched": False, "env_accessed": False, "data_acquired": False,
        "DATA_ACQUIRED": False, "downloaded": False, "accounts_registered": False, "intervention_implemented": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN, "TESTS_PHASE116": None,
        "REGRESSION_40_43_57_63_68_116": None, "FROZEN_PHASE40_TIMESTAMP": frozen.get("FROZEN_PHASE40_TIMESTAMP"),
        "FROZEN_PHASE40_FINGERPRINT": frozen.get("FROZEN_PHASE40_FINGERPRINT"), "FROZEN_PHASE40_SHA256": frozen.get("FROZEN_PHASE40_SHA256"),
        "frozen_integrity": frozen, "MT5_USED": False, "LIVE_TRADING": False, "ORDERS_PLACED": False, "ENV_ACCESSED": False,
        "PRODUCTION_CHANGED": False, "RISK_GATE_CHANGED": False, "TRADING_KERNEL_CHANGED": False, "EXECUTION_CHANGED": False,
        "STRATEGY_CHANGED": False, "CALIBRATION_CHANGED": False, "SIZING_CHANGED": False, "SLTP_CHANGED": False,
        "ML_ACTIVATED": False, "OPTIMIZATION_USED": False, "EXIT_DESIGN_SPEC_IMPLEMENTED": False, "PARAMETER_SEARCH_USED": False,
        "PRIMARY_EXIT_MECHANISM": "PROFIT_GIVEBACK", "DISCRIMINATOR_STATUS": "UNSUPPORTED",
        "EXIT_DESIGN_SPEC_STATUS": "INSUFFICIENT_EVIDENCE",
        "FINAL_GATE": "GO_RESEARCH" if frozen.get("ok") else "FAIL",
        "final_gate": "GO_RESEARCH" if frozen.get("ok") else "FAIL",
        "NEXT_RESEARCH_TARGET": nxt,
        "evidence_kind": "PUBLIC-DOC-EVIDENCE + CODE-EVIDENCE + FROZEN-DATA-EVIDENCE",
        "hypotheses": [{"id": "H116-01", "claim": "A canonical full-horizon XAUUSD_i tick path can be named without downloading data or connecting to MT5.", "result": "SUPPORTED_METHOD_UNPROVEN_RETENTION", "oos_used_for_decision": False}],
        "tests_performed": 1, "diagnostics_run": ["source_catalog", "identity_gate", "horizon_gate"], "oos_used_for_selection": False,
        "production_safety": {"TRADING": "NOT_PERFORMED", "STRATEGY": "NOT_MODIFIED", "ENV": "NOT_READ", "MT5": "NOT_USED", "OPTIMIZATION": "NOT_PERFORMED", "DATA_ACQUIRED": False, "production_changes": "NONE", "spec_implemented": False},
        "git_head": _git_head(root), "artifacts": {"json": PHASE116_JSON, "md": PHASE116_MD, "ledger": LEDGER_MD},
    }
    if not frozen.get("ok"):
        payload["PHASE116_STATUS"] = "FAIL"
        payload["blocker"] = "Frozen Phase 40 mismatch. File was not repaired."
    (root / PHASE116_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE116_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    _write_md(root, payload)
    _patch_truth(root, payload)
    append_ledger(root, payload)
    return payload