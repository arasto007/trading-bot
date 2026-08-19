"""Phase 52 — label & dataset diagnosis on v7 (research only)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from tradingbot.ml.dataset.schema import Label
from tradingbot.ml.research.phase35.label_alignment import (
    production_sl_tp_at_bar,
    resolve_label_with_sl_tp,
    sl_tp_distance_metrics,
)

ARTIFACTS = ROOT / "tradingbot" / "ml" / "research" / "phase52" / "artifacts"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
V7_PATH = ROOT / "tradingbot" / "ml" / "research" / "phase49" / "artifacts" / "dataset_v7_ml_signals.parquet"


def _pf_from_labels(labels: list[int]) -> float:
    wins = sum(1 for x in labels if x == 1)
    losses = sum(1 for x in labels if x == 0)
    if losses == 0:
        return 2.0 if wins > 0 else 0.0
    return round(wins / losses, 4)


def _pct(d: dict[str, int], key: str) -> float:
    c = d.get("checked", 0)
    return round(d.get(key, 0) / max(c, 1) * 100, 2)


def full_dataset_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Parquet-only statistics — no forward simulation."""
    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    label_col = "label_v3" if "label_v3" in work.columns else "label"
    binary = work[work[label_col].isin([0, 1])]

    by_year: dict[str, dict[str, float | int]] = {}
    for year, grp in binary.groupby(binary["timestamp"].dt.year):
        labels = grp[label_col].astype(int).tolist()
        by_year[str(int(year))] = {
            "rows": len(grp),
            "wins": sum(1 for x in labels if x == 1),
            "losses": sum(1 for x in labels if x == 0),
            "win_rate_pct": round(sum(1 for x in labels if x == 1) / max(len(labels), 1) * 100, 2),
            "pf_proxy": _pf_from_labels(labels),
        }

    by_regime: dict[str, dict[str, float | int]] = {}
    if "regime" in binary.columns:
        for regime, grp in binary.groupby("regime"):
            labels = grp[label_col].astype(int).tolist()
            by_regime[str(regime)] = {
                "rows": len(grp),
                "pf_proxy": _pf_from_labels(labels),
                "win_rate_pct": round(sum(1 for x in labels if x == 1) / max(len(labels), 1) * 100, 2),
            }

    by_source: dict[str, int] = {}
    if "source_dataset" in work.columns:
        by_source = {str(k): int(v) for k, v in work["source_dataset"].value_counts().items()}

    labels_all = binary[label_col].astype(int).tolist()
    sl_tp_present = 0
    if "stop_loss_v3" in work.columns and "take_profit_v3" in work.columns:
        sl_tp_present = int(((work["stop_loss_v3"] > 0) & (work["take_profit_v3"] > 0)).sum())

    return {
        "total_rows": len(work),
        "binary_label_rows": len(binary),
        "label_col": label_col,
        "wins": sum(1 for x in labels_all if x == 1),
        "losses": sum(1 for x in labels_all if x == 0),
        "win_rate_pct": round(sum(1 for x in labels_all if x == 1) / max(len(labels_all), 1) * 100, 2),
        "pf_proxy": _pf_from_labels(labels_all),
        "sl_tp_v3_present_rows": sl_tp_present,
        "by_year": by_year,
        "by_regime": by_regime,
        "by_source_dataset": by_source,
        "year_span": [str(work["timestamp"].min()), str(work["timestamp"].max())],
    }


def audit_sample(
    df: pd.DataFrame,
    candles: pd.DataFrame,
    *,
    sample_size: int = 1500,
    future_window_bars: int = 72,
    seed: int = 42,
) -> dict[str, Any]:
    """Re-resolve labels on sample vs stored v3 + production SL/TP."""
    from tradingbot.ml.dataset.label_quality import LabelQualityValidator
    from tradingbot.ml.research.phase49.bar_index import resolve_bar_index

    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    candle_min, candle_max = candles.index.min(), candles.index.max()
    overlap = work[(work["timestamp"] >= candle_min) & (work["timestamp"] <= candle_max)]
    n = min(sample_size, len(overlap))
    sample = overlap.sample(n=n, random_state=seed) if n > 0 else overlap.head(0)

    stored_vs_stored_sl_tp: dict[str, int] = {"match": 0, "mismatch": 0, "no_resolution": 0, "checked": 0}
    stored_vs_production: dict[str, int] = {"match": 0, "mismatch": 0, "no_resolution": 0, "checked": 0}
    sl_tp_stats: list[dict[str, float]] = []
    mismatch_examples: list[dict[str, Any]] = []
    aligned_rows: list[dict[str, Any]] = []

    for _, row in sample.iterrows():
        ts = row["timestamp"]
        idx = int(row["bar_index"]) if pd.notna(row.get("bar_index")) else resolve_bar_index(candles, ts)
        if idx < 20 or idx >= len(candles) - future_window_bars - 1:
            continue

        direction = int(row["direction"])
        entry = float(row["entry_price"])
        stored_label = int(row.get("label_v3", row.get("label", -1)))
        sl_stored = float(row.get("stop_loss_v3", row.get("stop_loss", 0)))
        tp_stored = float(row.get("take_profit_v3", row.get("take_profit", 0)))
        confidence = float(row.get("ml_confidence", 0.55) or 0.55)

        if sl_stored > 0 and tp_stored > 0:
            resolved = resolve_label_with_sl_tp(
                candles, idx, direction, sl_stored, tp_stored,
                future_window_bars=future_window_bars, entry_price=entry,
            )
            stored_vs_stored_sl_tp["checked"] += 1
            r_label = int(resolved["label"])
            if r_label == int(Label.NO_RESOLUTION):
                stored_vs_stored_sl_tp["no_resolution"] += 1
            elif r_label == stored_label:
                stored_vs_stored_sl_tp["match"] += 1
            else:
                stored_vs_stored_sl_tp["mismatch"] += 1

        sl_prod, tp_prod = production_sl_tp_at_bar(candles, idx, direction, confidence=confidence)
        if sl_prod > 0 and tp_prod > 0:
            prod_resolved = resolve_label_with_sl_tp(
                candles, idx, direction, sl_prod, tp_prod,
                future_window_bars=future_window_bars, entry_price=entry,
            )
            stored_vs_production["checked"] += 1
            p_label = int(prod_resolved["label"])
            if p_label == int(Label.NO_RESOLUTION):
                stored_vs_production["no_resolution"] += 1
            elif p_label == stored_label:
                stored_vs_production["match"] += 1
            else:
                stored_vs_production["mismatch"] += 1
                if len(mismatch_examples) < 15:
                    mismatch_examples.append({
                        "timestamp": str(ts),
                        "stored_label": stored_label,
                        "production_label": p_label,
                        "direction": direction,
                        "sl_stored": sl_stored,
                        "tp_stored": tp_stored,
                        "sl_production": sl_prod,
                        "tp_production": tp_prod,
                    })

            if sl_stored > 0 and tp_stored > 0:
                sl_tp_stats.append(sl_tp_distance_metrics(entry, direction, sl_stored, tp_stored, sl_prod, tp_prod))

            aligned_rows.append({
                "timestamp": str(ts),
                "stored_label": stored_label,
                "production_label": p_label,
                "label_changed": stored_label != p_label,
            })

    avg_sl_delta = round(sum(s["sl_dist_delta_pct"] for s in sl_tp_stats) / max(len(sl_tp_stats), 1), 2)
    avg_tp_delta = round(sum(s["tp_dist_delta_pct"] for s in sl_tp_stats) / max(len(sl_tp_stats), 1), 2)
    avg_rr_stored = round(sum(s["rr_dataset"] for s in sl_tp_stats) / max(len(sl_tp_stats), 1), 4)
    avg_rr_prod = round(sum(s["rr_production"] for s in sl_tp_stats) / max(len(sl_tp_stats), 1), 4)

    stored_labels = [int(r["stored_label"]) for r in aligned_rows if r["stored_label"] in (0, 1)]
    prod_labels = [int(r["production_label"]) for r in aligned_rows if r["production_label"] in (0, 1)]
    changed = sum(1 for r in aligned_rows if r["label_changed"])

    quality = LabelQualityValidator().validate(df)
    root_causes: list[str] = []
    if _pct(stored_vs_stored_sl_tp, "match") < 95:
        root_causes.append("V7_INTERNAL_LABEL_INCONSISTENCY")
    if avg_sl_delta > 5 or avg_tp_delta > 5:
        root_causes.append("SL_TP_FORMULA_MISMATCH")
    if abs(avg_rr_stored - avg_rr_prod) > 0.3:
        root_causes.append("RR_RATIO_MISMATCH")
    if _pct(stored_vs_production, "match") < 70:
        root_causes.append("PRODUCTION_LABEL_DIVERGENCE")

    match_stored = _pct(stored_vs_stored_sl_tp, "match")
    match_prod = _pct(stored_vs_production, "match")
    if match_stored >= 98 and match_prod >= 80:
        verdict = "V7_LABELS_HEALTHY"
    elif match_stored >= 95 and match_prod >= 65:
        verdict = "V7_LABELS_PARTIALLY_ALIGNED"
    elif root_causes:
        verdict = "V7_LABELS_MISALIGNED"
    else:
        verdict = "V7_LABELS_NEEDS_REVIEW"

    return {
        "verdict": verdict,
        "sample_size_requested": sample_size,
        "sample_size_resolved": len(aligned_rows),
        "overlap_rows": len(overlap),
        "coverage_pct": round(len(overlap) / max(len(work), 1) * 100, 2),
        "approach": "full_stats_from_parquet; re_resolution_on_stratified_sample_only",
        "stored_vs_stored_sl_tp": {
            **stored_vs_stored_sl_tp,
            "match_pct": match_stored,
            "mismatch_pct": _pct(stored_vs_stored_sl_tp, "mismatch"),
        },
        "stored_vs_production": {
            **stored_vs_production,
            "match_pct": match_prod,
            "mismatch_pct": _pct(stored_vs_production, "mismatch"),
        },
        "sl_tp_parity": {
            "avg_sl_distance_delta_pct": avg_sl_delta,
            "avg_tp_distance_delta_pct": avg_tp_delta,
            "avg_rr_stored": avg_rr_stored,
            "avg_rr_production": avg_rr_prod,
            "samples": len(sl_tp_stats),
        },
        "label_shift": {
            "stored_pf_proxy": _pf_from_labels(stored_labels),
            "production_pf_proxy": _pf_from_labels(prod_labels),
            "labels_would_change": changed,
            "labels_would_change_pct": round(changed / max(len(aligned_rows), 1) * 100, 2),
        },
        "root_causes": root_causes,
        "quality_report": quality.to_dict(),
        "mismatch_examples": mismatch_examples,
        "aligned_sample": aligned_rows[:50],
    }


def run_label_audit_v7(df: pd.DataFrame, candles: pd.DataFrame, *, sample_size: int = 1500) -> dict[str, Any]:
    full = full_dataset_stats(df)
    sample = audit_sample(df, candles, sample_size=sample_size)
    return {"dataset": "v7", "dataset_rows": full["total_rows"], "full_dataset_stats": full, **sample}


def run_phase52(*, sample_size: int | None = None) -> dict:
    from tradingbot.ml.research.phase39.candle_sources import resolve_fullest_candles

    if not V7_PATH.is_file():
        return {"verdict": "INSUFFICIENT_DATA", "error": "run phase49 first — v7 parquet missing"}

    df = pd.read_parquet(V7_PATH)
    candles = resolve_fullest_candles("XAUUSD", "M5")
    if candles is None or candles.empty:
        return {"verdict": "INSUFFICIENT_DATA", "error": "fullest candles unavailable"}

    n = sample_size or int(os.environ.get("PHASE52_SAMPLE_SIZE", "1500"))
    audit = run_label_audit_v7(df, candles, sample_size=n)
    return {
        "now": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase50_context": {"verdict": "STRICT_GATE_FAIL", "mean_pf": 0.9024, "mean_auc": 0.5115},
        "phase51_context": {
            "verdict": "EARLY_RESEARCH",
            "proximity_score": 27.0,
            "integration_gate": "BLOCK_PRODUCTION_INTEGRATION",
        },
        **audit,
    }


def write_all(data: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    for name, payload in {
        "full_dataset_stats.json": data.get("full_dataset_stats", {}),
        "label_audit_v7.json": {k: v for k, v in data.items() if k not in ("full_dataset_stats", "aligned_sample")},
        "aligned_sample_v7.json": data.get("aligned_sample", []),
    }.items():
        (ARTIFACTS / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote phase52/artifacts/{name}", flush=True)

    report = {
        "phase": "52",
        "title": "Label & Dataset Diagnosis (v7)",
        "title_fa": "تشخیص برچسب و دیتاست v7",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "dataset_rows": data.get("dataset_rows"),
        "full_dataset_stats": data.get("full_dataset_stats"),
        "stored_vs_stored_sl_tp_match_pct": (data.get("stored_vs_stored_sl_tp") or {}).get("match_pct"),
        "stored_vs_production_match_pct": (data.get("stored_vs_production") or {}).get("match_pct"),
        "sl_tp_parity": data.get("sl_tp_parity"),
        "label_shift": data.get("label_shift"),
        "root_causes": data.get("root_causes"),
        "sample_approach": data.get("approach"),
        "sample_size_resolved": data.get("sample_size_resolved"),
        "phase50_context": data.get("phase50_context"),
        "phase51_context": data.get("phase51_context"),
        "recommendation": _recommendation(data),
    }
    (ROOT / "phase52_final_report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("  wrote phase52_final_report.json", flush=True)


def _recommendation(data: dict) -> str:
    v = data.get("verdict", "")
    if v == "V7_LABELS_HEALTHY":
        return "Labels OK — proceed to phase53 execution funnel audit; label rebuild not required."
    if v == "V7_LABELS_PARTIALLY_ALIGNED":
        return "Partial alignment — phase54 model sweep may help; consider v8 aligned rebuild after phase56."
    return "Label misalignment likely contributes to gate failure — prioritize v8 aligned dataset in phase57."


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description="Phase 52 — v7 label audit")
    p.add_argument("--sample-size", type=int, default=None)
    args = p.parse_args()
    data = run_phase52(sample_size=args.sample_size)
    write_all(data)
    print(json.dumps({
        "verdict": data["verdict"],
        "rows": data.get("dataset_rows"),
        "stored_match": (data.get("stored_vs_stored_sl_tp") or {}).get("match_pct"),
        "production_match": (data.get("stored_vs_production") or {}).get("match_pct"),
        "pf_proxy_full": (data.get("full_dataset_stats") or {}).get("pf_proxy"),
    }, indent=2))


if __name__ == "__main__":
    main()
