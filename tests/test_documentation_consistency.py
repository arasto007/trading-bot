"""Phase 1.5.66–1.5.70 — documentation consistency (offline, no MT5)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_consistency_scan_passes() -> None:
    from tradingbot.ml.research.documentation_consistency.run import main

    result = main()
    assert result["ok"], result["failures"]
    assert result["invariants"]["PA_PRODUCTION_LOCK"] is True
    assert result["invariants"]["TREND_MODEL_ID"] == "trend_rf_v40"
    assert result["invariants"]["TREND_ENGINE_V41_ID"] == "trend_rf_v41"
    assert float(result["invariants"]["v41_calibration_factor"]) == 1.0
    assert result["v41_bundle"]["unchanged"] is True
    assert result["research_isolation"]["ok"] is True


def test_single_canonical_entry_file() -> None:
    from tradingbot.ml.research.documentation_consistency.scanner import (
        CANONICAL_REL,
        scan_canonical_entry,
    )

    entry = scan_canonical_entry()
    assert entry["ok"], entry
    assert not entry["duplicate_entries"]
    text = (ROOT / "docs_v2" / "01_truth" / "PROJECT_SOURCE_OF_TRUTH.md").read_text(encoding="utf-8")
    assert "Canonical-Entry:** true" in text
    for rel in CANONICAL_REL:
        if rel.endswith("PROJECT_SOURCE_OF_TRUTH.md"):
            continue
        body = (ROOT / rel).read_text(encoding="utf-8")
        assert "Canonical-Entry:** true" not in body, rel


def test_critical_production_classifications() -> None:
    from tradingbot.config.live import LIVE_TRADING_CONFIG, PRIMARY_SYMBOL
    from tradingbot.config.pa_symbol_tf_presets import PA_SYMBOL_TF_PRESETS
    from tradingbot.config.strategies import ACTIVE_STRATEGIES
    from tradingbot.ml.integration.factory import build_strategy_registry
    from tradingbot.ml.integration.config import is_ml_kernel_enabled
    from tradingbot.services.pa_production_lock import is_pa_production_lock

    assert PRIMARY_SYMBOL == "XAUUSD_i"
    assert ACTIVE_STRATEGIES.get("priceaction") is True
    assert sum(1 for v in ACTIVE_STRATEGIES.values() if v) == 1
    m5 = PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"]
    assert m5["PRESET"] == "gold_ny_sweep"
    assert m5["M5_USE_LONDON_SESSION"] is False
    assert m5["M5_USE_NY_SESSION"] is True
    assert LIVE_TRADING_CONFIG.get("PA_PRODUCTION_LOCK") is True
    assert is_pa_production_lock() is True or (
        LIVE_TRADING_CONFIG.get("ADAPTIVE_REGIME_ENABLED") or LIVE_TRADING_CONFIG.get("VOL_REGIME_ENABLED")
    )
    # Default process without Adaptive/VOL env: lock should hold.
    if not LIVE_TRADING_CONFIG.get("VOL_REGIME_ENABLED") and not LIVE_TRADING_CONFIG.get(
        "ADAPTIVE_REGIME_ENABLED"
    ):
        assert is_pa_production_lock() is True
    if not is_ml_kernel_enabled() and LIVE_TRADING_CONFIG.get("MULTI_ENGINE_ROUTER_ENABLED"):
        registry = build_strategy_registry({})
        # Shadow wrap possible; inner or self should be router.
        name = type(registry).__name__
        assert name in {"MultiEngineRouterRegistry", "ShadowStrategyRegistry"}, name


def test_protocol_and_contradiction_docs() -> None:
    proto = (ROOT / "docs_v2" / "99_change_control" / "DOCUMENTATION_UPDATE_PROTOCOL.md").read_text(
        encoding="utf-8"
    )
    assert "No important code change" in proto or "NO IMPORTANT CODE CHANGE" in proto.upper()
    cx = (ROOT / "docs_v2" / "01_truth" / "KNOWN_UNKNOWNS_AND_CONTRADICTIONS.md").read_text(
        encoding="utf-8"
    )
    assert "CX-001" in cx
    assert "CX-016" in cx
    assert "UNK-001" in cx
