#!/usr/bin/env python3
"""Phase 4 readiness — prop preset, drift monitor, slippage/spread reporting."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.adapters.legacy_loader import load_legacy_config
from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()


def main() -> int:
    issues: list[str] = []

    print("=== Phase 4 Live Proof Readiness ===")

    from tradingbot.config.prop_presets import PRESETS, active_preset_name

    print(f"  prop_presets: OK ({len(PRESETS)} presets: {', '.join(sorted(PRESETS))})")

    preset = active_preset_name()
    cfg = load_legacy_config()
    applied = str(cfg.get("PROP_FIRM_PRESET") or "none")
    print(f"  active_preset env: {preset or 'none'}")
    print(f"  config PROP_FIRM_PRESET: {applied}")
    if preset not in ("none", "") and preset not in PRESETS:
        print(f"  preset_apply: FAIL — unknown preset {preset!r}")
        issues.append(f"unknown_preset:{preset}")
    elif preset not in ("none", "") and applied != preset:
        print("  preset_apply: FAIL — preset not merged into config")
        issues.append("preset_not_applied")
    else:
        label = cfg.get("PROP_FIRM_NAME") if preset not in ("none", "") else "-"
        print(f"  preset_apply: OK ({label})")

    drift_path = ROOT / "tradingbot" / "services" / "drift_monitor.py"
    if not drift_path.is_file():
        print("  drift_monitor: MISSING")
        issues.append("drift_monitor")
    else:
        from tradingbot.services.drift_monitor import (
            BASELINE_PF,
            compute_drift_report,
            format_drift_telegram,
        )

        print(f"  drift_monitor: OK (baseline PF={BASELINE_PF})")
        report = compute_drift_report(cfg.get("BASE_DIR", str(ROOT)), cfg)
        out = Path(cfg.get("BASE_DIR", str(ROOT))) / "logs" / "drift_report.json"
        if not out.is_file():
            print("  drift_report.json: FAIL — not written")
            issues.append("drift_report_write")
        else:
            print(f"  drift_report.json: OK status={report.get('status')}")
        _ = format_drift_telegram(report)

    ops_path = ROOT / "tradingbot" / "services" / "live_ops_service.py"
    ops_src = ops_path.read_text(encoding="utf-8") if ops_path.is_file() else ""
    if "compute_drift_report" not in ops_src:
        print("  live_ops drift wiring: MISSING")
        issues.append("live_ops_drift")
    else:
        print("  live_ops drift wiring: OK")

    from tradingbot.services.live_reporting import current_spread_pips, journal_summary

    summary = journal_summary(cfg.get("BASE_DIR", str(ROOT)))
    for key in ("slippage_avg_pips", "slippage_max_pips", "executions_total"):
        if key not in summary:
            print(f"  journal slippage fields: FAIL — missing {key}")
            issues.append(f"journal:{key}")
            break
    else:
        print("  journal slippage fields: OK")

    spread = current_spread_pips(cfg)
    print(f"  spread probe: {'OK' if spread is not None else 'optional (MT5 offline)'}")

    snap_path = ROOT / "scripts" / "status_snapshot.py"
    snap_src = snap_path.read_text(encoding="utf-8") if snap_path.is_file() else ""
    for token in ("PROP|", "DRIFT|", "SLIP|", "SPREAD|"):
        if token not in snap_src:
            print(f"  status_snapshot {token.strip('|')}: MISSING")
            issues.append(f"status_snapshot:{token}")
        else:
            print(f"  status_snapshot {token.strip('|')}: OK")

    env_example = ROOT / ".env.example"
    if env_example.is_file() and "TRADINGBOT_PROP_PRESET" in env_example.read_text(encoding="utf-8"):
        print("  .env.example TRADINGBOT_PROP_PRESET: OK")
    else:
        print("  .env.example TRADINGBOT_PROP_PRESET: MISSING")
        issues.append("env_example")

    bat = ROOT / "start" / "3_live_loop_execute.bat"
    if bat.is_file() and "verify_phase4_live_ready.py" in bat.read_text(encoding="utf-8"):
        print("  3_live_loop_execute.bat phase4 hook: OK")
    else:
        print("  3_live_loop_execute.bat phase4 hook: MISSING")
        issues.append("live_bat")

    if issues:
        print("\nPhase 4: NOT READY — fix issues above")
        return 1
    print("\nPhase 4: READY (prop preset + drift + slippage/spread telemetry)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
