"""مرحله ۴: ریسک — معادل RiskManager.can_trade."""

from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.models import CycleContext
from tradingbot.pipeline.base import PipelineStage
from tradingbot.ports.risk import IRiskGate


class RiskStage(PipelineStage):
    name = PipelineStageName.RISK

    def __init__(self, risk: IRiskGate) -> None:
        self._risk = risk

    async def run(self, ctx: CycleContext, portfolio_snapshot: dict) -> bool:
        if ctx.signal is None:
            ctx.add_error("RiskStage: signal missing")
            return False
        current_time = None
        if ctx.enriched_ohlcv is not None and not ctx.enriched_ohlcv.empty:
            current_time = ctx.enriched_ohlcv.index[-1]
        snap = {
            **portfolio_snapshot,
            "ohlcv": ctx.enriched_ohlcv,
            "symbol": ctx.market.symbol,
            "timeframe": ctx.market.timeframe,
            "current_time": current_time,
            "htf_bias": portfolio_snapshot.get("htf_bias_map", {}).get(
                f"{ctx.market.symbol}:{ctx.market.timeframe}",
                portfolio_snapshot.get("htf_bias_map", {}).get(
                    ctx.market.symbol, portfolio_snapshot.get("htf_bias", 0)
                ),
            ),
        }
        decision = self._risk.evaluate(ctx.signal, snap)
        ctx.risk = decision
        if not decision.allowed:
            from tradingbot.services.rejection_events import (
                log_rejection_event,
                map_risk_reason_to_stage,
            )

            stage = map_risk_reason_to_stage(decision.reason)
            log_rejection_event(
                stage=stage,
                direction=ctx.signal.direction.name,
                reason=decision.reason,
                context={"symbol": ctx.market.symbol, "timeframe": ctx.market.timeframe},
                symbol=ctx.market.symbol,
            )
            try:
                from tradingbot.services.engine_telemetry import get_engine_telemetry, resolve_engine_from_signal

                get_engine_telemetry().record_rejection(
                    resolve_engine_from_signal(ctx.signal),
                    reason=decision.reason,
                    symbol=ctx.market.symbol,
                    timeframe=ctx.market.timeframe,
                    direction=ctx.signal.direction.name,
                    stage=stage,
                )
            except Exception:
                pass
            ctx.add_error(f"Risk blocked: {decision.reason}")
            return False
        if decision.adjusted_lot is not None and ctx.signal.lot_size is None:
            ctx.signal.lot_size = decision.adjusted_lot
        return True
