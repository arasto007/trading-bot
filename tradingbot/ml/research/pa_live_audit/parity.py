"""Phase 1.5.57 — LIVE vs BACKTEST vs RESEARCH parity matrix (no silent fixes)."""

from __future__ import annotations

from typing import Any

A = "A"  # identical
B = "B"  # materially equivalent
C = "C"  # different but understood
D = "D"  # unexplained divergence


def parity_matrix() -> list[dict[str, Any]]:
    """Each row is a comparison. Classes are about implementations, not performance."""
    return [
        {
            "item": "signal function",
            "live": "PriceActionStrategy → evaluate_m5_london_sweep + apply_setup_hardening",
            "backtest": "BacktestEngine uses build_strategy_registry → same PA owner if factory defaults hold",
            "research": "scripts/phase14* call evaluate_gold_setup directly; some skip PriceActionStrategy wrappers",
            "class": B,
            "note": "Core setup function can be shared; wrappers (dedup, confirmation, telemetry) differ",
        },
        {
            "item": "indicators / ATR",
            "live": "domain.price_action._atr period 14 on the strategy frame",
            "backtest": "PassthroughIndicatorEngine — ATR computed inside enrich_price_action, not a separate indicator engine",
            "research": "some scripts use (high-low).rolling(14) proxy (phase14b2_fast) instead of true ATR",
            "class": C,
            "note": "Research fast scripts can diverge from live ATR",
        },
        {
            "item": "candle timing / forming bar",
            "live": "exclude_forming_bar drops last MT5 row (closed-bar decision)",
            "backtest": "historical bars are already closed; no forming row",
            "research": "mixed — some use full-frame enrich (swing right=3 can see future bars if not sliced)",
            "class": C,
            "note": "Live vs backtest closed-bar is B; research full-frame enrich is look-ahead risk",
        },
        {
            "item": "look-ahead",
            "live": "enrich at last index; swings need `right=3` so last 3 bars cannot be swing points",
            "backtest": "same if it calls enrich per bar with at_index",
            "research": "enrich entire history then score bar i → swings use i+right future bars",
            "class": C,
            "note": "Understood: full-frame research enrich is not live-safe",
        },
        {
            "item": "OHLC source",
            "live": "Mt5MarketDataAdapter copy_rates on XAUUSD_i",
            "backtest": "BacktestMarketData cache or MT5 fetch; default symbol XAUUSD",
            "research": "data/ml/raw/candles/m5/XAUUSD_m5.parquet",
            "class": C,
            "note": "Three stores; XAUUSD_i research candles absent",
        },
        {
            "item": "symbol",
            "live": "PRIMARY_SYMBOL XAUUSD_i (normalized to XAUUSD for presets)",
            "backtest": "BacktestConfig.symbols default ['XAUUSD']",
            "research": "XAUUSD parquet",
            "class": C,
            "note": "Name alias is not proven economic identity (1.5.52)",
        },
        {
            "item": "timeframe",
            "live": "get_live_config forces ['5m'] when router/adaptive/vol on",
            "backtest": "BacktestConfig.timeframe default **M1**",
            "research": "usually M5 when PA-specific",
            "class": C,
            "note": "Default backtest TF is not the live TF unless the caller overrides",
        },
        {
            "item": "spread assumptions",
            "live": "RiskGate._live_spread_pips from MT5 tick; fail-closed 999 if tick missing",
            "backtest": "BacktestConfig spread_pips=2.5 slippage=0.8 variable_spread=True commission=0",
            "research": "usually uncosted or paper 0.30",
            "class": C,
            "note": "Not measured broker tape; backtest costs are assumed",
        },
        {
            "item": "SL/TP calculation",
            "live": "sweep extreme ± 0.35 ATR; TP max(asian opposite, 1.5R)",
            "backtest": "same if same setup function + same preset",
            "research": "same if evaluate_m5_london_sweep + M5 preset",
            "class": B,
        },
        {
            "item": "ATR calculation",
            "live": "TR rolling mean 14",
            "backtest": "same via enrich_price_action",
            "research": "sometimes high-low mean proxy",
            "class": C,
        },
        {
            "item": "entry timing",
            "live": "closed M5 bar close as entry price (setup.entry = close)",
            "backtest": "kernel on that bar then SimulatedBroker fill ± spread/slip",
            "research": "often fill = close with no spread",
            "class": C,
        },
        {
            "item": "exit timing",
            "live": "broker SL/TP + Mt5PositionManager (trailing/partial/EOD flags from config)",
            "backtest": "SimulatedBroker + BacktestPositionManager; default trailing/partial/zscore/EOD ON in BacktestConfig",
            "research": "typically first-touch SL/TP on subsequent bars",
            "class": C,
            "note": "Live M5 ENABLE_PARTIAL_TP=False; BacktestConfig defaults enable_partial_tp=True then overlay pa_tf",
        },
        {
            "item": "session filters",
            "live": "NY 15–16 UTC; DEMO_DISABLE_SESSION_FILTER can bypass",
            "backtest": "same PriceActionStrategy session check if same cfg",
            "research": "sometimes different hours / heatmap scripts",
            "class": B,
        },
        {
            "item": "signal confirmation",
            "live": "SIGNAL_CONFIRMATION_BARS=0",
            "backtest": "same preset",
            "research": "varies",
            "class": A,
        },
        {
            "item": "position sizing",
            "live": "RiskGate lot from live equity + sl distance + regime multiplier",
            "backtest": "BacktestRiskGate / 1% of simulated 1000 balance by default",
            "research": "often R-multiples only, no lots",
            "class": C,
        },
        {
            "item": "rounding",
            "live": "order_value special-case XAUUSD_i ×100; lot round 0.01",
            "backtest": "SimulatedBroker lot step; symbol often XAUUSD → different order_value path",
            "research": "n/a",
            "class": C,
        },
        {
            "item": "tick / point",
            "live": "pip_size heuristic 0.1; tick_value from MT5 when RiskGate queries",
            "backtest": "pip_size heuristic; no MT5 tick_value",
            "research": "R units from SL distance",
            "class": C,
        },
        {
            "item": "execution model",
            "live": "Mt5ExecutionAdapter + live book",
            "backtest": "SimulatedBroker mid ± assumed spread/slip",
            "research": "bar high/low first-touch",
            "class": C,
        },
        {
            "item": "missing-data behavior",
            "live": "empty df → no signal; spread tick None → 999 pips → spread gate fail",
            "backtest": "RuntimeError if not enough bars; assumed spread always present",
            "research": "skip / NaN ATR fallback price*0.001",
            "class": C,
        },
        {
            "item": "RiskGate vs BacktestRiskGate",
            "live": "full live gates + meta + MT5 account sync",
            "backtest": "BacktestRiskGate subset (spread assumed, news/friday similar)",
            "research": "usually no RiskGate",
            "class": C,
        },
        {
            "item": "meta-labeler",
            "live": "wired; gating conditional (ready + WR + regime)",
            "backtest": "use_meta_labeler=True default on BacktestConfig",
            "research": "usually off",
            "class": C,
            "note": "Continuous live meta enforcement NOT PROVEN (ML_STATUS)",
        },
        {
            "item": "max positions / cooldown",
            "live": "3 total / 2 per symbol / 18 bars / 3 per day from M5 preset",
            "backtest": "BacktestConfig defaults 2 total / 1 per symbol then overlay pa_tf when present",
            "research": "varies",
            "class": B,
        },
    ]


def unexplained_count(rows: list[dict[str, Any]] | None = None) -> int:
    return sum(1 for r in (rows or parity_matrix()) if r.get("class") == D)
