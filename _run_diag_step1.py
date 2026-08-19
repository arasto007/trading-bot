import subprocess, os, sys
from pathlib import Path

base = Path(r"C:\Users\AMIR\Desktop\TradingBot new")
lines = []

# 1 terminal64
lines.append("=== 1. terminal64 ===")
try:
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process terminal64 -ErrorAction SilentlyContinue | ForEach-Object { $_.Id.ToString() + ' ' + $_.ProcessName }"],
        capture_output=True, text=True, timeout=30, cwd=str(base))
    out = (r.stdout or "").strip()
    lines.append(out if out else "NOT RUNNING")
except Exception as e:
    lines.append(f"ERROR: {e}")

# 2 python - use wmic or tasklist fallback
lines.append("=== 2. watchdog / tradingbot --loop ===")
tradingbot_loop = False
watchdog_found = False
try:
    ps_script = r"""
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | ForEach-Object {
  $cl = $_.CommandLine
  if ($cl -match 'watchdog|tradingbot') {
    Write-Output ("PID=" + $_.ProcessId + " CMD=" + $cl)
  }
}
"""
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script],
                       capture_output=True, text=True, timeout=90, cwd=str(base))
    out = (r.stdout or "").strip()
    if out:
        lines.append(out)
        for line in out.splitlines():
            low = line.lower()
            if "watchdog" in low:
                watchdog_found = True
            if "tradingbot" in low and "--loop" in low:
                tradingbot_loop = True
    else:
        lines.append("NONE MATCHING watchdog/tradingbot")
    if r.stderr and r.stderr.strip():
        lines.append("STDERR: " + r.stderr.strip()[:500])
except Exception as e:
    lines.append(f"ERROR: {e}")

lines.append(f"tradingbot_loop_running={tradingbot_loop}")
lines.append(f"watchdog_running={watchdog_found}")

for rel in ["data/manual_stop.flag", "data/emergency_stop.json", "logs/mt5_ipc.lock"]:
    p = base / rel
    lines.append(f"=== {rel} ===")
    if p.exists():
        lines.append(p.read_text(encoding="utf-8", errors="replace").rstrip())
    else:
        lines.append("MISSING")

report = base / "_diag_report.txt"
report.write_text("\n".join(lines) + f"\n---META---\ntradingbot_loop={tradingbot_loop}\n", encoding="utf-8")
print("\n".join(lines))
print("---META---")
print(f"tradingbot_loop={tradingbot_loop}")
