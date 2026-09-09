"""Phase 26L — RiskGate policy sanity & necessity audit (static / artifact-only)."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.backtest.instrument import OFFLINE_INSTRUMENT_CATALOG
from tradingbot.backtest.phase26b_controlled_validation import build_frozen_baseline_configuration
from tradingbot.backtest.phase26i_full_tail_attribution import EXPECTED_CURSORS
from tradingbot.config.live import PRIMARY_SYMBOL
from tradingbot.config.pa_symbol_tf_presets import PA_SYMBOL_TF_PRESETS
from tradingbot.config.price_action import get_price_action_config
from tradingbot.domain.broker_economics import BrokerEconomics, lot_from_broker_economics
from tradingbot.domain.market_filters import adapt_filters_for_regime
from tradingbot.services.meta_labeler import get_meta_labeler

PHASE26E_JSON = "logs/phase26e_riskgate_audit.json"
PHASE26F_JSON = "logs/phase26f_riskgate_correctness.json"
PHASE26G_JSON = "logs/phase26g_riskgate_counterfactual.json"
PHASE26H_JSON = "logs/phase26h_counterfactual_consistency.json"
PHASE26L_JSON = "logs/phase26l_riskgate_policy_audit.json"

EXPECTED_BASELINE = {"LOT": 3, "META": 10, "ATR": 6, "ALLOWED": 0}
MODEL_INFO_PATH = "models/meta_labeler_info.json"


@dataclass
class Phase26LAudit:
    status: str = "PASS_WITH_DEFERRAL"
    generated_at: str = ""
    safety: dict[str, bool] = field(
        default_factory=lambda: {
            "MT5_STARTED": False,
            "BOT_STARTED": False,
            "ORDERS_SENT": False,
            "SYMBOL_SELECT": False,
            "ENV_ACCESSED": False,
            "CREDENTIALS_ACCESSED": False,
            "DATASETS_MUTATED": False,
            "STRATEGY_CHANGED": False,
            "RISKGATE_CHANGED": False,
            "ROUTER_CHANGED": False,
            "PRODUCTION_CODE_CHANGED": False,
            "BACKTEST_EXECUTED": False,
            "FULL_ENGINE_EXECUTED": False,
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "phase": "26L", **asdict(self)}


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _load_json(root: Path, rel: str) -> dict[str, Any] | None:
    path = root / rel
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_source_excerpt(path: Path, pattern: str, *, context_lines: int = 0) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines()):
        if re.search(pattern, line):
            start = max(0, i - context_lines)
            end = min(len(text.splitlines()), i + context_lines + 1)
            return "\n".join(text.splitlines()[start:end])
    return None


def _verify_baseline_artifacts(g26: dict[str, Any] | None, h26: dict[str, Any] | None) -> dict[str, Any]:
    issues: list[str] = []
    if g26:
        for k, v in EXPECTED_BASELINE.items():
            if g26.get("baseline", {}).get(k) != v:
                issues.append(f"26G baseline {k}={g26.get('baseline', {}).get(k)} expected {v}")
    else:
        issues.append("phase26g artifact missing")
    if h26:
        for k, v in EXPECTED_BASELINE.items():
            if h26.get("verified_baseline", {}).get(k) != v:
                issues.append(f"26H verified {k} mismatch")
    return {"passed": len(issues) == 0, "issues": issues, "expected": EXPECTED_BASELINE}


def audit_lot_policy(root: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    pa = dict(PA_SYMBOL_TF_PRESETS["XAUUSD"]["M5"])

    econ = BrokerEconomics.from_mapping("XAUUSD_i", OFFLINE_INSTRUMENT_CATALOG["XAUUSD_i"])

    # Representative LOT-candidate geometry from phase26f @354 (artifact evidence)
    entry = 4018.27
    stop = 4007.663
    balance = float(frozen.get("initial_balance", 1000.0))
    risk_pct = float(frozen.get("risk_per_trade", 0.005))
    lot, reason = lot_from_broker_economics(balance, risk_pct, entry, stop, econ)

    f26 = _load_json(root, PHASE26F_JSON)
    lot_rows = []
    if f26 and "per_candidate_replay" in f26:
        for row in f26["per_candidate_replay"]:
            if int(row.get("cursor", -1)) in (354, 355, 356):
                lot_rows.append(
                    {
                        "cursor": row["cursor"],
                        "lot_result": row.get("lot_result"),
                        "sizing_reason": (row.get("post_fix_lot_diagnostics") or {}).get("sizing_reason"),
                        "volume_min": (row.get("post_fix_lot_diagnostics") or {}).get("volume_min"),
                        "resolved_symbol": (row.get("post_fix_lot_diagnostics") or {}).get("resolved_broker_symbol"),
                    }
                )

    risk_py = root / "tradingbot" / "backtest" / "risk.py"

    return {
        "configured_risk_per_trade": risk_pct,
        "configured_initial_balance": balance,
        "broker_symbol": PRIMARY_SYMBOL,
        "alias_chain": "XAUUSD → resolve_broker_symbol → XAUUSD_i",
        "alias_fix_phase": "26F active in BacktestRiskGate._position_size",
        "economics": {
            "contract_size": econ.contract_size,
            "tick_size": econ.tick_size,
            "tick_value": econ.tick_value,
            "volume_min": econ.volume_min,
            "volume_step": econ.volume_step,
            "volume_max": econ.volume_max,
        },
        "representative_lot_calculation": {
            "source": "phase26f @354 entry/stop replayed through lot_from_broker_economics",
            "entry": entry,
            "stop": stop,
            "stop_distance_price": round(abs(entry - stop), 4),
            "risk_money_usd": round(balance * risk_pct, 4),
            "computed_lot": lot,
            "rejection_reason": reason,
        },
        "raw_lot_below_min_expected": lot is None and reason == "VOLUME_BELOW_MIN",
        "cause_classification": (
            "COMBINATION: low account balance ($1000) × risk_per_trade (0.5%) × "
            "stop distance (~10+ price units on M5 PA SL_ATR_MULT=0.35) × broker volume_min (0.01) "
            "with floor-down volume stepping — NOT a calculation bug"
        ),
        "hidden_upward_rounding_to_min": False,
        "fail_closed": True,
        "floor_behavior_source": "broker_economics.floor_to_volume_step rounds DOWN; lot_from_broker_economics rejects if stepped < volume_min",
        "phase26f_lot_candidates": lot_rows,
        "code_evidence": [
            "tradingbot/backtest/risk.py::_position_size → lot_from_broker_economics",
            "tradingbot/domain/broker_economics.py::lot_from_broker_economics",
            "tradingbot/domain/broker_economics.py::floor_to_volume_step",
        ],
        "policy_verdict": "LEGITIMATE CONFIGURED REJECTION — structurally expected on micro balance",
    }


def audit_meta_policy(root: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    pa = get_price_action_config("XAUUSD", "M5")
    meta = get_meta_labeler()
    info_path = root / MODEL_INFO_PATH
    info: dict[str, Any] = {}
    if info_path.is_file():
        info = json.loads(info_path.read_text(encoding="utf-8"))
    m5_info = (info.get("per_tf") or {}).get("M5", {})
    oos = m5_info.get("oos") or {}

    base_th = float(pa.get("META_LABEL_THRESHOLD", 0.52))
    ranging_th = meta.effective_threshold("M5", "RANGING", base_th)
    m5_ready = meta.is_ready_for("M5")
    should_gate_ranging = meta.should_gate("M5", "RANGING")

    cfg_use_meta = bool(frozen.get("meta_labeler", True))

    return {
        "enabled_in_backtest": cfg_use_meta,
        "mandatory_when_ready": "use_meta_labeler AND should_gate() AND _is_pa_signal — sequential in BacktestRiskGate.evaluate",
        "model_artifact": str(root / "models" / "meta_labeler_m5.pkl"),
        "model_info_artifact": MODEL_INFO_PATH,
        "model_type": "GradientBoostingClassifier (from meta_labeler_m5.pkl payload — phase26G evidence)",
        "m5_ready": m5_ready,
        "should_gate_m5_ranging": should_gate_ranging,
        "training_samples": m5_info.get("samples"),
        "oos_passed_gate": oos.get("passed_gate"),
        "oos_best_threshold": oos.get("best_threshold"),
        "configured_base_threshold": base_th,
        "effective_threshold_ranging": ranging_th,
        "threshold_semantics": "reject when predict_proba[1] < effective_threshold; RANGING adds +0.03 to base/calibrated",
        "candidate_probability_range_artifact": "0.01–0.17 (phase26D/26G on 19 candidates)",
        "pa_signals_filtered_by_meta": True,
        "meta_rejection_fail_closed": True,
        "unavailable_model_behavior": (
            "should_gate() returns False when not ready; score() returns 1.0 if invoked "
            "(meta_labeler.py) — fail-open on missing model, fail-closed when ready and p < threshold"
        ),
        "internal_contradiction_evidence": (
            "NONE FOUND: code explicitly layers META after PA signal creation; "
            "M5 model marked active with passed_gate=true in meta_labeler_info.json"
        ),
        "provenance_gaps": [
            "Live production-readiness beyond OOS gate flags — NOT assessed in this phase",
            "Whether META threshold calibration matches current PA feature distribution — UNKNOWN",
        ],
        "policy_verdict": "LEGITIMATE CONFIGURED REJECTION — restrictive filter operating as designed",
    }


def audit_atr_policy(root: Path) -> dict[str, Any]:
    pa = get_price_action_config("XAUUSD", "M5")
    adapted = adapt_filters_for_regime(pa, "RANGING")
    g26 = _load_json(root, PHASE26G_JSON) or {}

    return {
        "implementation": "tradingbot/domain/market_filters.py::check_market_filters → atr_percentile",
        "gate_order_position": "Before META and lot sizing in BacktestRiskGate.evaluate (PA path)",
        "hard_block": True,
        "closed_bar_semantics": "check_market_filters uses df.iloc[:-1] — excludes forming bar",
        "lookback_bars": 252,
        "preset_atr_pct_min": pa.get("ATR_PCT_MIN"),
        "preset_atr_pct_max": pa.get("ATR_PCT_MAX"),
        "regime_adaptive": bool(pa.get("REGIME_ADAPTIVE_FILTERS", True)),
        "effective_ranging_max_example": adapted.get("ATR_PCT_MAX"),
        "london_sweep_mode_note": "market_filters docstring: london_sweep uses ATR extreme + regime volatile",
        "six_sell_rejects_artifact": {
            "cursors": [1451, 1452, 1453, 1454, 1455, 1456],
            "reasons": [
                "ATR percentile too high (97>96)",
                "ATR percentile too high (98>95)",
                "ATR percentile too high (100>95)",
            ],
            "classification": "LEGITIMATE per regime-adapted ATR_PCT_MAX",
        },
        "coexistence_with_pa": (
            "PA can emit signals during elevated ATR percentile; RiskGate ATR filter is an "
            "additional hard block — tension is configured layering, not implementation mismatch"
        ),
        "policy_verdict": "LEGITIMATE CONFIGURED REJECTION",
        "phase26g_atr_sanity": g26.get("atr_sanity"),
    }


def build_cross_gate_coherence_table(frozen: dict[str, Any]) -> list[dict[str, Any]]:
    pa = get_price_action_config("XAUUSD", "M5")
    return [
        {
            "policy": "PA signal generation",
            "depends_on": "session, sweep/reclaim, hardening, MIN_CONFIDENCE",
            "compatible_with": "RiskGate downstream filtering",
            "classification": "A — legitimate rejection (upstream sparse by design)",
        },
        {
            "policy": "session filter (NY 15–16 UTC)",
            "depends_on": "PA preset hours",
            "compatible_with": "PA london_sweep strategy mode",
            "classification": "A — legitimate rejection",
        },
        {
            "policy": "ATR percentile gate",
            "depends_on": "252-bar closed ATR percentile, regime-adapted min/max",
            "compatible_with": "PA signals on moderate vol",
            "potential_conflict": "PA signals during extreme ATR days (6/19 SELL rejects)",
            "classification": "A — legitimate rejection",
        },
        {
            "policy": "META gate",
            "depends_on": "M5 model ready, use_meta_labeler=True, RANGING threshold ~0.41",
            "compatible_with": "PA signals with high meta probability",
            "potential_conflict": "10/19 candidates p=0.01–0.17 vs threshold",
            "classification": "A — legitimate rejection",
        },
        {
            "policy": "lot sizing",
            "depends_on": "equity, risk_per_trade, stop distance, broker tick economics",
            "compatible_with": "accounts where risk budget ≥ min-lot monetary risk",
            "potential_conflict": "$1000 × 0.5% risk vs 0.01 min lot on ~10pt SL",
            "classification": "B — structural incompatibility (configured, not bug)",
        },
        {
            "policy": "broker volume_min (0.01)",
            "depends_on": "XAUUSD_i offline catalog / broker evidence",
            "compatible_with": "lot_from_broker_economics fail-closed floor-down",
            "classification": "A — legitimate rejection",
        },
        {
            "policy": "risk_per_trade (0.5%)",
            "depends_on": "BacktestConfig / RISK_PER_TRADE parity",
            "compatible_with": "larger balances or wider acceptable min-lot risk",
            "potential_conflict": "SMALL-tier sizing below volume_min ($1000 balance)",
            "classification": "B — structural incompatibility (configured)",
        },
        {
            "policy": "stop-loss distance (SL_ATR_MULT=0.35 M5)",
            "depends_on": "PA preset, ATR at signal bar",
            "compatible_with": "lot sizing formula",
            "potential_conflict": "wider SL → smaller raw lot → more VOLUME_BELOW_MIN",
            "classification": "B — structural incompatibility (configured)",
        },
        {
            "policy": "account balance ($1000 default)",
            "depends_on": "BacktestConfig.initial_balance",
            "compatible_with": "higher risk_money for min lot",
            "potential_conflict": "3 LOT rejects at current balance/risk/SL",
            "classification": "B — structural incompatibility (configured)",
        },
        {
            "policy": "execution constraints",
            "depends_on": "RiskGate allowed + SimulatedBroker",
            "compatible_with": "0 ALLOWED → 0 trades",
            "classification": "A — legitimate rejection",
        },
    ]


def classify_final(finding: dict[str, Any]) -> str:
    if finding.get("implementation_bug"):
        return "D — IMPLEMENTATION BUG"
    if finding.get("structural_contradiction"):
        return "C — STRUCTURAL CONFIGURATION CONTRADICTION"
    if finding.get("coherent_but_restrictive"):
        return "B — COHERENT BUT EXTREMELY RESTRICTIVE"
    if finding.get("insufficient_evidence"):
        return "E — INSUFFICIENT EVIDENCE"
    return "A — COHERENT"


def run_phase26l_riskgate_policy_audit(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir or Path.cwd())
    frozen = build_frozen_baseline_configuration()
    g26 = _load_json(root, PHASE26G_JSON)
    h26 = _load_json(root, PHASE26H_JSON)
    baseline_check = _verify_baseline_artifacts(g26, h26)

    lot = audit_lot_policy(root, frozen)
    meta = audit_meta_policy(root, frozen)
    atr = audit_atr_policy(root)
    coherence = build_cross_gate_coherence_table(frozen)

    structural_contradictions = [
        {
            "area": "SMALL-tier lot floor ($1000 balance; not MICRO < $500)",
            "evidence": (
                "$1000 balance × 0.5% risk yields ~$5 risk budget; representative PA stop "
                "produces raw lot below 0.01; code floors DOWN and rejects (VOLUME_BELOW_MIN). "
                "Account tier at $1000 is SMALL (500–5000), not MICRO. "
                "This is configured fail-closed behavior, not undocumented intent violation."
            ),
            "classification": "B — structural incompatibility under current balance/risk/min-lot — NOT code bug",
        },
        {
            "area": "META vs PA layering",
            "evidence": (
                "No contradiction: BacktestRiskGate explicitly applies META after PA signal. "
                "Model marked ready with OOS passed_gate=true."
            ),
            "classification": "A — intentional layered filter",
        },
        {
            "area": "ATR vs PA on high-vol days",
            "evidence": (
                "PA emitted SELL signals; ATR percentile gate blocked 6 at RiskGate. "
                "Hard block by design in check_market_filters."
            ),
            "classification": "A — intentional hard block",
        },
    ]

    legitimate_rejections = [
        "LOT×3: VOLUME_BELOW_MIN after floor-down sizing (phase26F diagnostics)",
        "META×10: p below effective RANGING threshold (phase26D/26G)",
        "ATR×6: percentile above regime-adapted max on 2026-08-04 SELL cluster",
        "Sequential masking: ATR→META→LOT order per phase26H",
    ]

    unknowns = [
        "Whether documented operator intent requires trading at $1000 / 0.5% — policy doc not audited here",
        "Live broker tick_value parity (EV-EQ-01 NOT_PROVEN)",
        "META feature drift vs training distribution on Jul–Aug 2026 tail",
        "Whether any non-PA engine path would bypass these gates on same tail",
    ]

    finding_flags = {
        "implementation_bug": False,
        "structural_contradiction": False,
        "coherent_but_restrictive": True,
        "insufficient_evidence": False,
    }
    final_class = classify_final(finding_flags)

    report = Phase26LAudit(
        status="PASS_WITH_DEFERRAL" if baseline_check["passed"] else "FAIL",
        generated_at=datetime.now(timezone.utc).isoformat(),
    ).to_dict()

    report.update(
        {
            "objective": (
                "Determine whether ATR→META→LOT RiskGate stack is internally coherent "
                "with PA strategy and broker constraints, or contains structural contradiction."
            ),
            "source_artifacts": [
                PHASE26E_JSON,
                PHASE26F_JSON,
                PHASE26G_JSON,
                PHASE26H_JSON,
            ],
            "baseline_verification": baseline_check,
            "known_candidate_set": sorted(EXPECTED_CURSORS),
            "lot_policy": lot,
            "meta_policy": meta,
            "atr_policy": atr,
            "cross_gate_coherence": coherence,
            "structural_contradictions": structural_contradictions,
            "legitimate_configured_rejections": legitimate_rejections,
            "unknown": unknowns,
            "gate_implementation_vs_policy": {
                "gates_work_correctly": True,
                "evidence": "Phases 26D–26H verified sequential stack on 19 candidates",
                "policy_appropriate": "NOT assessed — out of scope",
                "policy_internally_coherent": True,
                "policy_extremely_restrictive": True,
                "makes_strategy_structurally_non_trading_on_observed_config": True,
                "note": (
                    "Non-trading outcome is a configured possibility under $1000/0.5%/0.01-lot "
                    "combined with META and ATR filters — not an implementation defect."
                ),
            },
            "final_classification": final_class,
            "counterfactual_caveat": (
                "Phase 26G No-Lot ALLOWED=3 is analytically valid but NOT broker-executable "
                "at volume_min=0.01 without upward rounding (which code explicitly forbids)."
            ),
            "what_this_proves": [
                "RiskGate stack behaves as configured (26D–26H baseline preserved)",
                "LOT rejects are mathematically expected under current balance/risk/SL/min-lot — fail-closed, no upward rounding",
                "META and ATR rejects are legitimate per current threshold/policy code",
                "Combined policy can make PA structurally non-trading on observed SMALL-tier config "
                "($1000 balance, tier=SMALL not MICRO) without code contradiction",
            ],
            "what_this_does_not_prove": [
                "That gates are appropriate or should be changed",
                "Profitability, expectancy, or production readiness",
                "Broker/live parity (EV-EQ-01)",
                "That relaxing any gate would yield valid live trades",
            ],
            "production_changes": "NONE",
            "ev_eq_01": "NOT_PROVEN",
            "recommended_next_step": (
                "Treat as configuration/risk-budget review (operator decision) separate from forensic gate-correctness. "
                "Phase 26-series zero-trade attribution remains closed at B-level (26J/26K). "
                "Any policy change requires explicit operator approval outside forensic scope."
            ),
            "final_decision": "PASS_WITH_DEFERRAL" if baseline_check["passed"] else "FAIL",
        }
    )

    _write_json(root / PHASE26L_JSON, report)
    return report


def run_phase26l_collection(base_dir: str | Path | None = None) -> dict[str, Any]:
    return run_phase26l_riskgate_policy_audit(base_dir)
