"""Phase 1.5.56 — code-traced live PA path. Read-only inventory."""

from __future__ import annotations

from typing import Any

from tradingbot.config.live import LIVE_TRADING_CONFIG, PRIMARY_SYMBOL
from tradingbot.config.pa_symbol_tf_presets import get_symbol_tf_overrides
from tradingbot.config.price_action import PA_COOLDOWN_BARS, get_price_action_config
from tradingbot.ml.confidence_engine.engine_calibrator import TREND_MODEL_ID
from tradingbot.ml.integration.config import is_ml_kernel_enabled
from tradingbot.ml.integration.kernel_adapter import PIPELINE_TIMEOUT_MS
from tradingbot.ml.phase15a.config import TREND_ENGINE_ID, TREND_ENGINE_V41_ID


LIVE = "LIVE"
SHADOW = "SHADOW"
RESEARCH = "RESEARCH"
BACKTEST = "BACKTEST"
LEGACY = "LEGACY"
DEAD = "DEAD/UNUSED"


def live_m5_pa_config() -> dict[str, Any]:
    return get_price_action_config("XAUUSD", "M5")


def live_path_hops() -> list[dict[str, Any]]:
    """Exact default-daemon hops. Classifications are reachability on that path."""
    return [
        {
            "hop": "startup",
            "owner": "scripts/start_bot.py → application/live_runner.py / bootstrap.build_kernel_live",
            "class": LIVE,
        },
        {
            "hop": "configuration",
            "owner": "tradingbot/config/live.py::get_live_config",
            "facts": {
                "PRIMARY_SYMBOL": PRIMARY_SYMBOL,
                "PA_PRODUCTION_LOCK_default": bool(LIVE_TRADING_CONFIG.get("PA_PRODUCTION_LOCK", True)),
                "MULTI_ENGINE_ROUTER_ENABLED_default": bool(
                    LIVE_TRADING_CONFIG.get("MULTI_ENGINE_ROUTER_ENABLED", True)
                ),
                "router_forces_timeframes": ["5m"],
                "USE_ML_KERNEL_default": False,
            },
            "class": LIVE,
        },
        {
            "hop": "factory",
            "owner": "tradingbot/ml/integration/factory.py::build_strategy_registry",
            "class": LIVE,
            "note": "Default: MultiEngineRouterRegistry (+ optional shadow wrap)",
        },
        {
            "hop": "effective_registry",
            "owner": "tradingbot/adapters/multi_engine_router.py::MultiEngineRouterRegistry",
            "class": LIVE,
        },
        {
            "hop": "pa_production_lock",
            "owner": "tradingbot/services/pa_production_lock.py::is_pa_production_lock",
            "class": LIVE,
            "note": "When lock and Adaptive/VOL off: PA only; VOL/Adaptive probed and logged",
        },
        {
            "hop": "inner_pa_registry",
            "owner": "tradingbot/adapters/legacy_strategy_registry.py::LegacyStrategyRegistry.generate_signal",
            "class": LIVE,
        },
        {
            "hop": "strategy_manager",
            "owner": "engine/strategy_manager.py::StrategyManager.generate_combined_signals",
            "class": LIVE,
        },
        {
            "hop": "signal_owner",
            "owner": "engine/strategies/price_action_strategy.py::PriceActionStrategy.generate_signals",
            "class": LIVE,
            "note": "Last closed bar only; generate_signals uses i = len(data)-1",
        },
        {
            "hop": "setup_router",
            "owner": "tradingbot/domain/gold_strategies/router.py::evaluate_gold_setup",
            "class": LIVE,
        },
        {
            "hop": "setup_implementation",
            "owner": "tradingbot/domain/gold_strategies/m5_london_sweep.py::evaluate_m5_london_sweep",
            "class": LIVE,
        },
        {
            "hop": "hardening",
            "owner": "tradingbot/domain/pa_hardening.py::apply_setup_hardening",
            "class": LIVE,
        },
        {
            "hop": "signal_normalize",
            "owner": "tradingbot/domain/signal_helpers.py::build_trading_signal",
            "class": LIVE,
        },
        {
            "hop": "forming_bar",
            "owner": "tradingbot/pipeline/signal_stage.py + domain/ohlcv.py::exclude_forming_bar",
            "class": LIVE,
            "note": "Drops last MT5 row so decision is on a closed bar",
        },
        {
            "hop": "filters_strategy",
            "owner": "session window + kill-zone (off) + min confidence + quality score + PA dedup",
            "class": LIVE,
        },
        {
            "hop": "filters_risk",
            "owner": "tradingbot/adapters/risk_gate.py::_live_gates + check_entry_allowed + meta",
            "class": LIVE,
        },
        {
            "hop": "execution",
            "owner": "tradingbot/adapters/mt5_execution.py::Mt5ExecutionAdapter",
            "class": LIVE,
        },
        {
            "hop": "vol_inner",
            "owner": "VolRegimeStrategyRegistry",
            "class": SHADOW,
            "note": "Always called by router; not selected under PA lock",
        },
        {
            "hop": "adaptive_inner",
            "owner": "AdaptiveRegimeStrategyRegistry",
            "class": SHADOW,
            "note": "Always called by router; not selected under PA lock",
        },
        {
            "hop": "ml_shadow",
            "owner": "ShadowStrategyRegistry wrap (daemon default ON)",
            "class": SHADOW,
        },
        {
            "hop": "ml_kernel",
            "owner": "MLKernelRegistry / KernelAdapter",
            "class": DEAD,
            "note": "USE_ML_KERNEL default false; live gate not opened by this audit",
        },
        {
            "hop": "v41_calibrators",
            "owner": "engine_calibrator / TREND_MODEL_ID",
            "class": DEAD,
            "note": "Not on PA path; remain research-watch",
        },
        {
            "hop": "m15_h4_presets",
            "owner": "pa_symbol_tf_presets M15/H4",
            "class": DEAD,
            "note": "get_live_config with router on forces TIMEFRAMES=['5m']",
        },
        {
            "hop": "m5_scalp_h4_swing",
            "owner": "evaluate_m5_scalp / evaluate_h4_swing / evaluate_m15_intraday",
            "class": DEAD,
            "note": "M5 GOLD_STRATEGY_MODE=london_sweep → evaluate_m5_london_sweep only",
        },
        {
            "hop": "generic_evaluate_setup_at",
            "owner": "tradingbot/domain/price_action.py::evaluate_setup_at",
            "class": DEAD,
            "note": "Not called by PriceActionStrategy; gold router is used instead",
        },
        {
            "hop": "backtest_engine",
            "owner": "tradingbot/backtest/engine.py::BacktestEngine",
            "class": BACKTEST,
        },
        {
            "hop": "research_replays",
            "owner": "scripts/phase14*.py, research/setup_quality_score.py",
            "class": RESEARCH,
        },
    ]


def pa_live_specification() -> dict[str, Any]:
    cfg = live_m5_pa_config()
    ov = get_symbol_tf_overrides("XAUUSD", "M5")
    return {
        "signal_owner": "engine.strategies.price_action_strategy.PriceActionStrategy.generate_signals",
        "strategy_implementation": "tradingbot.domain.gold_strategies.m5_london_sweep.evaluate_m5_london_sweep",
        "preset": ov.get("PRESET"),
        "gold_strategy_mode": cfg.get("GOLD_STRATEGY_MODE"),
        "symbol_live": PRIMARY_SYMBOL,
        "symbol_preset_key": "XAUUSD (normalize_symbol)",
        "timeframe_live": "5m / M5 only when router enabled",
        "indicators_features": [
            "ATR(14) via domain.price_action._atr (Wilder-style TR rolling mean)",
            "Asian range high/low 00:00–ASIAN_SESSION_END_UTC (preset 8)",
            "Sweep lookback highs/lows (12 bars) + SWEEP_BUFFER_ATR*ATR",
            "Optional engulfing / pin-bar if M5_REQUIRE_REJECTION (preset False)",
            "Hardening: BOS/FVG/sweep flags + quality_score (MIN_QUALITY_SCORE=55)",
            "Session hour from bar timestamp (UTC)",
        ],
        "entry_rules": [
            "Closed bar only (exclude_forming_bar)",
            "UTC hour in NY 15 <= h < 16 (London session off)",
            "Asian range exists and range >= MIN_RANGE_ATR * ATR (0.2)",
            "Sweep of asian high/low beyond buffer, then close back inside range",
            "SELL: swept high + close inside; BUY: swept low + close inside",
            "ENABLE_CHOCH_CONTINUATION=False — CHoCH path off",
            "confidence >= MIN_CONFIDENCE 0.52",
            "quality_score >= 55 after hardening",
            "PA dedup cooldown 10 minutes (in-process cache)",
            "SIGNAL_CONFIRMATION_BARS=0",
        ],
        "sl_rules": "SL beyond sweep extreme ± SL_ATR_MULT*ATR (0.35)",
        "tp_rules": "max(distance to opposite Asian bound, risk * MIN_RR) with MIN_RR=1.5",
        "filters": {
            "strategy_layer": "session 15–16 UTC, quality, confidence, dedup",
            "risk_layer": "spread, news, Friday, max positions, cooldown 18 bars, max 3/day",
            "market_filters": "RiskGate check_market_filters (ATR percentile 12–94; ADX off; regime on)",
            "htf": "REQUIRE_HTF_ALIGNMENT_M5=False",
            "meta": "META_LABEL_THRESHOLD 0.38; gating if model ready + live WR>=35% + regime not CRISIS/VOLATILE",
            "kill_zone": "USE_KILL_ZONES=False",
        },
        "session_logic": "NY 15–16 UTC; Asian range 00–08 UTC; session_label in hardening is observability",
        "position_sizing": "RiskGate recommended_lot_size(equity, risk_per_trade, sl_pips, symbol) — live MT5 equity",
        "risk_logic": "RiskGate _capital_adaptive_gates + _live_gates + tracker + risk_logic.can_trade + optional meta reject",
        "execution_assumptions": "Mt5ExecutionAdapter market/pending fill; live tick spread; not bar mid",
        "cooldown_bars": PA_COOLDOWN_BARS,
        "pipeline_timeout_ms": PIPELINE_TIMEOUT_MS,
        "ml_kernel_enabled": is_ml_kernel_enabled(),
        "trend_ids_untouched": {
            "TREND_MODEL_ID": TREND_MODEL_ID,
            "TREND_ENGINE_ID": TREND_ENGINE_ID,
            "TREND_ENGINE_V41_ID": TREND_ENGINE_V41_ID,
        },
        "preset_values": {
            "MIN_RR": cfg.get("MIN_RR"),
            "SL_ATR_MULT": cfg.get("SL_ATR_MULT"),
            "MIN_CONFIDENCE": cfg.get("MIN_CONFIDENCE"),
            "MIN_QUALITY_SCORE": cfg.get("MIN_QUALITY_SCORE"),
            "M5_REQUIRE_REJECTION": cfg.get("M5_REQUIRE_REJECTION"),
            "M5_USE_LONDON_SESSION": cfg.get("M5_USE_LONDON_SESSION"),
            "M5_USE_NY_SESSION": cfg.get("M5_USE_NY_SESSION"),
            "NY_ENTRY_START_UTC": cfg.get("NY_ENTRY_START_UTC"),
            "NY_ENTRY_END_UTC": cfg.get("NY_ENTRY_END_UTC"),
            "ASIAN_SESSION_END_UTC": cfg.get("ASIAN_SESSION_END_UTC"),
            "ENABLE_CHOCH_CONTINUATION": cfg.get("ENABLE_CHOCH_CONTINUATION"),
            "ENABLE_PARTIAL_TP": cfg.get("ENABLE_PARTIAL_TP"),
        },
    }
