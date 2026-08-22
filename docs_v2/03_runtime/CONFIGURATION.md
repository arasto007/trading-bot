# Configuration

## Status

- **Status:** VERIFIED
- **Last Verified:** 2026-08-22
- **Verification Method:** Traced config loaders and env reads on live path
- **Verified against commit:** `57bf778c23cefffe508bb49079688b177796f67e`

## Scope

How configuration is **defined, merged, and consumed** — not operator-specific runtime values.

## Configuration Sources (Precedence)

Highest influence first for overlapping keys:

| Priority | Source | Notes |
|----------|--------|-------|
| 1 | CLI-implied env | `--execute`/`--paper` set `TRADINGBOT_*` in `LiveRunner.__init__` |
| 2 | Process environment | Includes `start/_load_env.bat` and daemon-set vars |
| 3 | `dotenv_loader` | Loads `.env` only for keys **not already** in `os.environ` |
| 4 | `get_live_config()` overlay | Merges `LIVE_TRADING_CONFIG` + prop preset |
| 5 | `load_legacy_config()` | `engine_settings` base + live overlay + `PRICE_ACTION_CONFIG` |
| 6 | Hardcoded defaults | In Python modules |

**Evidence:** `tradingbot/config/dotenv_loader.py`; `tradingbot/adapters/legacy_loader.py`; `tradingbot/application/live_runner.py`

`.env.example` and `config/live_runtime.env.example` are **not proof** of live values.

## Primary Config Loaders

| Function | File | Output |
|----------|------|--------|
| `load_dotenv()` | `tradingbot/config/dotenv_loader.py` | Populates env from `.env` |
| `get_live_config()` | `tradingbot/config/live.py` | Live trading dict |
| `load_legacy_config()` | `tradingbot/adapters/legacy_loader.py` | Merged runtime dict for adapters |
| `kernel_settings_from_legacy()` | `tradingbot/config/legacy_settings.py` | `KernelSettings` |

## Engine Selection Flags

| Key | Code default | Daemon default (if unset) | Consumer |
|-----|--------------|---------------------------|----------|
| `MULTI_ENGINE_ROUTER_ENABLED` | `true` | `true` | `factory.build_strategy_registry` |
| `USE_ML_KERNEL` | must be env-set for ML | `false` | `ml/integration/config.py` |
| `ADAPTIVE_REGIME_ENABLED` | **not in dict** → `.get()` false | `false` | `factory.py` |
| `VOL_REGIME_ENABLED` | `false` | `false` | `factory.py` |
| `PA_PRODUCTION_LOCK` | `true` | (not set by daemon) | `pa_production_lock.py` |
| `ENABLE_ML_SHADOW` | `false` in code | `true` | `shadow_strategy_registry` |

**Evidence:** `live.py`; `start_live_daemon.ps1`; `factory.py`

## Symbol and Timeframe

| Key | Default | Runtime effect |
|-----|---------|----------------|
| `PRIMARY_SYMBOL` | `XAUUSD_i` | Broker symbol for live MT5 |
| `TIMEFRAMES` in live dict | `['5m','15m','4h']` | Overridden to `['5m']` when router/adaptive/vol on |
| `LOOP_INTERVAL` | 30 | Kernel sleep seconds |

**Evidence:** `live.py:17,60,80,215–222`

## Risk-Related Keys (verified consumers)

| Key | Default | Read by |
|-----|---------|---------|
| `RISK_PER_TRADE` | 0.005 | `RiskGate` |
| `MAX_DAILY_RISK` | 0.04 | RiskGate, KillSwitch, tracker |
| `MAX_OPEN_POSITIONS_TOTAL` | 3 | RiskGate |
| `MAX_OPEN_POSITIONS_PER_SYMBOL` | 2 | RiskGate |
| `USE_NEWS_FILTER` | true | RiskGate |
| `NEWS_BLACKOUT_MINUTES` | 30 | RiskGate |
| `EMERGENCY_STOP_CONDITIONS.max_drawdown` | 0.15 | KillSwitch |
| PA preset `COOLDOWN_BARS` | 18 (M5) | LiveRiskTracker via RiskGate |
| PA preset `MAX_TRADES_PER_DAY` | 3 (M5) | LiveRiskTracker |

**Evidence:** `live.py`, `price_action.py`, `pa_symbol_tf_presets.py`, `risk_gate.py`

## Execution / Safety Env Vars

| Variable | Purpose | Evidence |
|----------|---------|----------|
| `TRADINGBOT_DRY_RUN` | Block broker orders | `execution_mode.py` |
| `TRADINGBOT_PAPER` | Paper simulation | same |
| `TRADINGBOT_ALLOW_REAL` | Allow non-demo account | `demo_account_guard.py` |
| `TRADINGBOT_SKIP_MT5_STARTUP` | Skip MT5 connect check | `live_runner.py` |
| `TRADINGBOT_SIGNAL_FILTER` | WPSQF ON/OFF | `signal_filter_mode.py` |
| `TRADINGBOT_REJECTION_LOG` | Rejection JSONL path | `rejection_events.py` |
| `DEMO_DISABLE_SESSION_FILTER` | Bypass PA session windows | `filter_policy.py` |
| `META_OBSERVER_MODE` | Meta logs but never rejects | `risk_gate.py` |

## MT5 Credentials

Required via environment: `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`.

**Evidence:** `live.py` docstring; `legacy_loader.py` MT5 override block

## Keys Present but Weak / No Live Consumer Found

| Key | Status |
|-----|--------|
| `SIGNAL_TIMEOUT` | CONFIGURED — consumer not traced on live path |
| `NIGHTLY_OPTIMIZATION` | CONFIGURED — no live scheduler traced |
| Commented exposure limits in `live.py` | DISABLED in config |
| `ADAPTIVE_QUALITY_ENGINE` default false | DISABLED unless env true |
| `VOL_DIRECTION_FILTER_ENABLED` default false | DISABLED |

## Conflicting Documentation

Legacy `docs/robot_behavior_audit/configuration_truth.md` claims `ADAPTIVE_REGIME_ENABLED` default true — **contradicted** by code (key absent from dict, daemon sets false). See KNOWN_ISSUES KI-001.

## Unknowns

- Operator `.env` file contents
- `TRADINGBOT_PROP_PRESET` if set

## Change Impact

`tradingbot/config/`, `tradingbot/adapters/legacy_loader.py`, `scripts/start_live_daemon.ps1`, `.env`

## Verification

Read `load_legacy_config()`, `get_live_config()`, grep env keys in `tradingbot/`.
