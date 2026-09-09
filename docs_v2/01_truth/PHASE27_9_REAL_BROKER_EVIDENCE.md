# Phase 27.9 — Fresh Real Broker Read-Only Evidence

**Status:** PASS  
**Evidence status:** `REAL_COLLECTED`  
**Artifact:** `logs/phase27_9_real_broker_evidence.json`

## Safety

One bounded attach-only attempt. MT5 was **not** started or restarted. `symbol_select` was not called. No orders. No `.env` read/write. Credentials were not written.

## Account / terminal identity

| Field | Value |
|---|---|
| login identity | `sha256:6a69df7fca46f339` (hash only; raw login not stored) |
| trade mode | `2` → **REAL** |
| broker | `LiteFinance Global LLC` |
| server | `LiteFinance-MT5-Live` |
| currency | `USD` |
| terminal build | `6182` |

Connected environment: **REAL**. Labeled REAL: `True`. Real-specific collection: `COLLECTED`.

If this session is DEMO, it is recorded as DEMO and Real collection stops.

## Catalog (read-only `symbols_get`)

Exact matches: `{'XAUUSD_i': 'YES', 'XAUUSD': 'NO'}`. Total symbols: `374`.

## Symbol snapshots

Unavailable fields are **UNKNOWN**. Equivalence is not inferred.

| Symbol | exists | visible | digits | point | contract | swap L/S/3d | bid/ask | UTC |
|---|---|---|---|---|---|---|---|---|
| `XAUUSD_i` | YES | YES | 2 | 0.01 | 100.0 | -89.136 / 3.45 / 3 | 4430.13 / 4430.31 | 2026-09-04T23:58:56Z |
| `XAUUSD` | NO | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN / UNKNOWN / UNKNOWN | UNKNOWN / UNKNOWN | UNKNOWN |

## EV-EQ-01

**NOT_PROVEN** — both symbols must exist on the same broker/server/environment for comparison

Canonical symbol policy remains `XAUUSD_i`. That policy does not prove `XAUUSD` ≡ `XAUUSD_i`.

## Production

**BLOCKED.** No RiskGate, strategy, or execution changes.

## Next

STOP after Phase 27.9.
