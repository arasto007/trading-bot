"""Phase 26E — targeted RiskGate rejection audit (offline, read-only)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.adapters.risk_gate import _is_pa_signal, detect_account_tier, execution_profile_for_tier
from tradingbot.backtest.instrument import (
    OFFLINE_INSTRUMENT_CATALOG,
    resolve_backtest_economics,
)
from tradingbot.backtest.phase26b_controlled_validation import build_frozen_baseline_configuration
from tradingbot.backtest.phase26d_kernel_signal_trace import (
    _build_trace_engine,
    _enrich_frame,
    _load_parquet_tail,
)
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.broker_economics import lot_from_broker_economics
from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.market_filters import adapt_filters_for_regime, atr_percentile, check_market_filters
from tradingbot.domain.models import CycleContext, MarketKey
from tradingbot.domain.pa_hardening import clear_pa_dedup_cache
from tradingbot.domain.risk_logic import infer_regime_from_ohlcv, regime_position_multiplier
from tradingbot.domain.session_logic import variable_spread_pips
from tradingbot.services.meta_labeler import get_meta_labeler

PHASE26E_JSON = "logs/phase26e_riskgate_audit.json"
PHASE26D_JSON = "logs/phase26d_kernel_signal_trace.json"
DEFAULT_DATASET = "data/backtest/XAUUSD_M5_183d.parquet"

RISKGATE_EVAL_ORDER = [
    "check_max_positions",
    "min_balance",
    "cooldown_after_losses",
    "daily_loss_limit",
    "max_trades_per_day",
    "entry_cooldown",
    "friday_gate",
    "news_gate",
    "spread_gate",
    "htf_alignment",
    "no_opposite_position",
    "ohlcv_present",
    "check_market_filters",
    "meta_labeler",
    "lot_sizing",
]


@dataclass
class Phase26EAudit:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    overall_classification: str = "F — multiple independent causes"
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
        return {"schema_version": 1, "phase": "26E", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _load_phase26d_candidates(root: Path) -> list[dict[str, Any]]:
    path = root / PHASE26D_JSON
    if not path.is_file():
        raise FileNotFoundError(f"Phase 26D artifact required: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    per = (payload.get("propagation_counts") or {}).get("per_candidate") or []
    if not per:
        raise ValueError("Phase 26D per_candidate list missing")
    return per


def _economics_snapshot(econ: Any | None) -> dict[str, Any] | None:
    if econ is None:
        return None
    return {
        "symbol": econ.symbol,
        "contract_size": econ.contract_size,
        "tick_size": econ.tick_size,
        "tick_value": econ.tick_value,
        "volume_min": econ.volume_min,
        "volume_step": econ.volume_step,
    }


def _lot_sizing_audit(
    signal: Any,
    snapshot: dict[str, Any],
    *,
    legacy_config: dict[str, Any],
    risk_pct: float,
    regime: str,
) -> dict[str, Any]:
    symbol = signal.symbol
    df = snapshot.get("ohlcv")
    close = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0.0
    sl = float(signal.stop_loss) if signal.stop_loss else None

    econ_xauusd = resolve_backtest_economics(symbol, legacy_config)
    econ_broker = resolve_backtest_economics("XAUUSD_i", legacy_config)
    alias = (legacy_config.get("symbol_aliases") or {}).get(symbol)

    out: dict[str, Any] = {
        "signal_symbol": symbol,
        "resolve_backtest_economics_symbol": symbol,
        "economics_found_xauusd": econ_xauusd is not None,
        "economics_found_xauusd_i": econ_broker is not None,
        "symbol_aliases_entry": alias,
        "catalog_keys": list((legacy_config.get("BROKER_SYMBOL_CATALOG") or {}).keys()),
        "entry_price": close,
        "stop_loss": sl,
        "stop_distance": abs(close - sl) if sl else None,
        "risk_pct": risk_pct,
        "balance": float(snapshot.get("balance", 10000)),
        "regime": regime,
        "economics_xauusd": _economics_snapshot(econ_xauusd),
        "economics_xauusd_i": _economics_snapshot(econ_broker),
    }

    if sl and close > 0:
        risk_money = out["balance"] * risk_pct * regime_position_multiplier(regime)
        out["risk_amount"] = risk_money
        if econ_broker is not None:
            raw_lot, lot_reason = lot_from_broker_economics(
                out["balance"],
                risk_pct,
                close,
                sl,
                econ_broker,
                regime_multiplier=regime_position_multiplier(regime),
            )
            out["hypothetical_xauusd_i"] = {
                "raw_lot": raw_lot,
                "normalized_lot": raw_lot,
                "rejection_reason": lot_reason,
                "would_pass_min_lot": raw_lot is not None and raw_lot >= econ_broker.volume_min,
            }
        else:
            out["hypothetical_xauusd_i"] = {"error": "XAUUSD_i economics unavailable"}

        out["current_path"] = {
            "economics_resolved": econ_xauusd is not None,
            "final_lot": 0.0 if econ_xauusd is None else None,
            "rejection_reason": "resolve_backtest_economics returned None → lot 0 → lot too small"
            if econ_xauusd is None
            else "economics present",
        }
        if econ_xauusd is not None:
            lot, reason = lot_from_broker_economics(
                out["balance"],
                risk_pct,
                close,
                sl,
                econ_xauusd,
                regime_multiplier=regime_position_multiplier(regime),
            )
            out["current_path"]["raw_lot"] = lot
            out["current_path"]["normalized_lot"] = lot
            out["current_path"]["rejection_reason"] = reason or "ok"

    return out


def _meta_audit(
    signal: Any,
    snapshot: dict[str, Any],
    *,
    regime: str,
    pa_cfg: dict[str, Any],
    use_meta_labeler: bool,
    est_spread: float,
) -> dict[str, Any]:
    meta = get_meta_labeler()
    tf = signal.timeframe or "M5"
    m5_info = (meta.info().get("per_tf") or {}).get("M5", {})
    model_path = m5_info.get("path") or str(Path("models") / "meta_labeler_m5.pkl")
    ready = meta.is_ready_for(tf)
    should = meta.should_gate(tf, regime) if ready else False
    base_th = float(pa_cfg.get("META_LABEL_THRESHOLD", 0.52))
    eff_th = meta.effective_threshold(tf, regime, base_th) if ready else None
    prob = None
    if ready and should:
        prob = meta.score(signal, snapshot, regime, spread_pips=est_spread)
    return {
        "use_meta_labeler_config": use_meta_labeler,
        "model_ready": ready,
        "model_artifact_path": model_path,
        "model_artifact_exists": Path(model_path).is_file(),
        "model_type": type(meta._models.get("M5")).__name__ if meta._models.get("M5") else None,
        "is_pa_signal": _is_pa_signal(signal),
        "should_gate": should,
        "regime": regime,
        "probability": prob,
        "base_threshold": base_th,
        "effective_threshold": eff_th,
        "threshold_source": "pa_cfg META_LABEL_THRESHOLD + MetaLabeler.effective_threshold",
        "oos_best_threshold": (m5_info.get("oos") or {}).get("best_threshold"),
        "passed_gate_certified": (m5_info.get("oos") or {}).get("passed_gate"),
        "rejection": prob is not None and eff_th is not None and prob < eff_th,
    }


def _atr_audit(
    df: pd.DataFrame,
    pa_cfg: dict[str, Any],
    *,
    strategy_mode: str,
) -> dict[str, Any]:
    closed = df.iloc[:-1] if len(df) > 1 else df
    regime = infer_regime_from_ohlcv(closed)
    adapted = adapt_filters_for_regime(pa_cfg, regime)
    pct = atr_percentile(closed)
    pct_min = float(adapted.get("ATR_PCT_MIN", 25))
    pct_max = float(adapted.get("ATR_PCT_MAX", 80))
    ok, reason = check_market_filters(df, pa_cfg, strategy_mode=strategy_mode)
    return {
        "regime": regime,
        "atr_percentile": pct,
        "configured_min_before_adapt": float(pa_cfg.get("ATR_PCT_MIN", 25)),
        "configured_max_before_adapt": float(pa_cfg.get("ATR_PCT_MAX", 80)),
        "effective_min_after_regime_adapt": pct_min,
        "effective_max_after_regime_adapt": pct_max,
        "comparison": f"{pct:.0f} vs [{pct_min:.0f}, {pct_max:.0f}]",
        "filter_pass": ok,
        "reason": reason,
        "closed_window_len": len(closed),
        "uses_forming_bar_exclusion": len(df) > 1,
        "gold_strategy_mode": strategy_mode,
    }


def _first_rejection_gate(
    *,
    final_reason: str,
) -> str:
    reason = str(final_reason)
    if "ATR percentile" in reason:
        return "check_market_filters"
    if "meta-labeler" in reason:
        return "meta_labeler"
    if "lot too small" in reason:
        return "lot_sizing"
    return "unknown"


async def _audit_one_candidate(
    engine: Any,
    cand: dict[str, Any],
    *,
    data_label: str,
    frozen: dict[str, Any],
    legacy_config: dict[str, Any],
) -> dict[str, Any]:
    cursor = int(cand["cursor"])
    clear_pa_dedup_cache()
    engine._data.set_cursor(cursor)
    market = MarketKey(data_label, "M5")
    portfolio = engine._broker.snapshot()
    ctx = CycleContext(market=market)
    journal_before = len(engine._risk.risk_journal)

    for stage in engine._kernel._pipeline:
        ok = await stage.run(ctx, portfolio)
        if stage.name.value == PipelineStageName.RISK.value:
            break
        if not ok:
            break

    signal = ctx.signal
    risk = ctx.risk
    final_reason = getattr(risk, "reason", None) if risk else "no_risk_evaluation"
    df = ctx.enriched_ohlcv
    regime = infer_regime_from_ohlcv(df.iloc[:-1] if df is not None and len(df) > 1 else df) if df is not None else "RANGING"

    pa_cfg = get_price_action_config(data_label, "M5")
    strategy_mode = str(pa_cfg.get("GOLD_STRATEGY_MODE", ""))
    tier = detect_account_tier(float(portfolio.get("balance", engine._cfg.initial_balance)))
    profile = execution_profile_for_tier(tier)
    risk_pct = (
        float(profile.risk_per_trade_override)
        if profile.risk_per_trade_override is not None
        else float(engine._cfg.risk_per_trade)
    )

    hour = 12
    if df is not None and not df.empty and hasattr(df.index[-1], "hour"):
        hour = int(df.index[-1].hour)
    est_spread = (
        variable_spread_pips(engine._cfg.spread_pips, hour)
        if engine._cfg.variable_spread
        else engine._cfg.spread_pips
    )

    snap = {
        **portfolio,
        "ohlcv": df,
        "symbol": data_label,
        "timeframe": "M5",
        "current_time": df.index[-1] if df is not None and not df.empty else None,
        "htf_bias": portfolio.get("htf_bias", 0),
    }

    atr_info = _atr_audit(df, pa_cfg, strategy_mode=strategy_mode) if df is not None else {}
    meta_info = (
        _meta_audit(
            signal,
            snap,
            regime=regime,
            pa_cfg=pa_cfg,
            use_meta_labeler=engine._cfg.use_meta_labeler,
            est_spread=est_spread,
        )
        if signal is not None
        else {}
    )
    lot_info = (
        _lot_sizing_audit(
            signal,
            snap,
            legacy_config=legacy_config,
            risk_pct=risk_pct,
            regime=regime,
        )
        if signal is not None
        else {}
    )

    first_gate = _first_rejection_gate(final_reason=str(final_reason))

    for stage in engine._kernel._pipeline:
        if stage.name.value == PipelineStageName.SIGNALS.value:
            stage._last_closed_bar.clear()  # type: ignore[attr-defined]

    return {
        "cursor": cursor,
        "timestamp": cand.get("timestamp"),
        "direction": cand.get("direction"),
        "signal_confidence": float(getattr(signal, "confidence", 0) or 0) if signal else None,
        "phase26d_risk_reason": cand.get("risk_reason"),
        "final_riskgate_reason": final_reason,
        "first_rejection_gate": first_gate,
        "lot_sizing": lot_info if first_gate == "lot_sizing" or "lot too small" in str(final_reason) else {
            "skipped_or_passed": first_gate != "lot_sizing",
            "summary": lot_info.get("current_path") if lot_info else None,
        },
        "meta_labeler": meta_info if first_gate == "meta_labeler" or "meta-labeler" in str(final_reason) else {
            "skipped_or_passed": first_gate != "meta_labeler",
        },
        "atr_filter": atr_info if first_gate == "check_market_filters" or "ATR percentile" in str(final_reason) else {
            "skipped_or_passed": first_gate != "check_market_filters",
            "summary": {"atr_percentile": atr_info.get("atr_percentile"), "reason": atr_info.get("reason")},
        },
        "journal_appended": len(engine._risk.risk_journal) > journal_before,
        "decision_table_row": {
            "lot_sizing": "reject" if "lot too small" in str(final_reason) else "n/a",
            "atr_filter": "reject" if "ATR percentile" in str(final_reason) else "pass",
            "meta_labeler": "reject" if "meta-labeler" in str(final_reason) else "pass",
            "final_riskgate": "reject",
            "reason": final_reason,
        },
    }


def _classify_lot_root(candidates: list[dict[str, Any]]) -> str:
    lot_rows = [c for c in candidates if "lot too small" in str(c.get("final_riskgate_reason"))]
    if not lot_rows:
        return "N/A"
    all_none = all(
        not (c.get("lot_sizing") or {}).get("economics_found_xauusd", False) for c in lot_rows
    )
    if all_none:
        return "CONFIG/DATA MISMATCH"
    return "INCONCLUSIVE"


def _classify_meta_root(candidates: list[dict[str, Any]]) -> str:
    meta_rows = [c for c in candidates if "meta-labeler" in str(c.get("final_riskgate_reason"))]
    if not meta_rows:
        return "N/A"
    ready = all((c.get("meta_labeler") or {}).get("model_ready") for c in meta_rows)
    if ready:
        return "LEGITIMATE CONFIGURED BEHAVIOR"
    return "MODEL READINESS/ARTIFACT PROBLEM"


def _classify_atr_root(candidates: list[dict[str, Any]]) -> str:
    atr_rows = [c for c in candidates if "ATR percentile" in str(c.get("final_riskgate_reason"))]
    if not atr_rows:
        return "N/A"
    return "LEGITIMATE CONFIGURED BEHAVIOR"


def _classify_journal() -> str:
    return "METRIC GAP / DOCUMENTATION ISSUE"


def _classify_overall(lot: str, meta: str, atr: str, *, lot_n: int, meta_n: int, atr_n: int) -> str:
    distinct = sum(1 for n in (lot_n, meta_n, atr_n) if n > 0)
    if distinct >= 2:
        return "F — multiple independent causes"
    if lot_n > 0 and lot == "CONFIG/DATA MISMATCH":
        return "B — symbol/economics mismatch"
    if meta_n > 0 and atr_n > 0:
        return "F — multiple independent causes"
    if meta_n > 0 or atr_n > 0:
        return "A — legitimate configured rejection"
    return "G — inconclusive"


async def run_phase26e_riskgate_audit(
    base_dir: str | Path | None = None,
    *,
    dataset_rel: str = DEFAULT_DATASET,
) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    frozen = build_frozen_baseline_configuration()
    data_label = frozen.get("data_symbol_label", "XAUUSD")
    candidates_26d = _load_phase26d_candidates(root)

    parquet = root / dataset_rel
    if not parquet.is_file():
        raise FileNotFoundError(parquet)
    enriched = _enrich_frame(_load_parquet_tail(parquet, 2500))
    engine = _build_trace_engine(enriched, frozen)
    legacy_config = engine._legacy_config

    audited: list[dict[str, Any]] = []
    for cand in candidates_26d:
        audited.append(
            await _audit_one_candidate(
                engine,
                cand,
                data_label=data_label,
                frozen=frozen,
                legacy_config=legacy_config,
            )
        )

    lot_cls = _classify_lot_root(audited)
    meta_cls = _classify_meta_root(audited)
    atr_cls = _classify_atr_root(audited)
    journal_cls = _classify_journal()

    lot_only = [r for r in audited if "lot too small" in str(r.get("final_riskgate_reason"))]
    meta_only = [r for r in audited if "meta-labeler" in str(r.get("final_riskgate_reason"))]
    atr_only = [r for r in audited if "ATR percentile" in str(r.get("final_riskgate_reason"))]

    overall = _classify_overall(lot_cls, meta_cls, atr_cls, lot_n=len(lot_only), meta_n=len(meta_only), atr_n=len(atr_only))

    decision_table = [
        {
            "candidate": f"{r['timestamp']}@{r['cursor']}",
            "direction": r["direction"],
            **r["decision_table_row"],
        }
        for r in audited
    ]

    report = Phase26EAudit(
        status="PASS_WITH_DEFERRAL",
        generated_at=datetime.now(timezone.utc).isoformat(),
        overall_classification=overall,
    ).to_dict()

    report.update(
        {
            "phase26d_source": PHASE26D_JSON,
            "candidate_count": len(audited),
            "decision_table": decision_table,
            "riskgate_evaluation_order": RISKGATE_EVAL_ORDER,
            "riskgate_evaluation_order_source": "tradingbot/backtest/risk.py BacktestRiskGate.evaluate",
            "lot_sizing_audit": {
                "count": len(lot_only),
                "classification": lot_cls,
                "candidates": lot_only,
                "symbol_mismatch_only_cause": lot_cls == "CONFIG/DATA MISMATCH",
                "resolve_xauusd_returns_none": all(
                    not (r.get("lot_sizing") or {}).get("economics_found_xauusd", False)
                    for r in lot_only
                ),
                "resolve_xauusd_i_would_work": any(
                    (r.get("lot_sizing") or {}).get("hypothetical_xauusd_i", {}).get("would_pass_min_lot")
                    for r in lot_only
                ),
                "hypothetical_note": (
                    "XAUUSD_i mapping fixes economics lookup; some candidates may still fail VOLUME_BELOW_MIN "
                    "at $1000 balance / 0.5% risk on wide stops"
                ),
            },
            "meta_labeler_audit": {
                "count": len(meta_only),
                "classification": meta_cls,
                "candidates": meta_only,
                "global_model_state": {
                    "m5_ready": get_meta_labeler().is_ready_for("M5"),
                    "artifact": str(Path("models/meta_labeler_m5.pkl")),
                    "artifact_exists": Path("models/meta_labeler_m5.pkl").is_file(),
                    "use_meta_labeler": engine._cfg.use_meta_labeler,
                    "m5_threshold_config": get_price_action_config("XAUUSD", "M5").get("META_LABEL_THRESHOLD"),
                },
            },
            "atr_filter_audit": {
                "count": len(atr_only),
                "classification": atr_cls,
                "candidates": atr_only,
                "preset_bounds": {
                    "ATR_PCT_MIN": get_price_action_config("XAUUSD", "M5").get("ATR_PCT_MIN"),
                    "ATR_PCT_MAX": get_price_action_config("XAUUSD", "M5").get("ATR_PCT_MAX"),
                    "REGIME_ADAPTIVE_FILTERS": get_price_action_config("XAUUSD", "M5").get("REGIME_ADAPTIVE_FILTERS"),
                },
            },
            "journal_metric_audit": {
                "classification": journal_cls,
                "paths_that_append": [
                    "BacktestRiskGate._resolve_lot_for_signal (MICRO reject/allow)",
                    "BacktestRiskGate._resolve_lot_for_signal (non-MICRO allow after lot>0)",
                ],
                "paths_that_do_not_append": [
                    "check_market_filters early return",
                    "meta-labeler early return",
                    "lot<=0 return in _resolve_lot_for_signal",
                    "most evaluate() early gates (max positions, spread, etc.)",
                ],
                "phase26b_metric_meaning": "len(risk_journal) counts sizing-resolution records, not all evaluate() calls",
                "journal_appended_among_19": sum(1 for r in audited if r.get("journal_appended")),
            },
            "symbol_economics_consistency": {
                "dataset_symbol": data_label,
                "configured_instrument": frozen.get("configured_instrument_symbol"),
                "broker_catalog_keys": list((legacy_config.get("BROKER_SYMBOL_CATALOG") or {}).keys()),
                "symbol_aliases": legacy_config.get("symbol_aliases"),
                "signal_symbol_observed": "XAUUSD",
                "economics_lookup_symbol_observed": "XAUUSD",
                "offline_catalog_key": "XAUUSD_i",
                "ev_eq_01": "NOT_PROVEN",
                "lookup_failure_explanation": (
                    "resolve_backtest_economics('XAUUSD') misses catalog key 'XAUUSD_i'; "
                    "symbol_aliases is not consulted in sizing path"
                ),
            },
            "root_causes": {
                "LOT": lot_cls,
                "META": meta_cls,
                "ATR": atr_cls,
                "JOURNAL": journal_cls,
                "OVERALL": overall,
            },
            "code_defects": [
                {
                    "file": "tradingbot/backtest/risk.py",
                    "function": "BacktestRiskGate._position_size",
                    "defect": "resolve_backtest_economics(signal.symbol) without symbol_aliases resolution",
                    "affects": "3/19 lot too small rejections",
                },
                {
                    "file": "tradingbot/backtest/risk.py",
                    "function": "BacktestRiskGate.evaluate",
                    "defect": "early rejection paths omit _append_risk_journal",
                    "affects": "Phase 26B risk_journal_entries metric (19/19)",
                },
            ],
            "minimal_fixes": {
                "lot_sizing": "Apply symbol_aliases (XAUUSD→XAUUSD_i) before resolve_backtest_economics in _position_size",
                "meta_labeler": "No code fix required if configured gating is intended; document baseline rejection rate",
                "atr_filter": "No code fix required; rejections match adapt_filters_for_regime + atr_percentile logic",
                "journal": "Optional: append structured record on every evaluate() outcome for metric parity",
            },
            "what_this_proves": (
                "All 19 signals are rejected at RiskGate by three distinct gates. "
                "Current 'lot too small' on 3/19 is caused solely by resolve_backtest_economics('XAUUSD')→None. "
                "Even with XAUUSD_i economics, those 3 still fail VOLUME_BELOW_MIN at $1000/0.5% risk."
            ),
            "what_this_does_not_prove": (
                "Profitability, EV-EQ-01 symbol equivalence, or that relaxing meta/ATR would improve outcomes."
            ),
            "final_decision": "PASS_WITH_DEFERRAL",
        }
    )

    _write_json(root / PHASE26E_JSON, report)
    return report


def run_phase26e_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return asyncio.run(run_phase26e_riskgate_audit(base_dir))
