#!/usr/bin/env python3
"""Clear emergency stop flag so the bot can start again after kill switch."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def main() -> int:
    from tradingbot.services.emergency_stop_state import clear_emergency_stop

    clear_emergency_stop()
    print("Emergency stop cleared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
