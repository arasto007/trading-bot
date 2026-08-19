"""Phase 19A — symbol / temporal analysis."""

from __future__ import annotations

from typing import Any

from tradingbot.ml.phase19a.metrics import compute_performance, pf_from_r


def _session(hour: int) -> str:
    if 0 <= hour < 8:
        return "ASIA"
    if 8 <= hour < 13:
        return "LONDON"
    if 13 <= hour < 21:
        return "NY"
    return "LATE"


def analyze_symbol(trades: list[dict[str, Any]], *, symbol: str = "XAUUSD") -> dict[str, Any]:
    accepted = [t for t in trades if t.get("allowed")]

    def _group(key_fn) -> dict[str, Any]:
        groups: dict[str, list] = {}
        for t in accepted:
            k = str(key_fn(t))
            groups.setdefault(k, []).append(t)
        return {k: compute_performance(v) for k, v in sorted(groups.items())}

    by_year = _group(lambda t: t["year"])
    by_month = _group(lambda t: f"{t['year']}-{t['month']:02d}")
    by_weekday = _group(lambda t: t["weekday"])
    by_hour = _group(lambda t: t["hour"])
    by_session = _group(lambda t: _session(int(t["hour"])))

    return {
        "phase": "19A",
        "symbol": symbol,
        "total_trades": len(accepted),
        "by_year": by_year,
        "by_month": by_month,
        "by_weekday": by_weekday,
        "by_hour": by_hour,
        "by_session": by_session,
    }


def monthly_statistics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [t for t in trades if t.get("allowed")]
    months: dict[str, list[float]] = {}
    for t in accepted:
        key = f"{t['year']}-{t['month']:02d}"
        months.setdefault(key, []).append(float(t["r_multiple"]))
    stats = {}
    for k, r_vals in sorted(months.items()):
        stats[k] = {
            "trades": len(r_vals),
            "net_r": round(sum(r_vals), 4),
            "pf": pf_from_r(r_vals),
            "win_rate": round(sum(1 for r in r_vals if r > 0) / len(r_vals), 4),
        }
    return {"phase": "19A", "months": stats}


def yearly_statistics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [t for t in trades if t.get("allowed")]
    years: dict[str, list[float]] = {}
    for t in accepted:
        key = str(t["year"])
        years.setdefault(key, []).append(float(t["r_multiple"]))
    stats = {}
    for k, r_vals in sorted(years.items()):
        stats[k] = {
            "trades": len(r_vals),
            "net_r": round(sum(r_vals), 4),
            "pf": pf_from_r(r_vals),
            "win_rate": round(sum(1 for r in r_vals if r > 0) / len(r_vals), 4),
        }
    return {"phase": "19A", "years": stats}
