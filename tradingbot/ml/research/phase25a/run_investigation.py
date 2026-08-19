"""Phase 25A — Paper Trading vs Research Replay consistency audit (READ ONLY)."""

from __future__ import annotations

import asyncio
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

PHASE_DIR = Path(__file__).resolve().parent

LOOKBACK_BARS = 300
MIN_KERNEL_BARS = 250
WARMUP_REPLAY_15B = 120


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    if hasattr(obj, "to_dict"):
        try:
            return _json_safe(obj.to_dict())
        except Exception:
            pass
    if hasattr(obj, "name"):
        return str(getattr(obj, "name"))
    return obj


def _research_records(
    *,
    base_dir: str | None,
    symbol: str,
    timeframe: str,
    tail_only: int,
    stride: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from tradingbot.ml.research.phase24a.live_shadow_validator import collect_production_decisions

    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"
    records, meta = collect_production_decisions(
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        tail_only=tail_only,
        stride=stride,
        use_mt5=False,
    )
    return records, meta


def _paper_path_records(
    *,
    base_dir: str | None,
    symbol: str,
    timeframe: str,
    tail_only: int,
    stride: int,
    legacy_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Simulate production paper kernel path on frozen candles (no MT5 orders)."""
    from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
    from tradingbot.adapters.risk_gate import create_risk_gate
    from tradingbot.domain.enums import SignalDirection
    from tradingbot.domain.models import MarketKey
    from tradingbot.domain.ohlcv import exclude_forming_bar
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.integration.factory import build_strategy_registry
    from tradingbot.ml.integration.pipeline_cache import PipelineCache
    from tradingbot.ml.integration.replay_market_data import ReplayMarketDataAdapter
    from tradingbot.ml.research.regime_router.phase99_feature_validation import normalize_candles_for_builder
    from tradingbot.services.execution_mode import is_paper

    os.environ["TRADINGBOT_PAPER"] = "1"
    os.environ.pop("TRADINGBOT_DRY_RUN", None)
    os.environ["USE_ML_KERNEL"] = "1"
    os.environ["ALLOW_LEGACY_FALLBACK"] = "0"

    candles_raw = CandleStore(base_dir).load(symbol, timeframe)
    if candles_raw is None or candles_raw.empty:
        return [], {"error": "candles_unavailable"}

    window = normalize_candles_for_builder(candles_raw).tail(tail_only).copy()
    market = MarketKey(symbol, timeframe)
    PipelineCache.reset()
    registry = build_strategy_registry(legacy_config, base_dir=base_dir, symbol=symbol)
    indicators = TechnicalIndicatorEngine(legacy_config)
    risk_gate = create_risk_gate(legacy_config)

    warmup = max(MIN_KERNEL_BARS, LOOKBACK_BARS // 2)
    indices = list(range(warmup, len(window), max(1, stride)))
    records: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "mode": "paper_kernel_simulation",
        "paper_env": is_paper(),
        "lookback_bars": LOOKBACK_BARS,
        "bars_evaluated": 0,
    }

    last_closed_bar: object | None = None

    for bar_index in indices:
        meta["bars_evaluated"] += 1
        replay = ReplayMarketDataAdapter(window)
        replay.set_bar_index(bar_index)
        raw = replay.get_ohlcv(market, bars=LOOKBACK_BARS)
        if raw is None or raw.empty:
            continue

        if hasattr(indicators, "enrich_for_market"):
            enriched = indicators.enrich_for_market(raw, timeframe, symbol)
        else:
            enriched = indicators.enrich(raw)
        closed = exclude_forming_bar(enriched)
        if closed is None or closed.empty:
            continue

        ts = pd.to_datetime(closed.index[-1], utc=True)
        dedup_skipped = last_closed_bar == closed.index[-1]
        if not dedup_skipped:
            last_closed_bar = closed.index[-1]

        signal = None
        if not dedup_skipped:
            signal = registry.generate_signal(market, closed)

        direction = "HOLD"
        confidence = 0.0
        sl = tp = lot = None
        regime = engine = None
        risk_allowed = None
        risk_reason = ""
        filter_diag: dict[str, Any] = {}
        exec_message = ""
        unified_checksum = None
        probability = None

        if signal is not None:
            direction = signal.direction.name
            confidence = float(signal.confidence)
            sl = signal.stop_loss
            tp = signal.take_profit
            lot = signal.lot_size
            meta_sig = signal.metadata or {}
            regime = meta_sig.get("regime")
            engine = meta_sig.get("engine_name")
            unified_checksum = meta_sig.get("unified_checksum")
            probability = meta_sig.get("raw_probability")

        risk_decision = None
        if signal is not None and signal.direction not in (SignalDirection.HOLD,):
            portfolio = {
                "balance": 10_000.0,
                "equity": 10_000.0,
                "open_positions": [],
                "correlation_data": {},
                "ohlcv": closed,
                "symbol": symbol,
                "timeframe": timeframe,
                "current_time": closed.index[-1],
                "htf_bias": 0,
            }
            with _mock_mt5_gates():
                risk_decision = risk_gate.evaluate(signal, portfolio)
            risk_allowed = risk_decision.allowed
            risk_reason = risk_decision.reason
            if risk_decision.adjusted_lot is not None:
                lot = risk_decision.adjusted_lot

        if signal is not None and risk_allowed and signal.direction not in (SignalDirection.HOLD,):
            from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter

            adapter = Mt5ExecutionAdapter(legacy_config)
            with _mock_mt5_gates():
                exec_result = adapter.execute(signal, float(lot or 0.01))
            exec_message = exec_result.message

        adapter_inner = getattr(registry, "_adapter", None)
        if adapter_inner is not None and getattr(adapter_inner, "last_filter_diagnostics", None):
            filter_diag = adapter_inner.last_filter_diagnostics.to_dict()

        records.append(
            _json_safe(
                {
                    "timestamp": ts.isoformat(),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "regime": regime,
                    "feature_vector_checksum": unified_checksum,
                    "probability": probability,
                    "confidence": confidence,
                    "decision": direction,
                    "risk_allowed": risk_allowed,
                    "risk_reason": risk_reason,
                    "sl": sl,
                    "tp": tp,
                    "volume": lot,
                    "filter_diagnostics": filter_diag,
                    "execution_message": exec_message,
                    "dedup_skipped": dedup_skipped,
                    "registry_source": getattr(registry, "last_source", None),
                    "reason": risk_reason or exec_message or "",
                }
            )
        )

    return records, meta


class _mock_mt5_gates:
    """Stub MT5 reads so RiskGate live gates run deterministically offline."""

    def __enter__(self):
        from unittest import mock

        self._patches = [
            mock.patch(
                "tradingbot.adapters.risk_gate.RiskGate._sync_mt5_account",
                return_value=None,
            ),
            mock.patch(
                "tradingbot.services.live_risk_tracker.LiveRiskTracker.sync_from_mt5",
                return_value=None,
            ),
            mock.patch(
                "tradingbot.adapters.risk_gate.RiskGate._live_spread_pips",
                return_value=1.0,
            ),
            mock.patch(
                "tradingbot.adapters.mt5_health.check_autotrading_ready",
                return_value=(True, "mock ok"),
            ),
            mock.patch(
                "tradingbot.adapters.mt5_execution.ensure_mt5_connected",
                return_value=True,
            ),
            mock.patch(
                "tradingbot.adapters.mt5_execution._current_price",
                return_value=2000.0,
            ),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *args):
        for p in self._patches:
            p.stop()


def _replay_15b_records(
    *,
    base_dir: str | None,
    symbol: str,
    timeframe: str,
    tail_only: int,
    stride: int,
) -> list[dict[str, Any]]:
    from tradingbot.domain.models import MarketKey
    from tradingbot.ml.data.stores.candle_store import CandleStore
    from tradingbot.ml.integration.factory import build_kernel_adapter, build_ml_kernel_stack
    from tradingbot.ml.integration.ml_kernel_registry import MLKernelRegistry
    from tradingbot.ml.integration.pipeline_cache import PipelineCache

    os.environ["USE_ML_KERNEL"] = "1"
    PipelineCache.reset()
    stack = build_ml_kernel_stack(base_dir=base_dir, symbol=symbol)
    adapter = build_kernel_adapter(base_dir=base_dir, symbol=symbol, stack=stack)
    registry = MLKernelRegistry({"BASE_DIR": base_dir or "."}, adapter=adapter, base_dir=base_dir)
    candles = CandleStore(base_dir).load(symbol, timeframe)
    if candles is None or candles.empty:
        return []
    window = candles.tail(tail_only)
    market = MarketKey(symbol, timeframe)
    out: list[dict[str, Any]] = []
    for i in range(WARMUP_REPLAY_15B, len(window), stride):
        slice_df = window.iloc[max(0, i - WARMUP_REPLAY_15B) : i + 1]
        ts = pd.to_datetime(slice_df.index[-1], utc=True)
        sig = registry.generate_signal(market, slice_df)
        direction = "HOLD" if sig is None else sig.direction.name
        out.append(
            {
                "timestamp": ts.isoformat(),
                "decision": direction,
                "confidence": float(sig.confidence) if sig else 0.0,
                "lookback": len(slice_df),
            }
        )
    return out


def _norm_ts_key(ts: Any) -> str:
    return pd.to_datetime(ts, utc=True).strftime("%Y-%m-%dT%H:%M:%S%z").replace("+0000", "+00:00")
def _compare_by_timestamp(
    research: list[dict[str, Any]],
    paper: list[dict[str, Any]],
) -> dict[str, Any]:
    rmap = {_norm_ts_key(r["timestamp"]): r for r in research}
    pmap = {_norm_ts_key(p["timestamp"]): p for p in paper}
    keys = sorted(set(rmap) & set(pmap))
    positional_mismatches: list[dict[str, Any]] = []
    if not keys and len(research) == len(paper) and len(research) > 0:
        for i, (r, p) in enumerate(zip(research, paper)):
            rv = r.get("final_signal", r.get("decision"))
            pv = p.get("decision")
            if rv != pv:
                positional_mismatches.append(
                    {
                        "index": i,
                        "research_timestamp": r.get("timestamp"),
                        "paper_timestamp": p.get("timestamp"),
                        "research_value": rv,
                        "paper_value": pv,
                        "research_module": "phase24a.collect_production_decisions",
                        "paper_module": "paper_kernel_simulation",
                    }
                )
    mismatches: list[dict[str, Any]] = []
    fields = [
        ("decision", "final_signal", "decision"),
        ("confidence", "confidence", "confidence"),
        ("regime", "regime", "regime"),
    ]
    for ts in keys:
        r = rmap[ts]
        p = pmap[ts]
        for label, rkey, pkey in fields:
            rv = r.get(rkey)
            pv = p.get(pkey)
            if rv != pv and not (rv in (None, "") and pv in (None, "")):
                mismatches.append(
                    {
                        "timestamp": ts,
                        "field": label,
                        "research_value": rv,
                        "paper_value": pv,
                        "research_module": "phase24a.collect_production_decisions",
                        "paper_module": "paper_kernel_simulation",
                    }
                )
    if positional_mismatches:
        mismatches.extend(positional_mismatches)
    return {
        "joined_bars": len(keys) if keys else (len(research) if len(research) == len(paper) else 0),
        "timestamp_join_bars": len(keys),
        "positional_compare_bars": len(research) if not keys and len(research) == len(paper) else 0,
        "research_only": len(set(rmap) - set(pmap)),
        "paper_only": len(set(pmap) - set(rmap)),
        "mismatches": mismatches[:500],
        "mismatch_count": len(mismatches),
        "decision_match_rate": round(
            1.0
            - len([m for m in mismatches if m.get("field") == "decision" or "research_value" in m])
            / max(len(keys) if keys else len(research), 1),
            6,
        ),
    }


def _structural_divergences() -> list[dict[str, Any]]:
    return [
        {
            "id": "DIV-001",
            "area": "pipeline_depth",
            "research": "phase24a collect_production_decisions stops before RiskGate/ExecutionStage",
            "paper": "LiveRunner --paper runs RiskStage + ExecutionStage",
            "module": "ml/research/phase24a/live_shadow_validator.py vs application/live_runner.py",
            "line": "97 vs 124",
            "impact": "Research final_signal may pass while paper RiskGate blocks",
        },
        {
            "id": "DIV-002",
            "area": "ohlcv_window",
            "research": "LOOKBACK_BARS=300 chunk (phase24a:218)",
            "paper": "DataStage fetch_bars=300 via ReplayMarketDataAdapter",
            "module": "pipeline/data_stage.py:20",
            "line": "20",
            "impact": "Aligned when both use 300-bar window",
        },
        {
            "id": "DIV-003",
            "area": "ohlcv_window_replay_15b",
            "research": "run_kernel_replay warmup=120 slice",
            "paper": "300-bar fetch",
            "module": "ml/integration/replay_validator.py:100",
            "line": "100",
            "impact": "Phase15B replay differs from paper — not canonical research path",
        },
        {
            "id": "DIV-004",
            "area": "indicator_enrichment",
            "research": "Raw/normalized candles to KernelAdapter",
            "paper": "IndicatorStage enrich_for_market before SignalStage",
            "module": "pipeline/indicator_stage.py:20-25",
            "line": "20",
            "impact": "SL/TP via compute_sl_tp may differ; unified frame uses normalized candles inside adapter",
        },
        {
            "id": "DIV-005",
            "area": "bar_dedup",
            "research": "No SignalStage dedup",
            "paper": "SignalStage._last_closed_bar in-memory dedup",
            "module": "pipeline/signal_stage.py:29-32",
            "line": "29",
            "impact": "Duplicate evaluation on same bar if cycle re-enters",
        },
        {
            "id": "DIV-006",
            "area": "risk_gates",
            "research": "AdaptiveRisk inside quality.evaluate only",
            "paper": "Legacy RiskGate live gates + meta-labeler + LiveRiskTracker",
            "module": "adapters/risk_gate.py:109-207",
            "line": "109",
            "impact": "Paper may HOLD/block trades research approves at ML layer",
        },
        {
            "id": "DIV-007",
            "area": "record_live_entry",
            "research": "N/A",
            "paper": "Skipped in paper mode — cooldown counters not updated",
            "module": "adapters/mt5_execution.py:68-86",
            "line": "68",
            "impact": "Risk continuity differs across paper sessions",
        },
        {
            "id": "DIV-008",
            "area": "market_data_live",
            "research": "CandleStore frozen history",
            "paper": "Mt5MarketDataAdapter + ParquetCache live ticks",
            "module": "adapters/mt5_market_data.py:142",
            "line": "142",
            "impact": "Live paper bar timestamps/prices may differ from replay store",
        },
        {
            "id": "DIV-009",
            "area": "alternate_paper_engines",
            "research": "KernelAdapter production stack",
            "paper": "KernelPaperEngine uses CompositeStrategyRegistry/MLShadowStrategy",
            "module": "ml/paper/paper_engine.py:78",
            "line": "78",
            "impact": "NOT comparable to production --paper without USE_ML_KERNEL=1",
        },
        {
            "id": "DIV-010",
            "area": "forming_bar_alignment",
            "research": "collect_production_decisions timestamps norm_candles.index[bar_index]",
            "paper": "SignalStage exclude_forming_bar drops last row — decision on prior closed bar",
            "module": "domain/ohlcv.py:61-69 vs pipeline/signal_stage.py:24",
            "line": "69",
            "impact": "Paper decisions align to T-1 closed bar vs research bar_index (5min lag on M5)",
        },
    ]


def run_phase25a(
    *,
    base_dir: str | None = None,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    tail_only: int = 400,
    stride: int = 5,
) -> dict[str, Any]:
    from tradingbot.adapters.legacy_loader import load_legacy_config

    ts = datetime.now(timezone.utc).isoformat()
    legacy_config = load_legacy_config()
    if base_dir:
        legacy_config = {**legacy_config, "BASE_DIR": base_dir}

    research, research_meta = _research_records(
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        tail_only=tail_only,
        stride=stride,
    )
    paper, paper_meta = _paper_path_records(
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        tail_only=tail_only,
        stride=stride,
        legacy_config=legacy_config,
    )
    replay_15b = _replay_15b_records(
        base_dir=base_dir,
        symbol=symbol,
        timeframe=timeframe,
        tail_only=tail_only,
        stride=stride,
    )

    parity = _compare_by_timestamp(research, paper)
    structural = _structural_divergences()

    # Phase15B vs research canonical
    rmap = {_norm_ts_key(r["timestamp"]): r.get("final_signal", r.get("decision")) for r in research}
    bmap = {_norm_ts_key(r["timestamp"]): r.get("decision") for r in replay_15b}
    keys_15b = sorted(set(rmap) & set(bmap))
    mismatch_15b = sum(1 for k in keys_15b if rmap[k] != bmap[k])

    risk_diffs = [
        p for p in paper if p.get("decision") in ("BUY", "SELL") and p.get("risk_allowed") is False
    ]

    runtime_identical = (
        parity["mismatch_count"] == 0
        and parity["joined_bars"] > 0
        and len(research) > 0
    )
    structural_blockers = len(structural) > 0
    verdict = "PAPER_IDENTICAL_TO_RESEARCH" if runtime_identical and not structural_blockers else "PAPER_DIFFERS_FROM_RESEARCH"

    # Structural paths always differ on risk/execution depth even if ML signals match
    if structural_blockers:
        verdict = "PAPER_DIFFERS_FROM_RESEARCH"

    root_causes = []
    if parity["mismatch_count"] > 0 or parity.get("positional_compare_bars", 0) > 0 and parity["mismatch_count"] > 0:
        root_causes.append(
            {
                "id": "RC-RUNTIME",
                "cause": "ML decision field mismatch",
                "evidence": f"mismatch_count={parity['mismatch_count']} positional={parity.get('positional_compare_bars')}",
                "first_mismatches": parity["mismatches"][:10],
            }
        )
    if parity.get("timestamp_join_bars", 0) == 0 and parity.get("positional_compare_bars", 0) > 0:
        root_causes.append(
            {
                "id": "RC-FORMING-BAR",
                "cause": "Timestamp join failed — paper exclude_forming_bar shifts bar by one",
                "evidence": "research vs paper timestamps offset ~5min on M5",
                "module": "domain/ohlcv.py:69",
            }
        )
    if mismatch_15b > 0:
        root_causes.append(
            {
                "id": "RC-LOOKBACK",
                "cause": "Phase15B replay uses 120-bar window vs 300-bar production path",
                "evidence": f"15b_mismatches={mismatch_15b} joined={len(keys_15b)}",
                "module": "ml/integration/replay_validator.py:100",
            }
        )
    if risk_diffs:
        root_causes.append(
            {
                "id": "RC-RISKGATE",
                "cause": "Paper RiskGate blocks actionable ML signals",
                "evidence": f"blocked_count={len(risk_diffs)}",
                "module": "adapters/risk_gate.py:109",
            }
        )
    for div in structural:
        root_causes.append({"id": div["id"], "cause": div["area"], "evidence": div["impact"], "module": div["module"]})

    outputs = {
        "paper_vs_research.json": {
            "phase": "25A",
            "generated_utc": ts,
            "verdict": verdict,
            "symbol": symbol,
            "timeframe": timeframe,
            "tail_only": tail_only,
            "stride": stride,
            "research_meta": research_meta,
            "paper_meta": paper_meta,
            "parity_summary": parity,
            "research_bars": len(research),
            "paper_bars": len(paper),
            "replay_15b_mismatch_on_joined": mismatch_15b,
        },
        "decision_parity.json": {
            "joined_bars": parity["joined_bars"],
            "decision_match_rate": parity["decision_match_rate"],
            "mismatch_count": parity["mismatch_count"],
            "mismatches_sample": parity["mismatches"][:50],
        },
        "feature_parity.json": {
            "note": "Feature vectors compared via unified_checksum in paper metadata vs research feature_vector keys",
            "research_has_feature_vector": sum(1 for r in research if r.get("feature_vector")),
            "paper_has_checksum": sum(1 for p in paper if p.get("feature_vector_checksum")),
        },
        "probability_parity.json": {
            "fields_compared": ["raw_probability", "buy_probability", "confidence"],
            "research_sample": [
                {
                    "timestamp": r.get("timestamp"),
                    "raw_probability": r.get("raw_probability"),
                    "confidence": r.get("confidence"),
                }
                for r in research[:5]
            ],
            "paper_sample": [
                {
                    "timestamp": p.get("timestamp"),
                    "probability": p.get("probability"),
                    "confidence": p.get("confidence"),
                }
                for p in paper[:5]
            ],
        },
        "risk_parity.json": {
            "research_includes_legacy_riskgate": False,
            "paper_riskgate_blocks": len(risk_diffs),
            "blocked_sample": risk_diffs[:20],
            "ml_risk_in_research": "risk_result in collect_production_decisions record",
        },
        "execution_parity.json": {
            "research_executes": False,
            "paper_execution": "Mt5ExecutionAdapter paper branch — simulated fill, no order_send",
            "paper_exec_samples": [
                {"timestamp": p.get("timestamp"), "message": p.get("execution_message")}
                for p in paper
                if p.get("execution_message")
            ][:20],
        },
        "difference_report.json": {
            "runtime_ml_mismatches": parity["mismatches"],
            "structural_divergences": structural,
            "replay_15b_vs_24a": {"joined": len(keys_15b), "decision_mismatches": mismatch_15b},
        },
        "root_cause.json": {"root_causes": root_causes},
        "phase25a_final_report.json": {
            "phase": "25A",
            "generated_utc": ts,
            "verdict": verdict,
            "audit_mode": "READ_ONLY",
            "canonical_research_path": "phase24a.collect_production_decisions",
            "canonical_paper_path": "LiveRunner --paper USE_ML_KERNEL=1 (simulated on frozen candles)",
            "runtime_decision_match_rate": parity["decision_match_rate"],
            "structural_divergence_count": len(structural),
            "recommendation": (
                "Align research replay to include RiskGate+paper execution on ReplayMarketDataAdapter "
                "before claiming end-to-end parity"
                if verdict == "PAPER_DIFFERS_FROM_RESEARCH"
                else "Proceed to extended live paper shadow compare"
            ),
        },
    }

    PHASE_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (PHASE_DIR / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return outputs["phase25a_final_report.json"]


def main() -> int:
    report = run_phase25a()
    print(json.dumps(report, indent=2))
    return 0 if report.get("verdict") else 1


if __name__ == "__main__":
    raise SystemExit(main())
