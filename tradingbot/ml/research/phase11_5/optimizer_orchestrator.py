"""Phase 11.5 — research orchestrator (read-only, no execution changes)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    paper_trading_cycles_path,
    paper_trading_final_report_path,
    paper_trading_trades_path,
    phase9_9_metadata_path,
    phase9_9_model_path,
    phase9_9_scaler_path,
)
from tradingbot.ml.research.phase11_5.model_comparator import compare_models
from tradingbot.ml.research.phase11_5.regime_analysis import analyze_regimes
from tradingbot.ml.research.phase11_5.report_generator import (
    build_final_report,
    write_final_report,
    write_model_comparison_report,
    write_monte_carlo_report,
    write_regime_report,
    write_risk_report,
    write_sell_bias_report,
    write_session_report,
    write_threshold_report,
)
from tradingbot.ml.research.phase11_5.risk_optimizer import optimize_risk
from tradingbot.ml.research.phase11_5.robustness_check import run_robustness_check
from tradingbot.ml.research.phase11_5.sell_bias_analyzer import analyze_sell_bias
from tradingbot.ml.research.phase11_5.session_optimizer import optimize_sessions
from tradingbot.ml.research.phase11_5.threshold_optimizer import optimize_thresholds


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _load_json_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def verify_safety(*, base_dir: str | Path | None = None, paper_run_id: str) -> dict[str, Any]:
    meta = _load_json_dict(phase9_9_metadata_path(base_dir))
    paper = _load_json_dict(paper_trading_final_report_path(paper_run_id, base_dir))
    model_val = paper.get("model_validation", {})
    return {
        "phase9_9_model_checksum": _sha256(phase9_9_model_path(base_dir)),
        "phase9_9_scaler_checksum": _sha256(phase9_9_scaler_path(base_dir)),
        "expected_model_checksum": model_val.get("model_checksum"),
        "expected_scaler_checksum": model_val.get("scaler_checksum"),
        "checksums_match_paper_run": (
            _sha256(phase9_9_model_path(base_dir)) == model_val.get("model_checksum")
            and _sha256(phase9_9_scaler_path(base_dir)) == model_val.get("scaler_checksum")
        ),
        "dataset_fingerprint": meta.get("dataset_fingerprint"),
        "dataset_fingerprint_unchanged": meta.get("dataset_fingerprint")
        == model_val.get("dataset_fingerprint"),
        "artifacts_readonly": True,
        "execution_layer_touched": False,
    }


@dataclass
class Phase115Result:
    decision: str
    reports: dict[str, str] = field(default_factory=dict)
    final_report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reports": self.reports,
            "final_report": self.final_report,
        }


def run_phase11_5_analysis(
    *,
    symbol: str = "XAUUSD",
    timeframe: str = "M5",
    paper_run_id: str = "phase11_v1",
    base_dir: str | Path | None = None,
    bootstrap_iterations: int = 1000,
) -> Phase115Result:
    trades = _load_json_list(paper_trading_trades_path(paper_run_id, base_dir))
    cycles = _load_json_list(paper_trading_cycles_path(paper_run_id, base_dir))
    paper_final = _load_json_dict(paper_trading_final_report_path(paper_run_id, base_dir))
    safety = verify_safety(base_dir=base_dir, paper_run_id=paper_run_id)

    threshold = optimize_thresholds(trades, cycles)
    sell_bias = analyze_sell_bias(trades, cycles)
    session = optimize_sessions(trades)
    regime = analyze_regimes(trades)
    risk = optimize_risk(trades)
    model_comparison = compare_models(paper_run_id=paper_run_id, base_dir=base_dir)
    robustness = run_robustness_check(trades, iterations=bootstrap_iterations)

    reports: dict[str, str] = {}
    reports["threshold"] = str(write_threshold_report(threshold, base_dir))
    reports["sell_bias"] = str(write_sell_bias_report(sell_bias, base_dir))
    reports["session"] = str(write_session_report(session, base_dir))
    reports["regime"] = str(write_regime_report(regime, base_dir))
    reports["risk"] = str(write_risk_report(risk, base_dir))
    reports["model_comparison"] = str(write_model_comparison_report(model_comparison, base_dir))
    reports["monte_carlo"] = str(write_monte_carlo_report(robustness, base_dir))

    final = build_final_report(
        symbol=symbol,
        timeframe=timeframe,
        run_id=paper_run_id,
        threshold=threshold,
        sell_bias=sell_bias,
        session=session,
        regime=regime,
        risk=risk,
        model_comparison=model_comparison,
        robustness=robustness,
        paper_final=paper_final,
        safety=safety,
    )
    reports["final"] = str(write_final_report(final, base_dir))

    return Phase115Result(
        decision=final["decision"],
        reports=reports,
        final_report=final,
    )
