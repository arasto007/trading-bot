#!/usr/bin/env python3
"""Assemble docs/AUDIT_1_CLEANUP_REPORT.md from tools/audit/out artifacts."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
REPORT = ROOT / "docs" / "AUDIT_1_CLEANUP_REPORT.md"
BASELINE = ROOT / "docs" / "AUDIT_1_BASELINE_TEST_RESULTS.md"


def load(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main() -> int:
    summary = load("summary.json")
    unreachable = load("unreachable.json")
    reachable = load("reachable.json")
    runtime = load("runtime_reachable.json")
    test_only = load("test_only_reachable.json")
    flags = load("live_flag_inventory.json")
    getenv = load("getenv_inventory.json")
    md_files = load("all_md_files.json")
    baseline_text = ""
    if BASELINE.is_file():
        baseline_text = BASELINE.read_text(encoding="utf-8")

    flag_counts = Counter(x["flag"] for x in unreachable)
    dead = [x for x in unreachable if x["flag"] == "DEAD_CODE"]
    research = [x for x in unreachable if x["flag"] == "RESEARCH_ARCHIVE_CANDIDATE"]

    lines: list[str] = []
    a = lines.append

    a("# PROJECT_AUDIT_1 — Cleanup & Consolidation Report")
    a("")
    a(f"**Generated (UTC):** {datetime.now(timezone.utc).isoformat()}")
    a("**Phase:** REPORT ONLY — no production files modified, deleted, renamed, or moved.")
    a("**Analyzer:** `tools/audit/project_audit_1_reachability.py` (+ getenv/flag helpers under `tools/audit/`).")
    a("")
    a("## 1. Test baseline summary")
    a("")
    if baseline_text.strip():
        # Embed key lines from baseline doc
        a("See also: [`docs/AUDIT_1_BASELINE_TEST_RESULTS.md`](AUDIT_1_BASELINE_TEST_RESULTS.md)")
        a("")
        a("```")
        # take first 40 non-empty lines
        kept = 0
        for ln in baseline_text.splitlines():
            a(ln)
            kept += 1
            if kept >= 60:
                break
        a("```")
    else:
        a("_Baseline file not yet written — pytest still running or pending._")
    a("")

    a("## 2. Reachability / dependency graph")
    a("")
    a("### Method")
    a("")
    a("- Static AST import BFS from entry points:")
    a("  - `tradingbot.__main__`, `tradingbot.application.live_runner`, `tradingbot.application.bootstrap`, `tradingbot.backtest.engine`")
    a("  - Scripts referenced by root `دستورات_اجرایی.md` and `start/*.bat`")
    a("  - All `tests/**/*.py` imports and string path/module mentions of `tradingbot|engine|scripts`")
    a("- Inventory roots: `tradingbot/`, `engine/`, `scripts/`, root-level `*.py`")
    a("- Dynamic imports (`importlib`, string `__import__`) are **not** fully resolved — may under-count REACHABLE.")
    a("")
    a("### Counts")
    a("")
    a(f"| Metric | Count |")
    a(f"|--------|------:|")
    a(f"| Inventory `.py` files scanned | {summary['inventory_count']} |")
    a(f"| REACHABLE (runtime entries ∪ tests) | {summary['reachable_count']} |")
    a(f"| Runtime-only REACHABLE (no tests) | {summary['runtime_reachable_count']} |")
    a(f"| TEST_ONLY (reachable via tests, not runtime entries) | {summary.get('test_only_reachable_count', len(test_only))} |")
    a(f"| UNREACHABLE | {summary['unreachable_count']} |")
    a(f"| UNREACHABLE → DEAD_CODE | {flag_counts.get('DEAD_CODE', 0)} |")
    a(f"| UNREACHABLE → RESEARCH_ARCHIVE_CANDIDATE | {flag_counts.get('RESEARCH_ARCHIVE_CANDIDATE', 0)} |")
    a(f"| UNREACHABLE → TEST_ONLY | {flag_counts.get('TEST_ONLY', 0)} |")
    a("")
    a("Script entry refs used:")
    a("")
    for ref in summary.get("script_entry_refs", []):
        a(f"- `{ref}`")
    a("")

    a("### Classification notes")
    a("")
    a("- `RESEARCH_ARCHIVE_CANDIDATE`: path/name contains `phaseNN` and/or lives under `tradingbot/ml/research/` (expected historical research; not \"dead\" runtime).")
    a("- `DEAD_CODE`: unreachable and not phase/research-classified. **Includes operator utility scripts** that are simply not wired from the documented bat/doc entry set — human review required before deletion.")
    a("- `TEST_ONLY`: imported/mentioned by tests but not by runtime entries. Listed separately (they are in REACHABLE by Task 2 definition).")
    a("")

    a("### 2.1 REACHABLE full list")
    a("")
    a(f"_{len(reachable)} files_")
    a("")
    a("```")
    for p in reachable:
        a(p)
    a("```")
    a("")

    a("### 2.2 Runtime-only REACHABLE (subset)")
    a("")
    a(f"_{len(runtime)} files_")
    a("")
    a("```")
    for p in runtime:
        a(p)
    a("```")
    a("")

    a("### 2.3 TEST_ONLY (reachable via tests, not runtime entries)")
    a("")
    a(f"_{len(test_only)} files_")
    a("")
    a("```")
    for x in test_only:
        a(x["path"] if isinstance(x, dict) else x)
    a("```")
    a("")

    a("### 2.4 UNREACHABLE — DEAD_CODE")
    a("")
    a(f"_{len(dead)} files_")
    a("")
    a("| Path | Last commit | Message | Docstring/header (truncated) |")
    a("|------|-------------|---------|------------------------------|")
    for x in dead:
        msg = (x.get("last_commit_message") or "").replace("|", "\\|")
        doc = (x.get("docstring_head") or "").replace("|", "\\|")
        a(f"| `{x['path']}` | {x.get('last_commit_date') or '—'} | {msg[:80]} | {doc[:100]} |")
    a("")

    a("### 2.5 UNREACHABLE — RESEARCH_ARCHIVE_CANDIDATE")
    a("")
    a(f"_{len(research)} files_")
    a("")
    a("| Path | Last commit | Message | Docstring/header (truncated) |")
    a("|------|-------------|---------|------------------------------|")
    for x in research:
        msg = (x.get("last_commit_message") or "").replace("|", "\\|")
        doc = (x.get("docstring_head") or "").replace("|", "\\|")
        a(f"| `{x['path']}` | {x.get('last_commit_date') or '—'} | {msg[:80]} | {doc[:100]} |")
    a("")

    a("## 3. Documentation contradiction map")
    a("")
    a(f"Markdown inventory: `docs/` = **{md_files['docs_count']}** files; `docs_v2/` = **{md_files['docs_v2_count']}** files.")
    a("")
    a("Full paths:")
    a("")
    a("<details><summary>docs/ file list</summary>")
    a("")
    for p in md_files["docs"]:
        a(f"- `{p}`")
    a("")
    a("</details>")
    a("")
    a("<details><summary>docs_v2/ file list</summary>")
    a("")
    for p in md_files["docs_v2"]:
        a(f"- `{p}`")
    a("")
    a("</details>")
    a("")

    a("### Code ground truth (verified this audit)")
    a("")
    a("| Topic | What code actually does | Evidence |")
    a("|-------|-------------------------|----------|")
    a("| Pipeline stage count | **6 stages**: Data → Indicator → Signal → **SignalFilter** → Risk → Execution | `tradingbot/kernel/trading_kernel.py` lines 84–91 |")
    a("| SignalFilter default | Wired; default **OFF** (pass-through) unless `TRADINGBOT_SIGNAL_FILTER=WPSQF` | `tradingbot/services/signal_filter_mode.py` `resolve_signal_filter_mode()` |")
    a("| Live TIMEFRAMES | `LIVE_TRADING_CONFIG['TIMEFRAMES']=['5m','15m','4h']` but `get_live_config()` **forces `['5m']`** when `MULTI_ENGINE_ROUTER_ENABLED` / `VOL_REGIME_ENABLED` / `ADAPTIVE_REGIME_ENABLED` | `tradingbot/config/live.py` `get_live_config()` ~228–242; router default **true** |")
    a("| TIMEFRAME_CONFIGS | Dict for 1m/5m/15m/1h/4h \"ULTRA AGGRESSIVE\" thresholds; `get_timeframe_config()` defined | **No live/backtest call sites** found outside `live.py` itself (plus one research audit string) |")
    a("| Active live strategy | PA primary under `PA_PRODUCTION_LOCK` default true; VOL/Adaptive not selected for orders when lock holds | `tradingbot/services/pa_production_lock.py`; `docs_v2/04_strategy/ACTIVE_STRATEGIES.md` aligns |")
    a("| RiskGate position caps | Defaults from config/`PRICE_ACTION`: total **3**, per-symbol **2**; risk/trade **0.005** | `tradingbot/config/live.py` L42–52; `tradingbot/adapters/risk_gate.py` `__init__` ~862–876 |")
    a("")

    a("### Subsystem contradiction table (docs vs code)")
    a("")
    a("| Doc | Claim (summary) | Verdict vs code | Notes |")
    a("|-----|-----------------|-----------------|-------|")
    a("| `docs_v2/02_architecture/PIPELINE.md` | Six stages; SignalFilter registered; default OFF | **MATCHES_CODE** | Cites kernel lines |")
    a("| `docs_v2/01_truth/PROJECT_SOURCE_OF_TRUTH.md` | Six stages; M5 forced when router on | **MATCHES_CODE** | |")
    a("| `docs_v2/01_truth/SOURCE_OF_TRUTH.md` | Six stages; notes legacy 5-stage conflict | **MATCHES_CODE** | Explicitly documents KI area |")
    a("| `docs_v2/02_architecture/ARCHITECTURE.md` | Six stages | **MATCHES_CODE** | |")
    a("| `docs_v2/02_architecture/SYSTEM_ARCHITECTURE.md` | Includes SignalFilterStage | **MATCHES_CODE** | |")
    a("| `docs_v2/02_architecture/DATA_FLOW.md` | SignalFilter WPSQF default OFF | **MATCHES_CODE** | |")
    a("| `docs_v2/02_architecture/MODULE_MAP.md` | SignalFilter YES (pass-through when OFF) | **MATCHES_CODE** | |")
    a("| `docs_v2/03_runtime/LIVE_LOOP.md` | Six stages; default market XAUUSD_i:M5 | **MATCHES_CODE** | |")
    a("| `docs_v2/03_runtime/CONFIGURATION.md` | TIMEFRAMES list 5m/15m/4h overridden to 5m when router on | **MATCHES_CODE** | |")
    a("| `docs_v2/04_strategy/ACTIVE_STRATEGIES.md` | Live selected = priceaction; kernel TFs `[\"5m\"]` | **MATCHES_CODE** | |")
    a("| `docs_v2/05_risk/RISKGATE_SPEC.md` | Ordered gate list; meta observer never rejects | **MATCHES_CODE** | Spot-checked against `RiskGate.evaluate` structure |")
    a("| `docs_v2/05_risk/RISK.md` | Max positions 3/2 | **MATCHES_CODE** | Matches live.py defaults |")
    a("| `docs_v2/01_truth/CURRENT_STATE.md` | Six stages; SignalFilter default OFF | **MATCHES_CODE** | |")
    a("| `docs_v2/01_truth/KNOWN_ISSUES.md` | Notes 5-stage vs 6-stage; M5-only residual wording | **MATCHES_CODE** (as issue registry) | |")
    a("| `docs/CAPABILITIES.md` §1 | Kernel M5-only when router on; also says \"pipeline ۵ مرحله\" | **CONTRADICTS_CODE** (stage count) / **MATCHES_CODE** (M5 forcing) | Mixed; stage claim stale |")
    a("| `docs/ARCHITECTURE_FA.md` | Comment `pipeline 5-stage` | **CONTRADICTS_CODE** | Should be 6 with SignalFilter |")
    a("| `docs/WHITEBOARD_FA.md` | Pipeline diagram: داده→اندیکاتور→سیگنال→ریسک→اجرا (5) | **CONTRADICTS_CODE** | Omits SignalFilter |")
    a("| `docs/ONBOARDING_FA.md` | Describes M5/M15/H4 as live TFs without M5-only force | **CONTRADICTS_CODE** (live cycle TFs) / **STALE_HISTORICAL** for multi-TF presets | Presets still exist; kernel cycle is M5 when router on |")
    a("| `دستورات_اجرایی.md` (repo root) | TF = M5+M15+H4 همزمان; max pos 3/2; risk 0.5% | **CONTRADICTS_CODE** on simultaneous TFs; **MATCHES_CODE** on risk/caps | Entry-doc still teaches multi-TF live loop |")
    a("| `docs/robot_behavior_audit/*` | Six-stage flow; TIMEFRAME_CONFIGS unused | **MATCHES_CODE** | Prior audit; still accurate on dead TIMEFRAME_CONFIGS |")
    a("| `docs/PHASE*.md` / `docs_v2/02_research/PHASE*.md` / most `docs_v2/01_truth/PHASE27_*.md` | Point-in-time research closures | **STALE_HISTORICAL** | Not current operator runbooks; retain as research archive |")
    a("| `docs_v2/_system/*`, `99_change_control/*` | Process/schema | N/A (meta-docs) | Not runtime claims |")
    a("")

    a("### Known examples — explicit verification")
    a("")
    a("1. **Pipeline 5 vs 6 / SignalFilterStage:** Code registers six stages including `SignalFilterStage`. Canonical `docs_v2` architecture/truth docs match. Several Persian onboarding/architecture docs still say five stages → **CONTRADICTS_CODE**.")
    a("2. **Live timeframes M5-only vs M5/M15/H4:** With default `MULTI_ENGINE_ROUTER_ENABLED=true`, `get_live_config()` sets `TIMEFRAMES=[\"5m\"]`. Root ops doc and parts of ONBOARDING still imply concurrent M5/M15/H4 → **CONTRADICTS_CODE** for the live kernel cycle. Per-TF presets remain in code for backtest/other modes.")
    a("3. **TIMEFRAME_CONFIGS:** Defined in `live.py`; `get_timeframe_config()` has **no** callers in live/backtest paths → **dead configuration** (matches prior `docs/robot_behavior_audit/dead_features.md`).")
    a("")

    a("## 4. Config / flag inventory")
    a("")
    a("### 4.1 `tradingbot/config/live.py` env-driven flags")
    a("")
    a("| Env key | Config key | Default | Status | Phase/doc justification (from nearby comment) | Productionish consumers (sample) |")
    a("|---------|------------|---------|--------|-----------------------------------------------|----------------------------------|")
    for f in flags:
        prod = ", ".join(f"`{p}`" for p in f.get("productionish_files", [])[:5]) or "—"
        comment = (f.get("nearby_comment") or "").replace("|", "\\|")
        a(
            f"| `{f['env_key']}` | `{f.get('config_key') or '—'}` | `{f.get('default_expr') or '—'}` | **{f.get('status')}** | {comment[:120]} | {prod} |"
        )
    a("")
    a("Notable **DEFINED_ONLY** findings:")
    a("")
    a("- `VOL_DIRECTION_FILTER_ENABLED` — only assigned in `live.py`; **no other code references** the key (dead flag; Phase 48A comment says keep OFF).")
    a("- `TRADINGBOT_REAL_SYMBOL` — read only inside `live.py` to build `SYMBOL_BY_ENVIRONMENT` (wired indirectly via that dict; no other getenv sites).")
    a("- `EMAIL_USERNAME` / `EMAIL_TO` / `EMAIL_FROM` — defined into config; no non-live consumers found via key scan (email path may be unused).")
    a("")

    a("### 4.2 Other important env flags (outside live.py)")
    a("")
    a("| Env key | Default | Where read | Role |")
    a("|---------|---------|------------|------|")
    a("| `TRADINGBOT_SIGNAL_FILTER` | `OFF` | `services/signal_filter_mode.py` | Enables WPSQF SignalFilterStage |")
    a("| `TRADINGBOT_WPSQF_THRESHOLD` | (unset → 77.56) | `services/signal_filter_mode.py` | WPSQF score threshold |")
    a("| `TRADINGBOT_PROP_PRESET` / `PROP_FIRM_PRESET` | empty | `config/prop_presets.py` | Prop firm overlays via `get_live_config()` |")
    a("| `TRADING_BOT_BASE_DIR` | unset | `config/engine_settings.py` | Base directory override |")
    a("")
    a(f"Repo-wide getenv scan: **{getenv['total_getenv_sites']}** sites, **{getenv['unique_keys']}** unique keys (see `tools/audit/out/getenv_inventory.json`).")
    a("")
    a("### 4.3 Dead / unused config objects")
    a("")
    a("| Object | Verdict | Evidence |")
    a("|--------|---------|----------|")
    a("| `TIMEFRAME_CONFIGS` / `get_timeframe_config()` | **UNUSED** in live & backtest paths | Only definitions in `live.py`; research string mention in `ml/research/phase22b/...` |")
    a("| `STRATEGY_CONFIGS` | Empty dict | `live.py` |")
    a("| `DEMO_MODE` config key | Printed in validate/print helpers; does **not** block `--execute` | Aligns with CX-005 in known unknowns |")
    a("| Hardcoded MT5 defaults in `engine_settings.py` | Security smell (credential-like defaults present in source) | Do not echo secrets; recommend removal in a later hardening phase |")
    a("")

    a("## 5. Recommended next actions (NO EXECUTION)")
    a("")
    a("Each item is a discrete human-approvable unit. **Do not execute in this phase.**")
    a("")
    a("1. **Fix operator docs that contradict live TF/stage truth** — Edit `دستورات_اجرایی.md`, `docs/ONBOARDING_FA.md`, `docs/ARCHITECTURE_FA.md`, `docs/WHITEBOARD_FA.md`, and the stage-count line in `docs/CAPABILITIES.md` so they state: six pipeline stages (incl. SignalFilter pass-through) and M5-only kernel cycle when router default is on.")
    a("2. **Archive research Python bulk** — Move the 419 `RESEARCH_ARCHIVE_CANDIDATE` unreachable modules under e.g. `archive/research_py/` (or leave in place but exclude from default tooling). Prefer path-preserving git mv so history remains.")
    a("3. **Human-triage the 96 DEAD_CODE files** — Split into (a) keep as manual ops tools (e.g. `scripts/clear_emergency_stop.py`, diagnose helpers), (b) archive one-off `_patch*` / `_write_*` scripts, (c) delete only with explicit approval.")
    a("4. **Remove or quarantine dead config** — Delete or clearly `# UNUSED` mark `TIMEFRAME_CONFIGS` / `get_timeframe_config()` and `VOL_DIRECTION_FILTER_ENABLED` after confirming no dynamic getattr consumers.")
    a("5. **Credential hygiene** — Remove hardcoded MT5 credential defaults from `tradingbot/config/engine_settings.py` (replace with empty/required-env); rotate any credentials that ever lived in source; do not commit `.env`.")
    a("6. **Reduce TEST_ONLY surface carefully** — 894 modules are test-reachable only; many are intentional research harnesses covered by tests. Do not mass-delete; instead tag ownership (research vs production) in a manifest.")
    a("7. **Entry-point inventory expansion** — Add intentionally kept ops scripts to `دستورات_اجرایی.md` / `start/*.bat` so future reachability audits do not flag them as dead.")
    a("8. **Re-run this audit's pytest baseline after any cleanup phase** — Compare to `docs/AUDIT_1_BASELINE_TEST_RESULTS.md` before merging deletions.")
    a("9. **Optional: mark `docs/PHASE*.md` as historical** — Add a banner or move to `docs/archive/phases/` so operators default to `docs_v2/01_truth/*` + `docs_v2/03_runtime/*`.")
    a("10. **Collection error in `tests/test_accounting.py`** — Fix package/`PYTHONPATH` collection so `tradingbot` imports resolve when the file is collected (baseline recorded a collection ERROR).")
    a("")

    a("## 6. Integrity confirmation")
    a("")
    a("- This phase created/updated only: `docs/AUDIT_1_*.md`, `tools/audit/**`, and under `logs/_audit1_*` / `tools/audit/out/**` analysis outputs.")
    a("- No files under `tradingbot/` production packages were modified by this audit phase.")
    a("- Phase 40 frozen tape was not touched.")
    a("- No MT5 connection, `.env` read, or order placement was performed for this audit.")
    a("")
    a(f"**Totals:** inventory scanned **{summary['inventory_count']}** `.py` files; flagged unreachable **{summary['unreachable_count']}** "
      f"(DEAD_CODE **{flag_counts.get('DEAD_CODE', 0)}**, RESEARCH_ARCHIVE_CANDIDATE **{flag_counts.get('RESEARCH_ARCHIVE_CANDIDATE', 0)}**); "
      f"TEST_ONLY-via-tests **{len(test_only)}**; markdown files listed **{md_files['docs_count'] + md_files['docs_v2_count']}**.")
    a("")

    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT} ({REPORT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
