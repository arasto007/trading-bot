# V41 Deferred-Cost / Evidence Decision Audit (Phases 1.5.51–1.5.55)

**Status:** RESEARCH / OFFLINE  
**Last verified:** 2026-08-31  
**Live impact:** none  
**Classification:** **C — insufficient evidence, remain neutral**  
**v41 production factor:** remains **neutral 1.0**  
**Defensible round-trip cost model:** **does not exist**  
**Calibration justified:** **no**

This audit rechecks every cost candidate after 1.5.41–1.5.50. It does **not** start MT5, invent fills, rewrite prior research JSON, or change production calibrators.

Frozen OOS book (unchanged): 3,409 trades; gross PF 1.050; expectancy +0.033 R; max DD −33 R; break-even ≈ 0.033044 R/trade. At 0.04 R: expectancy ≈ −0.007 R, PF ≈ 0.990.

Machine-readable copy: `data/ml/reports/phase15_51/v41_decision_audit.json`.  
Prior JSON **not rewritten:** phase15_36, phase15_41, phase15_46.

---

## Phase 1.5.51 — cost-evidence recheck

Labels: **A** = directly usable for v41 round-trip costs · **B** = useful but incomplete · **C** = live-only / insufficient · **D** = fabricated / synthetic / not admissible.

Nothing new of class A was found. The only *new* facts relative to 1.5.46 are:

1. `data/ml/datasets/XAUUSD_M5_dataset_v2.parquet` has a `spread_pips` column — it is the OHLC bar-range proxy `(high−low)/pip` clipped to 5.0 (`sparse_event_builder.build_bar_spread_proxy_series`). **Class D.**
2. `data/ml/reports/phase20c/{spread,slippage}_analysis.json` exist but `count=0` / `PENDING`. **Class C.**
3. Research candles exist for **XAUUSD** M5/M15/H4; **no** `XAUUSD_i` / `XAUUSD_I` candle file. **Class C** for the live symbol.

| Source | Class | Why |
|--------|-------|-----|
| `data/ml/raw/spread/` (0 files) | C | empty store |
| `data/ml/raw/ticks/` (0 files) | C | empty store |
| XAUUSD M5/M15/H4 OHLC parquet | B | ATR / replay unit only — not bid/ask |
| XAUUSD_i M5 candles | C | file absent |
| `trade_journal.db` live executions n=17 | C | entry slippage only; not round-trip; not v41-TREND; n&lt;30 |
| Paper executions slippage=0 (n=5407) | D | always zero |
| Paper trades spread=0.30, commission=0 | D | PaperBroker default; engine phase9_9 |
| `data/ml/live/*.jsonl` | C | no spread/bid/ask/slippage keys |
| Dataset `spread_pips` / `bar_spread_pct` | D | OHLC proxy, clipped at 5.0 pips |
| Phase20c spread/slippage reports | C | count=0 |
| `engine_settings` `XAUUSD_i.max_spread=0.0200` | D | heuristic filter |
| `BrokerConstraints` tick_size/tick_value | D | `pip_size`/`contract_size` heuristics |
| PaperBroker / BacktestConfig / `execution_costs.py` | D | assumed constants |
| phase19a random 0–0.15 R | D | fabricated stress |
| phase27h `commission_per_lot_round=7.0` | D | research stress, not an invoice |
| RiskGate / MT5 `symbol_info` | C | live-only; not queried |
| `data/backtest` (21 cache files) | C | not a bid/ask tape |
| `reports/`, `data/exports`, `data/historical` | C | empty / absent |

**New evidence discovered this phase that is *usable* as a v41 cost tape: none.**  
**New evidence discovered that *rules out* using the dataset column as bid/ask: yes** (bar-range proxy).

No spread, slippage, commission, tick, or fill series was fabricated.

---

## Phase 1.5.52 — live symbol / research symbol identity

Research candles and the isolated book use **XAUUSD**. Live `PRIMARY_SYMBOL` is **XAUUSD_i**. Code aliases the *name* (`normalize_symbol("XAUUSD_i")` → `"XAUUSD"` in both `pa_symbol_tf_presets` and `live_gates`). That is **not** proof that the instruments are economically equivalent.

| Dimension | Code / file fact | Empirically proven? |
|-----------|------------------|---------------------|
| Price scale (pip) | `pip_size` returns 0.1 for both (`"XAU" in symbol`) | **NO** — heuristic |
| Point size | same heuristic as pip | **NO** — broker `trade_tick_size` not queried |
| Contract specification | `contract_size` returns 100 for both | **NO** — heuristic |
| `order_value(lot=0.01, px=2000)` | **XAUUSD_i → 2,000**; **XAUUSD → 2,000,000** | **disagrees in code** — 1000× |
| Spread behavior | `SYMBOL_CONFIGS` share assumed `spread_threshold=0.50`; `engine_settings` `max_spread=0.0200` | **NO** — no tape |
| Tick value | `BrokerConstraints` derives `tick_value = contract_size * pip_size` | **NO** — not MT5 `trade_tick_value` |
| Commission | paper/backtest default 0.0 | **NO** — unknown |
| Execution model | research = bar high/low SL/TP; live = `Mt5ExecutionAdapter` | **NO** — different models |
| Candle identity | XAUUSD M5 present; XAUUSD_i M5 **absent** | **NO** |

**INSUFFICIENT EVIDENCE — NOT PROVEN** that research XAUUSD and live XAUUSD_i share price scale, point size, contract spec, spread, tick value, commission, or execution.

Live configuration was **not** modified.

---

## Phase 1.5.53 — cost-model decision

A defensible **broker-realistic** cost model would need measured round-trip (spread + entry slip + exit slip + commission) on **XAUUSD_i**, at a sample large enough to apply to 3,409 OOS trades, plus proven symbol identity.

That evidence is **not in the repository**. Constructing a model from:

- 17 entry-only slips,
- paper 0.30 / backtest 2.5 pips,
- OHLC `(high−low)` clipped at 5.0,
- or any R-grid sensitivity

would **manufacture** broker costs. **No such model was built.**

The existing **sensitivity** grid (already computed in 1.5.41–50, not re-claimed as measurement):

| Kind | Status |
|------|--------|
| Uncosted OOS | exp +0.033 R, PF 1.050 |
| Break-even | 0.033044 R/trade |
| 0.04 R (sensitivity, not measured) | exp −0.007 R, PF 0.990 |
| Conservative lab bar (PF≥1.20 and exp≥0.05) | fails even at 0 R |

**Does current evidence support:**

| Option | Verdict |
|--------|---------|
| Calibration | **No** — no net measured edge, identity unproven, no class-A tape |
| Further research *from this agent* | **No** — remaining gaps require MT5/operator export; this process must not start MT5 |
| Stopping v41 entirely (class D) | **No** — uncosted OOS expectancy is still slightly positive; keep the frozen bundle as research-watch |

Remain **C**, remain **neutral 1.0**.

---

## Phase 1.5.54 — ranked evidence gaps

None of the nine items is currently available in the repo.

| Rank | Item | Why it matters | Minimum acceptable evidence | Offline from repo? | Needs MT5 / live export? | Available now? |
|------|------|----------------|----------------------------|--------------------|--------------------------|----------------|
| 1 | Real XAUUSD_i bid/ask tape | Round-trip spread vs a 0.033 R edge | Timestamped bid/ask (or spread) covering the OOS window, far more bars than trades | No | Yes (export allowed; this agent must not start MT5) | No |
| 2 | Entry **and** exit slippage | 17 rows are entry-only; exit can double cost | ≥30 live fills on **each** of entry and exit, same symbol, no paper mixing | No | Yes | No (17 entry-only) |
| 3 | Commission | Defaults are 0.0; small gold fees exceed 0.033 R | Broker schedule or measured commission on closed tickets | No | Yes | No |
| 4 | Tick / contract specification | `order_value` already disagrees; broker tick_value unqueried | Saved `symbol_info` snapshot (tick_size, tick_value, contract, digits) | No | Yes (snapshot file would suffice later) | No |
| 5 | Symbol identity mapping | Code aliases names; does not prove equal spread/execution | Paired quotes or broker spec that XAUUSD vs XAUUSD_i are the same instrument | No | Yes | No |
| 6 | Sufficiently large cost sample | n=17 &lt; 30; two outliers dominate the mean | ≥30 independent live **round-trips** (hundreds preferred) | No | Yes | No |
| 7 | Cost-aware OOS replay | Gross PF 1.05 is not net; 0.04 R already negative | Replay the **frozen** book with **measured** per-trade costs | No (needs 1–6 first) | Indirect | No |
| 8 | Robustness after costs | Uncosted rolling 250-windows already lose ~33% of the time | Year / session / rolling still viable **after measured costs** | No (needs 7) | Indirect | No |
| 9 | Retrain walk-forward | Different checksum than frozen v41; only after a surviving **net** edge | Justified **only if** items 1–8 show a measured net edge | Offline training possible later | Not first | No — **deferred** |

Retrain is **not** the next step.

---

## Phase 1.5.55 — final decision

**C — insufficient evidence, remain neutral.**

Not A: no class-A tape, no measured net expectancy, identity unproven.  
Not B: more analysis is not more evidence; remaining collection requires live/MT5 export this agent must not perform.  
Not D: uncosted OOS expectancy is still slightly positive, so the bundle is not disproven — it is unproven after costs.

v41 stays **neutral 1.0**. Production calibrators, `TREND_MODEL_ID`, RiskGate, execution, Adaptive wiring, `PIPELINE_TIMEOUT_MS`, `.env`, and `PA_PRODUCTION_LOCK` were **not** changed. ML live gate stays closed.

**Recommended next phase:** **STOP.** Do not auto-start 1.5.56. If a human later exports an XAUUSD_i bid/ask (and commission) tape **without this agent starting MT5**, a new **offline ingest** phase may re-score the frozen OOS book. Until that tape exists, v41 remains classification C.
