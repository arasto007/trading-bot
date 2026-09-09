# Risk and Execution Boundary

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Epistemic-Role:** OWNER of risk-vs-execution split (supporting RISKGATE + EXECUTION).  
**Operator-effective state:** UNKNOWN  

| Concern | Owner | Not owner |
|---------|--------|-----------|
| Allow/deny new entry | `RiskGate` | Execution adapter |
| Lot size | RiskGate / micro planner | Strategy may propose SL/TP |
| SL/TP on signal | PA setup + hardening | Risk may still reject |
| Broker send | `Mt5ExecutionAdapter` | RiskGate |
| Paper vs live | `execution_mode` + adapter branches | Factory |
| Duplicate / cooldown | RiskGate tracker + PA dedup | |
| Position manage | `Mt5PositionManager` each cycle | Signal stage |
| Kill / emergency | KillSwitch / emergency stop | |
| Partial fill | **UNKNOWN** | |
| Commission | **UNKNOWN** | |
| Research replay fills | Isolated audits | Not MT5 |

Live execute still requires RiskGate **allowed**. `--execute` without a passing gate does not send an order.

Future Demo/Real work must keep `Signal → RiskGate → Execution` (`DEMO_REAL_SYMBOL_COST_DESIGN.md`). Proposed `ACCOUNT_ENVIRONMENT` is **not** live.
