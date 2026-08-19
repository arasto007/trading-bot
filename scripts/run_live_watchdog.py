#!/usr/bin/env python3
"""
Watchdog — نگه‌داشتن ربات live با ری‌استارت خودکار.

چرا لازم است؟
  اگر ربات مستقیم اجرا شود، با کرش/قطع MT5/بستن ناخواسته متوقف می‌ماند.
  این اسکریپت فرزند را دوباره بالا می‌آورد — به‌جز توقف دستی یا خاموش شدن PC.

خروج tradingbot:
  0 + فلگ manual_stop = توقف عمدی کاربر (watchdog هم متوقف می‌شود)
  0 بدون فلگ = خروج تمیز غیرمنتظره — ری‌استارت بعد از ۵ دقیقه
  2 = Kill Switch — ۴ ساعت صبر، بعد ری‌استارت (مگر manual_stop)
  دیگر = کرش/قطع — ری‌استارت بعد از ۵ دقیقه
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.services.manual_stop import is_manual_stop, read_manual_stop  # noqa: E402

LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "watchdog.log"

RESTART_DELAY_SEC = int(os.environ.get("WATCHDOG_RESTART_DELAY_SEC", "300"))
KILL_SWITCH_COOLDOWN_SEC = 4 * 60 * 60
MAX_RAPID_RESTARTS = 8
RAPID_WINDOW_SEC = 300
MAX_RESTART_DELAY_SEC = int(os.environ.get("WATCHDOG_MAX_RESTART_DELAY_SEC", "3600"))
STALL_POLL_SEC = int(os.environ.get("WATCHDOG_STALL_POLL_SEC", "30"))
STALL_TERMINATE_GRACE_SEC = 15


def _restart_delay_sec(*, rapid_count: int, exit_code: int) -> int:
    if exit_code == 2:
        return KILL_SWITCH_COOLDOWN_SEC
    exp = min(max(rapid_count - 1, 0), 5)
    delay = RESTART_DELAY_SEC * (2**exp)
    return min(delay, MAX_RESTART_DELAY_SEC)


def should_stop_watchdog(exit_code: int) -> bool:
    """آیا watchdog باید کاملاً متوقف شود؟"""
    return exit_code == 0 and is_manual_stop()


def should_restart_after_exit(exit_code: int) -> bool:
    """آیا بعد از این خروج باید ری‌استارت شود؟"""
    if should_stop_watchdog(exit_code):
        return False
    if exit_code == 0:
        return True
    return True


def _log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).isoformat()} | {msg}"
    print(line, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _bot_cmd() -> list[str]:
    return [sys.executable, "-m", "tradingbot", "--loop", "--execute"]


def _terminate_child(proc: subprocess.Popen) -> int:
    if proc.poll() is not None:
        return int(proc.returncode or 0)
    _log(f"Terminating stalled child pid={proc.pid}")
    try:
        proc.terminate()
        try:
            return int(proc.wait(timeout=STALL_TERMINATE_GRACE_SEC) or 0)
        except subprocess.TimeoutExpired:
            _log("Child did not exit after terminate — killing")
            proc.kill()
            return int(proc.wait(timeout=10) or 0)
    except Exception as exc:
        _log(f"Failed to stop stalled child: {exc}")
        return int(proc.poll() or 1)


def _supervise_child(proc: subprocess.Popen, started_at: datetime) -> tuple[int, str]:
    """Watch a running child. Returns (exit_code, reason) where reason is exit|stall_restart."""
    from tradingbot.services.live_loop_health import (
        append_stall_alert,
        evaluate_heartbeat_freshness,
        evaluate_ny_stall,
        mark_stall_restart,
        read_heartbeat,
        stall_restart_done_for,
        write_watchdog_heartbeat,
        StallDecision,
    )

    last_alert_reason = ""
    while True:
        code = proc.poll()
        if code is not None:
            return int(code), "exit"
        now = datetime.now(timezone.utc)
        today = now.date().isoformat()
        already = stall_restart_done_for(today)
        try:
            write_watchdog_heartbeat()
        except Exception:
            pass
        hb = read_heartbeat()
        fresh = evaluate_heartbeat_freshness(
            now=now,
            heartbeat=hb,
            child_started_at=started_at,
            already_restarted=already,
        )
        ny = evaluate_ny_stall(
            now=now,
            heartbeat=hb,
            child_started_at=started_at,
            already_restarted=already,
        )
        stalled = bool(fresh.stalled or ny.stalled)
        should_restart = bool(fresh.should_restart or ny.should_restart)
        reason = "+".join(
            r for r in (fresh.reason if fresh.stalled else "", ny.reason if ny.stalled else "")
            if r and r != "ok" and r != "outside_ny_window"
        ) or (ny.reason if ny.stalled else fresh.reason)
        if stalled:
            if reason != last_alert_reason:
                alert = StallDecision(
                    stalled=True,
                    should_restart=should_restart,
                    reason=reason,
                    heartbeat_age_sec=fresh.heartbeat_age_sec,
                    bar_lag_sec=ny.bar_lag_sec,
                    in_ny_window=ny.in_ny_window,
                )
                append_stall_alert(
                    alert,
                    extra={"pid": proc.pid, "child_started_at": started_at.isoformat()},
                )
                last_alert_reason = reason
                _log(
                    f"Stall detected | reason={reason} "
                    f"hb_age={fresh.heartbeat_age_sec}s bar_lag={ny.bar_lag_sec}s "
                    f"restart={should_restart}"
                )
            if should_restart:
                mark_stall_restart(today)
                code = _terminate_child(proc)
                return int(code), "stall_restart"
        else:
            last_alert_reason = ""
        time.sleep(STALL_POLL_SEC)


def _run_pre_live_dataset_maintenance() -> None:
    """Skip ML dataset maintenance — VOL_REGIME live path does not use ML PipelineCache."""
    _log("Pre-live dataset maintenance skipped (VOL_REGIME core)")


def main() -> int:
    cmd = _bot_cmd()
    if is_manual_stop():
        detail = read_manual_stop() or "manual_stop.flag"
        _log(
            f"manual_stop.flag is set ({detail}) — watchdog not starting. "
            f"Run start\\3_live_loop_execute.bat to clear and start LIVE."
        )
        return 0

    _log(
        f"Watchdog started | cmd={' '.join(cmd)} | restart_delay={RESTART_DELAY_SEC}s"
    )

    _run_pre_live_dataset_maintenance()

    rapid_count = 0
    window_start = time.time()

    while True:
        if is_manual_stop():
            detail = read_manual_stop() or "manual_stop.flag"
            _log(f"Manual stop flag detected ({detail}) — watchdog stopping")
            return 0

        if time.time() - window_start > RAPID_WINDOW_SEC:
            rapid_count = 0
            window_start = time.time()

        _log("Starting tradingbot child process...")
        started_at = datetime.now(timezone.utc)
        proc = subprocess.Popen(cmd, cwd=str(ROOT))
        code, stop_reason = _supervise_child(proc, started_at)
        _log(f"tradingbot exited | code={code} | reason={stop_reason}")

        if code != 0:
            try:
                from tradingbot.services.phase51a_forward_cert import is_phase51a_enabled, log_runtime_error

                if is_phase51a_enabled():
                    log_runtime_error(stage="watchdog_child_exit", message=f"exit_code={code}")
            except Exception:
                pass

        if is_manual_stop():
            detail = read_manual_stop() or "manual_stop.flag"
            _log(f"Manual stop flag detected after child exit ({detail}) — watchdog stopping")
            return 0

        if should_stop_watchdog(code):
            detail = read_manual_stop() or "manual_stop"
            _log(f"Clean manual stop ({detail}) — watchdog stopping")
            return 0

        if not should_restart_after_exit(code):
            _log("No restart scheduled — watchdog stopping")
            return 0

        if stop_reason == "stall_restart":
            _log("NY stall — immediate one-shot restart (no crash delay)")
            rapid_count = 0
            window_start = time.time()
            continue

        if code == 2:
            delay = _restart_delay_sec(rapid_count=rapid_count, exit_code=code)
            _log(f"Kill Switch exit — cooldown {delay // 3600}h before retry")
            time.sleep(delay)
            rapid_count = 0
            window_start = time.time()
            continue

        if code != 0:
            rapid_count += 1
            if rapid_count >= MAX_RAPID_RESTARTS:
                _log(
                    f"Too many rapid restarts ({rapid_count}) — "
                    f"waiting {RAPID_WINDOW_SEC}s"
                )
                time.sleep(RAPID_WINDOW_SEC)
                rapid_count = 0
                window_start = time.time()
                continue

        delay = _restart_delay_sec(
            rapid_count=max(rapid_count, 1),
            exit_code=code,
        )
        if code == 0:
            _log(
                f"Unexpected clean exit (no manual flag) — auto-restart in {delay}s"
            )
        else:
            _log(
                f"Auto-restart in {delay}s "
                f"(rapid={rapid_count}/{MAX_RAPID_RESTARTS})"
            )
        time.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(main())
