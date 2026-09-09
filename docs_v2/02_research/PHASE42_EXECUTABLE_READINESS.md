# Phase 42 — Executable Readiness

**EXECUTABLE_BACKTEST_READY:** `False`
**Readiness:** `BLOCKED`

Required inputs and epistemic labels:

- `entry_price`: OBSERVED (Phase 40 RAW theoretical)
- `exit_price`: OBSERVED (Phase 40 theoretical SL/TP path)
- `spread`: PARTIAL sidecar / PROXY eval tape
- `commission`: UNKNOWN
- `swap`: CURRENT OBSERVED / HISTORICAL UNKNOWN
- `slippage`: MODELED
- `volume`: UNKNOWN
- `contract_size`: 100.0
- `tick_value`: 1.0
- `tick_size`: 0.01
- `execution_mode`: 2
- `minimum_volume`: 0.01
- `volume_step`: 0.01
- `SL`: OBSERVED on Phase 40 setups
- `TP`: OBSERVED on Phase 40 setups
- `holding_duration`: OBSERVED on Phase 40 setups
- `rollover`: CURRENT rate OBSERVED; historical UNKNOWN

Blockers:

- commission UNKNOWN / no VERIFIED_SCHEDULE
- request/fill pairs=0
- eval-tape Bid/Ask incomplete

The existing backtest engine was **not** changed.
Executable evaluation was **not** run.
