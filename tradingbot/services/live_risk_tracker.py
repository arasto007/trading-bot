"""ردیابی وضعیت ریسک live — cooldown و سقف روزانه per-TF."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "data" / "live_risk_state.json"

_BAR_MINUTES = {
    "M5": 5,
    "5M": 5,
    "M15": 15,
    "15M": 15,
    "H4": 240,
    "4H": 240,
}


def _norm_tf(timeframe: str) -> str:
    t = (timeframe or "M15").upper()
    return {"5M": "M5", "15M": "M15", "4H": "H4"}.get(t, t)


@dataclass
class LiveRiskSnapshot:
    day_utc: str = ""
    trades_today: int = 0
    trades_today_by_tf: dict[str, int] = field(default_factory=dict)
    daily_pnl: float = 0.0
    consecutive_losses: int = 0
    last_entry_utc: str = ""
    last_entry_utc_by_tf: dict[str, str] = field(default_factory=dict)
    pause_until_utc: str = ""
    position_cap_until_utc: str = ""
    day_start_equity: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveRiskTracker:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or STATE_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> LiveRiskSnapshot:
        if not self._path.is_file():
            return LiveRiskSnapshot()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            snap = LiveRiskSnapshot(
                **{
                    k: data[k]
                    for k in LiveRiskSnapshot.__dataclass_fields__
                    if k in data
                }
            )
            if snap.last_entry_utc and not snap.last_entry_utc_by_tf:
                snap.last_entry_utc_by_tf = {}
            return snap
        except Exception:
            return LiveRiskSnapshot()

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _today_utc() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _reset_day_if_needed(self, equity: float) -> None:
        today = self._today_utc()
        if self._state.day_utc != today:
            self._state.day_utc = today
            self._state.trades_today = 0
            self._state.trades_today_by_tf = {}
            self._state.daily_pnl = 0.0
            self._state.consecutive_losses = 0
            self._state.day_start_equity = equity

    def sync_from_mt5(self, equity: float, config: dict[str, Any] | None = None) -> None:
        """از تاریخچه معاملات امروز آمار را به‌روز می‌کند."""
        self._reset_day_if_needed(equity)
        try:
            import MetaTrader5 as mt5

            now = datetime.now(timezone.utc)
            start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
            deals = mt5.history_deals_get(start, now)
            if deals is None:
                return

            pnl = 0.0
            losses_streak = 0
            closed_count = 0
            for d in sorted(deals, key=lambda x: x.time):
                if int(getattr(d, "entry", 0)) != 1:
                    continue
                profit = float(getattr(d, "profit", 0.0))
                pnl += profit
                closed_count += 1
                if profit < 0:
                    losses_streak += 1
                else:
                    losses_streak = 0

            self._state.daily_pnl = pnl
            if closed_count > 0:
                self._state.consecutive_losses = losses_streak

            try:
                from tradingbot.ml.shadow.shadow_live_sync import sync_mt5_closed_deals

                sync_mt5_closed_deals(config)
            except Exception:
                pass

            max_losses = int((config or {}).get("MAX_CONSECUTIVE_LOSSES", 3))
            cooldown_bars = int((config or {}).get("COOLDOWN_AFTER_LOSS_BARS", 30))
            if losses_streak >= max_losses and not self._state.pause_until_utc:
                pause_min = cooldown_bars * 5
                until = now + timedelta(minutes=pause_min)
                self._state.pause_until_utc = until.isoformat()
        except Exception:
            pass
        self._save()

    def record_entry(self, timeframe: str) -> None:
        self._reset_day_if_needed(self._state.day_start_equity or 1.0)
        tf = _norm_tf(timeframe)
        self._state.trades_today += 1
        self._state.trades_today_by_tf[tf] = self._state.trades_today_by_tf.get(tf, 0) + 1
        now = datetime.now(timezone.utc).isoformat()
        self._state.last_entry_utc = now
        self._state.last_entry_utc_by_tf[tf] = now
        self._save()

    def check_entry_allowed(
        self,
        *,
        timeframe: str,
        max_trades_per_day: int,
        cooldown_bars: int,
        equity: float,
        initial_balance: float,
        max_daily_loss_pct: float,
        config: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        self._reset_day_if_needed(equity)
        tf = _norm_tf(timeframe)

        if self._state.pause_until_utc:
            try:
                until = datetime.fromisoformat(self._state.pause_until_utc)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) < until:
                    return False, "cooldown after consecutive losses"
                self._state.pause_until_utc = ""
            except ValueError:
                self._state.pause_until_utc = ""

        trades_tf = int(self._state.trades_today_by_tf.get(tf, 0))
        if max_trades_per_day > 0 and trades_tf >= max_trades_per_day:
            return False, f"max trades per day ({tf})"

        last_str = self._state.last_entry_utc_by_tf.get(tf) or self._state.last_entry_utc
        if cooldown_bars > 0 and last_str:
            try:
                last = datetime.fromisoformat(last_str)
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                bar_min = _BAR_MINUTES.get(tf, 15)
                need = timedelta(minutes=cooldown_bars * bar_min)
                if datetime.now(timezone.utc) - last < need:
                    return False, f"entry cooldown ({tf})"
            except ValueError:
                pass

        ref_equity = self._state.day_start_equity if self._state.day_start_equity > 0 else equity
        if ref_equity <= 0 and initial_balance > 0:
            ref_equity = initial_balance
        from tradingbot.ml.research.phase22c.config import compute_daily_loss_budget, load_phase22c_config

        cfg22 = load_phase22c_config()
        risk_pct = float((config or {}).get("RISK_PER_TRADE", (config or {}).get("risk_per_trade", 0.01)))
        max_loss = compute_daily_loss_budget(
            reference_balance=ref_equity,
            max_daily_loss_pct=max_daily_loss_pct,
            risk_per_trade=risk_pct,
            floor_trades=cfg22.daily_loss_floor_trades if cfg22.enabled else 1,
        )
        if ref_equity > 0 and self._state.daily_pnl <= -max_loss:
            return False, "daily loss limit"

        return True, "ok"

    @property
    def consecutive_losses(self) -> int:
        return int(self._state.consecutive_losses)

    def activate_loss_streak_position_cap(self, *, m5_bars: int = 12) -> None:
        """Reduce max concurrent positions for the next N M5 bars after a loss streak."""
        now = datetime.now(timezone.utc)
        until = now + timedelta(minutes=int(m5_bars) * 5)
        self._state.position_cap_until_utc = until.isoformat()
        self._save()

    def loss_streak_position_cap_active(self) -> bool:
        raw = self._state.position_cap_until_utc
        if not raw:
            return False
        try:
            until = datetime.fromisoformat(raw)
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < until:
                return True
            self._state.position_cap_until_utc = ""
            self._save()
        except ValueError:
            self._state.position_cap_until_utc = ""
            self._save()
        return False

    def to_risk_state(self, leverage: float = 0.0):
        from tradingbot.domain import risk_logic

        daily_loss = 0.0
        if self._state.day_start_equity > 0 and self._state.daily_pnl < 0:
            daily_loss = abs(self._state.daily_pnl) / self._state.day_start_equity
        return risk_logic.RiskState(
            daily_loss=daily_loss,
            consecutive_losses=self._state.consecutive_losses,
            leverage=leverage,
        )
