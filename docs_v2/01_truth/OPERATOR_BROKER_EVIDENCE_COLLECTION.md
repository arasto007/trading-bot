# Operator / Broker Evidence Collection Package

**Status:** RESEARCH / PROCEDURE — OPERATOR EVIDENCE COLLECTION GATE  
**Last verified:** 2026-09-02  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of operator-evidence **templates** and of **returned sheets** in this file. Does **not** own live routing, broker economics, or design verdicts. Runtime remains CODE. Economics remain UNKNOWN until both MT5 spec sheets exist. EV-EQ-01 is **not** decided in this gate.  
**Operator-effective state:** PARTIAL — Demo EV-D-* and EV-RT-D-* **COLLECTED** 2026-09-02 (LiteFinance-MT5-Demo); Real EV-R-19/20/21, EV-OBS-R-XAUUSD_i-*, EV-RT-R-*, EV-CAT-R-* COLLECTED; Real `XAUUSD` EV-R-01…18 NOT COLLECTED  
**Artifact class:** RESEARCH / PROCEDURE. Not production code. Not a live probe. Not a trade.  
**Method:** CODE > CANONICAL DOCS > PRODUCTION_READINESS_AUDIT.md > this package. Sessions: sanitized `.env`; read-only MT5 Python on Demo and Real terminals — no tradingbot runtime, no orders, no `symbol_select`. Raw artifacts: `logs/operator_broker_evidence_demo_raw.json`, `logs/operator_broker_evidence_raw.json`, `logs/operator_broker_symbol_catalog_raw.json`.

**Do not provide credentials or `.env` contents.** Never paste login, password, API key, account number, server password, Telegram token, or email password.

This package does **not** fix the robot. Deferred design is requirements-only. `XAUUSD_i` must **not** be changed to `XAUUSD` in code. Do **not** calculate EV-EQ-01. Do **not** declare Demo/Real equivalent.

---

## 0. Standing facts (do not re-litigate)

**USER-PROVIDED FACT (not a bug, not a contradiction):**

| Account type | Gold symbol name |
|--------------|------------------|
| DEMO | `XAUUSD_i` |
| REAL | `XAUUSD` |

Economic / contract equivalence of those two names: **UNKNOWN**. Do not guess.

Code defaults (VERIFIED, not operator-effective):

| Fact | Value | Evidence |
|------|-------|----------|
| Live symbol class A | `XAUUSD_i` | `tradingbot/config/live.py::PRIMARY_SYMBOL` |
| `DEMO_MODE` | hardcoded `True`; **not** an env key; does not block `--execute` | `LIVE_TRADING_CONFIG['DEMO_MODE']` (CX-005) |
| `order_value` gold `_i` | `lot * price * 100` | `order_logic.py::order_value` |
| `order_value` other names including `XAUUSD` | `lot * price * 100000` | same; cap `$100_000` |
| Gold `contract_size` heuristic | `100` for any `XAU`/`GOLD` | `position_logic.py::contract_size` |
| Silent name hunt | given name → `+_i` or strip `_i` via `symbol_info` | `symbols.py::resolve_broker_symbol` (CX-017) |
| Volume/stops/freeze at send | **not** applied; filling_mode only | `mt5_execution.py::_place_market_order` (UNK-012) |

MT5/broker cells below are filled only when evidence exists. Demo `XAUUSD_i` spec and closed-deal tape collected 2026-09-02 (§2.1, §3.1). Real `XAUUSD` EV-R-01…18 remain **NOT COLLECTED**. Secret values were never written here. Do not guess missing broker numbers.

---

## 1. How to use this package

1. Operator fills **Demo** sheets on the Demo terminal only.  
2. Operator fills **Real** sheets on the Real terminal only.  
3. If a Real (or Demo) terminal is not available: leave that side **NOT COLLECTED**. Do not invent values.  
4. Do **not** open a new trade to fill round-trip fields. Use an **existing closed** deal if one exists.  
5. Return filled tables to Cursor as sanitized text. No screenshots required if numbers are copied accurately.  
6. After collection, the next gate is a **DEMO/REAL design review** (still no production code). See §9 and §11.

**OPERATOR ACTION REQUIRED** for remaining MT5 fields. Sanitized `.env` flags, process counts, and a **read-only MT5 Python** session on the currently connected REAL terminal were collected 2026-09-02 (no secrets, no start/stop, no orders). Remaining work: **Demo terminal** EV-D-* (§2.1, §3.1) and Real **`XAUUSD`** spec EV-R-01…18 (§2.2) — symbol not found on connected Real terminal.

---

## 1.1 OPERATOR CHECKLIST (manual — Demo terminal then Real terminal)

Print this section or copy answers back into the tables in §2–§3. **Do not open a new trade. Do not start the bot. Do not change `.env`. Do not change code.**

### Safety (before you touch MT5)

1. Confirm you will **only look** at Specification, Market Watch, and History.
2. Do **not** place, modify, or close any order to create evidence.
3. Do **not** paste login, password, account number, ticket-if-it-embeds-account, server password, tokens, or `.env` contents.
4. If a field is not visible, write **NOT VISIBLE**. If a terminal is unavailable, leave that side **NOT COLLECTED**.
5. Do **not** assume Demo `XAUUSD_i` equals Real `XAUUSD`. Copy each side separately.

### A. DEMO terminal — `XAUUSD_i` specification (P0-002, P0-004, P0-005)

Open **only** the Demo MT5 terminal.

1. Navigator: copy the account-type **word only** (`demo` / other). No account number. → EV-D-19
2. Market Watch: is **`XAUUSD_i`** visible? YES / NO / UNKNOWN → feeds EV-D-01 and P0-006
3. Market Watch: is **`XAUUSD`** (no `_i`) also visible? YES / NO / UNKNOWN → EV-D-20
4. Right-click **`XAUUSD_i`** → **Specification** (or View → Symbols → Properties). Copy exactly:

| Copy this label | Paste into |
|-----------------|------------|
| Name | EV-D-01 |
| Digits | EV-D-02 |
| Point | EV-D-03 |
| Contract size / Trade contract size | EV-D-04 **and** P0-004 Demo |
| Tick size | EV-D-05 **and** P0-004 Demo |
| Tick value | EV-D-06 **and** P0-004 Demo |
| Volume min | EV-D-07 / P0-005 |
| Volume max | EV-D-08 / P0-005 |
| Volume step | EV-D-09 / P0-005 |
| Stops level | EV-D-10 / P0-005 |
| Freeze level | EV-D-11 / P0-005 |
| Filling (full text) | EV-D-12 / P0-005 |
| Trade / Trade mode | EV-D-13 / P0-005 |
| Execution | EV-D-14 / P0-005 |
| Commission if shown, else NOT VISIBLE | EV-D-16 |
| Swap long / Swap short | EV-D-17 |
| Margin / Initial / Maintenance / hedge if shown, else NOT VISIBLE | EV-D-18 |
| Partial-fill / filling notes if documented on the spec, else NOT VISIBLE | P0-005 note |

5. Market Watch at one moment: Spread (points) + Bid + Ask → EV-D-15
6. Write collection time **UTC** → EV-D-21

### B. DEMO terminal — existing closed gold deal (P0-003)

Toolbox → **History** / Account History.

- If **no** closed gold deal (`XAUUSD_i` or gold) exists: write **NOT COLLECTED — DO NOT CREATE ONE**. Stop this sub-step.
- If one exists: pick **one** closed trade. Redact ticket/login/account. Fill EV-RT-D-01…16 (symbol, side, requested volume if shown, filled volume, requested/entry, actual fill, SL, TP, exit, commission, swap, spread if shown, slippage if shown else NOT VISIBLE, open time, close time, P/L money, partial fill YES/NO/UNKNOWN).

### C. REAL terminal — `XAUUSD` specification (P0-002, P0-004, P0-005)

Open **only** the Real MT5 terminal. Repeat the same fields for **`XAUUSD`**. Do **not** copy Demo numbers across.

1. Account-type **word only** (`real` / other). No number. → EV-R-19
2. Is **`XAUUSD`** visible? YES / NO / UNKNOWN
3. Is **`XAUUSD_i`** also visible on this Real Market Watch? YES / NO / UNKNOWN → EV-R-20
4. Specification of **`XAUUSD`**: same labels as Demo → EV-R-01…18
5. Spread + Bid + Ask snapshot → EV-R-15
6. Collection time **UTC** → EV-R-21
7. P0-004 Real only: Contract size, Tick size, Tick value (EV-R-04, EV-R-05, EV-R-06)

### D. REAL terminal — existing closed gold deal (P0-003)

Same rule as Demo. If none: **NOT COLLECTED — DO NOT CREATE ONE**. If one exists: fill EV-RT-R-01…16. **Do not open a Real trade.**

### E. Already collected this gate (do not re-do unless you want to confirm)

- **P0-001 sanitized env flags:** filled in §4 (TRUE/FALSE/UNSET or SET/UNSET). Secret values were not recorded.
- **Process:** EV-PROC-01 / EV-PROC-02 filled in §5. Nothing was started or stopped.

### F. Return format

Paste the filled tables (or the same fields as labeled lines) back into chat. No screenshots required if numbers are accurate. After return, the next gate is design review — still no production code.

---

## 2. Demo / Real symbol evidence catalog

Collect **the same fields twice**: once for Demo `XAUUSD_i`, once for Real `XAUUSD`.

**Expected source:** MetaTrader 5 → Market Watch → right-click symbol → **Specification** (or View → Symbols → select → Properties). Spread: Market Watch bid/ask at a UTC timestamp. Commission/swap: Specification if shown; otherwise an existing closed deal (see §3). Margin: Specification “Margin” / “Initial margin” / “Maintenance” / hedge rate **if visible**; else write NOT VISIBLE.

**Safe method:** Operator copies numbers into the blank tables. Do not export the whole account. Do not send login. Do not start the bot to print specs. **Exception (2026-09-02):** read-only MT5 Python API used for broker-native `symbol_info` / deal history only — no tradingbot runtime, no `order_send`, no symbol selection changes.

| Field | WHY NEEDED | P0 / P1 | Expected MT5 label (typical) |
|-------|------------|---------|------------------------------|
| Symbol | Confirm the terminal actually lists the USER-PROVIDED name | P0-002, P0-006 | Name |
| Digits | Price precision; SL/TP rounding | P0-002, P0-005 | Digits |
| Point | Point size vs digits; stops distance | P0-002, P0-005 | Point |
| Contract size | Notional vs `order_value` vs `position_logic.contract_size` | P0-002, **P0-004** | Contract size / Trade contract size |
| Tick size | Minimum price increment | P0-002, P0-005 | Tick size |
| Tick value | Money per tick per lot; cost and size | P0-002, P0-004, P0-003 | Tick value |
| Volume minimum | Lot floor the adapter does not enforce | **P0-005**, UNK-012 | Volume min |
| Volume maximum | Lot cap the adapter does not enforce | P0-005, UNK-012 | Volume max |
| Volume step | Lot grid the adapter does not enforce | P0-005, UNK-012 | Volume step |
| Stops level | Min SL/TP distance; not applied at send | P0-005, UNK-012 | Stops level |
| Freeze level | Modify/close freeze; not applied at send | P0-005, UNK-012 | Freeze level |
| Filling mode | Adapter maps `filling_mode` to type_filling | P0-005 | Filling |
| Trade mode | Whether symbol is tradable (disabled / close-only) | P0-005, P0-006 | Trade / Trade mode |
| Execution mode | Instant / market / exchange / request | P0-005 | Execution |
| Spread | Round-trip cost component (time-varying) | **P0-003** | Spread + Bid/Ask |
| Commission | Round-trip cost; live path unmodeled | **P0-003**, UNK-007 | Commission (spec or deal) |
| Swap | Hold cost if position spans rollover | P0-003 | Swap long / Swap short |
| Margin information | Leverage / used margin vs notional | P0-002 | Margin / Initial / Maintenance **if visible** |

Also collect (non-secret):

| Field | WHY NEEDED | P0 / P1 |
|-------|------------|---------|
| Account type as MT5 shows it (`Demo` vs `Real`) — **no account number** | Confirms which terminal the sheet belongs to | P0-001 context, P0-002 |
| Whether the **other** gold name is also visible in Market Watch | Silent `_i` hunt (P0-006 / CX-017) | **P0-006** |
| Collection UTC timestamp | Spread/tick_value can move | P0-003 |

### 2.1 Demo fill-in — `XAUUSD_i`

Terminal: DEMO only. Symbol to open: **`XAUUSD_i`**.

**2026-09-02 read-only MT5 session:** connected terminal was **DEMO** (LiteFinance-MT5-Demo). `symbols_get()` exact `XAUUSD`: **NO**; exact `XAUUSD_i`: **YES**. No `symbol_select()` called.

| ID | Field | Operator value | Status |
|----|-------|----------------|--------|
| EV-D-01 | Symbol (exact Market Watch name) | `XAUUSD_i` | **COLLECTED** |
| EV-D-02 | Digits | 2 | **COLLECTED** |
| EV-D-03 | Point | 0.01 | **COLLECTED** |
| EV-D-04 | Contract size | 100 | **COLLECTED** |
| EV-D-05 | Tick size | 0.01 | **COLLECTED** |
| EV-D-06 | Tick value | 1.0 | **COLLECTED** |
| EV-D-07 | Volume minimum | 0.01 | **COLLECTED** |
| EV-D-08 | Volume maximum | 100 | **COLLECTED** |
| EV-D-09 | Volume step | 0.01 | **COLLECTED** |
| EV-D-10 | Stops level | 0 | **COLLECTED** |
| EV-D-11 | Freeze level | 0 | **COLLECTED** |
| EV-D-12 | Filling mode (raw `filling_mode`) | 1 | **COLLECTED** |
| EV-D-13 | Trade mode (raw `trade_mode`) | 4 | **COLLECTED** |
| EV-D-14 | Execution mode (raw `trade_exemode`) | 2 | **COLLECTED** |
| EV-D-15 | Spread (points) + Bid + Ask | 38 pts; bid 4374.47 / ask 4374.85 | **COLLECTED** |
| EV-D-16 | Commission (spec or “NOT VISIBLE”) | NOT VISIBLE | NOT COLLECTED |
| EV-D-17 | Swap long / Swap short | -89.136 / 3.45 | **COLLECTED** |
| EV-D-18 | Margin fields if visible, else NOT VISIBLE | initial 0.0 / maintenance 0.0 | **COLLECTED** |
| EV-D-19 | MT5 account type word only (`demo` / other) — no number | DEMO | **COLLECTED** |
| EV-D-20 | Is `XAUUSD` (no `_i`) also visible in this Demo Market Watch? YES/NO | NO — absent from catalog | **COLLECTED** |
| EV-D-21 | Collection timestamp UTC | 2026-09-02T18:31:37Z | **COLLECTED** |

**Supplemental Demo fields (same session, not separate EV-D IDs):** `trade_calc_mode` = 2; `trade_tick_value_profit` = 1.0; `trade_tick_value_loss` = 1.0; quote UTC 2026-09-02T21:31:37Z; spread 0.38 price units.

### 2.2 Real fill-in — `XAUUSD`

Terminal: REAL only. Symbol to open: **`XAUUSD`**. Do not switch the robot symbol in code.

**2026-09-02 read-only MT5 session:** connected terminal was REAL (LiteFinance-MT5-Live). `symbol_info("XAUUSD")` returned **null**. **Catalog check (§2.2c):** exact name `XAUUSD` is **absent** from `symbols_get()` on this terminal (375 symbols). This does **not** prove broker-wide absence on other terminals or servers. EV-R-01…18 for `XAUUSD` remain **NOT COLLECTED**. Account-type and visibility fields (EV-R-19…21) collected. Observed `XAUUSD_i` spec on this Real terminal is in §2.2a (supplemental; does not fill EV-R-01…18 for `XAUUSD`).

| ID | Field | Operator value | Status |
|----|-------|----------------|--------|
| EV-R-01 | Symbol (exact Market Watch name) | | NOT COLLECTED — `XAUUSD` absent from `symbols_get()` on this terminal (§2.2c) |
| EV-R-02 | Digits | | NOT COLLECTED |
| EV-R-03 | Point | | NOT COLLECTED |
| EV-R-04 | Contract size | | NOT COLLECTED |
| EV-R-05 | Tick size | | NOT COLLECTED |
| EV-R-06 | Tick value | | NOT COLLECTED |
| EV-R-07 | Volume minimum | | NOT COLLECTED |
| EV-R-08 | Volume maximum | | NOT COLLECTED |
| EV-R-09 | Volume step | | NOT COLLECTED |
| EV-R-10 | Stops level | | NOT COLLECTED |
| EV-R-11 | Freeze level | | NOT COLLECTED |
| EV-R-12 | Filling mode (copy Specification text) | | NOT COLLECTED |
| EV-R-13 | Trade mode | | NOT COLLECTED |
| EV-R-14 | Execution mode | | NOT COLLECTED |
| EV-R-15 | Spread (points) + Bid + Ask | | NOT COLLECTED |
| EV-R-16 | Commission (spec or “NOT VISIBLE”) | | NOT COLLECTED |
| EV-R-17 | Swap long / Swap short | | NOT COLLECTED |
| EV-R-18 | Margin fields if visible, else NOT VISIBLE | | NOT COLLECTED |
| EV-R-19 | MT5 account type word only (`real` / other) — no number | REAL | **COLLECTED** (2026-09-02 read-only MT5) |
| EV-R-20 | Is `XAUUSD_i` also visible in this Real Market Watch? YES/NO | YES | **COLLECTED** (2026-09-02 read-only MT5) |
| EV-R-21 | Collection timestamp UTC | 2026-09-02T18:24:48Z | **COLLECTED** (2026-09-02 read-only MT5) |

### 2.2a Observed on REAL terminal — `XAUUSD_i` (read-only MT5 Python 2026-09-02)

Supplemental broker-native evidence. Connected account: REAL / LiteFinance-MT5-Live. Does **not** fill Demo EV-D-* or Real `XAUUSD` EV-R-01…18 template slots. Raw numeric MT5 API fields reported as returned; UI text labels not inferred.

| ID | Field | Observed value | Status |
|----|-------|----------------|--------|
| EV-OBS-R-01 | Symbol | `XAUUSD_i` | **COLLECTED** |
| EV-OBS-R-02 | Exists | true | **COLLECTED** |
| EV-OBS-R-03 | Visible / selected | YES / YES | **COLLECTED** |
| EV-OBS-R-04 | Digits | 2 | **COLLECTED** |
| EV-OBS-R-05 | Point | 0.01 | **COLLECTED** |
| EV-OBS-R-06 | Contract size (`trade_contract_size`) | 100 | **COLLECTED** |
| EV-OBS-R-07 | Tick size | 0.01 | **COLLECTED** |
| EV-OBS-R-08 | Tick value | 1.0 | **COLLECTED** |
| EV-OBS-R-09 | Tick value profit | 1.0 | **COLLECTED** |
| EV-OBS-R-10 | Tick value loss | 1.0 | **COLLECTED** |
| EV-OBS-R-11 | Volume min / max / step | 0.01 / 100 / 0.01 | **COLLECTED** |
| EV-OBS-R-12 | Stops level / freeze level | 0 / 0 | **COLLECTED** |
| EV-OBS-R-13 | Filling mode (raw `filling_mode`) | 1 | **COLLECTED** |
| EV-OBS-R-14 | Trade mode (raw `trade_mode`) | 4 | **COLLECTED** |
| EV-OBS-R-15 | Execution (raw `trade_exemode`) | 2 | **COLLECTED** |
| EV-OBS-R-16 | Calc mode (raw `trade_calc_mode`) | 2 | **COLLECTED** |
| EV-OBS-R-17 | Currency base / profit / margin | USD / USD / USD | **COLLECTED** |
| EV-OBS-R-18 | Swap long / swap short / rollover3days | -89.136 / 3.45 / 3 | **COLLECTED** |
| EV-OBS-R-19 | Margin initial / maintenance | 0.0 / 0.0 | **COLLECTED** |
| EV-OBS-R-20 | Session trade / quote | NOT AVAILABLE | NOT COLLECTED |
| EV-OBS-R-21 | Bid / Ask / spread (price) / spread (points) | 4372.74 / 4373.11 / 0.37 / 37 | **COLLECTED** |
| EV-OBS-R-22 | Quote timestamp UTC | 2026-09-02T21:24:48Z | **COLLECTED** |
| EV-OBS-R-23 | Commission on symbol spec | NOT VISIBLE | NOT COLLECTED |

### 2.2b Contract/tick comparison (observed only — no equivalence verdict)

| Field | Demo `XAUUSD_i` (2026-09-02) | Real `XAUUSD_i` (2026-09-02) | Real `XAUUSD` |
|-------|------------------------------|------------------------------|---------------|
| Contract size | 100 | 100 | NOT AVAILABLE |
| Tick size | 0.01 | 0.01 | NOT AVAILABLE |
| Tick value | 1.0 | 1.0 | NOT AVAILABLE |
| Tick value profit | 1.0 | 1.0 | NOT AVAILABLE |
| Tick value loss | 1.0 | 1.0 | NOT AVAILABLE |
| Volume min | 0.01 | 0.01 | NOT AVAILABLE |
| Volume max | 100 | 100 | NOT AVAILABLE |
| Volume step | 0.01 | 0.01 | NOT AVAILABLE |
| Stops level | 0 | 0 | NOT AVAILABLE |
| Freeze level | 0 | 0 | NOT AVAILABLE |
| Filling (raw) | 1 | 1 | NOT AVAILABLE |
| Trade mode (raw) | 4 | 4 | NOT AVAILABLE |
| Execution (raw) | 2 | 2 | NOT AVAILABLE |

### 2.2c Read-only broker symbol catalog — REAL terminal (2026-09-02)

**Method:** `symbols_get()` on connected REAL terminal (LiteFinance-MT5-Live). No `symbol_select()`. No terminal or Market Watch changes. Scope: **this terminal’s broker symbol list only** — does not prove absence on other servers, account types, or future catalog updates.

| ID | Field | Observed value | Status |
|----|-------|----------------|--------|
| EV-CAT-R-01 | Total symbols in catalog | 375 | **COLLECTED** |
| EV-CAT-R-02 | Exact `XAUUSD` exists in `symbols_get()` | NO | **COLLECTED** |
| EV-CAT-R-03 | Exact `XAUUSD_i` exists in `symbols_get()` | YES | **COLLECTED** |
| EV-CAT-R-04 | Collection timestamp UTC | 2026-09-02T18:28:30Z | **COLLECTED** |

**Search hits (name contains):**

| Search term | Matching symbol names |
|-------------|----------------------|
| `XAU` | `XAUPUSD_cl`, `XAUUSD_i` |
| `GOLD` | *(none)* |
| `XA` | `XAGPUSD_cl`, `XAGUSD_i`, `XAUPUSD_cl`, `XAUUSD_i` |
| `USD` | 120+ symbols (full list in raw artifact; includes all rows above) |

**Gold-related symbols (name contains `XAU` or `GOLD`):**

| Symbol | In catalog | Visible | Selected | trade_mode (raw) |
|--------|------------|---------|----------|------------------|
| `XAUUSD_i` | YES | YES | YES | 4 |
| `XAUPUSD_cl` | YES | NO | NO | 4 |

No symbol name containing `GOLD` was returned. Exact `XAUUSD` was not present in the catalog array returned for this terminal.

### 2.3 Economic equivalence (do not fill until both sheets exist)

| ID | Field | Status |
|----|-------|--------|
| EV-EQ-01 | Are Demo `XAUUSD_i` and Real `XAUUSD` economically equivalent? | **INSUFFICIENT EVIDENCE** |

Sheets remain empty. Design review `DEMO_REAL_SYMBOL_COST_DESIGN.md` (2026-09-02) cannot choose EQUIVALENT or NOT EQUIVALENT. After both spec tapes exist, a later comparison may change this cell.

---

## 3. Round-trip cost evidence template

**Do not place a new order.** If no closed gold deal exists on that account, mark the sheet **NOT COLLECTED**.

**Expected source:** MT5 Toolbox → **History** / **Account History**. Open one **closed** gold deal (and its related order if the terminal splits entry/exit). Copy prices and money fields only.

**Safe method:** One existing closed trade per account type. Redact ticket/login/account number. Symbol name, prices, volume, times, commission, swap, profit are non-secret for this package.

Slippage (if the terminal does not show it):  
`slippage = actual_fill − requested_entry` (buy) or `requested_entry − actual_fill` (sell). If requested entry is unknown, write NOT VISIBLE.

Spread at fill: only if the deal comment / journal shows bid/ask; else NOT VISIBLE.

### 3.1 Demo round-trip (existing closed deal)

One existing closed `XAUUSD_i` deal collected 2026-09-02 via read-only MT5 deal history. No new trade opened.

| ID | Field | Operator value | Status |
|----|-------|----------------|--------|
| EV-RT-D-01 | Symbol | `XAUUSD_i` | **COLLECTED** |
| EV-RT-D-02 | Requested volume (lots) | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-D-02F | Actual filled volume (lots) | 0.01 | **COLLECTED** |
| EV-RT-D-03 | Requested entry | 4414.32 | **COLLECTED** |
| EV-RT-D-04 | Actual fill price | 4414.32 | **COLLECTED** |
| EV-RT-D-05 | SL | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-D-06 | TP | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-D-07 | Exit price | 4414.65 | **COLLECTED** |
| EV-RT-D-08 | Commission (entry+exit if split) | 0.0 | **COLLECTED** |
| EV-RT-D-09 | Swap | 0.0 | **COLLECTED** |
| EV-RT-D-10 | Spread if visible | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-D-11 | Slippage (or NOT VISIBLE) | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-D-12 | Entry timestamp (broker time + timezone if shown) | 2026-08-12T13:41:02Z | **COLLECTED** |
| EV-RT-D-13 | Exit timestamp | 2026-08-12T13:41:03Z | **COLLECTED** |
| EV-RT-D-14 | Result (profit/loss money, **not** account balance) | -0.33 | **COLLECTED** |
| EV-RT-D-15 | Side BUY/SELL | SELL | **COLLECTED** |
| EV-RT-D-16 | Partial fill? YES/NO/UNKNOWN | NO | **COLLECTED** |

No login / password / API key / account number / ticket if it embeds the account.

### 3.2 Real round-trip (existing closed deal)

Same fields: **EV-RT-R-01 … EV-RT-R-16**. One existing closed gold deal on REAL account collected 2026-09-02 via read-only MT5 deal history. Symbol is `XAUUSD_i` (not `XAUUSD` — only gold symbol with history on this terminal). No ticket/account identifiers recorded.

| ID | Field | Operator value | Status |
|----|-------|----------------|--------|
| EV-RT-R-01 | Symbol | `XAUUSD_i` | **COLLECTED** |
| EV-RT-R-02 | Requested volume (lots) | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-R-02F | Actual filled volume (lots) | 0.03 | **COLLECTED** |
| EV-RT-R-03 | Requested entry | 4154.17 | **COLLECTED** |
| EV-RT-R-04 | Actual fill price | 4154.17 | **COLLECTED** |
| EV-RT-R-05 | SL | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-R-06 | TP | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-R-07 | Exit price | 4156.24 | **COLLECTED** |
| EV-RT-R-08 | Commission (entry+exit if split) | 0.0 | **COLLECTED** |
| EV-RT-R-09 | Swap | 0.0 | **COLLECTED** |
| EV-RT-R-10 | Spread if visible | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-R-11 | Slippage (or NOT VISIBLE) | NOT AVAILABLE | NOT COLLECTED |
| EV-RT-R-12 | Entry timestamp (broker time + timezone if shown) | 2025-11-27T15:53:15Z | **COLLECTED** |
| EV-RT-R-13 | Exit timestamp | 2025-11-27T15:54:21Z | **COLLECTED** |
| EV-RT-R-14 | Result (profit/loss money, **not** account balance) | -6.21 | **COLLECTED** |
| EV-RT-R-15 | Side BUY/SELL | SELL | **COLLECTED** |
| EV-RT-R-16 | Partial fill? YES/NO/UNKNOWN | NO | **COLLECTED** |

**WHY / P0:** P0-003 (round-trip costs), UNK-003, UNK-007 (partials/commission). Supports later cost-model design only.

---

## 4. Sanitized environment evidence

**OPERATOR ACTION REQUIRED.** Open `.env` locally. Do **not** paste the file. Do **not** send it to chat.

For each key, report **only**:

- **TRUE** — key is present and truthy (`1` / `true` / `yes` / `on`)
- **FALSE** — key is present and falsey (`0` / `false` / `no` / `off`)
- **UNSET** — key is absent (or commented out)

Non-boolean keys: **SET** or **UNSET** only. If SET, you may add a **non-secret** token (example: `OR`, `0.38`, `OFF`). Never add secret strings.

**Never report values for:** `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `EMAIL_*`, `TELEGRAM_*`, any token/password/key/account number.

`load_dotenv` fills **only if the key is not already in the process environment** (`tradingbot/config/dotenv_loader.py`). Daemon `setdefault` applies if still unset (`scripts/start_live_daemon.ps1`).

### 4.1 Not env keys (code facts)

| ID | Name | Env report | Code default (VERIFIED) | Notes |
|----|------|------------|-------------------------|-------|
| EV-ENV-00 | `DEMO_MODE` | **NOT APPLICABLE** (not read from env) | `True` in `LIVE_TRADING_CONFIG` | Does not block `--execute` (CX-005) |
| EV-ENV-01 | `PRIMARY_SYMBOL` | **UNSET** | class A `XAUUSD_i` | Collected 2026-09-02. Env ignored by code; live symbol remains hardcoded |

### 4.2 Boolean / presence flags found in live-path code

| ID | Flag | Why | P0/P1 | Daemon if unset | Operator TRUE/FALSE/UNSET |
|----|------|-----|-------|-----------------|---------------------------|
| EV-ENV-02 | `USE_ML_KERNEL` | ML kernel gate | P0-001, P1-002 | `"false"` | **FALSE** |
| EV-ENV-03 | `ENABLE_ML_SHADOW` | shadow wrap | P0-001 | `"true"` | **UNSET** |
| EV-ENV-04 | `PA_PRODUCTION_LOCK` | PA lock | P0-001, P1-002 | not set by daemon; code default true | **UNSET** |
| EV-ENV-05 | `TRADINGBOT_ALLOW_REAL` | demo-account guard override | P0-001 | unset → real blocked | **UNSET** |
| EV-ENV-06 | `TRADINGBOT_DRY_RUN` | skips `order_send` | P0-001, execution | LiveRunner `--execute` pops it | **UNSET** |
| EV-ENV-07 | `TRADINGBOT_PAPER` | paper fills | P0-001 | same | **UNSET** |
| EV-ENV-08 | `TRADINGBOT_LIVE` | set by LiveRunner on `--execute` | P0-001 | usually not in `.env` | **UNSET** |
| EV-ENV-09 | `TRADINGBOT_SKIP_MT5_STARTUP` | skips MT5 connect | P0-001 | unset | **UNSET** |
| EV-ENV-10 | `ADAPTIVE_REGIME_ENABLED` | Adaptive select/probe | P0-001, P1-002, P1-006 | `"false"` | **UNSET** |
| EV-ENV-11 | `ADAPTIVE_CONFLUENCE_ONLY` | Adaptive confluence | P1-002 | not daemon; code default true | **UNSET** |
| EV-ENV-12 | `ADAPTIVE_QUALITY_ENGINE` | Adaptive quality | P1-002 | code default false | **UNSET** |
| EV-ENV-13 | `VOL_REGIME_ENABLED` | VOL engine | P0-001, P1-002 | `"false"` | **UNSET** |
| EV-ENV-14 | `VOL_DIRECTION_FILTER_ENABLED` | VOL as PA filter | P1-002 | code default false | **UNSET** |
| EV-ENV-15 | `VOL_REGIME_SKIP_TQ` | skip TQ on VOL | P1-002 | code default true | **UNSET** |
| EV-ENV-16 | `DEMO_DISABLE_SESSION_FILTER` | bypass NY window | P1-005 / UNK-005 | code default false | **TRUE** |
| EV-ENV-17 | `MULTI_ENGINE_ROUTER_ENABLED` | router | P0-001, P1-002 | `"true"` | **UNSET** |
| EV-ENV-18 | `META_OBSERVER_MODE` | meta observer | P1-003 | code default false | **UNSET** |
| EV-ENV-19 | `DISABLE_HIGH_VOL_FOR_MICRO` | micro vol block | P1-002 | code default true | **UNSET** |
| EV-ENV-20 | `ALLOW_LEGACY_FALLBACK` | ML fail → legacy | P0-001 | code default false | **UNSET** |
| EV-ENV-21 | `ROUTER_DECISION_LOG` | extra router log | P2 | unset | **UNSET** |
| EV-ENV-22 | `TRADINGBOT_REJECTION_LOG` | rejection log | P2 | unset | **UNSET** |
| EV-ENV-23 | `PHASE52A_PM` | PM variant | P1-008 | unset | **UNSET** |
| EV-ENV-24 | `PHASE47C_FORWARD_DEMO` | forward tracker | P2 | unset | **UNSET** |
| EV-ENV-25 | `PHASE51A_FORWARD_DEMO` | forward cert | P2 | unset | **UNSET** |
| EV-ENV-26 | `PHASE6A_FORWARD_DEMO` | phase6a cert | P2 | unset | **UNSET** |

### 4.3 SET / UNSET (non-boolean; no secrets)

| ID | Flag | Why | P0/P1 | Operator SET/UNSET |
|----|------|-----|-------|-------------------|
| EV-ENV-27 | `MT5_LOGIN` | whether env overrides `engine_settings` fallback (CX-016) | P0-001, P1-005, UNK-008 | **SET** (value not recorded) |
| EV-ENV-28 | `MT5_PASSWORD` | same | P0-001, P1-005 | **SET** (value not recorded) |
| EV-ENV-29 | `MT5_SERVER` | same | P0-001, P1-005 | **SET** (value not recorded) |
| EV-ENV-30 | `ADAPTIVE_CONFLUENCE_MODE` | OR vs AND | P1-002 | **UNSET** |
| EV-ENV-31 | `META_LABEL_THRESHOLD` | RiskGate meta | P1-003 | **UNSET** |
| EV-ENV-32 | `TRADINGBOT_PROP_PRESET` or `PROP_FIRM_PRESET` | risk overlay | P0-001 | **UNSET** / **UNSET** |
| EV-ENV-33 | `TRADINGBOT_SIGNAL_FILTER` | signal filter | P1 | **UNSET** |
| EV-ENV-34 | `TRADINGBOT_WPSQF_THRESHOLD` | filter threshold | P1 | **UNSET** |
| EV-ENV-35 | `TRADINGBOT_EXIT_MODE` | exit mode | P1-008 | **UNSET** |
| EV-ENV-36 | `TREND_MODEL_VERSION` | unused on default PA if ML off | P2 / H | **SET** (non-secret token: `v41`) |
| EV-ENV-37 | `EMAIL_USERNAME` / `EMAIL_PASSWORD` / `EMAIL_TO` / `EMAIL_FROM` | present? | P2 | **UNSET** / **UNSET** / **UNSET** / **UNSET** |
| EV-ENV-38 | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | present? | P2 | **UNSET** / **UNSET** |
| EV-ENV-39 | `LIVE_DAILY_REPORT_HOUR_UTC` / `LIVE_DRIFT_CHECK_HOUR_UTC` | ops hours | P2 | **UNSET** / **UNSET** |

`.env.example` also lists `ENABLE_RSI_FILTER`, `ENABLE_ADX_FILTER`, `PHASE22C_*`. Those are **not** consumed on the default PA live path documented in CONFIGURATION_TRUTH (class H / research). Optional: report SET/UNSET as EV-ENV-40. Do not treat them as live PA gates.

---

## 5. Current process evidence

**Do not start, stop, or kill any process.** This gate used a count-only check: no command lines, PIDs, or secrets were recorded. Nothing was started or stopped.

Collected 2026-09-02 on this machine (count-only): `--loop` count **0**; `run_live_watchdog` count **0**.

Safe Windows check (count only — do not paste full command lines):

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'tradingbot.*--loop' -or $_.CommandLine -match 'run_live_watchdog' } |
  Measure-Object |
  Select-Object -ExpandProperty Count
```

If Count ≥ 1 → YES (running). If 0 → NO. If the command fails → UNKNOWN.

| ID | Evidence | Status |
|----|----------|--------|
| EV-PROC-01 | `--loop` process running? YES/NO/UNKNOWN | **NO** (count 0, 2026-09-02) |
| EV-PROC-02 | `run_live_watchdog` process running? YES/NO/UNKNOWN | **NO** (count 0, 2026-09-02) |

Maps to UNK-010. No PID dump required.

---

## 6. Evidence matrix

Current Status values used here: **VERIFIED** (code fact only), **COLLECTED** (operator or sanitized sheet returned; not a P0 closure), **UNKNOWN** (established unknown, not guessed), **NOT COLLECTED** (operator has not returned the sheet), **NOT APPLICABLE**.

Who: **Operator** unless row says Code (already verified).

| Evidence ID | Evidence | Demo/Real/Both | P0/P1/P2 | Why Needed | Current Status | Who Must Provide | Safe Collection Method |
|-------------|----------|----------------|----------|------------|----------------|------------------|------------------------|
| EV-D-01 | Demo symbol name | Demo | P0-002, P0-006 | Confirm `XAUUSD_i` exists | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` on Demo |
| EV-D-02 | Demo digits | Demo | P0-002, P0-005 | Precision | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-03 | Demo point | Demo | P0-002, P0-005 | Point vs stops | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-04 | Demo contract size | Demo | P0-002, P0-004 | vs `order_value` *100 | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-05 | Demo tick size | Demo | P0-002, P0-005 | Increment | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-06 | Demo tick value | Demo | P0-002, P0-003, P0-004 | Money/tick | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-07 | Demo volume min | Demo | P0-005 | Adapter does not enforce | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-08 | Demo volume max | Demo | P0-005 | Adapter does not enforce | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-09 | Demo volume step | Demo | P0-005 | Adapter does not enforce | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-10 | Demo stops level | Demo | P0-005 | Adapter does not apply | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-11 | Demo freeze level | Demo | P0-005 | Adapter does not apply | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-12 | Demo filling mode | Demo | P0-005 | `type_filling` mapping | **COLLECTED** (raw 1) | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-13 | Demo trade mode | Demo | P0-005, P0-006 | Tradable? | **COLLECTED** (raw 4) | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-14 | Demo execution mode | Demo | P0-005 | Instant/market/etc. | **COLLECTED** (raw 2) | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-15 | Demo spread snapshot | Demo | P0-003 | Cost component | **COLLECTED** | Read-only MT5 2026-09-02 | tick snapshot |
| EV-D-16 | Demo commission spec | Demo | P0-003 | Unmodeled live | NOT COLLECTED — NOT VISIBLE | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-17 | Demo swap long/short | Demo | P0-003 | Hold cost | **COLLECTED** | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-18 | Demo margin info | Demo | P0-002 | If visible | **COLLECTED** (0.0 / 0.0) | Read-only MT5 2026-09-02 | `symbol_info` |
| EV-D-19 | Demo account type word | Demo | P0-001 | Terminal class | **COLLECTED — DEMO** | Read-only MT5 2026-09-02 | `account_info`; no login |
| EV-D-20 | Bare `XAUUSD` visible on Demo? | Demo | P0-006 | Silent hunt | **COLLECTED — NO** | Read-only MT5 2026-09-02 | `symbols_get` + visibility |
| EV-D-21 | Demo collection UTC time | Demo | P0-003 | Snapshot time | **COLLECTED** | Read-only MT5 2026-09-02 | Session timestamp |
| EV-R-01 | Real symbol name | Real | P0-002, P0-006 | Confirm `XAUUSD` exists | NOT COLLECTED — absent from `symbols_get()` on this REAL terminal (§2.2c) | Read-only MT5 2026-09-02 | `symbols_get` exact name |
| EV-R-02 | Real digits | Real | P0-002, P0-005 | Precision | NOT COLLECTED | Operator | Specification |
| EV-R-03 | Real point | Real | P0-002, P0-005 | Point vs stops | NOT COLLECTED | Operator | Specification |
| EV-R-04 | Real contract size | Real | P0-002, **P0-004** | vs `order_value` *100000 | NOT COLLECTED | Operator | Specification |
| EV-R-05 | Real tick size | Real | P0-002, P0-005 | Increment | NOT COLLECTED | Operator | Specification |
| EV-R-06 | Real tick value | Real | P0-002, P0-003, P0-004 | Money/tick | NOT COLLECTED | Operator | Specification |
| EV-R-07 | Real volume min | Real | P0-005 | Adapter does not enforce | NOT COLLECTED | Operator | Specification |
| EV-R-08 | Real volume max | Real | P0-005 | Adapter does not enforce | NOT COLLECTED | Operator | Specification |
| EV-R-09 | Real volume step | Real | P0-005 | Adapter does not enforce | NOT COLLECTED | Operator | Specification |
| EV-R-10 | Real stops level | Real | P0-005 | Adapter does not apply | NOT COLLECTED | Operator | Specification |
| EV-R-11 | Real freeze level | Real | P0-005 | Adapter does not apply | NOT COLLECTED | Operator | Specification |
| EV-R-12 | Real filling mode | Real | P0-005 | `type_filling` mapping | NOT COLLECTED | Operator | Specification |
| EV-R-13 | Real trade mode | Real | P0-005, P0-006 | Tradable? | NOT COLLECTED | Operator | Specification |
| EV-R-14 | Real execution mode | Real | P0-005 | Instant/market/etc. | NOT COLLECTED | Operator | Specification |
| EV-R-15 | Real spread snapshot | Real | P0-003 | Cost component | NOT COLLECTED | Operator | Market Watch + UTC time |
| EV-R-16 | Real commission spec | Real | P0-003 | Unmodeled live | NOT COLLECTED | Operator | Spec or NOT VISIBLE |
| EV-R-17 | Real swap long/short | Real | P0-003 | Hold cost | NOT COLLECTED | Operator | Specification |
| EV-R-18 | Real margin info | Real | P0-002 | If visible | NOT COLLECTED | Operator | Specification or NOT VISIBLE |
| EV-R-19 | Real account type word | Real | P0-001 | Terminal class | **COLLECTED — REAL** | Read-only MT5 2026-09-02 | `account_info`; no login |
| EV-R-20 | `XAUUSD_i` visible on Real? | Real | P0-006 | Silent hunt | **COLLECTED — YES** | Read-only MT5 2026-09-02 | `symbol_info` visible flag |
| EV-R-21 | Real collection UTC time | Real | P0-003 | Snapshot time | **COLLECTED** | Read-only MT5 2026-09-02 | Session timestamp |
| EV-OBS-R-* | `XAUUSD_i` on REAL terminal | Real | P0-002, P0-004, P0-005 | Supplemental; not USER-PROVIDED Real name | **COLLECTED** (§2.2a) | Read-only MT5 2026-09-02 | `symbol_info` / tick |
| EV-CAT-R-* | REAL broker symbol catalog | Real | P0-002, P0-006 | Exact-name presence vs visibility | **COLLECTED** (§2.2c) | Read-only MT5 2026-09-02 | `symbols_get`; no `symbol_select` |
| EV-EQ-01 | Economic equivalence | Both | P0-002 | Name is not the criterion; specs missing | INSUFFICIENT EVIDENCE | Later analysis after both sheets | Do not guess |
| EV-RT-D-* | Demo closed-trade tape | Demo | P0-003, UNK-007 | Round-trip cost | **PARTIAL COLLECTED** — `XAUUSD_i` SELL 0.01 (§3.1); requested vol / SL / TP / spread / slippage NOT COLLECTED | Read-only MT5 2026-09-02 | History; no new order |
| EV-RT-R-* | Real closed-trade tape | Real | P0-003, UNK-007 | Round-trip cost | **PARTIAL COLLECTED** — `XAUUSD_i` SELL 0.03 (§3.2); requested vol / SL / TP / spread / slippage NOT COLLECTED | Read-only MT5 2026-09-02 | History; no new order |
| EV-ENV-00 | `DEMO_MODE` env | Both | P0-001 | Not an env key | NOT APPLICABLE | — | Code default True is VERIFIED |
| EV-ENV-01 | `PRIMARY_SYMBOL` env | Both | P0-001, P0-006 | Env ignored; code `XAUUSD_i` | **COLLECTED — UNSET** | Sanitized `.env` 2026-09-02 | SET/UNSET only; no value |
| EV-ENV-02…26 | Boolean live flags | Both | P0-001, P1-002 | Operator-effective env | **COLLECTED** (see §4.2) | Sanitized `.env` 2026-09-02 | TRUE/FALSE/UNSET; never paste `.env` |
| EV-ENV-27…29 | MT5 credential **presence** | Both | P0-001, P1-005, CX-016 | Env vs hardcoded fallback | **COLLECTED — SET/SET/SET** (values not recorded) | Sanitized `.env` 2026-09-02 | SET/UNSET only; never values |
| EV-ENV-30…39 | Other SET/UNSET flags | Both | P0-001 / P1 / P2 | Completeness | **COLLECTED** (see §4.3) | Sanitized `.env` 2026-09-02 | SET/UNSET; no secrets |
| EV-PROC-01 | `--loop` running | Both | UNK-010, P1-008 | Current process | **COLLECTED — NO** | Count-only 2026-09-02 | Count YES/NO; no kill; no command line |
| EV-PROC-02 | `run_live_watchdog` running | Both | UNK-010 | Current process | **COLLECTED — NO** | Count-only 2026-09-02 | Count YES/NO; no kill |
| EV-CODE-OV | `order_value` formula | Both | P0-004 | Real name 1000× vs gold 100 | VERIFIED | Code | Already inspected; do not “fix” here |
| EV-CODE-CS | `contract_size` XAU=100 | Both | P0-004 | Heuristic vs broker | VERIFIED | Code | Already inspected |
| EV-CODE-RES | `resolve_broker_symbol` hunt | Both | P0-006 | Silent `_i` fallback | VERIFIED | Code | Already inspected |
| EV-CODE-FILL | Send uses filling_mode only | Both | P0-005 | Volume/stops unused | VERIFIED | Code | Already inspected |

---

## 7. P0 closure criteria (OPEN → RESOLVED)

No new P0 was added. Audit P0-001…P0-006 remain the set. CX-016 credential fallbacks stay under **P1-005 / UNK-008**, evidenced by EV-ENV-27…29 (SET/UNSET). Collection of those flags is required for P0-001 completeness.

| P0 | OPEN means | Evidence required | RESOLVED only when |
|----|------------|-------------------|--------------------|
| **P0-001** Operator `.env` | Operator-effective flags unknown | Complete §4 sheet (TRUE/FALSE/UNSET or SET/UNSET). No secrets. | Sheet **COLLECTED** 2026-09-02 (sanitized). This gate does **not** mark P0-001 RESOLVED. Missing keys stay UNSET, not guessed. |
| **P0-002** Demo/Real economics | Equivalence UNKNOWN | Complete EV-D-01…18 and EV-R-01…18 | Both tapes complete **and** a later comparison records EQUIVALENT or NOT EQUIVALENT field-by-field. Collection alone does **not** resolve EV-EQ-01. |
| **P0-003** Round-trip costs | No class-A cost tape | EV-RT-D-* and, if Real will be used, EV-RT-R-* from **existing** closed deals | At least one complete closed-trade tape per account type that will be traded. If no history: remains OPEN; **do not** create a trade. |
| **P0-004** Real `order_value` 1000× | Code: `XAUUSD` uses *100000 vs gold contract 100 | EV-R-04, EV-R-06, EV-D-04, EV-D-06 plus EV-CODE-OV (already VERIFIED) | **Not** resolved by collection. RESOLVED only after a later **authorized** redesign of `order_value` / contract handling, **or** an explicit written decision to keep live symbol `XAUUSD_i` and not send Real-name `XAUUSD` until redesigned. Do not “fix” by renaming the symbol. |
| **P0-005** volume/stops/partials | Send path ignores those `symbol_info` fields | EV-D-07…14 and EV-R-07…14; EV-RT-*-16 partials if a deal exists | **Not** resolved by collection. RESOLVED only after later authorized execution design uses volume min/max/step, stops/freeze, and defined partial-fill behavior. |
| **P0-006** silent `_i` resolution | `resolve_broker_symbol` hunts names | EV-D-20, EV-R-20 (other name visible YES/NO) plus USER-PROVIDED map | **Not** resolved by collection. RESOLVED only after later explicit DEMO/REAL symbol configuration **without** auto `_i` hunt. Do not change `XAUUSD_i` to `XAUUSD` in this or the next design-only gate. |

---

## 8. Deferred design / requirements (NO CODE)

Write-only requirements for a later authorized phase. **Do not implement now.**

1. **Explicit account-symbol map** — configuration such as `ACCOUNT_ENV=DEMO|REAL` (name TBD) selecting `XAUUSD_i` vs `XAUUSD`. Not inferred from `symbol_info` visibility.  
2. **Disable silent hunt** — `resolve_broker_symbol` must not auto-try `+_i` / strip `_i` on the live path. Missing configured symbol → fail closed, no fallback.  
3. **Do not rename** — do not replace live `PRIMARY_SYMBOL = "XAUUSD_i"` with `XAUUSD` as a “fix”.  
4. **`order_value`** — must not hardcode `* 100` vs `* 100000` by suffix. Size from broker `trade_contract_size` / tick value after evidence, with a cap that matches gold notional.  
5. **`contract_size`** — live sizing must not assume `100` for every `XAU*` independently of `symbol_info`.  
6. **Volume validation** — reject lots not on min/max/step **before** `order_send`.  
7. **Stops / freeze** — reject or adjust SL/TP that violate `stops_level` / `freeze_level` before send; freeze affects modify/close.  
8. **Execution / filling** — keep mapping explicit; do not silently change filling if broker rejects.  
9. **Partial fills** — defined behavior (reject remaining / log / no retry storm).  
10. **Commission / cost model** — live risk must not assume zero commission; feed from evidence tapes.  
11. **Env** — `PRIMARY_SYMBOL` must not stay a ignored env key if operators set it; either honor a dedicated non-secret symbol key or document it as unused.

---

## 9. Next gate (after evidence is returned)

**STOP** production-robot changes until operator sheets exist.

Exact next phase: **DEMO/REAL Symbol & Cost Design Review** (documentation/design only):

- Compare EV-D vs EV-R (EV-EQ-01).  
- Specify explicit symbol config and `order_value` redesign.  
- Still: no production implementation, no MT5 from Cursor, no orders, no ML activation, no `XAUUSD_i` → `XAUUSD` swap.

---

## 10. Safety

| Action | This package / this gate |
|--------|----------------|
| Production code | NONE |
| TradingKernel / RiskGate / Execution / symbol resolution / `order_value` / position sizing | NOT MODIFIED |
| MT5 started by Cursor | NO — used existing running terminal only |
| MT5 read-only Python (`symbol_info`, deal history, `symbols_get`) | YES (2026-09-02); no `order_send`, no `symbol_select`, no Market Watch changes |
| Bot / daemon / watchdog | NO start, NO stop |
| Orders | NO |
| ML / Adaptive / VOL activation | NO |
| `.env` | Sanitized presence/boolean read only. **No values of secrets recorded. File not changed.** |
| Git commit/reset/stash/clean | NO |
| Freshness snapshot rewrite | NO |
| EV-EQ-01 / Demo≡Real | NOT CALCULATED / NOT DECLARED |
| `ACCOUNT_ENVIRONMENT` / execution hardening | NOT IMPLEMENTED |

If a step would need MT5 login-from-Cursor, broker passwords, production edits, or `order_send`: **STOP** and mark **OPERATOR ACTION REQUIRED**.

**This gate remaining work:** Real `XAUUSD` spec EV-R-01…18 (§2.2) — exact name absent from REAL-terminal `symbols_get()` 2026-09-02 (broker-wide presence on other terminals/servers still UNKNOWN). Demo `XAUUSD_i` spec and closed-deal tape complete.
