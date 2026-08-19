"""Phase 30D — Real broker fingerprint data collection design (research only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]
PHASE_DIR = Path(__file__).resolve().parent
PHASE30C = PROJECT_ROOT / "tradingbot" / "ml" / "research" / "phase30c"

VERDICTS = {"READY_FOR_DATA_COLLECTION", "MORE_DATA_REQUIREMENTS_NEEDED"}


def _write(name: str, payload: dict[str, Any]) -> None:
    (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _metric(
    name: str,
    *,
    definition: str,
    sampling_frequency: str,
    collection_method: str,
    storage_format: str,
    required_sample_size: str,
    collection_duration: str,
    calibration_importance: str,
    confidence: int,
) -> dict[str, Any]:
    return {
        "metric": name,
        "definition": definition,
        "sampling_frequency": sampling_frequency,
        "collection_method": collection_method,
        "storage_format": storage_format,
        "required_sample_size": required_sample_size,
        "expected_collection_duration": collection_duration,
        "calibration_importance": calibration_importance,
        "confidence": confidence,
    }


def build_broker_statistics_requirements() -> dict[str, Any]:
    metrics = [
        _metric(
            "Bid ticks",
            definition="Best bid price at each observation instant",
            sampling_frequency="Every tick change or 100ms poll minimum during active collection windows",
            collection_method="MT5 symbol_info_tick().bid logged on timer + on order send",
            storage_format="Parquet column bid float64",
            required_sample_size="≥500,000 ticks per symbol (30 days overlap+London)",
            collection_duration="30 calendar days minimum",
            calibration_importance="CRITICAL — mid/spread anchor",
            confidence=92,
        ),
        _metric(
            "Ask ticks",
            definition="Best ask price at each observation instant",
            sampling_frequency="Synchronized with bid tick capture",
            collection_method="MT5 symbol_info_tick().ask",
            storage_format="Parquet column ask float64",
            required_sample_size="≥500,000 ticks per symbol",
            collection_duration="30 calendar days",
            calibration_importance="CRITICAL",
            confidence=92,
        ),
        _metric(
            "Tick timestamps",
            definition="UTC microsecond timestamp of quote observation",
            sampling_frequency="Per tick record",
            collection_method="time.time() UTC at poll; MT5 tick.time_msc if available",
            storage_format="Parquet timestamp_us int64 UTC",
            required_sample_size="1:1 with tick rows",
            collection_duration="30 days",
            calibration_importance="CRITICAL — latency coupling",
            confidence=90,
        ),
        _metric(
            "Spread evolution",
            definition="ask - bid in price points over time",
            sampling_frequency="Derived per tick; also 1-minute aggregates",
            collection_method="Computed at ingest: spread = ask - bid",
            storage_format="Parquet spread_points float32; agg table spread_1m",
            required_sample_size="≥500,000 tick spreads; ≥43,200 minute bars",
            collection_duration="30 days",
            calibration_importance="CRITICAL — SpreadEngine primary",
            confidence=93,
        ),
        _metric(
            "Spread by session",
            definition="Spread distribution conditional on Asian/London/Overlap/NY",
            sampling_frequency="Session tag per tick from UTC hour",
            collection_method="Derive session_from_hour at ingest; aggregate p50/p95 per session",
            storage_format="JSON aggregate broker_spread_by_session.json",
            required_sample_size="≥50,000 ticks per session bucket",
            collection_duration="30 days covers all sessions",
            calibration_importance="CRITICAL",
            confidence=88,
        ),
        _metric(
            "Spread by weekday",
            definition="Spread stats Mon–Fri plus Sunday open",
            sampling_frequency="Daily rollup + Sunday first 2h special",
            collection_method="Weekday tag on tick; Sunday 22:00–02:00 UTC window flagged",
            storage_format="JSON broker_spread_by_weekday.json",
            required_sample_size="≥4 samples per weekday; ≥4 Sunday opens",
            collection_duration="≥28 calendar days (4 weeks)",
            calibration_importance="HIGH",
            confidence=82,
        ),
        _metric(
            "Spread before news",
            definition="Spread in T-5min to T-1min before scheduled high-impact events",
            sampling_frequency="1-second during news windows",
            collection_method="Economic calendar join; tag ticks pre_event",
            storage_format="Parquet partition news/pre_event/",
            required_sample_size="≥20 events × 300 ticks each",
            collection_duration="≥60 days or 12 NFP+FOMC cycles",
            calibration_importance="CRITICAL — news stress",
            confidence=85,
        ),
        _metric(
            "Spread after news",
            definition="Spread T+0 to T+15min post release",
            sampling_frequency="1-second during news windows",
            collection_method="Calendar join post_event flag",
            storage_format="Parquet partition news/post_event/",
            required_sample_size="≥20 events × 900 ticks each",
            collection_duration="≥60 days",
            calibration_importance="CRITICAL",
            confidence=85,
        ),
        _metric(
            "Spread during rollover",
            definition="Spread 21:55–22:15 UTC daily (broker rollover window)",
            sampling_frequency="1-second in rollover window",
            collection_method="Time filter flag is_rollover",
            storage_format="Parquet partition rollover/",
            required_sample_size="≥20 rollover windows",
            collection_duration="≥20 trading days",
            calibration_importance="HIGH",
            confidence=80,
        ),
        _metric(
            "Slippage (signed)",
            definition="fill_price - requested_price (buy positive = worse)",
            sampling_frequency="Per execution event",
            collection_method="Log requested_price at send; fill_price from order result",
            storage_format="Executions table slippage_points float32",
            required_sample_size="≥200 fills minimum; ≥500 preferred",
            collection_duration="Until 500 fills or 90 days paper/live shadow",
            calibration_importance="CRITICAL",
            confidence=90,
        ),
        _metric(
            "Positive slippage",
            definition="Slippage favorable to trader (price improvement)",
            sampling_frequency="Subset of slippage where sign favorable",
            collection_method="Classify slippage_sign from signed slippage",
            storage_format="Aggregate positive_slippage_rate in slippage_stats.json",
            required_sample_size="≥30 positive events for rate estimate",
            collection_duration="Same as slippage collection",
            calibration_importance="MEDIUM",
            confidence=75,
        ),
        _metric(
            "Negative slippage",
            definition="Adverse slippage magnitude distribution",
            sampling_frequency="Per fill",
            collection_method="abs(min(0, signed_slippage))",
            storage_format="Histogram bins in slippage_stats.json",
            required_sample_size="≥100 adverse events",
            collection_duration="90 days or 500 fills",
            calibration_importance="CRITICAL",
            confidence=88,
        ),
        _metric(
            "Entry slippage",
            definition="Slippage on opening deal only",
            sampling_frequency="Per entry fill",
            collection_method="Tag deal entry_in; map to bot entry signals via ticket/time",
            storage_format="Executions leg=entry",
            required_sample_size="≥200 entry fills",
            collection_duration="90 days",
            calibration_importance="CRITICAL",
            confidence=88,
        ),
        _metric(
            "Exit slippage",
            definition="Slippage on closing deal vs expected SL/TP/close price",
            sampling_frequency="Per exit fill",
            collection_method="Compare fill to SL/TP level or quote at send",
            storage_format="Executions leg=exit; expected_price field",
            required_sample_size="≥200 exit fills",
            collection_duration="90 days",
            calibration_importance="CRITICAL — phase30b rank 2 gap",
            confidence=90,
        ),
        _metric(
            "Partial fills",
            definition="filled_volume < requested_volume",
            sampling_frequency="Per order result",
            collection_method="MT5 deal volume vs request volume",
            storage_format="Executions partial_fill bool; fill_ratio float",
            required_sample_size="≥500 orders (expect low rate at 0.01 lot)",
            collection_duration="90 days",
            calibration_importance="MEDIUM at min lot",
            confidence=78,
        ),
        _metric(
            "Execution delay",
            definition="t_fill - t_send in milliseconds",
            sampling_frequency="Per order",
            collection_method="Monotonic clock at send and on result callback",
            storage_format="Executions execution_delay_ms int32",
            required_sample_size="≥200 paired timestamps",
            collection_duration="30 days active trading",
            calibration_importance="HIGH",
            confidence=85,
        ),
        _metric(
            "Broker processing delay",
            definition="Portion of delay attributable to broker (result.time - send approx)",
            sampling_frequency="Per order when MT5 result time available",
            collection_method="MT5 order/deal time_msc minus local send time (clock sync note)",
            storage_format="Executions broker_delay_ms int32",
            required_sample_size="≥200",
            collection_duration="30 days",
            calibration_importance="MEDIUM",
            confidence=70,
        ),
        _metric(
            "Network latency",
            definition="RTT estimate via periodic ping or tick arrival jitter",
            sampling_frequency="Every 60s heartbeat",
            collection_method="Optional ICMP to broker host; or tick inter-arrival stability",
            storage_format="Latency heartbeat parquet",
            required_sample_size="≥10,000 heartbeat samples",
            collection_duration="30 days",
            calibration_importance="MEDIUM",
            confidence=65,
        ),
        _metric(
            "Round-trip latency",
            definition="Send order to confirmation total ms",
            sampling_frequency="Per order",
            collection_method="Same as execution_delay",
            storage_format="Executions round_trip_ms",
            required_sample_size="≥200",
            collection_duration="30 days",
            calibration_importance="HIGH — latency engine",
            confidence=85,
        ),
        _metric(
            "Order rejection / Retcodes",
            definition="MT5 TRADE_RETCODE_* on failed or requoted orders",
            sampling_frequency="Per order attempt",
            collection_method="Log result.retcode result.comment on every send",
            storage_format="Orders table retcode int; retcode_stats.json histogram",
            required_sample_size="≥1000 order attempts (includes successes)",
            collection_duration="90 days",
            calibration_importance="HIGH — fill probability model",
            confidence=82,
        ),
        _metric(
            "Freeze level events",
            definition="Orders rejected when price within freeze_level of market",
            sampling_frequency="On reject with retcode related to freeze",
            collection_method="symbol_info.freeze_level at reject time; log distance",
            storage_format="Rules events parquet",
            required_sample_size="≥10 events or symbol_info snapshot if none",
            collection_duration="90 days",
            calibration_importance="MEDIUM",
            confidence=68,
        ),
        _metric(
            "Stops level events",
            definition="SL/TP placement within stops_level minimum distance",
            sampling_frequency="On order validate fail or adjust",
            collection_method="symbol_info.stops_level logged at each entry with SL/TP distance",
            storage_format="Rules events + symbol_info daily snapshot",
            required_sample_size="Daily symbol_info snapshot × 30; ≥5 reject events",
            collection_duration="30 days",
            calibration_importance="MEDIUM",
            confidence=72,
        ),
        _metric(
            "Margin usage / level",
            definition="account.margin account.margin_free account.margin_level",
            sampling_frequency="Every 60s + at each fill",
            collection_method="MT5 account_info snapshot",
            storage_format="Account snapshots parquet",
            required_sample_size="≥5,000 snapshots",
            collection_duration="30 days",
            calibration_importance="MEDIUM — stop-out model",
            confidence=80,
        ),
        _metric(
            "Margin calls / Stop-outs",
            definition="Forced liquidation when margin_level below stop_out",
            sampling_frequency="Rare event — continuous account poll",
            collection_method="Log if margin_level < stop_out_level; history_deals with comment",
            storage_format="Risk events jsonl",
            required_sample_size="≥1 if possible; symbol_info stop_out level required regardless",
            collection_duration="≥90 days",
            calibration_importance="LOW at 0.01 lot; HIGH for realism completeness",
            confidence=75,
        ),
        _metric(
            "Commission",
            definition="Per-deal commission from account/deal history",
            sampling_frequency="Per deal",
            collection_method="MT5 history_deals commission field",
            storage_format="Executions commission float",
            required_sample_size="≥200 deals",
            collection_duration="90 days",
            calibration_importance="LOW if spread-only account",
            confidence=85,
        ),
        _metric(
            "Swap",
            definition="Overnight swap charged per position",
            sampling_frequency="Per deal at rollover",
            collection_method="history_deals swap field; position swap snapshot 22:00 UTC",
            storage_format="Carry events parquet",
            required_sample_size="≥20 overnight holds",
            collection_duration="≥30 days",
            calibration_importance="LOW for M5 72-bar max hold (~6h)",
            confidence=82,
        ),
        _metric(
            "Execution volume",
            definition="Filled lot size per deal",
            sampling_frequency="Per fill",
            collection_method="MT5 deal volume",
            storage_format="Executions filled_lot float",
            required_sample_size="≥500 fills",
            collection_duration="90 days",
            calibration_importance="MEDIUM",
            confidence=88,
        ),
        _metric(
            "Liquidity shortages",
            definition="Partial fill + requote + off-quotes cluster indicating thin book",
            sampling_frequency="Per abnormal retcode or partial",
            collection_method="Tag cluster events; spread widen simultaneous",
            storage_format="Liquidity events jsonl",
            required_sample_size="≥30 shortage indicators",
            collection_duration="60 days",
            calibration_importance="MEDIUM",
            confidence=70,
        ),
        _metric(
            "Weekend gaps",
            definition="Friday close to Sunday open price jump",
            sampling_frequency="Per weekend",
            collection_method="Last tick Fri 21:00 UTC vs first tick Sun open",
            storage_format="Gap events json: gap_points direction",
            required_sample_size="≥4 weekend transitions",
            collection_duration="≥28 days",
            calibration_importance="HIGH — GapEngine",
            confidence=83,
        ),
        _metric(
            "Gap-through-stop",
            definition="Exit fill worse than SL by more than tolerance",
            sampling_frequency="Per SL exit",
            collection_method="Compare exit fill to SL level; flag gap_through",
            storage_format="Executions gap_through_sl bool",
            required_sample_size="≥10 if occurs; model from weekend gaps otherwise",
            collection_duration="≥60 days",
            calibration_importance="HIGH tail",
            confidence=78,
        ),
        _metric(
            "Gap-through-TP",
            definition="Exit fill better than TP beyond tolerance",
            sampling_frequency="Per TP exit",
            collection_method="Compare exit fill to TP",
            storage_format="Executions gap_through_tp bool",
            required_sample_size="≥20 TP exits",
            collection_duration="60 days",
            calibration_importance="LOW",
            confidence=72,
        ),
        _metric(
            "Price improvement",
            definition="Fill better than quoted ask (buy) or bid (sell) at send",
            sampling_frequency="Per fill",
            collection_method="Compare fill to quote at send time",
            storage_format="Executions price_improvement bool",
            required_sample_size="≥200 fills for rate",
            collection_duration="90 days",
            calibration_importance="MEDIUM",
            confidence=80,
        ),
    ]
    return {
        "phase": "30D",
        "metric_count": len(metrics),
        "metrics": metrics,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_broker_fingerprint_schema() -> dict[str, Any]:
    return {
        "phase": "30D",
        "dataset_name": "BrokerFingerprintDataset",
        "version": "1.0.0",
        "root_path": "tradingbot/ml/research/phase30d/data/",
        "tick_store_path": "tradingbot/ml/research/phase30d/tick_store/",
        "timezone": "UTC only — all timestamps stored as UTC microseconds",
        "tables": {
            "ticks": {
                "format": "parquet partitioned by symbol/YYYY/MM/DD",
                "columns": {
                    "timestamp_us": "int64 UTC microseconds",
                    "symbol": "string",
                    "bid": "float64",
                    "ask": "float64",
                    "last": "float64 nullable",
                    "volume": "float64 nullable",
                    "spread_points": "float32 computed",
                    "session": "string",
                    "flags": "int32 bitfield news/rollover/weekend",
                },
                "compression": "zstd level 3",
                "primary_key": ["symbol", "timestamp_us"],
            },
            "executions": {
                "format": "parquet or sqlite broker_fingerprint.db",
                "columns": {
                    "execution_id": "uuid",
                    "order_id": "uuid",
                    "ticket": "int64",
                    "timestamp_send_us": "int64",
                    "timestamp_fill_us": "int64",
                    "symbol": "string",
                    "direction": "string",
                    "leg": "entry|exit",
                    "requested_price": "float64",
                    "quoted_bid": "float64",
                    "quoted_ask": "float64",
                    "fill_price": "float64",
                    "filled_lot": "float64",
                    "requested_lot": "float64",
                    "slippage_points": "float32",
                    "spread_at_send": "float32",
                    "execution_delay_ms": "int32",
                    "retcode": "int32",
                    "partial_fill": "bool",
                    "price_improvement": "bool",
                    "commission": "float32",
                    "swap": "float32",
                    "journal_execution_id": "int nullable map to trade_journal.executions",
                    "journal_paper_trade_id": "int nullable",
                },
            },
            "orders": {
                "format": "parquet",
                "columns": {
                    "order_id": "uuid",
                    "timestamp_us": "int64",
                    "symbol": "string",
                    "direction": "string",
                    "requested_lot": "float64",
                    "requested_price": "float64",
                    "deviation_points": "int32",
                    "retcode": "int32",
                    "retcode_comment": "string",
                    "attempt": "int32",
                    "success": "bool",
                },
            },
            "symbol_info_snapshots": {
                "format": "json daily",
                "fields": [
                    "digits", "point", "spread", "trade_stops_level", "trade_freeze_level",
                    "volume_min", "volume_step", "volume_max", "margin_initial", "swap_long", "swap_short",
                ],
            },
            "account_snapshots": {
                "format": "parquet",
                "columns": {
                    "timestamp_us": "int64",
                    "balance": "float64",
                    "equity": "float64",
                    "margin": "float64",
                    "margin_free": "float64",
                    "margin_level": "float64",
                },
            },
            "gap_events": {
                "format": "jsonl",
                "fields": ["weekend_id", "close_ts", "open_ts", "close_bid", "open_ask", "gap_points"],
            },
            "metadata": {
                "format": "broker_manifest.json",
                "fields": [
                    "broker_name", "server", "account_type", "symbol", "leverage",
                    "collection_start_utc", "collection_end_utc", "vps_profile",
                    "collector_version", "checksum_sha256",
                ],
            },
        },
        "journal_mapping": {
            "trade_journal.executions": "Map via timestamp±500ms symbol direction lot → execution_id",
            "trade_journal.paper_trades": "Map via id → journal_paper_trade_id",
            "note": "Read-only export — do not modify journal schema in Phase 30D",
        },
        "integrity": {
            "tick_validation": ["bid <= ask", "monotonic timestamps per symbol", "no null bid/ask"],
            "execution_validation": ["fill_price > 0", "retcode present", "send <= fill time"],
            "manifest_checksum": "SHA256 per partition file listed in manifest",
        },
        "synchronization": {
            "clock": "NTP-synced VPS required; log clock_offset_ms daily",
            "alignment": "Join executions to nearest tick within 250ms",
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_minimum_sample_requirements() -> dict[str, Any]:
    return {
        "phase": "30D",
        "symbol_primary": "XAUUSD",
        "minimums": {
            "ticks_total": 500_000,
            "ticks_per_session": 50_000,
            "executions_total": 200,
            "executions_preferred": 500,
            "entry_fills": 200,
            "exit_fills": 200,
            "order_attempts": 1000,
            "trading_days": 30,
            "trading_days_preferred": 90,
            "calendar_weeks": 4,
            "news_events_high_impact": 20,
            "rollover_windows": 20,
            "weekend_transitions": 4,
            "account_snapshots": 5000,
            "symbol_info_daily_snapshots": 30,
        },
        "statistical_reliability": {
            "spread_session_p50": "±0.02 points at 50k samples per session (CLT)",
            "slippage_p50": "±0.01 points at n≥200 fills",
            "retcode_rates": "±1% absolute at n≥1000 orders",
            "positive_slippage_rate": "±3% at n≥200 fills",
        },
        "estimated_storage": {
            "ticks_30d_100ms": "~2.5 GB compressed parquet",
            "executions_500": "~500 KB",
            "total_dataset": "~3 GB per symbol per 30 days",
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_calibration_readiness() -> dict[str, Any]:
    mins = build_minimum_sample_requirements()["minimums"]
    return {
        "phase": "30D",
        "checklist": [
            {"id": "C1", "item": "≥500k ticks XAUUSD with bid/ask/timestamp UTC", "required": True},
            {"id": "C2", "item": "≥50k ticks per session bucket", "required": True},
            {"id": "C3", "item": "≥200 entry fills with requested+fill price", "required": True},
            {"id": "C4", "item": "≥200 exit fills with expected SL/TP reference", "required": True},
            {"id": "C5", "item": "≥1000 order attempts with retcode histogram", "required": True},
            {"id": "C6", "item": "≥20 high-impact news windows (pre+post ticks)", "required": True},
            {"id": "C7", "item": "≥20 rollover windows sampled", "required": True},
            {"id": "C8", "item": "≥4 weekend gap measurements", "required": True},
            {"id": "C9", "item": "30 daily symbol_info snapshots (stops/freeze/volume)", "required": True},
            {"id": "C10", "item": "broker_manifest.json with server/account metadata", "required": True},
            {"id": "C11", "item": "Clock sync verified (NTP offset <50ms)", "required": True},
            {"id": "C12", "item": "Integrity checksums pass on all partitions", "required": True},
        ],
        "ready_for_calibration_when": "ALL required checklist items C1–C12 satisfied",
        "statistically_reliable_when": {
            "spread_engine": "C1+C2+C6+C7+C8 complete",
            "slippage_engine": "C3+C4 with n≥200 each leg",
            "fill_retcode_model": "C5 complete",
            "latency_engine": "C3 with execution_delay_ms on ≥200 fills",
            "broker_rules": "C9 complete",
            "gap_engine": "C8 complete",
        },
        "not_required_for_mvp_calibration": [
            "Margin stop-out events (if none occur)",
            "Partial fills at 0.01 lot (if rate <1%)",
            "Swap (hold horizon <24h)",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_tick_collection_plan() -> dict[str, Any]:
    return {
        "phase": "30D",
        "objective": "Continuous bid/ask stream for spread and latency-price coupling",
        "mode": "Research collector process — isolated from production pipeline",
        "method": {
            "primary": "Poll MT5 symbol_info_tick every 100ms during 00:00–22:00 UTC",
            "secondary": "On every bot order send capture quote snapshot",
            "high_frequency_windows": "1-second poll during news and rollover",
        },
        "windows": {
            "continuous": "Mon–Fri 00:00–22:00 UTC",
            "news": "T-5min to T+15min high impact USD/XAU",
            "rollover": "21:55–22:15 UTC daily",
            "weekend_open": "Sun 22:00–Mon 02:00 UTC first ticks",
        },
        "output": "tick_store/XAUUSD/YYYY/MM/DD/part-*.parquet",
        "phase30c_alignment": "Matches phase30c tick_requirements.json storage proposal",
        "duration_days": 30,
        "target_rows": 500_000,
        "collector_location": "tradingbot/ml/research/phase30d/collectors/ (Phase 30E implement)",
        "safety": "Read-only MT5 — no orders from tick collector",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_execution_collection_plan() -> dict[str, Any]:
    return {
        "phase": "30D",
        "objective": "Fill-level ground truth for slippage, retcodes, partial fills",
        "modes": [
            {
                "mode": "live_shadow",
                "description": "Bot runs paper; parallel log every live-eligible send without sending (or demo micro)",
                "risk": "LOW on demo account",
            },
            {
                "mode": "demo_live",
                "description": "0.01 lot demo account real sends — recommended",
                "risk": "LOW",
            },
            {
                "mode": "paper_export",
                "description": "Export trade_journal.executions — insufficient alone (slippage=0)",
                "risk": "NONE",
                "adequacy": "INSUFFICIENT for slippage calibration",
            },
        ],
        "recommended": "demo_live 0.01 lot XAUUSD M5 aligned with bot signals",
        "fields_per_send": [
            "timestamp_send_us", "requested_price", "quoted_bid", "quoted_ask",
            "result.retcode", "result.price", "result.volume", "execution_delay_ms",
        ],
        "target_fills": 500,
        "duration_days": 90,
        "journal_mapping": "Post-hoc join to trade_journal for signal context only",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_latency_collection_plan() -> dict[str, Any]:
    return {
        "phase": "30D",
        "objective": "Round-trip and component latency for LatencySimulator",
        "measurements": [
            {"name": "round_trip_ms", "method": "send to retcode callback", "n": 200},
            {"name": "tick_to_send_ms", "method": "last tick ts to send ts", "n": 200},
            {"name": "heartbeat_jitter_ms", "method": "60s tick poll arrival variance", "n": 10000},
        ],
        "profiles_to_capture": ["VPS co-located", "home ISP if applicable"],
        "coupling_requirement": "Every execution record must include quote at send AND quote at fill tick index",
        "duration_days": 30,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_spread_collection_plan() -> dict[str, Any]:
    return {
        "phase": "30D",
        "objective": "Empirical spread distributions for SpreadEngine calibration",
        "derived_from": "Tick dataset aggregations",
        "aggregates_required": [
            "by_session: p10 p50 p95 p99 spread_points",
            "by_weekday: p50 spread_points",
            "by_hour_utc: mean spread heatmap 24h",
            "news_pre_post: multiplier vs baseline",
            "rollover: multiplier vs baseline",
            "weekend_open: absolute spread and gap",
        ],
        "baseline_definition": "Overlap session median spread excluding news flags",
        "minimum_ticks": 500_000,
        "output_files": [
            "aggregates/spread_by_session.json",
            "aggregates/spread_news_multiplier.json",
            "aggregates/spread_rollover.json",
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_slippage_collection_plan() -> dict[str, Any]:
    return {
        "phase": "30D",
        "objective": "Signed slippage distributions entry vs exit",
        "source": "Executions dataset with requested_price and fill_price",
        "segments": [
            "leg entry|exit",
            "session",
            "direction BUY|SELL",
            "spread_quartile at send",
            "volatility_quartile ATR percentile",
        ],
        "minimum_fills_per_segment": 30,
        "outputs": [
            "aggregates/slippage_entry_by_session.json",
            "aggregates/slippage_exit_by_session.json",
            "aggregates/price_improvement_rate.json",
        ],
        "critical_note": "Paper journal slippage_pips=0 — MUST use demo/live fills not paper export alone",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_required_datasets() -> dict[str, Any]:
    return {
        "phase": "30D",
        "datasets": [
            {"id": "DS1", "name": "TickStream", "required": True, "feeds": ["SpreadEngine", "LatencyEngine"]},
            {"id": "DS2", "name": "ExecutionFills", "required": True, "feeds": ["SlippageEngine", "FillEngine"]},
            {"id": "DS3", "name": "OrderAttempts", "required": True, "feeds": ["Retcode model"]},
            {"id": "DS4", "name": "SymbolInfoDaily", "required": True, "feeds": ["BrokerRules"]},
            {"id": "DS5", "name": "AccountSnapshots", "required": False, "feeds": ["MarginEngine"]},
            {"id": "DS6", "name": "NewsCalendar", "required": True, "feeds": ["News spread flags"], "source": "External FF calendar JSON"},
            {"id": "DS7", "name": "GapEvents", "required": True, "feeds": ["GapEngine"]},
            {"id": "DS8", "name": "BrokerManifest", "required": True, "feeds": ["All modules metadata"]},
        ],
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def build_collection_priority_matrix() -> dict[str, Any]:
    return {
        "phase": "30D",
        "priority": [
            {"rank": 1, "dataset": "TickStream", "duration_days": 30, "blocker_for": "SpreadEngine calibration"},
            {"rank": 2, "dataset": "ExecutionFills demo live", "duration_days": 90, "blocker_for": "SlippageEngine"},
            {"rank": 3, "dataset": "OrderAttempts", "duration_days": 90, "blocker_for": "Retcode model"},
            {"rank": 4, "dataset": "SymbolInfoDaily", "duration_days": 30, "blocker_for": "BrokerRules"},
            {"rank": 5, "dataset": "NewsCalendar", "duration_days": "60+", "blocker_for": "News spread multiplier"},
            {"rank": 6, "dataset": "GapEvents", "duration_days": 28, "blocker_for": "GapEngine"},
            {"rank": 7, "dataset": "AccountSnapshots", "duration_days": 30, "blocker_for": "MarginEngine optional"},
        ],
        "parallel_collection": True,
        "estimated_wall_clock": "90 days to satisfy all minimums with bot running demo",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
    }


def determine_verdict(readiness: dict) -> str:
    required = sum(1 for c in readiness["checklist"] if c["required"])
    if required >= 12:
        return "READY_FOR_DATA_COLLECTION"
    return "MORE_DATA_REQUIREMENTS_NEEDED"


def run_phase30d() -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    PHASE_DIR.mkdir(parents=True, exist_ok=True)

    schema = build_broker_fingerprint_schema()
    _write("broker_fingerprint_schema.json", schema)

    stats = build_broker_statistics_requirements()
    _write("broker_statistics_requirements.json", stats)

    mins = build_minimum_sample_requirements()
    _write("minimum_sample_requirements.json", mins)

    readiness = build_calibration_readiness()
    _write("calibration_readiness.json", readiness)

    _write("required_datasets.json", build_required_datasets())
    _write("tick_collection_plan.json", build_tick_collection_plan())
    _write("execution_collection_plan.json", build_execution_collection_plan())
    _write("latency_collection_plan.json", build_latency_collection_plan())
    _write("spread_collection_plan.json", build_spread_collection_plan())
    _write("slippage_collection_plan.json", build_slippage_collection_plan())
    _write("collection_priority_matrix.json", build_collection_priority_matrix())

    verdict = determine_verdict(readiness)

    final = {
        "phase": "30D",
        "verdict": verdict,
        "mission": "Broker fingerprint collection design — no calibration, no implementation",
        "production_modified": False,
        "metrics_specified": stats["metric_count"],
        "datasets_required": 8,
        "minimum_ticks": mins["minimums"]["ticks_total"],
        "minimum_fills": mins["minimums"]["executions_preferred"],
        "minimum_days": mins["minimums"]["trading_days"],
        "collection_wall_clock_days": 90,
        "next_phase": "30E — implement isolated collectors per collection plans",
        "deliverables": [
            "broker_fingerprint_schema.json",
            "required_datasets.json",
            "tick_collection_plan.json",
            "execution_collection_plan.json",
            "latency_collection_plan.json",
            "spread_collection_plan.json",
            "slippage_collection_plan.json",
            "broker_statistics_requirements.json",
            "minimum_sample_requirements.json",
            "calibration_readiness.json",
            "collection_priority_matrix.json",
            "phase30d_final_report.json",
        ],
        "generated_utc": ts,
    }
    _write("phase30d_final_report.json", final)
    return final


def main() -> int:
    report = run_phase30d()
    print(json.dumps({"verdict": report["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
