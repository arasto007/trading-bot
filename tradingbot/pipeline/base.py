from abc import ABC, abstractmethod

from tradingbot.domain.enums import PipelineStageName
from tradingbot.domain.models import CycleContext


class PipelineStage(ABC):
    """پایه هر مرحله پردازش — یک مسئولیت، یک ورودی/خروجی روی CycleContext."""

    name: PipelineStageName

    @abstractmethod
    async def run(self, ctx: CycleContext, portfolio_snapshot: dict) -> bool:
        """
        اجرای مرحله. True = ادامه pipeline؛ False = توقف این چرخه برای این market.
        """
        ...
