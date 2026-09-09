"""پیکربندی بک‌تست."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingbot.config.live import PRIMARY_SYMBOL


@dataclass
class BacktestConfig:
    symbols: list[str] = field(default_factory=lambda: [PRIMARY_SYMBOL])
    timeframe: str = "M5"
    bars: int = 10000              # تعداد کندل تاریخی برای دریافت
    days: int | None = None        # اگر set باشد، داده با copy_rates_range (مثلاً 90 = ۳ ماه)
    start_offset_days: int = 0     # walk-forward: پرش به عقب از «الان» (روز)
    warmup: int = 300              # کندل‌های ابتدایی برای گرم‌شدن اندیکاتورها
    signal_window: int = 500       # پنجره داده برای استراتژی (Context نیاز به ~400+ دارد)
    initial_balance: float = 1000.0
    risk_per_trade: float = 0.005  # ۰.۵٪ — parity با live RISK_PER_TRADE
    max_daily_loss_pct: float = 0.04
    max_trades_per_day: int = 10
    cooldown_bars: int = 18  # PA_COOLDOWN_BARS parity
    max_consecutive_losses: int = 3
    cooldown_after_loss_bars: int = 30
    min_balance_pct: float = 0.70
    min_confidence: float | None = None  # آستانه‌ی اطمینان (None = پیش‌فرض استراتژی)
    max_positions_per_symbol: int = 1
    max_open_positions_total: int = 2
    require_htf_alignment_m5: bool = False
    require_htf_alignment_m15: bool = False
    require_htf_alignment_h4: bool = False
    htf_timeframe: str = "H4"
    min_lot: float = 0.01
    max_lot: float = 100.0
    lot_step: float = 0.01
    # Offline broker economics override (merged into legacy BROKER_SYMBOL_CATALOG)
    broker_economics: dict[str, dict[str, Any]] | None = None
    # PROXY | DATASET | CONFIGURED | UNKNOWN | AUTO — see backtest/cost_model.py
    spread_mode: str = "AUTO"
    simulate_forming_bar: bool = True
    # Explicit instrument binding (no silent XAUUSD == XAUUSD_i)
    configured_instrument_symbol: str = PRIMARY_SYMBOL
    dataset_symbol_map: dict[str, str] = field(default_factory=dict)
    # Commission/swap/slippage evidence status — never infer ZERO from missing data
    commission_status: str = "UNKNOWN"  # ZERO | MODELED | UNKNOWN | VERIFIED_SCHEDULE (gate, not current verification) | OBSERVED_ZERO_NOT_PROVEN — never infer ZERO from observed zeros
    slippage_status: str = "MODELED_PROXY"  # ZERO | MODELED | MODELED_PROXY | REALIZED | UNKNOWN — Phase 27.14: MODELED policy is MODELED_PROXY; ≠ REALIZED; base pips is an assumption
    swap_status: str = "UNKNOWN"  # ZERO | MODELED | UNKNOWN | BROKER_RATE_ONLY (rates ≠ historical series)
    # مدل هزینه (تقریبی + متغیر بر اساس سشن)
    spread_pips: float = 2.5
    slippage_pips: float = 0.8
    variable_spread: bool = True
    commission_per_lot: float = 0.0
    # فیلترها
    max_spread_pips: float = 5.0
    use_news_filter: bool = True
    news_blackout_minutes: int = 30
    friday_close_enabled: bool = True
    friday_close_hour: int = 20
    friday_close_minute: int = 0
    friday_no_entry_after_hour: int = 17
    trailing_atr_mult: float = 1.8
    # مدیریت پوزیشن هسته‌محور
    enable_trailing: bool = True
    enable_partial_tp: bool = True
    enable_emergency: bool = True
    emergency_max_loss_pips: float = 90.0
    # اسکالپ M1
    enable_eod_close: bool = True
    eod_hour: int = 23
    eod_minute: int = 55
    enable_zscore_exit: bool = True
    zscore_exit_z: float = 0.3
    zscore_window: int = 20
    # کش داده
    cache_dir: str = "data/backtest"
    use_cache: bool = True
    use_meta_labeler: bool = True
    # XAUUSD position management: none | legacy | 36a | 52a
    position_management_mode: str = "legacy"
