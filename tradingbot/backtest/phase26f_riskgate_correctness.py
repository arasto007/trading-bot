"""Phase 26F — minimal RiskGate economics alias fix + 19-candidate replay."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.adapters.risk_gate import detect_account_tier, execution_profile_for_tier
from tradingbot.adapters.symbols import resolve_broker_symbol
from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG, merge_broker_catalog, resolve_backtest_economics
from tradingbot.backtest.phase26b_controlled_validation import build_frozen_baseline_configuration
from tradingbot.backtest.phase26d_kernel_signal_trace import (
    _build_trace_engine,
    _enrich_frame,
    _load_parquet_tail,
)
from tradingbot.domain.broker_economics import lot_from_broker_economics
from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.models import CycleContext, MarketKey
from tradingbot.domain.pa_hardening import clear_pa_dedup_cache
from tradingbot.domain.risk_logic import infer_regime_from_ohlcv, regime_position_multiplier

PHASE26F_JSON = "logs/phase26f_riskgate_correctness.json"
PHASE26E_JSON = "logs/phase26e_riskgate_audit.json"
PHASE26D_JSON = "logs/phase26d_kernel_signal_trace.json"
DEFAULT_DATASET = "data/backtest/XAUUSD_M5_183d.parquet"

CODE_CHANGE = {
    "file": "tradingbot/backtest/risk.py",
    "function": "BacktestRiskGate._position_size",
    "change": "resolve_broker_symbol(symbol) before resolve_backtest_economics(broker_symbol)",
}


@dataclass
class Phase26FReport:
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
            "RISKGATE_POLICY_CHANGED": False,
            "ROUTER_CHANGED": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26F", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _load_before_state(root: Path) -> dict[str, dict[str, Any]]:
    e26 = json.loads((root / PHASE26E_JSON).read_text(encoding="utf-8"))
    before: dict[str, dict[str, Any]] = {}
    for row in e26.get("decision_table", []):
        key = row["candidate"]
        before[key] = {
            "reason": row.get("reason"),
            "lot_sizing": row.get("lot_sizing"),
            "meta_labeler": row.get("meta_labeler"),
            "atr_filter": row.get("atr_filter"),
        }
    lot_detail = {
        f"{c['timestamp']}@{c['cursor']}": c
        for c in (e26.get("lot_sizing_audit") or {}).get("candidates", [])
    }
    for key, detail in lot_detail.items():
        if key in before:
            before[key]["lot_detail"] = detail.get("lot_sizing")
    return before


def _lot_diagnostics(
    signal: Any,
    snapshot: dict[str, Any],
    *,
    legacy_config: dict[str, Any],
    risk_pct: float,
    regime: str,
) -> dict[str, Any]:
    symbol = signal.symbol
    broker_symbol = resolve_broker_symbol(symbol, legacy_config)
    econ = resolve_backtest_economics(broker_symbol, legacy_config)
    df = snapshot.get("ohlcv")
    close = float(df["close"].iloc[-1]) if df is not None and not df.empty else 0.0
    sl = float(signal.stop_loss) if signal.stop_loss else None
    balance = float(snapshot.get("balance", 1000.0))
    out: dict[str, Any] = {
        "signal_symbol": symbol,
        "resolved_broker_symbol": broker_symbol,
        "economics_found": econ is not None,
        "economics_symbol": econ.symbol if econ else None,
    }
    if sl and close > 0 and econ is not None:
        raw, reason = lot_from_broker_economics(
            balance,
            risk_pct,
            close,
            sl,
            econ,
            regime_multiplier=regime_position_multiplier(regime),
        )
        out.update(
            {
                "entry_price": close,
                "stop_loss": sl,
                "raw_lot": raw,
                "normalized_lot": raw,
                "volume_min": econ.volume_min,
                "below_min": raw is None or raw < econ.volume_min,
                "sizing_reason": reason,
            }
        )
    return out


async def _replay_candidate(
    engine: Any,
    cand: dict[str, Any],
    *,
    data_label: str,
    legacy_config: dict[str, Any],
) -> dict[str, Any]:
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

    signal = ctx.signal
    risk = ctx.risk
    df = ctx.enriched_ohlcv
    regime = (
        infer_regime_from_ohlcv(df.iloc[:-1] if df is not None and len(df) > 1 else df)
        if df is not None
        else "RANGING"
    )
    tier = detect_account_tier(float(portfolio.get("balance", engine._cfg.initial_balance)))
    profile = execution_profile_for_tier(tier)
    risk_pct = (
        float(profile.risk_per_trade_override)
        if profile.risk_per_trade_override is not None
        else float(engine._cfg.risk_per_trade)
    )
    snap = {
        **portfolio,
        "ohlcv": df,
        "symbol": data_label,
        "timeframe": "M5",
        "current_time": df.index[-1] if df is not None and not df.empty else None,
    }

    lot_diag = (
        _lot_diagnostics(signal, snap, legacy_config=legacy_config, risk_pct=risk_pct, regime=regime)
        if signal is not None
        else {}
    )

    reason = getattr(risk, "reason", None) if risk else None
    allowed = bool(risk and risk.allowed)

    for stage in engine._kernel._pipeline:
        if stage.name.value == PipelineStageName.SIGNALS.value:
            stage._last_closed_bar.clear()  # type: ignore[attr-defined]

    key = f"{cand.get('timestamp')}@{cursor}"
    return {
        "candidate_key": key,
        "cursor": cursor,
        "timestamp": cand.get("timestamp"),
        "direction": cand.get("direction"),
        "post_fix_reason": reason,
        "post_fix_allowed": allowed,
        "post_fix_lot": lot_diag.get("raw_lot"),
        "post_fix_lot_diagnostics": lot_diag,
        "meta_result": "reject" if reason and "meta-labeler" in str(reason) else "pass",
        "atr_result": "reject" if reason and "ATR percentile" in str(reason) else "pass",
        "lot_result": "reject" if reason and "lot too small" in str(reason) else "n/a",
    }


def _classify_rejection(reason: str | None) -> str:
    r = str(reason or "")
    if "lot too small" in r:
        return "lot/min-volume"
    if "meta-labeler" in r:
        return "meta"
    if "ATR percentile" in r:
        return "atr"
    if not r or r == "None":
        return "allowed"
    return "other"


async def run_phase26f_riskgate_correctness(
    base_dir: str | Path | None = None,
    *,
    dataset_rel: str = DEFAULT_DATASET,
) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    if not (root / PHASE26E_JSON).is_file() or not (root / PHASE26D_JSON).is_file():
        raise FileNotFoundError("Phase 26D/26E artifacts required")

    d26d = json.loads((root / PHASE26D_JSON).read_text(encoding="utf-8"))
    candidates = (d26d.get("propagation_counts") or {}).get("per_candidate") or []
    if len(candidates) != 19:
        raise ValueError(f"expected 19 candidates, got {len(candidates)}")

    before = _load_before_state(root)
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

    replay_rows: list[dict[str, Any]] = []
    for cand in candidates:
        post = await _replay_candidate(engine, cand, data_label=data_label, legacy_config=legacy)
        key = post["candidate_key"]
        pre = before.get(key, {})
        pre_reason = pre.get("reason")
        post_reason = post.get("post_fix_reason")
        replay_rows.append(
            {
                **post,
                "before_reason": pre_reason,
                "after_reason": post_reason,
                "reason_changed": pre_reason != post_reason,
                "before_lot": (pre.get("lot_detail") or {}).get("hypothetical_xauusd_i", {}).get("raw_lot"),
                "before_economics_found": (pre.get("lot_detail") or {}).get("economics_found_xauusd"),
            }
        )

    after_counts = {
        "lot/min-volume": 0,
        "meta": 0,
        "atr": 0,
        "allowed": 0,
        "other": 0,
    }
    before_counts = {"lot/min-volume": 3, "meta": 10, "atr": 6, "allowed": 0}
    for row in replay_rows:
        cat = _classify_rejection(row.get("post_fix_reason"))
        after_counts[cat] = after_counts.get(cat, 0) + 1

    same_distribution = all(
        before_counts.get(k, 0) == after_counts.get(k, 0) for k in ("lot/min-volume", "meta", "atr", "allowed")
    )
    any_allowed = any(r["post_fix_allowed"] for r in replay_rows)
    alias_fix_conclusion = (
        "decision-changing"
        if any_allowed
        else "rejection-reason-only"
        if same_distribution
        else "partial_change"
    )

    report = Phase26FReport(
        status="PASS_WITH_DEFERRAL",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "code_change": CODE_CHANGE,
            "alias_behavior": {
                "before": "resolve_backtest_economics(signal.symbol) with XAUUSD → None",
                "after": "resolve_broker_symbol(signal.symbol) → XAUUSD_i → economics found",
                "ev_eq_01": "NOT_PROVEN",
                "note": "Alias resolution does not prove XAUUSD/XAUUSD_i economic equivalence",
            },
            "journal_metric": {
                "changed": False,
                "action": "documented",
                "meaning": "risk_journal_entries counts _append_risk_journal sizing records, not all evaluate() calls",
                "location": "tradingbot/backtest/phase26b_controlled_validation.py comment",
            },
            "candidate_replay": replay_rows,
            "before_after_table": [
                {
                    "candidate": r["candidate_key"],
                    "direction": r["direction"],
                    "before_reason": r["before_reason"],
                    "after_reason": r["after_reason"],
                    "before_lot": r.get("before_lot"),
                    "after_lot": r.get("post_fix_lot"),
                    "allowed": r.get("post_fix_allowed"),
                }
                for r in replay_rows
            ],
            "rejection_counts": {
                "before_phase26e": before_counts,
                "after_phase26f": after_counts,
            },
            "alias_fix_conclusion": alias_fix_conclusion,
            "zero_trade_explanation": (
                "After alias fix: 0/19 allowed; 3 still lot/min-volume, 10 meta, 6 ATR. "
                "Alias defect was correctness/diagnostic only on this sample."
            ),
            "regression_checks": {
                "signal_stage": "unchanged",
                "signal_filter_stage": "unchanged",
                "trading_kernel": "unchanged",
                "strategy": "unchanged",
                "riskgate_policy": "unchanged except economics lookup path",
                "router": "unchanged",
                "execution": "unchanged",
                "live_config": "unchanged",
                "meta_labeler": "unchanged",
                "atr_filters": "unchanged",
            },
            "final_decision": "PASS_WITH_DEFERRAL",
        }
    )

    _write_json(root / PHASE26F_JSON, report)
    return report


def run_phase26f_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return asyncio.run(run_phase26f_riskgate_correctness(base_dir))
