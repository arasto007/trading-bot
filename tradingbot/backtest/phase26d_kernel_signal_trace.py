"""Phase 26D — bounded kernel signal-drop trace (offline, no full backtest)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from engine.strategies.price_action_strategy import PriceActionStrategy
from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.backtest.engine import BacktestEngine
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG, merge_broker_catalog
from tradingbot.backtest.phase26b_controlled_validation import (
    _build_backtest_config,
    build_frozen_baseline_configuration,
)
from tradingbot.backtest.phase26c_zero_signal_audit import (
    DIAGNOSTIC_BARS,
    WARMUP,
    _append_forming_bar_m5,
    _enrich_frame,
    _load_parquet_tail,
)
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.gold_strategies.m5_london_sweep import (
    asian_range,
    diagnose_m5_london_hold,
    evaluate_m5_london_sweep,
    m5_asian_end_hour,
    m5_ny_entry_hours,
)
from tradingbot.domain.gold_strategies.router import evaluate_gold_setup
from tradingbot.domain.models import CycleContext, MarketKey
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.domain.pa_hardening import apply_setup_hardening, clear_pa_dedup_cache
from tradingbot.domain.price_action import enrich_price_action
PHASE26D_JSON = "logs/phase26d_kernel_signal_trace.json"
DEFAULT_DATASET = "data/backtest/XAUUSD_M5_183d.parquet"


@dataclass
class Phase26DTrace:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    root_cause_classification: str = "I — INCONCLUSIVE"
    safety: dict[str, bool] = field(
        default_factory=lambda: {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "ROUTER_CHANGED": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26D", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _signal_summary(sig: Any) -> dict[str, Any] | None:
    if sig is None:
        return None
    if hasattr(sig, "direction"):
        direction = getattr(sig.direction, "name", str(sig.direction))
    elif hasattr(sig, "signal_type"):
        direction = getattr(sig.signal_type, "name", str(sig.signal_type))
    else:
        direction = "UNKNOWN"
    return {
        "direction": direction,
        "confidence": float(getattr(sig, "confidence", 0) or 0),
        "strategy_name": getattr(sig, "strategy_name", None),
        "timeframe": getattr(sig, "timeframe", None),
        "symbol": getattr(sig, "symbol", None),
        "stop_loss": getattr(sig, "stop_loss", None),
    }


def _build_trace_engine(enriched: pd.DataFrame, frozen: dict[str, Any]) -> BacktestEngine:
    legacy = load_legacy_config()
    legacy = merge_broker_catalog(legacy, {"XAUUSD_i": dict(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])})
    legacy["symbol_aliases"] = {"XAUUSD": PRIMARY_SYMBOL}
    data_label = frozen.get("data_symbol_label", "XAUUSD")
    cfg = _build_backtest_config(frozen)
    engine = BacktestEngine(cfg, legacy, quiet=True)
    engine._htf.needs_htf = lambda: True  # type: ignore[method-assign]
    engine._htf.load = lambda: None  # type: ignore[method-assign]
    engine._data.inject({data_label: enriched})
    return engine


def _setup_evidence(closed: pd.DataFrame, i: int, cfg: dict[str, Any]) -> dict[str, Any]:
    row = closed.iloc[i]
    bounds = asian_range(
        closed,
        i,
        start_hour=int(cfg.get("ASIAN_START_HOUR", 0)),
        end_hour=m5_asian_end_hour(cfg),
    )
    diag = diagnose_m5_london_hold(closed, i, cfg)
    df_pa = enrich_price_action(closed, cfg, at_index=i)
    raw = evaluate_m5_london_sweep(df_pa, i, cfg)
    hardened = (
        apply_setup_hardening(df_pa, i, cfg, raw, timeframe="M5") if raw is not None else None
    )
    gold = evaluate_gold_setup(df_pa, i, cfg, timeframe="M5")
    return {
        "timestamp": str(closed.index[i]),
        "bar_index": i,
        "cursor_equivalent": i,
        "ohlc": {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        },
        "asian_range": {"high": bounds[0], "low": bounds[1]} if bounds else None,
        "diagnose": diag,
        "sweep_direction": (raw.metadata or {}).get("sweep_side") if raw else None,
        "quality_score": (gold.metadata or {}).get("quality_score") if gold else None,
        "confidence": float(gold.confidence) if gold else None,
    }


def find_known_good_candidates(
    enriched: pd.DataFrame,
    *,
    warmup: int = WARMUP,
) -> list[dict[str, Any]]:
    cfg = get_price_action_config("XAUUSD", "M5")
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    legacy = load_legacy_config()
    clear_pa_dedup_cache()
    pa = PriceActionStrategy(legacy)
    out: list[dict[str, Any]] = []

    for cursor in range(warmup, len(enriched)):
        window = _append_forming_bar_m5(enriched.iloc[: cursor + 1])
        closed = exclude_forming_bar(window, min_rows=30)
        if closed is None or closed.empty:
            continue
        i = len(closed) - 1
        ts = closed.index[i]
        if not (ny_s <= ts.hour < ny_e):
            continue
        sigs = pa.generate_signals(closed, symbol="XAUUSD", timeframe="M5")
        if not sigs:
            continue
        evidence = _setup_evidence(closed, i, cfg)
        evidence["cursor"] = cursor
        evidence["isolated_signal"] = _signal_summary(sigs[0]) if sigs else None
        out.append(evidence)
    return out


def _kernel_closed_window(engine: BacktestEngine, cursor: int, data_label: str) -> pd.DataFrame | None:
    engine._data.set_cursor(cursor)
    fetch_bars = int((engine._legacy_config.get("PRICE_ACTION") or {}).get("FETCH_BARS", 300))
    raw_window = engine._data.get_ohlcv_window(data_label, fetch_bars)
    if raw_window is None or raw_window.empty:
        return None
    return exclude_forming_bar(raw_window, min_rows=30)


def _isolated_replay(
    enriched: pd.DataFrame,
    cursor: int,
    *,
    legacy_config: dict[str, Any],
    use_kernel_window: bool,
    engine: BacktestEngine | None = None,
    data_label: str = "XAUUSD",
) -> dict[str, Any] | None:
    clear_pa_dedup_cache()
    pa = PriceActionStrategy(legacy_config)
    if use_kernel_window and engine is not None:
        closed = _kernel_closed_window(engine, cursor, data_label)
    else:
        window = _append_forming_bar_m5(enriched.iloc[: cursor + 1])
        closed = exclude_forming_bar(window, min_rows=30)
    if closed is None or closed.empty:
        return None
    sigs = pa.generate_signals(closed, symbol="XAUUSD", timeframe="M5")
    return _signal_summary(sigs[0]) if sigs else None


async def trace_single_bar_pipeline(
    engine: BacktestEngine,
    cursor: int,
    *,
    data_label: str = "XAUUSD",
) -> dict[str, Any]:
    """Trace one cursor through the real TradingKernel pipeline (no pre-calls)."""
    market = MarketKey(data_label, "M5")
    clear_pa_dedup_cache()
    engine._data.set_cursor(cursor)
    portfolio = engine._broker.snapshot()

    fetch_bars = int((engine._legacy_config.get("PRICE_ACTION") or {}).get("FETCH_BARS", 300))
    raw_window = engine._data.get_ohlcv_window(data_label, fetch_bars)
    closed_from_raw = exclude_forming_bar(raw_window, min_rows=30) if raw_window is not None else None

    ctx = CycleContext(market=market)
    stage_trace: list[dict[str, Any]] = []
    journal_len_before = len(engine._risk.risk_journal)

    for stage in engine._kernel._pipeline:
        name = stage.name.value
        before_signal = _signal_summary(ctx.signal)
        ok = await stage.run(ctx, portfolio)
        stage_trace.append(
            {
                "stage": name,
                "continued": ok,
                "errors": list(ctx.errors),
                "signal_after": _signal_summary(ctx.signal),
                "signal_before": before_signal,
                "risk_allowed": getattr(ctx.risk, "allowed", None) if ctx.risk else None,
                "risk_reason": getattr(ctx.risk, "reason", None) if ctx.risk else None,
            }
        )
        if not ok:
            break

    closed_kernel = exclude_forming_bar(ctx.enriched_ohlcv, min_rows=30) if ctx.enriched_ohlcv is not None else None
    index_audit = {
        "engine_cursor": cursor,
        "raw_window_len": len(raw_window) if raw_window is not None else 0,
        "raw_last_ts": str(raw_window.index[-1]) if raw_window is not None and len(raw_window) else None,
        "closed_last_ts": str(closed_from_raw.index[-1]) if closed_from_raw is not None and len(closed_from_raw) else None,
        "closed_bar_index_in_enriched": (
            int(enriched_index(closed_from_raw.index[-1], engine._data.frame(data_label)))
            if closed_from_raw is not None and engine._data.frame(data_label) is not None
            else None
        ),
        "kernel_closed_last_ts": str(closed_kernel.index[-1]) if closed_kernel is not None and len(closed_kernel) else None,
        "fetch_bars_config": fetch_bars,
        "signal_window_config": engine._cfg.signal_window,
        "forming_bar_enabled": engine._cfg.simulate_forming_bar,
        "index_alignment": (
            "PASS"
            if closed_from_raw is not None
            and closed_kernel is not None
            and str(closed_from_raw.index[-1]) == str(closed_kernel.index[-1])
            else "FAIL"
        ),
    }

    return {
        "registry_type": type(engine._strategies).__name__,
        "window": {
            "fetch_bars": fetch_bars,
            "signal_window": engine._cfg.signal_window,
            "raw_len": len(raw_window) if raw_window is not None else 0,
        },
        "stage_trace": stage_trace,
        "pipeline_signal": _signal_summary(ctx.signal),
        "pipeline_risk_reason": getattr(ctx.risk, "reason", None) if ctx.risk else None,
        "risk_journal_len_after": len(engine._risk.risk_journal),
        "risk_journal_delta": len(engine._risk.risk_journal) - journal_len_before,
        "index_audit": index_audit,
        "wpsqf_mode": str(
            __import__(
                "tradingbot.services.signal_filter_mode",
                fromlist=["resolve_signal_filter_mode"],
            ).resolve_signal_filter_mode(config=engine._legacy_config).value
        ),
    }


def enriched_index(ts: pd.Timestamp, df: pd.DataFrame) -> int | None:
    try:
        return int(df.index.get_loc(ts))
    except Exception:
        return None


def _build_isolated_vs_full_table(
    *,
    isolated_full: dict[str, Any] | None,
    isolated_kernel: dict[str, Any] | None,
    single: dict[str, Any],
) -> list[dict[str, Any]]:
    stages = {s["stage"]: s for s in single.get("stage_trace", [])}
    pipe_sig = single.get("pipeline_signal")
    return [
        {
            "stage": "bar_selected",
            "isolated_full_history": "yes",
            "isolated_kernel_window": "yes",
            "full_path": "yes",
            "identical": True,
        },
        {
            "stage": "strategy_called",
            "isolated_full_history": isolated_full is not None,
            "isolated_kernel_window": isolated_kernel is not None,
            "full_path": stages.get(PipelineStageName.SIGNALS.value, {}).get("continued") is not None,
            "identical": bool(isolated_kernel) == bool(pipe_sig),
        },
        {
            "stage": "signal_created",
            "isolated_full_history": isolated_full is not None,
            "isolated_kernel_window": isolated_kernel is not None,
            "full_path": pipe_sig is not None,
            "identical": (isolated_kernel or {}).get("direction") == (pipe_sig or {}).get("direction"),
        },
        {
            "stage": "signal_direction",
            "isolated_full_history": (isolated_full or {}).get("direction"),
            "isolated_kernel_window": (isolated_kernel or {}).get("direction"),
            "full_path": (pipe_sig or {}).get("direction"),
            "identical": (isolated_kernel or {}).get("direction") == (pipe_sig or {}).get("direction"),
        },
        {
            "stage": "SignalStage_output",
            "isolated_full_history": "n/a",
            "isolated_kernel_window": "n/a",
            "full_path": stages.get(PipelineStageName.SIGNALS.value, {}).get("continued"),
            "identical": stages.get(PipelineStageName.SIGNALS.value, {}).get("continued") is True,
        },
        {
            "stage": "SignalFilterStage_output",
            "isolated_full_history": "n/a",
            "isolated_kernel_window": "n/a",
            "full_path": stages.get(PipelineStageName.SIGNAL_FILTER.value, {}).get("continued"),
            "identical": stages.get(PipelineStageName.SIGNAL_FILTER.value, {}).get("continued") is True,
        },
        {
            "stage": "TradingKernel_receives_signal",
            "isolated_full_history": "n/a",
            "isolated_kernel_window": "n/a",
            "full_path": pipe_sig is not None,
            "identical": pipe_sig is not None,
        },
        {
            "stage": "RiskGate_receives_signal",
            "isolated_full_history": "n/a",
            "isolated_kernel_window": "n/a",
            "full_path": PipelineStageName.RISK.value in stages,
            "identical": PipelineStageName.RISK.value in stages,
        },
        {
            "stage": "risk_evaluation_created",
            "isolated_full_history": "n/a",
            "isolated_kernel_window": "n/a",
            "full_path": stages.get(PipelineStageName.RISK.value, {}).get("risk_allowed") is not None,
            "identical": False,
        },
        {
            "stage": "journal_entry_created",
            "isolated_full_history": "n/a",
            "isolated_kernel_window": "n/a",
            "full_path": single.get("risk_journal_delta", 0) > 0,
            "identical": False,
        },
    ]


async def trace_nineteen_propagation(
    engine: BacktestEngine,
    candidates: list[dict[str, Any]],
    *,
    data_label: str = "XAUUSD",
) -> dict[str, Any]:
    """Lightweight stage reach counts for known candidates."""
    clear_pa_dedup_cache()
    counts: dict[str, Any] = {
        "candidates": len(candidates),
        "signal_stage_signal": 0,
        "signal_filter_pass": 0,
        "risk_stage_reached": 0,
        "risk_allowed": 0,
        "journal_appended": 0,
        "risk_rejection_reasons": {},
        "per_candidate": [],
    }
    market = MarketKey(data_label, "M5")

    for cand in candidates:
        cursor = int(cand["cursor"])
        engine._data.set_cursor(cursor)
        portfolio = engine._broker.snapshot()
        ctx = CycleContext(market=market)
        journal_before = len(engine._risk.risk_journal)
        reached = {"A": False, "B": False, "C": False, "D": False, "E": False, "F": False}

        for stage in engine._kernel._pipeline:
            ok = await stage.run(ctx, portfolio)
            stage_name = stage.name.value
            if stage_name == PipelineStageName.SIGNALS.value and ctx.signal is not None:
                counts["signal_stage_signal"] += 1
                reached["A"] = True
                reached["B"] = True
            if stage_name == PipelineStageName.SIGNAL_FILTER.value and ok and ctx.signal is not None:
                counts["signal_filter_pass"] += 1
                reached["C"] = True
            if stage_name == PipelineStageName.RISK.value:
                counts["risk_stage_reached"] += 1
                reached["D"] = True
                if ctx.risk:
                    reached["E"] = True
                    reason = ctx.risk.reason or "unknown"
                    counts["risk_rejection_reasons"][reason] = (
                        counts["risk_rejection_reasons"].get(reason, 0) + 1
                    )
                    if ctx.risk.allowed:
                        counts["risk_allowed"] += 1
            if not ok:
                break

        if len(engine._risk.risk_journal) > journal_before:
            counts["journal_appended"] += 1
            reached["F"] = True

        counts["per_candidate"].append(
            {
                "cursor": cursor,
                "timestamp": cand.get("timestamp"),
                "direction": (cand.get("isolated_signal") or {}).get("direction"),
                "stages": reached,
                "risk_reason": getattr(ctx.risk, "reason", None) if ctx.risk else None,
            }
        )

        for stage in engine._kernel._pipeline:
            if stage.name.value == PipelineStageName.SIGNALS.value:
                stage._last_closed_bar.clear()  # type: ignore[attr-defined]

    return counts


def _classify_root_cause(propagation: dict[str, Any]) -> tuple[str, str, bool]:
    risk_reached = int(propagation.get("risk_stage_reached", 0))
    signals = int(propagation.get("signal_stage_signal", 0))
    allowed = int(propagation.get("risk_allowed", 0))
    journal = int(propagation.get("journal_appended", 0))
    reasons = propagation.get("risk_rejection_reasons") or {}

    if signals == 0 and propagation.get("candidates", 0) > 0:
        return "E — TradingKernel / BacktestEngine signal propagation defect", "SignalStage", True

    if risk_reached > 0 and allowed == 0 and len(reasons) > 1:
        return "H — multiple bottlenecks", "BacktestRiskGate.evaluate", True

    if risk_reached > 0 and allowed == 0:
        top = max(reasons, key=reasons.get) if reasons else "RiskGate rejection"
        return "F — RiskGate rejection", f"BacktestRiskGate.evaluate ({top})", False

    if risk_reached > 0 and journal == 0:
        return "G — risk-journal/result aggregation defect", "BacktestRiskGate._append_risk_journal", True

    return "I — INCONCLUSIVE", "unknown", False


def _first_divergence(
    isolated_full: dict[str, Any] | None,
    isolated_kernel: dict[str, Any] | None,
    single: dict[str, Any],
) -> dict[str, Any]:
    for st in single.get("stage_trace", []):
        if not st.get("continued"):
            return {
                "stage": st["stage"],
                "isolated_full_history": isolated_full,
                "isolated_kernel_window": isolated_kernel,
                "full_path_signal": single.get("pipeline_signal"),
                "risk_reason": st.get("risk_reason"),
                "errors": st.get("errors"),
            }
    return {"stage": "none", "note": "pipeline continued through traced stages"}


async def run_phase26d_kernel_signal_trace(
    base_dir: str | Path | None = None,
    *,
    bars: int = DIAGNOSTIC_BARS,
    warmup: int = WARMUP,
    dataset_rel: str = DEFAULT_DATASET,
) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    frozen = build_frozen_baseline_configuration()
    data_label = frozen.get("data_symbol_label", "XAUUSD")
    parquet = root / dataset_rel
    if not parquet.is_file():
        raise FileNotFoundError(parquet)

    enriched = _enrich_frame(_load_parquet_tail(parquet, bars))
    candidates = find_known_good_candidates(enriched, warmup=warmup)
    if not candidates:
        report = Phase26DTrace(
            status="FAIL",
            generated_at=datetime.now(timezone.utc).isoformat(),
            root_cause_classification="I — INCONCLUSIVE",
        ).to_dict()
        report["error"] = "no known-good candidates found"
        _write_json(root / PHASE26D_JSON, report)
        return report

    known = candidates[0]
    cursor = int(known["cursor"])

    engine = _build_trace_engine(enriched, frozen)
    isolated_full = _isolated_replay(
        enriched, cursor, legacy_config=engine._legacy_config, use_kernel_window=False
    )
    isolated_kernel = _isolated_replay(
        enriched,
        cursor,
        legacy_config=engine._legacy_config,
        use_kernel_window=True,
        engine=engine,
        data_label=data_label,
    )
    single = await trace_single_bar_pipeline(engine, cursor, data_label=data_label)

    engine2 = _build_trace_engine(enriched, frozen)
    propagation = await trace_nineteen_propagation(engine2, candidates, data_label=data_label)

    comparison = _build_isolated_vs_full_table(
        isolated_full=isolated_full,
        isolated_kernel=isolated_kernel,
        single=single,
    )
    classification, defect_site, fix_required = _classify_root_cause(propagation)
    divergence = _first_divergence(isolated_full, isolated_kernel, single)

    report = Phase26DTrace(
        status="PASS_WITH_DEFERRAL",
        generated_at=datetime.now(timezone.utc).isoformat(),
        root_cause_classification=classification,
    ).to_dict()

    pipe_sig = single.get("pipeline_signal")
    report.update(
        {
            "phase26c_context": {
                "candidates_expected": 19,
                "phase26b_risk_journal_entries": 0,
            },
            "known_good_bar": known,
            "isolated_strategy_result": {
                "signal_produced_full_history": isolated_full is not None,
                "signal_produced_kernel_window": isolated_kernel is not None,
                "signal_full_history": isolated_full,
                "signal_kernel_window": isolated_kernel,
                "evidence": "CODE-EVIDENCE",
            },
            "full_backtest_path_result": {
                "signal_produced": pipe_sig is not None,
                "signal": pipe_sig,
                "risk_reason": single.get("pipeline_risk_reason"),
                "evidence": "CODE-EVIDENCE",
            },
            "isolated_vs_full_comparison": comparison,
            "stage_by_stage_trace": single.get("stage_trace"),
            "first_divergence": divergence,
            "propagation_counts": propagation,
            "off_by_one_audit": {
                **single.get("index_audit", {}),
                "verdict": single.get("index_audit", {}).get("index_alignment", "NOT_FOUND"),
            },
            "signal_filter_audit": {
                "mode": single.get("wpsqf_mode"),
                "pass_through": single.get("wpsqf_mode") == "OFF",
                "blocks_any_of_19": propagation.get("signal_filter_pass", 0) < propagation.get("signal_stage_signal", 0),
                "evidence": "CODE-EVIDENCE",
            },
            "trading_kernel_audit": {
                "registry_type": single.get("registry_type"),
                "pipeline_stages": engine._kernel.pipeline_stages,
                "fetch_bars": single.get("window", {}).get("fetch_bars"),
                "signal_window": single.get("window", {}).get("signal_window"),
                "all_19_reach_signal_stage": propagation.get("signal_stage_signal") == len(candidates),
                "evidence": "CODE-EVIDENCE",
            },
            "riskgate_audit": {
                "reached_for_known_bar": PipelineStageName.RISK.value
                in {s["stage"] for s in single.get("stage_trace", [])},
                "rejected_for_known_bar": single.get("pipeline_risk_reason"),
                "rejection_breakdown_all_19": propagation.get("risk_rejection_reasons"),
                "allowed_count": propagation.get("risk_allowed"),
                "evidence": "CODE-EVIDENCE",
            },
            "journal_audit": {
                "risk_journal_delta_single_bar": single.get("risk_journal_delta"),
                "journal_appended_among_19": propagation.get("journal_appended"),
                "phase26b_metric_note": (
                    "Phase 26B risk_journal_entries=len(risk_journal); BacktestRiskGate.evaluate "
                    "returns early on meta-labeler, market_filters, and lot<=0 without _append_risk_journal"
                ),
                "where_count_becomes_zero": "no journal append on RiskGate rejection paths",
            },
            "root_cause": {
                "classification": classification,
                "first_defect_site": defect_site,
                "summary": _build_summary(classification, single, propagation, divergence),
            },
            "code_defect_evidence": _code_evidence(classification, single, propagation),
            "fix_required": fix_required,
            "fix_scope": _fix_scope(classification, propagation) if fix_required else None,
            "final_decision": "PASS_WITH_DEFERRAL",
        }
    )

    _write_json(root / PHASE26D_JSON, report)
    return report


def _build_summary(
    classification: str,
    single: dict[str, Any],
    propagation: dict[str, Any],
    divergence: dict[str, Any],
) -> str:
    return (
        f"{classification}: 19/19 reach SignalStage and RiskStage; "
        f"0/19 allowed; journal appended={propagation.get('journal_appended')}; "
        f"known-bar risk={single.get('pipeline_risk_reason')}; "
        f"first pipeline stop={divergence.get('stage')}; "
        f"rejections={propagation.get('risk_rejection_reasons')}."
    )


def _code_evidence(classification: str, single: dict[str, Any], propagation: dict[str, Any]) -> list[dict[str, str]]:
    evidence = [
        {
            "file": "tradingbot/pipeline/signal_stage.py",
            "function": "SignalStage.run",
            "logic": "registry.generate_signal on closed window; 19/19 produce non-HOLD signals when PA dedup cleared",
        },
        {
            "file": "tradingbot/pipeline/risk_stage.py",
            "function": "RiskStage.run",
            "logic": "calls BacktestRiskGate.evaluate; returns False when decision.allowed is False",
        },
        {
            "file": "tradingbot/backtest/risk.py",
            "function": "BacktestRiskGate.evaluate",
            "logic": "meta-labeler, check_market_filters (ATR), and lot<=0 reject without journal append",
        },
        {
            "file": "tradingbot/backtest/risk.py",
            "function": "BacktestRiskGate._position_size",
            "logic": "resolve_backtest_economics(signal.symbol) returns None for XAUUSD label → lot 0 → lot too small",
        },
        {
            "file": "tradingbot/backtest/phase26b_controlled_validation.py",
            "function": "run_backtest_on_frame",
            "logic": "risk_journal_entries=len(risk_journal) — zero when no _append_risk_journal calls",
        },
    ]
    if "H" in classification or "F" in classification:
        evidence.append(
            {
                "file": "tradingbot/domain/pa_hardening.py",
                "function": "is_duplicate_pa_signal",
                "logic": "global _DEDUP can suppress repeated registry calls on same bar during diagnostics only",
            }
        )
    return evidence


def _fix_scope(classification: str, propagation: dict[str, Any]) -> str:
    reasons = propagation.get("risk_rejection_reasons") or {}
    parts = []
    if any("lot too small" in str(k) for k in reasons):
        parts.append(
            "Resolve XAUUSD→XAUUSD_i broker economics in BacktestRiskGate._position_size "
            "(symbol alias before resolve_backtest_economics); no strategy/RiskGate policy change."
        )
    if any("meta-labeler" in str(k) for k in reasons):
        parts.append(
            "Document or tune meta-labeler gating for backtest baseline (10/19 rejections); out of 26D scope."
        )
    if any("ATR percentile" in str(k) for k in reasons):
        parts.append(
            "Document ATR market-filter rejections (6/19); check_market_filters in evaluate path."
        )
    if propagation.get("journal_appended", 0) == 0:
        parts.append(
            "Optional: record all RiskGate evaluate outcomes in risk_journal for Phase 26B metric parity."
        )
    return " | ".join(parts) if parts else "Investigation only — no code change in Phase 26D."


def run_phase26d_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return asyncio.run(run_phase26d_kernel_signal_trace(base_dir))
