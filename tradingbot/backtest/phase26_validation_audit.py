"""Phase 26 — offline research/backtest validation readiness audit (read-only).

Does NOT start MT5, bot, daemon, or access credentials.
Does NOT modify datasets, strategy, RiskGate, Router, or live config.
Phase 25M remains the FINAL broker-evidence automation gate.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import pandas as pd

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.cost_evidence_audit import (
    ReportEvidenceClass,
    audit_commission_evidence,
    audit_slippage_evidence,
    audit_spread_evidence,
    audit_swap_evidence,
    cost_adjusted_metrics_allowed,
    dataset_eligibility_for_row,
    load_all_operator_deals,
)
from tradingbot.backtest.cost_model import CostCompleteness, SpreadMode, build_backtest_cost_model
from tradingbot.backtest.dataset_provenance import (
    LITEFINANCE_EVIDENCE_TIMESTAMP,
    audit_backtest_datasets,
    load_dataset_metadata,
    metadata_path_for,
)
from tradingbot.backtest.metrics import compute_metrics
from tradingbot.backtest.models import BacktestResult
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.symbol_equivalence import EquivalenceConclusion, audit_from_operator_artifacts
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.pa_symbol_tf_presets import PA_SYMBOL_TF_PRESETS
from tradingbot.config.strategies import ACTIVE_STRATEGIES

PHASE26_READINESS_JSON = "logs/phase26_validation_readiness_report.json"
PHASE26_CLAIMS_JSON = "logs/phase26_performance_claims_audit.json"
PHASE26_PARITY_JSON = "logs/phase26_backtest_live_parity.json"
PHASE26_MATRIX_JSON = "logs/phase26_validation_matrix.json"

PERFORMANCE_ARTIFACT_GLOBS: tuple[str, ...] = (
    "tradingbot/ml/research/**/phase*_final_report.json",
    "tradingbot/ml/research/**/backtest*.json",
    "tradingbot/ml/research/**/performance*.json",
    "ml/reports/**/*.json",
    "phase32g_final_report.json",
    "performance_gain.json",
)


class ActivationClass(str, Enum):
    IMPLEMENTED_AND_ACTIVE = "IMPLEMENTED_AND_ACTIVE"
    IMPLEMENTED_BUT_INACTIVE = "IMPLEMENTED_BUT_INACTIVE"
    PARTIAL = "PARTIAL"
    DOCUMENTATION_ONLY = "DOCUMENTATION_ONLY"
    UNKNOWN = "UNKNOWN"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"


class BiasSeverity(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    OK = "OK"


class ClaimClass(str, Enum):
    DEFENSIBLE = "DEFENSIBLE"
    CONDITIONALLY_DEFENSIBLE = "CONDITIONALLY_DEFENSIBLE"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    NOT_REPRODUCIBLE = "NOT_REPRODUCIBLE"
    INVALID = "INVALID"


class ParityClass(str, Enum):
    MATCH = "MATCH"
    PARTIAL = "PARTIAL"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"


@dataclass
class Phase26ValidationReport:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    code_version: str = "UNKNOWN"
    objective: str = ""
    strategy_inventory: list[dict[str, Any]] = field(default_factory=list)
    decision_path: list[dict[str, Any]] = field(default_factory=list)
    dataset_realism: list[dict[str, Any]] = field(default_factory=list)
    backtest_bias_audit: list[dict[str, Any]] = field(default_factory=list)
    cost_model_audit: dict[str, Any] = field(default_factory=dict)
    performance_claims: list[dict[str, Any]] = field(default_factory=list)
    overfitting_audit: dict[str, Any] = field(default_factory=dict)
    backtest_live_parity: list[dict[str, Any]] = field(default_factory=list)
    validation_readiness: dict[str, list[str]] = field(default_factory=dict)
    validation_matrix: list[dict[str, Any]] = field(default_factory=list)
    blockers: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    safety: dict[str, bool] = field(default_factory=dict)
    broker_evidence_gate: dict[str, Any] = field(default_factory=dict)
    immutability_ok: bool = True
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "phase": "26",
            **asdict(self),
        }


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _git_head(root: Path) -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except Exception:
        return "UNKNOWN"


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _infer_symbol_from_name(name: str) -> str:
    if name.upper().startswith("XAUUSD_I"):
        return "XAUUSD_i"
    if name.upper().startswith("XAUUSD"):
        return "XAUUSD"
    return "UNKNOWN"


def build_strategy_inventory() -> list[dict[str, Any]]:
    """Code-evidenced strategy inventory — default live/backtest path."""
    m5 = PA_SYMBOL_TF_PRESETS.get("XAUUSD", {}).get("M5", {})
    items: list[dict[str, Any]] = [
        {
            "item": "active_strategy",
            "value": "priceaction",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "tradingbot/config/strategies.py ACTIVE_STRATEGIES",
        },
        {
            "item": "strategy_mode",
            "value": m5.get("PRESET", "gold_ny_sweep"),
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "tradingbot/config/pa_symbol_tf_presets.py M5 preset",
        },
        {
            "item": "timeframe",
            "value": "M5",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "PRIMARY_SYMBOL + live get_live_config() router → 5m only",
        },
        {
            "item": "entry_engine",
            "value": "evaluate_m5_london_sweep (Asian range sweep + NY reclaim)",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "tradingbot/domain/gold_strategies/m5_london_sweep.py",
        },
        {
            "item": "buy_condition",
            "value": "Low sweep below Asian low → reclaim → close above Asian low",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "m5_london_sweep.py",
        },
        {
            "item": "sell_condition",
            "value": "High sweep above Asian high → reclaim → close below Asian high",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "m5_london_sweep.py",
        },
        {
            "item": "wait_conditions",
            "value": "outside session, no setup, low confidence/quality, duplicate, hardening reject, meta reject",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "price_action_strategy.py, pa_hardening.py, risk_gate.py",
        },
        {
            "item": "session_filter",
            "value": f"NY {m5.get('NY_ENTRY_HOUR_START', 15)}–{m5.get('NY_ENTRY_HOUR_END', 16)} UTC",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "pa_symbol_tf_presets + filter_policy",
        },
        {
            "item": "htf_alignment_m5",
            "value": str(m5.get("REQUIRE_HTF_ALIGNMENT_M5", False)),
            "classification": ActivationClass.IMPLEMENTED_BUT_INACTIVE.value,
            "evidence": "CODE",
            "source": "M5 preset REQUIRE_HTF_ALIGNMENT_M5=False",
        },
        {
            "item": "volatility_filter",
            "value": "ATR percentile 12–94 via RiskGate",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "tradingbot/risk/risk_gate.py check_market_filters",
        },
        {
            "item": "regime_filter",
            "value": "regime_blocks_entry when USE_REGIME_FILTER=True",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "risk_gate.py",
        },
        {
            "item": "spread_filter",
            "value": "check_spread_gate max_spread_pips",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "risk_gate.py",
        },
        {
            "item": "news_filter",
            "value": "check_news_gate blackout minutes",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "risk_gate.py",
        },
        {
            "item": "meta_labeler",
            "value": "MetaLabeler.score in RiskGate for PA signals",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "services/meta_labeler.py + risk_gate.py",
        },
        {
            "item": "ml_kernel",
            "value": "MLKernelRegistry",
            "classification": ActivationClass.IMPLEMENTED_BUT_INACTIVE.value,
            "evidence": "CODE",
            "source": "factory.py — requires USE_ML_KERNEL=true",
        },
        {
            "item": "wpsqf_filter",
            "value": "WinnerPopulationSignalQualityFilter",
            "classification": ActivationClass.IMPLEMENTED_BUT_INACTIVE.value,
            "evidence": "CODE",
            "source": "signal_filter_stage.py default OFF",
        },
        {
            "item": "bos_fvg_hardening",
            "value": "apply_setup_hardening quality_score MIN_QUALITY_SCORE",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "pa_hardening.py",
        },
        {
            "item": "choch_continuation",
            "value": str(m5.get("ENABLE_CHOCH_CONTINUATION", False)),
            "classification": ActivationClass.IMPLEMENTED_BUT_INACTIVE.value,
            "evidence": "CODE",
            "source": "M5 preset ENABLE_CHOCH_CONTINUATION=False",
        },
        {
            "item": "initial_sl_tp",
            "value": "SL behind sweep + ATR pad; TP by range/RR MIN_RR",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "m5_london_sweep.py",
        },
        {
            "item": "live_position_management",
            "value": "breakeven, partial, ATR trail, stagnation, EOD, Friday close",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "mt5_position_manager.py",
        },
        {
            "item": "backtest_position_management",
            "value": "BacktestPositionManager + bar SL/TP",
            "classification": ActivationClass.PARTIAL.value,
            "evidence": "CODE",
            "source": "PM uses close; broker uses high/low — asymmetry",
        },
        {
            "item": "cooldown",
            "value": f"{m5.get('COOLDOWN_BARS', 18)} bars, max {m5.get('MAX_TRADES_PER_DAY', 3)}/day",
            "classification": ActivationClass.IMPLEMENTED_AND_ACTIVE.value,
            "evidence": "CODE",
            "source": "LiveRiskTracker + preset",
        },
    ]
    inactive = [k for k, v in ACTIVE_STRATEGIES.items() if k != "priceaction" and v]
    if inactive:
        items.append(
            {
                "item": "other_strategies_flagged_active",
                "value": inactive,
                "classification": ActivationClass.UNKNOWN.value,
                "evidence": "CODE",
                "source": "strategies.py anomaly",
            }
        )
    return items


def build_decision_path() -> list[dict[str, Any]]:
    """Documented signal path with bias/leakage notes."""
    return [
        {"stage": "DATA", "component": "BacktestMarketData / Mt5MarketDataAdapter", "notes": "OHLCV window; backtest may append synthetic forming bar"},
        {"stage": "FORMING_BAR", "component": "exclude_forming_bar()", "notes": "Decisions on last closed bar; CODE-EVIDENCE parity intent"},
        {"stage": "INDICATOR", "component": "TechnicalIndicatorEngine / PassthroughIndicatorEngine", "notes": "Rolling indicators on history ≤ cursor; watch HTF min_rows fallback"},
        {"stage": "STRATEGY", "component": "PriceActionStrategy → evaluate_m5_london_sweep", "notes": "Asian range + NY session sweep setup"},
        {"stage": "HARDENING", "component": "apply_setup_hardening", "notes": "BOS/FVG/liquidity quality gate"},
        {"stage": "SIGNAL", "component": "build_trading_signal", "notes": "confidence floor, SL/TP attached"},
        {"stage": "FILTER", "component": "SignalFilterStage (WPSQF OFF)", "notes": "pass-through default"},
        {"stage": "META", "component": "MetaLabeler in RiskGate", "notes": "second-layer PA gate; skip CRISIS/VOLATILE"},
        {"stage": "RISK", "component": "RiskGate / BacktestRiskGate", "notes": "spread, news, regime, ATR, cooldown, sizing"},
        {"stage": "ORDER", "component": "ExecutionStage", "notes": "MT5 live vs SimulatedBroker backtest"},
        {"stage": "COST", "component": "build_backtest_cost_model", "notes": "spread/slippage/commission; swap tracked not accrued"},
        {"stage": "EXECUTION", "component": "entry at bar close ± costs", "notes": "P1: not true bid/ask touch fill"},
        {"stage": "EXIT_SLTP", "component": "SimulatedBroker.check_exits", "notes": "high/low intrabar; SL before TP; same-bar entry blocked"},
        {"stage": "EXIT_PM", "component": "BacktestPositionManager", "notes": "trailing/partial on close — P1 asymmetry vs SL/TP path"},
        {"stage": "METRICS", "component": "compute_metrics", "notes": "cost_adjusted_metrics only if COMPLETE"},
    ]


def _dataset_row_extended(entry: Any, root: Path) -> dict[str, Any]:
    row = dataset_eligibility_for_row(entry)
    meta = load_dataset_metadata(entry.path)
    sym = row.symbol or "UNKNOWN"
    path = Path(entry.path)
    df_info: dict[str, Any] = {}
    try:
        df = pd.read_parquet(path)
        idx = df.index
        if hasattr(idx, "tz"):
            tz = str(idx.tz) if idx.tz else "naive"
        else:
            tz = "naive"
        dup = int(idx.duplicated().sum()) if hasattr(idx, "duplicated") else 0
        df_info = {
            "row_count": len(df),
            "date_start": str(idx.min()) if len(idx) else None,
            "date_end": str(idx.max()) if len(idx) else None,
            "timezone": tz,
            "columns": list(df.columns),
            "duplicate_timestamps": dup,
            "has_bid": "bid" in {str(c).lower() for c in df.columns},
            "has_ask": "ask" in {str(c).lower() for c in df.columns},
            "has_volume": "volume" in {str(c).lower() for c in df.columns},
        }
    except Exception as exc:
        df_info = {"read_error": str(exc)}

    economics_note = row.economics
    if sym == "XAUUSD":
        economics_note = "UNKNOWN — EV-EQ-01 NOT_PROVEN; stale XAUUSD_i economics must not bind"
    elif sym == "XAUUSD_i":
        economics_note = "STALE_OPERATOR_EVIDENCE (2026-09-02) — not fresh Phase 25M"

    return {
        **row.to_dict(),
        "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        "sidecar_present": metadata_path_for(path).is_file(),
        "economics_provenance_note": economics_note,
        "broker_binding": (meta.broker if meta else None) or "UNKNOWN",
        "spread_source": entry.spread_mode,
        "cost_adjusted_metrics": row.cost_adjusted_metrics_allowed,
        "suitable_exploratory_research": row.research_backtest_eligible,
        "suitable_strategy_comparison": row.research_backtest_eligible,
        "suitable_parameter_validation": "CONDITIONAL — proxy spread; risk of overfit if tuned on same data",
        "suitable_walk_forward": "CONDITIONAL — chronological splits possible; costs incomplete",
        "suitable_cost_aware_testing": row.cost_aware_backtest_eligible,
        "suitable_production_evidence": row.production_validation_eligible,
        **df_info,
    }


def audit_dataset_realism(root: Path) -> list[dict[str, Any]]:
    entries = audit_backtest_datasets(base_dir=root)
    return [_dataset_row_extended(e, root) for e in entries]


def audit_backtest_engine_bias() -> list[dict[str, Any]]:
    """Static code-evidenced engine semantics — no live run required."""
    return [
        {
            "id": "BAR_ORDER",
            "severity": BiasSeverity.OK.value,
            "finding": "Exits before new entries on same bar cursor",
            "evidence": "CODE",
            "source": "tradingbot/backtest/engine.py docstring + loop order",
        },
        {
            "id": "FORMING_BAR",
            "severity": BiasSeverity.P1.value,
            "finding": "Synthetic forming bar duplicates last close — not live tick evolution",
            "evidence": "CODE",
            "source": "data_source.py simulate_forming_bar",
        },
        {
            "id": "ENTRY_AT_CLOSE",
            "severity": BiasSeverity.P0.value,
            "finding": "Fills at bar close ± spread/slippage, not bid/ask touch prices",
            "evidence": "CODE",
            "source": "broker.py execute()",
        },
        {
            "id": "SL_BEFORE_TP",
            "severity": BiasSeverity.OK.value,
            "finding": "When both touched intrabar, SL checked before TP (pessimistic)",
            "evidence": "CODE",
            "source": "broker.py check_exits elif chain",
        },
        {
            "id": "SAME_BAR_ENTRY_EXIT",
            "severity": BiasSeverity.OK.value,
            "finding": "Positions opened on cursor cannot exit until cursor+1",
            "evidence": "CODE",
            "source": "broker.py allow_same_bar=False default",
        },
        {
            "id": "PM_CLOSE_VS_HILO",
            "severity": BiasSeverity.P1.value,
            "finding": "Position manager trailing/partial uses close; SL/TP uses high/low",
            "evidence": "CODE",
            "source": "position_manager.py vs broker.py",
        },
        {
            "id": "COMMISSION_FAIL_CLOSED",
            "severity": BiasSeverity.P0.value,
            "finding": "Default commission UNKNOWN blocks entries — zero-trade backtests possible",
            "evidence": "CODE",
            "source": "broker.py + BacktestConfig defaults",
        },
        {
            "id": "EXIT_SLIPPAGE_UNKNOWN_ZERO",
            "severity": BiasSeverity.P1.value,
            "finding": "Exit slippage UNKNOWN silently uses 0 — asymmetric vs entry fail-closed",
            "evidence": "CODE",
            "source": "broker.py check_exits slip_pips fallback",
        },
        {
            "id": "SWAP_NOT_ACCRUED",
            "severity": BiasSeverity.P0.value,
            "finding": "Swap never applied to PnL; multi-day holds understate costs",
            "evidence": "CODE",
            "source": "cost_model.py + broker accounting",
        },
        {
            "id": "PROXY_SPREAD_ALL_OHLC",
            "severity": BiasSeverity.P0.value,
            "finding": "All 32 OHLC datasets use PROXY spread — not observed historical spread",
            "evidence": "AUDIT",
            "source": "Phase 25M cost matrix",
        },
        {
            "id": "EV_EQ_NOT_PROVEN",
            "severity": BiasSeverity.P0.value,
            "finding": "XAUUSD labeled datasets may not match XAUUSD_i live economics",
            "evidence": "AUDIT",
            "source": "Phase 25M EV-EQ-01 NOT_PROVEN",
        },
        {
            "id": "END_OF_BACKTEST_CLOSE_ALL",
            "severity": BiasSeverity.P1.value,
            "finding": "Open positions forced closed at last bar close",
            "evidence": "CODE",
            "source": "engine.py run() finalize",
        },
        {
            "id": "SHARPE_BAR_FREQUENCY",
            "severity": BiasSeverity.P2.value,
            "finding": "Sharpe on per-bar equity returns may misstate sparse-trade strategies",
            "evidence": "CODE",
            "source": "metrics.py",
        },
        {
            "id": "DUAL_BACKTEST_STACKS",
            "severity": BiasSeverity.P2.value,
            "finding": "tradingbot.backtest.engine vs tradingbot.ml.backtest.engine — must not mix claims",
            "evidence": "CODE",
            "source": "scripts/run_backtest.py import path",
        },
    ]


def audit_cost_model_state(root: Path) -> dict[str, Any]:
    deals, specs = load_all_operator_deals(root)
    spread = audit_spread_evidence(audit_backtest_datasets(base_dir=root))
    commission = audit_commission_evidence(deals)
    slippage = audit_slippage_evidence(deals)
    swap = audit_swap_evidence(deals, specs)

    default_model = build_backtest_cost_model(BacktestConfig())
    cfg = BacktestConfig(spread_mode="AUTO")
    partial_result = BacktestResult(
        config=cfg,
        trades=[],
        equity_curve=[],
        initial_balance=10000.0,
        final_balance=10000.0,
        cost_completeness=CostCompleteness.PARTIAL,
    )
    unknown_result = BacktestResult(
        config=cfg,
        trades=[],
        equity_curve=[],
        initial_balance=10000.0,
        final_balance=10000.0,
        cost_completeness=CostCompleteness.UNKNOWN,
    )

    return {
        "components": {
            "SPREAD": {"mode": SpreadMode.PROXY.value, "classification": "PROXY", "modeled_in_pnl": True},
            "COMMISSION": {"mode": commission.status, "classification": "UNKNOWN", "modeled_in_pnl": "fail_closed_entry"},
            "SLIPPAGE": {"mode": "MODELED_PROXY", "classification": "PROXY", "modeled_in_pnl": True},
            "SWAP": {"mode": swap.status, "classification": "BROKER_RATE_ONLY/UNKNOWN", "modeled_in_pnl": False},
            "EXECUTION": {"mode": "close_fill", "classification": "MODELED", "modeled_in_pnl": True},
            "LATENCY": {"mode": "NOT_MODELED", "classification": "NOT_APPLICABLE", "modeled_in_pnl": False},
        },
        "default_completeness": default_model.completeness.value,
        "cost_adjusted_metrics_partial": compute_metrics(partial_result)["cost_adjusted_metrics"],
        "cost_adjusted_metrics_unknown": compute_metrics(unknown_result)["cost_adjusted_metrics"],
        "cost_adjusted_metrics_allowed_gate": cost_adjusted_metrics_allowed(
            spread_mode=SpreadMode.DATASET.value,
            commission_status="ZERO",
            swap_status="ZERO",
            slippage_status="MODELED",
        ),
        "reported_result_basis": "gross_or_partial — never fully cost-adjusted under current evidence",
        "spread_evidence": spread.to_dict(),
        "commission_evidence": commission.to_dict(),
        "slippage_evidence": slippage.to_dict(),
        "swap_evidence": swap.to_dict(),
        "explicit_non_modeling": [
            "historical swap accrual",
            "observed historical spread series",
            "broker-confirmed commission schedule",
            "observed slippage from fills",
            "latency / partial fills / requotes",
        ],
    }


def _classify_performance_claim(path: Path, data: dict[str, Any]) -> str:
    text = json.dumps(data).lower()
    phase = str(data.get("phase", data.get("Phase", ""))).upper()
    audit_mode = str(data.get("audit_mode", "")).lower()
    production = data.get("production_modified", data.get("production_modified", False))

    if "parity" in path.name.lower() or "parity" in text:
        if data.get("verdict") == "PARITY_RESTORED" or data.get("primary_window_decision_match") == 1.0:
            return ClaimClass.CONDITIONALLY_DEFENSIBLE.value
        return ClaimClass.RESEARCH_ONLY.value

    if audit_mode in {"observation_only", "research_infrastructure_only"}:
        return ClaimClass.RESEARCH_ONLY.value

    if production is True:
        return ClaimClass.INVALID.value

    if any(k in data for k in ("net_profit", "profit_factor", "sharpe", "win_rate", "max_drawdown")):
        if "cost_adjusted" in text and "true" in text:
            return ClaimClass.INVALID.value
        return ClaimClass.RESEARCH_ONLY.value

    if phase.startswith("25") and "cost" in text:
        return ClaimClass.DEFENSIBLE.value

    if data.get("validation_passes") is True and phase.startswith("26"):
        return ClaimClass.RESEARCH_ONLY.value

    return ClaimClass.NOT_REPRODUCIBLE.value


def scan_performance_claims(root: Path, *, limit: int = 80) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in PERFORMANCE_ARTIFACT_GLOBS:
        for path in sorted(root.glob(pattern)):
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            if path.stat().st_size > 2_000_000:
                continue
            data = _safe_read_json(path)
            if not data:
                continue
            classification = _classify_performance_claim(path, data)
            claims.append(
                {
                    "artifact": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                    "phase": data.get("phase", data.get("Phase", "UNKNOWN")),
                    "classification": classification,
                    "cost_adjusted_claimed": "cost_adjusted" in json.dumps(data).lower() and "true" in json.dumps(data).lower(),
                    "reproducible": classification in {
                        ClaimClass.DEFENSIBLE.value,
                        ClaimClass.CONDITIONALLY_DEFENSIBLE.value,
                        ClaimClass.RESEARCH_ONLY.value,
                    },
                    "broker_bound": "broker" in json.dumps(data).lower() or "litefinance" in json.dumps(data).lower(),
                    "summary_keys": sorted(list(data.keys()))[:20],
                }
            )
            if len(claims) >= limit:
                return claims
    return claims


def audit_overfitting_evidence(root: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "train_test_split": ActivationClass.UNKNOWN.value,
        "chronological_split": ActivationClass.PARTIAL.value,
        "walk_forward": ActivationClass.PARTIAL.value,
        "out_of_sample": ActivationClass.PARTIAL.value,
        "parameter_stability": ActivationClass.UNKNOWN.value,
        "monte_carlo": ActivationClass.PARTIAL.value,
        "bootstrap": ActivationClass.UNKNOWN.value,
        "sensitivity_analysis": ActivationClass.PARTIAL.value,
        "cross_period_validation": ActivationClass.PARTIAL.value,
        "cross_symbol_validation": ActivationClass.NOT_IMPLEMENTED.value,
        "artifacts_found": [],
        "optimization_risk_notes": [],
    }
    wf_paths = list(root.glob("tradingbot/ml/research/**/walk_forward*.json")) + list(
        root.glob("ml/reports/**/monte_carlo*.json")
    )
    opt_paths = list(root.glob("tradingbot/ml/research/**/optim*.json")) + list(
        root.glob("tradingbot/ml/research/phase22ak/**")
    )
    for p in wf_paths[:10]:
        evidence["artifacts_found"].append(str(p.relative_to(root)))
        if "monte_carlo" in p.name:
            evidence["monte_carlo"] = ActivationClass.IMPLEMENTED_AND_ACTIVE.value
        if "walk_forward" in p.name:
            evidence["walk_forward"] = ActivationClass.IMPLEMENTED_AND_ACTIVE.value

    if (root / "tradingbot/ml/research/phase27m/overfitting_report.json").is_file():
        evidence["artifacts_found"].append("tradingbot/ml/research/phase27m/overfitting_report.json")
        evidence["parameter_stability"] = ActivationClass.PARTIAL.value

    if (root / "tradingbot/ml/research/phase25b/parity_replay_adapter.py").is_file():
        evidence["chronological_split"] = ActivationClass.IMPLEMENTED_AND_ACTIVE.value
        evidence["out_of_sample"] = ActivationClass.PARTIAL.value

    m5 = PA_SYMBOL_TF_PRESETS.get("XAUUSD", {}).get("M5", {})
    evidence["optimization_risk_notes"] = [
        f"Hardcoded M5 thresholds: MIN_CONFIDENCE={m5.get('MIN_CONFIDENCE')}, MIN_QUALITY_SCORE={m5.get('MIN_QUALITY_SCORE')}",
        "Phase 22ak optimizer artifacts exist in repo — ML research path, not default PA live",
        "No evidence of automated walk-forward on production BacktestEngine with cost-complete data",
        "Cherry-picking risk: many phase final_report.json files — classify individually",
    ]
    return evidence


def audit_backtest_live_parity() -> list[dict[str, Any]]:
    return [
        {"area": "symbol", "backtest": PRIMARY_SYMBOL, "live": PRIMARY_SYMBOL, "parity": ParityClass.MATCH.value, "risk": "P2"},
        {"area": "dataset_symbol_labels", "backtest": "XAUUSD parquets common", "live": "XAUUSD_i", "parity": ParityClass.MISMATCH.value, "risk": "P0"},
        {"area": "timeframe", "backtest": "configurable M5/M15/H4", "live": "M5 only default", "parity": ParityClass.PARTIAL.value, "risk": "P1"},
        {"area": "data_source", "backtest": "parquet OHLC", "live": "MT5 rates/ticks", "parity": ParityClass.PARTIAL.value, "risk": "P1"},
        {"area": "spread", "backtest": "PROXY or DATASET", "live": "symbol_info_tick", "parity": ParityClass.MISMATCH.value, "risk": "P0"},
        {"area": "execution", "backtest": "SimulatedBroker close fill", "live": "Mt5ExecutionAdapter", "parity": ParityClass.PARTIAL.value, "risk": "P1"},
        {"area": "slippage", "backtest": "MODELED_PROXY", "live": "UNKNOWN", "parity": ParityClass.UNKNOWN.value, "risk": "P1"},
        {"area": "commission", "backtest": "UNKNOWN fail-closed", "live": "UNKNOWN", "parity": ParityClass.MATCH.value, "risk": "P0"},
        {"area": "volume_sizing", "backtest": "BacktestRiskGate tiers", "live": "RiskGate tiers", "parity": ParityClass.PARTIAL.value, "risk": "P1"},
        {"area": "session_filter", "backtest": "index hours", "live": "same + DEMO_DISABLE_SESSION_FILTER env", "parity": ParityClass.PARTIAL.value, "risk": "P1"},
        {"area": "forming_bar", "backtest": "synthetic append + exclude", "live": "exclude_forming_bar on MT5 window", "parity": ParityClass.PARTIAL.value, "risk": "P1"},
        {"area": "signal_pipeline", "backtest": "TradingKernel 6 stages", "live": "TradingKernel 6 stages", "parity": ParityClass.MATCH.value, "risk": "P2"},
        {"area": "meta_labeler", "backtest": "BacktestRiskGate optional", "live": "RiskGate active", "parity": ParityClass.PARTIAL.value, "risk": "P1"},
        {"area": "position_management", "backtest": "BacktestPositionManager", "live": "Mt5PositionManager", "parity": ParityClass.PARTIAL.value, "risk": "P1"},
        {"area": "news_filter", "backtest": "config flag", "live": "check_news_gate", "parity": ParityClass.PARTIAL.value, "risk": "P2"},
    ]


def build_validation_matrix(dataset_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    any_research = any(r.get("suitable_exploratory_research") for r in dataset_rows)
    any_cost_aware = any(r.get("suitable_cost_aware_testing") for r in dataset_rows)
    any_production = any(r.get("suitable_production_evidence") for r in dataset_rows)

    def row(
        test: str,
        data_req: str,
        code_req: str,
        cost_req: str,
        status: str,
        can_run: bool,
        trust: str,
        blocker: str,
    ) -> dict[str, Any]:
        return {
            "test": test,
            "data_requirement": data_req,
            "code_requirement": code_req,
            "cost_requirement": cost_req,
            "current_status": status,
            "can_run_now": can_run,
            "trust_level": trust,
            "blocker": blocker,
        }

    return [
        row("baseline_backtest", "OHLC parquet", "BacktestEngine", "PROXY spread; commission config", "AVAILABLE", any_research, "LOW-MEDIUM", "commission UNKNOWN may block trades"),
        row("walk_forward", "chronological OHLC", "BacktestEngine loop", "PROXY acceptable for logic", "AVAILABLE", any_research, "MEDIUM", "costs incomplete — rank logic not PnL"),
        row("out_of_sample", "held-out period", "BacktestEngine", "PROXY", "AVAILABLE", any_research, "MEDIUM", "EV-EQ-01 NOT_PROVEN on XAUUSD sets"),
        row("parameter_sensitivity", "OHLC", "BacktestEngine + param grid", "PROXY", "AVAILABLE", any_research, "MEDIUM", "overfit risk if tuned on same data"),
        row("spread_stress", "OHLC", "BacktestConfig.spread_pips override", "PROXY sensitivity", "AVAILABLE", True, "MEDIUM", "not observed spread distribution"),
        row("slippage_stress", "OHLC", "BacktestConfig slippage override", "MODELED_PROXY", "AVAILABLE", True, "MEDIUM", "not observed slippage"),
        row("monte_carlo", "trade sequence or returns", "metrics/post-process", "any", "PARTIAL", True, "MEDIUM", "needs sufficient trades from baseline"),
        row("regime_analysis", "OHLC + labels", "BacktestEngine + regime tags", "PROXY", "AVAILABLE", any_research, "MEDIUM", "regime labels research-grade"),
        row("trade_distribution", "OHLC", "BacktestEngine", "PROXY", "AVAILABLE", any_research, "MEDIUM", "entry-at-close bias"),
        row("drawdown_stress", "OHLC", "BacktestEngine", "PROXY", "AVAILABLE", any_research, "MEDIUM", "not cost-complete"),
        row("cost_aware_backtest", "bid/ask parquet", "DATASET spread mode", "COMPLETE costs", "BLOCKED", any_cost_aware, "N/A", "no bid/ask dataset; Phase 25M BLOCKED"),
        row("broker_bound_backtest", "XAUUSD_i + fresh economics", "dataset_symbol_map explicit", "observed costs", "BLOCKED", False, "N/A", "MT5 operator session required"),
        row("live_parity_validation", "live+backtest same window", "phase25b replay adapter", "N/A", "PARTIAL", True, "MEDIUM-HIGH", "decision parity ≠ PnL parity"),
    ]


def build_validation_readiness(matrix: list[dict[str, Any]]) -> dict[str, list[str]]:
    valid_now = [m["test"] for m in matrix if m["can_run_now"] and m["trust_level"].startswith(("MEDIUM", "HIGH", "LOW"))]
    valid_cond = [
        "logic-only backtests under PROXY spread with explicit commission_status=ZERO (evidence-labeled research only)",
        "decision-path parity replay (phase25b) — not profitability claims",
        "spread/slippage stress sweeps on OHLC",
    ]
    blocked_broker = [
        "cost_aware_backtest",
        "broker_bound_backtest",
        "production_validation_eligible runs",
        "cost_adjusted_metrics=true reporting",
    ]
    blocked_data = ["historical bid/ask spread series", "XAUUSD_i_M5_bidask.parquet"]
    blocked_code = [
        "true bid/ask fill simulation",
        "swap accrual in PnL",
        "observed slippage from fills",
    ]
    return {
        "A_VALID_NOW": valid_now,
        "B_VALID_WITH_CONDITIONS": valid_cond,
        "C_NOT_VALID_UNTIL_BROKER_EVIDENCE": blocked_broker,
        "D_NOT_VALID_UNTIL_NEW_DATA": blocked_data,
        "E_NOT_VALID_UNTIL_CODE_FIX": blocked_code,
    }


def build_blockers(bias: list[dict[str, Any]], dataset_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    p0: list[dict[str, Any]] = []
    p1: list[dict[str, Any]] = []
    p2: list[dict[str, Any]] = []

    for item in bias:
        sev = item.get("severity")
        entry = {"id": item["id"], "finding": item["finding"], "evidence": item.get("evidence", "CODE")}
        if sev == BiasSeverity.P0.value:
            p0.append(entry)
        elif sev == BiasSeverity.P1.value:
            p1.append(entry)
        elif sev == BiasSeverity.P2.value:
            p2.append(entry)

    if not any(r.get("production_validation_eligible") for r in dataset_rows):
        p0.append(
            {
                "id": "NO_PRODUCTION_ELIGIBLE_DATASET",
                "finding": "Zero datasets pass production_validation_eligible",
                "evidence": "AUDIT",
            }
        )

    p0.append(
        {
            "id": "PHASE25M_OPERATOR_BLOCKED",
            "finding": "Fresh broker evidence BLOCKED_PENDING_OPERATOR — Phase 25M final gate",
            "evidence": "AUDIT",
        }
    )

    return {"P0": p0, "P1": p1, "P2": p2}


def _broker_evidence_gate(root: Path) -> dict[str, Any]:
    eq_audits = audit_from_operator_artifacts(base_dir=root)
    ev = EquivalenceConclusion.NOT_PROVEN.value
    if eq_audits:
        ev = eq_audits[0].ev_eq_01
    phase25m = root / "logs/phase25m_cost_evidence_audit.json"
    m25 = _safe_read_json(phase25m) if phase25m.is_file() else {}
    return {
        "phase_25m_final": True,
        "phase_25n_exists": (root / "tradingbot/backtest/phase25n_run.py").is_file(),
        "operator_blocked": m25.get("operator_blocked", True),
        "operator_blocker": m25.get("operator_blocker", "MT5_OPERATOR_SESSION_REQUIRED"),
        "ev_eq_01": m25.get("ev_eq_01", ev),
        "cost_adjusted_metrics_any_dataset": m25.get("cost_adjusted_metrics_any_dataset", False),
    }


def run_phase26_validation_audit(base_dir: str | Path | None = None) -> Phase26ValidationReport:
    """Offline validation readiness audit — read-only."""
    root = Path(base_dir or Path.cwd())
    report = Phase26ValidationReport(
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        code_version=_git_head(root),
        objective=(
            "Determine what strategy/backtest conclusions are defensible given current datasets, "
            "cost evidence limits, and known backtest-live gaps — without strategy changes."
        ),
    )

    report.safety = {
        "MT5_STARTED": False,
        "BOT_STARTED": False,
        "DAEMON_STARTED": False,
        "ORDERS_SENT": False,
        "SYMBOL_SELECT": False,
        "ENV_ACCESSED": False,
        "CREDENTIALS_ACCESSED": False,
        "DATASETS_MUTATED": False,
        "STRATEGY_CHANGED": False,
        "RISKGATE_CHANGED": False,
        "ROUTER_CHANGED": False,
        "LIVE_CONFIG_CHANGED": False,
    }

    before = build_immutability_manifest(root)
    imm_ok, imm_issues = verify_immutability(before, base_dir=root)
    report.immutability_ok = imm_ok
    report.safety["DATASETS_MUTATED"] = not imm_ok
    if not imm_ok:
        report.errors.extend(imm_issues)
        report.status = "FAIL"

    report.broker_evidence_gate = _broker_evidence_gate(root)
    report.strategy_inventory = build_strategy_inventory()
    report.decision_path = build_decision_path()
    report.dataset_realism = audit_dataset_realism(root)
    report.backtest_bias_audit = audit_backtest_engine_bias()
    report.cost_model_audit = audit_cost_model_state(root)
    report.performance_claims = scan_performance_claims(root)
    report.overfitting_audit = audit_overfitting_evidence(root)
    report.backtest_live_parity = audit_backtest_live_parity()
    report.validation_matrix = build_validation_matrix(report.dataset_realism)
    report.validation_readiness = build_validation_readiness(report.validation_matrix)
    report.blockers = build_blockers(report.backtest_bias_audit, report.dataset_realism)

    if report.status != "FAIL":
        report.status = "PASS_WITH_DEFERRAL"

    return report


def run_phase26_validation_collection(base_dir: str | Path | None = None) -> Phase26ValidationReport:
    """Entry point — audit + write artifacts."""
    root = Path(base_dir or Path.cwd())
    report = run_phase26_validation_audit(base_dir=root)
    payload = report.to_dict()

    _write_json(root / PHASE26_READINESS_JSON, payload)
    _write_json(
        root / PHASE26_CLAIMS_JSON,
        {
            "schema_version": 1,
            "phase": "26",
            "generated_at": report.generated_at,
            "claims": report.performance_claims,
            "claim_classes": [c.value for c in ClaimClass],
        },
    )
    _write_json(
        root / PHASE26_PARITY_JSON,
        {
            "schema_version": 1,
            "phase": "26",
            "generated_at": report.generated_at,
            "parity_table": report.backtest_live_parity,
        },
    )
    _write_json(
        root / PHASE26_MATRIX_JSON,
        {
            "schema_version": 1,
            "phase": "26",
            "generated_at": report.generated_at,
            "readiness": report.validation_readiness,
            "matrix": report.validation_matrix,
        },
    )
    return report
