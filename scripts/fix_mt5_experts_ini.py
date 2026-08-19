#!/usr/bin/env python3
"""Ensure MT5 common.ini allows algorithmic + Python API trading."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def _read_ini(path: Path) -> tuple[str, str]:
    for enc in ("utf-16-le", "utf-8", "utf-16"):
        try:
            return path.read_text(encoding=enc), enc
        except Exception:
            continue
    raise RuntimeError(f"cannot read {path}")


def _write_ini(path: Path, text: str, enc: str) -> None:
    path.write_text(text, encoding=enc)


def _patch_experts(text: str) -> str:
    """Patch [Experts] using official MT5 keys + newer Python API keys."""
    lines = text.splitlines()
    out: list[str] = []
    in_experts = False
    keys_set: set[str] = set()

    # Official keys (MetaTrader 5 Help: Platform Start -> [Experts])
    required = {
        "AllowLiveTrading": "1",
        "AllowDllImport": "1",
        "Enabled": "1",
        "Account": "0",
        "Profile": "0",
        "Chart": "0",
        "Api": "1",
    }
    # Newer builds / Python API (set OFF = allow Python trading)
    zero_means_allow = {
        "DisableTradeAPI": "0",
        "DisableTradeApi": "0",
        "DisablePythonAPI": "0",
        "DisablePythonApi": "0",
        "DisableApiTrading": "0",
        "TradeApiDisabled": "0",
    }
    all_keys = {**required, **zero_means_allow}

    for raw in lines:
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            if in_experts:
                for k, v in all_keys.items():
                    if k.lower() not in keys_set:
                        out.append(f"{k}={v}")
            in_experts = line.lower() == "[experts]"
            keys_set = set()
            out.append(raw)
            continue
        if in_experts and "=" in line:
            key, _, _val = line.partition("=")
            kl = key.strip().lower()
            keys_set.add(kl)
            if kl in {k.lower() for k in required}:
                out.append(f"{key.strip()}=1")
                continue
            if kl in {k.lower() for k in zero_means_allow}:
                out.append(f"{key.strip()}=0")
                continue
        out.append(raw)

    if not any(l.strip().lower() == "[experts]" for l in out):
        out.append("")
        out.append("[Experts]")
        keys_set = set()

    section = ""
    keys_set = set()
    for ln in out:
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s.lower()
            continue
        if section == "[experts]" and "=" in s:
            keys_set.add(s.split("=", 1)[0].strip().lower())

    for k, v in all_keys.items():
        if k.lower() not in keys_set:
            out.append(f"{k}={v}")

    result = "\n".join(out)
    if not result.endswith("\n"):
        result += "\n"
    return result


def main() -> int:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.adapters.mt5_utils import _read_common_ini_fields, _terminal_data_dirs

    cfg = load_legacy_config()
    login = int(cfg.get("MT5_LOGIN") or 0)
    print(f"=== Fix MT5 Experts ini (login={login}) ===")
    for data_dir in _terminal_data_dirs():
        ini = data_dir / "config" / "common.ini"
        if not ini.is_file():
            continue
        hint = _read_common_ini_fields(ini)
        if hint.get("saved_login") != login:
            continue
        text, enc = _read_ini(ini)
        new_text = _patch_experts(text)
        if new_text != text:
            bak = ini.with_suffix(".ini.bak")
            if not bak.exists():
                bak.write_text(text, encoding=enc)
            _write_ini(ini, new_text, enc)
            print(f"UPDATED {ini}")
        else:
            print(f"OK {ini}")
        hint2 = _read_common_ini_fields(ini)
        print(
            f"  AllowLiveTrading via Enabled={hint2.get('experts_algo_enabled')} "
            f"Api={hint2.get('experts_api_enabled')}"
        )
        print("  Restart MT5 to apply (GO_LIVE_FULL does this)")
        return 0
    print("No matching common.ini found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
