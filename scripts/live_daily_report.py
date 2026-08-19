#!/usr/bin/env python3
"""Print/send daily live report (Phase 2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.config.dotenv_loader import load_dotenv
from tradingbot.services.live_reporting import build_daily_report, format_daily_report_telegram
from tradingbot.services.notifier import Notifier

load_dotenv()


def main() -> int:
    cfg = load_legacy_config()
    report = build_daily_report(cfg.get("BASE_DIR", str(ROOT)), cfg)
    text = format_daily_report_telegram(report)
    print(text)
    print()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if "--telegram" in sys.argv:
        Notifier(cfg.get("BASE_DIR", str(ROOT))).alert("info", text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
