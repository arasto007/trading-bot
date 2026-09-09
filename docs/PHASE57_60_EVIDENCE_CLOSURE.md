# Phase 57–60 — Evidence Closure

## EXECUTIVE_STATUS

Research advanced. G1=`PARTIAL` (candidate `CLASSIC`). G2=`PARTIAL`. G3=`FAIL`. Live/optimization remain NO-GO. Project is **not** stopped.

## CURRENT_GATE
`TARGETED_EVIDENCE_COLLECTION` / FINAL_GATE BLOCKED

## G1_ACCOUNT_PRODUCT
`PARTIAL` — PARTIAL candidate CLASSIC
## G2_COMMISSION
`PARTIAL` — observed zeros NOT_PROVEN_SCHEDULE; CLASSIC 14 now converted as **points** (official PDF).
## G3_SYMBOL_EQUIVALENCE
`FAIL` — official XAUUSD swap/contract match XAUUSD_i is SUPPORTING only.
## G4_BID_ASK
PARTIAL
## G5_SWAP
PARTIAL (current rate observed; historical series unknown)
## G6_REQUEST_FILL
FAIL (0 pairs)
## G7_EXECUTABLE_VALIDATION
FAIL
## G8_EXECUTION_PARITY
FAIL

## PROVEN_FACTS
- REAL LiteFinance-MT5-Live; XAUUSD_i tradable on this terminal; XAUUSD not in current catalog.
- Official PDF effective 2026-05-19 (prior artifact 2026-03-26 kept as conflict).
- Official CLASSIC/CENT markup units = points per round lot for commodities.
- Official ECN max orders 500 vs CLASSIC/CENT 300; CENT currency USD-¢.

## UNKNOWN_FACTS
- Exact Cabinet product name for this login.
- Whether XAUUSD_i is officially the alias of XAUUSD.

## CONTRADICTIONS
- CX-REAL-SYMBOL: operator REAL=XAUUSD vs CODE/catalog XAUUSD_i.
- PDF dates 2026-03-26 vs 2026-05-19 (current fetch confirms 2026-05-19).

## COST_SCENARIOS / BREAK_EVEN / EDGE
- ECN scenario net event `0.041380655141037406` R
- Break-even event cost `0.04866` R ≈ `33.42333750000044` USD/lot
- EDGE_VS_COST_UNCERTAINTY: `MARGIN_NEGATIVE`

## OPERATOR_EVIDENCE_REQUEST
See `docs/OPERATOR_EVIDENCE_REQUEST.md`.

## NEXT_BEST_ACTION
1. Operator: Cabinet account type (ECN/CLASSIC/CENT), redacted.
2. Operator/support: XAUUSD_i ≡ XAUUSD on this server.
3. Then a dedicated executable cost-aware validation phase — not live.

## DO_NOT_DO_YET
Optimize, shadow, live, send orders, read .env, rename XAUUSD_i, hang tick download.
