#!/usr/bin/env python3
"""Print MT5 common.ini Experts section + terminal_info flags."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tradingbot.config.dotenv_loader import load_dotenv
load_dotenv()

def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import discover_terminal_path, list_terminal_installations

    cfg = load_legacy_config()
    login = cfg.get("MT5_LOGIN")
    print(f"=== MT5 INI + terminal_info (login={login}) ===\n")

    for row in list_terminal_installations(cfg):
        print(row)

    import os
    appdata = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    target_ini = None
    for d in appdata.iterdir() if appdata.is_dir() else []:
        ini = d / "config" / "common.ini"
        if not ini.is_file():
            continue
        text = ini.read_text(encoding="utf-16-le", errors="ignore")
        if f"Login={login}" in text.replace(" ", ""):
            target_ini = ini
            print(f"\n--- common.ini: {ini} ---")
            section = None
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("[") and s.endswith("]"):
                    section = s.lower()
                if section in ("[experts]", "[common]") or (section == "[common]" and any(k in s for k in ("Login=", "Server=", "Allow"))):
                    print(line.rstrip())
                elif section == "[experts]":
                    print(line.rstrip())
            break

    import MetaTrader5 as mt5
    path = discover_terminal_path(cfg)
    print(f"\ninitialize path={path}")
    mt5.initialize(path=path, timeout=60000) if path else mt5.initialize(timeout=60000)
    ti = mt5.terminal_info()
    if ti:
        print(f"trade_allowed={ti.trade_allowed}")
        print(f"tradeapi_disabled={getattr(ti, 'tradeapi_disabled', '?')}")
        print(f"dlls_allowed={getattr(ti, 'dlls_allowed', '?')}")
        print(f"path={getattr(ti, 'path', '?')}")
    mt5.shutdown()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
