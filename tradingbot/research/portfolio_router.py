"""PHASE 22D research-only portfolio router. Not wired to live routing."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

ENGINE_PA_CURRENT = "PA_CURRENT"
ENGINE_SWEEP_MSS_FVG = "SWEEP_MSS_FVG"
ENGINE_HTF_LIQUIDITY = "HTF_LIQUIDITY_SWEEP"
ENGINE_NONE = "NONE"

CANDIDATE_ENGINES = (ENGINE_PA_CURRENT, ENGINE_SWEEP_MSS_FVG, ENGINE_HTF_LIQUIDITY)

MODEL_TO_ENGINE = {
    "MODEL_A_CURRENT_PA": ENGINE_PA_CURRENT,
    "PA_CURRENT": ENGINE_PA_CURRENT,
    "MODEL_B_SWEEP_MSS_FVG": ENGINE_SWEEP_MSS_FVG,
    "SWEEP_MSS_FVG": ENGINE_SWEEP_MSS_FVG,
    "MODEL_C_HTF_LIQUIDITY": ENGINE_HTF_LIQUIDITY,
    "HTF_LIQUIDITY_SWEEP": ENGINE_HTF_LIQUIDITY,
}


@dataclass
class EngineSignal:
    model_id: str
    setup_id: str
    timestamp: str
    bar_index: int
    direction: str
    confidence: float
    expected_edge: float
    regime: str
    session: str
    reason: str
    certified: bool
    oos_quality: float
    realized_r: float
    planned_rr: float
    duplicate_key: str
    day: str
    final_R_spread: float = 0.0
    final_R_stress: float = 0.0
    sweep_level_type: str = ""

    def as_candidate(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "setup_id": self.setup_id,
            "direction": self.direction,
            "confidence": round(float(self.confidence), 4),
            "expected_edge": round(float(self.expected_edge), 4),
            "certified": bool(self.certified),
            "oos_quality": round(float(self.oos_quality), 4),
        }


@dataclass
class RouterState:
    last_bar: int = -10_000
    open_until: int = -1
    day: str = ""
    day_count: int = 0
    day_risk_r: float = 0.0
    recent_keys: dict[str, int] = field(default_factory=dict)


@dataclass
class RouterLimits:
    max_trades_day: int = 3
    cooldown_bars: int = 18
    open_hold_bars: int = 12
    max_daily_risk_r: float = 3.0
    dup_cluster_bars: int = 6


@dataclass
class RouterDecision:
    timestamp: str
    engine_candidates: list[str]
    selected_engine: str
    reason: str
    confidence: float
    expected_edge: float
    regime: str
    session: str
    risk_plan: dict[str, Any]
    blocked_engines: list[dict[str, str]]
    duplicate_key: str
    selected: EngineSignal | None = None

    def to_log(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "engine_candidates": self.engine_candidates,
            "selected_engine": self.selected_engine,
            "reason": self.reason,
            "confidence": self.confidence,
            "expected_edge": self.expected_edge,
            "regime": self.regime,
            "session": self.session,
            "risk_plan": self.risk_plan,
            "blocked_engines": self.blocked_engines,
            "duplicate_key": self.duplicate_key,
        }


class ResearchEngine:
    """Independent research engine. generate_signal() is bar-index lookup."""

    def __init__(
        self,
        model_id: str,
        *,
        certified: bool,
        oos_quality: float,
        expected_edge: float,
        setups: list[dict[str, Any]],
        cluster_bars: int = 6,
    ) -> None:
        self.model_id = model_id
        self.certified = bool(certified)
        self.oos_quality = float(oos_quality)
        self.expected_edge = float(expected_edge) if certified else 0.0
        self._by_bar: dict[int, EngineSignal] = {}
        for rec in setups:
            sig = self._to_signal(rec, cluster_bars)
            i = sig.bar_index
            if i not in self._by_bar:
                self._by_bar[i] = sig

    def generate_signal(self, bar_index: int) -> EngineSignal | None:
        return self._by_bar.get(int(bar_index))

    def all_signals(self) -> list[EngineSignal]:
        return [self._by_bar[k] for k in sorted(self._by_bar)]

    def _to_signal(self, rec: dict[str, Any], cluster_bars: int) -> EngineSignal:
        i = int(rec["i"])
        day = str(rec.get("day") or "")
        direction = str(rec.get("direction") or "")
        cluster = i // max(int(cluster_bars), 1)
        dup = "%s|%s|%s" % (day, direction, cluster)
        depth = float(rec.get("sweep_depth_atr") or 0.0)
        disp = float(rec.get("displacement_strength") or 0.0)
        conf = max(0.05, min(1.0, 0.35 * depth + 0.40 * max(disp, 0.0) + 0.15))
        setup_id = "%s|%s|%s" % (self.model_id, rec.get("timestamp"), direction)
        reason = "certified_setup" if self.certified else "uncertified_research_setup"
        return EngineSignal(
            model_id=self.model_id,
            setup_id=setup_id,
            timestamp=str(rec.get("timestamp") or ""),
            bar_index=i,
            direction=direction,
            confidence=conf,
            expected_edge=self.expected_edge,
            regime=str(rec.get("regime") or ""),
            session=str(rec.get("session") or ""),
            reason=reason,
            certified=self.certified,
            oos_quality=self.oos_quality if self.certified else 0.0,
            realized_r=float(rec.get("final_R") or 0.0),
            planned_rr=float(rec.get("planned_rr") or 0.0),
            duplicate_key=dup,
            day=day,
            final_R_spread=float(rec.get("final_R_spread") or 0.0),
            final_R_stress=float(rec.get("final_R_stress") or 0.0),
            sweep_level_type=str(rec.get("sweep_level_type") or ""),
        )


class PortfolioRouter:
    """Selects only 22B-certified engines. Not connected to live MultiEngineRouter."""

    def __init__(self, engines: Iterable[ResearchEngine], limits: RouterLimits | None = None) -> None:
        self.engines = {e.model_id: e for e in engines}
        self.limits = limits or RouterLimits()
        self.state = RouterState()

    def collect(self, bar_index: int) -> list[EngineSignal]:
        out: list[EngineSignal] = []
        for eng in self.engines.values():
            sig = eng.generate_signal(bar_index)
            if sig is not None:
                out.append(sig)
        return out

    def decide(self, candidates: list[EngineSignal]) -> RouterDecision:
        if not candidates:
            return RouterDecision(
                timestamp="",
                engine_candidates=[],
                selected_engine=ENGINE_NONE,
                reason="no_candidates",
                confidence=0.0,
                expected_edge=0.0,
                regime="",
                session="",
                risk_plan={},
                blocked_engines=[],
                duplicate_key="",
            )
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
        eligible.sort(key=lambda s: (s.oos_quality, s.expected_edge, s.confidence), reverse=True)
        pick = eligible[0]
        for sig in eligible[1:]:
            blocked.append({"engine": sig.model_id, "reason": "conflict_lower_oos_quality"})
        self._commit(pick)
        return RouterDecision(
            timestamp=pick.timestamp,
            engine_candidates=names,
            selected_engine=pick.model_id,
            reason="highest_certified_oos_quality" if len(eligible) > 1 else "sole_certified_eligible",
            confidence=pick.confidence,
            expected_edge=pick.expected_edge,
            regime=pick.regime,
            session=pick.session,
            risk_plan=self._risk_plan(pick),
            blocked_engines=blocked,
            duplicate_key=pick.duplicate_key,
            selected=pick,
        )

    def _block_reason(self, sig: EngineSignal) -> str | None:
        lim = self.limits
        st = self.state
        if not sig.certified:
            return "uncertified_engine"
        if sig.bar_index <= st.open_until:
            return "risk_cap_open_trade"
        if sig.bar_index - st.last_bar < lim.cooldown_bars:
            return "cooldown"
        if st.day_count >= lim.max_trades_day:
            return "max_trades_day"
        if st.day_risk_r + 1.0 > lim.max_daily_risk_r + 1e-9:
            return "risk_cap_daily"
        prev = st.recent_keys.get(sig.duplicate_key)
        if prev is not None and sig.bar_index - prev < lim.dup_cluster_bars * 4:
            return "duplicate_setup"
        return None

    def _commit(self, sig: EngineSignal) -> None:
        self.state.last_bar = sig.bar_index
        self.state.open_until = sig.bar_index + self.limits.open_hold_bars
        self.state.day_count += 1
        self.state.day_risk_r += 1.0
        self.state.recent_keys[sig.duplicate_key] = sig.bar_index

    def _roll_day(self, day: str) -> None:
        if day != self.state.day:
            self.state.day = day
            self.state.day_count = 0
            self.state.day_risk_r = 0.0

    def _risk_plan(self, sig: EngineSignal | None) -> dict[str, Any]:
        return {
            "max_trades_day": self.limits.max_trades_day,
            "cooldown_bars": self.limits.cooldown_bars,
            "max_daily_risk_r": self.limits.max_daily_risk_r,
            "open_hold_bars": self.limits.open_hold_bars,
            "planned_rr": None if sig is None else sig.planned_rr,
            "risk_units": 0 if sig is None else 1.0,
            "day_count": self.state.day_count,
            "day_risk_r": round(self.state.day_risk_r, 4),
        }