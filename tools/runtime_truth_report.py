#!/usr/bin/env python3
"""Print and persist runtime truth snapshot for the live trading path."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.services.runtime_truth import write_runtime_truth


def main() -> int:
    cfg = load_legacy_config()
    write_runtime_truth(legacy_config=cfg, print_console=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
