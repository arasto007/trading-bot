"""Phase 34 — statistical evidence, bootstrap, and Monte Carlo.

RESEARCH ONLY. Uses Phase 30 RAW, Phase 31 event grouping, and Phase 32
chronological folds. Signal-level results are never presented as independent
evidence. No production change, no optimization.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
    MIN_RESOLVED_FOR_SUFFICIENCY,
    UNKNOWN,
)
from tradingbot.backtest.phase28_3_monte_carlo import (
    LARGE_DD_R,
    MIN_TRADES_FOR_ROBUSTNESS,
    RUIN_DD_R,
    path_metrics,
    summarize_paths,
)
from tradingbot.backtest.phase30_unchanged_strategy_evaluation import PHASE30_JSON, event_representatives
from tradingbot.backtest.phase31_event_independence import PHASE31_JSON
from tradingbot.backtest.phase32_walk_forward import FOLD_NAMES, PHASE32_JSON

PHASE = "34"
PHASE34_JSON = "logs/phase34_statistical_validation.json"
PHASE34_MD = "docs_v2/02_research/PHASE34_STATISTICAL_VALIDATION.md"
EVALUATOR_VERSION = "phase34-stats-v1"
RNG_SEED = 340034
N_PATHS = 2000
PERCENTILES = (5, 25, 50, 75, 95)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "dataset_fingerprint",
    "units",
    "bootstrap",
    "monte_carlo",
    "null_checks",
    "multiple_testing",
    "conclusion",
    "FINAL_GATE",
    "phase_35_started",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_head(base_dir: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return UNKNOWN


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def observed_metrics(r_values: list[float]) -> dict[str, Any]:
    rs = [float(x) for x in r_values]
    path = path_metrics(rs)
    return {
        "n": len(rs),
        "mean_R": path["expectancy_R"],
        "expectancy_R": path["expectancy_R"],
        "median_R": float(np.median(rs)) if rs else None,
        "WR": path["win_rate"],
        "PF": path["profit_factor"],
        "max_DD_R": path["max_drawdown_R"],
        "loss_streak": int(path["longest_losing_streak"]),
        "final_R": path["final_R"],
        "wins": int(path["wins"]),
        "losses": int(path["losses"]),
    }


def path_metrics_ext(r_seq: list[float] | np.ndarray) -> dict[str, float]:
    seq = np.asarray(r_seq, dtype=float)
    m = path_metrics(seq)
    m["median_R"] = float(np.median(seq)) if len(seq) else 0.0
    m["mean_R"] = m["expectancy_R"]
    return m


def run_bootstrap_ext(r_values: list[float], rng: np.random.Generator, n_paths: int) -> list[dict[str, float]]:
    base = np.asarray(r_values, dtype=float)
    n = len(base)
    if n == 0:
        return []
    paths = []
    for _ in range(n_paths):
        seq = rng.choice(base, size=n, replace=True)
        paths.append(path_metrics_ext(seq))
    return paths


def run_shuffle_ext(r_values: list[float], rng: np.random.Generator, n_paths: int) -> list[dict[str, float]]:
    base = np.asarray(r_values, dtype=float)
    paths = []
    for _ in range(n_paths):
        paths.append(path_metrics_ext(rng.permutation(base)))
    return paths


def run_sign_flip_null(r_values: list[float], rng: np.random.Generator, n_paths: int) -> list[dict[str, float]]:
    mags = np.abs(np.asarray(r_values, dtype=float))
    paths = []
    for _ in range(n_paths):
        signs = rng.choice(np.array([-1.0, 1.0]), size=len(mags))
        paths.append(path_metrics_ext(mags * signs))
    return paths


def summarize_ext(paths: list[dict[str, float]]) -> dict[str, Any]:
    if not paths:
        return {"n_paths": 0}
    block = summarize_paths(paths)
    meds = [p["median_R"] for p in paths]
    means = [p["mean_R"] for p in paths]
    block["mean_R"] = {
        "median": float(np.median(means)),
        "p5": float(np.percentile(means, 5)),
        "p25": float(np.percentile(means, 25)),
        "p75": float(np.percentile(means, 75)),
        "p95": float(np.percentile(means, 95)),
    }
    block["median_R"] = {
        "median": float(np.median(meds)),
        "p5": float(np.percentile(meds, 5)),
        "p25": float(np.percentile(meds, 25)),
        "p75": float(np.percentile(meds, 75)),
        "p95": float(np.percentile(meds, 95)),
    }
    n = max(len(paths), 1)
    block["prob_expectancy_negative"] = float(sum(1 for p in paths if p["expectancy_R"] < 0) / n)
    block["prob_mean_R_negative"] = block["prob_expectancy_negative"]
    return block


def ci_contains_zero(dist: dict[str, Any] | None) -> bool | None:
    if not dist or dist.get("p5") is None or dist.get("p95") is None:
        return None
    return float(dist["p5"]) <= 0.0 <= float(dist["p95"])


def load_books(root: Path) -> dict[str, Any]:
    p30 = _safe_load_json(root / PHASE30_JSON) or {}
    p31 = _safe_load_json(root / PHASE31_JSON) or {}
    p32 = _safe_load_json(root / PHASE32_JSON) or {}
    if not (p30 and p31 and p32):
        raise FileNotFoundError("Phase 30, 31, and 32 artifacts are required")
    for payload, name in ((p30, "30"), (p31, "31"), (p32, "32")):
        if payload.get("dataset_fingerprint") != EXPECTED_CANONICAL_FINGERPRINT:
            raise RuntimeError(f"Phase {name} fingerprint is not the frozen canonical tape")
    raw = list((p30.get("raw_signal_book") or {}).get("rows") or [])
    cls = {str(r["timestamp"]): r["mechanical_event_id"] for r in (p31.get("signal_classifications") or [])}
    if len(raw) != 24:
        raise RuntimeError("Phase 30 RAW book is not the frozen 24-setup set")
    rows = []
    for r in raw:
        item = dict(r)
        item["mechanical_event_id"] = cls[str(r["timestamp"])]
        item["event_cluster_id"] = item["mechanical_event_id"]
        rows.append(item)
    events = event_representatives(rows)
    signal_r = [float(r["theoretical_R"]) for r in rows]
    event_r = [float(e["theoretical_R"]) for e in events]
    folds = {}
    for name in FOLD_NAMES:
        f = (p32.get("folds") or {}).get(name) or {}
        folds[name] = {
            "setups": int(f.get("setups") or 0),
            "events": int(f.get("events") or 0),
            "expectancy": f.get("expectancy"),
            "WR": f.get("WR"),
            "insufficient_sample": bool(f.get("insufficient_sample")),
        }
    return {
        "rows": rows,
        "events": events,
        "signal_r": signal_r,
        "event_r": event_r,
        "calendar_days": float(((p30.get("raw_signal_book") or {}).get("performance") or {}).get("calendar_days") or 14.8785),
        "phase31_grade": (p31.get("dependence_grade") or {}).get("grade") or (p31.get("conclusion") or {}).get("verdict"),
        "phase32_verdict": (p32.get("conclusion") or {}).get("verdict"),
        "folds": folds,
        "n_events": len(event_r),
    }


def unit_block(name: str, r_values: list[float], *, independent_evidence: bool, seed: int) -> dict[str, Any]:
    rng_b = np.random.default_rng(seed)
    rng_s = np.random.default_rng(seed + 1)
    rng_n = np.random.default_rng(seed + 2)
    obs = observed_metrics(r_values)
    boot = run_bootstrap_ext(r_values, rng_b, N_PATHS)
    shuf = run_shuffle_ext(r_values, rng_s, N_PATHS)
    null = run_sign_flip_null(r_values, rng_n, N_PATHS)
    boot_sum = summarize_ext(boot)
    shuf_sum = summarize_ext(shuf)
    null_sum = summarize_ext(null)
    naive_p = None
    if null:
        naive_p = float(sum(1 for p in null if p["expectancy_R"] <= obs["expectancy_R"]) / len(null))
    return {
        "unit": name,
        "independent_evidence": independent_evidence,
        "n": len(r_values),
        "observed": obs,
        "bootstrap": boot_sum,
        "shuffle_monte_carlo": shuf_sum,
        "sign_flip_null": {
            **null_sum,
            "descriptive_tail_prob_exp_le_observed": naive_p,
            "not_a_classical_p_value": True,
            "not_multiple_testing_corrected": True,
            "do_not_interpret_as_significance": True,
        },
        "ci_expectancy_contains_zero": ci_contains_zero(boot_sum.get("expectancy_R")),
        "ci_mean_contains_zero": ci_contains_zero(boot_sum.get("mean_R")),
    }


def evaluate_stats(loaded: dict[str, Any]) -> dict[str, Any]:
    signal = unit_block("signal_level", loaded["signal_r"], independent_evidence=False, seed=RNG_SEED)
    event = unit_block("event_level", loaded["event_r"], independent_evidence=True, seed=RNG_SEED + 100)
    fold_notes = {}
    for name, f in loaded["folds"].items():
        fold_notes[name] = {
            **f,
            "bootstrap_interpreted": False,
            "reason": "Fold n is below Phase 28.2/28.3 floors; chronological description only.",
        }
    return {
        "units": {
            "signal_level": {
                "n": signal["n"],
                "independent_evidence": False,
                "reason": "Phase 31 HIGH_DEPENDENCE. 24 RAW rows are not 24 independent observations.",
            },
            "event_level": {
                "n": event["n"],
                "independent_evidence": True,
                "reason": "Mechanical event = (UTC date, Asian high, Asian low, side). Correct inferential unit.",
                "still_insufficient": event["n"] < MIN_RESOLVED_FOR_SUFFICIENCY,
            },
        },
        "bootstrap": {
            "methodology": (
                "IID nonparametric bootstrap of the stored R series with replacement. "
                "Event-level resamples event-representative R (earliest official signal). "
                "Signal-level resamples 24 dependent R and is not independent evidence. "
                f"{N_PATHS} paths, numpy Generator seed {RNG_SEED}."
            ),
            "seed": RNG_SEED,
            "n_paths": N_PATHS,
            "signal_level": signal,
            "event_level": event,
        },
        "monte_carlo": {
            "methodology": (
                "Deterministic seeded simulations on stored R only. No OHLC re-walk. "
                "Shuffle permutes order (expectancy invariant; DD/streak path metrics). "
                "Bootstrap (above) is the resampling Monte Carlo. "
                f"P(maxDD >= {LARGE_DD_R}R) and P(maxDD >= {RUIN_DD_R}R) are descriptive "
                "drawdown thresholds, not broker-margin ruin."
            ),
            "seed": RNG_SEED,
            "n_paths": N_PATHS,
            "ohlc_rewalked": False,
            "broker_margin_ruin_model": False,
            "signal_level_shuffle": signal["shuffle_monte_carlo"],
            "event_level_shuffle": event["shuffle_monte_carlo"],
            "signal_level_bootstrap": signal["bootstrap"],
            "event_level_bootstrap": event["bootstrap"],
            "not_broker_margin_ruin": True,
        },
        "null_checks": {
            "overstatement_forbidden": True,
            "signal_level": {
                "sign_flip_null": signal["sign_flip_null"],
                "independent_evidence": False,
            },
            "event_level": {
                "sign_flip_null": event["sign_flip_null"],
                "bootstrap_ci_expectancy_contains_zero": event["ci_expectancy_contains_zero"],
                "note": (
                    "Sign-flip preserves |R| and randomizes direction. "
                    "The tail probability is descriptive only — not a classical p-value, "
                    "not valid under a 6-event sample, not multiple-testing corrected."
                ),
            },
            "chronological_folds": fold_notes,
        },
        "multiple_testing": {
            "parameter_search_in_phases_30_to_33": False,
            "production_parameters_changed": False,
            "retroactive_optimization": False,
            "sequential_research_phases": True,
            "many_descriptive_metrics_inspected": True,
            "family_wise_error_controlled": False,
            "pre_registered_primary_endpoint": False,
            "note": (
                "Phases 28–33 reported many descriptive metrics on the same 24-setup book "
                "(RAW, event, folds, SL/RR/cost diagnostics, dependence). No parameter was "
                "searched or optimized. Sequential inspection still consumes researcher "
                "degrees of freedom. A single favorable interval or tail probability on this "
                "tape is not STATISTICALLY_SUPPORTED."
            ),
        },
    }


def classify_conclusion(loaded: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    n = len(loaded["signal_r"])
    events = loaded["n_events"]
    days = loaded["calendar_days"]
    floors = {
        "resolved_signals": {
            "value": n,
            "required": MIN_RESOLVED_FOR_SUFFICIENCY,
            "pass": n >= MIN_RESOLVED_FOR_SUFFICIENCY,
        },
        "unique_events": {
            "value": events,
            "required": MIN_RESOLVED_FOR_SUFFICIENCY,
            "pass": events >= MIN_RESOLVED_FOR_SUFFICIENCY,
        },
        "calendar_days": {
            "value": days,
            "required": MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
            "pass": days >= MIN_CALENDAR_DAYS_FOR_SUFFICIENCY,
        },
        "robustness_n": {
            "value": n,
            "required": MIN_TRADES_FOR_ROBUSTNESS,
            "pass": n >= MIN_TRADES_FOR_ROBUSTNESS,
        },
    }
    insufficient = any(not v["pass"] for v in floors.values())
    event_ci_zero = audit["bootstrap"]["event_level"]["ci_expectancy_contains_zero"]
    if insufficient:
        verdict = "INSUFFICIENT_SAMPLE"
        text = (
            "INSUFFICIENT_SAMPLE. Official inferential unit is the mechanical event "
            f"(n={events}); signal-level n={n} is dependent (Phase 31 HIGH_DEPENDENCE). "
            f"Floors: resolved/events >= {MIN_RESOLVED_FOR_SUFFICIENCY}, calendar days >= "
            f"{MIN_CALENDAR_DAYS_FOR_SUFFICIENCY}, Phase 28.3 robustness n >= "
            f"{MIN_TRADES_FOR_ROBUSTNESS}. Tape is ~{days:.1f} days. Bootstrap/MC "
            "distributions are descriptive. They do not support STATISTICALLY_SUPPORTED "
            "or NOT_STATISTICALLY_SUPPORTED. One favorable metric is not significance. "
            "Shuffle DD thresholds are not broker-margin ruin."
        )
    elif event_ci_zero:
        verdict = "NOT_STATISTICALLY_SUPPORTED"
        text = "Event-level 5–95% expectancy interval includes 0. No statistical support for a nonzero edge."
    else:
        verdict = "INDETERMINATE"
        text = "Sample floors passed but sequential unregistered metrics forbid STATISTICALLY_SUPPORTED."
    return {
        "verdict": verdict,
        "edge_supported": False,
        "statistical_significance_claimed": False,
        "signal_level_is_independent_evidence": False,
        "floors": floors,
        "event_ci_expectancy_contains_zero": event_ci_zero,
        "text": text,
    }


def _fmt_dist(d: dict[str, Any] | None) -> str:
    if not d:
        return "n/a"
    return f"med {d.get('median')} / p5 {d.get('p5')} / p95 {d.get('p95')}"


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    b = payload["bootstrap"]
    sig = b["signal_level"]
    ev = b["event_level"]
    path = root / PHASE34_MD
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""# Phase 34 — Statistical Evidence, Bootstrap & Monte Carlo

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Conclusion:** `{payload["conclusion"]["verdict"]}`
**Live trading authorized:** NO
**Parameters optimized / searched:** NO
**Strategy/RiskGate/ML changed:** NO
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`

STOP AFTER PHASE 34. DO NOT START PHASE 35.

Data: Phase 30 RAW, Phase 31 mechanical events, Phase 32 chronological folds.
Fingerprint `{payload.get("dataset_fingerprint")}`.

---

## Units

- **Signal-level** n={sig["n"]}: **not** independent evidence (Phase 31 HIGH_DEPENDENCE).
- **Event-level** n={ev["n"]}: official inferential unit. Still below the 30-event floor.

## Bootstrap

Seed `{b["seed"]}`, paths `{b["n_paths"]}`. IID resample of stored R. Event-level resamples event representatives.

| Metric | Signal-level (not independent) | Event-level |
|---|---|---|
| Observed expectancy | {sig["observed"]["expectancy_R"]} | {ev["observed"]["expectancy_R"]} |
| Expectancy dist | {_fmt_dist(sig["bootstrap"].get("expectancy_R"))} | {_fmt_dist(ev["bootstrap"].get("expectancy_R"))} |
| Mean R dist | {_fmt_dist(sig["bootstrap"].get("mean_R"))} | {_fmt_dist(ev["bootstrap"].get("mean_R"))} |
| Median R dist | {_fmt_dist(sig["bootstrap"].get("median_R"))} | {_fmt_dist(ev["bootstrap"].get("median_R"))} |
| WR dist | {_fmt_dist(sig["bootstrap"].get("win_rate"))} | {_fmt_dist(ev["bootstrap"].get("win_rate"))} |
| PF dist | {_fmt_dist(sig["bootstrap"].get("profit_factor"))} | {_fmt_dist(ev["bootstrap"].get("profit_factor"))} |
| Max DD dist | {_fmt_dist(sig["bootstrap"].get("max_drawdown_R"))} | {_fmt_dist(ev["bootstrap"].get("max_drawdown_R"))} |
| Loss streak dist | {_fmt_dist(sig["bootstrap"].get("longest_losing_streak"))} | {_fmt_dist(ev["bootstrap"].get("longest_losing_streak"))} |
| P(exp < 0) | {sig["bootstrap"].get("prob_expectancy_negative")} | {ev["bootstrap"].get("prob_expectancy_negative")} |
| CI contains 0 | {sig.get("ci_expectancy_contains_zero")} | {ev.get("ci_expectancy_contains_zero")} |

## Monte Carlo

{payload["monte_carlo"]["methodology"]}

Shuffle P(final R < 0) signal `{sig["shuffle_monte_carlo"].get("prob_final_R_negative")}` / event `{ev["shuffle_monte_carlo"].get("prob_final_R_negative")}`.  
P(DD ≥ 10R) / P(DD ≥ 20R) are **not** broker-margin ruin.

## Null checks

Sign-flip null tail probabilities are **not** classical p-values and are **not** significance.  
Phase 32 folds remain INSUFFICIENT_SAMPLE; they are not bootstrapped as evidence.

## Multiple testing

{payload["multiple_testing"]["note"]}

No retroactive optimization. No production change.

## CONCLUSION

**{payload["conclusion"]["verdict"]}**

{payload["conclusion"]["text"]}

## Safety

No MT5 trading, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 35 was **not** started.
""",
        encoding="utf-8",
    )


def run_phase34_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical M5 fingerprint changed — Phase 34 refuses to proceed")
    loaded = load_books(root)
    pass_a = evaluate_stats(loaded)
    pass_b = evaluate_stats(loaded)

    def core(p: dict[str, Any]) -> dict[str, Any]:
        return {
            "sig": p["bootstrap"]["signal_level"]["bootstrap"]["expectancy_R"],
            "ev": p["bootstrap"]["event_level"]["bootstrap"]["expectancy_R"],
            "sig_dd": p["monte_carlo"]["signal_level_shuffle"]["max_drawdown_R"],
            "ev_dd": p["monte_carlo"]["event_level_shuffle"]["max_drawdown_R"],
        }

    if _stable_hash(core(pass_a)) != _stable_hash(core(pass_b)):
        raise RuntimeError("Phase 34 evaluation is not deterministic")

    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    conclusion = classify_conclusion(loaded, pass_a)
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": "PASS_WITH_DEFERRAL",
        "research_only": True,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "parameters_searched": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "silent_xauusd_mapping": False,
        "ev_eq_01": "NOT_PROVEN",
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "dataset": CANONICAL_PARQUET,
        "dataset_fingerprint": fp,
        "phase31_dependence": loaded["phase31_grade"],
        "phase32_verdict": loaded["phase32_verdict"],
        "calendar_days": loaded["calendar_days"],
        **pass_a,
        "conclusion": conclusion,
        "reproducibility": {
            "passes": 2,
            "passes_match": True,
            "data_fingerprint": fp,
            "evaluator_fingerprint": EVALUATOR_VERSION,
            "rng_seed": RNG_SEED,
            "n_paths": N_PATHS,
            "output_fingerprint": _stable_hash(core(pass_a)),
        },
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "PHASE_35_STARTED": False,
        },
        "phase_35_started": False,
    }
    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after
    _write_json(root / PHASE34_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Statistical validation (Phase 34)"
        block = (
            "\n\n## Statistical validation (Phase 34)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| Signal-level bootstrap is independent evidence | **NO** — HIGH_DEPENDENCE |\n"
            "| Event-level n=6 supports significance | **NO** — INSUFFICIENT_SAMPLE |\n"
            "| Shuffle DD is broker-margin ruin | **NO** |\n"
            "| Phase 34 authorizes live trading or optimization | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")
    return payload


if __name__ == "__main__":
    run_phase34_collection()
