"""Phase 22F — pipeline trace collector (research hooks, no production edits)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BlockedSignal:
    timeframe: str
    timestamp: str
    direction: str
    stage: str
    reason: str
    regime: str
    engine: str
    bar_index: int = 0
    symbol: str = "XAUUSD"
    closed_bar_time: str = ""
    feature_checksum: str = ""
    confidence: float | None = None
    quality_score: float | None = None
    adx: float | None = None
    atr: float | None = None
    rsi: float | None = None
    spread: float | None = None
    htf_bias: int | None = None
    sl: float | None = None
    tp: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "direction": self.direction,
            "stage": self.stage,
            "reason": self.reason,
            "regime": self.regime,
            "engine": self.engine,
            "bar_index": self.bar_index,
            "symbol": self.symbol,
            "closed_bar_time": self.closed_bar_time,
            "feature_checksum": self.feature_checksum,
            "confidence": self.confidence,
            "quality_score": self.quality_score,
            "adx": self.adx,
            "atr": self.atr,
            "rsi": self.rsi,
            "spread": self.spread,
            "htf_bias": self.htf_bias,
            "sl": self.sl,
            "tp": self.tp,
        }


@dataclass
class TraceCollector:
    timeframe: str = "M5"
    bars: int = 0
    model_pass: int = 0
    calibration_pass: int = 0
    quality_pass: int = 0
    rsi_pass: int = 0
    adx_pass: int = 0
    meta_pass: int = 0
    riskgate_reached: int = 0
    riskgate_pass: int = 0
    executed: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    hold_signals: int = 0
    regime_counts: Counter = field(default_factory=Counter)
    engine_counts: Counter = field(default_factory=Counter)
    block_reasons: Counter = field(default_factory=Counter)
    stage_blocks: Counter = field(default_factory=Counter)
    blocked_events: list[BlockedSignal] = field(default_factory=list)
    riskgate_block_reasons: Counter = field(default_factory=Counter)
    meta_rejected: int = 0
    meta_approved: int = 0
    htf_blocked: int = 0
    session_blocked: int = 0
    forensic_events: list[dict[str, Any]] = field(default_factory=list)

    def snapshot_funnel(self) -> dict[str, Any]:
        b = max(self.bars, 1)
        stages = [
            ("bars", self.bars),
            ("model_pass", self.model_pass),
            ("calibration_pass", self.calibration_pass),
            ("quality_pass", self.quality_pass),
            ("rsi_pass", self.rsi_pass),
            ("adx_pass", self.adx_pass),
            ("meta_pass", self.meta_pass),
            ("riskgate_reached", self.riskgate_reached),
            ("riskgate_pass", self.riskgate_pass),
            ("executed", self.executed),
        ]
        funnel = []
        prev = self.bars
        for name, count in stages[1:]:
            lost = max(0, prev - count)
            funnel.append({
                "stage": name,
                "count": count,
                "pct_of_bars": round(count / b * 100, 3),
                "lost_from_prev": lost,
                "lost_pct_from_prev": round(lost / max(prev, 1) * 100, 3),
            })
            prev = count
        return {
            "timeframe": self.timeframe,
            "bars": self.bars,
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "hold_signals": self.hold_signals,
            "buy_pct": round(self.buy_signals / max(self.buy_signals + self.sell_signals + self.hold_signals, 1) * 100, 2),
            "sell_pct": round(self.sell_signals / max(self.buy_signals + self.sell_signals + self.hold_signals, 1) * 100, 2),
            "hold_pct": round(self.hold_signals / max(self.buy_signals + self.sell_signals + self.hold_signals, 1) * 100, 2),
            "funnel": funnel,
            "regime_distribution": dict(self.regime_counts),
            "engine_distribution": dict(self.engine_counts),
            "stage_blocks": dict(self.stage_blocks),
            "riskgate_block_reasons": dict(self.riskgate_block_reasons),
        }


_TRACE: TraceCollector | None = None
_PATCHED = False


def get_trace() -> TraceCollector:
    global _TRACE
    if _TRACE is None:
        _TRACE = TraceCollector()
    return _TRACE


def reset_trace(tf: str = "M5") -> TraceCollector:
    global _TRACE
    _TRACE = TraceCollector(timeframe=tf)
    return _TRACE


def install_trace_hooks(trace: TraceCollector | None = None) -> None:
    global _PATCHED
    if _PATCHED:
        return
    tr = trace or get_trace()

    from tradingbot.pipeline import data_stage, signal_stage, risk_stage, execution_stage
    from tradingbot.adapters import risk_gate as rg_mod
    from tradingbot.ml.integration import kernel_adapter as ka_mod
    from tradingbot.ml.phase19c import filters as filt_mod
    from tradingbot.services import meta_labeler as meta_mod
    from tradingbot.domain import live_gates

    orig_data = data_stage.DataStage.run
    orig_sig = signal_stage.SignalStage.run
    orig_risk = risk_stage.RiskStage.run
    orig_exec = execution_stage.ExecutionStage.run
    orig_produce = ka_mod.KernelAdapter.produce_unified_signal
    from tradingbot.backtest import risk as bt_risk
    orig_bt_rg = bt_risk.BacktestRiskGate.evaluate
    orig_apply_filt = filt_mod.apply_profitability_filters
    orig_htf = live_gates.check_htf_alignment
    orig_meta_should = meta_mod.MetaLabeler.should_gate

    from tradingbot.ml.research.phase33d.forensic_context import ForensicContext, get_ctx, row_checksum, set_ctx
    from tradingbot.ml.research.phase33d.schema import make_event

    _cycle = 0

    def _emit_forensic(blocked: BlockedSignal, *, function: str) -> None:
        fctx = get_ctx()
        ev = make_event(
            module=blocked.stage or "unknown",
            function=function,
            reason=blocked.reason,
            symbol=blocked.symbol,
            timeframe=blocked.timeframe,
            timestamp=blocked.timestamp,
            bar_index=blocked.bar_index,
            closed_bar_time=blocked.closed_bar_time,
            current_bar_time=fctx.current_bar_time if fctx else blocked.timestamp,
            feature_checksum=blocked.feature_checksum,
            confidence=blocked.confidence,
            quality_score=blocked.quality_score,
            adx=blocked.adx,
            atr=blocked.atr,
            rsi=blocked.rsi,
            spread=blocked.spread,
            htf_trend=blocked.htf_bias,
            regime=blocked.regime,
            trend=blocked.engine,
            cycle_id=fctx.cycle_id if fctx else 0,
            direction=blocked.direction,
            filter_chain=[blocked.stage],
        )
        tr.forensic_events.append(ev.to_dict())

    def _blocked_from_signal(signal, snapshot: dict, stage: str, reason: str) -> BlockedSignal:
        cursor = int(snapshot.get("cursor", 0))
        ts = snapshot.get("current_time")
        ts_str = str(ts) if ts is not None else ""
        meta = signal.metadata or {}
        feats = meta.get("_entry_features") or {}
        direction = signal.direction.name if hasattr(signal.direction, "name") else str(signal.direction)
        return BlockedSignal(
            signal.timeframe,
            ts_str,
            direction,
            stage,
            reason,
            str(meta.get("_regime", snapshot.get("regime", "UNKNOWN"))),
            signal.strategy_name or "",
            bar_index=cursor,
            symbol=signal.symbol,
            closed_bar_time=ts_str,
            feature_checksum=str(meta.get("unified_checksum", "")),
            confidence=float(signal.confidence) if signal.confidence is not None else None,
            quality_score=float(meta.get("quality")) if meta.get("quality") is not None else None,
            adx=feats.get("adx"),
            atr=feats.get("atr"),
            rsi=feats.get("rsi"),
            spread=feats.get("spread_pips"),
            htf_bias=int(snapshot.get("htf_bias", 0) or 0),
            sl=float(signal.stop_loss or 0) or None,
            tp=float(signal.take_profit or 0) or None,
        )

    async def data_run(self, ctx, portfolio):
        nonlocal _cycle
        tr.bars += 1
        _cycle += 1
        closed_ts = ""
        bar_idx = int(portfolio.get("cursor", 0))
        if ctx.enriched_ohlcv is not None and not ctx.enriched_ohlcv.empty:
            closed_ts = str(ctx.enriched_ohlcv.index[-1])
        set_ctx(
            ForensicContext(
                symbol=ctx.market.symbol,
                timeframe=ctx.market.timeframe,
                bar_index=bar_idx,
                closed_bar_time=closed_ts,
                current_bar_time=str(portfolio.get("current_time", closed_ts)),
                cycle_id=_cycle,
                htf_bias=int(portfolio.get("htf_bias", 0) or 0),
                portfolio_snapshot=dict(portfolio),
            )
        )
        return await orig_data(self, ctx, portfolio)

    async def sig_run(self, ctx, portfolio):
        return await orig_sig(self, ctx, portfolio)

    async def risk_run(self, ctx, portfolio):
        return await orig_risk(self, ctx, portfolio)

    async def exec_run(self, ctx, portfolio):
        ok = await orig_exec(self, ctx, portfolio)
        if ok and ctx.execution and ctx.execution.success:
            tr.executed += 1
        return ok

    def produce(self, market, df):
        unified = orig_produce(self, market, df)
        direction = unified.direction
        regime = unified.regime or "UNKNOWN"
        engine = unified.engine or "NONE"
        tr.regime_counts[regime] += 1
        tr.engine_counts[engine] += 1
        if direction == "HOLD":
            tr.hold_signals += 1
        elif direction == "BUY":
            tr.buy_signals += 1
        elif direction == "SELL":
            tr.sell_signals += 1
        return unified

    def apply_filt(features, settings=None):
        result = orig_apply_filt(features, settings)
        if not result.passed:
            from tradingbot.ml.research.phase33d.forensic_context import get_ctx

            fctx = get_ctx()
            ts_str = fctx.closed_bar_time if fctx else ""
            bar_idx = fctx.bar_index if fctx else 0
            for b in result.blocked_by:
                tr.stage_blocks[b] += 1
                tr.blocked_events.append(
                    BlockedSignal(
                        fctx.timeframe if fctx else "M5",
                        ts_str,
                        "?",
                        b,
                        b,
                        "",
                        "",
                        bar_index=bar_idx,
                        closed_bar_time=ts_str,
                        feature_checksum=row_checksum(features),
                        adx=result.adx,
                        rsi=result.rsi,
                    )
                )
                _emit_forensic(tr.blocked_events[-1], function="apply_profitability_filters")
        return result

    def bt_rg_eval(self, signal, snapshot):
        tr.riskgate_reached += 1
        decision = orig_bt_rg(self, signal, snapshot)
        if decision.allowed:
            tr.riskgate_pass += 1
        else:
            reason = decision.reason.split("(")[0].strip()
            tr.riskgate_block_reasons[reason] += 1
            tr.stage_blocks["riskgate"] += 1
            tr.blocked_events.append(_blocked_from_signal(signal, snapshot, "riskgate", reason))
            _emit_forensic(tr.blocked_events[-1], function="BacktestRiskGate.evaluate")
        return decision

    def rg_eval(self, signal, portfolio_snapshot):
        tf = signal.timeframe
        regime = str((signal.metadata or {}).get("_regime", "RANGING"))
        meta = meta_mod.get_meta_labeler()
        if orig_meta_should(meta, tf, regime):
            decision = orig_rg_eval(self, signal, portfolio_snapshot)
            if not decision.allowed and "meta" in decision.reason.lower():
                tr.meta_rejected += 1
                tr.stage_blocks["meta"] += 1
                tr.blocked_events.append(
                    _blocked_from_signal(signal, portfolio_snapshot, "meta", decision.reason)
                )
                _emit_forensic(tr.blocked_events[-1], function="RiskGate.evaluate")
            elif decision.allowed:
                tr.meta_approved += 1
                tr.meta_pass += 1
            return decision
        tr.meta_pass += 1
        return orig_rg_eval(self, signal, portfolio_snapshot)

    def htf_check(*args, **kwargs):
        ok, reason = orig_htf(*args, **kwargs)
        if not ok:
            tr.htf_blocked += 1
            tr.stage_blocks["htf_confirmation"] += 1
        return ok, reason

    data_stage.DataStage.run = data_run
    signal_stage.SignalStage.run = sig_run
    risk_stage.RiskStage.run = risk_run
    execution_stage.ExecutionStage.run = exec_run
    ka_mod.KernelAdapter.produce_unified_signal = produce
    filt_mod.apply_profitability_filters = apply_filt
    rg_mod.RiskGate.evaluate = rg_eval
    bt_risk.BacktestRiskGate.evaluate = bt_rg_eval
    live_gates.check_htf_alignment = htf_check
    _PATCHED = True
