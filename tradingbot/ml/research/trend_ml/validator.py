"""Phase 13.4 — walk-forward trend ML validation (research only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.research.phase11_5._metrics import trade_metrics
from tradingbot.ml.research.regime_detector.regime_validator import build_expanding_windows
from tradingbot.ml.research.trend_ml.feature_builder import TREND_ML_FEATURE_COLUMNS
from tradingbot.ml.research.trend_ml.models import create_trend_ml_model
from tradingbot.ml.research.trend_ml.trend_ml_filter import DEFAULT_THRESHOLD

DEFAULT_RR = 2.0


def _year_mask(ts: pd.Series, start: int, end: int) -> np.ndarray:
    years = pd.to_datetime(ts, utc=True).dt.year
    return ((years >= start) & (years <= end)).to_numpy()


def _split_window(df: pd.DataFrame, window: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    if "train_end" in window:
        ordered = df.sort_values("timestamp").reset_index(drop=True)
        return ordered.iloc[: window["train_end"]], ordered.iloc[window["train_end"] :]

    ts = df["timestamp"]
    tr_s, tr_e = window["train_years"]
    te_s, te_e = window["test_years"]
    train = df.loc[_year_mask(ts, tr_s, tr_e)]
    test = df.loc[_year_mask(ts, te_s, te_e)]
    return train, test


def _safe_auc(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return 0.5
    return float(roc_auc_score(y_true, y_prob))


def _filtered_trade_metrics(test: pd.DataFrame, probs: np.ndarray, *, threshold: float) -> dict[str, Any]:
    allowed = probs >= threshold
    if not allowed.any():
        return trade_metrics([])

    trades: list[dict[str, Any]] = []
    for idx, row in test.loc[allowed].iterrows():
        label = int(row["successful_trade"])
        r_mult = DEFAULT_RR if label == 1 else -1.0
        trades.append({"pnl": r_mult, "R_multiple": r_mult, "successful_trade": label})
    return trade_metrics(trades)


def _robustness_score(window_metrics: list[dict[str, Any]]) -> float:
    if not window_metrics:
        return 0.0
    aucs = [float(w.get("test_roc_auc", 0.5)) for w in window_metrics]
    pfs = [float(w.get("profit_factor", 0.0)) for w in window_metrics]
    auc_std = float(np.std(aucs)) if len(aucs) > 1 else 0.0
    pf_std = float(np.std(pfs)) if len(pfs) > 1 else 0.0
    return round(max(0.0, 1.0 - auc_std) * 0.6 + max(0.0, 1.0 - pf_std) * 0.4, 4)


def walk_forward_validate(
    samples: pd.DataFrame,
    *,
    model_name: str = "logistic",
    seed: int = 42,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    """Expanding windows 2021-2026; scaler fit on train only; no shuffle."""
    work = samples.sort_values("timestamp").reset_index(drop=True)
    cols = [c for c in TREND_ML_FEATURE_COLUMNS if c in work.columns]
    windows_out: list[dict[str, Any]] = []

    for window in build_expanding_windows(work):
        train, test = _split_window(work, window)
        if len(train) < 40 or len(test) < 15:
            windows_out.append({"window_id": window["window_id"], "skipped": True})
            continue

        X_tr = train[cols].astype(np.float64)
        y_tr = train["successful_trade"].astype(int).values
        X_te = test[cols].astype(np.float64)
        y_te = test["successful_trade"].astype(int).values

        scaler = StandardScaler()
        X_tr_s = pd.DataFrame(scaler.fit_transform(X_tr), columns=cols)
        X_te_s = pd.DataFrame(scaler.transform(X_te), columns=cols)

        model = create_trend_ml_model(model_name, seed=seed)
        model.fit(X_tr_s, y_tr)

        tr_prob = model.predict_proba(X_tr_s)[:, 1]
        te_prob = model.predict_proba(X_te_s)[:, 1]
        train_auc = _safe_auc(y_tr, tr_prob)
        test_auc = _safe_auc(y_te, te_prob)
        auc_gap = round(train_auc - test_auc, 4)

        filtered = _filtered_trade_metrics(test, te_prob, threshold=threshold)
        win_rate = filtered["win_rate"]
        pf = filtered["profit_factor"]
        expectancy = filtered["expectancy_r"]

        windows_out.append(
            {
                "window_id": window["window_id"],
                "train_rows": len(train),
                "test_rows": len(test),
                "train_roc_auc": round(train_auc, 4),
                "test_roc_auc": round(test_auc, 4),
                "auc_gap": auc_gap,
                "win_rate": win_rate,
                "profit_factor": pf,
                "expectancy_r": expectancy,
                "filtered_trades": filtered["trades"],
                "threshold": threshold,
                "shuffle": False,
            }
        )

    active = [w for w in windows_out if not w.get("skipped")]
    mean_auc = round(float(np.mean([w["test_roc_auc"] for w in active])), 4) if active else 0.0
    mean_gap = round(float(np.mean([w["auc_gap"] for w in active])), 4) if active else 0.0
    mean_pf = round(float(np.mean([w["profit_factor"] for w in active])), 4) if active else 0.0
    mean_exp = round(float(np.mean([w["expectancy_r"] for w in active])), 4) if active else 0.0
    mean_wr = round(float(np.mean([w["win_rate"] for w in active])), 4) if active else 0.0

    return {
        "model": model_name,
        "windows": windows_out,
        "mean_test_roc_auc": mean_auc,
        "mean_auc_gap": mean_gap,
        "mean_profit_factor": mean_pf,
        "mean_expectancy_r": mean_exp,
        "mean_win_rate": mean_wr,
        "robustness_score": _robustness_score(active),
        "chronological": True,
        "shuffle": False,
        "scaler_fit": "train_only",
        "threshold": threshold,
    }
