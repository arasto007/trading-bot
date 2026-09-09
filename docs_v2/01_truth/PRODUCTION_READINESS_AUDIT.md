# PRODUCTION READINESS AUDIT — FINAL REPORT

**Status:** RESEARCH / OFFLINE  
**Last verified:** 2026-09-02  
**Canonical-Entry:** false  
**Epistemic-Role:** DERIVED audit artifact. Not a competing SOT. Runtime facts remain CODE + owner docs.  
**Operator-effective state:** UNKNOWN  
**Artifact class:** RESEARCH-ONLY (static code inspection). Not CURRENT process state. Not broker economics.  
**Method:** CODE > CANONICAL DOCS > this artifact. `.env` not read. MT5/bot not started.

---

## 1. Executive Verdict

**BLOCKED**

Not ready for real-money preparation. Demo code path is internally more coherent than Real, but operator env, broker contract specs, round-trip costs, silent symbol fallback, and Real-name `order_value` cap are unresolved. This audit does **not** claim the robot is safe to trade.

## 2. What Actually Runs Live

Verified **code-defined** default Windows path (operator-effective process: UNKNOWN):

```text
start/START_BOT.bat
  → start/_load_env.bat          # loads .env into cmd; values UNKNOWN
  → scripts/start_bot.py         # load_dotenv fill-if-missing; refuses if --loop already running
  → scripts/start_live_daemon.ps1
       kills existing watchdog/--loop
       setdefault: USE_ML_KERNEL=false, ENABLE_ML_SHADOW=true,
                   MULTI_ENGINE_ROUTER_ENABLED=true,
                   ADAPTIVE_REGIME_ENABLED=false, VOL_REGIME_ENABLED=false
       Start-Process: run_live_watchdog.py --execute
  → scripts/run_live_watchdog.py
       child: python -m tradingbot --loop --execute
  → tradingbot/__main__.py
       run_live_loop(dry_run=False, paper=False, enable_recovery=True)
  → LiveRunner → TradingKernel pipeline
       Data → Indicators → Signal → SignalFilter → Risk → Execution
  → factory.build_strategy_registry → MultiEngineRouterRegistry
  → is_pa_production_lock → PA selected; VOL/Adaptive probed not selected
  → LegacyStrategyRegistry → PriceActionStrategy
  → evaluate_gold_setup → evaluate_m5_london_sweep → apply_setup_hardening
  → SignalStage: exclude_forming_bar
  → RiskGate.evaluate
  → Mt5ExecutionAdapter.execute → guarded_order_send → mt5.order_send
```

The documented path is **confirmed**. Extra verified hops: `_load_env.bat`, dotenv fill-if-missing, daemon kill-then-start, `--loop` enables PositionRecovery unless `--no-recovery`, HTF H4 fetch for bias map (not an entry TF).

## 3. Current Production Owner

| Item | Code-defined value | Evidence |
|------|--------------------|----------|
| Strategy | `priceaction` only | `tradingbot/config/strategies.py::ACTIVE_STRATEGIES` |
| Registry | `MultiEngineRouterRegistry` when router on and ML off | `factory.py::build_strategy_registry` |
| Evaluator | `evaluate_m5_london_sweep` | `GOLD_STRATEGY_MODE=london_sweep` + M5 |
| Preset | `gold_ny_sweep` | `PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"]` |
| Symbol (code default) | `XAUUSD_i` | `live.py::PRIMARY_SYMBOL` |
| TF | `["5m"]` when router/adaptive/vol on | `get_live_config()` |
| ML | off unless `USE_ML_KERNEL` explicit truthy | `is_ml_kernel_enabled` |
| v41 | inactive on this path; factor 1.0 if ML engine ≠ v40 | `engine_calibrator.py` |

## 4. Demo/Real Symbol Handling

**USER-PROVIDED BROKER FACT:**

| Account | Gold name |
|---------|-----------|
| DEMO | `XAUUSD_i` |
| REAL | `XAUUSD` |

The name difference is **expected**. It is **not** an automatic contradiction.

Economic/contract equivalence of `XAUUSD_i` vs `XAUUSD`: **UNKNOWN**.

Code facts:

- Live default is hardcoded `PRIMARY_SYMBOL = "XAUUSD_i"` — **not** env-switched.
- `normalize_symbol("XAUUSD_i")` strips `_I` → preset key `XAUUSD` (both names can share M5 `gold_ny_sweep`).
- CLI `--symbol` default `XAUUSD` is **not** used by the daemon.
- `resolve_broker_symbol` **auto-tries** original, then `+_i` or strip `_i`, via `symbol_info`. First visible tradable candidate wins. This is **account-dependent auto-detect**. See CX-017.
- Execution `check_order_risk` uses the **resolved broker name**. Exact `"XAUUSD_i"` uses `lot*price*100`. Bare `XAUUSD` uses `lot*price*100000`. See §8.

Do **not** replace `XAUUSD_i` with `XAUUSD`. Preferred later design: explicit `DEMO`/`REAL` config boundary, no silent `symbol_info` fallback, broker `symbol_info` for sizing — **not implemented in this phase**.

## 5. Production Architecture

```text
Mt5MarketDataAdapter.get_ohlcv (MT5 copy_rates; resolve_broker_symbol)
  → DataStage
  → TechnicalIndicatorEngine
  → SignalStage (exclude_forming_bar)
       MultiEngineRouterRegistry.generate_signal
         PA: LegacyStrategyRegistry → PriceActionStrategy
             → evaluate_gold_setup → evaluate_m5_london_sweep
             → apply_setup_hardening
         VOL + Adaptive: generated, not selected under lock
  → SignalFilterStage (WPSQF default off)
  → RiskStage → RiskGate.evaluate
  → ExecutionStage → Mt5ExecutionAdapter.execute
  → guarded_order_send → mt5.order_send (live --execute)
```

## 6. RiskGate Verdict

On the **kernel pipeline**, RiskGate is the final authority **before a new entry**. `TradingKernel` runs `RiskStage` then `ExecutionStage` in fixed order. Missing tick → `_live_spread_pips` returns **999.0** → spread gate can reject. **VERIFIED.**

Bypass candidates for **new entries** (not modified):

| Path | Class | Can place new live entry? |
|------|--------|---------------------------|
| Kernel RiskStage → ExecutionStage | PRODUCTION | Only if RiskGate allows |
| `Mt5PositionManager` trailing/partial/close | PRODUCTION PM | Existing positions only |
| `KillSwitchService` | PRODUCTION | Flatten/close |
| `PositionRecoveryService` | PRODUCTION; **ON** for `--loop` default | Recovery/emergency closes |
| `PositionProtector` | OFF unless `--protector` | N/A default |
| `research/orb_forward_demo.py` `mt5.order_send` | RESEARCH | Not imported by `build_kernel_live` |
| Stubs / paper / dry-run | not live send | Guarded |

VOL `_live_gates` early-return skips HTF/market filters; unused for **selected** live orders under PA lock.

Meta **can** reject PA if `should_gate()`; today **NOT PROVEN** (UNK-004). Observer mode never rejects.

## 7. Execution Verdict

**VERIFIED in code:**

- Modes: dry-run (`TRADINGBOT_DRY_RUN`) / paper (`TRADINGBOT_PAPER`) / live (`--execute` and not dry/paper).
- Daemon passes `--execute`. Operator dry-run/paper: **UNKNOWN**.
- Request: `TRADE_ACTION_DEAL`, volume, type, price, deviation **20**, magic **234000**, GTC, filling from `symbol_info.filling_mode`, optional SL/TP.
- Retry once on retcodes `{10004,10006,10007,10010,10021,10031}`; refresh price.
- Success: `TRADE_RETCODE_DONE` or `PLACED` (10009).
- AutoTrading check; `strict_account=True` on live execute; demo guard at startup unless `TRADINGBOT_ALLOW_REAL`.
- `DEMO_MODE=true` in config does **not** by itself block `--execute` (CX-005).

**NOT handled / UNKNOWN:**

- `volume_min` / `volume_max` / `volume_step` clamp (UNK-012)
- `stops_level` / `freeze_level` adjustment
- Partial fills as a first-class state (UNK-007)
- Requote beyond retry set; invalid stops as dedicated branch
- SL/TP **modification** failure after fill
- Idempotency of entry across watchdog restart (in-memory PA dedup lost)
- Commission in result handling

## 8. Position Sizing Verdict

**Risk percent:** `LIVE_TRADING_CONFIG['RISK_PER_TRADE'] = 0.005`. Printed as `* 100` → **0.5% of equity**, not 0.01% and not 0.01 as 1% on this live dict. `risk_logic.DEFAULT_RISK_PER_TRADE = 0.02` is fallback if config missing.

> **Superseded (Phase 26N, 2026-09-05):** At audit time (2026-09-02) this report stated `BacktestConfig.risk_per_trade=0.01` (1%) vs live 0.5%. **Current code (Phase 25B):** `BacktestConfig.risk_per_trade = 0.005` — aligned with live. See `CONFIGURATION_TRUTH.md` row `BacktestConfig.risk_per_trade`. Historical pre-25B mismatch preserved above for audit traceability.

**Live lot (gold with SL):** `lot_from_stop_distance`:

`lot = (equity * risk_per_trade) / (|entry-SL| * contract_size(symbol))`

`contract_size`: any symbol containing `XAU` or `GOLD` → **100.0** (comment: 1 lot ≈ 100 oz). Same formula for `XAUUSD` and `XAUUSD_i`.

**Order notional cap** (`order_logic.order_value` then `MAX_ORDER_VALUE=100_000`):

| Symbol string | Formula | lot=0.01, price=2650 |
|---------------|---------|----------------------|
| exact `XAUUSD_i` | `lot * price * 100` | $2,650 — under cap |
| `XAUUSD` (and most others) | `lot * price * 100000` | $2,650,000 — **rejected** |

The ~**1000×** gap is real in code. It is **not** proven to be a broker contract fact. For Demo `XAUUSD_i`, sizing (`*100`) and notional check (`*100`) agree. For Real name `XAUUSD`, sizing still uses gold `contract_size=100` but the **cap uses forex-scale `*100000`**, so typical gold market orders fail `check_order_risk` after resolve. Broker tick_value: **UNKNOWN**.

## 9. SL/TP Verdict

Preset `MIN_RR` / `TP_RR` = **1.5**, not 1:2.

- SL: sweep extreme ± `SL_ATR_MULT` **0.35** ATR  
- TP: `max(other Asian bound distance, 1.5R)`  
- CHoCH continuation **off** (`ENABLE_CHOCH_CONTINUATION=False`)  
- Rejection candle **off** (`M5_REQUIRE_REJECTION=False`)  
- Quality ≥ **55** (`MIN_QUALITY_SCORE` via `apply_setup_hardening`)  
- Cooldown **18** bars  

1:2 is **not** guaranteed. Broker min-distance/stops_level: **UNKNOWN**. Spread is **not** added into SL/TP in the evaluator.

## 10. Session Verdict

- Mode **name:** `london_sweep` (CX-001)  
- **Active window:** NY **15 ≤ hour < 16**, London **off** (`M5_USE_NY_SESSION=True`, `M5_USE_LONDON_SESSION=False`)  
- Hour source: bar index `.hour` after `pd.to_datetime(..., utc=True)` plus optional broker-skew shift (`detect_mt5_utc_offset_seconds`). Offline offset: **UNKNOWN**  
- Env/CLI do not define NY hours; preset keys do. `.env` can still change flags that **defeat the lock** (CX-007), not the hour numbers themselves unless operator edits presets.

## 11. Data Verdict

| TF | Live entry loop | Other live use |
|----|-----------------|----------------|
| M5 | **Yes** (forced when router on) | Signal + session |
| M15 | **Not** iterated as entry TF | Preset exists; unused on default loop |
| H4 | **Not** entry TF | Fetched for `htf_timeframe_for(M5)→H4` bias map; M5 `REQUIRE_HTF_ALIGNMENT_M5=False` so bias does not gate |
| M1 | **No** live | ~~Backtest default~~ **Superseded:** was M1 at audit time; **current** `BacktestConfig.timeframe` = **M5** (Phase 25B) |
| Ticks | **Not** for signals | `symbol_info_tick` for spread / price |

Forming bar dropped: `exclude_forming_bar` → `iloc[:-1]`. Source: MT5 `copy_rates_from_pos`. Claim “H4=bias, M15=context, M5=entry” is **PARTIAL**: H4 bias is computed; M15 is not a live context loop; M5 alignment to H4 is **not required**.

## 12. Cost Verdict

| | |
|--|--|
| **MODELED live** | Tick spread at RiskGate (pips vs max, gold floor 15 pips); deviation 20 points on send; slippage logged after fill |
| **NOT MODELED live** | Commission, swap, spread widening as cost, partial-fill economics, latency as PnL |
| **UNKNOWN** | Actual spread, commission, swap, tick value, contract size from broker (UNK-002, UNK-003) |
| **Research** | Uncosted PA replay; dataset `spread_pips` often OHLC proxy (CX-010) |

Do not invent broker costs.

## 13. Backtest ↔ Live Parity

| Item | Live | Backtest/research | Class |
|------|------|-------------------|--------|
| Symbol | `XAUUSD_i` default | typically `XAUUSD` / CLI default `XAUUSD` | CRITICAL (economics UNKNOWN) |
| TF | M5 | `BacktestConfig.timeframe` default **M5** (Phase 25B; was **M1** at 2026-09-02 audit) | ~~CRITICAL~~ **RESOLVED** (TF parity) |
| Forming bar | drop last | historical closed | SAFE if backtest is closed-only |
| Session | NY 15–16 UTC (if TZ correct) | index hours | MATERIAL if TZ wrong |
| Spread | live tick | often 0 or OHLC proxy | CRITICAL for expectancy |
| Costs | unmodeled | uncosted PA class B | CRITICAL |
| SL/TP | 0.35 ATR / 1.5R | same if same preset | SAFE if preset forced |
| Sizing | 0.5% live dict | 0.5% backtest default (`0.005`; Phase 25B; was 1% at audit) | ~~MATERIAL~~ **RESOLVED** (risk parity) |
| RiskGate | full MT5 hops | BacktestRiskGate subset | MATERIAL |
| Execution | MT5 market | bar/sim fill | CRITICAL |

## 14. Configuration Precedence

Approximate live order (fill-if-missing, not overwrite of existing process env):

1. Already-set process environment (including `_load_env.bat` / `load_dotenv` if key absent)  
2. Daemon setdefault only if unset (ML/router/Adaptive/VOL/shadow/meta threshold)  
3. `LIVE_TRADING_CONFIG` + `os.getenv` inside `live.py` (e.g. `PA_PRODUCTION_LOCK` default true)  
4. `get_live_config()` forces `TIMEFRAMES=["5m"]` when router/adaptive/vol on  
5. `PA_SYMBOL_TF_PRESETS` overlay via `get_price_action_config` / `normalize_symbol`  
6. CLI: daemon **does not** pass `--symbol`/`--tf`; `--execute` **is** passed; `--loop` default **enables recovery**  
7. Hardcoded: `PRIMARY_SYMBOL`, magic, deviation, `order_value` branches  

Dangerous ambiguities: `.env` can enable Adaptive/VOL and **defeat** PA lock (CX-007); `USE_ML_KERNEL=true` can select ML if live gate allows; `TRADINGBOT_ALLOW_REAL` disables demo abort; `DEMO_MODE` vs `--execute` (CX-005). Operator values: **UNKNOWN**.

## 15. Watchdog / Operational Safety

**VERIFIED:**

- `start_bot.py` skips start if `tradingbot --loop` already running.  
- `start_live_daemon.ps1` **kills** existing watchdog/`--loop` then starts one watchdog.  
- Watchdog restarts child after crash; exit 2 (kill switch) waits 4h; rapid-restart cap 8 / 300s window; stall poll.  
- Manual stop flag stops watchdog on clean 0.  

**GAPS / UNKNOWN:**

- Restart **does** blindly re-enter after crash delay — duplicate orders if broker position exists and in-memory dedup is gone.  
- Two instances: BAT path guarded; running `python -m tradingbot --loop` **besides** watchdog is possible if started another way.  
- Order idempotency: **not guaranteed**.  
- Current daemon PID: UNKNOWN (not probed).

## 16. ML Safety Boundary

| Item | Default live | Hidden activation |
|------|----------------|-------------------|
| `USE_ML_KERNEL` | daemon `"false"`; code requires explicit env truthy | `.env` / process `true`/`1` — then factory may take ML if live gate allows |
| v41 | inactive; class C; factor **1.0** when engine ≠ `trend_rf_v40` | only if ML kernel actually selected |
| Adaptive selected | daemon false; factory `.get(..., False)` | env true **and** router off or lock defeated |
| Adaptive probe `_enabled` | class default `get(..., True)` if key missing | CX-014 / UNK-009 |
| VOL selected | daemon false | same as Adaptive |
| Shadow wrap | daemon true if unset | log-only wrap |
| Artifacts | v41 bundle present as research | must not be live-selected |

Do not activate. This audit did not.

## 17. P0 Blockers

| ID | BLOCKER | EVIDENCE | STATUS | REQUIRED ACTION |
|----|---------|----------|--------|-----------------|
| P0-001 | Operator-effective `.env` | dotenv fill-if-missing; not read | OPEN | Sanitized flag dump (no secrets) |
| P0-002 | Demo/Real contract economics | no `symbol_info` tape | OPEN | Operator MT5 specs both symbols |
| P0-003 | Round-trip costs | empty class-A tape; live unmodeled | OPEN | Tickets + bid/ask/commission |
| P0-004 | Real-name `order_value` vs gold `contract_size` | `order_logic.py::order_value` vs `position_logic.contract_size` | OPEN | Do not switch to `XAUUSD` until redesigned; do not “fix” in this phase |
| P0-005 | Execution volume/stops/partials | `mt5_execution.py` uses filling_mode only | OPEN | Broker spec + later design |
| P0-006 | Silent symbol resolve | `symbols.py::resolve_broker_symbol` | OPEN | Explicit DEMO/REAL map; disable auto `_i` hunt |

## 18. P1 Items

| ID | ITEM | EVIDENCE | STATUS | REQUIRED ACTION |
|----|------|----------|--------|-----------------|
| P1-001 | Session TZ vs UTC | skew detector exists; offset UNKNOWN offline | OPEN | Confirm hours after offset on live bars |
| P1-002 | Config can defeat PA lock | `is_pa_production_lock` | CX-007 | Sanitized Adaptive/VOL flags |
| P1-003 | Meta `should_gate` today | hop 12 | UNK-004 | Journal if bot already running (do not start) |
| P1-004 | News calendar | `USE_NEWS_FILTER` default true | UNK-006 | Inspect store later |
| P1-005 | Credential fallbacks in `engine_settings.py` | CX-016 | OPEN | Confirm env overrides; never commit secrets |
| P1-006 | Adaptive probe enablement | CX-014 | UNK-009 | Leave Adaptive off |
| P1-007 | Watchdog restart vs duplicate entry | in-memory dedup | OPEN | Design idempotency later |
| P1-008 | `--loop` recovery ON | `__main__.py` `enable_recovery=not args.no_recovery` | OPEN | Know PM can `guarded_order_send` |
| P1-009 | Backtest M1 / 1% / uncosted | CX-002 | **PARTIALLY RESOLVED** (Phase 25B: TF M5 + risk 0.005 aligned; costs still uncosted) | Do not size from uncosted backtest |

## 19. P2 Items

| ID | ITEM | EVIDENCE | STATUS | REQUIRED ACTION |
|----|------|----------|--------|-----------------|
| P2-001 | Complete call graph | UNK-011 | OPEN | Optional static |
| P2-002 | `london_sweep` name | CX-001 | DOCUMENTED | Optional rename later |
| P2-003 | CLI `--tf M15` / `--symbol XAUUSD` | CX-015 | DOCUMENTED | Daemon ignores |
| P2-004 | Historical `docs/` Adaptive-as-default | CX-004 | DOCUMENTED | Ignore for live |
| P2-005 | H4 bias unused as M5 gate | `REQUIRE_HTF_ALIGNMENT_M5=False` | DOCUMENTED | Product decision |

## 20. Contradictions

Preserve CX-001 through CX-016. **New:**

### CX-017 silent broker-symbol fallback vs explicit DEMO/REAL names

| Field | Value |
|-------|--------|
| Source A | USER-PROVIDED mapping Demo=`XAUUSD_i`, Real=`XAUUSD`; live default hardcoded `_i` |
| Source B | `resolve_broker_symbol` tries `symbol`, then `+_i` or strip `_i`, via `symbol_info` |
| Severity | P0 if Real terminal / both names visible / switch without config |
| Authoritative | Code fallback is real; it is **not** an approved account-type detector |
| Status | OPEN |

## 21. Unknowns

UNK-001–011 unchanged. **New:**

| ID | Pri | What | Why | Evidence to resolve | MT5? |
|----|-----|------|-----|---------------------|------|
| UNK-012 | P0 | volume min/max/step, stops_level, freeze_level at send | `symbol_info` not used for those fields in `_place_market_order` | broker spec + later code audit against `symbol_info` fields | Yes |
| UNK-013 | P1 | Effective session hour after broker TZ correction | detector exists; not observed this batch | live bar timestamps vs UTC (operator) | Yes |

## 22. Required Human/Broker Evidence

**Do not provide credentials or `.env` contents.**

Fillable templates, P0 closure criteria, and the evidence matrix live in:

`docs_v2/01_truth/OPERATOR_BROKER_EVIDENCE_COLLECTION.md`

That file is OWNER of templates only. Values remain **NOT COLLECTED** until the operator returns sanitized sheets. Cursor must not read `.env`, start MT5, or place orders.

Never: password, API key, `.env` file, login, server password, account number.

## 23. Recommended Next Phase

Operator fills `OPERATOR_BROKER_EVIDENCE_COLLECTION.md` (OPERATOR ACTION REQUIRED). Design review without numbers: `DEMO_REAL_SYMBOL_COST_DESIGN.md` (EV-EQ-01 INSUFFICIENT EVIDENCE). Next gate remains evidence collection, then authorized implementation review — still no production implementation, no MT5 from Cursor, no `XAUUSD_i` → `XAUUSD` swap, no Real trading.

## 24. Files Inspected

`start/START_BOT.bat`, `start/_load_env.bat`, `scripts/start_bot.py`, `scripts/start_live_daemon.ps1`, `scripts/run_live_watchdog.py`, `tradingbot/__main__.py`, `tradingbot/application/live_runner.py`, `tradingbot/application/bootstrap.py`, `tradingbot/ml/integration/factory.py`, `tradingbot/ml/integration/config.py`, `tradingbot/services/pa_production_lock.py`, `tradingbot/adapters/multi_engine_router.py`, `tradingbot/domain/gold_strategies/router.py`, `tradingbot/domain/gold_strategies/m5_london_sweep.py`, `tradingbot/domain/pa_hardening.py`, `tradingbot/domain/ohlcv.py`, `tradingbot/domain/order_logic.py`, `tradingbot/domain/position_logic.py`, `tradingbot/domain/risk_logic.py`, `tradingbot/adapters/risk_gate.py`, `tradingbot/adapters/mt5_execution.py`, `tradingbot/adapters/symbols.py`, `tradingbot/adapters/mt5_market_data.py`, `tradingbot/adapters/legacy_loader.py`, `tradingbot/pipeline/*`, `tradingbot/kernel/trading_kernel.py`, `tradingbot/config/live.py`, `tradingbot/config/pa_symbol_tf_presets.py`, `tradingbot/config/strategies.py`, `tradingbot/config/dotenv_loader.py`, `tradingbot/config/engine_settings.py` (structure only; secret fallback **values not copied**), `tradingbot/services/execution_mode.py`, `tradingbot/services/demo_account_guard.py`, `tradingbot/services/startup_validator.py`, `tradingbot/services/mt5_order_guard.py`, `tradingbot/ml/confidence_engine/engine_calibrator.py`, canonical `docs_v2` load-path owners listed in the prompt.

## 25. Files Modified

Documentation-only (this audit): this file; `KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md`; `DATA_CONTRACTS.md`; `PROJECT_SOURCE_OF_TRUTH.md` nav row; `DOCUMENT_OWNERSHIP_MATRIX.md` supporting line; `data/ml/reports/production_readiness_audit/audit.json`.

## 26. Production Code Modified?

**NO**

## 27. MT5 Started?

**NO**

## 28. Bot Started?

**NO**

## 29. Orders Sent?

**NO**

## 30. ML Activated?

**NO**

## 31. Git State

No commit / reset / stash / clean. Working tree remains dirty from prior work plus these documentation/report files.

---

## Most important question

**Is the robot currently safe and sufficiently evidenced to move toward real-money preparation?**

**NO**

Why: operator `.env` unknown; Demo/Real **economics** unknown; costs unknown; Real symbol name would hit a **1000×** `order_value` cap vs gold `contract_size`; `resolve_broker_symbol` can silently switch `_i` ↔ bare name; execution does not apply broker volume/stops constraints; PA edge remains uncosted class B. Code inspection cannot authorize real money.
