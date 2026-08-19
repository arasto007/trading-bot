#!/usr/bin/env python3
"""End-to-end live pipeline audit — each stage from preflight to position mgmt."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


def ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def warn(msg: str) -> None:
    print(f"  [WARN] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    failures = 0
    warnings = 0

    section("1. Entry files exist")
    required = [
        "live_dashboard.hta",
        "start/3_live_loop_execute.bat",
        "start/5_stop_bot.bat",
        "scripts/run_live_watchdog.py",
        "scripts/start_live_daemon.ps1",
        "tradingbot/__main__.py",
        "tradingbot/application/live_runner.py",
        "tradingbot/kernel/trading_kernel.py",
    ]
    for rel in required:
        p = ROOT / rel.replace("/", os.sep)
        if p.is_file():
            ok(rel)
        else:
            fail(f"missing {rel}")
            failures += 1

    section("2. Preflight scripts")
    for rel in [
        "scripts/check_vol_regime_live_setup.py",
        "scripts/verify_vol_regime_live_ready.py",
        "scripts/verify_phase2_live_ready.py",
        "scripts/verify_phase4_live_ready.py",
    ]:
        p = ROOT / rel.replace("/", os.sep)
        if not p.is_file():
            fail(f"missing {rel}")
            failures += 1
            continue
        proc = subprocess.run(
            [sys.executable, str(p)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
        if proc.returncode == 0:
            ok(f"{rel} exit=0")
        elif rel.endswith("check_vol_regime_live_setup.py") and proc.returncode == 1:
            warn(f"{rel} exit=1 (MT5 offline?)")
            warnings += 1
        else:
            fail(f"{rel} exit={proc.returncode}")
            failures += 1

    section("3. Engine selection (VOL_REGIME path)")
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.config.live import get_live_config
    from tradingbot.ml.integration.factory import build_strategy_registry

    cfg = load_legacy_config()
    live = get_live_config()
    vol_on = bool(live.get("VOL_REGIME_ENABLED", False))
    ml_off = os.getenv("USE_ML_KERNEL", "").lower() in ("false", "0", "no")
    reg = build_strategy_registry(cfg)
    cls = type(reg).__name__
    if vol_on and ml_off and cls == "VolRegimeStrategyRegistry":
        ok(f"registry={cls} VOL_REGIME_ENABLED={vol_on} USE_ML_KERNEL=false")
    else:
        fail(f"unexpected registry={cls} vol={vol_on} ml_off={ml_off}")
        failures += 1

    section("4. Pipeline stages wired")
    from tradingbot.kernel.trading_kernel import TradingKernel
    from tradingbot.config.legacy_settings import kernel_settings_from_legacy
    from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter
    from tradingbot.adapters.indicator_engine import TechnicalIndicatorEngine
    from tradingbot.adapters.risk_gate import create_risk_gate
    from tradingbot.adapters.mt5_execution import Mt5ExecutionAdapter
    from tradingbot.adapters.mt5_position_manager import Mt5PositionManager

    os.environ["TRADINGBOT_DRY_RUN"] = "1"
    settings = kernel_settings_from_legacy()
    settings.extra.setdefault("BASE_DIR", str(ROOT))
    kernel = TradingKernel(
        settings=settings,
        market_data=Mt5MarketDataAdapter(cfg),
        indicators=TechnicalIndicatorEngine(cfg),
        strategies=reg,
        risk=create_risk_gate(cfg),
        executor=Mt5ExecutionAdapter(cfg),
        position_manager=Mt5PositionManager(cfg),
    )
    stages = [s.upper() for s in kernel.pipeline_stages]
    expected = ["DATA", "INDICATORS", "SIGNALS", "SIGNAL_FILTER", "RISK", "EXECUTION"]
    if stages == expected:
        ok(f"pipeline stages: {' -> '.join(stages)}")
    else:
        fail(f"pipeline mismatch: {stages}")
        failures += 1
    if kernel._position_manager is not None:
        ok("Mt5PositionManager attached")
    else:
        fail("no position manager")
        failures += 1

    section("5. Safety layers")
    from tradingbot.services.demo_account_guard import verify_demo_account_or_abort
    from tradingbot.services.kill_switch import KillSwitchService
    from tradingbot.services.startup_validator import validate_startup
    from tradingbot.services.mt5_order_guard import blocks_broker_orders

    os.environ["TRADINGBOT_DRY_RUN"] = "1"
    if blocks_broker_orders():
        ok("dry_run blocks broker orders")
    else:
        fail("dry_run should block orders")
        failures += 1

    ks = KillSwitchService(kernel, cfg)
    if hasattr(ks, "start") and hasattr(ks, "_check"):
        ok("KillSwitchService present")
    else:
        fail("KillSwitch incomplete")
        failures += 1

    section("6. MT5 connection + one dry cycle")
    mt5_ok = False
    try:
        from tradingbot.adapters.mt5_utils import attach_mt5_session, safe_release_mt5

        mt5_ok = attach_mt5_session(cfg, strict_account=False, use_lock=False)
        if mt5_ok:
            ok("MT5 attach (audit probe)")
            import MetaTrader5 as mt5

            ai = mt5.account_info()
            if ai:
                ok(f"account login={ai.login} balance={ai.balance:.2f}")
            demo_ok, demo_msg = verify_demo_account_or_abort(config=cfg)
            if demo_ok:
                ok(f"demo guard OK — {demo_msg}")
            else:
                warn(f"demo guard would block — {demo_msg}")
                warnings += 1
        else:
            warn("MT5 not connected — skip live cycle test")
            warnings += 1
    finally:
        try:
            from tradingbot.adapters.mt5_utils import safe_release_mt5

            safe_release_mt5()
        except Exception:
            pass

    if mt5_ok:
        async def _one_cycle() -> bool:
            kernel.state = kernel.state  # noqa: B018
            from tradingbot.domain.enums import KernelState

            kernel.state = KernelState.RUNNING
            try:
                await kernel.run_global_cycle()
                return True
            except Exception as exc:
                print(f"  cycle error: {exc}")
                return False

        cycle_ok = asyncio.run(_one_cycle())
        if cycle_ok:
            ok("one dry global cycle completed (no real orders)")
        else:
            fail("global cycle failed")
            failures += 1

    section("7. Signal evaluation on cached/live data")
    if mt5_ok:
        from tradingbot.domain.models import MarketKey
        from tradingbot.adapters.mt5_market_data import Mt5MarketDataAdapter

        md = Mt5MarketDataAdapter(cfg)
        asyncio.run(md.ensure_connected())
        asyncio.run(md.update_all(["XAUUSD"], ["5m"]))
        mk = MarketKey(symbol="XAUUSD", timeframe="5m")
        df = md.get_ohlcv(mk, bars=300)
        if df is not None and len(df) >= 80:
            ok(f"OHLCV bars={len(df)}")
            sig = reg.generate_signal(mk, df)
            if sig is None:
                warn("no signal on latest bar (normal — setup not met)")
                warnings += 1
            else:
                ok(f"signal generated: {sig.direction} conf={getattr(sig, 'confidence', '?')}")
        else:
            fail("insufficient OHLCV")
            failures += 1
        asyncio.run(md.shutdown())

    section("8. Position manager + recovery modules")
    for mod, cls in [
        ("tradingbot.adapters.mt5_position_manager", "Mt5PositionManager"),
        ("tradingbot.services.position_recovery_service", "PositionRecoveryService"),
    ]:
        m = importlib.import_module(mod)
        if hasattr(m, cls):
            ok(f"{cls} importable")
        else:
            fail(f"missing {cls}")
            failures += 1

    section("9. Unit tests (pipeline wiring)")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_dashboard_hta_wiring.py",
            "tests/test_vol_regime_signal.py",
            "tests/test_startup_validator.py",
            "-q",
            "--tb=no",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    tail = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        ok(f"pytest: {tail.strip().split(chr(10))[-1] if tail else 'passed'}")
    else:
        fail(f"pytest exit={proc.returncode}\n{tail[-800:]}")
        failures += 1

    section("SUMMARY")
    print(f"  FAILURES: {failures}")
    print(f"  WARNINGS: {warnings}")
    if failures == 0:
        print("\n  AUDIT: PIPELINE OK — live path structurally sound")
        if warnings:
            print("  (some warnings — MT5 offline or no signal today is normal)")
        return 0
    print("\n  AUDIT: ISSUES FOUND — review FAIL items above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
