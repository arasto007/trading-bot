from pathlib import Path
import sys
ROOT = Path(r"C:\Users\AMIR\Desktop\TradingBot new")
OUT = ROOT / "tradingbot" / "backtest" / "phase118_tick_forensic_validation.py"
CHUNK_DIR = ROOT / "tools" / "_phase118_chunks"
CHUNK_DIR.mkdir(parents=True, exist_ok=True)
mode = sys.argv[1]
if mode == "init":
    OUT.write_text("", encoding="utf-8")
    print("init", OUT)
elif mode == "add":
    # read stdin as utf-8 and append
    data = sys.stdin.buffer.read().decode("utf-8")
    with OUT.open("a", encoding="utf-8", newline="\n") as f:
        f.write(data)
    print("added", len(data))
elif mode == "verify":
    b = OUT.read_bytes()[:5]
    print(b, b.startswith(b'"""'), "size", OUT.stat().st_size)
else:
    raise SystemExit(mode)