#!/usr/bin/env python3
"""Poll until MT5 is running and attached account matches config."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import safe_attach, safe_release_mt5, verify_attached_account

    cfg = load_legacy_config()
    deadline = time.time() + max(5, args.timeout)
    while time.time() < deadline:
        if safe_attach(cfg, allow_start=False):
            ok, _msg = verify_attached_account(cfg, strict=True)
            safe_release_mt5()
            if ok:
                print("OK")
                return 0
        time.sleep(3)
    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
