import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OK = ROOT / "data" / "hta_mshta_ok.txt"
if OK.exists():
    OK.unlink()
subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
subprocess.Popen(["mshta.exe", str(ROOT / "live_dashboard.hta")], cwd=str(ROOT))
passed = False
for _ in range(24):
    time.sleep(0.5)
    if OK.exists():
        print("FULL_HTA_OK", OK.read_text(encoding="utf-8"))
        passed = True
        break
if not passed:
    print("FULL_HTA_FAIL")
subprocess.run(["taskkill", "/F", "/IM", "mshta.exe"], capture_output=True)
raise SystemExit(0 if passed else 1)
