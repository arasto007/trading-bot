#!/usr/bin/env python3
"""PHASE 20B — Meta Shadow Demotion Audit.

Research/shadow only. Does not change live decisions or config.
USE_ML_KERNEL=false. PATCH_APPLIED=NO.
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

SRC = ROOT / "data" / "ml" / "research" / "phase18a" / "labeled_setups_180d.parquet"
SHADOW = ROOT / "logs" / "phase19c" / "meta_shadow_all_setups.jsonl"
RESULT = ROOT / "logs" / "phase20b_meta_shadow_demotion.txt"
DETAIL = ROOT / "logs" / "phase20b" / "mode_metrics.json"
BASE_TH = 0.38


def emit(msg: str = "") -> None:
    print(msg, flush=True)


def max_dd_r(rs: np.ndarray) -> float:
    if rs.size == 0:
        return 0.0
    eq = np.cumsum(rs.astype(float))
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    return float(dd.max()) if dd.size else 0.0


def metrics(rs: np.ndarray) -> dict[str, Any]:
    rs = np.asarray(rs, dtype=float)
    n = int(rs.size)
    if n == 0:
        return {
            "trades": 0,
            "wr": 0.0,
            "pf": 0.0,
            "expr": 0.0,
            "maxdd": 0.0,
            "net_r": 0.0,
            "wins": 0,
            "losses": 0,
            "scratches": 0,
        }
    wins = rs[rs > 0]
    losses = rs[rs < 0]
    gw = float(wins.sum()) if wins.size else 0.0
    gl = float(abs(losses.sum())) if losses.size else 0.0
    if gl > 0:
        pf = gw / gl
    elif gw > 0:
        pf = min(10.0, 1.0 + gw) if n >= 5 else 0.0
    else:
        pf = 0.0
    return {
        "trades": n,
        "wr": round(100.0 * float((rs > 0).mean()), 2),
        "pf": round(min(float(pf), 99.0), 4),
        "expr": round(float(rs.mean()), 4),
        "maxdd": round(max_dd_r(rs), 4),
        "net_r": round(float(rs.sum()), 4),
        "wins": int((rs > 0).sum()),
        "losses": int((rs < 0).sum()),
        "scratches": int((rs == 0).sum()),
    }


def load_shadow(src: pd.DataFrame) -> pd.DataFrame:
    if SHADOW.is_file():
        rows = []
        with SHADOW.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        sh = pd.DataFrame(rows)
        keep = [c for c in ("setup_id", "meta_probability", "threshold_used", "hypothetical_decision") if c in sh.columns]
        out = src.merge(sh[keep], on="setup_id", how="left")
        if int(out["meta_probability"].isna().sum()) == 0:
            emit("joined phase19c shadow scores n=" + str(len(out)))
            return out
        emit("WARN: incomplete 19C join, unmatched=" + str(int(out["meta_probability"].isna().sum())))

    emit("re-scoring with live M5 meta")
    from scripts.phase19c_shadow_meta import build_feature_matrix, map_regime_code
    from tradingbot.services.meta_labeler import reload_meta_labeler

    meta = reload_meta_labeler()
    model = meta._models.get("M5")
    if model is None:
        raise RuntimeError("meta_labeler_m5.pkl not loaded")
    X = build_feature_matrix(src)
    probs = np.asarray(model.predict_proba(X)[:, 1], dtype=float)
    ths = []
    for rec in src.itertuples(index=False):
        live_reg, _ = map_regime_code(getattr(rec, "regime", "RANGING"), rec.direction)
        ths.append(float(meta.effective_threshold("M5", live_reg, BASE_TH)))
    src = src.copy()
    src["meta_probability"] = probs
    src["threshold_used"] = np.asarray(ths, dtype=float)
    src["hypothetical_decision"] = np.where(src["meta_probability"] >= src["threshold_used"], "accepted", "rejected")
    return src


def fmt_row(name: str, m: dict[str, Any]) -> str:
    return f"{name:<22} {m['trades']:>8} {m['wr']:>7.2f} {m['pf']:>8.4f} {m['expr']:>8.4f} {m['maxdd']:>8.4f}"


def main() -> int:
    emit("PHASE 20B — Meta Shadow Demotion Audit")
    emit("USE_ML_KERNEL=false PATCH_APPLIED=NO")
    src = pd.read_parquet(SRC)
    src["timestamp_utc"] = pd.to_datetime(src["timestamp_utc"], utc=True, format="mixed")
    src = src.sort_values("timestamp_utc").reset_index(drop=True)
    src = load_shadow(src)

    rcol = "realized_r_multiple"
    u_mask = (
        src["reclaim"].astype(bool)
        & src["bos"].astype(bool)
        & (src["quality_score"].astype(float) >= 55)
    )
    u = src.loc[u_mask].copy()
    emit("18A n=" + str(len(src)) + " universe reclaim+bos+q>=55 n=" + str(len(u)))

    # Modes
    pa_raw = metrics(src[rcol].to_numpy())
    pa_no_meta = metrics(u[rcol].to_numpy())  # quality already in U
    meta_fixed = u["meta_probability"].astype(float) >= BASE_TH
    pa_meta = metrics(u.loc[meta_fixed, rcol].to_numpy())
    pa_quality = pa_no_meta  # 18A quality_score min=68; quality gate is a no-op

    meta_eff = u["meta_probability"].astype(float) >= u["threshold_used"].astype(float)
    pa_meta_eff = metrics(u.loc[meta_eff, rcol].to_numpy())

    rec_only = src.loc[src["reclaim"].astype(bool), rcol].to_numpy()
    bos_only = src.loc[src["bos"].astype(bool), rcol].to_numpy()
    rec_bos = src.loc[src["reclaim"].astype(bool) & src["bos"].astype(bool), rcol].to_numpy()
    q80 = src.loc[src["quality_score"].astype(float) >= 80, rcol].to_numpy()
    rq55 = src.loc[src["research_quality_score"].astype(float) >= 55, rcol].to_numpy()

    # Edge test: meta vs taking all U
    adds_edge = bool(
        pa_meta["trades"] >= 10
        and pa_meta["pf"] > pa_no_meta["pf"]
        and pa_meta["expr"] > pa_no_meta["expr"]
    )
    # Observer is safe if gating does not improve PF/ExpR (meta is not helping)
    observer_ok = (not adds_edge) and pa_no_meta["trades"] >= 20

    modes = {
        "PA_RAW": pa_raw,
        "PA_META_0_38": pa_meta,
        "PA_NO_META": pa_no_meta,
        "PA_NO_META_QUALITY": pa_quality,
        "PA_META_EFFECTIVE_TH": pa_meta_eff,
        "PA_RECLAIM_ONLY": metrics(rec_only),
        "PA_BOS_ONLY": metrics(bos_only),
        "PA_RECLAIM_AND_BOS": metrics(rec_bos),
        "PA_QUALITY_GE_80": metrics(q80),
        "PA_RESEARCH_Q_GE_55": metrics(rq55),
    }

    killed = int((~meta_fixed).sum()) if len(u) else 0
    killed_winners = int(((~meta_fixed) & (u[rcol].astype(float) > 0)).sum()) if len(u) else 0
    kept_losers = int((meta_fixed & (u[rcol].astype(float) < 0)).sum()) if len(u) else 0

    DETAIL.parent.mkdir(parents=True, exist_ok=True)
    DETAIL.write_text(json.dumps(modes, indent=2), encoding="utf-8")

    lines = [
        "PHASE 20B — Meta Shadow Demotion Audit",
        "MODE=SHADOW_ONLY",
        "USE_ML_KERNEL=false",
        "PATCH_APPLIED=NO",
        "LIVE_DECISIONS_CHANGED=NO",
        "DATASET=data/ml/research/phase18a/labeled_setups_180d.parquet",
        "META_SCORES=logs/phase19c/meta_shadow_all_setups.jsonl",
        "MODEL=models/meta_labeler_m5.pkl",
        "THRESHOLD_FIXED=0.38",
        "",
        "UNIVERSE_FILTER=reclaim=true AND bos=true AND quality_score>=55",
        f"TOTAL_18A={len(src)}",
        f"UNIVERSE_N={len(u)}",
        f"QUALITY_SCORE_MIN_18A={float(src['quality_score'].min()):.0f}  # quality>=55 is a no-op on this dataset",
        f"META_ACCEPT_FIXED_0_38={int(meta_fixed.sum())}",
        f"META_ACCEPT_LIVE_EFFECTIVE={int(meta_eff.sum())}",
        f"META_MEAN_P_UNIVERSE={round(float(u['meta_probability'].mean()), 4) if len(u) else 0.0}",
        "",
        f"{'Mode':<22} {'Trades':>8} {'WR%':>7} {'PF':>8} {'ExpR':>8} {'MaxDD':>8}",
        "-" * 64,
        fmt_row("PA raw", pa_raw),
        fmt_row("PA + Meta 0.38", pa_meta),
        fmt_row("PA no Meta", pa_no_meta),
        fmt_row("PA no Meta + quality", pa_quality),
        "",
        "EXTRA (not in required table)",
        fmt_row("PA + Meta effective", pa_meta_eff),
        fmt_row("PA reclaim only", modes["PA_RECLAIM_ONLY"]),
        fmt_row("PA bos only", modes["PA_BOS_ONLY"]),
        fmt_row("PA reclaim+bos", modes["PA_RECLAIM_AND_BOS"]),
        fmt_row("PA quality>=80", modes["PA_QUALITY_GE_80"]),
        fmt_row("PA research_q>=55", modes["PA_RESEARCH_Q_GE_55"]),
        "",
        "=== META vs PA FREQUENCY ===",
        f"UNIVERSE_TRADES={pa_no_meta['trades']}",
        f"META_0_38_TRADES={pa_meta['trades']}",
        f"FREQUENCY_CUT_PCT={round(100.0 * (1.0 - pa_meta['trades'] / pa_no_meta['trades']), 2) if pa_no_meta['trades'] else 0.0}",
        f"META_KILLED={killed}",
        f"META_KILLED_WINNERS={killed_winners}",
        f"META_KEPT_LOSERS={kept_losers}",
        f"PA_NO_META_NET_R={pa_no_meta['net_r']}",
        f"PA_META_NET_R={pa_meta['net_r']}",
        "",
        "=== EDGE VERDICT ===",
        "PA raw = all 18A sweep events (includes no-reclaim).",
        "PA no Meta = reclaim+bos+quality>=55, Meta does not gate.",
        "PA + Meta 0.38 = same universe, keep only meta_probability>=0.38.",
        "PA no Meta + quality = same as PA no Meta because 18A quality_score min is 68.",
        "Meta adds edge only if PF and ExpR both beat PA no Meta with >=10 trades.",
        f"META_ADDS_EDGE={'YES' if adds_edge else 'NO'}",
        f"SAFE_TO_KEEP_META_AS_OBSERVER={'YES' if observer_ok else 'NO'}",
        "",
        "PHASE_20B_RESULT",
        f"PA_RAW_PF={pa_raw['pf']}",
        f"PA_META_PF={pa_meta['pf']}",
        f"PA_NO_META_PF={pa_no_meta['pf']}",
        f"QUALITY_ONLY_PF={pa_quality['pf']}",
        f"META_ADDS_EDGE={'YES' if adds_edge else 'NO'}",
        f"SAFE_TO_KEEP_META_AS_OBSERVER={'YES' if observer_ok else 'NO'}",
        "PATCH_APPLIED=NO",
    ]
    text = "\n".join(lines) + "\n"
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(text, encoding="utf-8")
    emit(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())