# Position Lifecycle

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Traced execution → MT5 → position manager → kill switch
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Lifecycle of a position from **approved signal** through **close and journal** on the default live path.

## Lifecycle Diagram (Verified)

```text
RiskGate approves signal (adjusted_lot)
  ↓
ExecutionStage → Mt5ExecutionAdapter.execute()
  ↓
[live] mt5.order_send (market deal, magic 234000)
  ↓
record_live_entry() + TradeJournal.log_execution()
  ↓
Position open at broker
  ↓
Each global cycle: Mt5PositionManager.manage_all()
  ├── Friday close (if enabled)
  ├── EOD close (if enabled)
  ├── Emergency max loss pips
  ├── Partial TP (preset-dependent; M5 partial OFF)
  └── ATR trailing stop modify
  ↓
Close via SL/TP at broker OR manager-initiated close OR KillSwitch flatten
  ↓
Journal / telemetry (entry logged; full exit accounting PARTIALLY VERIFIED)
```

## 1. Entry

| Step | Owner | Evidence |
|------|-------|----------|
| Risk approval | `RiskGate` | `risk_stage.py` |
| Order build | `Mt5ExecutionAdapter._place_market_order` | SL/TP on request if set |
| Pre-send validation | `order_logic.validate_order`, `check_order_risk` | `domain/order_logic.py` |
| Send | `guarded_order_send` → `mt5.order_send` | `mt5_execution.py` |
| Retry | Up to 2 attempts, refresh price | `_order_send_with_retry` |
| Post-fill | `record_live_entry`, journal, telemetry | `mt5_execution.py` |

**Dry-run/paper:** No broker send; journal records simulated outcome.

## 2. Open Position Monitoring

**Primary owner:** `Mt5PositionManager.manage_all()` — called **every global cycle** from `TradingKernel._manage_positions()`.

Also: `executor.manage_open_positions()` logs open count per market (debug).

**Evidence:** `tradingbot/kernel/trading_kernel.py`

## 3. Modification Actions (Mt5PositionManager)

| Action | Condition | Broker action |
|--------|-----------|---------------|
| Emergency close | Loss exceeds `EMERGENCY_MAX_LOSS_PIPS` | Close deal |
| Partial TP | R-multiple targets (if enabled for TF) | Partial close |
| Trailing stop | ATR-based improvement only | `TRADE_ACTION_SLTP` modify |
| EOD close | Time ≥ EOD hour/minute | Close |
| Friday close | Friday after configured hour | Close |

M5 preset: `ENABLE_PARTIAL_TP: False` — partial TP **DISABLED** for default M5 live.

**Evidence:** `mt5_position_manager.py`; `pa_symbol_tf_presets.py` M5 block

## 4. Alternate Position Owners (Disabled Default)

| Component | Status | Risk if enabled with kernel manager |
|-----------|--------|--------------------------------------|
| `PositionProtector` | **DISABLED** | Duplicate trailing/partial/emergency |
| `PositionRecoveryService` | **DISABLED** | Duplicate recovery logic |

Disabled when router/adaptive/vol enabled: `live_runner.py:341–347`.

## 5. Kill Switch Exit

On trigger: closes **all** positions via market deals (`KillSwitchService._close_all_positions`), sets emergency stop, watchdog may exit with code 2.

**Bypasses:** RiskGate (intentional emergency authority).

**Evidence:** `kill_switch.py`

## 6. Startup Reconciliation

After MT5 connect: logs open position count; if any, calls `position_manager.manage_all()` once.

**Evidence:** `live_runner.py::_startup_position_reconciliation`

Does not auto-close unknown orphans — applies manager rules to existing positions.

## 7. Journal and Metrics

| Artifact | What is logged | Exit detail |
|----------|----------------|-------------|
| `TradeJournal` SQLite | Executions table with fill, slip, ticket | **PARTIALLY VERIFIED** — entry-focused schema |
| `engine_telemetry` | Trade open events | UNKNOWN close pairing |
| `meta_decision_log` | Meta decisions at entry | N/A |
| MT5 broker history | Source of truth for fills | Outside repo |

**Evidence:** `tradingbot/services/trade_journal.py`

## Backtest Lifecycle Differences

- `SimulatedBroker` opens virtual positions
- SL/TP checked intrabar in backtest engine before new entries
- Same `Mt5PositionManager` logic mirrored in `BacktestPositionManager`

**Evidence:** `tradingbot/backtest/engine.py`, `broker.py`

## Unknowns

- Complete exit_reason propagation into journal for all close paths
- Orphan ticket handling when bot restarts mid-trade (beyond one-shot manage_all)

## Change Impact

`tradingbot/adapters/mt5_execution.py`, `mt5_position_manager.py`, `kill_switch.py`, `trade_journal.py`, PA presets

## Verification

Trace `ExecutionStage` → `Mt5ExecutionAdapter` → `TradingKernel._manage_positions`.
