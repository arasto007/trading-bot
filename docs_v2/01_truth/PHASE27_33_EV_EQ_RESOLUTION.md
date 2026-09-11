# Phase 27.33 — EV-EQ-01 Resolution

**Status:** FAILED  
**EV-EQ-01:** `NOT_PROVEN`  
**State:** `B_POLICY_AUTHORIZED_XAUUSD_i_ONLY`  
**Proven:** `False`  
**Artifact:** `logs/phase27_33_ev_eq_resolution.json`  
**Timestamp UTC:** `2026-09-10T07:31:12Z`

Read-only. Maps were not inserted. Production parquet was not rewritten.
Absence of `XAUUSD` is **NOT_PROVEN**, not DISPROVEN. Operator policy State B is **not** equivalence.

## Real account

| Field | Value |
|---|---|
| account | `REAL` |
| broker | `LiteFinance Global LLC` |
| server | `LiteFinance-MT5-Live` |
| terminal build | `6182` |
| evidence source | `fresh_readonly_catalog` |

## Symbols

| Symbol | Exists | Visible |
|---|---|---|
| XAUUSD | `False` | `UNKNOWN` |
| XAUUSD_i | `True` | `YES` |

## Field comparison

Matching: `0` — []  
Differing: `0` — []  
Unknown: `18` — ['contract_size', 'point', 'digits', 'tick_size', 'tick_value', 'tick_value_profit', 'tick_value_loss', 'volume_min', 'volume_max', 'volume_step', 'stops_level', 'freeze_level', 'execution_mode', 'calculation_mode', 'currency_profit', 'currency_margin', 'swap_long', 'swap_short']

XAUUSD is absent on the observed Real terminal. Absence is NOT_PROVEN, not DISPROVEN and not broker-wide absence. Similar XAUUSD_i economics do not invent XAUUSD. State B is available only as operator policy, not as proven equivalence.

## Operator policy

| Field | Value |
|---|---|
| canonical_symbol | `XAUUSD_i` |
| dataset_mapping_policy | `ONLY_WITH_EXPLICIT_DATASET_MAP` |
| silent mapping authorized | `False` |

## Dataset binding (Phase 27.27 inventory, not modified)

| Metric | Count |
|---|---|
| total | `43` |
| direct XAUUSD_i | `12` |
| explicit mapped | `0` |
| missing map | `30` |
| invalid map | `0` |
| unknown | `1` |

## Contract behavior

| Case | Result |
|---|---|
| missing map | `BLOCK` |
| valid explicit map | `ALLOWED` |
| direct XAUUSD_i | `ALLOWED` |
| silent conversion | `False` |

FINAL_GATE remains `BLOCKED`. Cost completeness remains `BLOCKED`.

## Next

STOP after Phase 27.33.
