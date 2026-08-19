from enum import Enum, auto


class TradingMode(Enum):
    LIVE = auto()
    BACKTEST = auto()
    PAPER = auto()


class SignalDirection(Enum):
    BUY = 1
    SELL = -1
    HOLD = 0


class PipelineStageName(Enum):
    """مراحل استاندارد پردازش در هسته مرکزی."""

    DATA = "data"
    INDICATORS = "indicators"
    SIGNALS = "signals"
    SIGNAL_FILTER = "signal_filter"
    RISK = "risk"
    EXECUTION = "execution"
    POSITIONS = "positions"


class KernelState(Enum):
    STOPPED = auto()
    RUNNING = auto()
    PAUSED = auto()
    EMERGENCY_STOP = auto()
