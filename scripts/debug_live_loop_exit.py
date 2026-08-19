#!/usr/bin/env python3
"""Run live loop briefly and log why the process exits."""

from __future__ import annotations

import atexit
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _on_exit() -> None:
    print("debug_live_loop_exit: process atexit fired", flush=True)


def main() -> int:
    atexit.register(_on_exit)
    cmd = [sys.executable, "-m", "tradingbot", "--loop", "--execute"]
    print(f"Spawning: {' '.join(cmd)}", flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    deadline = time.time() + 120
    lines: list[str] = []
    assert proc.stdout is not None
    while time.time() < deadline:
        if proc.poll() is not None:
            while True:
                line = proc.stdout.readline()
                if not line:
                    break
                lines.append(line.rstrip())
                print(line.rstrip(), flush=True)
            break
        ready, _, _ = select.select([proc.stdout], [], [], 1.0)
        if ready:
            line = proc.stdout.readline()
            if line:
                lines.append(line.rstrip())
                print(line.rstrip(), flush=True)

    rc = proc.poll()
    if rc is None:
        print("Child still running after 120s — healthy loop (terminating probe)", flush=True)
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        rc = 0
        out = ROOT / "logs" / "debug_live_loop_exit.txt"
        out.write_text(
            "\n".join(lines[-25:])
            + "\n\nresult=stable_120s\nexit_code=0\n",
            encoding="utf-8",
        )
        print(f"Saved to {out}", flush=True)
        return 0

    print(f"Child exit code={rc}", flush=True)
    tail = [ln for ln in lines if ln][-25:]
    out = ROOT / "logs" / "debug_live_loop_exit.txt"
    out.write_text("\n".join(tail) + f"\n\nexit_code={rc}\n", encoding="utf-8")
    print(f"Saved tail to {out}", flush=True)
    return rc or 0


if __name__ == "__main__":
    raise SystemExit(main())
