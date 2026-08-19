"""Phase 9.5 — advanced discovery orchestrator."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.data.paths import (
    advanced_label_research_path,
    feature_discovery_report_path,
    phase9_5_discovery_report_path,
    signal_mining_report_path,
)
from tradingbot.ml.data.stores import CandleStore
from tradingbot.ml.dataset.store import DatasetStore
from tradingbot.ml.research.advanced_discovery.experimental_features import (
    audit_experimental_features,
    compute_experimental_features,
)
from tradingbot.ml.research.advanced_discovery.feature_discovery import (
    run_feature_discovery,
    save_feature_discovery_report,
)
from tradingbot.ml.research.advanced_discovery.label_discovery import (
    run_label_discovery,
    save_advanced_label_research,
)
from tradingbot.ml.research.advanced_discovery.model_discovery import run_model_discovery
from tradingbot.ml.research.advanced_discovery.signal_mining import (
    run_signal_mining,
    save_signal_mining_report,
)
from tradingbot.ml.research.research_utils import dataset_content_fingerprint
from tradingbot.ml.training.data_loader import filter_resolved_labels, load_dataset_v2_splits
from tradingbot.ml.training.model_factory import DEFAULT_SEED

logger = logging.getLogger(__name__)

PHASE = "9.5"
BACKTEST_READY_VAL_AUC = 0.55
BACKTEST_READY_TEST_AUC = 0.52


@dataclass
class DiscoveryRunResult:
    symbol: str
    timeframe: str
    status: str
    recommendation: str
    report_path: str
    leakage_status: str
    beats_phase9_4: bool = False
    blocked: bool = False
    block_reason: str = ""
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "recommendation": self.recommendation,
            "report_path": self.report_path,
            "leakage_status": self.leakage_status,
            "beats_phase9_4": self.beats_phase9_4,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "summary": self.summary,
        }


class AdvancedDiscoveryRunner:
    """Phase 9.5 research orchestrator — isolated experiments only."""

    def __init__(self, *, base_dir: str | Path | None = None, seed: int = DEFAULT_SEED) -> None:
        self.base_dir = base_dir
        self.seed = seed

    def run(self, symbol: str, timeframe: str) -> DiscoveryRunResult:
        symbol = symbol.upper()
        timeframe = timeframe.upper()

        store = DatasetStore(self.base_dir)
        raw = store.load_v2(symbol, timeframe)
        if raw is None or raw.empty:
            return self._blocked(symbol, timeframe, "dataset_v2_missing")

        fingerprint_before = dataset_content_fingerprint(raw)
        resolved = filter_resolved_labels(raw)

        logger.info("Phase 9.5: feature discovery")
        splits = load_dataset_v2_splits(symbol, timeframe, self.base_dir)
        feature_report = run_feature_discovery(splits, seed=self.seed)
        save_feature_discovery_report(splits, self.base_dir, seed=self.seed)

        logger.info("Phase 9.5: signal mining")
        signal_report = run_signal_mining(resolved)
        save_signal_mining_report(resolved, self.base_dir)

        logger.info("Phase 9.5: experimental features")
        enriched = compute_experimental_features(resolved)
        leakage = audit_experimental_features(enriched)

        logger.info("Phase 9.5: label discovery")
        label_report = run_label_discovery(raw, symbol, timeframe, self.base_dir)
        save_advanced_label_research(raw, symbol, timeframe, self.base_dir)

        candles = CandleStore(self.base_dir).load(symbol, timeframe)
        best_label = label_report.get("best_configuration")
        best_event = signal_report.get("best_event")

        logger.info("Phase 9.5: model discovery")
        model_report = run_model_discovery(
            raw,
            symbol,
            timeframe,
            candles=candles,
            top_features=feature_report.get("top_features", []),
            best_label=best_label,
            best_event=best_event,
            base_dir=self.base_dir,
            seed=self.seed,
        )

        raw_after = store.load_v2(symbol, timeframe)
        fingerprint_after = dataset_content_fingerprint(raw_after) if raw_after is not None else ""
        if fingerprint_before != fingerprint_after:
            return self._blocked(symbol, timeframe, "dataset_v2_mutated")

        val_auc = float(model_report.get("validation_roc_auc", 0.0))
        test_auc = float(model_report.get("test_roc_auc", 0.0))
        beats_94 = bool(model_report.get("beats_phase9_4", False))
        recommendation = _build_recommendation(val_auc, test_auc, leakage.get("status", "fail"), beats_94)

        final_report = {
            "phase": PHASE,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "seed": self.seed,
            "status": "PASS" if leakage.get("status") == "pass" else "WARN",
            "recommendation": recommendation,
            "dataset": {
                "fingerprint": fingerprint_before,
                "fingerprint_unchanged": fingerprint_before == fingerprint_after,
                "rows": len(raw),
                "resolved_rows": len(resolved),
                "registry_features": len(feature_report.get("rankings", [])),
                "experimental_features": len(enriched.columns),
            },
            "leakage_audit": leakage,
            "feature_findings": {
                "top_features": feature_report.get("top_features", []),
                "useless_features": feature_report.get("useless_features", []),
                "unstable_features": feature_report.get("unstable_features", []),
                "test_roc_auc_diagnosis": feature_report.get("test_roc_auc_diagnosis", []),
            },
            "signal_findings": {
                "best_events": signal_report.get("ranked_by_expectancy", [])[:3],
                "worst_events": [signal_report.get("worst_event")],
                "by_event_type": signal_report.get("by_event_type", []),
            },
            "label_findings": {
                "best_configuration": best_label,
                "experiment_count": label_report.get("experiment_count", 0),
            },
            "model_findings": {
                "best_model": model_report.get("best_candidate", {}).get("model_name"),
                "best_configuration": model_report.get("best_candidate", {}).get("variant_id"),
                "validation_roc_auc": val_auc,
                "test_roc_auc": test_auc,
                "beats_phase9_2": model_report.get("beats_phase9_2"),
                "beats_phase9_4": beats_94,
                "comparison_table": model_report.get("comparison_table", []),
                "experiments": model_report.get("experiments", []),
            },
            "comparison_with_previous_phases": {
                "phase9_2_val_roc_auc": model_report.get("baseline_phase9_2_val_roc_auc"),
                "phase9_4_val_roc_auc": model_report.get("baseline_phase9_4_val_roc_auc"),
            },
            "artifacts": {
                "feature_discovery": str(feature_discovery_report_path(self.base_dir)),
                "signal_mining": str(signal_mining_report_path(self.base_dir)),
                "advanced_label_research": str(advanced_label_research_path(self.base_dir)),
            },
        }

        report_path = phase9_5_discovery_report_path(self.base_dir)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(final_report, indent=2, ensure_ascii=False), encoding="utf-8")

        return DiscoveryRunResult(
            symbol=symbol,
            timeframe=timeframe,
            status=final_report["status"],
            recommendation=recommendation,
            report_path=str(report_path),
            leakage_status=str(leakage.get("status", "unknown")),
            beats_phase9_4=beats_94,
            summary={
                "validation_roc_auc": val_auc,
                "test_roc_auc": test_auc,
                "best_event": best_event,
                "best_label": best_label,
            },
        )

    def _blocked(self, symbol: str, timeframe: str, reason: str) -> DiscoveryRunResult:
        logger.warning("Phase 9.5 blocked: %s", reason)
        return DiscoveryRunResult(
            symbol=symbol,
            timeframe=timeframe,
            status="FAIL",
            recommendation="More feature/data research required",
            report_path="",
            leakage_status="unknown",
            blocked=True,
            block_reason=reason,
        )


def _build_recommendation(
    val_auc: float,
    test_auc: float,
    leakage_status: str,
    beats_phase9_4: bool,
) -> str:
    if leakage_status != "pass":
        return "More feature/data research required"
    if val_auc >= BACKTEST_READY_VAL_AUC and test_auc >= BACKTEST_READY_TEST_AUC and beats_phase9_4:
        return "Signal quality sufficient for backtesting"
    return "More feature/data research required"
