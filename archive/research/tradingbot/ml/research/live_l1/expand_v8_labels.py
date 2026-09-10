"""L1b — expand v8 labels on unlabeled rows (production SL/TP + research RR=1.0)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.live_l2.edge_discovery import FUTURE_WINDOW, WARMUP
from tradingbot.ml.research.live_l2.sl_tp_sweep import _make_sl_tp_fn
from tradingbot.ml.research.phase35.label_alignment import resolve_label_with_sl_tp
from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles
from tradingbot.ml.research.phase39.expand_dataset import production_sl_tp_at_bar_fast

ROOT = Path(__file__).resolve().parents[4]
V8_IN = ROOT / "tradingbot" / "ml" / "research" / "live_l1" / "artifacts" / "dataset_v8_enriched.parquet"
OUT_DIR = ROOT / "tradingbot" / "ml" / "research" / "live_l1" / "artifacts"
OUT_PARQUET = OUT_DIR / "dataset_v8_labeled.parquet"
REPORT_PATH = ROOT / "live_l1b_label_expansion_report.json"

SYMBOL = "XAUUSD"
TIMEFRAME = "M5"
BATCH_SIZE = 5000
ATR_MULT = 2.0
RR_RESEARCH = 1.0


def _infer_direction(row: pd.Series) -> int | None:
    if "direction" in row.index and pd.notna(row["direction"]):
        d = int(row["direction"])
        if d in (1, -1):
            return d
    for col in ("ema200_distance", "ema200_distance_computed"):
        if col in row.index and pd.notna(row[col]):
            return 1 if float(row[col]) >= 0 else -1
    if "close" in row.index and "ema200_computed" in row.index:
        if pd.notna(row["close"]) and pd.notna(row["ema200_computed"]):
            return 1 if float(row["close"]) >= float(row["ema200_computed"]) else -1
    return None


def _label_to_binary(label: int) -> int | None:
    if label == int(Label.TP_FIRST):
        return 1
    if label == int(Label.SL_FIRST):
        return 0
    return None


def _row_atr(row: pd.Series, candles: pd.DataFrame, bar_idx: int) -> float:
    for col in ("atr_14_computed", "atr_14"):
        if col in row.index and pd.notna(row[col]) and float(row[col]) > 0:
            return float(row[col])
    if bar_idx >= 14:
        h = candles["high"].iloc[bar_idx - 13 : bar_idx + 1]
        l = candles["low"].iloc[bar_idx - 13 : bar_idx + 1]
        c = candles["close"].iloc[bar_idx - 13 : bar_idx + 1]
        tr = pd.concat([(h - l).abs(), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
        val = float(tr.mean())
        if np.isfinite(val) and val > 0:
            return val
    return 0.0


def _resolve_row_labels(
    candles: pd.DataFrame,
    bar_idx: int,
    direction: int,
    entry: float,
    atr: float,
    *,
    sl_tp_prod: bool,
    sl_tp_rr_fn,
) -> dict[str, Any] | None:
    if bar_idx < WARMUP or bar_idx >= len(candles) - FUTURE_WINDOW - 1:
        return None

    out: dict[str, Any] = {}
    if sl_tp_prod:
        sl_p, tp_p = production_sl_tp_at_bar_fast(candles, bar_idx, direction)
        if sl_p <= 0 or tp_p <= 0:
            return None
        res_p = resolve_label_with_sl_tp(
            candles,
            bar_idx,
            direction,
            sl_p,
            tp_p,
            future_window_bars=FUTURE_WINDOW,
            entry_price=entry,
        )
        lbl_p = _label_to_binary(int(res_p["label"]))
        if lbl_p is None:
            return None
        out["label_v3"] = lbl_p
        out["stop_loss_v3"] = round(sl_p, 6)
        out["take_profit_v3"] = round(tp_p, 6)

    sl_r, tp_r = sl_tp_rr_fn(entry, direction, atr)
    if sl_r <= 0 or tp_r <= 0:
        return None
    res_r = resolve_label_with_sl_tp(
        candles,
        bar_idx,
        direction,
        sl_r,
        tp_r,
        future_window_bars=FUTURE_WINDOW,
        entry_price=entry,
    )
    lbl_r = _label_to_binary(int(res_r["label"]))
    if lbl_r is None:
        return None
    out["label_v3_rr1"] = lbl_r
    out["stop_loss_rr1"] = round(sl_r, 6)
    out["take_profit_rr1"] = round(tp_r, 6)
    out["direction"] = direction
    return out


def _needs_label(row: pd.Series) -> bool:
    for col in ("label_v3", "label_v3_rr1"):
        if col not in row.index or pd.isna(row[col]) or row[col] not in (0, 1):
            return True
    return False


def expand_v8_labels(
    *,
    input_path: Path | None = None,
    batch_size: int = BATCH_SIZE,
    max_rows: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    in_path = input_path or V8_IN
    if not in_path.is_file():
        raise FileNotFoundError(f"v8 dataset missing: {in_path}")

    candles = resolve_fullest_candles(SYMBOL, TIMEFRAME)
    if candles is None or candles.empty:
        raise RuntimeError("fullest candle source missing")

    candles = candles.copy()
    candles.index = pd.to_datetime(candles.index, utc=True)
    candles = candles.sort_index()

    print(f"L1b: loading {in_path} ...", flush=True)
    df = pd.read_parquet(in_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    rows_before = len(df)
    labeled_before_v3 = int(df["label_v3"].isin([0, 1]).sum()) if "label_v3" in df.columns else 0
    labeled_before_rr1 = int(df["label_v3_rr1"].isin([0, 1]).sum()) if "label_v3_rr1" in df.columns else 0

    for col in ("label_v3_rr1", "stop_loss_rr1", "take_profit_rr1"):
        if col not in df.columns:
            df[col] = np.nan

    sl_tp_rr_fn = _make_sl_tp_fn("atr_rr", atr_mult=ATR_MULT, rr=RR_RESEARCH)

    work_mask = df.apply(_needs_label, axis=1)
    work_idx = df.index[work_mask].tolist()
    has_direction_idx = [
        i for i in work_idx if pd.notna(df.at[i, "direction"]) and int(df.at[i, "direction"]) in (1, -1)
    ]
    inferred_idx = [i for i in work_idx if i not in has_direction_idx]
    adaptive_stride = 1
    if len(inferred_idx) > 150_000:
        adaptive_stride = 3
        inferred_idx = inferred_idx[::adaptive_stride]
    work_idx = has_direction_idx + inferred_idx
    if max_rows is not None:
        work_idx = work_idx[:max_rows]

    df["_quarter"] = df["timestamp"].dt.to_period("Q").astype(str)
    quarter_groups: dict[str, list[int]] = {}
    for i in work_idx:
        q = str(df.at[i, "_quarter"])
        quarter_groups.setdefault(q, []).append(i)

    print(
        f"L1b: rows needing labels={len(work_idx)} / {rows_before} "
        f"(direction={len(has_direction_idx)} inferred_stride={adaptive_stride} "
        f"quarters={len(quarter_groups)})",
        flush=True,
    )

    resolved_count = 0
    skipped_no_direction = 0
    skipped_no_resolution = 0
    batches_done = 0

    ordered_quarters = sorted(quarter_groups.keys())
    for q_idx, quarter in enumerate(ordered_quarters):
        quarter_indices = quarter_groups[quarter]
        print(f"L1b: quarter {quarter} ({q_idx + 1}/{len(ordered_quarters)}) rows={len(quarter_indices)}", flush=True)
        for start in range(0, len(quarter_indices), batch_size):
            batch_indices = quarter_indices[start : start + batch_size]
        for i in batch_indices:
            row = df.loc[i]
            bar_idx = int(row["bar_index"]) if "bar_index" in row.index and pd.notna(row["bar_index"]) else None
            if bar_idx is None:
                ts = row["timestamp"]
                bar_idx = int(candles.index.searchsorted(ts, side="right") - 1)
            if bar_idx < WARMUP or bar_idx >= len(candles) - FUTURE_WINDOW - 1:
                skipped_no_resolution += 1
                continue

            direction = _infer_direction(row)
            if direction is None:
                skipped_no_direction += 1
                continue

            entry = float(row["close"]) if pd.notna(row.get("close")) else float(candles["close"].iloc[bar_idx])
            need_prod = pd.isna(row.get("label_v3")) or row.get("label_v3") not in (0, 1)
            need_rr1 = pd.isna(row.get("label_v3_rr1")) or row.get("label_v3_rr1") not in (0, 1)
            if not need_prod and not need_rr1:
                continue

            atr = _row_atr(row, candles, bar_idx)
            if atr <= 0:
                skipped_no_resolution += 1
                continue

            labels = _resolve_row_labels(
                candles,
                bar_idx,
                direction,
                entry,
                atr,
                sl_tp_prod=need_prod,
                sl_tp_rr_fn=sl_tp_rr_fn,
            )
            if labels is None:
                skipped_no_resolution += 1
                continue

            for k, v in labels.items():
                df.at[i, k] = v
            resolved_count += 1

            batches_done += 1
            if batches_done % 5 == 0 or start + batch_size >= len(quarter_indices):
                print(
                    f"  batch {batches_done}: resolved={resolved_count} "
                    f"skip_dir={skipped_no_direction} skip_nores={skipped_no_resolution}",
                    flush=True,
                )
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        df.drop(columns=["_quarter"], errors="ignore").to_parquet(OUT_PARQUET, index=False)

    df.drop(columns=["_quarter"], errors="ignore", inplace=True)
    labeled_after_v3 = int(df["label_v3"].isin([0, 1]).sum())
    labeled_after_rr1 = int(df["label_v3_rr1"].isin([0, 1]).sum())

    report = {
        "phase": "L1b",
        "title": "v8 Label Expansion",
        "title_fa": "گسترش label دیتاست v8",
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "verdict": "EXPANSION_COMPLETE",
        "research_only": True,
        "input": str(in_path),
        "output": str(OUT_PARQUET),
        "rows_total": rows_before,
        "rows_needing_labels": len(work_idx),
        "rows_newly_resolved": resolved_count,
        "labeled_v3_before": labeled_before_v3,
        "labeled_v3_after": labeled_after_v3,
        "labeled_rr1_before": labeled_before_rr1,
        "labeled_rr1_after": labeled_after_rr1,
        "delta_v3": labeled_after_v3 - labeled_before_v3,
        "delta_rr1": labeled_after_rr1 - labeled_before_rr1,
        "skipped_no_direction": skipped_no_direction,
        "skipped_no_resolution": skipped_no_resolution,
        "methodology": {
            "production_sl_tp": "production_sl_tp_at_bar_fast",
            "research_sl_tp": f"ATR{ATR_MULT}_RR{RR_RESEARCH}",
            "label_columns": ["label_v3", "label_v3_rr1"],
            "direction_inference": "existing direction or ema200_distance sign",
            "future_window_bars": FUTURE_WINDOW,
            "batch_size": batch_size,
            "adaptive_inferred_stride": adaptive_stride,
        },
    }
    return df, report


def write_outputs(df: pd.DataFrame, report: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PARQUET, index=False)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> dict[str, Any]:
    df, report = expand_v8_labels()
    write_outputs(df, report)
    print(
        f"L1b done: label_v3={report['labeled_v3_after']} label_v3_rr1={report['labeled_rr1_after']}",
        flush=True,
    )
    print(f"Parquet: {OUT_PARQUET}", flush=True)
    print(f"Report: {REPORT_PATH}", flush=True)
    return report


if __name__ == "__main__":
    main()
