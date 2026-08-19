#!/usr/bin/env python3
"""Release MT5 IPC lock and optional refresh marker (safe after bot stop)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def main() -> int:
    from tradingbot.adapters.mt5_utils import (
        mt5_ipc_lock_path,
        mt5_refresh_marker_path,
        release_mt5_lock,
    )

    release_mt5_lock()
    lock = mt5_ipc_lock_path()
    marker = mt5_refresh_marker_path()
    print(f"IPC lock released ({lock.name})")
    if marker.is_file():
        marker.unlink(missing_ok=True)
        print(f"Refresh marker cleared ({marker.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
