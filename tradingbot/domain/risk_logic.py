"""
منطق خالص ریسک — اندازه‌ی پوزیشن و گیت معامله (pure functions).

این ماژول نسخه‌ی تمیز و بازنویسی‌شده‌ی *رفتار مؤثر* `engine/risk_manager.py`
است؛ یعنی همان منطقی که در معماری جدید واقعاً استفاده می‌شود:

- `can_trade`: حد ضررهای دوره‌ای (روزانه/هفتگی/ماهانه)، زیان‌های متوالی، اهرم و
  همبستگی. آستانه‌ها دقیقاً مطابق نسخه‌ی قدیم (نسخه‌ی «relaxed») هستند.
- اندازه‌ی لات: `optimal_lot_size` (ریسک ثابت بر حسب pip) × ضریب رژیم بازار.

در نسخه‌ی قدیم، Kelly و volatility-adjustment محاسبه می‌شدند ولی در لات نهایی
**استفاده نمی‌شدند** (فقط لاگ می‌شدند)؛ بنابراین اینجا هم حذف شده‌اند تا کد تمیز
بماند و خروجی **عیناً** یکسان باشد.

توابع کاملاً خالص‌اند (بدون I/O، لاگ، یا وابستگی به engine).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tradingbot.domain.position_logic import contract_size, pip_size

STANDARD_CONTRACT_SIZE = 100_000.0
HARD_MIN_LOT = 0.01
HARD_MAX_LOT = 10.0
DEFAULT_RISK_PER_TRADE = 0.02

# ضریب اندازه‌ی پوزیشن بر اساس رژیم بازار
# (مطابق engine.advanced_regime_detector.get_trading_adjustments)
REGIME_POSITION_MULTIPLIER: dict[str, float] = {
    "STRONG_TREND_UP": 1.2,
    "STRONG_TREND_DOWN": 1.2,
    "RANGING": 1.0,
    "VOLATILE": 0.7,
    "CRISIS": 0.5,
}


def regime_position_multiplier(regime: str | None) -> float:
    """ضریب پوزیشن برای رژیم؛ پیش‌فرض RANGING (=۱.۰)."""
    return REGIME_POSITION_MULTIPLIER.get(regime or "RANGING", 1.0)


def infer_regime_from_ohlcv(df: pd.DataFrame, at_index: int | None = None) -> str:
    """تشخیص ساده رژیم از ATR نسبی و شیب قیمت."""
    if df is None or df.empty or len(df) < 30:
        return "RANGING"
    i = at_index if at_index is not None else len(df) - 1
    window = df.iloc[max(0, i - 50) : i + 1]
    atr_now = atr_from_ohlcv(window)
    price = float(window["close"].iloc[-1])
    if price <= 0:
        return "RANGING"

    hist_atr = []
    for j in range(max(14, len(window) - 20), len(window)):
        hist_atr.append(atr_from_ohlcv(window.iloc[: j + 1]))
    mean_atr = sum(hist_atr) / max(len(hist_atr), 1)
    ratio = atr_now / mean_atr if mean_atr > 0 else 1.0

    if ratio >= 2.0:
        return "CRISIS"
    if ratio >= 1.5:
        return "VOLATILE"

    sma20 = float(window["close"].tail(20).mean())
    sma50 = float(window["close"].tail(min(50, len(window))).mean())
    if price > sma20 > sma50:
        return "STRONG_TREND_UP"
    if price < sma20 < sma50:
        return "STRONG_TREND_DOWN"
    return "RANGING"


def regime_blocks_entry(regime: str | None, *, strategy_mode: str = "") -> bool:
    """مسدودسازی رژیم — بسته به نوع استراتژی."""
    r = regime or "RANGING"
    mode = (strategy_mode or "").lower()
    if mode in ("london_sweep", "scalp"):
        return r == "CRISIS"
    if mode == "h4_swing":
        return r == "CRISIS"
    return r in ("CRISIS", "VOLATILE")


def is_gold_symbol(symbol: str) -> bool:
    s = symbol.upper()
    return "XAU" in s or "GOLD" in s


def lot_pip_value(symbol: str) -> float:
    """Pip value per standard lot unit — طلا از position_logic."""
    return pip_size(symbol)


def optimal_lot_size(
    equity: float,
    risk_per_trade: float,
    stop_loss_pips: float,
    symbol: str,
    *,
    contract_size_units: float | None = None,
    min_lot: float = HARD_MIN_LOT,
    max_lot: float = HARD_MAX_LOT,
) -> float:
    """
    لات بهینه بر اساس ریسک ثابت (pip-based — فارکس).
    برای طلا از lot_from_stop_distance استفاده کنید.
    """
    if stop_loss_pips <= 0:
        return min_lot
    cs = contract_size_units or (1000.0 if "JPY" in symbol.upper() else STANDARD_CONTRACT_SIZE)
    risk_amount = equity * risk_per_trade
    pip_value = lot_pip_value(symbol)
    lot = risk_amount / (stop_loss_pips * pip_value * cs)
    lot = round(lot, 2)
    return max(min_lot, min(lot, max_lot))


def lot_from_stop_distance(
    equity: float,
    risk_per_trade: float,
    entry_price: float,
    stop_loss: float,
    symbol: str,
    *,
    regime: str = "RANGING",
    min_lot: float = HARD_MIN_LOT,
    max_lot: float = HARD_MAX_LOT,
    lot_step: float = 0.01,
) -> float:
    """محاسبه لات از فاصله SL — parity با بک‌تست (طلا-aware)."""
    risk_money = equity * risk_per_trade
    risk_per_unit = abs(entry_price - stop_loss) * contract_size(symbol)
    if risk_per_unit <= 0:
        lot = min_lot
    else:
        lot = risk_money / risk_per_unit
        lot *= regime_position_multiplier(regime)
    lot = max(min_lot, min(lot, max_lot))
    return round(round(lot / lot_step) * lot_step, 2)


def recommended_lot_size(
    equity: float,
    risk_per_trade: float,
    stop_loss_pips: float,
    symbol: str,
    regime: str = "RANGING",
) -> float:
    """لات نهایی پیشنهادی = optimal × ضریب رژیم، گرد و محدودشده به [0.01, 10]."""
    lot = optimal_lot_size(equity, risk_per_trade, stop_loss_pips, symbol)
    lot *= regime_position_multiplier(regime)
    lot = round(lot, 2)
    return max(HARD_MIN_LOT, min(lot, HARD_MAX_LOT))


# --------------------------------------------------------------------------- #
# ATR → فاصله‌ی استاپ (pip)
# --------------------------------------------------------------------------- #
def atr_from_ohlcv(df: pd.DataFrame) -> float:
    """
    آخرین ATR را از DataFrame می‌خواند یا از True Range محاسبه می‌کند.

    رفتار مطابق `LegacyRiskGate._atr_from_df`.
    """
    if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]):
        return float(df["atr"].iloc[-1])
    if len(df) < 15:
        return float(df["close"].iloc[-1]) * 0.01
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    val = tr.rolling(14).mean().iloc[-1]
    price = float(df["close"].iloc[-1])
    if pd.isna(val) or val <= 0:
        return price * 0.01
    return float(val)


def atr_to_stop_pips(atr: float, symbol: str) -> float:
    """تبدیل ATR به pip — از pip_size واقعی نماد."""
    pip = pip_size(symbol)
    if pip <= 0:
        return 20.0
    return max(20.0, min(atr / pip, 200.0))


# --------------------------------------------------------------------------- #
# گیت معامله (can_trade)
# --------------------------------------------------------------------------- #
@dataclass
class RiskLimits:
    """آستانه‌های ریسک (پیش‌فرض‌ها مطابق نسخه‌ی قدیم)."""

    max_daily_loss: float = 0.05
    max_weekly_loss: float = 0.15
    max_monthly_loss: float = 0.25
    max_consecutive_losses: int = 5
    max_leverage: float = 10.0

    @classmethod
    def from_config(cls, config: dict[str, Any] | None) -> "RiskLimits":
        cfg = config or {}
        return cls(
            max_daily_loss=float(
                cfg.get("max_daily_loss", cfg.get("MAX_DAILY_RISK", 0.05))
            ),
            max_weekly_loss=float(
                cfg.get("max_weekly_loss", cfg.get("MAX_WEEKLY_RISK", 0.15))
            ),
            max_monthly_loss=float(
                cfg.get("max_monthly_loss", cfg.get("MAX_MONTHLY_RISK", 0.25))
            ),
            max_consecutive_losses=int(
                cfg.get("max_consecutive_losses", cfg.get("MAX_CONSECUTIVE_LOSSES", 5))
            ),
            max_leverage=float(cfg.get("max_leverage", cfg.get("MAX_LEVERAGE", 10.0))),
        )


@dataclass
class RiskState:
    """وضعیت لحظه‌ای حساب برای ارزیابی گیت."""

    daily_loss: float = 0.0
    weekly_loss: float = 0.0
    monthly_loss: float = 0.0
    consecutive_losses: int = 0
    leverage: float = 0.0
    active_correlations: list[float] = field(default_factory=list)


def can_trade(state: RiskState, limits: RiskLimits) -> tuple[bool, str]:
    """
    آیا با توجه به وضعیت و آستانه‌ها معامله مجاز است؟

    آستانه‌ها «relaxed» مطابق نسخه‌ی قدیم (ضرایب ۲x/۱.۵x). برمی‌گرداند
    (allowed, reason).
    """
    if state.daily_loss >= limits.max_daily_loss * 2.0:
        return False, "daily loss limit exceeded"
    if state.weekly_loss >= limits.max_weekly_loss * 1.5:
        return False, "weekly loss limit exceeded"
    if state.monthly_loss >= limits.max_monthly_loss * 1.5:
        return False, "monthly loss limit exceeded"
    if state.consecutive_losses >= limits.max_consecutive_losses * 2:
        return False, "max consecutive losses reached"
    if state.leverage > limits.max_leverage * 2.0:
        return False, "leverage limit exceeded"
    if any(abs(c) > 0.95 for c in state.active_correlations):
        return False, "very high correlation with open position"
    return True, "approved"
