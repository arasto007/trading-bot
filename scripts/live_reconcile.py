#!/usr/bin/env python3
"""Journal vs MT5 reconciliation for today."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.config.dotenv_loader import load_dotenv
from tradingbot.services.live_reporting import reconcile_journal_mt5

load_dotenv()


def main() -> int:
    cfg = load_legacy_config()
    result = reconcile_journal_mt5(cfg.get("BASE_DIR", str(ROOT)), cfg)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
