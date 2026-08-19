"""Phase 9.8 — per-window train/validate evaluation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.preprocessing import StandardScaler

from tradingbot.ml.backtest.broker_sim import BrokerConfig, SimulatedBroker
from tradingbot.ml.backtest.risk import RiskConfig, RiskManager
from tradingbot.ml.backtest.strategy import StrategyConfig, ThresholdStrategy
from tradingbot.ml.backtest.state import SignalAction
from tradingbot.ml.research.regime_optimization.regime_utils import assign_market_regime, apply_event_filter
from tradingbot.ml.research.retrain_optimizer import create_research_model
from tradingbot.ml.research.walk_forward.window_manager import WalkForwardWindow, assert_no_overlap
from tradingbot.ml.training.model_factory import DEFAULT_SEED

FIXED_STRATEGY = StrategyConfig(buy_threshold=0.55, sell_threshold=0.45)
FIXED_RISK = RiskConfig(risk_pct=0.005, tp_r_multiple=2.0, sl_r_multiple=1.0, max_open_trades=1)
FIXED_BROKER = BrokerConfig(spread_points=0.30, slippage_points=0.10, commission_per_trade=0.0)
INITIAL_EQUITY = 10_000.0


def apply_phase97_filters(
    df: pd.DataFrame,
    *,
    regime: str = "RANGE",
    event_scheme: str = "A_all_events",
) -> pd.DataFrame:
    work = df.copy()
    work["market_regime"] = assign_market_regime(work)
    work = work.loc[work["market_regime"] == regime]
    return apply_event_filter(work, event_scheme).sort_values("timestamp").reset_index(drop=True)


def _ml_metrics(y_true: np.ndarray, y_pred: np.ndarray, proba: np.ndarray) -> dict[str, float]:
    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)
    out: dict[str, float] = {
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": 0.0,
    }
    if len(np.unique(y_true)) > 1:
        out["roc_auc"] = round(float(roc_auc_score(y_true, proba[:, 1])), 4)
    return out


def _simulate_trades(val_df: pd.DataFrame, proba: np.ndarray) -> dict[str, float]:
    """Fixed-threshold trade simulation on validation rows (no tuning)."""
    strategy = ThresholdStrategy(FIXED_STRATEGY)
    risk_mgr = RiskManager(FIXED_RISK)
    broker = SimulatedBroker(FIXED_BROKER)

    equity = INITIAL_EQUITY
    peak = equity
    max_dd = 0.0
    pnls: list[float] = []
    pnl_r: list[float] = []
    open_count = 0

    for idx, (_, row) in enumerate(val_df.iterrows()):
        prob_tp = float(proba[idx, 1]) if proba.ndim == 2 else float(proba[idx])
        signal = strategy.generate_signal(prob_tp)
        if not strategy.should_trade(signal) or open_count >= FIXED_RISK.max_open_trades:
            continue

        event_dir = int(row.get("direction", 1))
        trade_dir = strategy.trade_direction(signal, event_dir)
        if trade_dir == 0:
            continue

        risk_unit = float(row.get("risk_unit", 0.0))
        if risk_unit <= 0:
            risk_unit = abs(float(row["entry_price"]) - float(row["stop_loss"]))
        atr = float(row.get("atr_14", 0.0) or 0.0)
        if risk_unit <= 0 and atr <= 0:
            continue

        position = risk_mgr.compute_position(equity, risk_unit, atr=atr if atr > 0 else None)
        costs = broker.execution_cost_r(risk_unit, position.risk_amount)
        label = int(row["label"])
        pnl, r = risk_mgr.pnl_from_label(label, position.risk_amount, costs=costs)
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak > 0 else 0.0)
        pnls.append(pnl)
        pnl_r.append(r)
        open_count = 0

    if not pnls:
        return {
            "num_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
            "sharpe_proxy": 0.0,
            "net_profit": 0.0,
        }

    arr = np.array(pnls, dtype=np.float64)
    r_arr = np.array(pnl_r, dtype=np.float64)
    wins = arr > 0
    gross_profit = float(arr[wins].sum()) if wins.any() else 0.0
    gross_loss = float(-arr[~wins].sum()) if (~wins).any() else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
    std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
    sharpe = float(np.mean(arr) / std * np.sqrt(len(arr))) if std > 1e-12 else 0.0

    return {
        "num_trades": len(pnls),
        "win_rate": round(float(wins.mean()), 4),
        "profit_factor": round(pf, 4),
        "expectancy": round(float(r_arr.mean()), 4),
        "max_drawdown": round(max_dd, 4),
        "total_return": round((equity - INITIAL_EQUITY) / INITIAL_EQUITY, 4),
        "sharpe_proxy": round(sharpe, 4),
        "net_profit": round(equity - INITIAL_EQUITY, 4),
    }


def validate_window(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    window: WalkForwardWindow,
    *,
    feature_cols: list[str],
    model_name: str,
    hyperparameters: dict[str, Any],
    seed: int = DEFAULT_SEED,
    regime: str = "RANGE",
    event_scheme: str = "A_all_events",
) -> dict[str, Any]:
    """Train on train window only; evaluate ML + trading on validation."""
    assert_no_overlap(train_df, val_df)
    train_f = apply_phase97_filters(train_df, regime=regime, event_scheme=event_scheme)
    val_f = apply_phase97_filters(val_df, regime=regime, event_scheme=event_scheme)

    if len(train_f) < 20 or len(val_f) < 5:
        return {
            "window_id": window.window_id,
            "skipped": True,
            "reason": "insufficient_rows_after_filter",
            "train_rows": len(train_f),
            "validation_rows": len(val_f),
        }

    cols = [c for c in feature_cols if c in train_f.columns and c in val_f.columns]
    if not cols:
        return {"window_id": window.window_id, "skipped": True, "reason": "no_features"}

    scaler = StandardScaler()
    X_tr = train_f.loc[:, cols].astype(np.float64).values
    y_tr = train_f["label"].astype(int).to_numpy()
    scaler.fit(X_tr)

    X_va = scaler.transform(val_f.loc[:, cols].astype(np.float64).values)
    y_va = val_f["label"].astype(int).to_numpy()

    model = create_research_model(model_name, seed, hyperparameters)
    model.fit(scaler.transform(X_tr), y_tr)

    train_proba = model.predict_proba(scaler.transform(X_tr))
    train_pred = model.predict(scaler.transform(X_tr))
    train_ml = _ml_metrics(y_tr, train_pred, train_proba)

    val_proba = model.predict_proba(X_va)
    val_pred = model.predict(X_va)
    val_ml = _ml_metrics(y_va, val_pred, val_proba)
    trading = _simulate_trades(val_f.reset_index(drop=True), val_proba)

    train_val_gap = round(train_ml["roc_auc"] - val_ml["roc_auc"], 4)
    performance_degradation = 0.0
    if train_ml["roc_auc"] > 0:
        performance_degradation = round(max(0.0, train_val_gap / train_ml["roc_auc"]), 4)

    return {
        "window_id": window.window_id,
        "skipped": False,
        "train_start": window.train_start,
        "train_end": window.train_end,
        "validation_start": window.validation_start,
        "validation_end": window.validation_end,
        "train_rows": len(train_f),
        "validation_rows": len(val_f),
        "shuffle": False,
        "scaler_fit_on": "train_only",
        **val_ml,
        **trading,
        "train_roc_auc": train_ml["roc_auc"],
        "train_val_auc_gap": train_val_gap,
        "performance_degradation": performance_degradation,
    }
