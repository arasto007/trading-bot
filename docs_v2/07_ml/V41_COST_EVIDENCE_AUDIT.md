# V41 Cost Evidence Audit (Phases 1.5.46–1.5.47)

**Status:** RESEARCH / OFFLINE  
**Last verified:** 2026-08-31  
**Live impact:** none  
**Real-world full cost tape:** **UNKNOWN**  
**Tiny measured sample:** 17 live **entry** slippage rows in `data/trade_journal.db` — **INSUFFICIENT** for a v41 cost model  
**Classification (with 1.5.48–50):** **C — insufficient evidence**  
**v41 production factor:** remains **neutral 1.0**

No costs were fabricated. No random spread distribution was created. Prior research JSON was not rewritten.

---

## Measured vs assumed vs unknown

| Kind | What |
|------|------|
| **Measured** | 17 `mode=live` journal fills with `slippage_pips = abs(fill−requested)/pip_size`; OHLC candles exist |
| **Repository assumptions** | PaperBroker 0.30/0.10, BacktestConfig 2.5/0.8 pips, `execution_costs.py` multipliers, paper_trades spread always 0.30 |
| **Sensitivity** | Constant R deducted from the frozen v41 OOS book (see `V41_ROBUSTNESS_EVIDENCE.md`) |
| **Unknown** | Historical bid/ask tape, round-trip live cost, commission, XAUUSD_i vs XAUUSD fill identity, tick path |

---

## Phase 1.5.46 — real cost data availability

Searched: `data/ml/raw/{spread,ticks,sessions,events,news}`, `data/ml/live/*.jsonl`, `data/trade_journal.db`, `data/trading_bot.db`, `data/position_state.db`, `data/backtest`, phase26c journals, filenames matching spread/tick/fill/slippage/commission.

| Source | Present? | Real broker cost? | Why not a v41 tape |
|--------|----------|-------------------|--------------------|
| `data/ml/raw/spread/` | dir, **0 files** | no | nothing to read |
| `data/ml/raw/ticks/` | dir, **0 files** | no | nothing to read |
| sessions/events/news raw | **0 files** | no | empty |
| `data/ml/live/decisions.jsonl` (~578 MB) | yes | no | keys: engine/regime/confidence — **no spread/bid/ask/slippage** |
| `kernel_decisions.jsonl` | yes | no | same |
| Paper `executions` n=5407 | yes | no | `slippage_pips` **always 0.0** |
| Paper `paper_trades` n=5352 | yes | no | spread **always 0.30**, commission **0**, engine **phase9_9** only |
| Phase26c journal “live” n=100 | yes | no | message `paper — simulated fill (sl_tp_midpoint)` |
| Live journal fills n=**17** | yes | **partial** | entry slip only; not round-trip; not TREND-v41 book; n<30 |
| MT5 `.hst` / tick export | **not in repo** | n/a | would require starting MT5 — forbidden |
| `data/backtest` | 21 cache files | no | strategy backtest cache, not a bid/ask tape |

**Why a full tape cannot be obtained from the repository:** the raw spread/tick stores were never populated; live kernel logs do not record bid/ask; paper rows hard-code 0.30/0 slip; the only live fills are 17 PA-path entries. Reconstructing a 3,409-trade OOS cost series from 17 points would be fabrication. That was **not** done.

### The 17 live fills (measured, not a model)

Source: `data/trade_journal.db` `executions` where `mode='live'`. Formula in `tradingbot/adapters/mt5_execution.py`: `slip_pips = abs(fill_price - price) / pip_size(symbol)` with `pip_size` = **0.1** for XAU*. Journal `symbol` column is `XAUUSD`; live primary is `XAUUSD_i`.

| ts (UTC) | requested | fill | slip pips | slip points (×0.1) |
|----------|-----------|------|-----------|---------------------|
| 2026-06-10 12:50 | 4157.21 | 4157.37 | 1.6 | 0.16 |
| 2026-06-11 09:19 | 4087.16 | 4087.16 | 0.0 | 0.00 |
| 2026-06-11 09:20 | 4085.55 | 4085.51 | 0.4 | 0.04 |
| 2026-06-11 13:30 | 4075.29 | 4075.29 | 0.0 | 0.00 |
| 2026-06-11 14:15 | 4065.85 | 4065.91 | 0.6 | 0.06 |
| 2026-06-11 14:45 | 4076.90 | 4076.78 | 1.2 | 0.12 |
| 2026-06-11 16:00 | 4090.06 | 4090.07 | 0.1 | 0.01 |
| 2026-06-11 16:30 | 4079.59 | 4079.56 | 0.3 | 0.03 |
| 2026-06-12 12:15 | 4214.56 | 4214.52 | 0.4 | 0.04 |
| 2026-06-15 11:50 | 4334.95 | 4334.95 | 0.0 | 0.00 |
| 2026-06-19 11:10 | 4146.63 | 4146.63 | 0.0 | 0.00 |
| 2026-06-19 12:48 | 4150.45 | 4148.33 | **21.2** | 2.12 |
| 2026-07-20 16:25 | 4011.92 | 4011.92 | 0.0 | 0.00 |
| 2026-07-29 18:56 | 4102.87 | 4102.77 | 1.0 | 0.10 |
| 2026-07-29 19:26 | 4082.43 | 4083.64 | **12.1** | 1.21 |
| 2026-08-07 10:15 | 4308.49 | 4308.49 | 0.0 | 0.00 |
| 2026-08-12 10:41 | 4413.64 | 4414.32 | 6.8 | 0.68 |

Sample mean **2.69 pips ≈ 0.27 points** entry-only. Two outliers (21.2, 12.1) dominate the mean. **INSUFFICIENT EVIDENCE — NOT PROVEN** that this mean applies to v41 TREND OOS. Not used as a cost model. Not bootstrapped.

Break-even of the v41 OOS book is **~0.15 points** at median ATR 4.50. Even this tiny live sample’s mean already exceeds that — but n=17 forbids treating that as proof.

---

## Phase 1.5.47 — cost mechanism audit

Production behavior was not changed.

| Mechanism | File | Parameter | Empirical? | Legs | Suitable for v41 evidence? | Can change PF/exp? |
|-----------|------|-----------|------------|------|----------------------------|---------------------|
| PaperBroker | `tradingbot/ml/paper_trading/paper_broker.py` | `spread_points=0.30`, `slippage_points=0.10`, `commission=0.0` | **assumed** | **entry-only** in `execute_entry` (half-spread+slip) | no — not measured; RANGE paper_trades use it | **yes** (0.25 pt ≈ 0.056 R at ATR 4.5 > 0.033 edge) |
| paper_trades DB | `data/trade_journal.db` | spread always 0.30 | copied default | n/a | no — phase9_9 paper | would if treated as real (must not) |
| BacktestConfig | `tradingbot/backtest/config.py` | `spread_pips=2.5`, `slippage_pips=0.8`, `commission_per_lot=0.0` | **assumed** | entry half-spread+slip in `SimulatedBroker`; session multipliers | no — heuristic | **yes** (~0.41 pt round-trip if both legs+2×slip) |
| `variable_spread_pips` | `tradingbot/domain/session_logic.py` | 1.0–1.6 × base by hour | **assumed** | n/a | no | yes if applied |
| `execution_costs.py` | `tradingbot/execution/execution_costs.py` | `base_spread_points` × session/vol/news; `apply_side_price` half-spread+slip | **assumed** (needs `ctx.spread_points`) | entry-side in `apply_side_price` | no — simulator | yes |
| Phase 6A stress | `phase6a/vol_v2_expansion.py` | `BASE_SPREAD_PIPS=4.0`; `(2s+2slip)/stop` | **assumed** | modeled round-trip | no — VOL-v2 | yes |
| Phase 19A random 0–0.15 R | `phase19a/robustness.py` | uniform RNG | **fabricated** | n/a | **no (class D)** | yes, invalidly |
| Live MT5 slip log | `mt5_execution.py` | measured `abs(fill−req)/pip` | **empirical n=17** | **entry-only** | not for 3409-trade model | unknown |
| RiskGate `tick_value` | `adapters/risk_gate.py` | `info.trade_tick_value` | live MT5 | n/a | **no** (would start MT5) | n/a offline |
| `pip_size` / `contract_size` | `domain/position_logic.py` | XAU pip=0.1, contract=100 | heuristic | n/a | unit conversion only | converts points↔R |
| `order_value` | `domain/order_logic.py` | `XAUUSD_i`: lot×price×100 | heuristic | n/a | not a spread | no |

### XAUUSD vs XAUUSD_i

| Item | Value |
|------|-------|
| Live `PRIMARY_SYMBOL` | `XAUUSD_i` (`tradingbot/config/live.py`) |
| Isolated v41 research candles | `XAUUSD` M5 parquet |
| Journal live `symbol` column | `XAUUSD` |
| `pip_size` | `"XAU" in symbol` → 0.1 for both |
| `order_value` | special-cases **only** `XAUUSD_i` |

**INSUFFICIENT EVIDENCE — NOT PROVEN** that research `XAUUSD` bars and live `XAUUSD_i` fills share the same spread. They were not merged.

Commission: paper and backtest defaults are **0.0**. Live commission is **UNKNOWN**.

---

## Conclusions (cost audit)

1. There is **no** reusable historical bid/ask tape in the repo.  
2. There **is** a 17-row live entry-slippage sample. It is real, too small, entry-only, and not v41-TREND. It was **not** turned into a distribution.  
3. Every production-adjacent cost **number** that could be applied at scale is an **assumption** and is large enough to wipe a 0.033 R edge.  
4. v41 stays **neutral 1.0**. Calibrators untouched.

See `docs_v2/07_ml/V41_ROBUSTNESS_EVIDENCE.md` for the R-grid and stability diagnostics.
