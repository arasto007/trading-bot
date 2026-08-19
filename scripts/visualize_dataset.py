#!/usr/bin/env python3
"""Offline dataset visualization — Phase 3.1 (no live trading impact)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.dataset.store import DatasetStore


def _save_bar_chart(labels: list[str], values: list[int], title: str, path: Path) -> bool:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(labels, values, color="#4C72B0")
    ax.set_title(title)
    ax.set_ylabel("count")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize ML dataset distributions (offline)")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframe", default="M5")
    args = parser.parse_args()

    store = DatasetStore()
    df = store.load(args.symbol, args.timeframe)
    if df is None or df.empty:
        print(f"No dataset for {args.symbol} {args.timeframe}")
        return 1

    out_dir = reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"{args.symbol.upper()}_{args.timeframe.upper()}"

    saved = 0
    if "label" in df.columns:
        vc = df["label"].value_counts().sort_index()
        labels = [str(int(k)) for k in vc.index]
        if _save_bar_chart(labels, vc.tolist(), "Label Distribution", out_dir / f"{prefix}_label_distribution.png"):
            saved += 1

    if "event_type" in df.columns:
        vc = df["event_type"].value_counts()
        if _save_bar_chart(vc.index.tolist(), vc.tolist(), "Event Distribution", out_dir / f"{prefix}_event_distribution.png"):
            saved += 1

    session_cols = {
        "asia": "session_asia",
        "london": "session_london",
        "new_york": "session_ny",
        "off_hours": "session_off",
    }
    if any(c in df.columns for c in session_cols.values()):
        counts = []
        names = []
        for name, col in session_cols.items():
            if col in df.columns:
                names.append(name)
                counts.append(int((df[col] == 1).sum()))
        if names and _save_bar_chart(names, counts, "Session Distribution", out_dir / f"{prefix}_session_distribution.png"):
            saved += 1

    if saved == 0:
        print("matplotlib not available — install matplotlib to generate PNG reports")
        return 1

    print(f"Saved {saved} chart(s) to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
