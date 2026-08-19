# Phase 10.3 — Trade Integrity Audit

## Scope

Audit of virtual trade construction in Phase 10.2 live shadow (`live_shadow_runner.py`) before the Phase 10.3 integrity fix.

**Out of scope (unchanged):** TradingKernel, RiskGate, Execution, Mt5ExecutionAdapter, ML model, feature pipeline, dataset, training.

---

## Current Trade Path (Phase 10.2)

```
MT5 candles → TradingKernel.run_market_cycle()
  → SignalStage (legacy + ML composite)
  → RiskStage (real RiskGate.evaluate)
  → ExecutionStage (ShadowExecutionGuard — blocked)
  → live_shadow_runner: if risk.allowed → virtual_order from ctx.signal
  → PaperBroker.resolve_bar → virtual PnL
```

### Components reviewed

| Component | Role | Modified in 10.3? |
|-----------|------|-------------------|
| `ShadowExecutionGuard` | Blocks real orders, logs blocked virtual metadata from signal | No |
| `live_shadow_runner._OpenVirtual` | Holds open virtual position | Yes (ATR levels) |
| `PaperBroker` | Entry fill, SL/TP helper, bar resolution | Yes (simultaneous SL/TP rule) |
| `PositionManager` (paper_trading) | Used in Phase 9.10 sidecar only | No |
| `RiskGate` | Real approval + `adjusted_lot` | No |
| ATR source | `compute_atr_at()` in `ml/dataset/labels.py` | Reused (read-only) |

---

## Where SL / TP / Size Were Produced (Phase 10.2 bug)

| Field | Source (10.2) | Problem |
|-------|---------------|---------|
| **Entry** | `ctx.signal.metadata["entry"]` or fallback `ctx.signal.stop_loss` | Fallback sets **entry == SL** |
| **SL** | `ctx.signal.stop_loss` | Legacy priceaction signals often invalid vs ATR |
| **TP** | `ctx.signal.take_profit` | Not guaranteed 2R from entry |
| **Size** | `ctx.risk.adjusted_lot` | OK from RiskGate, but applied to bad levels |
| **PnL** | `R_multiple * equity * risk_pct` | Correct formula, wrong levels → wrong outcomes |

### Root cause

Virtual trades copied **kernel signal SL/TP** instead of recomputing **ATR-based 1R:2R** levels at the bar close. Legacy `priceaction` signals frequently emit `stop_loss` equal to entry or distant TP unrelated to ATR.

### Evidence — `live_run_v1` (Phase 10.2)

- Total virtual trades: **71**
- Trades with `entry == sl` (or near): **majority of legacy-approved signals**
- R:R not equal to 2.0: widespread on non-ML signals

Example bad record:

```json
{
  "entry": 4107.14275,
  "sl": 4107.14275,
  "tp": 4198.14,
  "result": "SL"
}
```

---

## Phase 10.3 Fix

New integration-only layer:

1. **`ATRTradeCalculator`** — entry via spread/slippage fill, SL/TP from ATR (1R / 2R)
2. **`TradeIntegrityValidator`** — geometry, R:R, position size checks
3. **`VirtualTradeBuilder`** — builds plan only after validation passes
4. **`trade_integrity_logger`** — `data/ml/shadow/trade_integrity/{run_id}/`

Virtual orders are **no longer** taken from `ctx.signal.stop_loss` / `take_profit`. Kernel signal direction + RiskGate approval still drive *whether* a trade opens; levels come from ATR calculator.

### PaperBroker bar resolution

When both SL and TP are inside the same bar range, **SL is resolved first** (pessimistic / conservative — no tick data).

---

## Files Changed (Phase 10.3)

| File | Change |
|------|--------|
| `tradingbot/ml/integration/sl_tp_calculator.py` | **New** |
| `tradingbot/ml/integration/trade_integrity.py` | **New** |
| `tradingbot/ml/integration/virtual_trade_builder.py` | **New** |
| `tradingbot/ml/integration/trade_integrity_logger.py` | **New** |
| `tradingbot/ml/integration/live_shadow_runner.py` | Virtual trade path |
| `tradingbot/ml/paper_trading/paper_broker.py` | Simultaneous SL/TP rule |
| `tradingbot/ml/data/paths.py` | Trade integrity paths |
| `tests/test_ml_phase10_3_trade_integrity.py` | **New** |

**Not changed:** TradingKernel, RiskGate, Execution, Mt5ExecutionAdapter, ML model, feature pipeline, dataset, training.
