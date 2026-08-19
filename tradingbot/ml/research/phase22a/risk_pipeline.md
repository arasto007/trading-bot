# Phase 22A — Risk Pipeline

## Components

| Component | File | Role |
|-----------|------|------|
| RiskGate | `adapters/risk_gate.py` | Production IRiskGate |
| risk_logic | `domain/risk_logic.py` | Core limits, can_trade |
| LiveRiskTracker | `services/live_risk_tracker.py` | Daily trades, cooldown, loss |
| MetaLabeler | `services/meta_labeler.py` | Secondary ML filter at risk stage |
| BacktestRiskGate | `backtest/risk.py` | Simulated equivalent |

## Position Sizing

```python
# risk_gate.evaluate() after gates pass
lot = lot_from_stop_distance(
    equity, risk_per_trade, entry, stop_loss, symbol
)
# Clamped: MIN_LOT_SIZE .. MAX_LOT_SIZE
# Default risk: 0.005 (0.5%) from RISK_PER_TRADE / presets
```

## Lot Calculation Inputs

- Account equity (synced from MT5)
- Signal entry price + stop_loss distance
- Symbol pip/point value
- `RISK_PER_TRADE` default 0.005

## Maximum Exposure

| Limit | Source | Default |
|-------|--------|---------|
| MAX_OPEN_POSITIONS_TOTAL | PRICE_ACTION preset | 2-3 |
| MAX_OPEN_POSITIONS_PER_SYMBOL | preset | 2 |
| Leverage check | AccountState.get_leverage() | risk_logic |
| MAX_DAILY_RISK | config | 4% |

## Drawdown Control

- `LiveRiskTracker` — daily PnL vs initial balance
- `KillSwitchService` — emergency flatten + kernel EMERGENCY_STOP
- `emergency_drawdown` config (0.25) in background services
- `Mt5PositionManager` — per-position emergency close

## Daily Limits

- `MAX_TRADES_PER_DAY` per TF preset (3/4/2)
- `COOLDOWN_BARS` after entry
- `MAX_CONSECUTIVE_LOSSES` + cooldown bars (backtest + tracker)

## Stop Loss / Take Profit

| Source | Method |
|--------|--------|
| ML signals | `map_unified_to_trading_signal()` — ATR multiples |
| Legacy PA | `build_trading_signal()` — sl_atr from preset |
| Execution | Attached to MT5 request sl/tp fields |
| Management | Mt5PositionManager trailing/partial |

**Target RR:** 1:2 (project default; preset-specific sl_atr/tp)

## Trade Rejection Logic (ordered)

1. **Live gates** (`_live_gates`):
   - Max positions total/symbol
   - Opposite position block
   - Spread gate (MAX_SPREAD_PIPS)
   - News blackout (USE_NEWS_FILTER)
   - Friday no-entry hour
   - HTF alignment
   - Market filters (session)

2. **LiveRiskTracker.check_entry_allowed**:
   - Max trades per day per TF
   - Cooldown bars
   - Daily loss limit

3. **risk_logic.can_trade**:
   - Regime limits
   - Leverage / exposure

4. **MetaLabeler** (if `should_gate(tf, regime)`):
   - `prob < effective_threshold` → reject

5. **Pre-execution** (`order_logic`):
   - validate_order
   - check_order_risk

## Meta-Labeler Integration

- Loaded from `data/models/meta_labeler_{m5,m15,h4}.pkl`
- Features via `capture_entry_features()` at risk evaluation
- Threshold: `META_LABEL_THRESHOLD` default 0.40, regime-adjusted
- Logs to meta decision log

## Portfolio Snapshot

RiskGate.portfolio_snapshot() syncs MT5 account:
- balance, equity, open positions list
- Passed to each RiskStage evaluation

## Backtest Parity

BacktestRiskGate mirrors live gates + meta when `use_meta_labeler=True`.

## Default Risk Parameters

```
RISK_PER_TRADE = 0.005  (0.5%)
MAX_DAILY_RISK = 0.04   (4%)
DEFAULT_LOT = 0.01 fallback if no SL sizing
```
