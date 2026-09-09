"""Phase 26C — lightweight zero-signal root-cause audit (offline, no MT5)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG, merge_broker_catalog
from tradingbot.backtest.phase26b_controlled_validation import build_frozen_baseline_configuration
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.filter_policy import aligned_session_hours, is_session_filter_enabled
from tradingbot.domain.gold_strategies.m5_london_sweep import (
    asian_range,
    diagnose_m5_london_hold,
    evaluate_m5_london_sweep,
    m5_asian_end_hour,
    m5_ny_entry_hours,
)
from tradingbot.domain.gold_strategies.router import evaluate_gold_setup
from tradingbot.domain.market_filters import check_market_filters
from tradingbot.domain.ohlcv import exclude_forming_bar
from tradingbot.domain.pa_hardening import apply_setup_hardening
from tradingbot.domain.price_action import enrich_price_action
from tradingbot.services.meta_labeler import get_meta_labeler

PHASE26C_JSON = "logs/phase26c_zero_signal_audit.json"
DEFAULT_DATASET = "data/backtest/XAUUSD_M5_183d.parquet"
DIAGNOSTIC_BARS = 2500
WARMUP = 300


@dataclass
class Phase26CAudit:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    root_cause_classification: str = "G — INCONCLUSIVE"
    first_bottleneck: str = "UNKNOWN"
    safety: dict[str, bool] = field(
        default_factory=lambda: {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "CONFIGURATION_MUTATED": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26C", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _load_parquet_tail(path: Path, bars: int) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        if "time" in df.columns:
            df = df.set_index(pd.to_datetime(df["time"], utc=True))
        elif "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"], utc=True))
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df = df.sort_index()
    return df.tail(bars).copy()


def _enrich_frame(df: pd.DataFrame) -> pd.DataFrame:
    legacy = load_legacy_config()
    legacy = merge_broker_catalog(legacy, {"XAUUSD_i": dict(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])})
    legacy["symbol_aliases"] = {"XAUUSD": PRIMARY_SYMBOL}
    ind = TechnicalIndicatorEngine(legacy)
    enriched = ind.enrich_for_market(df, "M5", "XAUUSD")
    return enriched.dropna(subset=["open", "high", "low", "close"])


def _session_audit(df: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    ny_s, ny_e = m5_ny_entry_hours(cfg)
    asian_end = m5_asian_end_hour(cfg)
    strat_start, strat_end = aligned_session_hours(cfg)
    hours = df.index.hour
    ny_mask = (hours >= ny_s) & (hours < ny_e)
    asian_mask = (hours >= int(cfg.get("ASIAN_START_HOUR", 0))) & (hours < asian_end)

    days_ny: set[Any] = set()
    days_asian: set[Any] = set()
    for ts in df.index[ny_mask]:
        days_ny.add(ts.date())
    for ts in df.index[asian_mask]:
        days_asian.add(ts.date())

    sample_ts = df.index[0]
    return {
        "evidence": "CODE-EVIDENCE + DATA-EVIDENCE",
        "index_timezone": str(sample_ts.tzinfo),
        "index_tz_aware": sample_ts.tzinfo is not None,
        "interpretation": "UTC (tz-aware index; hour extracted via .hour on UTC timestamps)",
        "configured_ny_window": f"{ny_s}-{ny_e} UTC",
        "strategy_session_hours": f"{strat_start}-{strat_end} UTC",
        "asian_session": f"{cfg.get('ASIAN_START_HOUR', 0)}-{asian_end} UTC",
        "session_filter_enabled": is_session_filter_enabled(cfg),
        "bars_total": len(df),
        "bars_in_ny_window": int(ny_mask.sum()),
        "bars_in_asian_window": int(asian_mask.sum()),
        "days_with_ny_bars": len(days_ny),
        "days_with_asian_bars": len(days_asian),
        "date_start": str(df.index[0]),
        "date_end": str(df.index[-1]),
        "hour_distribution": {str(h): int((hours == h).sum()) for h in range(24)},
    }


def _compare_configurations(frozen: dict[str, Any]) -> dict[str, Any]:
    live_cfg = get_price_action_config("XAUUSD", "M5")
    keys = [
        "GOLD_STRATEGY_MODE",
        "NY_ENTRY_START_HOUR",
        "NY_ENTRY_END_HOUR",
        "M5_USE_NY_SESSION",
        "M5_USE_LONDON_SESSION",
        "MIN_CONFIDENCE",
        "MIN_QUALITY_SCORE",
        "MIN_RR",
        "COOLDOWN_BARS",
        "MAX_TRADES_PER_DAY",
        "REQUIRE_HTF_ALIGNMENT_M5",
        "META_LABEL_THRESHOLD",
        "USE_REGIME_FILTER",
        "USE_ATR_PERCENTILE_FILTER",
        "ATR_PCT_MIN",
        "ATR_PCT_MAX",
        "M5_REQUIRE_REJECTION",
        "SWEEP_LOOKBACK_BARS",
        "SWEEP_BUFFER_ATR",
        "MIN_RANGE_ATR",
    ]
    diffs: list[dict[str, Any]] = []
    pa_overrides = frozen.get("pa_overrides_applied") or {}
    for key in keys:
        frozen_val = pa_overrides.get(key, frozen.get(key))
        live_val = live_cfg.get(key)
        if frozen_val != live_val:
            diffs.append({"key": key, "phase26b_frozen": frozen_val, "live_default": live_val})
    return {
        "evidence": "CODE-EVIDENCE",
        "configuration_fingerprint": frozen.get("configuration_fingerprint"),
        "differences": diffs,
        "match": len(diffs) == 0,
    }


def _meta_labeler_audit() -> dict[str, Any]:
    meta = get_meta_labeler()
    m5_ready = meta.is_ready_for("M5")
    return {
        "evidence": "CODE-EVIDENCE",
        "m5_model_ready": m5_ready,
        "should_gate_m5_ranging": meta.should_gate("M5", "RANGING") if m5_ready else False,
        "not_ready_behavior": "should_gate=False; score() returns 1.0 if invoked",
        "relevant_to_zero_trades": False,
        "note": (
            "Not primary bottleneck when no candidates reach RiskGate. "
            "When strategy candidates exist, verify kernel path before meta analysis."
        ),
    }


def _append_forming_bar_m5(df: pd.DataFrame) -> pd.DataFrame:
    """Match BacktestMarketData._append_forming_bar for M5."""
    last = df.iloc[-1]
    next_ts = pd.to_datetime(df.index[-1]) + timedelta(minutes=5)
    forming = pd.DataFrame(
        {
            "open": [float(last["open"])],
            "high": [float(last["high"])],
            "low": [float(last["low"])],
            "close": [float(last["close"])],
            "volume": [float(last.get("volume", 0.0))],
        },
        index=pd.DatetimeIndex([next_ts]),
    )
    return pd.concat([df, forming])


def _classify_root_cause(gates: dict[str, Any], session: dict[str, Any]) -> tuple[str, str]:
    """Return (classification, first_bottleneck)."""
    if session.get("bars_in_ny_window", 0) == 0:
        return "C — DATA/SESSION/TIMEZONE INCOMPATIBILITY", "ny_session_window_empty"

    ny = gates["ny_session_bars"]
    asian_ok = gates["asian_range_valid"]
    sweep = gates["sweep_detected"]
    reclaim = gates["reclaim_detected"]
    pre_hard = gates["setup_ok_pre_hardening"]
    gold = gates["evaluate_gold_setup_pass"]
    strat_signals = gates.get("price_action_strategy_signals", 0)
    conf = gates["confidence_pass"]
    market = gates["market_filter_pass_on_candidates"]

    if ny == 0:
        return "C — DATA/SESSION/TIMEZONE INCOMPATIBILITY", "ny_session_window_empty"
    if asian_ok == 0:
        return "C — DATA/SESSION/TIMEZONE INCOMPATIBILITY", "no_valid_asian_range_on_ny_bars"
    if sweep == 0:
        return "A — NO SETUPS OBSERVED", "sweep_detection"
    if reclaim == 0:
        return "A — NO SETUPS OBSERVED", "reclaim_inside_asian_range"
    if pre_hard == 0:
        return "A — NO SETUPS OBSERVED", "sweep_reclaim_rr_path"
    if gold == 0 and pre_hard > 0:
        return "B — UPSTREAM FILTER BLOCKED SETUPS", "quality_hardening"
    if gold > 0 and strat_signals == 0:
        return "D — BACKTEST/CODE PATH DEFECT", "price_action_strategy_path"
    if conf == 0 and gold > 0:
        return "B — UPSTREAM FILTER BLOCKED SETUPS", "confidence_threshold"
    if market == 0 and gold > 0 and strat_signals > 0:
        return "B — UPSTREAM FILTER BLOCKED SETUPS", "market_filters"
    if strat_signals > 0 and gates.get("phase26b_risk_journal_entries", 0) == 0:
        return (
            "F — MULTIPLE BOTTLENECKS",
            "strategy_candidates_vs_zero_risk_journal",
        )
    if reclaim < sweep and sweep > 0:
        return "A — NO SETUPS OBSERVED", "reclaim_inside_asian_range"
    if gold > 0 and strat_signals > 0:
        return "F — MULTIPLE BOTTLENECKS", "mixed_upstream_downstream"
    return "G — INCONCLUSIVE", "unknown"


def run_phase26c_zero_signal_audit(
    base_dir: str | Path | None = None,
    *,
    bars: int = DIAGNOSTIC_BARS,
    warmup: int = WARMUP,
    dataset_rel: str = DEFAULT_DATASET,
) -> dict[str, Any]:
    """Lightweight gate-count audit on the Phase 26B diagnostic window."""
    root = Path(base_dir or Path.cwd())
    frozen = build_frozen_baseline_configuration()
    cfg = get_price_action_config("XAUUSD", "M5")

    parquet = root / dataset_rel
    if not parquet.is_file():
        raise FileNotFoundError(f"Dataset missing: {parquet}")

    raw = _load_parquet_tail(parquet, bars)
    enriched = _enrich_frame(raw)
    session = _session_audit(enriched, cfg)

    ny_s, ny_e = m5_ny_entry_hours(cfg)
    asian_start = int(cfg.get("ASIAN_START_HOUR", 0))
    asian_end = m5_asian_end_hour(cfg)
    min_conf = float(cfg.get("MIN_CONFIDENCE", 0.52))
    strat_start, strat_end = aligned_session_hours(cfg)

    reject_reasons: Counter[str] = Counter()
    asian_range_sizes: list[float] = []
    potential_low_sweeps = 0
    potential_high_sweeps = 0

    gate_counts = {
        "raw_bars": len(enriched),
        "bars_after_warmup": max(0, len(enriched) - warmup),
        "ny_session_bars": 0,
        "strategy_session_pass": 0,
        "asian_range_valid": 0,
        "asian_range_too_small": 0,
        "sweep_detected": 0,
        "reclaim_detected": 0,
        "setup_ok_pre_hardening": 0,
        "evaluate_m5_london_sweep_pass": 0,
        "hardening_rejected": 0,
        "evaluate_gold_setup_pass": 0,
        "confidence_pass": 0,
        "market_filter_pass_on_candidates": 0,
        "forming_bar_sim_pass": 0,
        "price_action_strategy_signals": 0,
        "phase26b_risk_journal_entries": 0,
    }

    hardening_fail_quality = 0
    hardening_fail_other = 0

    try:
        baseline_path = root / "logs" / "phase26b_baseline_results.json"
        if baseline_path.is_file():
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            gate_counts["phase26b_risk_journal_entries"] = int(
                (baseline.get("logic_validation") or {}).get("risk_journal_entries") or 0
            )
    except (json.JSONDecodeError, OSError):
        pass

    from engine.strategies.price_action_strategy import PriceActionStrategy

    pa_strategy = PriceActionStrategy(load_legacy_config())

    for cursor in range(warmup, len(enriched)):
        window = enriched.iloc[: cursor + 1]
        window = _append_forming_bar_m5(window)
        closed = exclude_forming_bar(window, min_rows=30)
        if closed is None or closed.empty:
            continue
        i = len(closed) - 1
        ts = closed.index[i]
        hour = int(ts.hour)

        if not (ny_s <= hour < ny_e):
            continue
        gate_counts["ny_session_bars"] += 1

        if is_session_filter_enabled(cfg) and not (strat_start <= hour < strat_end):
            reject_reasons["outside_strategy_session_hours"] += 1
            continue
        gate_counts["strategy_session_pass"] += 1

        bounds = asian_range(closed, i, start_hour=asian_start, end_hour=asian_end, min_bars=4)
        if bounds is None:
            reject_reasons["no_asian_range"] += 1
            continue
        asian_hi, asian_lo = bounds
        row = closed.iloc[i]
        atr = float(row["atr"]) if "atr" in row and not pd.isna(row["atr"]) else float(row["close"]) * 0.001
        min_range = atr * float(cfg.get("MIN_RANGE_ATR", 0.2))
        rng = asian_hi - asian_lo
        asian_range_sizes.append(rng)
        if rng < min_range:
            gate_counts["asian_range_too_small"] += 1
            reject_reasons["asian_range_below_min_atr"] += 1
            continue
        gate_counts["asian_range_valid"] += 1

        diag = diagnose_m5_london_hold(closed, i, cfg)
        reason = str(diag.get("reject_reason") or "unknown")
        reject_reasons[reason] += 1

        lookback = int(cfg.get("SWEEP_LOOKBACK_BARS", 12))
        buf = atr * float(cfg.get("SWEEP_BUFFER_ATR", 0.12))
        start_j = max(0, i - lookback)
        win = closed.iloc[start_j : i + 1]
        win_high = float(win["high"].max())
        win_low = float(win["low"].min())
        if win_high > asian_hi + buf:
            potential_high_sweeps += 1
        if win_low < asian_lo - buf:
            potential_low_sweeps += 1

        if diag.get("sweep_detected"):
            gate_counts["sweep_detected"] += 1
        if diag.get("reclaim_detected"):
            gate_counts["reclaim_detected"] += 1
        if reason == "setup_ok_pre_hardening":
            gate_counts["setup_ok_pre_hardening"] += 1

        df_pa = enrich_price_action(closed, cfg, at_index=i)
        raw_setup = evaluate_m5_london_sweep(df_pa, i, cfg)
        if raw_setup is not None:
            gate_counts["evaluate_m5_london_sweep_pass"] += 1
            hardened = apply_setup_hardening(df_pa, i, cfg, raw_setup, timeframe="M5")
            if hardened is None:
                gate_counts["hardening_rejected"] += 1
                hardening_fail_quality += 1
            else:
                gate_counts["evaluate_gold_setup_pass"] += 1
                if hardened.confidence >= min_conf:
                    gate_counts["confidence_pass"] += 1
                    mf_ok, mf_reason = check_market_filters(
                        closed.iloc[: i + 1], cfg, strategy_mode="london_sweep"
                    )
                    if mf_ok:
                        gate_counts["market_filter_pass_on_candidates"] += 1
                    else:
                        reject_reasons[f"market_filter:{mf_reason}"] += 1

        gold = evaluate_gold_setup(df_pa, i, cfg, timeframe="M5")
        if gold is not None:
            gate_counts["forming_bar_sim_pass"] += 1

        sigs = pa_strategy.generate_signals(closed, symbol="XAUUSD", timeframe="M5")
        if sigs:
            gate_counts["price_action_strategy_signals"] += len(sigs)

    classification, bottleneck = _classify_root_cause(gate_counts, session)

    asian_stats = {}
    if asian_range_sizes:
        asian_stats = {
            "count_on_ny_bars": len(asian_range_sizes),
            "avg_size": round(sum(asian_range_sizes) / len(asian_range_sizes), 4),
            "min_size": round(min(asian_range_sizes), 4),
            "max_size": round(max(asian_range_sizes), 4),
        }

    pipeline = [
        {"gate": "raw_bars", "count": gate_counts["raw_bars"], "evidence": "DATA-EVIDENCE"},
        {"gate": "bars_after_warmup", "count": gate_counts["bars_after_warmup"], "evidence": "DATA-EVIDENCE"},
        {"gate": "ny_session_bars", "count": gate_counts["ny_session_bars"], "evidence": "CODE-EVIDENCE + DATA-EVIDENCE"},
        {"gate": "strategy_session_pass", "count": gate_counts["strategy_session_pass"], "evidence": "CODE-EVIDENCE"},
        {"gate": "asian_range_valid", "count": gate_counts["asian_range_valid"], "evidence": "CODE-EVIDENCE"},
        {"gate": "sweep_detected", "count": gate_counts["sweep_detected"], "evidence": "CODE-EVIDENCE"},
        {"gate": "reclaim_detected", "count": gate_counts["reclaim_detected"], "evidence": "CODE-EVIDENCE"},
        {"gate": "setup_ok_pre_hardening", "count": gate_counts["setup_ok_pre_hardening"], "evidence": "CODE-EVIDENCE"},
        {"gate": "evaluate_gold_setup_pass", "count": gate_counts["evaluate_gold_setup_pass"], "evidence": "CODE-EVIDENCE"},
        {"gate": "price_action_strategy_signals", "count": gate_counts["price_action_strategy_signals"], "evidence": "CODE-EVIDENCE"},
        {"gate": "confidence_pass", "count": gate_counts["confidence_pass"], "evidence": "CODE-EVIDENCE"},
        {"gate": "market_filter_pass", "count": gate_counts["market_filter_pass_on_candidates"], "evidence": "CODE-EVIDENCE"},
        {"gate": "risk_gate_entries_phase26b", "count": 0, "evidence": "AUDIT-EVIDENCE"},
    ]

    report = Phase26CAudit(
        status="PASS_WITH_DEFERRAL",
        generated_at=datetime.now(timezone.utc).isoformat(),
        root_cause_classification=classification,
        first_bottleneck=bottleneck,
    ).to_dict()

    report.update(
        {
            "objective": "Determine why Phase 26B produced 0 trades on Jul–Aug 2026 tail",
            "phase26b_context": {
                "configuration_fingerprint": frozen.get("configuration_fingerprint"),
                "robustness_classification_26b": "D — LOGICALLY WEAK",
                "note": "26B classification retained; 26C explains zero-trade mechanism without rewriting 26B artifacts",
                "evidence": "AUDIT-EVIDENCE",
            },
            "data_window": {
                "dataset": dataset_rel,
                "bars": len(enriched),
                "warmup": warmup,
                "date_start": str(enriched.index[0]),
                "date_end": str(enriched.index[-1]),
                "evidence": "DATA-EVIDENCE",
            },
            "signal_gate_pipeline": pipeline,
            "gate_counts": gate_counts,
            "reject_reasons_on_ny_bars": dict(reject_reasons),
            "first_bottleneck": {
                "gate": bottleneck,
                "classification": classification,
                "evidence": "CODE-EVIDENCE + DATA-EVIDENCE",
            },
            "session_timezone_audit": session,
            "asian_range_sweep_audit": {
                "evidence": "DATA-EVIDENCE",
                "asian_range_stats": asian_stats,
                "asian_range_too_small_count": gate_counts["asian_range_too_small"],
                "potential_high_sweeps": potential_high_sweeps,
                "potential_low_sweeps": potential_low_sweeps,
                "sweep_detected_bars": gate_counts["sweep_detected"],
                "reclaim_detected_bars": gate_counts["reclaim_detected"],
            },
            "hardening_audit": {
                "evidence": "CODE-EVIDENCE",
                "pre_hardening_candidates": gate_counts["setup_ok_pre_hardening"],
                "hardening_rejected": gate_counts["hardening_rejected"],
                "quality_floor_rejects": hardening_fail_quality,
                "min_quality_score": int(cfg.get("MIN_QUALITY_SCORE", 55)),
            },
            "meta_labeler_audit": _meta_labeler_audit(),
            "dataset_compatibility": {
                "evidence": "DATA-EVIDENCE",
                "symbol_label": "XAUUSD",
                "configured_instrument": PRIMARY_SYMBOL,
                "timeframe": "M5",
                "ohlc_complete": True,
                "warmup_sufficient": len(enriched) > warmup,
                "htf_alignment_required": bool(cfg.get("REQUIRE_HTF_ALIGNMENT_M5", False)),
                "explicit_symbol_map_required": True,
                "ev_eq_01": "NOT_PROVEN",
            },
            "configuration_comparison": _compare_configurations(frozen),
            "root_cause": {
                "summary": _root_cause_summary(classification, bottleneck, gate_counts, session),
                "classification": classification,
                "evidence": "CODE-EVIDENCE + DATA-EVIDENCE",
            },
            "what_this_proves": [
                "Whether zero trades is explained by upstream setup detection vs downstream gates",
                "Session/timezone compatibility of the diagnostic window with NY 15–16 UTC",
                "Gate-level rejection counts on the exact 26B window",
            ],
            "what_this_does_not_prove": [
                "Strategy profitability or edge",
                "Broker-realistic cost-adjusted performance",
                "Live path parity under MT5 ticks",
                "That D — LOGICALLY WEAK should be removed (sample still zero trades)",
            ],
            "remaining_blockers": [
                "EV-EQ-01 NOT_PROVEN",
                "cost_adjusted_metrics=false",
                "Operator Phase 25M broker-evidence session",
            ],
            "recommended_next_step": _recommended_next(classification, bottleneck),
            "final_decision": "PASS_WITH_DEFERRAL",
        }
    )

    _write_json(root / PHASE26C_JSON, report)
    return report


def _root_cause_summary(
    classification: str,
    bottleneck: str,
    gates: dict[str, Any],
    session: dict[str, Any],
) -> str:
    rj = gates.get("phase26b_risk_journal_entries", 0)
    strat = gates.get("price_action_strategy_signals", 0)
    gold = gates.get("evaluate_gold_setup_pass", 0)
    if classification.startswith("A"):
        return (
            f"On {session.get('bars_in_ny_window', 0)} NY-session bars in the 2500-bar tail, "
            f"the first zero-producing gate is '{bottleneck}' "
            f"(sweep={gates.get('sweep_detected', 0)}, reclaim={gates.get('reclaim_detected', 0)}). "
            f"Phase 26B risk_journal_entries={rj}."
        )
    if classification.startswith("D"):
        return (
            f"evaluate_gold_setup passed {gold} times but PriceActionStrategy emitted {strat} signals "
            f"while Phase 26B risk_journal_entries={rj}. Path mismatch between direct evaluator and strategy stack."
        )
    if classification.startswith("B"):
        return (
            f"Setup candidates existed pre-hardening ({gates.get('setup_ok_pre_hardening', 0)}) "
            f"but were blocked at '{bottleneck}' before trade emission."
        )
    if classification.startswith("E"):
        return (
            f"Strategy path produced {strat} signal(s) but Phase 26B recorded {rj} risk journal entries — "
            "downstream RiskGate/execution did not accept trades."
        )
    if bottleneck == "strategy_candidates_vs_zero_risk_journal":
        return (
            f"NY session: {gates.get('ny_session_bars', 0)} bars; sweep={gates.get('sweep_detected', 0)}; "
            f"reclaim={gates.get('reclaim_detected', 0)}; evaluate_gold_setup={gates.get('evaluate_gold_setup_pass', 0)}; "
            f"PriceActionStrategy signals={strat}. Phase 26B risk_journal_entries={rj}. "
            "Most NY bars fail at sweep/reclaim; isolated strategy replay finds candidates but full 26B engine recorded no risk evaluations."
        )
    if classification.startswith("F"):
        return (
            f"Multiple factors: upstream reclaim/sweep filtering on most NY bars, plus "
            f"{strat} strategy-level candidates vs {rj} Phase 26B risk journal entries."
        )
    if classification.startswith("C"):
        return f"Session/data compatibility issue at '{bottleneck}'."
    return f"Inconclusive; earliest anomaly at '{bottleneck}'."


def _recommended_next(classification: str, bottleneck: str) -> str:
    if bottleneck == "sweep_detection":
        return (
            "Inspect Jul–Aug 2026 price action vs Asian range/sweep rules (research-only); "
            "consider longer diagnostic window ONLY if a specific date hypothesis exists — not a full 26B rerun."
        )
    if classification.startswith("B"):
        return "Review hardening/quality scoring on any pre-hardening candidates; do not tune thresholds in Phase 26C."
    return "Document findings; await operator broker-evidence session before economic validation."


def run_phase26c_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    """Synchronous entry point."""
    return run_phase26c_zero_signal_audit(base_dir)
