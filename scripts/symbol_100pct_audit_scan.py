#!/usr/bin/env python3
"""Read-only symbol grep + classification for PHASE SYMBOL-100PCT-AUDIT."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs" / "symbol_audit"
SKIP_DIRS = {
    ".git", "__pycache__", "logs", "data", "models", "node_modules",
    ".cursor", ".venv", "venv", "agent-transcripts",
}
SKIP_SUFFIX = {".parquet", ".pkl", ".pyc", ".png", ".jpg", ".zip", ".7z", ".exe", ".dll"}
CODE_SUFFIX = {".py", ".ps1", ".bat", ".json", ".yml", ".yaml", ".md", ".txt", ".env", ".example", ".ini", ".toml"}

PATTERNS = [
    ("XAUUSD_i", re.compile(r"XAUUSD_i")),
    ("XAUUSD", re.compile(r"XAUUSD")),
    ("PRIMARY_SYMBOL", re.compile(r"PRIMARY_SYMBOL")),
    ("DEFAULT_SYMBOL", re.compile(r"DEFAULT_SYMBOL")),
    ("SYMBOL =", re.compile(r"SYMBOL\s*=")),
    ("symbol=", re.compile(r"symbol\s*=")),
]

LIVE_PREFIXES = (
    "tradingbot/config/live.py",
    "tradingbot/config/legacy_settings.py",
    "tradingbot/config/engine_settings.py",
    "tradingbot/config/price_action.py",
    "tradingbot/config/pa_symbol_tf_presets.py",
    "tradingbot/application/",
    "tradingbot/__main__.py",
    "tradingbot/adapters/mt5_",
    "tradingbot/adapters/risk_gate.py",
    "tradingbot/adapters/multi_engine_router.py",
    "tradingbot/adapters/legacy_strategy_registry.py",
    "tradingbot/adapters/symbols.py",
    "tradingbot/adapters/legacy_loader.py",
    "tradingbot/kernel/",
    "tradingbot/services/runtime_truth.py",
    "tradingbot/services/live_",
    "tradingbot/services/startup_validator.py",
    "tradingbot/services/engine_telemetry.py",
    "tradingbot/services/paper_fill_resolver.py",
    "tradingbot/ml/integration/factory.py",
    "tradingbot/domain/order_logic.py",
    "tradingbot/domain/signal_helpers.py",
    "engine/strategies/price_action_strategy.py",
    "scripts/run_live_watchdog.py",
    "scripts/start_live_",
    "scripts/stop_live_",
    "scripts/phase21c_health_snapshot.py",
    "scripts/check_live_setup.py",
    "scripts/status_snapshot.py",
    "start/",
)


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def is_comment(path: str, line: str) -> bool:
    s = line.strip()
    if path.endswith((".md", ".txt")):
        return True
    if s.startswith("#") or s.startswith("//"):
        return True
    if s.startswith('"""') or s.startswith("'''"):
        return True
    return False


def classify(path: str, line: str, lineno: int) -> str:
    if is_comment(path, line) or "/docs/" in path or path.startswith("docs/"):
        return "COMMENT_OR_DOC"
    low = path.lower()
    if (
        "/research/" in low
        or "/ml/phase" in low
        or "/ml/research" in low
        or "scripts/run_phase" in low
        or "scripts/phase" in low and "phase21c_health" not in low
        or "scripts/backtest_" in low
    ):
        return "RESEARCH_ONLY"
    if "backtest" in low or path.startswith("tradingbot/backtest/"):
        return "BACKTEST_ONLY"
    if path == "tradingbot/__main__.py" and "--symbol" in line:
        return "BACKTEST_ONLY"
    if path.endswith("bootstrap.py") and "build_kernel_demo" in open_context_hint(path, lineno):
        return "BACKTEST_ONLY"
    for pref in LIVE_PREFIXES:
        if path == pref or path.startswith(pref):
            return "LIVE_CRITICAL"
    if path.startswith("tests/"):
        return "BACKTEST_ONLY"
    if "adaptive" in low or "vol_regime" in low:
        return "RESEARCH_ONLY"
    return "RESEARCH_ONLY"


def open_context_hint(path: str, lineno: int) -> str:
    return ""


def iter_files():
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        if p.suffix.lower() not in CODE_SUFFIX and p.name not in {".env", ".env.example"}:
            continue
        yield p


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    grep_lines: list[str] = []
    classified: list[str] = []
    grep_lines.append("PHASE_SYMBOL_100PCT full grep")
    grep_lines.append(f"ROOT={ROOT}")
    grep_lines.append("")
    for f in sorted(iter_files(), key=lambda x: rel(x).lower()):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel_path = rel(f)
        for i, line in enumerate(text.splitlines(), 1):
            hits = []
            for name, rx in PATTERNS:
                if rx.search(line):
                    hits.append(name)
            if not hits:
                continue
            # Prefer XAUUSD_i over XAUUSD when both match
            symbol_hit = "XAUUSD_i" if "XAUUSD_i" in hits else ("XAUUSD" if "XAUUSD" in hits else hits[0])
            cat = classify(rel_path, line, i)
            snippet = line.replace("\t", " ")[:240]
            grep_lines.append(f"{rel_path}:{i}:{','.join(hits)}:{snippet}")
            classified.append(f"{rel_path}\t{i}\t{symbol_hit}\t{cat}\t{snippet}")
    grep_path = OUT_DIR / "full_symbol_grep.txt"
    class_path = OUT_DIR / "classified_matches.tsv"
    grep_path.write_text("\n".join(grep_lines) + "\n", encoding="utf-8")
    header = "File\tLine\tSymbol\tCategory\tSnippet"
    class_path.write_text(header + "\n" + "\n".join(classified) + "\n", encoding="utf-8")
    print(f"grep_lines={len(grep_lines)-3} classified={len(classified)} -> {grep_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())