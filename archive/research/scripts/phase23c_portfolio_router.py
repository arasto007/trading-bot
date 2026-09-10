#!/usr/bin/env python3
"""PHASE 23C - Portfolio router promotion candidate (research-only, no live enable).

Uses only Phase 23B-certified engines for portfolio routing. Compares PA / ORB / Momentum
isolated baselines vs regime-aware multi-engine portfolio.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.update({
    "USE_ML_KERNEL": "false",
    "TRADINGBOT_DISABLE_JOURNAL": "1",
    "TRADINGBOT_DRY_RUN": "1",
})

from tradingbot.config.dotenv_loader import load_dotenv

load_dotenv()

from tradingbot.research.portfolio_router import (
    ENGINE_NONE,
    EngineSignal,
    PortfolioRouter,
    ResearchEngine,
    RouterDecision,
    RouterLimits,
)

OUT = ROOT / "logs" / "phase23c"
CERT_23B = ROOT / "logs" / "phase23b" / "certification_matrix.json"
RESULT_23B = ROOT / "logs" / "phase23b" / "phase23b_result.txt"
LOG_JSONL = OUT / "portfolio_router_decisions.jsonl"
TEL_DIR = OUT / "engine_telemetry"

ENGINE_PA = "PA"
ENGINE_ORB = "ORB"
ENGINE_MOMENTUM = "MOMENTUM"
CANDIDATE_ENGINES = (ENGINE_PA, ENGINE_ORB, ENGINE_MOMENTUM)

CERT_LABEL_TO_ENGINE = {
    "MODEL_A_LONDON_SWEEP": ENGINE_PA,
    "MODEL_A": ENGINE_PA,
    "PA": ENGINE_PA,
    "MODEL_B_ORB": ENGINE_ORB,
    "ORB_30M_CONT": ENGINE_ORB,
    "ORB": ENGINE_ORB,
    "MODEL_C_MOM": ENGINE_MOMENTUM,
    "MOM_90M": ENGINE_MOMENTUM,
    "MOMENTUM": ENGINE_MOMENTUM,
}

FROZEN_ORB = "ORB_30M_CONT"
FROZEN_MOM = "MOM_90M"
COOLDOWN = 18
MAX_DAY = 3

MODES = (
    "PA_ONLY",
    "ORB_ONLY",
    "MOMENTUM_ONLY",
    "PORTFOLIO",
)

FAMILY_KEY_TO_ENGINE = {
    "A": ENGINE_PA,
    "B": ENGINE_ORB,
    "C": ENGINE_MOMENTUM,
}


def emit(msg: str) -> None:
    print(msg, flush=True)


def load_p23a():
    path = ROOT / "scripts" / "phase23a_multi_strategy_discovery.py"
    spec = importlib.util.spec_from_file_location("phase23a_multi_strategy_discovery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load phase23a_multi_strategy_discovery.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_kv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def label_to_engine(label: str) -> str | None:
    label = str(label or "").strip()
    if not label:
        return None
    if label in CERT_LABEL_TO_ENGINE:
        return CERT_LABEL_TO_ENGINE[label]
    for k, v in CERT_LABEL_TO_ENGINE.items():
        if k == label:
            return v
    return CERT_LABEL_TO_ENGINE.get(label)


def load_certified_engines(cert_path: Path = CERT_23B, result_path: Path = RESULT_23B) -> set[str]:
    certified: set[str] = set()
    if cert_path.is_file():
        blob = json.loads(cert_path.read_text(encoding="utf-8"))
        for label, rec in (blob.get("candidates") or {}).items():
            if not rec.get("certified"):
                continue
            eng = label_to_engine(label) or label_to_engine(str(rec.get("strategy_id") or ""))
            if eng in CANDIDATE_ENGINES:
                certified.add(eng)
    kv = parse_kv(result_path)
    raw = kv.get("CERTIFIED_MODELS", "")
    if raw and raw.upper() != "NONE":
        for token in raw.split(","):
            eng = label_to_engine(token.strip())
            if eng in CANDIDATE_ENGINES:
                certified.add(eng)
    certified.discard("")
    return certified


def regime_bucket(reg: str) -> str:
    r = str(reg or "")
    if r in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
        return "trend"
    if r in ("VOLATILE", "CRISIS"):
        return "expansion"
    return "ranging"


def quality_from_metrics(m: dict[str, Any]) -> float:
    pf = float(m.get("profit_factor") or 0.0)
    exp = float(m.get("expectancy_R") or 0.0)
    q = 0.5 * min(max(pf, 0.0), 3.0) / 3.0 + 0.5 * (max(min(exp, 0.5), -0.5) + 0.5)
    return round(q, 4)


def load_oos_quality(cert_blob: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {e: {"quality": 0.0, "pf": 0.0, "exp": 0.0, "trades": 0} for e in CANDIDATE_ENGINES}
    for label, rec in (cert_blob.get("candidates") or {}).items():
        eng = label_to_engine(label) or label_to_engine(str(rec.get("strategy_id") or ""))
        if eng not in CANDIDATE_ENGINES:
            continue
        wf = rec.get("walk_forward") or {}
        pooled = (wf.get("pooled_oos") or {}).get(rec.get("key") or "") or wf.get("pooled_oos")
        if isinstance(pooled, dict) and "profit_factor" in pooled:
            m = pooled
        else:
            key = str(rec.get("key") or "")
            m = (wf.get("pooled_oos") or {}).get(key) or {}
        if not m:
            continue
        out[eng] = {
            "pf": float(m.get("profit_factor") or 0.0),
            "exp": float(m.get("expectancy_R") or 0.0),
            "quality": quality_from_metrics(m),
            "trades": int(m.get("trades") or 0),
            "label": label,
        }
    fam = cert_blob.get("family_reference") or {}
    key_map = {"A": ENGINE_PA, "B": ENGINE_ORB, "C": ENGINE_MOMENTUM}
    for k, eng in key_map.items():
        ref = fam.get(k) or {}
        m = ref.get("pooled_oos") or {}
        if int(out[eng].get("trades") or 0) == 0 and m:
            out[eng] = {
                "pf": float(m.get("profit_factor") or 0.0),
                "exp": float(m.get("expectancy_R") or 0.0),
                "quality": quality_from_metrics(m),
                "trades": int(m.get("trades") or 0),
                "label": str(ref.get("model") or eng),
                "reference_only": True,
            }
    return out


def build_regime_scores(cert_blob: dict[str, Any], oos_quality: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    buckets = ("trend", "expansion", "ranging")
    scores: dict[str, dict[str, float]] = {e: {b: 0.0 for b in buckets} for e in CANDIDATE_ENGINES}
    for label, rec in (cert_blob.get("candidates") or {}).items():
        eng = label_to_engine(label) or label_to_engine(str(rec.get("strategy_id") or ""))
        if eng not in CANDIDATE_ENGINES:
            continue
        by_reg = ((rec.get("stability") or {}).get("by_regime")) or {}
        for bucket, m in by_reg.items():
            b = str(bucket)
            if b not in scores[eng]:
                scores[eng][b] = quality_from_metrics(m)
            else:
                scores[eng][b] = max(scores[eng][b], quality_from_metrics(m))
    fam = cert_blob.get("family_reference") or {}
    for key, eng in FAMILY_KEY_TO_ENGINE.items():
        base_q = float((oos_quality.get(eng) or {}).get("quality") or 0.0)
        for b in buckets:
            if scores[eng][b] <= 0.0:
                scores[eng][b] = base_q
    for eng in CANDIDATE_ENGINES:
        base_q = float((oos_quality.get(eng) or {}).get("quality") or 0.0)
        for b in buckets:
            if scores[eng][b] <= 0.0:
                scores[eng][b] = base_q
    return scores


class RegimeAwarePortfolioRouter(PortfolioRouter):
    """Certified-only router with regime-weighted conflict resolution."""

    def __init__(
        self,
        engines: list[ResearchEngine] | tuple[ResearchEngine, ...],
        *,
        limits: RouterLimits | None = None,
        regime_scores: dict[str, dict[str, float]] | None = None,
    ) -> None:
        super().__init__(engines, limits=limits)
        self.regime_scores = regime_scores or {}

    def _regime_score(self, sig: EngineSignal) -> float:
        bucket = regime_bucket(sig.regime)
        eng_scores = self.regime_scores.get(sig.model_id) or {}
        return float(eng_scores.get(bucket) or eng_scores.get("ranging") or 0.0)

    def decide(self, candidates: list[EngineSignal]) -> RouterDecision:
        if not candidates:
            return super().decide(candidates)
        lead = max(candidates, key=lambda s: s.bar_index)
        self._roll_day(lead.day)
        blocked: list[dict[str, str]] = []
        eligible: list[EngineSignal] = []
        for sig in candidates:
            why = self._block_reason(sig)
            if why:
                blocked.append({"engine": sig.model_id, "reason": why})
            else:
                eligible.append(sig)
        names = [s.model_id for s in candidates]
        if not eligible:
            return RouterDecision(
                timestamp=lead.timestamp,
                engine_candidates=names,
                selected_engine=ENGINE_NONE,
                reason=blocked[0]["reason"] if blocked else "no_eligible",
                confidence=0.0,
                expected_edge=0.0,
                regime=lead.regime,
                session=lead.session,
                risk_plan=self._risk_plan(None),
                blocked_engines=blocked,
                duplicate_key=lead.duplicate_key,
            )
        eligible.sort(
            key=lambda s: (
                self._regime_score(s),
                s.oos_quality,
                s.expected_edge,
                s.confidence,
            ),
            reverse=True,
        )
        pick = eligible[0]
        bucket = regime_bucket(pick.regime)
        for sig in eligible[1:]:
            blocked.append({"engine": sig.model_id, "reason": "conflict_lower_regime_score"})
        reason = "regime_aware_highest_score" if len(eligible) > 1 else "sole_certified_eligible"
        self._commit(pick)
        return RouterDecision(
            timestamp=pick.timestamp,
            engine_candidates=names,
            selected_engine=pick.model_id,
            reason=reason,
            confidence=pick.confidence,
            expected_edge=pick.expected_edge,
            regime=pick.regime,
            session=pick.session,
            risk_plan={**self._risk_plan(pick), "regime_bucket": bucket, "regime_score": round(self._regime_score(pick), 4)},
            blocked_engines=blocked,
            duplicate_key=pick.duplicate_key,
            selected=pick,
        )


def summarize_mode(p22a, rs: list[float], spread_rs: list[float], stress_rs: list[float]) -> dict[str, Any]:
    base = p22a.metrics_from_rs(rs)
    base["cost_spread"] = p22a.metrics_from_rs(spread_rs) if spread_rs else p22a.metrics_from_rs([])
    base["cost_stress"] = p22a.metrics_from_rs(stress_rs) if stress_rs else p22a.metrics_from_rs([])
    return base


def daily_r(signals: list[EngineSignal]) -> dict[str, float]:
    acc: dict[str, float] = defaultdict(float)
    for sig in signals:
        acc[sig.day] += float(sig.realized_r)
    return dict(acc)


def corr_map(series: dict[str, dict[str, float]]) -> dict[str, float | None]:
    keys = list(series.keys())
    out: dict[str, float | None] = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            days = sorted(set(series[a]) | set(series[b]))
            if len(days) < 8:
                out["%s__%s" % (a, b)] = None
                continue
            xa = np.array([series[a].get(d, 0.0) for d in days], dtype=float)
            xb = np.array([series[b].get(d, 0.0) for d in days], dtype=float)
            if xa.std() < 1e-12 or xb.std() < 1e-12:
                out["%s__%s" % (a, b)] = 0.0
            else:
                out["%s__%s" % (a, b)] = round(float(np.corrcoef(xa, xb)[0, 1]), 4)
    return out


def engine_contribution(signals: list[EngineSignal]) -> tuple[dict[str, float], dict[str, int]]:
    contrib_r: dict[str, float] = defaultdict(float)
    contrib_n: dict[str, int] = defaultdict(int)
    for sig in signals:
        contrib_r[sig.model_id] += float(sig.realized_r)
        contrib_n[sig.model_id] += 1
    return dict(contrib_r), dict(contrib_n)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def write_engine_telemetry(engines: dict[str, ResearchEngine], selected_setup_ids: set[str]) -> None:
    TEL_DIR.mkdir(parents=True, exist_ok=True)
    for mid, eng in engines.items():
        rows = []
        for sig in eng.all_signals():
            rows.append({
                "timestamp": sig.timestamp,
                "model_id": sig.model_id,
                "setup_id": sig.setup_id,
                "direction": sig.direction,
                "confidence": sig.confidence,
                "expected_edge": sig.expected_edge,
                "regime": sig.regime,
                "session": sig.session,
                "reason": sig.reason,
                "certified": sig.certified,
                "oos_quality": sig.oos_quality,
                "selected": sig.setup_id in selected_setup_ids,
                "duplicate_key": sig.duplicate_key,
                "realized_r": sig.realized_r,
            })
        out_path = TEL_DIR / ("%s.jsonl" % mid.lower())
        out_path.write_text(
            "".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows),
            encoding="utf-8",
            newline="\n",
        )


def collect_engines(
    p23a,
    p22a,
    cert_blob: dict[str, Any],
    certified_global: set[str],
    oos_quality: dict[str, dict[str, Any]],
) -> tuple[Any, dict[str, list[dict[str, Any]]], dict[str, ResearchEngine]]:
    frozen_orb = str(cert_blob.get("frozen_orb") or FROZEN_ORB)
    frozen_mom = str(cert_blob.get("frozen_momentum") or FROZEN_MOM)
    orb_cfg = {str(c["strategy_id"]): c for c in p23a.ORB_CONFIGS}
    mom_cfg = {str(c["strategy_id"]): c for c in p23a.MOM_CONFIGS}
    if frozen_orb not in orb_cfg:
        frozen_orb = FROZEN_ORB
    if frozen_mom not in mom_cfg:
        frozen_mom = FROZEN_MOM

    df = p22a.load_df()
    ctx = p23a.build_ctx(p22a, df)
    raw_map = {
        ENGINE_PA: p23a.collect_model_a(p22a, ctx),
        ENGINE_ORB: p23a.collect_orb_variant(p22a, ctx, orb_cfg[frozen_orb]),
        ENGINE_MOMENTUM: p23a.collect_mom_variant(p22a, ctx, mom_cfg[frozen_mom]),
    }
    emit(
        "collect setups PA=%s ORB(%s)=%s MOM(%s)=%s bars=%s"
        % (
            len(raw_map[ENGINE_PA]),
            frozen_orb,
            len(raw_map[ENGINE_ORB]),
            frozen_mom,
            len(raw_map[ENGINE_MOMENTUM]),
            len(df),
        )
    )

    engines: dict[str, ResearchEngine] = {}
    for eng, raw in raw_map.items():
        q = oos_quality.get(eng) or {}
        engines[eng] = ResearchEngine(
            eng,
            certified=eng in certified_global,
            oos_quality=float(q.get("quality") or 0.0),
            expected_edge=float(q.get("exp") or 0.0),
            setups=raw,
        )
    return df, raw_map, engines


def mode_certified_set(mode: str, certified_global: set[str]) -> set[str]:
    if mode == "PA_ONLY":
        return {ENGINE_PA}
    if mode == "ORB_ONLY":
        return {ENGINE_ORB}
    if mode == "MOMENTUM_ONLY":
        return {ENGINE_MOMENTUM}
    return set(certified_global)


def rebuild_engine_from_signals(eng: ResearchEngine, *, certified: bool) -> ResearchEngine:
    rows: list[dict[str, Any]] = []
    for sig in eng.all_signals():
        rows.append({
            "i": sig.bar_index,
            "day": sig.day,
            "direction": sig.direction,
            "timestamp": sig.timestamp,
            "regime": sig.regime,
            "session": sig.session,
            "planned_rr": sig.planned_rr,
            "final_R": sig.realized_r,
            "final_R_spread": sig.final_R_spread,
            "final_R_stress": sig.final_R_stress,
        })
    return ResearchEngine(
        eng.model_id,
        certified=certified,
        oos_quality=eng.oos_quality,
        expected_edge=eng.expected_edge,
        setups=rows,
    )


def run_mode(
    mode: str,
    engines: dict[str, ResearchEngine],
    certified_global: set[str],
    regime_scores: dict[str, dict[str, float]],
    limits: RouterLimits,
) -> dict[str, Any]:
    active = mode_certified_set(mode, certified_global)
    mode_engines = {mid: rebuild_engine_from_signals(eng, certified=mid in active) for mid, eng in engines.items()}
    if mode == "PORTFOLIO":
        router: PortfolioRouter = RegimeAwarePortfolioRouter(
            mode_engines.values(),
            limits=limits,
            regime_scores=regime_scores,
        )
    else:
        router = PortfolioRouter(mode_engines.values(), limits=limits)

    bars = sorted({sig.bar_index for eng in mode_engines.values() for sig in eng.all_signals()})
    decisions: list[dict[str, Any]] = []
    selected: list[EngineSignal] = []
    block_counts: dict[str, int] = defaultdict(int)
    for i in bars:
        cands = router.collect(i)
        if not cands:
            continue
        dec = router.decide(cands)
        row = dec.to_log()
        row["mode"] = mode
        decisions.append(row)
        if dec.selected is not None:
            selected.append(dec.selected)
        for b in dec.blocked_engines:
            block_counts["%s:%s" % (b.get("engine"), b.get("reason"))] += 1

    rs = [float(s.realized_r) for s in selected]
    sp = [float(s.final_R_spread) for s in selected]
    st = [float(s.final_R_stress) for s in selected]
    contrib_r, contrib_n = engine_contribution(selected)
    none_rate = 0.0
    if decisions:
        none_rate = round(sum(1 for d in decisions if d.get("selected_engine") == ENGINE_NONE) / len(decisions), 4)
    return {
        "mode": mode,
        "active_certified": sorted(active),
        "decisions": decisions,
        "selected": selected,
        "metrics": {
            "trades": len(rs),
            "rs": rs,
            "spread_rs": sp,
            "stress_rs": st,
        },
        "engine_contribution_R": contrib_r,
        "engine_contribution_n": contrib_n,
        "block_counts": dict(block_counts),
        "router_events": len(decisions),
        "selected_none_rate": none_rate,
    }


def overlap_stats(engines: dict[str, ResearchEngine], cluster: int = 6) -> dict[str, Any]:
    buckets: dict[tuple[str, str, int], set[str]] = defaultdict(set)
    for mid, eng in engines.items():
        for sig in eng.all_signals():
            buckets[(sig.day, sig.direction, sig.bar_index // cluster)].add(mid)
    n = len(buckets)
    multi = sum(1 for v in buckets.values() if len(v) >= 2)
    pair_counts: dict[str, int] = defaultdict(int)
    for v in buckets.values():
        names = sorted(v)
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                pair_counts["%s__%s" % (a, b)] += 1
    return {
        "clusters": n,
        "multi_engine_clusters": multi,
        "overlap_rate": round(multi / n, 4) if n else 0.0,
        "pair_counts": dict(pair_counts),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    p23a = load_p23a()
    p22a = p23a.load_phase22a()
    cert_blob: dict[str, Any] = {}
    if CERT_23B.is_file():
        cert_blob = json.loads(CERT_23B.read_text(encoding="utf-8"))
    certified = load_certified_engines()
    oos_quality = load_oos_quality(cert_blob)
    regime_scores = build_regime_scores(cert_blob, oos_quality)
    emit("Phase 23B certified engines: %s" % (sorted(certified) or ["NONE"]))
    emit("OOS quality: %s" % {k: round(v.get("quality", 0.0), 4) for k, v in oos_quality.items()})

    df, raw_map, engines = collect_engines(p23a, p22a, cert_blob, certified, oos_quality)
    limits = RouterLimits(max_trades_day=MAX_DAY, cooldown_bars=COOLDOWN, open_hold_bars=12, max_daily_risk_r=3.0)

    mode_results: dict[str, Any] = {}
    for mode in MODES:
        emit("Simulating %s ..." % mode)
        mode_results[mode] = run_mode(mode, engines, certified, regime_scores, limits)

    portfolio = mode_results["PORTFOLIO"]
    selected_ids = {s.setup_id for s in portfolio["selected"]}
    write_jsonl(LOG_JSONL, portfolio["decisions"])
    write_engine_telemetry(engines, selected_ids)

    isolated_daily: dict[str, dict[str, float]] = {}
    raw_daily: dict[str, dict[str, float]] = {}
    for eng, raw in raw_map.items():
        cd = p22a.apply_cd(raw)
        acc: dict[str, float] = defaultdict(float)
        for t in cd:
            acc[str(t.get("day") or "")] += float(t.get("final_R") or 0.0)
        raw_daily[eng] = dict(acc)

    summaries: dict[str, Any] = {}
    for mode in MODES:
        pack = mode_results[mode]
        m = summarize_mode(
            p22a,
            pack["metrics"]["rs"],
            pack["metrics"]["spread_rs"],
            pack["metrics"]["stress_rs"],
        )
        summaries[mode] = {
            **m,
            "engine_contribution_R": {k: round(v, 4) for k, v in pack["engine_contribution_R"].items()},
            "engine_contribution_n": pack["engine_contribution_n"],
            "router_events": pack["router_events"],
            "selected_none_rate": pack["selected_none_rate"],
            "active_certified": pack["active_certified"],
        }
        isolated_daily[mode] = daily_r(pack["selected"])

    ov = overlap_stats(engines)
    cross_corr = corr_map(isolated_daily)
    raw_corr = corr_map(raw_daily)

    def line_mode(name: str, sm: dict[str, Any]) -> list[str]:
        return [
            "%s_TRADES=%s" % (name, sm.get("trades")),
            "%s_PF=%s" % (name, sm.get("profit_factor")),
            "%s_EXP_R=%s" % (name, sm.get("expectancy_R")),
            "%s_DD=%s" % (name, sm.get("max_dd_R")),
            "%s_STREAK=%s" % (name, sm.get("longest_losing_streak")),
            "%s_COST_STRESS_PF=%s" % (name, (sm.get("cost_stress") or {}).get("profit_factor")),
        ]

    result_lines = [
        "PHASE_23C_RESULT",
        "",
        "CERTIFIED_ENGINES=%s" % (",".join(sorted(certified)) if certified else "NONE"),
        "PRODUCTION_ENABLED=NO",
        "LIVE_PATCH_APPLIED=NO",
        "",
    ]
    for mode in MODES:
        result_lines.append("[%s]" % mode)
        result_lines.extend(line_mode(mode, summaries[mode]))
        result_lines.append("")

    port_sm = summaries["PORTFOLIO"]
    result_lines.extend(
        [
            "PORTFOLIO_ENGINE_OVERLAP_RATE=%s" % ov["overlap_rate"],
            "PORTFOLIO_ROUTER_EVENTS=%s" % port_sm.get("router_events"),
            "PORTFOLIO_SELECTED_NONE_RATE=%s" % port_sm.get("selected_none_rate"),
            "DECISION_LOG=%s" % LOG_JSONL,
            "",
        ]
    )
    result_text = "\n".join(result_lines)

    matrix = {
        "phase": "23C",
        "live_files_modified": False,
        "production_enabled": False,
        "certified_engines": sorted(certified),
        "candidate_engines": list(CANDIDATE_ENGINES),
        "frozen_orb": cert_blob.get("frozen_orb") or FROZEN_ORB,
        "frozen_momentum": cert_blob.get("frozen_momentum") or FROZEN_MOM,
        "oos_quality": oos_quality,
        "regime_scores": regime_scores,
        "limits": {
            "max_trades_day": limits.max_trades_day,
            "cooldown_bars": limits.cooldown_bars,
            "max_daily_risk_r": limits.max_daily_risk_r,
            "open_hold_bars": limits.open_hold_bars,
        },
        "router_rule": "never_select_uncertified; portfolio uses regime-aware tie-break",
        "mode_summaries": summaries,
        "engine_overlap": ov,
        "cross_mode_daily_correlation": cross_corr,
        "raw_engine_daily_correlation": raw_corr,
        "portfolio_block_counts": mode_results["PORTFOLIO"]["block_counts"],
        "decision_log": str(LOG_JSONL),
        "bars": len(df),
        "result_block": result_text,
    }
    (OUT / "router_matrix.json").write_text(json.dumps(matrix, indent=2, default=str), encoding="utf-8", newline="\n")
    notes = {
        "regime_scores": regime_scores,
        "overlap": ov,
        "cross_mode_correlation": cross_corr,
        "raw_correlation": raw_corr,
        "portfolio_contribution": summaries["PORTFOLIO"].get("engine_contribution_R"),
    }
    extra = result_text + "\nNOTES\n" + json.dumps(notes, indent=2, default=str) + "\nLIVE_PATCH_APPLIED=NO\n"
    (OUT / "phase23c_result.txt").write_text(extra, encoding="utf-8", newline="\n")
    emit(result_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
