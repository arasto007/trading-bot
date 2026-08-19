"""Trading threshold optimization — maximize expected R with risk proxies."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.models.dataset_loader import load_dataset_splits
from tradingbot.ml.models.evaluator import expected_r_from_proba
from tradingbot.ml.models.training import load_model
from tradingbot.ml.validation._utils import write_json_report

DEFAULT_THRESHOLDS = (0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)


@dataclass
class ThresholdResult:
    threshold: float
    expected_R: float
    winrate: float
    signals: int
    max_drawdown_proxy: float
    score: float


@dataclass
class ThresholdOptimizer:
    model: str
    symbol: str
    timeframe: str
    split: str
    candidates: list[ThresholdResult] = field(default_factory=list)
    best_threshold: float = 0.5
    expected_R: float = 0.0
    winrate: float = 0.0
    signals: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "split": self.split,
            "best_threshold": self.best_threshold,
            "expected_R": self.expected_R,
            "winrate": self.winrate,
            "signals": self.signals,
            "candidates": [asdict(c) for c in self.candidates],
        }


def _max_drawdown_proxy(returns: np.ndarray) -> float:
    """Peak-to-trough drawdown on sequential R-multiples."""
    if len(returns) == 0:
        return 0.0
    equity = np.cumsum(returns)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    return round(float(drawdown.max()), 4)


def _trade_returns(y_true: np.ndarray, take_mask: np.ndarray) -> np.ndarray:
    """Realized R per taken trade: TP=+2R, SL=-1R."""
    labels = y_true[take_mask]
    return np.where(labels == 1, 2.0, -1.0)


def _score_candidate(
    expected_r: float,
    winrate: float,
    signals: int,
    max_dd: float,
    *,
    min_signals: int = 5,
) -> float:
    """Composite score favoring expected R, win rate, frequency, low drawdown."""
    if signals < min_signals:
        return -1e9
    freq_bonus = min(1.0, signals / 100.0)
    dd_penalty = max_dd / 10.0
    return expected_r * 0.5 + winrate * 0.25 + freq_bonus * 0.15 - dd_penalty * 0.10


def optimize_threshold(
    symbol: str,
    timeframe: str,
    model_name: str,
    *,
    base_dir: str | Path | None = None,
    split: str = "validation",
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    save: bool = True,
) -> ThresholdOptimizer:
    splits = load_dataset_splits(symbol, timeframe, base_dir)
    split_map = {
        "train": (splits.X_train, splits.y_train),
        "validation": (splits.X_val, splits.y_val),
        "test": (splits.X_test, splits.y_test),
    }
    X, y = split_map[split]
    if X.empty:
        raise ValueError(f"Split '{split}' is empty")

    model = load_model(model_name, base_dir)
    proba = model.predict_proba(X)
    y_true = np.asarray(y).astype(int)
    exp_r_all = expected_r_from_proba(proba)

    candidates: list[ThresholdResult] = []
    best: ThresholdResult | None = None

    for thr in thresholds:
        take = proba[:, 1] >= thr
        signals = int(take.sum())
        if signals == 0:
            candidates.append(
                ThresholdResult(thr, 0.0, 0.0, 0, 0.0, -1e9)
            )
            continue

        returns = _trade_returns(y_true, take)
        realized_exp_r = float(returns.mean())
        winrate = float((y_true[take] == 1).mean())
        avg_pred_exp_r = float(exp_r_all[take].mean())
        max_dd = _max_drawdown_proxy(returns)
        score = _score_candidate(avg_pred_exp_r, winrate, signals, max_dd)

        result = ThresholdResult(
            threshold=thr,
            expected_R=round(avg_pred_exp_r, 4),
            winrate=round(winrate, 4),
            signals=signals,
            max_drawdown_proxy=max_dd,
            score=round(score, 4),
        )
        candidates.append(result)
        if best is None or result.score > best.score:
            best = result

    if best is None:
        best = ThresholdResult(0.5, 0.0, 0.0, 0, 0.0, 0.0)

    optimizer = ThresholdOptimizer(
        model=model_name.lower(),
        symbol=symbol.upper(),
        timeframe=timeframe.upper(),
        split=split,
        candidates=candidates,
        best_threshold=best.threshold,
        expected_R=best.expected_R,
        winrate=best.winrate,
        signals=best.signals,
    )

    if save:
        payload = {
            "model": optimizer.model,
            "best_threshold": optimizer.best_threshold,
            "expected_R": optimizer.expected_R,
            "winrate": optimizer.winrate,
            "signals": optimizer.signals,
        }
        write_json_report(reports_dir(base_dir) / "optimal_threshold.json", payload)

    return optimizer
