#!/usr/bin/env python3
"""گزارش صادقانه meta-labeler — فقط OOS و لاگ لایو."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INFO = ROOT / "models" / "meta_labeler_info.json"


def main() -> int:
    from tradingbot.services.meta_decision_log import recent_stats
    from tradingbot.services.meta_labeler import get_meta_labeler

    meta = get_meta_labeler()
    print("\n=== Meta-Labeler Status (OOS-based) ===\n")

    if INFO.is_file():
        info = json.loads(INFO.read_text(encoding="utf-8"))
        print(f"  last_trained_utc: {info.get('last_trained_utc', 'نامشخص')}")
        print(f"  last_mode: {info.get('last_mode', 'full')}")
        print()
        for tf, row in (info.get("per_tf") or {}).items():
            if row.get("skipped"):
                print(f"{tf}: SKIPPED — {row.get('reason')}")
                continue
            oos = row.get("oos") or {}
            active = meta.is_ready_for(tf)
            print(f"{tf}: {'ACTIVE' if active else 'OFF'}")
            print(f"  train samples: {row.get('train_samples')} | OOS: {oos.get('oos_samples')}")
            print(f"  OOS profit: {oos.get('oos_net_profit')} | PF: {oos.get('oos_pf')}")
            print(f"  OOS WR: {oos.get('oos_win_rate_pct')}% | threshold: {oos.get('best_threshold')}")
            print(f"  OOS trades taken: {oos.get('oos_trades_taken')} | gate: {oos.get('passed_gate')}")
            print()
    else:
        print("No meta_labeler_info.json — run train_meta_labeler.py first\n")

    live = recent_stats()
    print("=== Live Meta Log ===")
    print(f"  decisions: {live.get('decisions')} (accepted {live.get('accepted')}, rejected {live.get('rejected')})")
    print(f"  closed trades logged: {live.get('closed_trades')}")
    if live.get("live_win_rate_pct") is not None:
        print(f"  live WR: {live.get('live_win_rate_pct')}%")
    print(f"  log: {live.get('log_path', 'data/meta_decisions.jsonl')}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
