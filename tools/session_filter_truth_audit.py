#!/usr/bin/env python3
"""
Phase 34B — SESSION filter truth audit (research only).

Compares session filter scenarios on the same M5 data as adaptive_regime_live_truth_7d.
Does NOT modify production code or strategy parameters.
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

os.environ.setdefault("USE_ML_KERNEL", "false")
os.environ.setdefault("ADAPTIVE_REGIME_ENABLED", "true")
os.environ.setdefault("ADAPTIVE_CONFLUENCE_ONLY", "true")

import pandas as pd

import tradingbot.strategies.adaptive_regime as adaptive_regime
from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.backtest.config import BacktestConfig
from tradingbot.backtest.engine import BacktestEngine
from tradingbot.domain.signal_helpers import compute_sl_tp
from tradingbot.ml.decision_engine.decision_policy import VOL_REGIME_RULE_CONFIDENCE
from tradingbot.strategies.adaptive_regime import (
    AdaptiveSignal,
    evaluate_adaptive_at_index,
    prepare_adaptive_frame,
)

# Reuse data loader from Phase 34A (same directory)
sys.path.insert(0, str(ROOT / "tools"))
from adaptive_regime_live_truth_7d import _load_with_fallback  # noqa: E402

SESSION_CURRENT: tuple[tuple[int, int], ...] = ((12, 17),)
SESSION_NONE: tuple[tuple[int, int], ...] = ((0, 24),)
SESSION_LONDON_NY: tuple[tuple[int, int], ...] = ((7, 16),)

MAX_HOLD_BARS = 288  # 24h on M5 — timeout for hypothetical replay
WARMUP = 80
DAYS = 7
SYMBOL = "XAUUSD"


@dataclass
class HypotheticalTrade:
    timestamp: str
    direction: str
    entry_price: float
    sl: float
    tp: float
    blocked_reason: str
    session_name: str
    scenario: str
    strategy_id: str
    hour_utc: int
    outcome: str  # TP | SL | timeout
    r_multiple: float
    mfe_r: float
    mae_r: float
    hold_bars: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioResult:
    name: str
    session_label: str
    session_hours: tuple[tuple[int, int], ...]
    signal_count: int = 0
    executed_count: int = 0
    blocked_count: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy_r: float = 0.0
    net_r: float = 0.0
    avg_hold_hours: float = 0.0
    max_drawdown_r: float = 0.0
    recovery_factor: float = 0.0
    trades: list[HypotheticalTrade] = field(default_factory=list)


def _session_name(hours: tuple[tuple[int, int], ...]) -> str:
    if hours == SESSION_CURRENT:
        return "OVERLAP_12_17"
    if hours == SESSION_NONE:
        return "NO_SESSION_FILTER"
    if hours == SESSION_LONDON_NY:
        return "LONDON_NY_07_16"
    return str(hours)


def _hour_in_session(hour: int, sessions: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= hour < end for start, end in sessions)


@contextmanager
def _session_patch(hours: tuple[tuple[int, int], ...]) -> Iterator[None]:
    original = adaptive_regime.SESSION_HOURS
    adaptive_regime.SESSION_HOURS = hours
    try:
        yield
    finally:
        adaptive_regime.SESSION_HOURS = original


def _load_data() -> tuple[pd.DataFrame, pd.DataFrame, str, int]:
    legacy = load_legacy_config()
    cfg = BacktestConfig(
        symbols=[SYMBOL],
        timeframe="M5",
        days=DAYS,
        warmup=WARMUP,
        use_cache=True,
    )
    engine = BacktestEngine(cfg, legacy, quiet=True)
    length = _load_with_fallback(engine, cfg, DAYS)
    raw = engine.data_source.frame(SYMBOL)
    if raw is None or raw.empty:
        raise RuntimeError("No data loaded")
    frame = prepare_adaptive_frame(raw.copy())
    note = getattr(engine.data_source, "_load_note", "unknown")
    return raw, frame, note, length


def _compute_sl_tp(raw: pd.DataFrame, idx: int, sig: AdaptiveSignal) -> tuple[float, float]:
    window = raw.iloc[: idx + 1]
    sl, tp, _ = compute_sl_tp(
        window,
        int(sig.direction),
        VOL_REGIME_RULE_CONFIDENCE,
        symbol=SYMBOL,
        strategy_name=sig.strategy_id.lower(),
        timeframe="5m",
        config=load_legacy_config(),
    )
    return float(sl), float(tp)


def _replay(
    raw: pd.DataFrame,
    idx: int,
    sig: AdaptiveSignal,
    *,
    scenario: str,
    session_name: str,
    blocked_reason: str = "",
) -> HypotheticalTrade | None:
    entry = float(raw["close"].iloc[idx])
    sl, tp = _compute_sl_tp(raw, idx, sig)
    risk = abs(entry - sl)
    if risk <= 0:
        return None

    is_buy = int(sig.direction) > 0
    direction = "BUY" if is_buy else "SELL"
    hour = int(raw.iloc[idx].get("hour_utc", pd.Timestamp(raw.index[idx]).hour))

    mfe_r = 0.0
    mae_r = 0.0
    outcome = "timeout"
    r_mult = 0.0
    hold_bars = 0
    end = min(len(raw), idx + 1 + MAX_HOLD_BARS)

    for j in range(idx + 1, end):
        hold_bars += 1
        bar = raw.iloc[j]
        hi, lo = float(bar["high"]), float(bar["low"])
        if is_buy:
            mfe_r = max(mfe_r, (hi - entry) / risk)
            mae_r = max(mae_r, (entry - lo) / risk)
            if lo <= sl:
                outcome = "SL"
                r_mult = -1.0
                break
            if hi >= tp:
                outcome = "TP"
                r_mult = (tp - entry) / risk
                break
        else:
            mfe_r = max(mfe_r, (entry - lo) / risk)
            mae_r = max(mae_r, (hi - entry) / risk)
            if hi >= sl:
                outcome = "SL"
                r_mult = -1.0
                break
            if lo <= tp:
                outcome = "TP"
                r_mult = (entry - tp) / risk
                break
    else:
        if hold_bars > 0:
            exit_px = float(raw["close"].iloc[end - 1])
            r_mult = ((exit_px - entry) / risk) if is_buy else ((entry - exit_px) / risk)
        outcome = "timeout"

    ts = pd.Timestamp(raw.index[idx])
    return HypotheticalTrade(
        timestamp=str(ts),
        direction=direction,
        entry_price=round(entry, 2),
        sl=round(sl, 2),
        tp=round(tp, 2),
        blocked_reason=blocked_reason,
        session_name=session_name,
        scenario=scenario,
        strategy_id=sig.strategy_id,
        hour_utc=hour,
        outcome=outcome,
        r_multiple=round(r_mult, 4),
        mfe_r=round(mfe_r, 4),
        mae_r=round(mae_r, 4),
        hold_bars=hold_bars,
    )


def _metrics_from_trades(trades: list[HypotheticalTrade], bars_scanned: int) -> dict[str, float]:
    if not trades:
        return {
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "net_r": 0.0,
            "avg_hold_hours": 0.0,
            "max_drawdown_r": 0.0,
            "recovery_factor": 0.0,
        }
    rs = [t.r_multiple for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    net_r = sum(rs)
    expectancy = net_r / len(rs)

    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    recovery = (net_r / max_dd) if max_dd > 0 and net_r > 0 else 0.0
    avg_hold = sum(t.hold_bars for t in trades) / len(trades) * 5 / 60

    return {
        "win_rate": round(len(wins) / len(rs) * 100, 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else float("inf"),
        "expectancy_r": round(expectancy, 4),
        "net_r": round(net_r, 4),
        "avg_hold_hours": round(avg_hold, 2),
        "max_drawdown_r": round(max_dd, 4),
        "recovery_factor": round(recovery, 4),
    }


def run_scenario(
    raw: pd.DataFrame,
    frame: pd.DataFrame,
    *,
    name: str,
    session_hours: tuple[tuple[int, int], ...],
    bars_scanned: int,
) -> ScenarioResult:
    trades: list[HypotheticalTrade] = []
    signal_count = 0

    with _session_patch(session_hours):
        for idx in range(WARMUP, len(frame)):
            sig = evaluate_adaptive_at_index(frame, idx, log_rejections=False)
            if sig is None:
                continue
            signal_count += 1
            trade = _replay(
                raw,
                idx,
                sig,
                scenario=name,
                session_name=_session_name(session_hours),
            )
            if trade:
                trades.append(trade)

    m = _metrics_from_trades(trades, bars_scanned)
    return ScenarioResult(
        name=name,
        session_label=_session_name(session_hours),
        session_hours=session_hours,
        signal_count=signal_count,
        executed_count=len(trades),
        blocked_count=bars_scanned - signal_count,
        win_rate=m["win_rate"],
        profit_factor=m["profit_factor"],
        expectancy_r=m["expectancy_r"],
        net_r=m["net_r"],
        avg_hold_hours=m["avg_hold_hours"],
        max_drawdown_r=m["max_drawdown_r"],
        recovery_factor=m["recovery_factor"],
        trades=trades,
    )


def extract_session_blocked_replays(
    raw: pd.DataFrame,
    frame: pd.DataFrame,
) -> list[HypotheticalTrade]:
    """Signals that exist without session filter but blocked by current 12-17 window."""
    blocked: list[HypotheticalTrade] = []

    for idx in range(WARMUP, len(frame)):
        row = frame.iloc[idx]
        hour = int(row.get("hour_utc", 12))
        if _hour_in_session(hour, SESSION_CURRENT):
            continue

        with _session_patch(SESSION_NONE):
            sig_open = evaluate_adaptive_at_index(frame, idx, log_rejections=False)
        if sig_open is None:
            continue

        with _session_patch(SESSION_CURRENT):
            sig_closed = evaluate_adaptive_at_index(frame, idx, log_rejections=False)
        if sig_closed is not None:
            continue

        trade = _replay(
            raw,
            idx,
            sig_open,
            scenario="A_session_blocked",
            session_name="OVERLAP_12_17",
            blocked_reason=f"hour_utc={hour} outside 12-17 UTC",
        )
        if trade:
            blocked.append(trade)

    return blocked


def hourly_stats(all_trades_no_session: list[HypotheticalTrade]) -> list[dict[str, Any]]:
    rows = []
    for h in range(24):
        subset = [t for t in all_trades_no_session if t.hour_utc == h]
        if not subset:
            rows.append(
                {
                    "hour": h,
                    "signals": 0,
                    "wins": 0,
                    "losses": 0,
                    "PF": 0.0,
                    "expectancy_R": 0.0,
                }
            )
            continue
        wins = [t for t in subset if t.r_multiple > 0]
        losses = [t for t in subset if t.r_multiple < 0]
        gw = sum(t.r_multiple for t in wins)
        gl = abs(sum(t.r_multiple for t in losses))
        pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else 0.0)
        exp = sum(t.r_multiple for t in subset) / len(subset)
        rows.append(
            {
                "hour": h,
                "signals": len(subset),
                "wins": len(wins),
                "losses": len(losses),
                "PF": round(pf, 3) if pf != float("inf") else "inf",
                "expectancy_R": round(exp, 4),
            }
        )
    return rows


def choose_verdict(a: ScenarioResult, b: ScenarioResult) -> str:
    if b.profit_factor > a.profit_factor and b.expectancy_r > a.expectancy_r:
        return "SESSION_FILTER_HARMFUL"
    if b.profit_factor < a.profit_factor and b.max_drawdown_r > a.max_drawdown_r:
        return "SESSION_FILTER_PROFITABLE"
    return "SESSION_FILTER_NEUTRAL"


def write_false_negative_md(
    path: Path,
    blocked: list[HypotheticalTrade],
    scenario_a: ScenarioResult,
    scenario_b: ScenarioResult,
) -> None:
    total = len(blocked)
    winners = [t for t in blocked if t.r_multiple > 0]
    losers = [t for t in blocked if t.r_multiple < 0]
    fn_rate = (len(winners) / total * 100) if total else 0.0

    lines = [
        "# Session Filter — False Negative Analysis",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Data window:** {DAYS} days M5 XAUUSD",
        "",
        "## Question: Does SESSION remove winning trades?",
        "",
        f"**Answer:** {'Yes — materially' if fn_rate >= 40 else 'Mixed' if fn_rate >= 20 else 'Mostly no — blocked signals are mostly losers'}",
        "",
        "## Method",
        "",
        "For each bar **outside 12–17 UTC**, evaluate signal with:",
        "1. No session filter (would trade)",
        "2. Current session filter (blocked)",
        "",
        "If (1) produces signal and (2) does not → **SESSION-blocked candidate**. Replay hypothetically on historical bars (SL/TP/timeout, no live execution).",
        "",
        "## Results",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| Total SESSION-blocked signals replayed | {total} |",
        f"| Would-be winners (R > 0) | {len(winners)} |",
        f"| Would-be losers (R < 0) | {len(losers)} |",
        f"| Flat / timeout | {total - len(winners) - len(losers)} |",
        f"| **false_negative_rate** | **{fn_rate:.2f}%** |",
        "",
        "### Formula",
        "",
        "```",
        "false_negative_rate = winning_blocked / total_session_blocked",
        f"                      = {len(winners)} / {total} = {fn_rate:.2f}%",
        "```",
        "",
        "## Scenario comparison (hypothetical replay)",
        "",
        "| Scenario | Signals | Win% | PF | Expectancy R | Net R | Max DD R |",
        "|----------|--------:|-----:|---:|-------------:|------:|---------:|",
        f"| A — Current SESSION 12–17 | {scenario_a.signal_count} | {scenario_a.win_rate}% | {scenario_a.profit_factor} | {scenario_a.expectancy_r} | {scenario_a.net_r} | {scenario_a.max_drawdown_r} |",
        f"| B — No SESSION | {scenario_b.signal_count} | {scenario_b.win_rate}% | {scenario_b.profit_factor} | {scenario_b.expectancy_r} | {scenario_b.net_r} | {scenario_b.max_drawdown_r} |",
        "",
        "## Sample SESSION-blocked trades (first 15)",
        "",
        "| timestamp | hour | dir | outcome | R | MFE R | MAE R |",
        "|-----------|-----:|-----|---------|---:|------:|------:|",
    ]
    for t in blocked[:15]:
        lines.append(
            f"| {t.timestamp} | {t.hour_utc} | {t.direction} | {t.outcome} | {t.r_multiple} | {t.mfe_r} | {t.mae_r} |"
        )
    if not blocked:
        lines.append("| — | — | — | No SESSION-blocked signals in window | — | — | — |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_hourly_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Hourly Edge Heatmap (UTC)",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "**Source:** Scenario B (no session filter) — signals grouped by bar hour UTC",
        "",
        "| hour | signals | wins | losses | PF | expectancy_R |",
        "|-----:|--------:|-----:|-------:|---:|-------------:|",
    ]
    for r in rows:
        pf = r["PF"]
        lines.append(
            f"| {r['hour']:02d} | {r['signals']} | {r['wins']} | {r['losses']} | {pf} | {r['expectancy_R']} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_session_mermaid(path: Path, bars_scanned: int, funnel: dict[str, int]) -> None:
    session_pct = round(funnel.get("session_pct", 78.3), 1)
    conf_pct = round(funnel.get("confluence_pct", 21.3), 1)
    signal_pct = round(funnel.get("signal_pct", 0.4), 1)
    risk_pct = round(funnel.get("risk_pct", 37.5), 1)
    exec_pct = round(funnel.get("exec_pct", 62.5), 1)

    content = f"""%% Phase 34B — Session decision flow (Phase 34A percentages on 7d M5 data)
flowchart TD
    BARS["1936 M5 bars scanned"] --> EVAL{{Signal evaluation}}
    EVAL -->|"{session_pct}% SESSION block"| BLOCKED["Blocked outside 12-17 UTC"]
    EVAL -->|"{100 - session_pct:.1f}% in-session"| CONF{{Confluence check}}
    CONF -->|"{conf_pct}% no confluence"| CBLOCK["Blocked: MTF/VOL disagree"]
    CONF -->|"{signal_pct}% signal"| SIG["Signal produced"]
    SIG -->|"{risk_pct}% risk/cooldown est."| RBLOCK["RiskGate block"]
    SIG -->|"{exec_pct}% executed"| EXEC["MT5 Execute"]
    EXEC --> PM["PositionManager"]

    style BLOCKED fill:#faa,stroke:#800
    style CBLOCK fill:#fcc,stroke:#a00
    style SIG fill:#afa,stroke:#080
    style EXEC fill:#9cf,stroke:#006
"""
    path.write_text(content, encoding="utf-8")


def write_final_report(
    path: Path,
    *,
    data_note: str,
    scenarios: dict[str, ScenarioResult],
    verdict: str,
    blocked: list[HypotheticalTrade],
    fn_rate: float,
) -> None:
    a, b, c = scenarios["A"], scenarios["B"], scenarios["C"]
    lines = [
        "# Phase 34B — Session Filter Truth Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Data:** {DAYS}-day M5 XAUUSD ({data_note})",
        f"**Verdict:** **{verdict}**",
        "",
        "## Executive summary",
        "",
        f"- Current session window **12–17 UTC** produced **{a.signal_count}** signals vs **{b.signal_count}** without session filter.",
        f"- Hypothetical PF: A={a.profit_factor}, B={b.profit_factor}, C={c.profit_factor}",
        f"- SESSION-blocked false negative rate: **{fn_rate:.1f}%** ({len([t for t in blocked if t.r_multiple > 0])}/{len(blocked)} would-be winners)",
        "",
        "## Scenario comparison",
        "",
        "| Metric | A: Current 12–17 | B: No SESSION | C: London+NY 07–16 |",
        "|--------|----------------:|--------------:|-------------------:|",
        f"| signal_count | {a.signal_count} | {b.signal_count} | {c.signal_count} |",
        f"| executed_count | {a.executed_count} | {b.executed_count} | {c.executed_count} |",
        f"| blocked_count | {a.blocked_count} | {b.blocked_count} | {c.blocked_count} |",
        f"| win_rate | {a.win_rate}% | {b.win_rate}% | {c.win_rate}% |",
        f"| profit_factor | {a.profit_factor} | {b.profit_factor} | {c.profit_factor} |",
        f"| expectancy_r | {a.expectancy_r} | {b.expectancy_r} | {c.expectancy_r} |",
        f"| net_r | {a.net_r} | {b.net_r} | {c.net_r} |",
        f"| avg_hold_hours | {a.avg_hold_hours} | {b.avg_hold_hours} | {c.avg_hold_hours} |",
        f"| max_drawdown_r | {a.max_drawdown_r} | {b.max_drawdown_r} | {c.max_drawdown_r} |",
        f"| recovery_factor | {a.recovery_factor} | {b.recovery_factor} | {c.recovery_factor} |",
        "",
        "## Verdict rule applied",
        "",
        "| Condition | Result |",
        "|-----------|--------|",
        f"| Removing SESSION increases PF and expectancy? | {b.profit_factor > a.profit_factor and b.expectancy_r > a.expectancy_r} |",
        f"| Removing SESSION increases drawdown? | {b.max_drawdown_r > a.max_drawdown_r} |",
        "",
        "## Files produced",
        "",
        "- `docs/session_filter_false_negative_analysis.md`",
        "- `docs/hourly_edge_heatmap.md`",
        "- `docs/session_decision_flow.mmd`",
        "- `logs/session_filter_blocked_replay.jsonl`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    raw, frame, data_note, length = _load_data()
    bars_scanned = length - WARMUP

    scenario_a = run_scenario(
        raw, frame, name="A_current", session_hours=SESSION_CURRENT, bars_scanned=bars_scanned
    )
    scenario_b = run_scenario(
        raw, frame, name="B_no_session", session_hours=SESSION_NONE, bars_scanned=bars_scanned
    )
    scenario_c = run_scenario(
        raw, frame, name="C_london_ny", session_hours=SESSION_LONDON_NY, bars_scanned=bars_scanned
    )

    session_blocked = extract_session_blocked_replays(raw, frame)
    winners_blocked = [t for t in session_blocked if t.r_multiple > 0]
    fn_rate = (len(winners_blocked) / len(session_blocked) * 100) if session_blocked else 0.0

    hourly = hourly_stats(scenario_b.trades)
    verdict = choose_verdict(scenario_a, scenario_b)

    # Phase 34A funnel percentages
    in_session = bars_scanned - round(bars_scanned * 0.783)
    funnel = {
        "session_pct": 1516 / 1936 * 100 if bars_scanned else 78.3,
        "confluence_pct": 412 / 1936 * 100,
        "signal_pct": scenario_a.signal_count / bars_scanned * 100,
        "risk_pct": 3 / max(scenario_a.signal_count, 1) * 100,
        "exec_pct": 5 / max(scenario_a.signal_count, 1) * 100,
    }

    docs = ROOT / "docs"
    logs = ROOT / "logs"
    docs.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    write_false_negative_md(
        docs / "session_filter_false_negative_analysis.md",
        session_blocked,
        scenario_a,
        scenario_b,
    )
    write_hourly_md(docs / "hourly_edge_heatmap.md", hourly)
    write_session_mermaid(docs / "session_decision_flow.mmd", bars_scanned, funnel)
    write_final_report(
        docs / "phase34b_session_truth_report.md",
        data_note=data_note,
        scenarios={"A": scenario_a, "B": scenario_b, "C": scenario_c},
        verdict=verdict,
        blocked=session_blocked,
        fn_rate=fn_rate,
    )

    out_jsonl = logs / "session_filter_blocked_replay.jsonl"
    with out_jsonl.open("w", encoding="utf-8") as fh:
        for t in session_blocked:
            fh.write(json.dumps(t.to_dict(), ensure_ascii=False) + "\n")

    print(f"Verdict: {verdict}")
    print(f"A signals={scenario_a.signal_count} PF={scenario_a.profit_factor} | B signals={scenario_b.signal_count} PF={scenario_b.profit_factor}")
    print(f"SESSION-blocked replayed: {len(session_blocked)} | false_negative_rate={fn_rate:.1f}%")
    print(f"Reports written under docs/ and {out_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
