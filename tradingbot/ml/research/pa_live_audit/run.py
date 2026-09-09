"""Write Phase 1.5.56–60 research report JSON. Offline only."""

from __future__ import annotations

import json
from typing import Any

from tradingbot.ml.data.paths import reports_dir
from tradingbot.ml.research.pa_live_audit.classify import classify_phase60
from tradingbot.ml.research.pa_live_audit.parity import parity_matrix
from tradingbot.ml.research.pa_live_audit.path import live_path_hops, pa_live_specification
from tradingbot.ml.research.pa_live_audit.replay import replay_live_pa_rules
from tradingbot.ml.research.pa_live_audit.root_cause import root_cause_findings


def run_pa_live_audit(*, write_reports: bool = True, max_bars: int | None = None) -> dict[str, Any]:
    spec = pa_live_specification()
    hops = live_path_hops()
    matrix = parity_matrix()
    replay = replay_live_pa_rules(max_bars=max_bars)
    decision = classify_phase60(replay)
    payload: dict[str, Any] = {
        "phase": "1.5.56-1.5.60",
        "offline_only": True,
        "production_unchanged": True,
        "v41_not_activated": True,
        "live_path": hops,
        "pa_specification": spec,
        "parity_matrix": matrix,
        "replay": replay,
        "root_causes": root_cause_findings(),
        "decision": decision,
    }
    if write_reports:
        out = reports_dir() / "phase15_56"
        out.mkdir(parents=True, exist_ok=True)
        # Drop per-trade list if ever added; keep summaries only.
        path = out / "pa_live_edge_audit.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        payload["report_path"] = str(path)
    return payload


if __name__ == "__main__":
    result = run_pa_live_audit()
    keep = {
        "decision": result.get("decision"),
        "replay_full": (result.get("replay") or {}).get("full"),
        "replay_oos": (result.get("replay") or {}).get("out_of_sample"),
        "replay_ins": (result.get("replay") or {}).get("in_sample"),
        "year": (result.get("replay") or {}).get("year"),
        "direction": (result.get("replay") or {}).get("direction"),
        "session": (result.get("replay") or {}).get("session"),
        "holding_time": (result.get("replay") or {}).get("holding_time"),
        "preset": (result.get("pa_specification") or {}).get("preset"),
        "report_path": result.get("report_path"),
    }
    print(json.dumps(keep, indent=2, default=str))
