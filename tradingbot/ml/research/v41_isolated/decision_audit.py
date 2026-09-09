"""Phase 1.5.51–1.5.55 — deferred-cost / v41 evidence decision (offline, no fills invented)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingbot.config.live import PRIMARY_SYMBOL, SYMBOL_CONFIGS
from tradingbot.config.pa_symbol_tf_presets import normalize_symbol as normalize_pa
from tradingbot.domain.live_gates import normalize_symbol as normalize_gates
from tradingbot.domain.order_logic import order_value
from tradingbot.domain.position_logic import contract_size, pip_size
from tradingbot.ml.data.paths import candle_path, reports_dir, spread_dir, ticks_dir
from tradingbot.ml.research.v41_isolated.replay import MIN_TRADES_FOR_INFERENCE

RESEARCH_SYMBOL = "XAUUSD"
LIVE_SYMBOL = "XAUUSD_i"


def _file_count(root: Path) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("*") if p.is_file())


def classify_cost_sources(*, live_fill_n: int = 17) -> list[dict[str, Any]]:
    """A/B/C/D labels. Does not load MT5. live_fill_n is the already-audited journal count."""
    n_spread = _file_count(spread_dir())
    n_ticks = _file_count(ticks_dir())
    return [
        {
            "source": "data/ml/raw/spread",
            "class": "C" if n_spread == 0 else "B",
            "n_files": n_spread,
            "note": "directory exists; zero parquet — cannot form round-trip costs",
        },
        {
            "source": "data/ml/raw/ticks",
            "class": "C" if n_ticks == 0 else "B",
            "n_files": n_ticks,
            "note": "directory exists; zero parquet",
        },
        {
            "source": "XAUUSD M5/M15/H4 candles",
            "class": "B",
            "path": str(candle_path(RESEARCH_SYMBOL, "M5")),
            "present": Path(candle_path(RESEARCH_SYMBOL, "M5")).is_file(),
            "note": "OHLC for replay/ATR unit conversion only — not bid/ask",
        },
        {
            "source": "XAUUSD_i M5 candles",
            "class": "C",
            "path": str(candle_path(LIVE_SYMBOL, "M5")),
            "present": Path(candle_path(LIVE_SYMBOL, "M5")).is_file(),
            "note": "no live-symbol candle file in the research store",
        },
        {
            "source": "trade_journal live executions",
            "class": "C",
            "n": live_fill_n,
            "note": (
                f"{live_fill_n} entry-slippage rows; not round-trip; not v41-TREND; "
                f"n < {MIN_TRADES_FOR_INFERENCE}; inadmissible as a cost model"
            ),
        },
        {
            "source": "trade_journal paper_trades spread=0.30",
            "class": "D",
            "note": "hard-coded PaperBroker default; engine phase9_9; not measured",
        },
        {
            "source": "paper executions slippage=0",
            "class": "D",
            "note": "always zero — not broker tape",
        },
        {
            "source": "data/ml/live jsonl",
            "class": "C",
            "note": "decision logs; no bid/ask/spread/slippage fields (1.5.46 peek)",
        },
        {
            "source": "XAUUSD_M5_dataset_v2.parquet spread_pips",
            "class": "D",
            "note": (
                "sparse_event_builder.build_bar_spread_proxy_series: "
                "(high-low)/pip_size clipped to 5.0 — OHLC bar range, not bid/ask"
            ),
        },
        {
            "source": "phase20c spread_analysis.json / slippage_analysis.json",
            "class": "C",
            "note": "status PENDING, count=0, reason no_spread_samples / no_slippage_samples",
        },
        {
            "source": "engine_settings XAUUSD_i.max_spread=0.0200",
            "class": "D",
            "note": "heuristic filter, not a measured tape; units not empirically proven",
        },
        {
            "source": "BrokerConstraints tick_size/tick_value",
            "class": "D",
            "note": "derived from pip_size/contract_size heuristics in accounting/broker_constraints.py",
        },
        {
            "source": "data/backtest cache",
            "class": "C",
            "note": "strategy cache files, not a bid/ask tape",
        },
        {
            "source": "root reports/ historical exports",
            "class": "C",
            "note": "reports/ empty; data/exports and data/historical absent",
        },
        {
            "source": "PaperBroker / BacktestConfig / execution_costs.py",
            "class": "D",
            "note": "assumed constants; already shown to wipe +0.033 R if treated as truth",
        },
        {
            "source": "phase19a random 0-0.15R",
            "class": "D",
            "note": "fabricated stress",
        },
        {
            "source": "phase27h commission_per_lot_round=7.0",
            "class": "D",
            "note": "research stress constant, not a broker invoice",
        },
        {
            "source": "RiskGate tick_value / MT5 symbol_info",
            "class": "C",
            "note": "live-only; obtaining it here would start MT5 — forbidden",
        },
    ]


def symbol_identity_audit() -> dict[str, Any]:
    """Code conventions vs unproven market identity. Does not change live config."""
    pa = normalize_pa(LIVE_SYMBOL)
    gates = normalize_gates(LIVE_SYMBOL)
    pip_r = pip_size(RESEARCH_SYMBOL)
    pip_l = pip_size(LIVE_SYMBOL)
    cs_r = contract_size(RESEARCH_SYMBOL)
    cs_l = contract_size(LIVE_SYMBOL)
    ov_l = order_value(LIVE_SYMBOL, 0.01, 2000.0)
    ov_r = order_value(RESEARCH_SYMBOL, 0.01, 2000.0)
    from tradingbot.domain.broker_economics import BrokerEconomics

    _observed = {
        "point": 0.01,
        "digits": 2,
        "contract_size": 100.0,
        "tick_size": 0.01,
        "tick_value": 1.0,
        "tick_value_profit": 1.0,
        "tick_value_loss": 1.0,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "volume_step": 0.01,
        "stops_level": 0,
        "freeze_level": 0,
    }
    eco_l = BrokerEconomics.from_mapping(LIVE_SYMBOL, _observed)
    eco_r = BrokerEconomics.from_mapping(RESEARCH_SYMBOL, _observed)
    ov_l_broker = order_value(LIVE_SYMBOL, 0.01, 2000.0, economics=eco_l)
    ov_r_broker = order_value(RESEARCH_SYMBOL, 0.01, 2000.0, economics=eco_r)
    return {
        "research_symbol": RESEARCH_SYMBOL,
        "live_symbol": LIVE_SYMBOL,
        "primary_symbol_constant": PRIMARY_SYMBOL,
        "normalize_pa": pa,
        "normalize_gates": gates,
        "code_alias_maps_to_xauusd": pa == RESEARCH_SYMBOL and gates == RESEARCH_SYMBOL,
        "price_scale": {
            "pip_size_research": pip_r,
            "pip_size_live": pip_l,
            "equal": pip_r == pip_l,
            "empirical": False,
            "source": "tradingbot/domain/position_logic.py heuristic",
        },
        "point_size": {
            "same_heuristic": pip_r == pip_l,
            "proven_from_broker": False,
        },
        "contract_specification": {
            "contract_size_research": cs_r,
            "contract_size_live": cs_l,
            "equal_heuristic": cs_r == cs_l,
            "order_value_lot0.01_px2000_live": ov_l,
            "order_value_lot0.01_px2000_research": ov_r,
            "order_value_equal_without_economics": ov_l == ov_r,
            "order_value_broker_live": ov_l_broker,
            "order_value_broker_research": ov_r_broker,
            "order_value_equal_with_same_broker_economics": ov_l_broker == ov_r_broker,
            "order_value_equal": ov_l_broker == ov_r_broker,
            "note": (
                "Phase 25A: order_value requires broker economics (fail-closed without). "
                "Same observed contract_size yields equal notional; broker identity still unproven."
            ),
            "proven_from_broker": False,
        },
        "spread_behavior": {
            "proven": False,
            "reason": "no bid/ask tape for either symbol; live SYMBOL_CONFIGS share a 0.50 assumed threshold",
            "symbol_configs_share_gold_block": set(SYMBOL_CONFIGS) >= {RESEARCH_SYMBOL, LIVE_SYMBOL},
        },
        "tick_value": {"proven": False, "reason": "requires MT5 symbol_info — not queried"},
        "commission": {"proven": False, "reason": "paper/backtest defaults 0.0; live unknown"},
        "execution_model": {
            "proven": False,
            "reason": "research replay uses bar high/low SL/TP; live uses Mt5ExecutionAdapter",
        },
        "candle_files": {
            "xauusd_m5": Path(candle_path(RESEARCH_SYMBOL, "M5")).is_file(),
            "xauusd_i_m5": Path(candle_path(LIVE_SYMBOL, "M5")).is_file(),
        },
        "engine_settings_max_spread": {
            "symbol": LIVE_SYMBOL,
            "value": 0.0200,
            "source": "tradingbot/config/engine_settings.py heuristic",
            "empirical": False,
        },
        "missing_for_identity": [
            "live XAUUSD_i candle file",
            "paired bid/ask quotes for both names",
            "broker tick_size/tick_value snapshot",
            "commission schedule",
            "measured spread distribution",
            "execution-model comparison (bar SL/TP vs Mt5ExecutionAdapter fills)",
            "order_value formula agreement (currently 1000x divergent at lot 0.01 / px 2000)",
        ],
        "identity_proven": False,
    }


def evidence_gaps() -> list[dict[str, Any]]:
    return [
        {
            "rank": 1,
            "item": "real XAUUSD_i bid/ask tape",
            "why": "round-trip spread is the dominant unknown vs a 0.033 R edge",
            "minimum": "timestamped bid/ask (or spread) covering the OOS window, n_bars >> 30 aligned to trades",
            "offline_from_repo": False,
            "requires_mt5_or_export": True,
            "currently_available": False,
        },
        {
            "rank": 2,
            "item": "entry + exit slippage",
            "why": "17 rows are entry-only; exit leg can double the cost",
            "minimum": ">=30 live fills on each of entry and exit, same symbol, no paper mixing",
            "offline_from_repo": False,
            "requires_mt5_or_export": True,
            "currently_available": False,
        },
        {
            "rank": 3,
            "item": "commission",
            "why": "defaults are 0.0; even small per-lot fees exceed 0.033 R on gold",
            "minimum": "broker schedule or measured commission on closed tickets",
            "offline_from_repo": False,
            "requires_mt5_or_export": True,
            "currently_available": False,
        },
        {
            "rank": 4,
            "item": "tick/contract specification",
            "why": "order_value(XAUUSD) != order_value(XAUUSD_i); broker tick_value unqueried",
            "minimum": "MT5 symbol_info tick_size/tick_value/contract OR a saved snapshot JSON",
            "offline_from_repo": False,
            "requires_mt5_or_export": True,
            "currently_available": False,
        },
        {
            "rank": 5,
            "item": "symbol identity mapping",
            "why": "code aliases names; does not prove equal spread/execution",
            "minimum": "paired quotes or broker spec showing XAUUSD vs XAUUSD_i are the same instrument",
            "offline_from_repo": False,
            "requires_mt5_or_export": True,
            "currently_available": False,
        },
        {
            "rank": 6,
            "item": "sufficiently large cost sample",
            "why": "n=17 < 30; 2 outliers dominate the mean",
            "minimum": f">={MIN_TRADES_FOR_INFERENCE} independent live round-trips (preferably hundreds)",
            "offline_from_repo": False,
            "requires_mt5_or_export": True,
            "currently_available": False,
        },
        {
            "rank": 7,
            "item": "cost-aware OOS replay",
            "why": "gross PF 1.05 is not net; 0.04 R already negative",
            "minimum": "replay the frozen book with measured per-trade costs, not assumed constants",
            "offline_from_repo": False,
            "requires_mt5_or_export": True,
            "currently_available": False,
        },
        {
            "rank": 8,
            "item": "robustness after costs",
            "why": "uncosted rolling 250-windows already lose 33% of the time",
            "minimum": "year/session/rolling metrics still viable after measured costs",
            "offline_from_repo": False,
            "requires_mt5_or_export": True,
            "currently_available": False,
        },
        {
            "rank": 9,
            "item": "retrain walk-forward",
            "why": "would be a different model than frozen checksum; only after net edge exists",
            "minimum": "justified only if items 1–8 show a surviving measured edge",
            "offline_from_repo": False,
            "requires_mt5_or_export": False,
            "currently_available": False,
            "deferred_until": "measured net edge exists",
        },
    ]


def cost_model_decision() -> dict[str, Any]:
    """No defensible v41 cost model can be built from repo evidence without fabrication."""
    sources = classify_cost_sources()
    usable_a = [s for s in sources if s.get("class") == "A"]
    return {
        "defensible_cost_model_exists": False,
        "class_A_sources": usable_a,
        "reason": (
            "No class-A round-trip tape. Class-B OHLC cannot supply spread. "
            "n=17 live entry slips are class C. Dataset spread_pips is an OHLC bar-range "
            "proxy clipped at 5.0 (class D). Paper 0.30 / backtest 2.5 pips are class D. "
            "Building a model from those would manufacture broker costs."
        ),
        "supports_calibration": False,
        "supports_further_research": (
            "only if an operator later provides an offline-exported tape; "
            "this process must not start MT5 to collect it"
        ),
        "supports_stopping_v41_entirely": False,
        "stop_reason": (
            "uncosted OOS expectancy is still slightly positive — D is not met; "
            "keep the frozen bundle as research, do not calibrate"
        ),
    }


def classify_phase55() -> dict[str, Any]:
    identity = symbol_identity_audit()
    model = cost_model_decision()
    return {
        "classification": "C",
        "label": "insufficient evidence, remain neutral",
        "v41_remains_neutral_1_0": True,
        "production_calibrators_modified": False,
        "calibration_justified": False,
        "defensible_cost_model_exists": model["defensible_cost_model_exists"],
        "identity_proven": identity["identity_proven"],
        "reason": (
            "No class-A cost tape; symbol identity unproven; gross +0.033 R dies at 0.04 R "
            "sensitivity; 17 live slips insufficient. Not D because uncosted OOS expectancy > 0."
        ),
        "recommended_next_phase": (
            "STOP agent-driven v41 work. If a human later exports an XAUUSD_i bid/ask "
            "(and commission) tape without this agent starting MT5, a new OFFLINE ingest "
            "phase may re-score the frozen OOS book. Do not collect that tape from here."
        ),
    }


def run_decision_audit(*, write_reports: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "phase": "1.5.51-1.5.55",
        "offline_only": True,
        "prior_json_not_rewritten": [
            "data/ml/reports/phase15_36/v41_isolated_trend_replay.json",
            "data/ml/reports/phase15_41/v41_cost_robustness.json",
            "data/ml/reports/phase15_46/v41_cost_followup.json",
        ],
        "cost_sources": classify_cost_sources(),
        "symbol_identity": symbol_identity_audit(),
        "cost_model": cost_model_decision(),
        "evidence_gaps": evidence_gaps(),
        "decision": classify_phase55(),
    }
    if write_reports:
        out = reports_dir() / "phase15_51"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "v41_decision_audit.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        payload["report_path"] = str(path)
    return payload


if __name__ == "__main__":
    result = run_decision_audit()
    keep = {
        "decision": result.get("decision"),
        "cost_model": result.get("cost_model"),
        "identity_proven": (result.get("symbol_identity") or {}).get("identity_proven"),
        "class_A": [
            s.get("source") for s in (result.get("cost_sources") or []) if s.get("class") == "A"
        ],
        "n_sources": len(result.get("cost_sources") or []),
        "report_path": result.get("report_path"),
    }
    print(json.dumps(keep, indent=2, default=str))
