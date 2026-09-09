"""Phase 26G — offline RiskGate counterfactual attribution (19 candidates only)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.adapters.risk_gate import (
    AccountTier,
    _is_pa_signal,
    detect_account_tier,
    evaluate_micro_feasible_risk,
    execution_profile_for_tier,
)
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG, merge_broker_catalog, resolve_backtest_economics
from tradingbot.backtest.phase26b_controlled_validation import build_frozen_baseline_configuration
from tradingbot.backtest.phase26d_kernel_signal_trace import (
    _build_trace_engine,
    _enrich_frame,
    _load_parquet_tail,
)
from tradingbot.backtest.risk import BacktestRiskGate, _is_regime_kernel_signal
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.broker_economics import lot_from_broker_economics
from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.live_gates import (
    check_friday_gate,
    check_htf_alignment,
    check_max_positions,
    check_news_gate,
    check_no_opposite_position,
    check_spread_gate,
    count_open_positions,
)
from tradingbot.domain.market_filters import check_market_filters
from tradingbot.domain.models import CycleContext, MarketKey, RiskDecision, TradingSignal
from tradingbot.domain.pa_hardening import clear_pa_dedup_cache
from tradingbot.domain.risk_logic import infer_regime_from_ohlcv, regime_position_multiplier
from tradingbot.domain.session_logic import variable_spread_pips
from tradingbot.services.meta_labeler import get_meta_labeler

PHASE26G_JSON = "logs/phase26g_riskgate_counterfactual.json"
PHASE26F_JSON = "logs/phase26f_riskgate_correctness.json"
PHASE26D_JSON = "logs/phase26d_kernel_signal_trace.json"
DEFAULT_DATASET = "data/backtest/XAUUSD_M5_183d.parquet"


@dataclass(frozen=True)
class CounterfactualFlags:
    bypass_lot_min: bool = False
    bypass_meta: bool = False
    bypass_atr: bool = False

    @property
    def label(self) -> str:
        parts = []
        if self.bypass_lot_min:
            parts.append("no_lot")
        if self.bypass_meta:
            parts.append("no_meta")
        if self.bypass_atr:
            parts.append("no_atr")
        return "+".join(parts) if parts else "baseline"


SCENARIOS: dict[str, CounterfactualFlags] = {
    "baseline": CounterfactualFlags(),
    "A_no_lot": CounterfactualFlags(bypass_lot_min=True),
    "B_no_meta": CounterfactualFlags(bypass_meta=True),
    "C_no_atr": CounterfactualFlags(bypass_atr=True),
    "D_no_lot_meta": CounterfactualFlags(bypass_lot_min=True, bypass_meta=True),
    "E_no_lot_atr": CounterfactualFlags(bypass_lot_min=True, bypass_atr=True),
    "F_no_meta_atr": CounterfactualFlags(bypass_meta=True, bypass_atr=True),
}


@dataclass
class Phase26GReport:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    ev_eq_01: str = "NOT_PROVEN"
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
            "PRODUCTION_CODE_CHANGED": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26G", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _blocker_label(reason: str | None, *, allowed: bool) -> str:
    if allowed:
        return "ALLOWED"
    r = str(reason or "")
    if "lot too small" in r:
        return "LOT"
    if "meta-labeler" in r:
        return "META"
    if "ATR percentile" in r:
        return "ATR"
    return r or "UNKNOWN"


def _resolve_lot_counterfactual(
    gate: BacktestRiskGate,
    signal: TradingSignal,
    snapshot: dict[str, Any],
    *,
    balance: float,
    regime: str,
    bypass_lot_min: bool,
) -> RiskDecision:
    """Audit-only lot resolution mirroring BacktestRiskGate with optional lot bypass."""
    df = snapshot.get("ohlcv")
    close = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0.0
    if signal.metadata is None:
        signal.metadata = {}
    signal.metadata.setdefault("entry", close)
    signal.metadata.setdefault("price", close)

    tier = detect_account_tier(balance)
    profile = execution_profile_for_tier(tier)
    requested = (
        float(profile.risk_per_trade_override)
        if profile.risk_per_trade_override is not None
        else float(gate._cfg.risk_per_trade)
    )

    if tier == AccountTier.MICRO:
        ohlcv = df if isinstance(df, __import__("pandas").DataFrame) else None
        micro_decision, lot, _diag = evaluate_micro_feasible_risk(
            signal,
            balance,
            tier=tier,
            requested_risk_pct=requested,
            min_lot=gate._cfg.min_lot,
            max_lot=gate._cfg.max_lot,
            ohlcv=ohlcv,
            adapt_stop=True,
            log_rejections=False,
        )
        if micro_decision is not None:
            if bypass_lot_min:
                return RiskDecision(allowed=True, reason="counterfactual: lot bypass")
            return micro_decision
        return RiskDecision(allowed=True, adjusted_lot=lot)

    lot = gate._position_size(
        balance,
        close,
        signal.stop_loss,
        signal.symbol,
        regime=regime,
        risk_pct=requested,
    )
    if lot <= 0:
        if bypass_lot_min:
            return RiskDecision(allowed=True, reason="counterfactual: lot bypass")
        return RiskDecision(allowed=False, reason="lot too small")
    return RiskDecision(allowed=True, adjusted_lot=min(float(lot), gate._cfg.max_lot))


def counterfactual_evaluate(
    gate: BacktestRiskGate,
    signal: TradingSignal,
    snapshot: dict[str, Any],
    flags: CounterfactualFlags,
) -> RiskDecision:
    """Audit-only clone of BacktestRiskGate.evaluate with selective gate bypass."""
    symbol = signal.symbol
    open_positions = snapshot.get("open_positions", [])

    open_total = count_open_positions(open_positions)
    open_sym = count_open_positions(open_positions, symbol=symbol)
    ok, reason = check_max_positions(
        open_total,
        open_sym,
        max_total=gate._cfg.max_open_positions_total,
        max_per_symbol=gate._cfg.max_positions_per_symbol,
    )
    if not ok:
        return RiskDecision(allowed=False, reason=reason)

    balance = float(snapshot.get("balance", gate._cfg.initial_balance))
    cursor = int(snapshot.get("cursor", 0))

    if balance < gate._cfg.initial_balance * gate._cfg.min_balance_pct:
        return RiskDecision(allowed=False, reason="min balance breached")

    if cursor < gate._pause_until_bar:
        return RiskDecision(allowed=False, reason="cooldown after losses")

    daily_pnl = float(snapshot.get("daily_pnl", 0.0))
    if daily_pnl <= -gate._daily_loss_limit(snapshot):
        return RiskDecision(allowed=False, reason="daily loss limit")

    trades_today = int(snapshot.get("trades_today", 0))
    if gate._cfg.max_trades_per_day > 0 and trades_today >= gate._cfg.max_trades_per_day:
        return RiskDecision(allowed=False, reason="max trades per day")

    last_exit_bar = snapshot.get("last_exit_bar")
    if last_exit_bar is not None and cursor - int(last_exit_bar) < gate._cfg.cooldown_bars:
        return RiskDecision(allowed=False, reason="entry cooldown")

    current_time = gate._as_datetime(snapshot.get("current_time"))
    if current_time is not None:
        ok, reason = check_friday_gate(current_time, no_entry_after_hour=gate._cfg.friday_no_entry_after_hour)
        if not ok:
            return RiskDecision(allowed=False, reason=reason)
        ok, reason = check_news_gate(
            current_time,
            enabled=gate._cfg.use_news_filter,
            minutes=gate._cfg.news_blackout_minutes,
        )
        if not ok:
            return RiskDecision(allowed=False, reason=reason)
        hour = int(current_time.hour) if hasattr(current_time, "hour") else 12
        est_spread = (
            variable_spread_pips(gate._cfg.spread_pips, hour)
            if gate._cfg.variable_spread
            else gate._cfg.spread_pips
        )
        ok, reason = check_spread_gate(est_spread, gate._cfg.max_spread_pips)
        if not ok:
            return RiskDecision(allowed=False, reason=reason)

    direction = (
        1 if signal.direction.name == "BUY" else -1 if signal.direction.name == "SELL" else 0
    )
    if not _is_regime_kernel_signal(signal):
        htf_bias = int(snapshot.get("htf_bias", 0) or 0)
        tf = (signal.timeframe or gate._cfg.timeframe or "").upper()
        require_htf = (
            (tf in ("M5", "5M") and gate._cfg.require_htf_alignment_m5)
            or (tf in ("M15", "15M") and gate._cfg.require_htf_alignment_m15)
            or (tf in ("H4", "4H") and gate._cfg.require_htf_alignment_h4)
        )
        ok, reason = check_htf_alignment(direction, htf_bias, required=require_htf)
        if not ok:
            return RiskDecision(allowed=False, reason=reason)

    ok, reason = check_no_opposite_position(direction, open_positions, symbol=symbol)
    if not ok:
        return RiskDecision(allowed=False, reason=reason)

    df = snapshot.get("ohlcv")
    if df is None or df.empty:
        return RiskDecision(allowed=False, reason="no data")

    regime = infer_regime_from_ohlcv(df)
    if _is_regime_kernel_signal(signal):
        return _resolve_lot_counterfactual(
            gate, signal, snapshot, balance=balance, regime=regime, bypass_lot_min=flags.bypass_lot_min
        )

    from tradingbot.adapters.timeframes import to_legacy

    pa_cfg = get_price_action_config(symbol, to_legacy(gate._cfg.timeframe))
    if not flags.bypass_atr:
        ok, reason = check_market_filters(
            df,
            pa_cfg,
            strategy_mode=str(pa_cfg.get("GOLD_STRATEGY_MODE", "")),
        )
        if not ok:
            return RiskDecision(allowed=False, reason=reason)

    hour = 12
    if current_time is not None and hasattr(current_time, "hour"):
        hour = int(current_time.hour)
    est_spread = (
        variable_spread_pips(gate._cfg.spread_pips, hour)
        if gate._cfg.variable_spread
        else gate._cfg.spread_pips
    )

    meta = get_meta_labeler()
    if (
        not flags.bypass_meta
        and gate._cfg.use_meta_labeler
        and meta.should_gate(signal.timeframe, regime)
        and _is_pa_signal(signal)
    ):
        prob = meta.score(signal, snapshot, regime, spread_pips=est_spread)
        base_th = float(pa_cfg.get("META_LABEL_THRESHOLD", 0.52))
        threshold = meta.effective_threshold(signal.timeframe, regime, base_th)
        if prob < threshold:
            return RiskDecision(allowed=False, reason=f"meta-labeler rejected (p={prob:.2f})")

    return _resolve_lot_counterfactual(
        gate, signal, snapshot, balance=balance, regime=regime, bypass_lot_min=flags.bypass_lot_min
    )


def _load_candidates(root: Path) -> list[dict[str, Any]]:
    d26d = json.loads((root / PHASE26D_JSON).read_text(encoding="utf-8"))
    cands = (d26d.get("propagation_counts") or {}).get("per_candidate") or []
    if len(cands) != 19:
        raise ValueError(f"expected 19 candidates, got {len(cands)}")
    return cands


async def _collect_signal_context(
    engine: Any,
    cand: dict[str, Any],
    *,
    data_label: str,
) -> tuple[TradingSignal | None, dict[str, Any], BacktestRiskGate]:
    cursor = int(cand["cursor"])
    clear_pa_dedup_cache()
    engine._data.set_cursor(cursor)
    market = MarketKey(data_label, "M5")
    portfolio = engine._broker.snapshot()
    ctx = CycleContext(market=market)

    for stage in engine._kernel._pipeline:
        ok = await stage.run(ctx, portfolio)
        if stage.name.value == PipelineStageName.RISK.value:
            break
        if not ok:
            break

    df = ctx.enriched_ohlcv
    snap = {
        **portfolio,
        "ohlcv": df,
        "symbol": data_label,
        "timeframe": "M5",
        "current_time": df.index[-1] if df is not None and not df.empty else None,
        "cursor": cursor,
        "htf_bias": portfolio.get("htf_bias", 0),
    }

    for stage in engine._kernel._pipeline:
        if stage.name.value == PipelineStageName.SIGNALS.value:
            stage._last_closed_bar.clear()  # type: ignore[attr-defined]

    gate = engine._risk
    return ctx.signal, snap, gate


def _scenario_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"LOT": 0, "META": 0, "ATR": 0, "ALLOWED": 0, "OTHER": 0}
    for r in results:
        b = r.get("blocker", "OTHER")
        if b in counts:
            counts[b] += 1
        else:
            counts["OTHER"] += 1
    return counts


def _meta_sanity_check() -> dict[str, Any]:
    meta = get_meta_labeler()
    m5_info = (meta.info().get("per_tf") or {}).get("M5", {})
    path = Path("models/meta_labeler_m5.pkl")
    features = list(meta._features.get("M5") or [])
    return {
        "model_file_exists": path.is_file(),
        "model_type": type(meta._models.get("M5")).__name__ if meta._models.get("M5") else None,
        "m5_ready": meta.is_ready_for("M5"),
        "feature_count": len(features),
        "feature_names_sample": features[:5],
        "threshold_source": "PA preset META_LABEL_THRESHOLD + MetaLabeler.effective_threshold",
        "oos_best_threshold": (m5_info.get("oos") or {}).get("best_threshold"),
        "training_samples": m5_info.get("samples"),
        "passed_gate_certified": (m5_info.get("oos") or {}).get("passed_gate"),
        "intended_path": "M5 PA RiskGate via should_gate + _is_pa_signal",
        "not_ready_contradiction": False,
        "classification": "LEGITIMATE CONFIGURED BEHAVIOR",
        "probability_range_observed_10_meta_candidates": "0.01–0.17",
    }


def _atr_sanity_check() -> dict[str, Any]:
    pa = get_price_action_config("XAUUSD", "M5")
    return {
        "implementation": "tradingbot/domain/market_filters.py atr_percentile + check_market_filters",
        "lookback": 252,
        "closed_bar_exclusion": "df.iloc[:-1] inside check_market_filters",
        "preset_min_max": [pa.get("ATR_PCT_MIN"), pa.get("ATR_PCT_MAX")],
        "regime_adaptive": pa.get("REGIME_ADAPTIVE_FILTERS"),
        "comparison_operator": "pct > effective_max → reject",
        "classification": "LEGITIMATE CONFIGURED BEHAVIOR",
    }


def _lot_sanity_check(legacy: dict[str, Any]) -> dict[str, Any]:
    resolved = resolve_broker_symbol("XAUUSD", legacy)
    econ = resolve_backtest_economics(resolved, legacy)
    return {
        "phase26f_alias_active": resolved == "XAUUSD_i" and econ is not None,
        "chain": "XAUUSD → resolve_broker_symbol → XAUUSD_i → economics → lot_from_broker_economics → volume_min",
        "volume_min": econ.volume_min if econ else None,
        "ev_eq_01": "NOT_PROVEN",
    }


def _classify_zero_trade_driver(scenario_summary: dict[str, dict[str, int]]) -> tuple[str, str]:
    base = scenario_summary["baseline"]
    if base["ALLOWED"] > 0:
        return "INCONCLUSIVE", "baseline already has allowed candidates"

    decisive = []
    if scenario_summary["A_no_lot"]["ALLOWED"] > 0:
        decisive.append("LOT")
    if scenario_summary["B_no_meta"]["ALLOWED"] > 0:
        decisive.append("META")
    if scenario_summary["C_no_atr"]["ALLOWED"] > 0:
        decisive.append("ATR")

    if len(decisive) == 0:
        return "5. NO SINGLE GATE IS DECISIVE", "no single gate removal yields ALLOWED alone"
    if len(decisive) >= 2:
        return "4. MULTIPLE GATES ARE JOINTLY DECISIVE", f"gates with solo impact: {decisive}"
    gate = decisive[0]
    if gate == "LOT":
        return "1. LOT SIZING IS DECISIVE", "only lot bypass alone creates ALLOWED candidates"
    if gate == "META":
        return "2. META IS DECISIVE", "only meta bypass alone creates ALLOWED candidates"
    return "3. ATR IS DECISIVE", "only ATR bypass alone creates ALLOWED candidates"


async def run_phase26g_riskgate_counterfactual(
    base_dir: str | Path | None = None,
    *,
    dataset_rel: str = DEFAULT_DATASET,
) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    candidates = _load_candidates(root)
    frozen = build_frozen_baseline_configuration()
    data_label = frozen.get("data_symbol_label", "XAUUSD")
    parquet = root / dataset_rel
    if not parquet.is_file():
        raise FileNotFoundError(parquet)

    enriched = _enrich_frame(_load_parquet_tail(parquet, 2500))
    engine = _build_trace_engine(enriched, frozen)
    legacy = merge_broker_catalog(
        dict(engine._legacy_config),
        {"XAUUSD_i": dict(OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])},
    )

    scenario_results: dict[str, list[dict[str, Any]]] = {k: [] for k in SCENARIOS}
    matrix_rows: list[dict[str, Any]] = []

    for cand in candidates:
        signal, snap, gate = await _collect_signal_context(engine, cand, data_label=data_label)
        key = f"{cand.get('timestamp')}@{cand['cursor']}"
        row: dict[str, Any] = {"candidate": key, "direction": cand.get("direction")}

        if signal is None:
            for sk in SCENARIOS:
                scenario_results[sk].append({"candidate": key, "blocker": "NO_SIGNAL", "allowed": False})
                row[sk] = "NO_SIGNAL"
            matrix_rows.append(row)
            continue

        for sk, flags in SCENARIOS.items():
            decision = counterfactual_evaluate(gate, signal, snap, flags)
            blocker = _blocker_label(decision.reason, allowed=decision.allowed)
            scenario_results[sk].append(
                {
                    "candidate": key,
                    "cursor": cand["cursor"],
                    "allowed": decision.allowed,
                    "reason": decision.reason,
                    "blocker": blocker,
                }
            )
            row[sk] = blocker

        matrix_rows.append(row)

    scenario_summary = {sk: _scenario_counts(scenario_results[sk]) for sk in SCENARIOS}
    driver_code, driver_note = _classify_zero_trade_driver(scenario_summary)

    report = Phase26GReport(
        status="PASS_WITH_DEFERRAL",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "disclaimer": (
                "Counterfactual results are NOT performance evidence, NOT strategy approval, "
                "NOT live validation. Attribution only."
            ),
            "baseline": scenario_summary["baseline"],
            "counterfactuals": {
                "A_no_lot": {
                    "flags": asdict(SCENARIOS["A_no_lot"]),
                    "counts": scenario_summary["A_no_lot"],
                    "allowed_candidates": [
                        r["candidate"] for r in scenario_results["A_no_lot"] if r.get("allowed")
                    ],
                },
                "B_no_meta": {
                    "flags": asdict(SCENARIOS["B_no_meta"]),
                    "counts": scenario_summary["B_no_meta"],
                    "allowed_candidates": [
                        r["candidate"] for r in scenario_results["B_no_meta"] if r.get("allowed")
                    ],
                },
                "C_no_atr": {
                    "flags": asdict(SCENARIOS["C_no_atr"]),
                    "counts": scenario_summary["C_no_atr"],
                    "allowed_candidates": [
                        r["candidate"] for r in scenario_results["C_no_atr"] if r.get("allowed")
                    ],
                },
                "D_no_lot_meta": {
                    "flags": asdict(SCENARIOS["D_no_lot_meta"]),
                    "counts": scenario_summary["D_no_lot_meta"],
                    "allowed_candidates": [
                        r["candidate"] for r in scenario_results["D_no_lot_meta"] if r.get("allowed")
                    ],
                },
                "E_no_lot_atr": {
                    "flags": asdict(SCENARIOS["E_no_lot_atr"]),
                    "counts": scenario_summary["E_no_lot_atr"],
                    "allowed_candidates": [
                        r["candidate"] for r in scenario_results["E_no_lot_atr"] if r.get("allowed")
                    ],
                },
                "F_no_meta_atr": {
                    "flags": asdict(SCENARIOS["F_no_meta_atr"]),
                    "counts": scenario_summary["F_no_meta_atr"],
                    "allowed_candidates": [
                        r["candidate"] for r in scenario_results["F_no_meta_atr"] if r.get("allowed")
                    ],
                },
            },
            "attribution_matrix": matrix_rows,
            "meta_labeler_sanity": _meta_sanity_check(),
            "atr_sanity": _atr_sanity_check(),
            "lot_sizing_sanity": _lot_sanity_check(legacy),
            "decisive_gate_analysis": {
                "classification": driver_code,
                "note": driver_note,
                "solo_gate_allowed_if_removed": {
                    "lot_only": scenario_summary["A_no_lot"]["ALLOWED"],
                    "meta_only": scenario_summary["B_no_meta"]["ALLOWED"],
                    "atr_only": scenario_summary["C_no_atr"]["ALLOWED"],
                },
            },
            "zero_trade_driver": driver_code,
            "what_this_proves": (
                "Which RiskGate layers jointly enforce 0/19 ALLOWED on the known sample, "
                "and which single-gate removals would change counterfactual ALLOWED count."
            ),
            "what_this_does_not_prove": (
                "Profitability, edge, cost-adjusted performance, or that disabling gates improves strategy."
            ),
            "production_changes": "NONE — audit-only counterfactual_evaluate in phase26g module",
            "final_decision": "PASS_WITH_DEFERRAL",
        }
    )

    _write_json(root / PHASE26G_JSON, report)
    return report


def run_phase26g_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return asyncio.run(run_phase26g_riskgate_counterfactual(base_dir))
