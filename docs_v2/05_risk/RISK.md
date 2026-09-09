# Risk Controls

> **Canonical risk memory (2026-09-01):** `docs_v2/05_risk/RISKGATE_SPEC.md` and `RISK_AND_EXECUTION_BOUNDARY.md`.

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Read `RiskGate.evaluate`, gate helpers, KillSwitch, LiveRiskTracker
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

Risk and safety controls affecting **new trade entries** and **account-level emergency stops**.

## Final Authority for New Entries

**`RiskGate`** via **`RiskStage`** — every new entry on the kernel path must pass `RiskGate.evaluate()` before `ExecutionStage`.

**Evidence:** `tradingbot/pipeline/risk_stage.py`; `tradingbot/kernel/trading_kernel.py` pipeline order

**Exception paths that bypass RiskGate for new entries:** None on kernel path. Research scripts and ORB demo are separate.

## RiskGate Implementation

| Field | Value |
|-------|-------|
| **File** | `tradingbot/adapters/risk_gate.py` |
| **Factory** | `create_risk_gate(config)` |
| **Interface** | `IRiskGate.evaluate(signal, portfolio_snapshot) -> RiskDecision` |

## evaluate() Sequence (Verified)

1. **Entries frozen** — MT5 equity unavailable (`runtime_truth.entries_frozen()`)
2. Sync MT5 account; infer regime from OHLCV
3. **LiveRiskTracker** sync; VOL loss-streak position cap (VOL signals only)
4. **Capital-adaptive tier gates** — confidence threshold, confluence, H1 alignment (tier profiles)
5. **`_live_gates()`** — structural live gates (see below)
6. **Tracker entry allowed** — daily trades, cooldown, daily loss %
7. **`risk_logic.can_trade()`** — limits object
8. **Meta-labeler** (PA signals only, when gating active)
9. Lot sizing — `_compute_lot()`, MICRO feasible planner
10. Return `RiskDecision(allowed=True, adjusted_lot=...)`

**Evidence:** `risk_gate.py::evaluate` (~L949–1185)

## _live_gates() Checks (PA path)

| Check | Function / source | Default PA M5 |
|-------|-------------------|---------------|
| Max positions total/symbol | `check_max_positions` | 3 / 2 |
| News blackout | `check_news_gate` | ON, 30 min |
| Friday no-entry | `check_friday_gate` | After hour 17 UTC |
| Spread | `check_spread_gate` | Max 15 pips effective for XAU |
| No opposite position | `check_no_opposite_position` | ON |
| HTF alignment | `check_htf_alignment` | **OFF** for M5 preset |
| Market filters | `check_market_filters` | Per preset (regime/ATR filters ON for M5) |

VOL signals skip HTF/market filter block early return at `_live_gates` end — **N/A on default PA-only path**.

**Evidence:** `risk_gate.py::_live_gates`

## Position Sizing

- Base: `RISK_PER_TRADE` (0.5% default) × equity / stop distance
- Tier profiles may override risk % and caps
- MICRO accounts: `evaluate_micro_feasible_risk()` may shrink lot/stop
- Output: `RiskDecision.adjusted_lot` applied in RiskStage

**Evidence:** `risk_gate.py::_compute_lot`, `_apply_micro_feasible_plan`

## Stop Loss / Take Profit

SL/TP set at **signal construction** in `signal_helpers.compute_sl_tp()` from PA preset — **not** recomputed inside RiskGate except tier adaptation via `_adapt_xauusd_stop_for_tier`.

## Meta-Labeler (PA Only)

| Field | Value |
|-------|-------|
| **File** | `tradingbot/services/meta_labeler.py` |
| **Trigger** | `_is_pa_signal(signal)` in RiskGate |
| **Gating** | Only when `should_gate(tf, regime)` — requires loaded model + live win rate threshold |
| **Threshold** | M5 preset `META_LABEL_THRESHOLD=0.38` (effective threshold may adapt) |
| **Observer mode** | `META_OBSERVER_MODE=true` → never rejects |

**Artifact status (2026-08-22 files audit):**

| Aspect | Status | Evidence |
|--------|--------|----------|
| Model artifacts | **VERIFIED FROM FILES** | `models/meta_labeler_m5.pkl`, `m15`, `h4`, `meta_labeler_info.json` (E025–E027) |
| Loadability | **VERIFIED FROM FILES** | Read-only load test: M5/M15/H4 loadable; `is_ready=True` |
| Historical decisions | **VERIFIED FROM FILES** | 4 records in `data/meta_decisions.jsonl` (E028) |
| Continuous live enforcement | **NOT PROVEN** | Last meta decision 2026-08-12; sample size tiny |

When models are not ready, `MetaLabeler.score()` returns `1.0` (fail-open for scoring) and `should_gate()` returns `False` (bypass gating) — source code behavior, not runtime proof of current path.

## LiveRiskTracker

**File:** `tradingbot/services/live_risk_tracker.py`

- Persists `data/live_risk_state.json` (gitignored)
- Per-TF cooldown bars, max trades/day, daily PnL tracking
- Used by RiskGate before approval

## Kill Switch (Separate from RiskGate)

**File:** `tradingbot/services/kill_switch.py`

| Field | Value |
|-------|-------|
| **Trigger** | Drawdown ≥ max_dd × buffer OR daily loss limit |
| **Action** | `kernel.emergency_stop()` + **close all positions** via MT5 |
| **Persistence** | Emergency stop state on disk |
| **Bypass RiskGate?** | YES — emergency flatten, not new entry |

Default max drawdown: 15% (`MAX_DRAWDOWN_PCT` / emergency conditions).

## Demo Account Guard (Startup, Not RiskGate)

Blocks live loop start on real accounts unless `TRADINGBOT_ALLOW_REAL=1`.

**Evidence:** `demo_account_guard.py`; `startup_validator.py`

## Backtest Risk

**`BacktestRiskGate`** — separate class, parity-oriented but not identical.

**Evidence:** `tradingbot/backtest/risk.py`

## Controls Existing but Not Enforced on Default PA Path

| Control | Status |
|---------|--------|
| TradeQualityEngine | **DISABLED** — VOL path; skipped when `VOL_REGIME_SKIP_TQ` |
| WPSQF filter | **DISABLED** default |
| ML AdaptiveRiskEngine | **NOT WIRED** — ML kernel off |
| Commented exposure limits in live.py | **DISABLED** |
| VOL-specific concurrent caps | **N/A** — PA signals |

## Unknowns

- Whether meta-labeler actively rejects on operator machine
- Live win rate feeding `should_gate()`

## Change Impact

`tradingbot/adapters/risk_gate.py`, `tradingbot/services/live_risk_tracker.py`, `tradingbot/services/kill_switch.py`, `tradingbot/services/meta_labeler.py`, PA presets

## Verification

Read `RiskStage.run` → `RiskGate.evaluate` full method; grep `check_` helpers in `domain/live_gates.py`.
