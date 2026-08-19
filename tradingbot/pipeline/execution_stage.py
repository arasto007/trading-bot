"""مرحله ۵: اجرا — معادل OrderManager.execute_order + place_order."""

from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.models import CycleContext
from tradingbot.pipeline.base import PipelineStage
from tradingbot.ports.execution import IOrderExecutor


class ExecutionStage(PipelineStage):
    name = PipelineStageName.EXECUTION

    def __init__(self, executor: IOrderExecutor, default_lot: float = 0.01) -> None:
        self._executor = executor
        self._default_lot = default_lot

    async def run(self, ctx: CycleContext, portfolio_snapshot: dict) -> bool:
        if ctx.signal is None:
            ctx.add_error("ExecutionStage: signal missing")
            return False
        lot = ctx.signal.lot_size or self._default_lot
        ctx.execution = self._executor.execute(ctx.signal, lot)
        return ctx.execution.success
