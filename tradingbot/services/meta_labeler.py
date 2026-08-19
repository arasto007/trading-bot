"""Meta-Labeler — per TF با gate تطبیقی (رژیم + عملکرد live)."""

from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path
from typing import Any

from tradingbot.domain.models import TradingSignal
from tradingbot.ml.features.unified_feature_store import FEATURES, UnifiedFeatureStore

FEATURE_NAMES = FEATURES

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models"

_TF_FILES = {
    "M5": MODEL_DIR / "meta_labeler_m5.pkl",
    "M15": MODEL_DIR / "meta_labeler_m15.pkl",
    "H4": MODEL_DIR / "meta_labeler_h4.pkl",
}
_INFO_PATH = MODEL_DIR / "meta_labeler_info.json"
_LEGACY_PATH = MODEL_DIR / "meta_labeler.pkl"

# در این رژیم‌ها meta غیرفعال — فیلتر ریسک و سایز پوزیشن کافی است
META_SKIP_REGIMES = frozenset({"CRISIS", "VOLATILE"})
MIN_LIVE_CLOSED_FOR_STATS = 5
MIN_LIVE_WIN_RATE_PCT = 35.0


def _norm_tf(tf: str) -> str:
    t = (tf or "M15").upper()
    return {"5M": "M5", "15M": "M15", "4H": "H4"}.get(t, t)


class MetaLabeler:
    def __init__(self) -> None:
        self._models: dict[str, Any] = {}
        self._features: dict[str, list[str]] = {}
        self._info: dict[str, Any] = {}
        self._load_all()

    def _load_all(self) -> None:
        if _INFO_PATH.is_file():
            try:
                self._info = json.loads(_INFO_PATH.read_text(encoding="utf-8"))
            except Exception:
                self._info = {}

        for tf, path in _TF_FILES.items():
            if not path.is_file():
                continue
            try:
                with path.open("rb") as f:
                    payload = pickle.load(f)
                self._models[tf] = payload.get("model")
                self._features[tf] = list(payload.get("features", FEATURE_NAMES))
            except Exception as e:
                logger.warning("Meta load %s failed: %s", tf, e)

        if not self._models and _LEGACY_PATH.is_file():
            try:
                with _LEGACY_PATH.open("rb") as f:
                    payload = pickle.load(f)
                for tf in ("M5", "M15", "H4"):
                    self._models[tf] = payload.get("model")
                    self._features[tf] = list(payload.get("features", FEATURE_NAMES))
            except Exception:
                pass

    def _tf_info(self, timeframe: str) -> dict[str, Any]:
        tf = _norm_tf(timeframe)
        return (self._info.get("per_tf") or {}).get(tf, {})

    def is_ready_for(self, timeframe: str) -> bool:
        tf = _norm_tf(timeframe)
        if tf not in self._models or not self._features.get(tf):
            return False
        tf_info = self._tf_info(timeframe)
        oos = tf_info.get("oos") or {}
        if oos:
            return bool(oos.get("passed_gate", False))
        prec = float(tf_info.get("precision", 0) or 0)
        acc = float(tf_info.get("accuracy", 0) or 0)
        samples = int(tf_info.get("samples", 0) or 0)
        return samples >= 20 and prec >= 0.30 and acc >= 0.52

    def _live_performance_ok(self) -> bool:
        try:
            from tradingbot.services.meta_decision_log import recent_stats

            stats = recent_stats()
            closed = int(stats.get("closed_trades", 0) or 0)
            wr = stats.get("live_win_rate_pct")
            if closed < MIN_LIVE_CLOSED_FOR_STATS or wr is None:
                return True
            return float(wr) >= MIN_LIVE_WIN_RATE_PCT
        except Exception:
            return True

    def should_gate(self, timeframe: str, regime: str) -> bool:
        """آیا meta برای این TF و رژیم فعال شود؟"""
        if not self.is_ready_for(timeframe):
            return False
        r = (regime or "RANGING").upper()
        if r in META_SKIP_REGIMES:
            return False
        if not self._live_performance_ok():
            logger.info("Meta gate off — live win rate below %.0f%%", MIN_LIVE_WIN_RATE_PCT)
            return False
        return True

    def effective_threshold(
        self,
        timeframe: str,
        regime: str,
        base_threshold: float,
    ) -> float:
        """آستانه تطبیقی: روند = نرم‌تر، رنج = سخت‌تر."""
        calibrated = self.calibrated_threshold(timeframe)
        th = float(calibrated if calibrated is not None else base_threshold)
        r = (regime or "RANGING").upper()
        if r in ("STRONG_TREND_UP", "STRONG_TREND_DOWN"):
            return max(0.25, th - 0.05)
        if r == "RANGING":
            return min(0.55, th + 0.03)
        if r == "VOLATILE":
            return min(0.60, th + 0.08)
        return th

    def calibrated_threshold(self, timeframe: str) -> float | None:
        oos = self._tf_info(timeframe).get("oos") or {}
        th = oos.get("best_threshold")
        if th is not None:
            return float(th)
        return None

    @property
    def is_ready(self) -> bool:
        return any(self.is_ready_for(tf) for tf in ("M5", "M15", "H4"))

    def build_features(
        self,
        signal: TradingSignal,
        snapshot: dict[str, Any],
        regime: str,
        *,
        spread_pips: float = 0.0,
    ) -> dict[str, float]:
        return UnifiedFeatureStore.build_live(
            signal,
            snapshot,
            regime,
            spread_pips=spread_pips,
        )

    def score(
        self,
        signal: TradingSignal,
        snapshot: dict[str, Any],
        regime: str = "RANGING",
        *,
        spread_pips: float = 0.0,
    ) -> float:
        tf = _norm_tf(signal.timeframe)
        if not self.is_ready_for(tf):
            return 1.0
        model = self._models[tf]
        names = self._features[tf]
        feats = self.build_features(signal, snapshot, regime, spread_pips=spread_pips)
        if list(names) == list(FEATURES):
            row = UnifiedFeatureStore.to_vector(feats)
        else:
            row = [float(feats.get(name, 0.0)) for name in names]
        try:
            proba = model.predict_proba([row])[0]
            return float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception as e:
            logger.debug("Meta score %s error: %s", tf, e)
            return 1.0

    def info(self) -> dict[str, Any]:
        return dict(self._info)


_instance: MetaLabeler | None = None


def get_meta_labeler() -> MetaLabeler:
    global _instance
    if _instance is None:
        _instance = MetaLabeler()
    return _instance


def reload_meta_labeler() -> MetaLabeler:
    global _instance
    _instance = MetaLabeler()
    return _instance
