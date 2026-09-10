# archive/research

Historical research artifacts archived during **PROJECT_AUDIT_7** (2026-09-10).

## What this is

Python modules (and their preserved relative paths) that AUDIT_1 classified as
`RESEARCH_ARCHIVE_CANDIDATE`: phase research scripts/outputs under paths such as
`tradingbot/ml/research/`, research `scripts/phase*.py`, etc.

These files are **preserved for reference** and for traceability against
`docs/RESEARCH_LEDGER.md`. They are **not** part of the active/maintained
runtime surface.

## What this is not

- Not imported by production live/backtest entry points
- Not a substitute for deleting `DEAD_CODE` (that is a separate human-approval phase)
- Files that tests or active scripts still reference were **not** moved here
  (see `docs/AUDIT_7_ARCHIVE_REPORT.md` → `NO_LONGER_ARCHIVE_CANDIDATE`)

## Layout

Original relative paths are preserved under this directory, e.g.:

`tradingbot/ml/research/phase22a/foo.py`
→ `archive/research/tradingbot/ml/research/phase22a/foo.py`

## Phase 40 frozen tape

`logs/phase40_raw_setups.jsonl` was **not** moved and must remain at its original path.
