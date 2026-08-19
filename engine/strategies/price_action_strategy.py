"""
Price Action Strategy — SMC حرفه‌ای (sweep, BOS+OB, FVG).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from engine.logger import get_logger
from engine.strategies.base_strategy import BaseStrategy, Signal, SignalType
from tradingbot.config.pa_symbol_tf_presets import is_pa_cell_enabled
from tradingbot.config.price_action import PRICE_ACTION_CONFIG, get_price_action_config
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.domain.filter_policy import (
    aligned_session_hours,
    is_session_filter_enabled,
    strategy_uses_kill_zone,
)
from tradingbot.domain.gold_strategies import evaluate_gold_setup
from tradingbot.domain.gold_strategies.m5_london_sweep import diagnose_m5_london_hold
from tradingbot.domain.price_action import enrich_price_action
from tradingbot.domain.session_logic import is_kill_zone

logger = get_logger("price_action", ".")


def _emit_pa_hold(
    *,
    timestamp: Any,
    session_ok: bool,
    asian_range_built: bool = False,
    sweep_detected: bool = False,
    reclaim_detected: bool = False,
    bos_detected: bool = False,
    fvg_detected: bool = False,
    confidence_score: float = 0.0,
    quality_score: float = 0.0,
    reject_reason: str,
    symbol: str = PRIMARY_SYMBOL,
    timeframe: str = "M5",
) -> None:
    """Observability only — never raises into the trading path."""
    try:
        from tradingbot.services.engine_telemetry import get_engine_telemetry

        ts = timestamp
        if hasattr(ts, "isoformat"):
            ts_s = ts.isoformat()
        else:
            ts_s = str(ts)
        get_engine_telemetry().record_pa_hold_reason(
            timestamp=ts_s,
            session_ok=session_ok,
            asian_range_built=asian_range_built,
            sweep_detected=sweep_detected,
            reclaim_detected=reclaim_detected,
            bos_detected=bos_detected,
            fvg_detected=fvg_detected,
            confidence_score=float(confidence_score or 0.0),
            reject_reason=reject_reason,
            symbol=symbol,
            timeframe=timeframe,
            extra={"quality_score": float(quality_score or 0.0)},
        )
    except Exception:
        pass
    try:
        from tradingbot.research.phase17a_forensic import record_pa_forensic_decision

        record_pa_forensic_decision(
            timestamp=timestamp,
            symbol=symbol,
            timeframe=timeframe,
            session_ok=session_ok,
            asian_range_ready=asian_range_built,
            sweep_detected=sweep_detected,
            reclaim_ok=reclaim_detected,
            bos_ok=bos_detected,
            fvg_ok=fvg_detected,
            confidence=float(confidence_score or 0.0),
            quality_score=float(quality_score or 0.0),
            reject_reason=reject_reason,
        )
    except Exception:
        pass


def _structure_flags(df: pd.DataFrame, i: int, setup: Any) -> tuple[bool, bool]:
    try:
        from tradingbot.domain.pa_hardening import (
            confirm_fvg_fill,
            detect_bos_continuation,
            detect_liquidity_sweep_flag,
        )

        if setup is not None:
            return (
                bool(setup.metadata.get("bos_confirmed", False)),
                bool(setup.metadata.get("fvg_confirmed", False)),
            )
        breaks = df.attrs.get("pa_breaks", []) or []
        fvgs = df.attrs.get("pa_fvgs", []) or []
        price = float(df["close"].iloc[i])
        bos = detect_bos_continuation(breaks, i, 1) or detect_bos_continuation(breaks, i, -1)
        fvg = confirm_fvg_fill(fvgs, price=price, direction=1, i=i) or confirm_fvg_fill(
            fvgs, price=price, direction=-1, i=i
        )
        return bos, fvg
    except Exception:
        return False, False


class PriceActionStrategy(BaseStrategy):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config or {})
        self.name = "price_action"
        self.description = "Professional SMC Price Action"
        self.is_active = True
        self.signal_weight = 1.0

        merged = dict(config or {})
        pa = dict(merged.get("PRICE_ACTION", {}))
        self._base_pa = {**PRICE_ACTION_CONFIG, **pa}
        self._legacy = merged
        self.cfg = dict(self._base_pa)
        self.min_confidence = float(self.cfg.get("MIN_CONFIDENCE", 0.50))
        self.session_start = int(self.cfg.get("SESSION_START_HOUR", 8))
        self.session_end = int(self.cfg.get("SESSION_END_HOUR", 20))
        self.cooldown_bars = int(self.cfg.get("COOLDOWN_BARS", 10))
        allowed = self.cfg.get("ALLOWED_SYMBOLS", [])
        self.allowed_symbols = {s.upper() for s in allowed}
        self._pending_dir = 0
        self._pending_count = 0

    def generate_signals(
        self,
        data: pd.DataFrame,
        symbol: str | None = None,
        timeframe: str | None = None,
        return_trades: bool = False,
    ) -> list[Signal]:
        if return_trades:
            return []
        if data is None or data.empty or len(data) < 60:
            return []

        sym = (symbol or "").upper()
        if sym and self.allowed_symbols:
            allowed = {s.upper() for s in self.allowed_symbols}
            if sym not in allowed and not any(x in sym for x in ("XAU", "GOLD")):
                return []

        tf = (timeframe or "").lower()
        if tf and tf not in ("5m", "15m", "4h", "m5", "m15", "h4"):
            return []
            
        if sym and tf and not is_pa_cell_enabled(sym, tf):
            return []

        cfg = get_price_action_config(sym or PRIMARY_SYMBOL, tf or "15m")
        min_conf = float(cfg.get("MIN_CONFIDENCE", self.min_confidence))
        session_start, session_end = aligned_session_hours(cfg)
        out_sym = sym or PRIMARY_SYMBOL
        out_tf = (tf or "15m").upper().replace("5M", "M5").replace("15M", "M15").replace("4H", "H4")
        if out_tf in ("5M", "M5"):
            out_tf = "M5"

        i = len(data) - 1
        ts = data.index[i]
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if isinstance(ts, datetime) and is_session_filter_enabled(cfg):
            if not (session_start <= ts.hour < session_end):
                _emit_pa_hold(
                    timestamp=ts,
                    session_ok=False,
                    reject_reason="outside_ny_entry_window",
                    symbol=out_sym,
                    timeframe=out_tf,
                )
                return []
            if not is_kill_zone(ts, use_kill_zones=strategy_uses_kill_zone(cfg)):
                _emit_pa_hold(
                    timestamp=ts,
                    session_ok=True,
                    reject_reason="kill_zone_blocked",
                    symbol=out_sym,
                    timeframe=out_tf,
                )
                return []

        df = enrich_price_action(data, cfg, at_index=i)
        setup = evaluate_gold_setup(df, i, cfg, timeframe=tf or "15m")
        if setup is None or setup.confidence < min_conf:
            self._pending_dir = 0
            self._pending_count = 0
            diag = (
                diagnose_m5_london_hold(df, i, cfg)
                if out_tf == "M5"
                else {
                    "session_ok": True,
                    "asian_range_built": False,
                    "sweep_detected": False,
                    "reclaim_detected": False,
                    "confidence_score": float(getattr(setup, "confidence", 0) or 0),
                    "reject_reason": "no_setup",
                }
            )
            bos, fvg = _structure_flags(df, i, setup)
            qscore = 0.0
            if setup is not None and setup.confidence < min_conf:
                reason = "confidence_below_threshold"
                conf = float(setup.confidence)
                qscore = float((setup.metadata or {}).get("quality_score", 0) or 0)
            else:
                reason = str(diag.get("reject_reason") or "no_setup")
                conf = float(diag.get("confidence_score") or 0.0)
                if reason == "setup_ok_pre_hardening":
                    reason = "hardening_rejected"
            _emit_pa_hold(
                timestamp=ts,
                session_ok=bool(diag.get("session_ok", True)),
                asian_range_built=bool(diag.get("asian_range_built", False)),
                sweep_detected=bool(diag.get("sweep_detected", False)),
                reclaim_detected=bool(diag.get("reclaim_detected", False)),
                bos_detected=bos,
                fvg_detected=fvg,
                confidence_score=conf,
                quality_score=qscore,
                reject_reason=reason,
                symbol=out_sym,
                timeframe=out_tf,
            )
            return []

        from tradingbot.domain.pa_hardening import is_duplicate_pa_signal

        dedup_min = int(cfg.get("PA_DEDUP_COOLDOWN_MINUTES", 10))
        if is_duplicate_pa_signal(sym or PRIMARY_SYMBOL, setup.direction, ts, cooldown_minutes=dedup_min):
            bos, fvg = _structure_flags(df, i, setup)
            _emit_pa_hold(
                timestamp=ts,
                session_ok=True,
                asian_range_built=True,
                sweep_detected=bool(setup.metadata.get("liquidity_sweep", False)),
                reclaim_detected=True,
                bos_detected=bos,
                fvg_detected=fvg,
                confidence_score=float(setup.confidence),
                quality_score=float((setup.metadata or {}).get("quality_score", 0) or 0),
                reject_reason="duplicate_pa_signal",
                symbol=out_sym,
                timeframe=out_tf,
            )
            return []

        confirm_bars = int(cfg.get("SIGNAL_CONFIRMATION_BARS", 0))
        if confirm_bars > 0:
            if self._pending_dir != setup.direction:
                self._pending_dir = setup.direction
                self._pending_count = 1
                bos, fvg = _structure_flags(df, i, setup)
                _emit_pa_hold(
                    timestamp=ts,
                    session_ok=True,
                    asian_range_built=True,
                    sweep_detected=bool(setup.metadata.get("liquidity_sweep", False)),
                    reclaim_detected=True,
                    bos_detected=bos,
                    fvg_detected=fvg,
                    confidence_score=float(setup.confidence),
                    quality_score=float((setup.metadata or {}).get("quality_score", 0) or 0),
                    reject_reason="signal_confirmation_pending",
                    symbol=out_sym,
                    timeframe=out_tf,
                )
                return []
            self._pending_count += 1
            if self._pending_count < confirm_bars:
                bos, fvg = _structure_flags(df, i, setup)
                _emit_pa_hold(
                    timestamp=ts,
                    session_ok=True,
                    asian_range_built=True,
                    sweep_detected=bool(setup.metadata.get("liquidity_sweep", False)),
                    reclaim_detected=True,
                    bos_detected=bos,
                    fvg_detected=fvg,
                    confidence_score=float(setup.confidence),
                    quality_score=float((setup.metadata or {}).get("quality_score", 0) or 0),
                    reject_reason="signal_confirmation_pending",
                    symbol=out_sym,
                    timeframe=out_tf,
                )
                return []
            self._pending_dir = 0
            self._pending_count = 0

        sig_type = SignalType.BUY if setup.direction == 1 else SignalType.SELL
        signal = Signal(
            timestamp=ts,
            signal_type=sig_type,
            price=setup.entry,
            confidence=setup.confidence,
                    metadata={
                "strategy": "priceaction",
                "setup": setup.setup.value,
                "confidence": setup.confidence,
                "stop_loss": setup.stop_loss,
                "take_profit": setup.take_profit,
                "risk_reward_ratio": setup.metadata.get("rr", 2.0),
                "confluence": setup.confluence,
                "trend": setup.metadata.get("trend"),
                "pattern": setup.setup.value,
                "setup_type": setup.metadata.get("setup_type", setup.setup.value),
                "bos_confirmed": setup.metadata.get("bos_confirmed", False),
                "fvg_confirmed": setup.metadata.get("fvg_confirmed", False),
                "liquidity_sweep": setup.metadata.get("liquidity_sweep", False),
                "quality_score": setup.metadata.get("quality_score", 0),
                "session": setup.metadata.get("session", ""),
                "hour15_mode": setup.metadata.get("hour15_mode", out_tf == "M5"),
                "asian_end_utc": setup.metadata.get("asian_end_utc"),
            },
        )
        if self.validate_signal(signal):
            try:
                from tradingbot.research.phase17a_forensic import record_pa_forensic_decision

                record_pa_forensic_decision(
                    timestamp=ts,
                    symbol=out_sym,
                    timeframe=out_tf,
                    session_ok=True,
                    asian_range_ready=True,
                    sweep_detected=bool(setup.metadata.get("liquidity_sweep", False)),
                    reclaim_ok=True,
                    bos_ok=bool(setup.metadata.get("bos_confirmed", False)),
                    fvg_ok=bool(setup.metadata.get("fvg_confirmed", False)),
                    confidence=float(setup.confidence),
                    quality_score=float((setup.metadata or {}).get("quality_score", 0) or 0),
                    reject_reason="signal_emitted",
                    extra={"event": "pa_signal"},
                )
            except Exception:
                pass
            return [signal]
        bos, fvg = _structure_flags(df, i, setup)
        _emit_pa_hold(
            timestamp=ts,
            session_ok=True,
            asian_range_built=True,
            sweep_detected=bool(setup.metadata.get("liquidity_sweep", False)),
            reclaim_detected=True,
            bos_detected=bos,
            fvg_detected=fvg,
            confidence_score=float(setup.confidence),
            quality_score=float((setup.metadata or {}).get("quality_score", 0) or 0),
            reject_reason="validate_signal_failed",
            symbol=out_sym,
            timeframe=out_tf,
        )
        return []
