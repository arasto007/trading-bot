import json
from pathlib import Path

ROOT = Path(r"C:\Users\AMIR\Desktop\TradingBot new")
d30 = {
    "BASELINE": {"window": "10-17", "raw_setups": 474, "meta_accepted": 80, "win_rate": 29.03, "profit_factor": 1.027, "expectancy_R": 0.0194, "max_drawdown_R": 5.443, "final_signals": 31},
    "TEST_WINDOW": {"window": "9-17", "raw_setups": 574, "meta_accepted": 102, "win_rate": 27.78, "profit_factor": 0.943, "expectancy_R": -0.0413, "max_drawdown_R": 9.0, "final_signals": 36},
}
d60 = {
    "BASELINE": {"window": "10-17", "raw_setups": 854, "meta_accepted": 147, "win_rate": 22.81, "profit_factor": 0.647, "expectancy_R": -0.2698, "max_drawdown_R": 18.979, "final_signals": 57},
    "TEST_WINDOW": {"window": "9-17", "raw_setups": 1051, "meta_accepted": 198, "win_rate": 23.19, "profit_factor": 0.579, "expectancy_R": -0.3231, "max_drawdown_R": 28.809, "final_signals": 69},
}
d90 = json.loads((ROOT / "logs" / "phase14c1_90d_only.json").read_text(encoding="utf-8"))
all_res = {"30d": d30, "60d": d60, "90d": d90}


def gate(base, test):
    raw_inc = ((test["raw_setups"] - base["raw_setups"]) / max(base["raw_setups"], 1)) * 100
    pf_drop = ((base["profit_factor"] - test["profit_factor"]) / max(base["profit_factor"], 1e-9)) * 100 if base["profit_factor"] > 0 else 999
    exp_pos = test["expectancy_R"] > 0
    dd_inc = test["max_drawdown_R"] - base["max_drawdown_R"]
    ok = raw_inc >= 25 and pf_drop <= 10 and exp_pos and dd_inc <= 1.0
    return {
        "raw_setups_increase_pct": round(raw_inc, 2),
        "pf_drop_pct": round(pf_drop, 2),
        "expectancy_stays_positive": "YES" if exp_pos else "NO",
        "max_dd_increase_R": round(dd_inc, 3),
        "gates_pass": "YES" if ok else "NO",
    }

gates = {t: gate(all_res[t]["BASELINE"], all_res[t]["TEST_WINDOW"]) for t in all_res}
certified = all(g["gates_pass"] == "YES" for g in gates.values())
base = d90["BASELINE"]
test = d90["TEST_WINDOW"]
g90 = gates["90d"]
safe = "YES" if certified else "NO"
rec = "09-17" if certified else "10-17"

lines = [
    "PHASE 14C-1 Session Window Recovery (Research Only)",
    "BASELINE=10-17 UTC | TEST_WINDOW=09-17 UTC",
    "PATCH_APPLIED=NO",
    "",
]
for tag in ("30d", "60d", "90d"):
    lines.append("=== " + tag + " ===")
    lines.append("| Window | Raw Setups | Meta Accepted | Win Rate | PF | Expectancy R | Max DD |")
    lines.append("| ------ | ---------- | ------------- | -------- | -- | ------------ | ------ |")
    for name in ("BASELINE", "TEST_WINDOW"):
        r = all_res[tag][name]
        lines.append(
            "| "
            + name
            + " "
            + r["window"]
            + " | "
            + str(r["raw_setups"])
            + " | "
            + str(r["meta_accepted"])
            + " | "
            + str(r["win_rate"])
            + " | "
            + str(r["profit_factor"])
            + " | "
            + str(r["expectancy_R"])
            + " | "
            + str(r["max_drawdown_R"])
            + " |"
        )
    g = gates[tag]
    lines.append(
        "gates: raw_inc="
        + str(g["raw_setups_increase_pct"])
        + "% pf_drop="
        + str(g["pf_drop_pct"])
        + "% exp_pos="
        + g["expectancy_stays_positive"]
        + " dd_inc="
        + str(g["max_dd_increase_R"])
        + "R PASS="
        + g["gates_pass"]
    )
    lines.append("")

lines.extend(
    [
        "PHASE_14C_1_RESULT",
        "BASELINE_RAW=" + str(base["raw_setups"]),
        "TEST_RAW=" + str(test["raw_setups"]),
        "RAW_INCREASE_PCT=" + str(g90["raw_setups_increase_pct"]),
        "BASELINE_PF=" + str(base["profit_factor"]),
        "TEST_PF=" + str(test["profit_factor"]),
        "BASELINE_EXPECTANCY_R=" + str(base["expectancy_R"]),
        "TEST_EXPECTANCY_R=" + str(test["expectancy_R"]),
        "BASELINE_MAX_DD_R=" + str(base["max_drawdown_R"]),
        "TEST_MAX_DD_R=" + str(test["max_drawdown_R"]),
        "SESSION_RECOVERY_CERTIFIED=" + ("YES" if certified else "NO"),
        "SAFE_LIVE_PATCH=" + safe,
        "RECOMMENDED_WINDOW=" + rec,
    ]
)
text = "\n".join(lines) + "\n"
(ROOT / "logs" / "phase14c1_session_window_recovery.txt").write_text(text, encoding="utf-8")
(ROOT / "logs" / "phase14c1_session_window_recovery.json").write_text(
    json.dumps({"datasets": all_res, "gates": gates, "certified": certified}, indent=2),
    encoding="utf-8",
)
print(text)
