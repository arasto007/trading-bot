# Data Contracts

**Status:** VERIFIED (code-cited contracts; economics UNKNOWN)  
**Last verified:** 2026-09-09  
**Epistemic-Role:** OWNER of DATA_CONTRACTS.  
**Operator-effective state:** UNKNOWN  

Live market-data identity and live-vs-research contracts. Supporting adapter detail: `DATA_PIPELINE.md`. Architecture flow: `docs_v2/02_architecture/DATA_FLOW.md`.

---

## 1. Live symbol / timeframe contract (CODE DEFAULT)

| Contract | Value | Evidence |
|----------|-------|----------|
| Live broker symbol | `XAUUSD_i` | `tradingbot/config/live.py::PRIMARY_SYMBOL` |
| Live kernel TF when router on | `5m` only | `get_live_config()` |
| Forming bar | dropped before signal | `ohlcv.py::exclude_forming_bar` |
| Live bars source | MT5 via `Mt5MarketDataAdapter` | `DATA_PIPELINE.md`; `mt5_market_data.py` |

---

## 2. DEMO/REAL naming (USER-PROVIDED FACT)

| Environment | Symbol name | Kind |
|-------------|-------------|------|
| Demo | `XAUUSD_i` | USER-PROVIDED FACT |
| Real | `XAUUSD` | USER-PROVIDED FACT |

Source: `PROJECT_SOURCE_OF_TRUTH.md` §9; `CHATGPT_BOOTSTRAP.md` §8.

Naming is expected DEMO/REAL mapping. Contract / economic equivalence is **NOT PROVEN** (EV-EQ-01). Fail-closed dataset maps required; silent `XAUUSD`→`XAUUSD_i` forbidden (`CONFIGURATION_TRUTH.md`; Phase 27.8 / 27.10).

---

## 3. Research / dataset vs live

| Surface | Typical label | Notes |
|---------|---------------|-------|
| Research candles | often `XAUUSD` parquet | Not automatic live identity |
| Dataset `spread_pips` | OHLC PROXY | ≠ live tick spread (`CHATGPT_BOOTSTRAP.md` §8) |
| Historical bid/ask for cost COMPLETE | full-horizon M5 bid/ask | Partial tick sidecars do not satisfy COMPLETE_COSTS_REQUIRED |

---

## 4. Unknowns

- Operator `.env` data overrides — UNKNOWN (UNK-001)
- Demo↔Real economics — UNKNOWN / NOT PROVEN (UNK-002)
- Round-trip cost completeness — UNKNOWN (UNK-003)
