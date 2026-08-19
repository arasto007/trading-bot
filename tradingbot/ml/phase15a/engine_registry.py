"""Phase 15A — production engine registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import pandas as pd

from tradingbot.ml.decision_engine.decision_policy import RANGE_MODEL_ID, TREND_MODEL_ID
from tradingbot.ml.paper_trading.model_registry import load_phase9_9_bundle, verify_bundle_integrity
from tradingbot.ml.phase15a.config import RANGE_ENGINE_ID, TREND_ENGINE_ID, TREND_ENGINE_V41_ID
from tradingbot.ml.phase15a.trend_bundle import TrendRfBundle, load_trend_bundle, validate_trend_checksum
from tradingbot.ml.research.phase13_8.recovered_trend_engine import RecoveredTrendEngine
from tradingbot.ml.research.phase13_8.trend_variants import evaluate_variant_a
from tradingbot.ml.research.phase13_9.router_pipeline_rebuilder import UnifiedRangeWrapper
from tradingbot.ml.research.regime_router.range_engine_adapter import RangeEngineAdapter
from tradingbot.ml.decision_engine.decision_policy import TREND_ML_THRESHOLD


@runtime_checkable
class ProductionEngine(Protocol):
  def predict(self, row: pd.Series, *, regime: str) -> dict[str, Any]: ...
  def confidence(self, row: pd.Series, *, regime: str) -> float: ...
  def version(self) -> str: ...
  def checksum(self) -> str | None: ...
  def health(self) -> dict[str, Any]: ...


@dataclass
class Phase99EngineWrapper:
  inner: UnifiedRangeWrapper
  bundle_checksum: str | None = None

  def predict(self, row: pd.Series, *, regime: str) -> dict[str, Any]:
    from tradingbot.ml.research.phase13_9.unified_features import row_for_phase99_range
    return self.inner.evaluate(row=row_for_phase99_range(row))

  def confidence(self, row: pd.Series, *, regime: str) -> float:
    return float(self.predict(row, regime=regime).get("confidence", 0.0))

  def version(self) -> str:
    return RANGE_MODEL_ID

  def checksum(self) -> str | None:
    return self.bundle_checksum

  def health(self) -> dict[str, Any]:
    return {"engine": RANGE_ENGINE_ID, "status": "OK" if self.bundle_checksum else "UNKNOWN"}


@dataclass
class TrendRfEngineWrapper:
  bundle: TrendRfBundle
  inner: Any
  engine_id: str = TREND_ENGINE_ID
  bundle_version: str = "v40"

  def predict(self, row: pd.Series, *, regime: str) -> dict[str, Any]:
    return self.inner.evaluate(row, regime=regime)

  def confidence(self, row: pd.Series, *, regime: str) -> float:
    return float(self.predict(row, regime=regime).get("confidence", 0.0))

  def version(self) -> str:
    return self.bundle.version

  def checksum(self) -> str | None:
    return self.bundle.checksum.get("bundle_sha256")

  def health(self) -> dict[str, Any]:
    chk = validate_trend_checksum(version=self.bundle_version)
    return {"engine": self.engine_id, "status": "OK" if chk.get("valid") else "FAIL", "checksum": chk}


class EngineRegistry:
  """Registry of production ML engines — no execution."""

  def __init__(self, engines: dict[str, ProductionEngine] | None = None) -> None:
    self._engines: dict[str, ProductionEngine] = engines or {}

  def register(self, engine_id: str, engine: ProductionEngine) -> None:
    self._engines[engine_id] = engine

  def get(self, engine_id: str) -> ProductionEngine | None:
    return self._engines.get(engine_id)

  def list_ids(self) -> list[str]:
    return sorted(self._engines.keys())

  def health_all(self) -> dict[str, Any]:
    return {eid: eng.health() for eid, eng in self._engines.items()}

  def get_active_trend(self) -> ProductionEngine | None:
    from tradingbot.ml.phase17d.versioning import resolve_active_trend_engine_id

    return self.get(resolve_active_trend_engine_id())

  @classmethod
  def build_default(
    cls,
    *,
    base_dir: str | None = None,
    build_trend_if_missing: bool = True,
    symbol: str = "XAUUSD",
  ) -> "EngineRegistry":
    registry = cls()
    p99 = load_phase9_9_bundle(base_dir=base_dir, build_if_missing=False)
    from tradingbot.ml.phase15a.trend_bundle import sha256_file
    from tradingbot.ml.data.paths import phase9_9_model_path
    p99_path = phase9_9_model_path(base_dir)
    p99_hash = sha256_file(p99_path) if p99_path.is_file() else None
    range_inner = RangeEngineAdapter.load(symbol=symbol, base_dir=base_dir)
    range_wrapped = UnifiedRangeWrapper(range_inner)
    registry.register(RANGE_ENGINE_ID, Phase99EngineWrapper(range_wrapped, p99_hash))

    from tradingbot.ml.feature_alignment.factory import build_distribution_aligner
    aligner = build_distribution_aligner(base_dir=base_dir, symbol=symbol)

    bundle_v40 = load_trend_bundle(
      base_dir=base_dir, build_if_missing=build_trend_if_missing, symbol=symbol, version="v40",
    )
    trend_v40 = RecoveredTrendEngine(
      model=bundle_v40.model,
      scaler=bundle_v40.scaler,
      model_name="random_forest",
      threshold=float(bundle_v40.config.get("threshold", TREND_ML_THRESHOLD)),
      rule_fn=evaluate_variant_a,
      symbol=symbol,
      aligner=aligner,
    )
    trend_v40.model_version = TREND_MODEL_ID
    registry.register(
      TREND_ENGINE_ID,
      TrendRfEngineWrapper(bundle_v40, trend_v40, engine_id=TREND_ENGINE_ID, bundle_version="v40"),
    )

    try:
      from tradingbot.ml.phase17d.v41_engine import TrendRfV41Engine

      bundle_v41 = load_trend_bundle(base_dir=base_dir, build_if_missing=False, version="v41")
      trend_v41 = TrendRfV41Engine(
        bundle=bundle_v41,
        threshold=float(bundle_v41.config.get("threshold", TREND_ML_THRESHOLD)),
        rule_fn=evaluate_variant_a,
        symbol=symbol,
        aligner=None,
        engine_id=TREND_ENGINE_V41_ID,
      )
      registry.register(
        TREND_ENGINE_V41_ID,
        TrendRfEngineWrapper(bundle_v41, trend_v41, engine_id=TREND_ENGINE_V41_ID, bundle_version="v41"),
      )
    except FileNotFoundError:
      pass

    return registry
