# Phase 58 — Commission Accountability

**G2:** `PARTIAL`
**Product (Phase 57):** `PARTIAL` candidate `CLASSIC`

Observed gold-deal commissions remain **NOT_PROVEN_SCHEDULE** even if all zeros.

## 58A Product → schedule
ECN $5/lot is BROKER_DOCUMENTED. It is ACCOUNT_PRODUCT_VERIFIED / COMMISSION_SCHEDULE_VERIFIED only if Phase 57 is VERIFIED_ECN and the 2026-05-19 PDF applies. It is not.

## 58B Historical deals
Per-deal commission is OBSERVED. A zero schedule is NOT inferred.

## 58C–58D ECN / CLASSIC / CENT
- ECN $5/lot → `0.007279` R/event (SCENARIO). Net event `0.041381` R
- CLASSIC/CENT 14 **points** (official PDF 2026-05-19 note 2) → `0.020382` R/event using XAUUSD_i point=0.01. Not treated as $14 without units.

## 58E–58G Scenarios / break-even / uncertainty
- Event break-even cost `0.048660` R ≈ `33.42` USD/lot at median SL.
- EDGE_SMALLER_THAN_COST_UNCERTAINTY = TRUE (modeled 1x spread+slip).

Not a profitability verdict. G2 is not PASS while the account product is not VERIFIED.
