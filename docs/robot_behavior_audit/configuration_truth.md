# Configuration Truth

**Repository:** `TradingBot new`  
**Sources:** `tradingbot/config/live.py`, `.env.example`, `tradingbot/ml/integration/config.py`, runtime env reads

**Current detected values:** Based on code **defaults** and `.env.example`. User's actual `.env` file was **NOT PROVEN** readable in this audit (may contain secrets). Where unknown, marked **NOT PROVEN**.

**Restart required:** Any env var read at process start requires bot restart. `live.py` env reads occur at import/`get_live_config()` — **restart required** for changes unless noted.

---

## Critical Engine Flags

| Flag | Default | Current detected | Read in | ON behavior | OFF behavior | Restart? |
|------|---------|------------------|---------|-------------|--------------|----------|
| `USE_ML_KERNEL` | false (`.env.example`) | false (example + daemon default) | `ml/integration/config.py` → `is_ml_kernel_enabled()` | ML kernel registry, full ML stack | Adaptive or VOL or legacy path | **YES** |
| `ADAPTIVE_REGIME_ENABLED` | **true** (`live.py` L102) | true (default + daemon) | `live.py`, `factory.py` | `AdaptiveRegimeStrategyRegistry` | Falls through to VOL_REGIME | **YES** |
| `ADAPTIVE_CONFLUENCE_ONLY` | **true** (`live.py` L104) | true (default) | `adaptive_regime.py` → `_confluence_only()` | MTF+VOL must agree; limited high-vol path | All sub-strategies per regime | **YES** |
| `VOL_REGIME_ENABLED` | **true** (`live.py` L105) | true but **shadowed** if adaptive on | `factory.py` | Standalone VOL registry when adaptive off | N/A if adaptive on | **YES** |
| `VOL_REGIME_SKIP_TQ` | **true** (`live.py` L108) | true (default) | `vol_regime_strategy_registry.py` | Skip TradeQuality filter | TQ can block (spread_proxy risk) | **YES** |
| `ALLOW_LEGACY_FALLBACK` | false | NOT PROVEN | `ml/integration/config.py` L37 | ML failures fall back to PA | ML failures → HOLD | **YES** |
| `TRADINGBOT_PAPER` | unset | unset (live uses `--execute`) | `execution_mode.py` | Simulated fills in paper_trades table | Real MT5 orders | **YES** |
| `TRADINGBOT_DRY_RUN` | unset | unset with `--execute` | `execution_mode.py` | Log only, no broker | Normal execution | **YES** |

---

## Signal Filter Flags

| Flag | Default | Detected | Read in | ON | OFF | Restart? |
|------|---------|----------|---------|-----|-----|----------|
| `TRADINGBOT_SIGNAL_FILTER` | **OFF** | OFF (unset) | `signal_filter_mode.py` L24 | WPSQF active | Pass-through | **YES** |
| `TRADINGBOT_WPSQF_THRESHOLD` | 77.56 | 77.56 | `signal_filter_mode.py` L35 | Min score to pass WPSQF | N/A | **YES** |

---

## Exit / Position Mode

| Flag | Default | Detected | Read in | ON | OFF | Restart? |
|------|---------|----------|---------|-----|-----|----------|
| `TRADINGBOT_EXIT_MODE` | NOT PROVEN in codebase grep | NOT PROVEN | — | — | — | — |

**Note:** No `TRADINGBOT_EXIT_MODE` reference found in audited files — flag may not exist or uses different name. **NOT PROVEN**.

Position management controlled by:
- `EOD_CLOSE_ENABLED=true` (`live.py` L70)
- `FRIDAY_CLOSE_ENABLED` in PRICE_ACTION presets
- `Mt5PositionManager` constructor flags

---

## Risk / Cooldown / Spread

| Flag / Config key | Default | Detected | Read in | Effect | Restart? |
|-------------------|---------|----------|---------|--------|----------|
| `RISK_PER_TRADE` | 0.005 (0.5%) | 0.005 | `live.py`, `risk_gate.py` | Lot sizing from equity | **YES** |
| `VOL_REGIME_RISK_PER_TRADE_PCT` | 0.5 | 0.5 | `live.py`, adaptive registry metadata | Display/logging; **not wired to lot** | **YES** |
| `VOL_REGIME_MAX_LOT` | 0.01 | 0.01 | `live.py` | NOT PROVEN enforced in RiskGate max | **YES** |
| `VOL_REGIME_COOLDOWN_BARS` | **12** | 12 | `live.py`, `risk_gate.py` | ~60 min between trades on M5 | **YES** |
| `VOL_REGIME_MAX_TRADES_PER_DAY` | **3** | 3 | `live.py`, `live_risk_tracker.py` | Daily entry cap | **YES** |
| `VOL_REGIME_MAX_CONCURRENT` | **1** | 1 | `risk_gate.py` L107 | Max 1 open for adaptive/vol signals | **YES** |
| `MAX_DAILY_RISK` | 0.04 | 0.04 | `live.py`, kill switch, risk_logic | 4% daily loss halt | **YES** |
| `MAX_SPREAD_PIPS` (PA) | 5.0 | **15 floor for XAU** | `risk_gate.py` L95–100 | Blocks entry if spread too wide | **YES** |
| `USE_NEWS_FILTER` | true | true | `live.py`, `risk_gate.py` | 30 min blackout around news | **YES** |
| `NEWS_BLACKOUT_MINUTES` | 30 | 30 | same | News window | **YES** |
| `FRIDAY_NO_ENTRY_AFTER_HOUR` | 17 | 17 | PRICE_ACTION / `live_gates.py` | No new entries | **YES** |
| `EMERGENCY_STOP_CONDITIONS.max_drawdown` | 0.15 | 0.15 | `live.py` L119 | Kill switch at 15% DD | **YES** |

---

## MT5 / Safety

| Flag | Default | Detected | Read in | Effect | Restart? |
|------|---------|----------|---------|--------|----------|
| `MT5_LOGIN/PASSWORD/SERVER` | required | NOT PROVEN | `live.py`, MT5 adapters | Connection | **YES** |
| `TRADINGBOT_ALLOW_REAL` | unset (block real) | NOT PROVEN | `demo_account_guard.py` | Allows non-demo accounts | **YES** |
| `TRADINGBOT_SKIP_MT5_STARTUP` | unset | NOT PROVEN | `live_runner.py` | Skip connect check | **YES** |
| `TRADINGBOT_PROP_PRESET` | unset | NOT PROVEN | `prop_presets.py` | FTMO-style risk overrides | **YES** |

---

## ML / Phase22C (Inactive When ML Off)

| Flag | Default (.env.example) | Affects live now? | Read in |
|------|------------------------|-------------------|---------|
| `PHASE22C_ENABLED` | true | **NO** | `phase22c/config.py` |
| `PHASE22C_DECISION_MIN_CONFIDENCE` | 0.48 | **NO** | ML policy |
| `PHASE22C_QUALITY_THRESHOLD` | 0.52 | **NO** | TradeQualityEngine |
| `ENABLE_RSI_FILTER` | true | **NO** (adaptive path) | `phase19c/filters.py` |
| `ENABLE_ADX_FILTER` | true | **NO** (adaptive path) | same |
| `TREND_MODEL_VERSION` | v41 | **NO** | `phase17d/versioning.py` |

---

## Loop / Timing

| Config | Default | Read in | Effect | Restart? |
|--------|---------|---------|--------|----------|
| `LOOP_INTERVAL` | 30 seconds | `live.py` L75 → KernelSettings | Time between global cycles | **YES** |
| `HEALTH_MAX_TICK_AGE_SEC` | 120 | `trading_kernel.py` L80 | Skip cycle if ticks stale | **YES** |
| `WATCHDOG_RESTART_DELAY_SEC` | 300 | `run_live_watchdog.py` | Delay before bot restart | Watchdog restart |

---

## Hardcoded Live Overrides (Not Env)

| Override | Where | Effect |
|----------|-------|--------|
| Symbols → XAUUSD only | `get_live_config()` L190–192 | When adaptive or vol on |
| Timeframes → 5m only | same | Single market bot |
| Daemon sets USE_ML_KERNEL=false | `start_live_daemon.ps1` | Unless already in env |
| Daemon sets ADAPTIVE_REGIME_ENABLED=true | same | Unless already in env |

---

## Config That Appears in live.py But Does Nothing

| Key | Evidence |
|-----|----------|
| `SIGNAL_TIMEOUT` | Zero references outside live.py |
| `NIGHTLY_OPTIMIZATION` | Zero references |
| `ADAPTIVE_OPTIMIZATION` | Zero references |
| `TIMEFRAME_CONFIGS` | No consumer in live chain |
| `MIN_CONFIDENCE` | Bypassed by fixed 0.60 rule confidence |

See `dead_features.md` for full list.

---

## How to Verify Current Runtime Values

1. Check `.env` in project root (NOT PROVEN in audit).
2. Read watchdog log at startup — `startup_diagnostics.log_engine_selection()`.
3. Query `data/trade_journal.db` → `cycle_events` for recent behavior.
4. Inspect `logs/watchdog_stderr_*.log` for `AdaptiveRegimeStrategyRegistry active` line.

**NOT PROVEN:** Live log files not accessed in this audit session.
