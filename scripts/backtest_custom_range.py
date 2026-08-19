#!/usr/bin/env python3
"""بک‌تست با بازهٔ دلخواه — تاریخ و ساعت شروع/پایان به وقت تهران."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

TEHRAN = ZoneInfo("Asia/Tehran")
WARMUP_PAD_DAYS = {"M5": 4, "M15": 6, "H4": 65}
TF_LIST = ("M5", "M15", "H4")


def _to_tehran(entry_time: datetime) -> datetime:
    if entry_time.tzinfo is None:
        entry_time = entry_time.replace(tzinfo=timezone.utc)
    return entry_time.astimezone(TEHRAN)


def parse_tehran_dt(value: str) -> datetime:
    value = value.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=TEHRAN)
        except ValueError:
            continue
    raise ValueError(f"فرمت تاریخ/ساعت نامعتبر: {value!r} (مثال: 2026-06-12 12:00)")


def entry_in_tehran_range(
    entry_time: datetime,
    start: datetime,
    end: datetime,
) -> bool:
    local = _to_tehran(entry_time)
    return start <= local <= end


def metrics_from_trades(trades, initial_balance: float, timeframe: str) -> dict:
    from tradingbot.backtest.metrics import compute_metrics
    from tradingbot.backtest.models import BacktestResult

    if not trades:
        return {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "net_profit": 0.0,
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
        }

    net = sum(t.pnl for t in trades)
    stub = BacktestResult(
        config=None,
        initial_balance=initial_balance,
        final_balance=initial_balance + net,
        trades=trades,
        equity_curve=[
            {"equity": initial_balance + sum(t.pnl for t in trades[: i + 1])}
            for i in range(len(trades))
        ],
    )
    return compute_metrics(stub, timeframe=timeframe)


def _data_window_days(
    tf: str,
    start: datetime,
    end: datetime,
    now_tehran: datetime,
) -> tuple[int, int]:
    """تعداد روز داده از گذشته تا الان (offset=0) + warmup؛ فیلتر بازه در پایان."""
    pad = WARMUP_PAD_DAYS.get(tf, 7)
    days = max((now_tehran.date() - start.date()).days + pad + 2, pad + 3)
    return days, 0


async def run_one(
    symbol: str,
    tf: str,
    balance: float,
    start: datetime,
    end: datetime,
    *,
    use_cache: bool = False,
) -> dict | None:
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine

    now_tehran = datetime.now(TEHRAN)
    days, offset = _data_window_days(tf, start, end, now_tehran)

    cfg = BacktestConfig(
        symbols=[symbol],
        timeframe=tf,
        days=days,
        start_offset_days=offset,
        initial_balance=balance,
        use_cache=use_cache,
    )
    try:
        engine = BacktestEngine(cfg)
        result = await engine.run()
    except RuntimeError as exc:
        if "Not enough data" in str(exc):
            logging.warning("%s skipped — %s", tf, exc)
            return None
        raise

    filtered = [t for t in result.trades if entry_in_tehran_range(t.entry_time, start, end)]
    range_metrics = metrics_from_trades(filtered, balance, tf)

    return {
        "timeframe": tf,
        "days_fetched": days,
        "start_offset_days": offset,
        "symbol": symbol,
        "range_tehran": {
            "start": start.strftime("%Y-%m-%d %H:%M"),
            "end": end.strftime("%Y-%m-%d %H:%M"),
        },
        "all_trades": len(result.trades),
        "range_trades": len(filtered),
        "all_metrics": result.metrics,
        "range_metrics": range_metrics,
        "filtered_trades": [
            {
                "side": "BUY" if t.is_buy else "SELL",
                "entry_time_utc": str(t.entry_time),
                "entry_time_tehran": _to_tehran(t.entry_time).strftime("%Y-%m-%d %H:%M"),
                "pnl": round(t.pnl, 2),
                "reason": t.reason,
            }
            for t in filtered
        ],
    }


def load_request(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("start", "end", "balance"):
        if key not in data:
            raise ValueError(f"فیلد {key} در JSON نیست")
    return data


async def run_backtest(
    *,
    symbol: str,
    balance: float,
    start: datetime,
    end: datetime,
) -> dict:
    if end < start:
        raise ValueError("زمان پایان باید بعد از زمان شروع باشد")

    now_tehran = datetime.now(TEHRAN)
    if start > now_tehran:
        raise ValueError("زمان شروع در آینده است")

    rows = []
    for tf in TF_LIST:
        logging.info("Running %s | %s → %s", tf, start, end)
        row = await run_one(symbol, tf, balance, start, end, use_cache=False)
        if row:
            rows.append(row)
            rm = row["range_metrics"]
            print(
                f"\n=== {tf} | {row['range_tehran']['start']} → {row['range_tehran']['end']} (تهران) ===\n"
                f"  trades (all/range): {row['all_trades']} / {row['range_trades']}\n"
                f"  return %: {rm.get('return_pct', 0)} | PF: {rm.get('profit_factor')} | "
                f"WR: {rm.get('win_rate_pct')}% | net: {rm.get('net_profit')}"
            )

    return {
        "symbol": symbol,
        "balance": balance,
        "range_tehran": {
            "start": start.strftime("%Y-%m-%d %H:%M"),
            "end": end.strftime("%Y-%m-%d %H:%M"),
        },
        "generated_at_tehran": now_tehran.strftime("%Y-%m-%d %H:%M"),
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest custom Tehran datetime range")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--balance", type=float, default=None)
    parser.add_argument("--start", default=None, help="شروع تهران YYYY-MM-DD HH:MM")
    parser.add_argument("--end", default=None, help="پایان تهران YYYY-MM-DD HH:MM")
    parser.add_argument("--from-json", default=None, help="مسیر درخواست JSON از پنل HTA")
    parser.add_argument("--save", default=None)
    args = parser.parse_args()

    if args.from_json:
        req = load_request(Path(args.from_json))
        symbol = str(req.get("symbol", "XAUUSD"))
        balance = float(req["balance"])
        start = parse_tehran_dt(str(req["start"]))
        end = parse_tehran_dt(str(req["end"]))
    else:
        if not args.start or not args.end or args.balance is None:
            parser.error("یا --from-json یا هر سه --start --end --balance لازم است")
        symbol = args.symbol
        balance = float(args.balance)
        start = parse_tehran_dt(args.start)
        end = parse_tehran_dt(args.end)

    out = asyncio.run(
        run_backtest(symbol=symbol, balance=balance, start=start, end=end)
    )

    tag = f"{start.strftime('%Y%m%d_%H%M')}_{end.strftime('%Y%m%d_%H%M')}"
    save_path = args.save or str(ROOT / "reports" / f"backtest_range_{tag}_{symbol}.json")
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    Path(save_path).write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved -> {save_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
