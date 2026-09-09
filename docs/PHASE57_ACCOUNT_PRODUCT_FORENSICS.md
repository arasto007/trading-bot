# Phase 57 — Account Product Forensics

**ACCOUNT_PRODUCT:** `PARTIAL`
**CANDIDATE:** `CLASSIC`
**G1:** `PARTIAL`
**MT5 attached:** `True`

ECN was not inferred from leverage. CLASSIC was not inferred from `_cl` or `CLS_LOW_SPREAD_i`.
Zeros were not used. CENT is incompatible with observed USD (official CENT is USD-¢).
limit_orders=300 is incompatible with official ECN 500 and compatible with CLASSIC/CENT.
This is **PARTIAL**, not VERIFIED_CLASSIC: no product field; customization not disproven.

PDF effective date on the current official file is **2026-05-19**. Prior artifact 2026-03-26 remains recorded. DOCUMENT_DATE_CONFLICT=TRUE.

## 57A Account metadata
Login is hashed if present. No group/product/tier field is exposed by `account_info()`.

## 57B Group / path / server
Server naming and CLS_LOW_SPREAD_i path are supporting only. Official FAQ says account types use different servers but does not name LiteFinance-MT5-Live.

## 57C Local project evidence
Repository token hits do not identify this exact account's product.

## 57D Official documents
Sources: account-types ECN/CLASSIC/CENT pages and markups PDF. DOCUMENT_DATE_CONFLICT=TRUE.

## 57E Verdict
`ACCOUNT_PRODUCT=PARTIAL` candidate `CLASSIC`. Not VERIFIED.

## Operator evidence required

- LiteFinance Cabinet: Account type / product line (ECN or CLASSIC or CENT), with account number and balances redacted.
- Optional: support confirmation of the same product. No password, login, .env, API key, or payment details.
