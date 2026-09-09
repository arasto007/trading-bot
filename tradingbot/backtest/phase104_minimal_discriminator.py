"""Phase 104 — predeclared minimal discriminator families.

Families are declared only from TRAIN+VAL confirmed evidence in Phases 98–103.
They are research counterfactuals, not exit rules. No combinations invented to chase expectancy.
"""

from __future__ import annotations

import json
import random
from datetime import timedelta
from pathlib import Path
from typing import Any

from tradingbot.backtest.operator_evidence import _safe_load_json
from tradingbot.backtest.phase61_edge_survival_forensics import (
    FROZEN,
    PHASE40_BOOTSTRAP_SEED,
    PHASE40_JSON,
    _git_head,
    _mean,
    _parse_ts,
    _utc_now,
    pack_stats,
)
from tradingbot.backtest.phase68_exit_forensics import TAPE_END_FALLBACK
from tradingbot.backtest.phase70_exit_counterfactuals import N_BOOT
from tradingbot.backtest.phase74_profit_giveback_forensics import PHASE74_JSON, _f
from tradingbot.backtest.phase75_exit_counterfactuals import classify_status
from tradingbot.backtest.phase98_first_favorable_state import CD, EF, PHASE98_JSON, _rate, confirmed_sep
from tradingbot.backtest.phase99_path_velocity_persistence import PHASE99_JSON, persist_kind
from tradingbot.backtest.phase100_retrace_expansion_forensics import PHASE100_JSON
from tradingbot.backtest.phase101_entry_vs_exit import PHASE101_JSON
from tradingbot.backtest.phase102_cluster_timing_forensics import PHASE102_JSON
from tradingbot.backtest.phase103_structure_at_retracement import PHASE103_JSON

PHASE = "104"
PHASE104_JSON = "logs/phase104_minimal_discriminator.json"
PHASE104_MD = "docs/PHASE104_MINIMAL_DISCRIMINATOR.md"
BLOCKED = "BLOCKED"
MAX_FAMILIES = 4
REQUIRED_ARTIFACT_KEYS = (
    "phase",
    "timestamp_utc",
    "n_families",
    "final_gate",
    "production_safety",
    "artifacts",
)


def _boot_diff(cd_flags: list[bool], ef_flags: list[bool], seed: int = PHASE40_BOOTSTRAP_SEED) -> dict[str, Any]:
    if len(cd_flags) < 2 or len(ef_flags) < 2:
        return {"n_cd": len(cd_flags), "n_ef": len(ef_flags), "mean": None, "ci95": [None, None], "small_n": True}
    rng = random.Random(seed)
    diffs = []
    for _ in range(N_BOOT):
        cd_s = [cd_flags[rng.randrange(len(cd_flags))] for _ in cd_flags]
        ef_s = [ef_flags[rng.randrange(len(ef_flags))] for _ in ef_flags]
        diffs.append((sum(cd_s) / len(cd_s)) - (sum(ef_s) / len(ef_s)))
    diffs.sort()
    lo = diffs[int(0.025 * N_BOOT)]
    hi = diffs[min(N_BOOT - 1, int(0.975 * N_BOOT))]
    return {
        "n_cd": len(cd_flags),
        "n_ef": len(ef_flags),
        "mean": _mean(diffs),
        "ci95": [lo, hi],
        "small_n": False,
        "seed": seed,
        "n_boot": N_BOOT,
        "kind": "DERIVED_BOOTSTRAP",
    }


def _recent(ts: Any, cut) -> bool:
    t = _parse_ts(ts)
    return bool(t is not None and t >= cut)


def fires_persistence(r: dict[str, Any]) -> bool:
    s = (r.get("states") or {}).get("0.5") or {}
    return persist_kind(s) == "FAST_SPIKE" if s else False


def fires_structure(r: dict[str, Any], feat: str) -> bool:
    ret = (r.get("anatomy") or {}).get("retrace") or {}
    if not ret:
        return False
    mapping = {
        "wick_reject": "wick_reject",
        "close_against": "close_against",
        "range_expand": "range_expand",
        "failed_new_extreme": "failed_new_extreme",
        "cons_adv_ge_2": None,
        "fast_to_half": None,
    }
    if feat == "cons_adv_ge_2":
        return int(ret.get("cons_adv_close") or 0) >= 2
    if feat == "fast_to_half":
        s = (r.get("states") or {}).get("0.5") or {}
        return bool(s.get("fast"))
    key = mapping.get(feat, feat)
    if key in ret:
        return bool(ret.get(key))
    s05 = (r.get("states") or {}).get("0.5") or {}
    return bool(s05.get(feat))


def fires_state(r: dict[str, Any], level: str, feat: str) -> bool:
    s = (r.get("states") or {}).get(str(level)) or {}
    return bool(s.get(feat)) if s else False


def declare_families(p98: dict, p99: dict, p100: dict, p101: dict, p102: dict, p103: dict) -> list[dict[str, Any]]:
    """Declare at most four families from prior TRAIN+VAL evidence. No extra combos."""
    fams: list[dict[str, Any]] = []
    sep98 = p98.get("separators_train_val") or []
    sep99 = p99.get("separators_train_val") or []
    sep100 = p100.get("separators_train_val") or []
    sep101 = p101.get("separators_train_val") or []
    sep102 = p102.get("separators_train_val") or []
    sep103 = p103.get("separators_train_val") or []
    persist_ok = bool(sep99) or (p99.get("PERSISTENCE_DISCRIMINATOR") == "CANDIDATE_PERSISTENCE")
    struct_ok = bool(sep100 or sep103)
    state_ok = bool(sep98)
    # A persistence
    if persist_ok and len(fams) < MAX_FAMILIES:
        feat99 = (sep99[0].get("feature") if sep99 and isinstance(sep99[0], dict) else None) or "is_fast_spike"
        fams.append(
            {
                "name": "A_PERSISTENCE_STATE",
                "family": "persistence-based state",
                "source_phase": "99",
                "feature": feat99,
                "kind": "PERSISTENCE",
            }
        )
    # B structural
    if struct_ok and len(fams) < MAX_FAMILIES:
        feat = (sep103[0] if sep103 else None) or (sep100[0] if sep100 else "failed_new_extreme")
        fams.append(
            {
                "name": "B_RETRACE_STRUCTURE",
                "family": "retracement structural confirmation",
                "source_phase": "103" if sep103 else "100",
                "feature": feat,
                "kind": "STRUCTURE",
            }
        )
    # C state+persist only if BOTH independently confirmed
    if state_ok and persist_ok and len(fams) < MAX_FAMILIES:
        s0 = sep98[0] if sep98 else {}
        fams.append(
            {
                "name": "C_FAVORABLE_PLUS_PERSISTENCE",
                "family": "favorable-excursion + persistence state",
                "source_phase": "98+99",
                "feature": {"state": s0, "persist": sep99[:1]},
                "kind": "STATE_AND_PERSIST",
            }
        )
    # D state+structure only if BOTH independently confirmed
    if state_ok and struct_ok and len(fams) < MAX_FAMILIES:
        s0 = sep98[0] if sep98 else {}
        fams.append(
            {
                "name": "D_FAVORABLE_PLUS_STRUCTURE",
                "family": "favorable-excursion + structural confirmation",
                "source_phase": "98+103",
                "feature": {"state": s0, "struct": (sep103[:1] or sep100[:1])},
                "kind": "STATE_AND_STRUCTURE",
            }
        )
    # Entry/cluster are not exit discriminators; do not promote them into families
    # even if 101/102 confirmed — that would mix signal timing into an exit spec.
    _ = (sep101, sep102)
    return fams[:MAX_FAMILIES]


def flag_event(r: dict[str, Any], fam: dict[str, Any]) -> bool:
    kind = fam.get("kind")
    feat = fam.get("feature")
    if kind == "PERSISTENCE":
        if feat == "is_sustained":
            s = (r.get("states") or {}).get("0.5") or {}
            return persist_kind(s) == "SUSTAINED_FAVORABLE" if s else False
        if feat == "is_mixed":
            s = (r.get("states") or {}).get("0.5") or {}
            return persist_kind(s) == "MIXED" if s else False
        return fires_persistence(r)
    if kind == "STRUCTURE":
        return fires_structure(r, str(feat))
    if kind == "STATE_AND_PERSIST":
        st = (feat or {}).get("state") or {}
        lv = str(st.get("level") if isinstance(st, dict) else "0.5")
        f = st.get("feature") if isinstance(st, dict) else "fast"
        return fires_state(r, lv, str(f)) and fires_persistence(r)
    if kind == "STATE_AND_STRUCTURE":
        st = (feat or {}).get("state") or {}
        lv = str(st.get("level") if isinstance(st, dict) else "0.5")
        f = st.get("feature") if isinstance(st, dict) else "fast"
        struct_f = ((feat or {}).get("struct") or ["failed_new_extreme"])[0]
        return fires_state(r, lv, str(f)) and fires_structure(r, str(struct_f))
    return False


def cf_r(r: dict[str, Any], flagged: bool, fam: dict[str, Any]) -> float | None:
    orig = _f(r.get("orig"))
    if orig is None:
        return None
    if not flagged:
        return orig
    if fam.get("kind") in {"STRUCTURE", "STATE_AND_STRUCTURE"}:
        close_r = ((r.get("anatomy") or {}).get("retrace") or {}).get("close_R")
        return float(close_r) if close_r is not None else orig
    s = (r.get("states") or {}).get("0.5") or {}
    close_r = s.get("close_R")
    return float(close_r) if close_r is not None else orig


def eval_family(fam: dict[str, Any], compact: list[dict[str, Any]], cut) -> dict[str, Any]:
    flags = []
    for r in compact:
        flagged = flag_event(r, fam)
        flags.append(
            {
                **{k: r.get(k) for k in ("ts", "path_class", "fold", "side", "reg", "year", "orig", "n_sig")},
                "flagged": flagged,
                "cf": cf_r(r, flagged, fam),
                "recent180": _recent(r.get("ts"), cut),
            }
        )
    cd = [x for x in flags if x.get("path_class") in CD]
    ef = [x for x in flags if x.get("path_class") in EF]
    ranked = sorted(flags, key=lambda x: float(x.get("orig") or 0), reverse=True)
    top1 = ranked[0] if ranked else {}
    top5_ts = {x.get("ts") for x in ranked[:5]}
    f_row = next((x for x in flags if x.get("path_class") == "F"), None)

    def pack_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
        cds = [x for x in rows if x.get("path_class") in CD]
        efs = [x for x in rows if x.get("path_class") in EF]
        orig = [_f(x.get("orig")) for x in rows]
        cfs = [_f(x.get("cf")) for x in rows]
        pairs = [(a, b) for a, b in zip(orig, cfs) if a is not None and b is not None]
        ox = [a for a, _ in pairs]
        cx = [b for _, b in pairs]
        return {
            "n": len(rows),
            "CD_flag_rate": _rate(cds, "flagged"),
            "EF_flag_rate": _rate(efs, "flagged"),
            "orig": pack_stats(ox),
            "cf": pack_stats(cx),
            "delta_expectancy": None if not pairs else _mean(cx) - _mean(ox),
        }

    full = pack_split(flags)
    train = pack_split([x for x in flags if x.get("fold") == "TRAIN"])
    val = pack_split([x for x in flags if x.get("fold") == "VALIDATION"])
    oos = pack_split([x for x in flags if x.get("fold") == "OOS"])
    rec = pack_split([x for x in flags if x.get("recent180")])
    buy = pack_split([x for x in flags if str(x.get("side") or "").upper() in {"BUY", "1", "LONG"}])
    sell = pack_split([x for x in flags if str(x.get("side") or "").upper() in {"SELL", "-1", "SHORT"}])
    status = classify_status(
        (train.get("orig") or {}).get("expectancy_R"),
        (train.get("cf") or {}).get("expectancy_R"),
        (val.get("orig") or {}).get("expectancy_R"),
        (val.get("cf") or {}).get("expectancy_R"),
    )
    tail_flagged = bool(f_row and f_row.get("flagged"))
    tail_cf = None if f_row is None else f_row.get("cf")
    tail_orig = None if f_row is None else f_row.get("orig")
    if f_row is None:
        tail = "UNKNOWN"
    elif not tail_flagged:
        tail = "PRESERVED"
    elif tail_cf is not None and float(tail_cf) >= 10:
        tail = "PARTIALLY_PRESERVED"
    else:
        tail = "DESTROYED"
    without_top1 = pack_split([x for x in flags if x.get("ts") != top1.get("ts")])
    without_top5 = pack_split([x for x in flags if x.get("ts") not in top5_ts])
    by_year = {}
    years = sorted({str(x.get("year")) for x in flags if x.get("year") is not None})
    for y in years:
        by_year[y] = pack_split([x for x in flags if str(x.get("year")) == y])
    by_reg = {}
    regs = sorted({str(x.get("reg")) for x in flags if x.get("reg")})
    for rg in regs:
        by_reg[rg] = pack_split([x for x in flags if str(x.get("reg")) == rg])
    boot = _boot_diff([bool(x.get("flagged")) for x in cd], [bool(x.get("flagged")) for x in ef])
    oos_ok = confirmed_sep(
        (train.get("CD_flag_rate") or {}).get("rate"),
        (train.get("EF_flag_rate") or {}).get("rate"),
        (oos.get("CD_flag_rate") or {}).get("rate"),
        (oos.get("EF_flag_rate") or {}).get("rate"),
    )
    rec_ok = confirmed_sep(
        (train.get("CD_flag_rate") or {}).get("rate"),
        (train.get("EF_flag_rate") or {}).get("rate"),
        (rec.get("CD_flag_rate") or {}).get("rate"),
        (rec.get("EF_flag_rate") or {}).get("rate"),
    )
    helpful = status == "HELPFUL" and tail != "DESTROYED" and oos_ok
    return {
        "rule": fam,
        "status": status,
        "TAIL_PRESERVATION": tail,
        "tail_flagged": tail_flagged,
        "tail_orig": tail_orig,
        "tail_cf": tail_cf,
        "FULL": full,
        "TRAIN": train,
        "VALIDATION": val,
        "OOS": oos,
        "RECENT_180D": rec,
        "BUY": buy,
        "SELL": sell,
        "by_year": by_year,
        "by_regime": by_reg,
        "WITHOUT_TOP1": without_top1,
        "WITHOUT_TOP5": without_top5,
        "bootstrap_cd_minus_ef": boot,
        "survives_OOS_direction": oos_ok,
        "survives_recent180_direction": rec_ok,
        "HELPFUL_AND_TAIL_SAFE": helpful,
        "kind": "COUNTERFACTUAL",
    }


def run_phase104_collection(root: Path | None = None) -> dict[str, Any]:
    root = Path(root or Path.cwd())
    p40 = _safe_load_json(root / PHASE40_JSON) or {}
    p74 = _safe_load_json(root / PHASE74_JSON) or {}
    p98 = _safe_load_json(root / PHASE98_JSON) or {}
    p99 = _safe_load_json(root / PHASE99_JSON) or {}
    p100 = _safe_load_json(root / PHASE100_JSON) or {}
    p101 = _safe_load_json(root / PHASE101_JSON) or {}
    p102 = _safe_load_json(root / PHASE102_JSON) or {}
    p103 = _safe_load_json(root / PHASE103_JSON) or {}
    families = declare_families(p98, p99, p100, p101, p102, p103)
    tape_end = _parse_ts(p74.get("tape_end")) or TAPE_END_FALLBACK
    cut = tape_end - timedelta(days=180)
    compact = p98.get("compact") or []
    evals = {}
    for fam in families:
        evals[fam["name"]] = eval_family(fam, compact, cut)
    helpful = [k for k, v in evals.items() if v.get("HELPFUL_AND_TAIL_SAFE")]
    payload = {
        "phase": PHASE,
        "timestamp_utc": _utc_now(),
        "schema_version": 1,
        "research_only": True,
        "status": "PASS",
        "parameters_optimized": False,
        "grid_search": False,
        "phase40_scan_rerun": False,
        "mt5_launched": False,
        "env_accessed": False,
        "frozen_tape_fingerprint": p40.get("tape_fingerprint") or FROZEN,
        "families_declared_from_prior_evidence": True,
        "combinations_invented": False,
        "n_families": len(families),
        "max_families": MAX_FAMILIES,
        "rules": {f["name"]: f for f in families},
        "counterfactuals": evals,
        "helpful_families": helpful,
        "evidence_prior": {
            "98": p98.get("DISCRIMINATOR_AT_FIRST_FAVORABLE"),
            "99": p99.get("PERSISTENCE_DISCRIMINATOR"),
            "100": p100.get("PRE_RETRACE_DISCRIMINATOR"),
            "101": p101.get("ENTRY_DISTINGUISHABLE"),
            "102": p102.get("CLUSTER_EARLY_WARNING"),
            "103": p103.get("STRUCTURAL_DISCRIMINATOR"),
        },
        "evidence_kind": "COUNTERFACTUAL" if families else "INFERENCE",
        "hypotheses": [
            {
                "id": "H104-01",
                "claim": "At most four families declared from 98-103 TRAIN+VAL evidence improve C/D vs E/F without destroying the tail.",
                "result": helpful if families else "NO_FAMILIES_DECLARED",
                "oos_used_for_decision": False,
            }
        ],
        "tests_performed": 1,
        "diagnostics_run": ["minimal_discriminator_families"],
        "oos_used_for_selection": False,
        "final_gate": BLOCKED,
        "FINAL_GATE": BLOCKED,
        "production_safety": {
            "TRADING": "NOT_PERFORMED",
            "STRATEGY": "NOT_MODIFIED",
            "OPTIMIZATION": "NOT_PERFORMED",
            "ENV": "NOT_READ",
            "MT5": "NOT_USED",
            "production_changes": "NONE",
            "not_exit_rules": True,
        },
        "git_head": _git_head(root),
        "artifacts": {"json": PHASE104_JSON, "md": PHASE104_MD},
    }
    (root / PHASE104_JSON).parent.mkdir(parents=True, exist_ok=True)
    (root / PHASE104_JSON).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    lines = [
        "# Phase 104 — Predeclared Minimal Discriminator",
        "",
        "COUNTERFACTUAL if families exist. Not an exit rule. Combinations only if both parts independently confirmed.",
        f"**n_families:** `{len(families)}`",
        f"**helpful_and_tail_safe:** `{helpful}`",
        "",
    ]
    if not families:
        lines.append("No TRAIN+VAL confirmed discriminator in Phases 98–103. Families not invented.")
    for name, row in evals.items():
        lines.append(
            f"- `{name}` status=`{row.get('status')}` tail=`{row.get('TAIL_PRESERVATION')}` "
            f"OOS_dir=`{row.get('survives_OOS_direction')}`"
        )
    (root / PHASE104_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = run_phase104_collection(Path("."))
    print(p["n_families"], p["helpful_families"])
