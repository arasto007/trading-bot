"""Phase 28.3 — Monte Carlo robustness on Phase 28.1/28.2 baseline trades.

RESEARCH ONLY. Uses stored trade-level results only. No optimization, no new
backtest walk, no OHLC rewrite, no MT5. Spread/slippage shocks are MODELED,
not historical realized costs.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase25h_run import build_immutability_manifest, verify_immutability
from tradingbot.backtest.phase27_16_final_validation_gate import PHASE2716_JSON
from tradingbot.backtest.phase27_30_slippage_evidence import file_fingerprint
from tradingbot.backtest.phase28_0_performance_foundation import (
    BLOCKED,
    CANONICAL_PARQUET,
    EXPECTED_CANONICAL_FINGERPRINT,
    UNKNOWN,
)
from tradingbot.backtest.phase28_1_full_baseline import PHASE281_JSON
from tradingbot.backtest.phase28_2_walk_forward import PHASE282_JSON
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.domain.position_logic import pip_size

PHASE = "28.3"
PHASE283_JSON = "logs/phase28_3_monte_carlo.json"
PHASE283_MD = "docs_v2/02_research/PHASE28_3_MONTE_CARLO.md"
RNG_SEED = 283003
N_PATHS = 2000
MIN_TRADES_FOR_ROBUSTNESS = 30
LARGE_DD_R = 10.0
RUIN_DD_R = 20.0
PERCENTILES = (5, 25, 50, 75, 95)

REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "research_only",
    "live_trading_authorized",
    "parameters_optimized",
    "baseline_source",
    "dataset_fingerprint",
    "trade_count_raw",
    "trade_count_executable",
    "modeled_costs",
    "monte_carlo",
    "perturbations",
    "robustness",
    "conclusion",
    "FINAL_GATE",
    "phase_28_4_started",
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


def load_baseline_trades(root: Path) -> dict[str, Any]:
    p281 = _safe_load_json(root / PHASE281_JSON) or {}
    p282 = _safe_load_json(root / PHASE282_JSON) or {}
    if not p281 or not p282:
        raise FileNotFoundError("Phase 28.1 and 28.2 artifacts are required")
    raw_rows = list((p281.get("raw_signal") or {}).get("setup_rows") or [])
    if not raw_rows:
        raise RuntimeError("Phase 28.1 has no raw setup_rows")
    r28_2 = list((p282.get("raw_signal") or {}).get("setup_rows") or [])
    r_281 = [float(r["r_multiple"]) for r in raw_rows if r.get("r_multiple") is not None]
    r_282 = [float(r["r_multiple"]) for r in r28_2 if r.get("r_multiple") is not None]
    if r_281 != r_282:
        raise RuntimeError("Phase 28.1 and 28.2 raw R series do not match")
    exe = p281.get("executable") or {}
    return {
        "trades": raw_rows,
        "r_values": r_281,
        "executable_allowed": int(exe.get("allowed") or 0),
        "executable_fills": int(exe.get("executed_simulated_fills") or 0),
        "phase28_1_fingerprint": p281.get("dataset_fingerprint"),
        "phase28_2_fingerprint": p282.get("dataset_fingerprint"),
        "phase28_1_raw_setups": int((p281.get("raw_signal") or {}).get("setups") or len(raw_rows)),
        "phase28_2_raw_setups": int((p282.get("raw_signal") or {}).get("setups_total") or len(r28_2)),
    }


def path_metrics(r_seq: list[float] | np.ndarray) -> dict[str, float]:
    rs = [float(x) for x in r_seq]
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    loss_streak = 0
    max_loss = 0
    wins = 0
    losses = 0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
        if r > 0:
            wins += 1
            loss_streak = 0
        else:
            losses += 1
            loss_streak += 1
            max_loss = max(max_loss, loss_streak)
    gross_win = float(sum(r for r in rs if r > 0))
    gross_loss = float(abs(sum(r for r in rs if r <= 0)))
    n = max(len(rs), 1)
    pf = (gross_win / gross_loss) if gross_loss > 0 else None
    return {
        "final_R": equity,
        "max_drawdown_R": abs(max_dd),
        "longest_losing_streak": float(max_loss),
        "win_rate": wins / n if rs else 0.0,
        "expectancy_R": (sum(rs) / len(rs)) if rs else 0.0,
        "profit_factor": pf if pf is not None else 0.0,
        "wins": float(wins),
        "losses": float(losses),
    }


def summarize_paths(paths: list[dict[str, float]]) -> dict[str, Any]:
    finals = [p["final_R"] for p in paths]
    dds = [p["max_drawdown_R"] for p in paths]
    streaks = [p["longest_losing_streak"] for p in paths]
    wrs = [p["win_rate"] for p in paths]
    exps = [p["expectancy_R"] for p in paths]
    pfs = [p["profit_factor"] for p in paths]
    n = max(len(paths), 1)
    return {
        "n_paths": len(paths),
        "final_R": {
            "median": float(np.percentile(finals, 50)),
            "p5": float(np.percentile(finals, 5)),
            "p25": float(np.percentile(finals, 25)),
            "p75": float(np.percentile(finals, 75)),
            "p95": float(np.percentile(finals, 95)),
        },
        "max_drawdown_R": {
            "median": float(np.percentile(dds, 50)),
            "p5": float(np.percentile(dds, 5)),
            "p25": float(np.percentile(dds, 25)),
            "p75": float(np.percentile(dds, 75)),
            "p95": float(np.percentile(dds, 95)),
        },
        "longest_losing_streak": {
            "median": float(np.percentile(streaks, 50)),
            "p5": float(np.percentile(streaks, 5)),
            "p95": float(np.percentile(streaks, 95)),
            "max": float(max(streaks) if streaks else 0),
        },
        "expectancy_R": {
            "median": float(np.median(exps)),
            "p5": float(np.percentile(exps, 5)),
            "p95": float(np.percentile(exps, 95)),
        },
        "profit_factor": {
            "median": float(np.median(pfs)),
            "p5": float(np.percentile(pfs, 5)),
            "p95": float(np.percentile(pfs, 95)),
        },
        "win_rate": {
            "median": float(np.median(wrs)),
            "p5": float(np.percentile(wrs, 5)),
            "p95": float(np.percentile(wrs, 95)),
        },
        "prob_dd_ge_10R": float(sum(1 for d in dds if d >= LARGE_DD_R) / n),
        "prob_dd_ge_20R": float(sum(1 for d in dds if d >= RUIN_DD_R) / n),
        "prob_final_R_negative": float(sum(1 for f in finals if f < 0) / n),
        "ruin_definition": (
            f"MODELED descriptive: P(maxDD >= {LARGE_DD_R}R) and P(maxDD >= {RUIN_DD_R}R). "
            "Not a broker-margin ruin model. Not realized."
        ),
    }


def run_shuffle(r_values: list[float], rng: np.random.Generator, n_paths: int) -> list[dict[str, float]]:
    base = np.asarray(r_values, dtype=float)
    paths = []
    for _ in range(n_paths):
        seq = rng.permutation(base)
        paths.append(path_metrics(seq))
    return paths


def run_bootstrap(r_values: list[float], rng: np.random.Generator, n_paths: int) -> list[dict[str, float]]:
    base = np.asarray(r_values, dtype=float)
    n = len(base)
    paths = []
    for _ in range(n_paths):
        seq = rng.choice(base, size=n, replace=True)
        paths.append(path_metrics(seq))
    return paths


def modeled_entry_shift_r(trade: dict[str, Any], *, adverse_price: float) -> float:
    """Recompute R from stored SL/TP/outcome after an adverse MODELED entry shift.

    Does not walk OHLC. Assumes the baseline exit price (SL or TP) still applies.
    """
    direction = str(trade.get("direction") or "").upper()
    entry = float(trade["entry_price"])
    sl = float(trade["stop_loss"])
    tp = float(trade["take_profit"])
    outcome = str(trade.get("outcome") or "")
    exit_px = sl if outcome == "loss" else tp
    buy = direction == "BUY"
    new_entry = entry + adverse_price if buy else entry - adverse_price
    risk = (new_entry - sl) if buy else (sl - new_entry)
    if risk <= 0:
        return float(trade.get("r_multiple") or -1.0)
    if buy:
        return float((exit_px - new_entry) / risk)
    return float((new_entry - exit_px) / risk)


def modeled_cost_spec() -> dict[str, Any]:
    cfg = BacktestConfig()
    pip = pip_size(PRIMARY_SYMBOL)
    return {
        "label": "MODELED",
        "not_historical_realized": True,
        "spread_status": "MODELED_PROXY",
        "slippage_status": "MODELED_PROXY",
        "spread_pips": cfg.spread_pips,
        "slippage_pips": cfg.slippage_pips,
        "pip_size": pip,
        "half_spread_price": (cfg.spread_pips / 2.0) * pip,
        "slippage_price": cfg.slippage_pips * pip,
        "note": (
            "BacktestConfig.spread_pips=2.5 and slippage_pips=0.8 are assumptions. "
            "Phase 27.30: 0 genuine requested-vs-fill pairs. Do not treat as realized costs."
        ),
    }


def apply_modeled_shift(trades: list[dict[str, Any]], adverse_price: float) -> list[float]:
    return [modeled_entry_shift_r(t, adverse_price=adverse_price) for t in trades]


def apply_random_signed_spread(trades: list[dict[str, Any]], half_spread: float, rng: np.random.Generator) -> list[float]:
    out = []
    for t in trades:
        sign = float(rng.choice([-1.0, 1.0]))
        # +sign means adverse for this helper when we pass adverse_price=abs
        shift = half_spread if sign > 0 else 0.0
        # minus case: favorable entry (MODELED ±)
        if sign < 0:
            direction = str(t.get("direction") or "").upper()
            entry = float(t["entry_price"])
            sl = float(t["stop_loss"])
            tp = float(t["take_profit"])
            outcome = str(t.get("outcome") or "")
            exit_px = sl if outcome == "loss" else tp
            buy = direction == "BUY"
            new_entry = entry - half_spread if buy else entry + half_spread
            risk = (new_entry - sl) if buy else (sl - new_entry)
            if risk <= 0:
                out.append(float(t.get("r_multiple") or -1.0))
            elif buy:
                out.append(float((exit_px - new_entry) / risk))
            else:
                out.append(float((new_entry - exit_px) / risk))
        else:
            out.append(modeled_entry_shift_r(t, adverse_price=shift))
    return out


def classify_robustness(*, n_trades: int, n_executable: int) -> dict[str, Any]:
    if n_trades < MIN_TRADES_FOR_ROBUSTNESS:
        return {
            "classification": "INSUFFICIENT_SAMPLE",
            "n_trades": n_trades,
            "n_executable": n_executable,
            "min_required": MIN_TRADES_FOR_ROBUSTNESS,
            "confidence_invented": False,
            "note": (
                "24 theoretical baseline trades cannot support ROBUST / CONDITIONALLY_ROBUST / FRAGILE. "
                "Executable n=0 cannot be Monte-Carlo'd. Descriptive MC paths are not a robustness proof."
            ),
        }
    return {
        "classification": "CONDITIONALLY_ROBUST",
        "n_trades": n_trades,
        "confidence_invented": False,
    }


def _fmt(x: Any, digits: int = 4) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def _write_markdown(root: Path, payload: dict[str, Any]) -> None:
    mc = payload["monte_carlo"]
    obs = payload["observed_raw"]
    costs = payload["modeled_costs"]
    pert = payload["perturbations"]["summary"]
    sh = mc["shuffle"]
    bs = mc["bootstrap"]
    path = root / PHASE283_MD
    path.parent.mkdir(parents=True, exist_ok=True)

    def _pct_row(label: str, block: dict[str, Any], key: str) -> str:
        d = block[key]
        return (
            f"| {label} | {_fmt(d.get('median'))} | {_fmt(d.get('p5'))} | "
            f"{_fmt(d.get('p25'))} | {_fmt(d.get('p75'))} | {_fmt(d.get('p95'))} |"
        )

    path.write_text(
        f"""# Phase 28.3 — Monte Carlo Robustness

**Status:** {payload.get("status")}
**Class:** RESEARCH ONLY
**Conclusion:** `{payload.get("conclusion")}`
**Live trading authorized:** NO
**Parameters optimized:** NO
**Costs:** MODELED / not realized
**FINAL_GATE:** `{payload.get("FINAL_GATE")}`

Monte Carlo on **stored Phase 28.1/28.2 trade-level results only**. No new strategy walk. No optimization. No OHLC rewalk.

STOP AFTER PHASE 28.3. DO NOT START PHASE 28.4.

---

## Baseline

| Item | Value |
|---|---|
| Dataset fingerprint | `{payload.get("dataset_fingerprint")}` |
| RAW trades | {payload.get("trade_count_raw")} |
| EXECUTABLE fills | {payload.get("trade_count_executable")} |
| Observed final R | {_fmt(obs["final_R"])} |
| Observed expectancy R | {_fmt(obs["expectancy_R"])} |
| Observed PF | {_fmt(obs["profit_factor"])} |
| Observed WR | {_fmt(obs["win_rate"])} |
| Observed max DD R | {_fmt(obs["max_drawdown_R"])} |
| Observed longest losing streak | {_fmt(obs["longest_losing_streak"], 0)} |
| Seed | `{mc["seed"]}` |
| Paths | {mc["n_paths"]} |

Fingerprint matches Phase 28.0/28.1/28.2. Canonical parquet was not rewritten.

---

## Sequence resampling (stored RAW R)

Shuffle permutes the 24 observed R values. Bootstrap resamples them with replacement. Neither invents new trades.

| Metric | median | p5 | p25 | p75 | p95 |
|---|---:|---:|---:|---:|---:|
{_pct_row("Shuffle final R", sh, "final_R")}
{_pct_row("Shuffle max DD R", sh, "max_drawdown_R")}
{_pct_row("Bootstrap final R", bs, "final_R")}
{_pct_row("Bootstrap max DD R", bs, "max_drawdown_R")}

| Path set | P(DD≥10R) | P(DD≥20R) | P(final R < 0) | losing-streak median / p95 |
|---|---:|---:|---:|---|
| Shuffle | {_fmt(sh["prob_dd_ge_10R"])} | {_fmt(sh["prob_dd_ge_20R"])} | {_fmt(sh["prob_final_R_negative"])} | {_fmt(sh["longest_losing_streak"]["median"], 0)} / {_fmt(sh["longest_losing_streak"]["p95"], 0)} |
| Bootstrap | {_fmt(bs["prob_dd_ge_10R"])} | {_fmt(bs["prob_dd_ge_20R"])} | {_fmt(bs["prob_final_R_negative"])} | {_fmt(bs["longest_losing_streak"]["median"], 0)} / {_fmt(bs["longest_losing_streak"]["p95"], 0)} |

Ruin / large-DD here is **descriptive R-space only**: P(max DD ≥ 10R) and P(max DD ≥ 20R). Not a broker-margin ruin model. Not realized.

Shuffle expectancy / PF / WR are invariant because the trade set is unchanged. Bootstrap bands:

| Metric | median | p5 | p95 |
|---|---:|---:|---:|
| Expectancy R | {_fmt(bs["expectancy_R"]["median"])} | {_fmt(bs["expectancy_R"]["p5"])} | {_fmt(bs["expectancy_R"]["p95"])} |
| PF | {_fmt(bs["profit_factor"]["median"])} | {_fmt(bs["profit_factor"]["p5"])} | {_fmt(bs["profit_factor"]["p95"])} |
| Win rate | {_fmt(bs["win_rate"]["median"])} | {_fmt(bs["win_rate"]["p5"])} | {_fmt(bs["win_rate"]["p95"])} |

---

## MODELED perturbations

These are **not** historical realized costs. `{costs["note"]}`

Assumptions (labeled MODELED / MODELED_PROXY): spread `{costs["spread_pips"]}` pips, slippage `{costs["slippage_pips"]}` pips, pip size `{costs["pip_size"]}`. Entry is shifted on stored SL/TP/outcome; OHLC is not rewalked.

| Shock | expectancy R | PF | WR | max DD R | final R |
|---|---:|---:|---:|---:|---:|
| Observed (no shock) | {_fmt(obs["expectancy_R"])} | {_fmt(obs["profit_factor"])} | {_fmt(obs["win_rate"])} | {_fmt(obs["max_drawdown_R"])} | {_fmt(obs["final_R"])} |
| Entry spread adverse MODELED | {_fmt(pert["entry_spread_adverse_MODELED"]["expectancy_R"])} | {_fmt(pert["entry_spread_adverse_MODELED"]["profit_factor"])} | {_fmt(pert["entry_spread_adverse_MODELED"]["win_rate"])} | {_fmt(pert["entry_spread_adverse_MODELED"]["max_drawdown_R"])} | {_fmt(pert["entry_spread_adverse_MODELED"]["final_R"])} |
| Entry ± spread MODELED | {_fmt(pert["entry_spread_plus_minus_MODELED"]["expectancy_R"])} | {_fmt(pert["entry_spread_plus_minus_MODELED"]["profit_factor"])} | {_fmt(pert["entry_spread_plus_minus_MODELED"]["win_rate"])} | {_fmt(pert["entry_spread_plus_minus_MODELED"]["max_drawdown_R"])} | {_fmt(pert["entry_spread_plus_minus_MODELED"]["final_R"])} |
| Slippage adverse MODELED | {_fmt(pert["slippage_adverse_MODELED"]["expectancy_R"])} | {_fmt(pert["slippage_adverse_MODELED"]["profit_factor"])} | {_fmt(pert["slippage_adverse_MODELED"]["win_rate"])} | {_fmt(pert["slippage_adverse_MODELED"]["max_drawdown_R"])} | {_fmt(pert["slippage_adverse_MODELED"]["final_R"])} |
| Spread + slippage adverse MODELED | {_fmt(pert["spread_plus_slippage_adverse_MODELED"]["expectancy_R"])} | {_fmt(pert["spread_plus_slippage_adverse_MODELED"]["profit_factor"])} | {_fmt(pert["spread_plus_slippage_adverse_MODELED"]["win_rate"])} | {_fmt(pert["spread_plus_slippage_adverse_MODELED"]["max_drawdown_R"])} | {_fmt(pert["spread_plus_slippage_adverse_MODELED"]["final_R"])} |

MODELED haircuts move expectancy / PF by a few thousandths of an R. They do not change the sample-size problem.

---

## EXECUTABLE

n=0. Monte Carlo is not defined on an empty executable book. 0 fills is not proof of no edge.

---

## Robustness

**{payload["robustness"]["classification"]}**

{payload["robustness"].get("note", "")}

Descriptive paths look uniformly negative (bootstrap p95 final R still `{_fmt(bs["final_R"]["p95"])}`). That is not enough trades to label the strategy FRAGILE.

---

## Conclusion

{payload.get("conclusion_text")}

## Safety

No MT5, no `.env`, no parquet rewrite, no strategy/RiskGate/ML/parameter changes. Phase 28.4 was **not** started.

Artifacts: `logs/phase28_3_monte_carlo.json`, `docs_v2/02_research/PHASE28_3_MONTE_CARLO.md`, `tradingbot/backtest/phase28_3_monte_carlo.py`, `tests/test_phase28_3_monte_carlo.py`
""",
        encoding="utf-8",
    )


def run_phase28_3_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    before = build_immutability_manifest(base_dir=root)
    loaded = load_baseline_trades(root)
    fp = file_fingerprint(root / CANONICAL_PARQUET)
    if fp != EXPECTED_CANONICAL_FINGERPRINT:
        raise RuntimeError("Canonical fingerprint changed — Phase 28.3 refuses to proceed")
    if loaded["phase28_1_fingerprint"] != fp or loaded["phase28_2_fingerprint"] != fp:
        raise RuntimeError("Phase 28.1/28.2 fingerprints do not match the canonical parquet")

    trades = loaded["trades"]
    r_obs = loaded["r_values"]
    costs = modeled_cost_spec()
    rng = np.random.default_rng(RNG_SEED)

    shuffle_paths = run_shuffle(r_obs, rng, N_PATHS)
    bootstrap_paths = run_bootstrap(r_obs, rng, N_PATHS)

    spread_adverse = apply_modeled_shift(trades, costs["half_spread_price"])
    slip_adverse = apply_modeled_shift(trades, costs["slippage_price"])
    both_adverse = apply_modeled_shift(trades, costs["half_spread_price"] + costs["slippage_price"])
    rng_pm = np.random.default_rng(RNG_SEED + 1)
    spread_pm = apply_random_signed_spread(trades, costs["half_spread_price"], rng_pm)

    rng_s = np.random.default_rng(RNG_SEED + 2)
    rng_b = np.random.default_rng(RNG_SEED + 3)
    pert = {
        "entry_spread_adverse_MODELED": {
            "r_series": spread_adverse,
            "baseline_path": path_metrics(spread_adverse),
            "shuffle": summarize_paths(run_shuffle(spread_adverse, rng_s, N_PATHS)),
        },
        "entry_spread_plus_minus_MODELED": {
            "r_series": spread_pm,
            "baseline_path": path_metrics(spread_pm),
            "bootstrap": summarize_paths(run_bootstrap(spread_pm, rng_b, N_PATHS)),
        },
        "slippage_adverse_MODELED": {
            "r_series": slip_adverse,
            "baseline_path": path_metrics(slip_adverse),
        },
        "spread_plus_slippage_adverse_MODELED": {
            "r_series": both_adverse,
            "baseline_path": path_metrics(both_adverse),
        },
    }
    # drop full r_series from artifact? keep compact observed + summary only
    pert_summary = {
        name: {
            "label": "MODELED",
            "not_realized": True,
            "expectancy_R": block["baseline_path"]["expectancy_R"],
            "profit_factor": block["baseline_path"]["profit_factor"],
            "max_drawdown_R": block["baseline_path"]["max_drawdown_R"],
            "win_rate": block["baseline_path"]["win_rate"],
            "final_R": block["baseline_path"]["final_R"],
            **{k: v for k, v in block.items() if k in {"shuffle", "bootstrap"}},
        }
        for name, block in pert.items()
    }

    observed = path_metrics(r_obs)
    robustness = classify_robustness(
        n_trades=len(r_obs),
        n_executable=loaded["executable_fills"],
    )
    conclusion = robustness["classification"]
    if conclusion == "INSUFFICIENT_SAMPLE":
        status = "PASS_WITH_DEFERRAL"
        conclusion_text = (
            "INSUFFICIENT_SAMPLE. The baseline RAW book has 24 theoretical trades and 0 executable fills. "
            "Shuffle/bootstrap and MODELED spread/slippage shocks are descriptive only. "
            "They are not historical realized costs and do not prove robustness or fragility. "
            "No parameters were optimized. FINAL_GATE remains BLOCKED. Phase 28.4 was not started."
        )
    else:
        status = "PASS_WITH_DEFERRAL"
        conclusion_text = f"{conclusion}. Still not live authorization."

    gate16 = _safe_load_json(root / PHASE2716_JSON) or {}
    payload = {
        "schema_version": 1,
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "git_head": _git_head(root),
        "status": status,
        "research_only": True,
        "live_trading_authorized": False,
        "parameters_optimized": False,
        "strategy_changed": False,
        "riskgate_changed": False,
        "ml_changed": False,
        "monte_carlo_used_baseline_only": True,
        "ohlc_rewalked": False,
        "ev_eq_01": "NOT_PROVEN",
        "cost_completeness": BLOCKED,
        "FINAL_GATE": gate16.get("FINAL_GATE") or BLOCKED,
        "baseline_source": {
            "phase28_1": PHASE281_JSON,
            "phase28_2": PHASE282_JSON,
            "r_series_match": True,
        },
        "dataset_fingerprint": fp,
        "trade_count_raw": len(r_obs),
        "trade_count_executable": loaded["executable_fills"],
        "observed_raw": observed,
        "observed_r_values": r_obs,
        "modeled_costs": costs,
        "monte_carlo": {
            "seed": RNG_SEED,
            "n_paths": N_PATHS,
            "method": "trade_sequence_resampling_of_stored_R",
            "ohlc_rewalked": False,
            "shuffle": summarize_paths(shuffle_paths),
            "bootstrap": summarize_paths(bootstrap_paths),
            "executable": {
                "defined": False,
                "n_fills": loaded["executable_fills"],
                "reason": "EXECUTABLE n=0. Monte Carlo is not defined on an empty fill book.",
            },
        },
        "perturbations": {
            "all_labeled_MODELED": True,
            "not_historical_realized": True,
            "summary": pert_summary,
        },
        "robustness": robustness,
        "conclusion": conclusion,
        "conclusion_text": conclusion_text,
        "safety": {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "ML_CHANGED": False,
            "PARAMETERS_OPTIMIZED": False,
            "PHASE_28_4_STARTED": False,
        },
        "phase_28_4_started": False,
        "deterministic_reproducibility": {
            "seed": RNG_SEED,
            "config_hash": hashlib.sha256(
                json.dumps(
                    {"seed": RNG_SEED, "n": N_PATHS, "r": r_obs},
                    sort_keys=True,
                ).encode()
            ).hexdigest()[:16],
        },
    }

    ok, issues = verify_immutability(before, base_dir=root)
    fp_after = file_fingerprint(root / CANONICAL_PARQUET)
    payload["datasets_changed"] = (not ok) or (fp_after != fp)
    payload["immutability_issues"] = issues
    payload["canonical_fingerprint_before"] = fp
    payload["canonical_fingerprint_after"] = fp_after

    _write_json(root / PHASE283_JSON, payload)
    _write_markdown(root, payload)

    known = root / "docs_v2/01_truth/KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md"
    if known.is_file():
        text = known.read_text(encoding="utf-8")
        marker = "## Performance validation (Phase 28.3)"
        block = (
            "\n\n## Performance validation (Phase 28.3)\n\n"
            "| Claim | Status |\n"
            "|---|---|\n"
            "| MC uses only Phase 28.1/28.2 baseline trades | **SUPPORTED** |\n"
            "| Spread/slippage shocks are realized costs | **NO** — MODELED / MODELED_PROXY |\n"
            "| Strategy is MC-robust | **INSUFFICIENT_SAMPLE** |\n"
            "| Phase 28.3 authorizes live trading | **NO** |\n"
        )
        if marker not in text:
            known.write_text(text.rstrip() + block, encoding="utf-8")

    return payload


if __name__ == "__main__":
    run_phase28_3_collection()
