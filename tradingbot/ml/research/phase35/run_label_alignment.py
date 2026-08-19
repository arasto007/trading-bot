#!/usr/bin/env python3
"""Phase 35 — Label Alignment & ML Retrain Readiness Audit (read-only)."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
SAMPLE_SIZE = 800


def _load_dataset() -> pd.DataFrame | None:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.paths import normalize_ml_base_dir
    from tradingbot.ml.dataset.store import DatasetStore

    base = normalize_ml_base_dir(load_legacy_config().get("BASE_DIR"))
    store = DatasetStore(base)
    df = store.load_v2("XAUUSD", "M5")
    if df is None or df.empty:
        df = store.load("XAUUSD", "M5")
    return df


def _load_candles() -> pd.DataFrame | None:
    from tradingbot.adapters.legacy_loader import load_legacy_config
    from tradingbot.ml.data.stores.candle_store import CandleStore

    raw = CandleStore(load_legacy_config().get("BASE_DIR")).load("XAUUSD", "M5")
    if raw is None or raw.empty:
        return None
    if not isinstance(raw.index, pd.DatetimeIndex):
        if "timestamp" in raw.columns:
            raw = raw.set_index("timestamp")
    raw.index = pd.to_datetime(raw.index, utc=True)
    return raw.sort_index()


def _pf_from_labels(labels: list[int]) -> float:
    wins = sum(1 for x in labels if x == 1)
    losses = sum(1 for x in labels if x == 0)
    if losses == 0:
        return 2.0 if wins > 0 else 0.0
    return round(wins / losses, 4)


def _bar_index_for_timestamp(candles: pd.DataFrame, ts: pd.Timestamp) -> int:
    """Match dataset builder bar indexing."""
    if ts in candles.index:
        return int(candles.index.get_loc(ts))
    return int(candles.index.searchsorted(ts, side="right") - 1)


def run_audit() -> dict:
    from tradingbot.ml.dataset.label_quality import LabelQualityValidator
    from tradingbot.ml.dataset.labels import label_from_future_candles
    from tradingbot.ml.dataset.schema import Label
    from tradingbot.ml.research.phase35.label_alignment import (
        production_sl_tp_at_bar,
        resolve_label_with_sl_tp,
        sl_tp_distance_metrics,
    )
    from tradingbot.ml.research.phase33d.replay import replay_with_production_sl_tp

    df = _load_dataset()
    candles = _load_candles()
    if df is None or df.empty or candles is None:
        return {"verdict": "INSUFFICIENT_DATA", "error": "dataset or candles missing"}

    work = df.copy()
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    candle_min, candle_max = candles.index.min(), candles.index.max()
    overlap_mask = (work["timestamp"] >= candle_min) & (work["timestamp"] <= candle_max)
    overlap_df = work.loc[overlap_mask]
    coverage_pct = round(len(overlap_df) / max(len(work), 1) * 100, 2)

    sample = overlap_df.sample(n=min(SAMPLE_SIZE, len(overlap_df)), random_state=42) if len(overlap_df) > 0 else work.head(0)

    stored_vs_resolved = {"match": 0, "mismatch": 0, "no_resolution": 0, "checked": 0}
    stored_vs_production = {"match": 0, "mismatch": 0, "no_resolution": 0, "checked": 0}
    builder_vs_production = {"match": 0, "mismatch": 0, "checked": 0}
    sl_tp_stats: list[dict] = []
    mismatch_examples: list[dict] = []
    aligned_rows: list[dict] = []

    for _, row in sample.iterrows():
        ts = row["timestamp"]
        idx = _bar_index_for_timestamp(candles, ts)
        if idx < 0 or idx >= len(candles) - 5:
            continue
        direction = int(row["direction"])
        entry = float(row["entry_price"])
        stored_label = int(row["label"])
        sl_stored = float(row["stop_loss"])
        tp_stored = float(row["take_profit"])
        fw = int(row.get("future_window_bars", 72))

        resolved = resolve_label_with_sl_tp(
            candles, idx, direction, sl_stored, tp_stored,
            future_window_bars=fw, entry_price=entry,
        )
        stored_vs_resolved["checked"] += 1
        r_label = int(resolved["label"])
        if r_label == int(Label.NO_RESOLUTION):
            stored_vs_resolved["no_resolution"] += 1
        elif r_label == stored_label:
            stored_vs_resolved["match"] += 1
        else:
            stored_vs_resolved["mismatch"] += 1

        sl_prod, tp_prod = production_sl_tp_at_bar(candles, idx, direction)
        if sl_prod > 0 and tp_prod > 0:
            prod_resolved = resolve_label_with_sl_tp(
                candles, idx, direction, sl_prod, tp_prod,
                future_window_bars=fw, entry_price=entry,
            )
            stored_vs_production["checked"] += 1
            p_label = int(prod_resolved["label"])
            if p_label == int(Label.NO_RESOLUTION):
                stored_vs_production["no_resolution"] += 1
            elif p_label == stored_label:
                stored_vs_production["match"] += 1
            else:
                stored_vs_production["mismatch"] += 1
                if len(mismatch_examples) < 10:
                    replay = replay_with_production_sl_tp(
                        candles, idx,
                        direction="BUY" if direction > 0 else "SELL",
                        confidence=0.55,
                    )
                    mismatch_examples.append({
                        "timestamp": str(ts),
                        "stored_label": stored_label,
                        "production_label": p_label,
                        "replay_r": replay.get("r_multiple"),
                        "sl_stored": sl_stored,
                        "tp_stored": tp_stored,
                        "sl_production": sl_prod,
                        "tp_production": tp_prod,
                    })

            metrics = sl_tp_distance_metrics(entry, direction, sl_stored, tp_stored, sl_prod, tp_prod)
            if sl_stored > 0 and sl_prod > 0 and entry > 0:
                sl_tp_stats.append(metrics)

            rebuilt = label_from_future_candles(candles, idx, direction, future_window_bars=fw, entry_price=entry)
            builder_vs_production["checked"] += 1
            if int(rebuilt.label) == p_label:
                builder_vs_production["match"] += 1
            else:
                builder_vs_production["mismatch"] += 1

            aligned_rows.append({
                "timestamp": str(ts),
                "direction": direction,
                "stored_label": stored_label,
                "production_label": p_label,
                "aligned_label": p_label,
                "label_changed": stored_label != p_label,
                **metrics,
            })

    def _pct(d: dict, key: str) -> float:
        c = d.get("checked", 0)
        return round(d.get(key, 0) / max(c, 1) * 100, 2)

    avg_sl_delta = round(sum(s["sl_dist_delta_pct"] for s in sl_tp_stats) / max(len(sl_tp_stats), 1), 2)
    avg_tp_delta = round(sum(s["tp_dist_delta_pct"] for s in sl_tp_stats) / max(len(sl_tp_stats), 1), 2)
    avg_rr_dataset = round(sum(s["rr_dataset"] for s in sl_tp_stats) / max(len(sl_tp_stats), 1), 4)
    avg_rr_production = round(sum(s["rr_production"] for s in sl_tp_stats) / max(len(sl_tp_stats), 1), 4)

    stored_labels = [int(x) for x in sample["label"] if int(x) in (0, 1)]
    prod_labels = [r["production_label"] for r in aligned_rows if r["production_label"] in (0, 1)]
    changed = sum(1 for r in aligned_rows if r["label_changed"])

    quality = LabelQualityValidator().validate(df)

    root_causes = []
    if _pct(stored_vs_resolved, "match") < 95:
        root_causes.append("DATASET_INTERNAL_INCONSISTENCY")
    if avg_sl_delta > 5 or avg_tp_delta > 5:
        root_causes.append("SL_TP_FORMULA_MISMATCH")
    if abs(avg_rr_dataset - avg_rr_production) > 0.3:
        root_causes.append("RR_RATIO_MISMATCH")
    if _pct(stored_vs_production, "match") < 60:
        root_causes.append("PRODUCTION_LABEL_DIVERGENCE")

    if coverage_pct < 50:
        root_causes.insert(0, "CANDLE_HISTORY_TRUNCATION")

    if _pct(stored_vs_resolved, "match") >= 98 and _pct(stored_vs_production, "match") >= 75:
        verdict = "LABELS_ALIGNABLE"
    elif _pct(stored_vs_production, "match") >= 55:
        verdict = "LABELS_PARTIALLY_ALIGNABLE"
    elif root_causes:
        verdict = "LABELS_MISALIGNED"
    else:
        verdict = "LABELS_NEEDS_REVIEW"

    retrain_ready = (
        verdict in ("LABELS_ALIGNABLE", "LABELS_PARTIALLY_ALIGNABLE")
        and _pct(stored_vs_resolved, "match") >= 95
    )

    return {
        "now": NOW,
        "verdict": verdict,
        "dataset_rows": len(df),
        "candle_coverage": {
            "candle_range": [str(candle_min), str(candle_max)],
            "dataset_rows_in_range": len(overlap_df),
            "coverage_pct": coverage_pct,
        },
        "sample_size": len(sample),
        "stored_vs_resolved": {
            **stored_vs_resolved,
            "match_pct": _pct(stored_vs_resolved, "match"),
            "mismatch_pct": _pct(stored_vs_resolved, "mismatch"),
        },
        "stored_vs_production": {
            **stored_vs_production,
            "match_pct": _pct(stored_vs_production, "match"),
            "mismatch_pct": _pct(stored_vs_production, "mismatch"),
        },
        "builder_vs_production": {
            **builder_vs_production,
            "match_pct": _pct(builder_vs_production, "match"),
        },
        "sl_tp_parity": {
            "avg_sl_distance_delta_pct": avg_sl_delta,
            "avg_tp_distance_delta_pct": avg_tp_delta,
            "avg_rr_dataset": avg_rr_dataset,
            "avg_rr_production": avg_rr_production,
            "samples": len(sl_tp_stats),
        },
        "root_causes": root_causes,
        "label_distribution": {
            "stored_pf_proxy": _pf_from_labels(stored_labels),
            "production_pf_proxy": _pf_from_labels(prod_labels),
            "labels_would_change": changed,
            "labels_would_change_pct": round(changed / max(len(aligned_rows), 1) * 100, 2),
        },
        "quality_report": quality.to_dict(),
        "mismatch_examples": mismatch_examples,
        "aligned_sample": aligned_rows[:50],
        "retrain_readiness": {
            "ready": retrain_ready,
            "blockers": [] if retrain_ready else root_causes or ["alignment_insufficient"],
            "recommendation": "BUILD_ALIGNED_DATASET_V3_IN_RESEARCH" if retrain_ready else "FIX_LABEL_SLTP_FIRST",
        },
        "phase34_crosscheck": {
            "phase34b_match_pct": 48.0,
            "phase35_stored_resolve_pct": _pct(stored_vs_resolved, "match"),
            "note": "34B used dataset-A candles; 35 uses full CandleStore",
        },
    }


def write_all(data: dict) -> None:
    def w(name: str, payload: dict) -> None:
        (ROOT / name).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"  wrote {name}", flush=True)

    w("label_alignment_report.json", {"timestamp_utc": data["now"], **{k: data[k] for k in data if k != "aligned_sample"}})
    w("sl_tp_parity.json", {"timestamp_utc": data["now"], "parity": data["sl_tp_parity"], "root_causes": data["root_causes"]})
    w("label_resolution_parity.json", {
        "timestamp_utc": data["now"],
        "stored_vs_resolved": data["stored_vs_resolved"],
        "stored_vs_production": data["stored_vs_production"],
        "builder_vs_production": data["builder_vs_production"],
    })
    w("aligned_label_proposal.json", {
        "timestamp_utc": data["now"],
        "labels_would_change_pct": data["label_distribution"]["labels_would_change_pct"],
        "production_pf_proxy": data["label_distribution"]["production_pf_proxy"],
        "sample": data.get("aligned_sample", []),
    })
    w("ml_retrain_readiness.json", {"timestamp_utc": data["now"], **data["retrain_readiness"]})
    w("phase35_final_report.json", {
        "phase": "35",
        "title": "Label Alignment & Retrain Readiness Audit",
        "timestamp_utc": data["now"],
        "verdict": data["verdict"],
        "root_causes": data["root_causes"],
        "stored_vs_resolved_match_pct": data["stored_vs_resolved"]["match_pct"],
        "stored_vs_production_match_pct": data["stored_vs_production"]["match_pct"],
        "sl_tp_parity": data["sl_tp_parity"],
        "label_distribution": data["label_distribution"],
        "retrain_readiness": data["retrain_readiness"],
        "candle_coverage": data.get("candle_coverage"),
        "phase34_crosscheck": data["phase34_crosscheck"],
        "deliverables": [
            "label_alignment_report.json", "sl_tp_parity.json", "label_resolution_parity.json",
            "aligned_label_proposal.json", "ml_retrain_readiness.json", "phase35_final_report.json",
        ],
    })

    out_dir = ROOT / "tradingbot" / "ml" / "research" / "phase35" / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "aligned_sample.json").write_text(
        json.dumps(data.get("aligned_sample", []), indent=2, default=str), encoding="utf-8"
    )


def main() -> None:
    data = run_audit()
    write_all(data)
    print(json.dumps({
        "verdict": data["verdict"],
        "stored_resolve": data["stored_vs_resolved"]["match_pct"],
        "stored_production": data["stored_vs_production"]["match_pct"],
        "retrain_ready": data["retrain_readiness"]["ready"],
    }, indent=2))


if __name__ == "__main__":
    main()
