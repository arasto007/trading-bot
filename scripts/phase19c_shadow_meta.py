#!/usr/bin/env python3
"""PHASE 19C ? Shadow Meta Truth Monitor (research / shadow only).

Scores every raw PA setup with the current M5 meta-labeler.
Does not change live decisions. USE_ML_KERNEL=false.
"""
from __future__ import annotations

import json
import os
import sys
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_SIGNAL_FILTER": "OFF",
    "TRADINGBOT_DRY_RUN": "1",
})
warnings.filterwarnings("ignore")

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.domain.trade_features import REGIME_MAP
from tradingbot.ml.features.unified_feature_store import FEATURES, to_vector
from tradingbot.research.regime_ensemble import trade_metrics
from tradingbot.services.meta_labeler import reload_meta_labeler

SRC = ROOT / "data" / "ml" / "research" / "phase18a" / "labeled_setups_180d.parquet"
OUT = ROOT / "logs" / "phase19c"
JSONL = OUT / "meta_shadow_all_setups.jsonl"
CURVE_JSON = OUT / "threshold_curve.json"
OPP_JSON = OUT / "opportunity_cost.json"
RESULT = OUT / "phase19c_result.txt"

BASE_TH = 0.38
THRESHOLDS = (0.30, 0.34, 0.36, 0.38, 0.40, 0.42)
BIG_WIN = 1.0
BIG_LOSS = -1.0
SPREAD_PIPS = 4.0
CONFLUENCE_DEFAULT = 3.2


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def map_regime_code(regime: str, direction: str) -> tuple[str, float]:
    r = str(regime or "RANGING").upper()
    if r == "TREND":
        live = "STRONG_TREND_UP" if str(direction).upper() == "BUY" else "STRONG_TREND_DOWN"
        return live, float(REGIME_MAP.get(live, 1.0))
    if r == "EXPANSION":
        return "VOLATILE", float(REGIME_MAP.get("VOLATILE", 0.5))
    if r == "RANGING":
        return "RANGING", float(REGIME_MAP.get("RANGING", 0.0))
    return r, float(REGIME_MAP.get(r, 0.0))


def build_feature_matrix(df: pd.DataFrame) -> np.ndarray:
    rows = []
    for rec in df.itertuples(index=False):
        ts = pd.Timestamp(rec.timestamp_utc, tz="UTC")
        live_reg, reg_code = map_regime_code(getattr(rec, "regime", "RANGING"), rec.direction)
        _ = live_reg
        entry = float(rec.entry_price)
        sl = float(rec.stop_price)
        atr = float(getattr(rec, "atr", 0.0) or 0.0)
        sl_atr = abs(entry - sl) / atr if atr > 0 else 0.0
        feats = {
            "confidence": float(getattr(rec, "confidence", 0.0) or 0.0),
            "confluence": float(getattr(rec, "confluence_score", CONFLUENCE_DEFAULT) or CONFLUENCE_DEFAULT),
            "rr": float(getattr(rec, "rr_target", 0.0) or 0.0),
            "adx": float(getattr(rec, "adx", 0.0) or 0.0),
            "atr_pct": float(getattr(rec, "atr_pct", 50.0) or 50.0),
            "htf_bias": 0.0,
            "hour_utc": float(getattr(rec, "session_hour", ts.hour) or ts.hour),
            "weekday": float(ts.weekday()),
            "direction": 1.0 if str(rec.direction).upper() == "BUY" else -1.0,
            "regime_code": reg_code,
            "spread_pips": float(getattr(rec, "spread_pips", SPREAD_PIPS) or SPREAD_PIPS),
            "sl_atr_mult": round(sl_atr, 4),
            "setup_code": 1.0,
        }
        rows.append(to_vector(feats))
    return np.asarray(rows, dtype=float)


def opportunity(mask_accept: np.ndarray, rs: np.ndarray) -> dict[str, Any]:
    rej = ~mask_accept
    acc = mask_accept
    return {
        "rejected_profitable": int(((rej) & (rs > 0)).sum()),
        "rejected_big_winners": int(((rej) & (rs >= BIG_WIN)).sum()),
        "accepted_losers": int(((acc) & (rs < 0)).sum()),
        "accepted_big_losers": int(((acc) & (rs <= BIG_LOSS)).sum()),
        "opportunity_cost_R": round(float(rs[rej & (rs > 0)].sum()) if (rej & (rs > 0)).any() else 0.0, 4),
        "avoided_loss_R": round(float(abs(rs[rej & (rs < 0)].sum())) if (rej & (rs < 0)).any() else 0.0, 4),
        "accepted_net_R": round(float(rs[acc].sum()) if acc.any() else 0.0, 4),
    }


def curve_row(th: float, probs: np.ndarray, rs: np.ndarray) -> dict[str, Any]:
    acc = probs >= th
    taken = [float(r) for r, a in zip(rs, acc) if a]
    tm = trade_metrics(taken)
    opp = opportunity(acc, rs)
    return {
        "threshold": th,
        "trades": tm["trades"],
        "pf": tm["oos_pf"],
        "expectancy_r": tm["oos_expectancy_r"],
        "opportunity_cost_R": opp["opportunity_cost_R"],
        "rejected_profitable": opp["rejected_profitable"],
        "rejected_big_winners": opp["rejected_big_winners"],
        "accepted_losers": opp["accepted_losers"],
        "accepted_big_losers": opp["accepted_big_losers"],
        "accepted_net_R": opp["accepted_net_R"],
        "avoided_loss_R": opp["avoided_loss_R"],
    }


def pick_best(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = []
    for r in rows:
        ranked.append((
            1 if r["trades"] >= 20 else 0,
            float(r["pf"]),
            float(r["expectancy_r"]),
            -float(r["opportunity_cost_R"]),
            r,
        ))
    ranked.sort(reverse=True)
    return ranked[0][-1]


def main() -> int:
    emit("PHASE 19C ? shadow meta truth monitor")
    emit("USE_ML_KERNEL=false PATCH_APPLIED=NO")
    src = pd.read_parquet(SRC)
    emit(f"raw setups n={len(src)}")

    meta = reload_meta_labeler()
    if not meta.is_ready_for("M5"):
        emit("WARN: M5 meta not ready; scoring may return pass-through")
    model = meta._models.get("M5")
    if model is None:
        raise RuntimeError("meta_labeler_m5.pkl not loaded")

    X = build_feature_matrix(src)
    probs = np.asarray(model.predict_proba(X)[:, 1], dtype=float)
    rs = src["realized_r_multiple"].astype(float).to_numpy()
    emit(f"scored mean_p={probs.mean():.4f} p50={np.median(probs):.4f}")

    live_th = []
    live_regimes = []
    for rec in src.itertuples(index=False):
        live_reg, _ = map_regime_code(getattr(rec, "regime", "RANGING"), rec.direction)
        live_regimes.append(live_reg)
        live_th.append(float(meta.effective_threshold("M5", live_reg, BASE_TH)))
    live_th_a = np.asarray(live_th, dtype=float)
    accept_live = probs >= live_th_a

    OUT.mkdir(parents=True, exist_ok=True)
    with JSONL.open("w", encoding="utf-8") as fh:
        for i, rec in enumerate(src.itertuples(index=False)):
            p = float(probs[i])
            th = float(live_th_a[i])
            r = float(rs[i])
            hyp = "accepted" if p >= th else "rejected"
            fh.write(
                json.dumps(
                    {
                        "setup_id": rec.setup_id,
                        "timestamp_utc": str(rec.timestamp_utc),
                        "direction": rec.direction,
                        "regime": getattr(rec, "regime", None),
                        "live_regime_mapped": live_regimes[i],
                        "meta_probability": round(p, 6),
                        "threshold_used": round(th, 4),
                        "hypothetical_decision": hyp,
                        "final_r": round(r, 4),
                        "label_18a": int(rec.label),
                        "reclaim": bool(getattr(rec, "reclaim", False)),
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )

    opp_live = opportunity(accept_live, rs)
    taken_live = [float(r) for r, a in zip(rs, accept_live) if a]
    live_tm = trade_metrics(taken_live)

    curve = [curve_row(th, probs, rs) for th in THRESHOLDS]
    best = pick_best(curve)
    row38 = next(r for r in curve if abs(r["threshold"] - 0.38) < 1e-9)
    row36 = next(r for r in curve if abs(r["threshold"] - 0.36) < 1e-9)

    lower = [r for r in curve if r["threshold"] < 0.38]
    better_lower = any(
        r["trades"] > row38["trades"]
        and r["pf"] >= (row38["pf"] * 0.95 if row38["pf"] > 0 else 0.0)
        and r["expectancy_r"] >= (row38["expectancy_r"] - 0.05)
        for r in lower
    )
    too_strict = bool(
        opp_live["rejected_profitable"] >= 20
        and (
            better_lower
            or row38["trades"] < 20
            or (row36["trades"] > row38["trades"] and row36["pf"] >= row38["pf"])
        )
    )

    CURVE_JSON.write_text(json.dumps({"rows": curve, "best": best}, indent=2), encoding="utf-8")
    OPP_JSON.write_text(
        json.dumps({"live_threshold_effective": opp_live, "live_metrics": live_tm}, indent=2),
        encoding="utf-8",
    )

    n = len(src)
    acc_n = int(accept_live.sum())
    rej_n = n - acc_n
    rec_th = float(best["threshold"])

    lines = [
        "PHASE_19C_RESULT",
        "",
        f"TOTAL_RAW_SETUPS={n}",
        f"ACCEPTED={acc_n}",
        f"REJECTED={rej_n}",
        "",
        f"REJECTED_PROFITABLE={opp_live['rejected_profitable']}",
        f"REJECTED_BIG_WINNERS={opp_live['rejected_big_winners']}",
        f"ACCEPTED_LOSERS={opp_live['accepted_losers']}",
        "",
        f"BEST_THRESHOLD={rec_th:.2f}",
        f"BEST_THRESHOLD_PF={best['pf']}",
        f"BEST_THRESHOLD_EXPECTANCY_R={best['expectancy_r']}",
        f"BEST_THRESHOLD_OPPORTUNITY_COST_R={best['opportunity_cost_R']}",
        "",
        f"IS_0_38_TOO_STRICT={'YES' if too_strict else 'NO'}",
        f"RECOMMENDED_OPERATIONAL_THRESHOLD={rec_th:.2f}",
        "PATCH_APPLIED=NO",
        "",
        f"LIVE_EFFECTIVE_PF={live_tm['oos_pf']}",
        f"LIVE_EFFECTIVE_EXPECTANCY_R={live_tm['oos_expectancy_r']}",
        f"LIVE_ACCEPTED_BIG_LOSERS={opp_live['accepted_big_losers']}",
        f"MEAN_META_PROB={round(float(probs.mean()), 4)}",
        "THRESHOLD_CURVE=",
    ]
    for r in curve:
        lines.append(
            f"  th={r['threshold']:.2f} trades={r['trades']} PF={r['pf']} "
            f"ExpR={r['expectancy_r']} oppR={r['opportunity_cost_R']} "
            f"rej_profit={r['rejected_profitable']} acc_losers={r['accepted_losers']}"
        )
    lines += [
        "",
        "USE_ML_KERNEL=false",
        "MODE=SHADOW_MONITOR_ONLY",
        "LIVE_DECISIONS_CHANGED=NO",
        "MODEL=models/meta_labeler_m5.pkl",
    ]
    text = "\n".join(lines) + "\n"
    RESULT.write_text(text, encoding="utf-8")
    emit(text)
    emit(f"WROTE {JSONL}")
    emit(f"WROTE {RESULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
