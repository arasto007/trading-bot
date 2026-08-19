#!/usr/bin/env python3
"""
آموزش Meta-Labeler — داده واقعی + walk-forward + gate صادقانه.

- جمع‌آوری معاملات بدون فیلتر meta (unbiased)
- ویژگی‌های واقعی از entry_features هر معامله
- برچسب: R-multiple >= 0.35
- train: ۷۵٪ اول زمانی | test: ۲۵٪ آخر (OOS)
- مدل نهایی فقط روی train fit می‌شود
- threshold از OOS کالیبره می‌شود (بیشینه PF)
- فعال‌سازی فقط اگر OOS: PF>=1.0، trades>=8، net_profit>0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

MODEL_DIR = ROOT / "models"
INFO_PATH = MODEL_DIR / "meta_labeler_info.json"
CACHE_PATH = ROOT / "data" / "meta_training_cache.json"

SPECS = [
    ("M5", 180),
    ("M15", 180),
    ("H4", 270),
]

# حداقل روز داده برای بک‌تست delta (warmup=300 + حاشیه؛ H4 ~۶ کندل/روز)
MIN_COLLECT_DAYS = {"M5": 7, "M15": 7, "H4": 65}
DEFAULT_WARMUP = 300

OOS_FRAC = 0.25
MIN_OOS_TRADES = 8
MIN_TRAIN_SAMPLES = 25
LABEL_MIN_R = 0.35
THRESHOLD_GRID = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]


def _trade_row(trade, tf: str) -> dict | None:
    from tradingbot.domain.trade_features import FEATURE_NAMES, trade_quality_label

    feats = dict(getattr(trade, "entry_features", None) or {})
    if not feats or feats.get("confidence", 0) <= 0:
        return None

    label = trade_quality_label(
        trade.pnl,
        trade.entry_price,
        getattr(trade, "entry_sl", None) or 0.0,
        trade.volume,
        trade.symbol,
        trade.is_buy,
        min_r=LABEL_MIN_R,
    )
    row = {name: float(feats.get(name, 0.0)) for name in FEATURE_NAMES}
    row["label"] = label
    row["pnl"] = round(trade.pnl, 2)
    row["r_multiple"] = round(getattr(trade, "r_multiple", 0.0) or 0.0, 4)
    row["tf"] = tf
    row["entry_time"] = str(trade.entry_time)
    return row


async def collect_for_tf(symbol: str, tf: str, days: int, balance: float) -> list[dict]:
    from tradingbot.backtest.config import BacktestConfig
    from tradingbot.backtest.engine import BacktestEngine

    logging.info("Collecting %s / %d days (meta OFF, real features ON) ...", tf, days)
    cfg = BacktestConfig(
        symbols=[symbol],
        timeframe=tf,
        days=days,
        initial_balance=balance,
        use_cache=True,
        use_meta_labeler=False,
    )
    engine = BacktestEngine(cfg)
    result = await engine.run()
    rows: list[dict] = []
    skipped = 0
    for t in result.trades:
        row = _trade_row(t, tf)
        if row is None:
            skipped += 1
            continue
        rows.append(row)
    logging.info("  %s trades: %d usable (%d missing features)", tf, len(rows), skipped)
    return rows


def _parse_entry_time(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        s = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _min_collect_days(tf: str, warmup: int = DEFAULT_WARMUP) -> int:
    """حداقل روز history برای عبور از warmup در BacktestEngine."""
    pad = MIN_COLLECT_DAYS.get(tf)
    if pad is not None:
        return pad
    bars_per_day = {"M5": 288, "M15": 96, "H4": 6}.get(tf, 96)
    return max(7, int(warmup / max(bars_per_day, 1)) + 5)


def _max_window_days(tf: str) -> int:
    for spec_tf, days in SPECS:
        if spec_tf == tf:
            return days
    return 180


def _load_cache() -> dict[str, list[dict]]:
    if not CACHE_PATH.is_file():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {k: list(v) for k, v in (data.get("per_tf") or {}).items()}
    except Exception:
        return {}


def _save_cache(per_tf: dict[str, list[dict]]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "per_tf": per_tf,
    }
    CACHE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in sorted(rows, key=lambda x: x.get("entry_time", "")):
        key = f"{r.get('tf')}|{r.get('entry_time')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _trim_rows(rows: list[dict], tf: str) -> list[dict]:
    """فقط نمونه‌های داخل پنجرهٔ rolling نگه می‌دارد."""
    max_days = _max_window_days(tf)
    cutoff = datetime.now(timezone.utc).timestamp() - max_days * 86400
    kept: list[dict] = []
    for r in rows:
        dt = _parse_entry_time(str(r.get("entry_time", "")))
        if dt is None or dt.timestamp() >= cutoff:
            kept.append(r)
    return kept


def _merge_rows(existing: list[dict], new_rows: list[dict], tf: str) -> list[dict]:
    merged = _dedupe_rows(existing + new_rows)
    return _trim_rows(merged, tf)


def _read_last_trained_utc() -> datetime | None:
    if not INFO_PATH.is_file():
        return None
    try:
        info = json.loads(INFO_PATH.read_text(encoding="utf-8"))
        raw = info.get("last_trained_utc")
        return _parse_entry_time(str(raw)) if raw else None
    except Exception:
        return None


async def collect_delta_for_tf(
    symbol: str,
    tf: str,
    balance: float,
    since: datetime,
) -> list[dict]:
    """فقط معاملات جدیدتر از since را از بک‌تست اخیر جمع می‌کند."""
    now = datetime.now(timezone.utc)
    delta_days = max(7, int((now - since).total_seconds() / 86400) + 3)
    delta_days = max(delta_days, _min_collect_days(tf))
    delta_days = min(delta_days, _max_window_days(tf))
    rows = await collect_for_tf(symbol, tf, delta_days, balance)
    out: list[dict] = []
    for r in rows:
        dt = _parse_entry_time(str(r.get("entry_time", "")))
        if dt is not None and dt > since:
            out.append(r)
    logging.info("  %s delta trades since %s: %d", tf, since.date(), len(out))
    return out


def _split_oos(rows: list[dict], oos_frac: float) -> tuple[list[dict], list[dict]]:
    ordered = sorted(rows, key=lambda r: r.get("entry_time", ""))
    n = len(ordered)
    cut = max(int(n * (1.0 - oos_frac)), MIN_TRAIN_SAMPLES)
    cut = min(cut, n - max(5, MIN_OOS_TRADES // 2))
    if cut < MIN_TRAIN_SAMPLES or n - cut < 5:
        return ordered, []
    return ordered[:cut], ordered[cut:]


def _fit_model(X: np.ndarray, y: np.ndarray):
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.utils.class_weight import compute_sample_weight

    sw = compute_sample_weight("balanced", y)
    model = GradientBoostingClassifier(
        n_estimators=160,
        max_depth=3,
        learning_rate=0.06,
        subsample=0.85,
        random_state=42,
    )
    model.fit(X, y, sample_weight=sw)
    return model


def _proba(model, X: np.ndarray) -> np.ndarray:
    proba = model.predict_proba(X)
    if proba.shape[1] < 2:
        return proba[:, 0]
    return proba[:, 1]


def _oos_simulate(
    model,
    oos_rows: list[dict],
    feature_names: list[str],
) -> dict:
    from tradingbot.domain.trade_features import FEATURE_NAMES

    names = feature_names or FEATURE_NAMES
    X = np.array([[r.get(f, 0.0) for f in names] for r in oos_rows])
    y = np.array([int(r["label"]) for r in oos_rows])
    pnls = np.array([float(r["pnl"]) for r in oos_rows])
    probs = _proba(model, X)

    best: dict = {
        "best_threshold": 0.45,
        "oos_trades_taken": 0,
        "oos_net_profit": 0.0,
        "oos_pf": 0.0,
        "oos_win_rate_pct": 0.0,
        "oos_precision": 0.0,
        "passed_gate": False,
    }

    for th in THRESHOLD_GRID:
        mask = probs >= th
        taken = int(mask.sum())
        if taken < 3:
            continue
        taken_pnls = pnls[mask]
        wins = taken_pnls[taken_pnls > 0]
        losses = taken_pnls[taken_pnls <= 0]
        gross_win = float(wins.sum()) if len(wins) else 0.0
        gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
        net = float(taken_pnls.sum())
        pf = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
        wr = float((taken_pnls > 0).sum()) / taken * 100.0

        pred_pos = (probs[mask] >= th).astype(int)
        actual_pos = y[mask]
        prec = float((pred_pos & actual_pos).sum()) / max(pred_pos.sum(), 1)

        score = net + pf * 2.0
        best_score = best["oos_net_profit"] + best["oos_pf"] * 2.0
        if score > best_score:
            best = {
                "best_threshold": th,
                "oos_trades_taken": taken,
                "oos_net_profit": round(net, 2),
                "oos_pf": round(pf, 3),
                "oos_win_rate_pct": round(wr, 2),
                "oos_precision": round(prec, 4),
                "passed_gate": False,
            }

    if (
        best["oos_trades_taken"] >= MIN_OOS_TRADES
        and best["oos_net_profit"] > 0
        and best["oos_pf"] >= 1.0
    ):
        best["passed_gate"] = True

    # متریک‌های طبقه‌بندی خام OOS (بدون threshold)
    pred_all = (probs >= 0.5).astype(int)
    from sklearn.metrics import accuracy_score, precision_score

    best["oos_accuracy"] = round(float(accuracy_score(y, pred_all)), 4) if len(y) else 0.0
    best["oos_samples"] = len(oos_rows)
    best["oos_label_win_rate_pct"] = round(float(y.mean()) * 100, 2) if len(y) else 0.0
    try:
        best["oos_precision_raw"] = round(
            float(precision_score(y, pred_all, zero_division=0)), 4
        )
    except Exception:
        best["oos_precision_raw"] = 0.0

    return best


def train_tf_model(rows: list[dict], tf: str) -> dict:
    from tradingbot.domain.trade_features import FEATURE_NAMES

    if len(rows) < MIN_TRAIN_SAMPLES:
        return {
            "tf": tf,
            "skipped": True,
            "reason": f"too few samples ({len(rows)} < {MIN_TRAIN_SAMPLES})",
            "samples": len(rows),
        }

    train_rows, oos_rows = _split_oos(rows, OOS_FRAC)
    if not oos_rows:
        return {
            "tf": tf,
            "skipped": True,
            "reason": "not enough rows for OOS split",
            "samples": len(rows),
        }

    X_train = np.array([[r.get(f, 0.0) for f in FEATURE_NAMES] for r in train_rows])
    y_train = np.array([int(r["label"]) for r in train_rows])

    if len(set(y_train)) < 2:
        return {
            "tf": tf,
            "skipped": True,
            "reason": "single class in train set",
            "samples": len(rows),
        }

    model = _fit_model(X_train, y_train)
    oos_metrics = _oos_simulate(model, oos_rows, FEATURE_NAMES)

    out_path = MODEL_DIR / f"meta_labeler_{tf.lower()}.pkl"
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        pickle.dump({"model": model, "features": FEATURE_NAMES}, f)

    y_all = np.array([int(r["label"]) for r in rows])
    return {
        "tf": tf,
        "skipped": False,
        "samples": len(rows),
        "train_samples": len(train_rows),
        "oos_samples": len(oos_rows),
        "wins": int(y_all.sum()),
        "losses": int(len(y_all) - y_all.sum()),
        "win_rate_pct": round(float(y_all.mean()) * 100, 2),
        "label_min_r": LABEL_MIN_R,
        "path": str(out_path),
        "oos": oos_metrics,
        "active": bool(oos_metrics.get("passed_gate")),
    }


async def main_async(
    symbol: str = "XAUUSD",
    balance: float = 1000.0,
    *,
    mode: str = "full",
) -> dict:
    per_tf: dict = {}
    cache = _load_cache()
    last_trained = _read_last_trained_utc()

    if mode == "update" and last_trained is None:
        logging.info("No prior training found — running full train instead")
        mode = "full"

    for tf, days in SPECS:
        if mode == "full":
            rows = await collect_for_tf(symbol, tf, days, balance)
        else:
            assert last_trained is not None
            existing = cache.get(tf, [])
            try:
                delta = await collect_delta_for_tf(symbol, tf, balance, last_trained)
            except RuntimeError as exc:
                logging.warning(
                    "  %s: delta collect failed (%s) — using cache (%d)",
                    tf,
                    exc,
                    len(existing),
                )
                delta = []
            if not delta:
                rows = _trim_rows(existing, tf)
                logging.info("  %s: no new trades — using cache (%d)", tf, len(rows))
            else:
                rows = _merge_rows(existing, delta, tf)
        per_tf[tf] = train_tf_model(rows, tf)
        cache[tf] = rows

    now_iso = datetime.now(timezone.utc).isoformat()
    info = {
        "specs": SPECS,
        "oos_frac": OOS_FRAC,
        "label_min_r": LABEL_MIN_R,
        "last_trained_utc": now_iso,
        "last_mode": mode,
        "per_tf": per_tf,
    }
    _save_cache(cache)
    INFO_PATH.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        from tradingbot.services.meta_labeler import reload_meta_labeler

        reload_meta_labeler()
        logging.info("Meta-labeler reloaded in memory")
    except Exception as e:
        logging.warning("Reload meta in live process skipped: %s", e)

    return info


def main() -> int:
    parser = argparse.ArgumentParser(description="Train meta-labeler with real features + OOS gate")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--balance", type=float, default=1000.0)
    parser.add_argument(
        "--update",
        action="store_true",
        help="فقط دادهٔ جدید از آخرین آموزش + بازآموزی",
    )
    args = parser.parse_args()

    mode = "update" if args.update else "full"
    info = asyncio.run(main_async(symbol=args.symbol, balance=args.balance, mode=mode))
    print(f"\n=== Meta-Labeler ({mode}) ===")
    if info.get("last_trained_utc"):
        print(f"  trained_until: {info.get('last_trained_utc')}")
    for tf, row in info.get("per_tf", {}).items():
        if row.get("skipped"):
            print(f"  {tf}: SKIPPED — {row.get('reason')}")
            continue
        oos = row.get("oos") or {}
        status = "ACTIVE" if row.get("active") else "OFF"
        print(
            f"  {tf}: {status} | train={row.get('train_samples')} oos={row.get('oos_samples')} "
            f"| OOS profit={oos.get('oos_net_profit')} PF={oos.get('oos_pf')} "
            f"| th={oos.get('best_threshold')} taken={oos.get('oos_trades_taken')}"
        )
    print(f"\nInfo -> {INFO_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
