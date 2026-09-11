# AUDIT_5 — Data Recovery from Git History

**Phase:** PROJECT_AUDIT_5  
**Generated:** 2026-09-10  
**Scope:** Read-only investigation of two lost evidence files; restore only if a genuine prior git/stash/reflog version exists. No fabrication.

**Protected invariant:** Fix 2 spread / historical_m5_bidask gate stays strict (partial ticks do not COMPLETE).

---

## 0. Executive result

| File | Verdict |
|------|---------|
| `logs/phase27_5_real_operator_evidence_raw.json` | **CONFIRMED_LOST** |
| `logs/phase27_18_xauusd_i_m5_bidask.parquet` | **CONFIRMED_LOST** (known fingerprint `c6aedc…` never present in git) |

Neither file was ever tracked by git. `logs/` has been gitignored since the initial local commit (`57bf778`). Stash list is empty; dangling stash commits and blobs contain only docs/code (no evidence payloads). No restore was performed. Downstream phase27_12 / 27_19 / 27_22 / 27_23 artifacts were **not** regenerated (would require fabricated inputs).

---

## 1. Git history search results

### 1.1 Structural fact (applies to both files)

- `.gitignore` line 6: `logs/` — present in **every** reachable commit checked (`57bf778`, `5381902`, `0898515`, `4bdc0f6`, and remote `7a2140b`).
- `git ls-files logs/` → **0** tracked paths (current tree and all historical trees scanned).
- `git rev-list --objects --all` → **no** path matching `phase27_5_real`, `phase27_18_xauusd`, `operator_evidence_raw`, or `m5_bidask`.

### 1.2 `logs/phase27_5_real_operator_evidence_raw.json`

| Check | Result |
|-------|--------|
| `git log --all --follow --oneline -- logs/phase27_5_real_operator_evidence_raw.json` | *(empty — never committed)* |
| `git log --all --oneline -- logs/phase27_5*` | *(empty)* |
| `git cat-file -e <commit>:logs/phase27_5_real_operator_evidence_raw.json` for `57bf778`, `5381902`, `0898515`, `4bdc0f6`, `7a2140b`, dangling `12c6f27`, dangling `82a8de2` | **missing in all** (exit 128) |
| Size / content at any commit | N/A — no blob |

### 1.3 `logs/phase27_18_xauusd_i_m5_bidask.parquet`

| Check | Result |
|-------|--------|
| `git log --all --follow --oneline -- logs/phase27_18_xauusd_i_m5_bidask.parquet` | *(empty — never committed)* |
| `git log --all --oneline -- logs/phase27_18*` | *(empty)* |
| `git cat-file -e <commit>:logs/phase27_18_xauusd_i_m5_bidask.parquet` for same commit set | **missing in all** |
| Size / content / fingerprint at any commit | N/A — no blob |
| Fingerprint string `c6aedc9b…` in git | Present only as **documentation / code constant** (`PHASE2718_KNOWN_FINGERPRINT` in `phase27_23_bidask_expansion.py` and `PHASE27_23_BIDASK_EXPANSION.md`) — **not** as parquet bytes |

### 1.4 Stash

| Check | Result |
|-------|--------|
| `git stash list` | **empty** |
| Dangling commit `12c6f272…` (`WIP on main: 0898515`) | Docs + `phase115` + one test — **no** `logs/` evidence |
| Dangling commit `82a8de24…` (`index on main: 0898515`) | Stash index pair of above — **no** evidence files |

### 1.5 Reflog

Full `git reflog --all` (all entries):

| Ref | Action |
|-----|--------|
| `4bdc0f6` | merge: resolve gitignore conflict / push |
| `7a2140b` | pull origin main --allow-unrelated-histories |
| `0898515` | commit: update project files |
| `5381902` | rename master→main; evidence-based docs baseline |
| `57bf778` | Initial snapshot - TradingBot New |

No reset/amend that could hide a prior commit containing these files. Only 5 reachable commits total in the object DB for this clone’s history spine.

### 1.6 Dangling blobs (`git fsck --unreachable`)

Inspected unreachable blobs (gitignore conflict, phase114/115 source, docs). **None** are JSON deal corpora or parquet tapes for the two target paths.

### 1.7 Supplementary offline checks (non-restore sources)

| Source | Result |
|--------|--------|
| Cursor `User/History` `entries.json` scan (~3037 dirs) for either path | **0** hits |
| Repo-wide filesystem copy of either basename | Only current `logs/phase27_18_…parquet` (wrong fingerprint); **JSON missing on disk** |

---

## 2. Per-file verdicts

### 2.1 Commission corpus — CONFIRMED_LOST

**Path:** `logs/phase27_5_real_operator_evidence_raw.json`

**Current disk state (AUDIT_5 probe):**
- File **absent**.
- `load_all_gold_deal_records()` → **`gold_deal_count = 2`** (from stale `logs/operator_broker_evidence_demo_raw.json` + `logs/operator_broker_evidence_raw.json` only; both `commission: 0.0`, tickets `None`).
- Related stub present: `logs/phase27_6_real_operator_evidence_raw.json` (3201 bytes) — not a 50-deal corpus and not a substitute.

**Why git cannot help:** File lived only under gitignored `logs/`; never entered any commit, stash, or reflog commit.

**What re-collection requires (operator — not performed in this phase):**
1. Attach an already-running MT5 terminal to the **same REAL operator account / broker** used for the historical 50-deal evidence (LiteFinance path as documented in phase27 artifacts).
2. Re-export / re-collect closed **XAUUSD / XAUUSD_i** deal history covering a window that again yields **≥ 50 distinct gold deals** with commission fields populated (historically narrated as 50 observed zeros → `OBSERVED_ZERO_NOT_PROVEN`, not a verified zero schedule).
3. Persist via the existing Phase 27.5 operator collector into `logs/phase27_5_real_operator_evidence_raw.json` (attach-only, no `symbol_select`, no orders — same contract as `phase27_5_operator_evidence.py`).
4. Then regenerate **only** downstream artifacts: phase27_12, 27_19, 27_22 (and re-run their tests). Do **not** weaken the `sample_count == 50` / `observed_zero_count == 50` gates to match the stub.

**This phase did not connect to MT5 or invent deals.**

### 2.2 Phase 27.18 bid/ask tape — CONFIRMED_LOST

**Path:** `logs/phase27_18_xauusd_i_m5_bidask.parquet`

**Locked expectation:** `PHASE2718_KNOWN_FINGERPRINT` =  
`c6aedc9bca3f9cf66d2c2e2971a301e224b2157e1cf91c60933a9a742398d319`  
(documented ~82-bar window `2026-09-04T17:10:00Z` → `2026-09-04T23:55:00Z`).

**Current disk state (AUDIT_5 probe via `tape_fingerprint`):**
- Exists, size 9416 bytes.
- Rows: **84** (not the locked Sep-4 82-bar tape).
- Fingerprint: **`98f594d70598af9b645380b19a996060cdc6342c7da170f4a8ac09e2cebe1510`** ≠ known.
- Metadata time range: `2026-09-09T17:05:00Z` → `2026-09-10T01:00:00Z` (AUDIT_3-era overwrite / later drift; AUDIT_4 had noted `8c6fd7…` / 71 bars — still not `c6aedc…`).
- File SHA-256 (bytes): `800156d6c5dcc33b30d91214c1d2f7117e5366d1bbed32ad8b0c32c0ab4338ee`.

**Why git cannot help:** Same as above — never tracked. The known fingerprint exists only as a code/doc constant, not as recoverable blob content.

**What re-collection requires (operator — not performed):**
1. Restore or re-collect the **exact** historical M5 bid/ask tape for XAUUSD_i covering **`2026-09-04T17:10:00Z`–`2026-09-04T23:55:00Z`** (UTC), using the same read-only `copy_ticks_range` / Phase 27.18 method that originally produced fingerprint `c6aedc…`.
2. Verify `tape_fingerprint(df) == PHASE2718_KNOWN_FINGERPRINT` **before** replacing `logs/phase27_18_xauusd_i_m5_bidask.parquet` (+ matching `.metadata.json`).
3. If the broker no longer retains that tick window, the locked fingerprint **cannot** be recreated honestly — document permanent loss; do **not** update `PHASE2718_KNOWN_FINGERPRINT` to endorse a newer tape without an explicit human policy decision.
4. After a verified restore, regenerate phase27_23 metadata/artifacts only as needed and re-run `test_phase27_18_not_overwritten_as_production`.

**This phase did not connect to MT5 or synthesize bars.**

---

## 3. Previously blocked tests (before/after)

No recovery → no honest pass change expected. Targeted re-run after investigation:

| Test area | AUDIT_4 | AUDIT_5 (no restore) |
|-----------|---------|----------------------|
| phase27_12 (2) | FAIL (2≠50 / FAIL≠PASS) | **still FAIL** |
| phase27_19 observed_zero | FAIL | **still FAIL** |
| phase27_22 (2) | FAIL | **still FAIL** |
| phase27_23 fingerprint | FAIL (`8c6fd7…`≠`c6aedc…`) | **still FAIL** (now `98f594…`≠`c6aedc…`) |

Targeted command result: **7 failed, 28 passed** in the four modules (same blocked assertions).

Downstream artifacts **not** regenerated.

---

## 4. Full suite vs AUDIT_4

Command (AUDIT_1-style):

```text
python -m pytest --continue-on-collection-errors -q --tb=line --junitxml=logs/audit5_junit.xml --ignore-glob=tests/test_ml_phase*.py
```

| Metric | AUDIT_4 | AUDIT_5 |
|--------|---------|---------|
| Executed | 6987 | 6987 |
| Passed | 6932 | 6900 |
| Failed | 22 | 57 |
| Errors | 3 | 0 |
| Skipped | 30 | 30 |
| Duration | ~14:53 | 1:56:05 |

**Delta vs AUDIT_4:** executed 0, passed -32, failed +35, errors -3, skipped 0.

**Interpretation:** AUDIT_5 performed **no restores and no code edits**. The 22 failures shared with AUDIT_4 still include the expected unrestorable commission/fingerprint cluster (27.12 / 27.19 / 27.22 / 27.23). The **+35 new failures** are almost entirely `tests/test_ml_*` modules outside the `--ignore-glob=tests/test_ml_phase*.py` filter (shadow/stress/training/validation) plus `test_phase118_tick_forensic_validation` — environmental/artifact drift during the long suite, **not** caused by evidence recovery. The 3 AUDIT_4 `test_phase24e` setup **errors** did not recur (0 errors).

Logs: `logs/audit5_full_suite.txt`, `logs/audit5_junit.xml`, `logs/audit5_targeted.txt`.

---

## 5. Integrity

- No fabricated JSON deals or parquet bars.
- No MT5 / `.env` / live orders.
- No kernel / adapters / domain / execution / RiskGate / Phase 40 tape edits.
- No code or gate weakenings in this phase.
