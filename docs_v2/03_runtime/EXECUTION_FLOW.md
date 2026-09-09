# Execution Flow

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of EXECUTION modes.  
**Operator-effective state:** UNKNOWN  

## Modes (`Mt5ExecutionAdapter.execute`)

| Mode | Condition | Broker order | Evidence |
|------|-----------|--------------|----------|
| Dry-run | `is_dry_run()` | No | journals `dry_run` |
| Paper | `is_paper()` | No | `PaperTradeRecorder` |
| Live | `--execute` and not dry/paper | Yes | `guarded_order_send` / `_order_send_with_retry` |

Daemon argument is `--execute`. `TRADINGBOT_DRY_RUN` / `TRADINGBOT_PAPER` operator values = **UNKNOWN**.

## Live send path (code)

1. MT5 connected (`ensure_mt5_connected`)  
2. Broker symbol reconcile  
3. AutoTrading ready  
4. Direction → MT5 signal; HOLD → no order  
5. Current price; SL/TP from signal  
6. `order_send` with retry  
7. Slippage **logged** vs request when fill exists  

Partial fills: **UNKNOWN / not specified as a complete model in this documentation.**  
Commission: **UNKNOWN.**  
Sizing: RiskGate before this adapter (lot argument).  

Failure: returns `ExecutionResult(success=False, message=...)`. Missing price / AutoTrading / connect → no order (fail-closed for that cycle).
