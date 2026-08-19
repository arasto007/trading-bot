#!/usr/bin/env python3
"""Enable MT5 AutoTrading via Win32 WM_COMMAND and optional Options UI."""

from __future__ import annotations

import argparse
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

WM_COMMAND = 0x0111
MT5_WMCMD_EXPERTS = 32851
GA_ROOT = 2

user32 = ctypes.windll.user32


def _powershell(script: str) -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=False,
    )


def _find_mt5_root_hwnd(pid: int) -> int | None:
    matches: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        proc = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc))
        if int(proc.value) != pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title = buf.value or ""
        if title:
            matches.append((hwnd, title))
        return True

    user32.EnumWindows(_enum, 0)
    for hwnd, title in matches:
        low = title.lower()
        if "metatrader" in low or "litefinance" in low:
            root = user32.GetAncestor(hwnd, GA_ROOT)
            return int(root or hwnd)
    if matches:
        hwnd = matches[0][0]
        return int(user32.GetAncestor(hwnd, GA_ROOT) or hwnd)
    return None


def _activate_and_sendkeys(pid: int, keys: str) -> None:
    _powershell(
        f"$p=Get-Process -Id {pid} -ErrorAction SilentlyContinue; "
        f"if($p){{$w=New-Object -ComObject WScript.Shell; "
        f"for($i=0;$i -lt 8;$i++){{if($w.AppActivate($p.Id)){{break}}; Start-Sleep -m 300}}; "
        f"Start-Sleep -m 400; $w.SendKeys('{keys}')}}"
    )


def _send_wm_toggle(hwnd: int) -> None:
    user32.PostMessageW(hwnd, WM_COMMAND, MT5_WMCMD_EXPERTS, 0)


def _read_flags() -> tuple[bool | None, bool | None]:
    import MetaTrader5 as mt5

    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import safe_attach, safe_release_mt5

    cfg = load_legacy_config()
    if not safe_attach(cfg, allow_start=False):
        return None, None
    try:
        ti = mt5.terminal_info()
        if ti is None:
            return None, None
        return bool(getattr(ti, "trade_allowed", False)), bool(getattr(ti, "tradeapi_disabled", False))
    finally:
        safe_release_mt5()


def _open_expert_options_tab(pid: int) -> None:
    _activate_and_sendkeys(pid, "^o")
    time.sleep(1.2)
    for seq in ("{TAB}{TAB}{TAB}{TAB}", "%e"):
        _activate_and_sendkeys(pid, seq)
        time.sleep(0.35)


def _uncheck_python_api_block(pid: int) -> None:
    _open_expert_options_tab(pid)
    _activate_and_sendkeys(pid, " ")
    time.sleep(0.2)
    for _ in range(4):
        _activate_and_sendkeys(pid, "{TAB}")
        time.sleep(0.12)
    _activate_and_sendkeys(pid, " ")
    time.sleep(0.2)
    _activate_and_sendkeys(pid, "{ENTER}")


def _terminal_pid() -> int:
    if sys.platform != "win32":
        return 0
    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process terminal64 -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Id)",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return int(out) if out.isdigit() else 0
    except Exception:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--max-tries", type=int, default=4)
    args = parser.parse_args()

    pid = args.pid or _terminal_pid()
    if pid <= 0:
        print("FAIL: terminal64.exe not running")
        return 1

    print(f"=== Enable MT5 AutoTrading (PID={pid}) ===")
    hwnd = _find_mt5_root_hwnd(pid)
    if not hwnd:
        print("FAIL: MT5 main window not found")
        return 1

    for attempt in range(1, args.max_tries + 1):
        trade_allowed, tradeapi_disabled = _read_flags()
        print(f"try {attempt}: trade_allowed={trade_allowed} tradeapi_disabled={tradeapi_disabled}")
        if trade_allowed and tradeapi_disabled is False:
            print("OK: AutoTrading + Python API enabled")
            return 0

        if not trade_allowed:
            print("  -> WM_COMMAND toggle Algo Trading toolbar")
            _activate_and_sendkeys(pid, "^e")
            _send_wm_toggle(hwnd)
            time.sleep(1.5)

        trade_allowed, tradeapi_disabled = _read_flags()
        if tradeapi_disabled:
            print("  -> Options / Expert Advisors (Python API block)")
            _uncheck_python_api_block(pid)
            time.sleep(1.5)

    trade_allowed, tradeapi_disabled = _read_flags()
    print(f"FINAL: trade_allowed={trade_allowed} tradeapi_disabled={tradeapi_disabled}")
    if trade_allowed and tradeapi_disabled is False:
        return 0

    print("\nMANUAL FIX in MT5:")
    print("  Tools -> Options -> Expert Advisors")
    print("  [x] Allow algorithmic trading")
    print("  [ ] Disable automatic trading through the external Python API  (must be OFF)")
    print("  Toolbar Algo Trading GREEN (Ctrl+E)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
