#!/usr/bin/env python3
"""
Read-only project analyzer — generates Architecture Atlas JSON + Mermaid.
Run from repo root: python docs/architecture_atlas/build_atlas.py
Does NOT modify production code.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ATLAS = Path(__file__).resolve().parent
SCAN_ROOTS = ("tradingbot", "scripts", "engine")
SKIP_PARTS = {"__pycache__", ".git", "architecture_atlas", "tests"}
MAX_NODES_MERMAID = 80

# ── Curated metadata (ELI15 Persian + production facts) ─────────────────────

CURATED: dict[str, dict] = {
    "tradingbot.kernel.trading_kernel.TradingKernel": {
        "title": "TradingKernel",
        "type": "class",
        "district": "kernel",
        "importance": 5,
        "production": True,
        "description": "Main orchestration engine. Runs every trading cycle through a fixed pipeline.",
        "description_fa": "مغز اصلی ربات. مثل مدیر یک کارخانه است — هر ۳۰ ثانیه یک دور کامل می‌زند: داده بگیر، سیگنال بساز، ریسک چک کن، سفارش بزن.",
        "runs_when": "Every global cycle (live loop or backtest)",
        "risk_if_removed": "Robot stops completely.",
        "stages": ["Data", "Indicators", "Signal", "Filter", "Risk", "Execution"],
        "files": ["tradingbot/kernel/trading_kernel.py"],
        "called_by": ["LiveRunner", "bootstrap", "BacktestEngine"],
        "calls": ["DataStage", "RiskStage", "ExecutionStage", "TradeJournal"],
    },
    "tradingbot.application.live_runner.LiveRunner": {
        "title": "LiveRunner",
        "type": "class",
        "district": "application",
        "importance": 5,
        "production": True,
        "description": "Owns the infinite live loop: MT5 connect, kill switch, startup validation, kernel.run_forever().",
        "description_fa": "راننده ربات زنده. MT5 را وصل می‌کند، قبل از شروع همه چیز را چک می‌کند، بعد موتور اصلی را روشن می‌کند و تا وقتی توقف نزنی کار می‌کند.",
        "runs_when": "python -m tradingbot --loop --execute or START_BOT.bat",
        "risk_if_removed": "No live trading possible.",
        "files": ["tradingbot/application/live_runner.py"],
        "called_by": ["__main__", "start_bot.py", "watchdog"],
        "calls": ["TradingKernel", "KillSwitchService", "validate_startup"],
    },
    "tradingbot.adapters.risk_gate.RiskGate": {
        "title": "RiskGate",
        "type": "class",
        "district": "risk",
        "importance": 5,
        "production": True,
        "description": "Bodyguard layer: spread, cooldown, Friday window, max positions, drawdown, lot sizing.",
        "description_fa": "مثل نگهبان ربات. حتی اگر هوش مصنوعی بخواهد بخرد، اینجا می‌گوید «نه» اگر اسپرد زیاد باشد، ضرر روزانه زیاد باشد، یا جمعه نزدیک باشد.",
        "runs_when": "Every signal, inside RiskStage",
        "risk_if_removed": "Uncontrolled orders — account danger.",
        "files": ["tradingbot/adapters/risk_gate.py"],
        "called_by": ["RiskStage", "create_risk_gate"],
        "calls": ["live_gates", "LiveRiskTracker", "risk_logic"],
    },
    "tradingbot.pipeline.risk_stage.RiskStage": {
        "title": "RiskStage",
        "type": "class",
        "district": "pipeline",
        "importance": 4,
        "production": True,
        "description": "Pipeline stage 4 — calls IRiskGate.evaluate on each signal.",
        "description_fa": "ایستگاه چهارم خط تولید. سیگنال را می‌گیرد و می‌پرسد «آیا اجازه معامله داریم؟»",
        "runs_when": "Each market cycle after signal",
        "files": ["tradingbot/pipeline/risk_stage.py"],
        "called_by": ["TradingKernel"],
        "calls": ["RiskGate"],
    },
    "tradingbot.adapters.mt5_execution.Mt5ExecutionAdapter": {
        "title": "Mt5ExecutionAdapter",
        "type": "class",
        "district": "execution",
        "importance": 5,
        "production": True,
        "description": "Sends real orders to MetaTrader 5 (live/paper/dry-run modes).",
        "description_fa": "دست ربات برای زدن دکمه خرید/فروش در MT5. اگر dry-run باشد فقط شبیه‌سازی می‌کند.",
        "runs_when": "ExecutionStage when signal approved",
        "risk_if_removed": "Signals never become trades.",
        "files": ["tradingbot/adapters/mt5_execution.py"],
        "called_by": ["ExecutionStage", "LiveRunner"],
        "calls": ["mt5_order_guard", "MetaTrader5"],
    },
    "tradingbot.adapters.mt5_market_data.Mt5MarketDataAdapter": {
        "title": "Mt5MarketDataAdapter",
        "type": "class",
        "district": "data",
        "importance": 5,
        "production": True,
        "description": "Fetches OHLCV candles and ticks from MT5.",
        "description_fa": "چشم ربات — قیمت‌ها و کندل‌ها را از MT5 می‌خواند.",
        "runs_when": "DataStage every cycle",
        "files": ["tradingbot/adapters/mt5_market_data.py"],
        "called_by": ["DataStage"],
        "calls": ["mt5_utils", "market_cache"],
    },
    "tradingbot.adapters.vol_regime_strategy_registry": {
        "title": "VolRegimeStrategyRegistry",
        "type": "module",
        "district": "trading",
        "importance": 5,
        "production": True,
        "description": "Active live strategy: VOL_REGIME ATR2.5_RR0.8 on XAUUSD M5.",
        "description_fa": "استراتژی فعلی ربات — بر اساس نوسان بازار تصمیم می‌گیرد چه موقع طلا بخرد یا بفروشد.",
        "runs_when": "SignalStage when USE_ML_KERNEL=false",
        "files": ["tradingbot/adapters/vol_regime_strategy_registry.py"],
        "called_by": ["build_strategy_registry"],
        "calls": ["vol_regime_signal"],
    },
    "tradingbot.services.kill_switch.KillSwitchService": {
        "title": "KillSwitchService",
        "type": "class",
        "district": "monitoring",
        "importance": 5,
        "production": True,
        "description": "Emergency halt on max drawdown or daily loss breach.",
        "description_fa": "کلید قطع اضطراری. اگر ضرر از حد مجاز رد شود، ربات را می‌بندد.",
        "runs_when": "Background during live loop",
        "risk_if_removed": "Account can bleed without auto-stop.",
        "files": ["tradingbot/services/kill_switch.py"],
        "called_by": ["LiveRunner"],
        "calls": ["emergency_stop_state"],
    },
    "tradingbot.services.trade_journal.TradeJournal": {
        "title": "TradeJournal",
        "type": "class",
        "district": "monitoring",
        "importance": 4,
        "production": True,
        "description": "SQLite journal: executions, cycle events, paper trades.",
        "description_fa": "دفتر خاطرات ربات — هر معامله و هر چرخه را یادداشت می‌کند.",
        "runs_when": "After execution and each cycle",
        "files": ["tradingbot/services/trade_journal.py"],
        "called_by": ["TradingKernel", "Mt5ExecutionAdapter"],
        "calls": ["data/trade_journal.db"],
    },
    "tradingbot.services.startup_validator": {
        "title": "startup_validator",
        "type": "module",
        "district": "services",
        "importance": 4,
        "production": True,
        "description": "Pre-flight: MT5, autotrading, config, demo guard before live loop.",
        "description_fa": "چک لیست قبل از پرواز — مطمئن می‌شود MT5 وصل است و همه چیز آماده است.",
        "runs_when": "Once at LiveRunner startup",
        "files": ["tradingbot/services/startup_validator.py"],
        "called_by": ["LiveRunner"],
        "calls": ["mt5_health", "demo_account_guard"],
    },
    "tradingbot.backtest.engine": {
        "title": "BacktestEngine",
        "type": "module",
        "district": "backtest",
        "importance": 4,
        "production": True,
        "description": "Historical simulation using same kernel pipeline as live.",
        "description_fa": "ربات را روی گذشته بازار تست می‌کند — مثل بازی کردن با تاریخ.",
        "runs_when": "python -m tradingbot --backtest or run_backtest.py",
        "files": ["tradingbot/backtest/engine.py"],
        "called_by": ["__main__", "scripts/run_backtest.py"],
        "calls": ["TradingKernel", "BacktestDataSource"],
    },
    "scripts.start_bot": {
        "title": "START_BOT",
        "type": "entry",
        "district": "configuration",
        "importance": 5,
        "production": True,
        "description": "One-click live start via start/START_BOT.bat.",
        "description_fa": "دکمه روشن — همین یک فایل ربات را زنده می‌کند.",
        "runs_when": "User double-clicks START_BOT.bat",
        "files": ["scripts/start_bot.py", "start/START_BOT.bat"],
        "called_by": ["User", "Dashboard"],
        "calls": ["start_live_daemon.ps1"],
    },
    "tradingbot.ml.integration.factory": {
        "title": "ML Strategy Factory",
        "type": "module",
        "district": "ml",
        "importance": 3,
        "production": True,
        "description": "Builds strategy registry — ML or VOL_REGIME based on config flags.",
        "description_fa": "انتخاب مغز ربات — ML یا VOL_REGIME بسته به تنظیمات.",
        "runs_when": "LiveRunner init",
        "files": ["tradingbot/ml/integration/factory.py"],
        "called_by": ["LiveRunner"],
        "calls": ["vol_regime_strategy_registry", "composite_registry"],
    },
    "tradingbot.adapters.mt5_position_manager.Mt5PositionManager": {
        "title": "Mt5PositionManager",
        "type": "class",
        "district": "execution",
        "importance": 4,
        "production": True,
        "description": "Manages open positions: trailing stop, partial TP, emergency close.",
        "description_fa": "نگهبان پوزیشن‌های باز — SL متحرک، برداشت جزئی سود، بستن اضطراری.",
        "runs_when": "After each global cycle",
        "files": ["tradingbot/adapters/mt5_position_manager.py"],
        "called_by": ["TradingKernel"],
        "calls": ["MetaTrader5"],
    },
    "tradingbot.adapters.background_services.BackgroundServices": {
        "title": "BackgroundServices",
        "type": "class",
        "district": "services",
        "importance": 3,
        "production": True,
        "description": "Periodic background tasks during live loop (recovery, optional protector).",
        "description_fa": "کارهای پس‌زمینه while ربات روشن است — مثل بازیابی پوزیشن گم‌شده.",
        "runs_when": "Parallel with live loop",
        "files": ["tradingbot/adapters/background_services.py"],
        "called_by": ["LiveRunner"],
        "calls": ["position_recovery_service"],
    },
    "tradingbot.strategies.vol_regime_signal": {
        "title": "VolRegimeSignal",
        "type": "module",
        "district": "trading",
        "importance": 5,
        "production": True,
        "description": "Core VOL_REGIME signal logic — ATR breakout with regime filter.",
        "description_fa": "فرمول سیگنال فعلی — وقتی نوسان و قیمت شرایط خاص داشته باشد سیگنال می‌دهد.",
        "runs_when": "SignalStage every M5 cycle",
        "files": ["tradingbot/strategies/vol_regime_signal.py"],
        "called_by": ["VolRegimeStrategyRegistry"],
        "calls": ["domain indicators"],
    },
    "tradingbot.ml.trade_quality": {
        "title": "TradeQuality Engine",
        "type": "module",
        "district": "ml",
        "importance": 3,
        "production": True,
        "description": "Scores trade quality — can block low-quality ML signals (TQ gate).",
        "description_fa": "نمره کیفیت معامله — اگر سیگنال ضعیف باشد اجازه نمی‌دهد.",
        "runs_when": "When ML kernel active",
        "files": ["tradingbot/ml/trade_quality/"],
        "called_by": ["RiskGate hold chain"],
        "calls": ["confidence_engine"],
    },
    "tradingbot.services.paper_trade_recorder": {
        "title": "Paper Trading",
        "type": "module",
        "district": "services",
        "importance": 3,
        "production": True,
        "description": "Simulated fills and journal when --paper mode is on.",
        "description_fa": "معامله ساختگی — قیمت واقعی ولی سفارش واقعی به بروکر نمی‌رود.",
        "runs_when": "python -m tradingbot --loop --paper",
        "files": ["tradingbot/services/paper_trade_recorder.py"],
        "called_by": ["Mt5ExecutionAdapter"],
        "calls": ["TradeJournal"],
    },
}

DISTRICT_META = {
    "kernel": {"label": "Kernel", "color": "#2ecc71", "fa": "مغز مرکزی"},
    "application": {"label": "Application", "color": "#3498db", "fa": "اجرای زنده"},
    "pipeline": {"label": "Pipeline", "color": "#9b59b6", "fa": "خط تولید"},
    "adapters": {"label": "Adapters", "color": "#e67e22", "fa": "اتصال به دنیا"},
    "execution": {"label": "Execution", "color": "#e74c3c", "fa": "اجرای سفارش"},
    "risk": {"label": "Risk", "color": "#f39c12", "fa": "مدیریت ریسک"},
    "data": {"label": "Data", "color": "#1abc9c", "fa": "داده بازار"},
    "trading": {"label": "Trading", "color": "#d4a017", "fa": "استراتژی"},
    "monitoring": {"label": "Monitoring", "color": "#7cb8ff", "fa": "نظارت"},
    "services": {"label": "Services", "color": "#95a5a6", "fa": "سرویس‌ها"},
    "config": {"label": "Configuration", "color": "#bdc3c7", "fa": "تنظیمات"},
    "backtest": {"label": "Backtest", "color": "#8e44ad", "fa": "بک‌تست"},
    "ml": {"label": "ML", "color": "#16a085", "fa": "یادگیری ماشین"},
    "research": {"label": "Research", "color": "#636e72", "fa": "تحقیق (غیر production)"},
    "domain": {"label": "Domain", "color": "#fdcb6e", "fa": "قوانین خالص"},
    "ports": {"label": "Ports", "color": "#74b9ff", "fa": "قراردادها"},
    "scripts": {"label": "Scripts", "color": "#a29bfe", "fa": "اسکریپت‌های کمکی"},
}


@dataclass
class Node:
    id: str
    label: str
    node_type: str  # folder|module|class|function|entry
    district: str
    file_path: str = ""
    production: bool = True
    research: bool = False
    importance: int = 1
    in_degree: int = 0
    out_degree: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    edge_type: str  # imports|calls|creates|uses|inherits|reads|writes
    label: str = ""


def _district_from_path(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    if parts[0] == "scripts":
        return "scripts"
    if len(parts) < 2:
        return "kernel"
    second = parts[1]
    if second == "ml" and len(parts) > 2 and parts[2] == "research":
        return "research"
    mapping = {
        "kernel": "kernel",
        "application": "application",
        "pipeline": "pipeline",
        "adapters": "adapters",
        "execution": "execution",
        "services": "services",
        "config": "config",
        "backtest": "backtest",
        "ml": "ml",
        "domain": "domain",
        "ports": "ports",
        "strategies": "trading",
        "accounting": "services",
        "infra": "services",
    }
    return mapping.get(second, "adapters")


def _is_research(rel: str) -> bool:
    r = rel.replace("\\", "/")
    return "/ml/research/" in r or "/phase" in r.lower() and "/ml/" in r


def _module_id(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    return p.replace("/", ".")


def scan_python_files() -> list[Path]:
    files: list[Path] = []
    for root_name in SCAN_ROOTS:
        base = ROOT / root_name
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if any(part in SKIP_PARTS for part in p.parts):
                continue
            files.append(p)
    return files


def parse_file(path: Path) -> tuple[list[str], list[tuple[str, str]], list[str], list[str]]:
    """Returns (imports, local_calls, classes, functions)."""
    rel = str(path.relative_to(ROOT)).replace("\\", "/")
    module = _module_id(rel)
    imports: list[str] = []
    calls: list[tuple[str, str]] = []
    classes: list[str] = []
    functions: list[str] = []

    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src, filename=str(path))
    except Exception:
        return imports, calls, classes, functions

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
        elif isinstance(node, ast.ClassDef) and node.col_offset == 0:
            classes.append(f"{module}.{node.name}")
        elif isinstance(node, ast.FunctionDef) and node.col_offset == 0:
            functions.append(f"{module}.{node.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                calls.append((module, func.id))
            elif isinstance(func, ast.Attribute):
                calls.append((module, func.attr))

    return imports, calls, classes, functions


def resolve_import(imp: str, from_module: str, known: set[str]) -> str | None:
    candidates = [imp]
    if from_module:
        base = from_module.rsplit(".", 1)[0] if "." in from_module else from_module
        candidates.append(f"{base}.{imp}")
    parts = from_module.split(".") if from_module else []
    for i in range(len(parts), 0, -1):
        candidates.append(".".join(parts[:i]) + "." + imp)
    for c in candidates:
        if c in known:
            return c
        # prefix match module
        for k in known:
            if k == c or k.startswith(c + "."):
                return k
    if imp.startswith("tradingbot") or imp.startswith("scripts") or imp.startswith("engine"):
        return imp.replace("/", ".")
    return None


def build_graph() -> tuple[dict[str, Node], list[Edge]]:
    py_files = scan_python_files()
    known_modules: set[str] = set()
    file_to_module: dict[str, str] = {}

    for p in py_files:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        mid = _module_id(rel)
        known_modules.add(mid)
        file_to_module[rel] = mid

    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    import_counter: Counter[str] = Counter()
    imported_by: Counter[str] = Counter()

    # Folder nodes
    folders_seen: set[str] = set()
    for p in py_files:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        parts = Path(rel).parts
        for i in range(1, len(parts)):
            folder_rel = "/".join(parts[:i])
            if folder_rel not in folders_seen:
                folders_seen.add(folder_rel)
                fid = f"folder:{folder_rel}"
                nodes[fid] = Node(
                    id=fid,
                    label=parts[i - 1] if i else parts[0],
                    node_type="folder",
                    district=_district_from_path(folder_rel),
                    file_path=folder_rel,
                    production=not _is_research(folder_rel),
                    research=_is_research(folder_rel),
                    importance=2 if i <= 2 else 1,
                )

    # Module + class + function nodes
    parsed_data: dict[str, tuple] = {}
    for p in py_files:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        mid = _module_id(rel)
        district = _district_from_path(rel)
        prod = not _is_research(rel)
        research = _is_research(rel)

        nodes[mid] = Node(
            id=mid,
            label=Path(rel).stem,
            node_type="module",
            district=district,
            file_path=rel,
            production=prod,
            research=research,
            importance=3 if prod and district in ("kernel", "application", "pipeline") else 1,
        )

        imports, calls, classes, functions = parse_file(p)
        parsed_data[mid] = (imports, calls, classes, functions)

        for cid in classes[:8]:
            if cid not in nodes:
                cname = cid.rsplit(".", 1)[-1]
                meta = CURATED.get(cid, {})
                nodes[cid] = Node(
                    id=cid,
                    label=cname,
                    node_type="class",
                    district=district,
                    file_path=rel,
                    production=prod,
                    research=research,
                    importance=meta.get("importance", 2),
                    meta=meta,
                )
                edges.append(Edge(mid, cid, "contains", "contains"))

        for fid in functions[:5]:
            fn_id = fid
            if fn_id not in nodes and any(
                x in fid.lower() for x in ("run_", "execute", "evaluate", "build_", "create_", "validate", "main")
            ):
                nodes[fn_id] = Node(
                    id=fn_id,
                    label=fid.rsplit(".", 1)[-1],
                    node_type="function",
                    district=district,
                    file_path=rel,
                    production=prod,
                    research=research,
                    importance=2,
                )
                edges.append(Edge(mid, fn_id, "contains", "contains"))

    # Import edges
    for mid, (imports, calls, _c, _f) in parsed_data.items():
        src_district = nodes[mid].district if mid in nodes else "adapters"
        for imp in imports:
            resolved = resolve_import(imp, mid, known_modules)
            if not resolved:
                continue
            if resolved not in nodes and not resolved.startswith("folder:"):
                continue
            tgt = resolved
            if tgt in nodes:
                edges.append(Edge(mid, tgt, "imports", "imports"))
                import_counter[mid] += 1
                imported_by[tgt] += 1
                # folder hierarchy
                src_folder = str(nodes[mid].file_path).rsplit("/", 1)[0]
                tgt_folder = str(nodes[tgt].file_path).rsplit("/", 1)[0] if nodes[tgt].file_path else ""
                sfid = f"folder:{src_folder}"
                tfid = f"folder:{tgt_folder}"
                if sfid in nodes and tfid in nodes and sfid != tfid:
                    edges.append(Edge(sfid, tfid, "uses", "uses"))

    # Curated edges
    CURATED_EDGES = [
        ("tradingbot.application.live_runner", "tradingbot.kernel.trading_kernel", "creates", "creates"),
        ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.data_stage", "creates", "creates"),
        ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.risk_stage", "creates", "creates"),
        ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.execution_stage", "creates", "creates"),
        ("tradingbot.pipeline.risk_stage", "tradingbot.adapters.risk_gate", "calls", "calls"),
        ("tradingbot.pipeline.execution_stage", "tradingbot.adapters.mt5_execution", "calls", "calls"),
        ("tradingbot.pipeline.data_stage", "tradingbot.adapters.mt5_market_data", "calls", "calls"),
        ("tradingbot.application.live_runner", "tradingbot.services.kill_switch", "creates", "creates"),
        ("tradingbot.application.live_runner", "tradingbot.services.startup_validator", "calls", "calls"),
        ("tradingbot.adapters.risk_gate", "tradingbot.domain.live_gates", "uses", "reads"),
        ("tradingbot.adapters.mt5_execution", "tradingbot.services.trade_journal", "writes", "writes"),
        ("scripts.start_bot", "scripts.start_live_daemon", "calls", "calls"),
    ]
    for s, t, et, lb in CURATED_EDGES:
        if s not in nodes:
            nodes[s] = Node(s, s.rsplit(".", 1)[-1], "module", "scripts", s.replace(".", "/") + ".py", True, False, 3)
        if t not in nodes:
            pass
        else:
            edges.append(Edge(s, t, et, lb))

    # Merge curated metadata
    for cid, meta in CURATED.items():
        if cid in nodes:
            nodes[cid].meta = {**meta, **nodes[cid].meta}
            nodes[cid].importance = meta.get("importance", nodes[cid].importance)
        else:
            district = meta.get("district", "kernel")
            nodes[cid] = Node(
                id=cid,
                label=meta.get("title", cid.rsplit(".", 1)[-1]),
                node_type=meta.get("type", "class"),
                district=district,
                file_path=meta.get("files", [""])[0],
                production=meta.get("production", True),
                research=False,
                importance=meta.get("importance", 3),
                meta=meta,
            )

    # Degree counts
    out_d: Counter[str] = Counter()
    in_d: Counter[str] = Counter()
    for e in edges:
        out_d[e.source] += 1
        in_d[e.target] += 1
    for nid, n in nodes.items():
        n.in_degree = in_d[nid]
        n.out_degree = out_d[nid]

    return nodes, edges, import_counter, imported_by, py_files


def node_to_json(n: Node) -> dict:
    m = n.meta or {}
    return {
        "id": n.id,
        "label": n.label,
        "type": n.node_type,
        "district": n.district,
        "districtLabel": DISTRICT_META.get(n.district, {}).get("label", n.district),
        "color": DISTRICT_META.get(n.district, {}).get("color", "#888"),
        "file": n.file_path,
        "production": n.production,
        "research": n.research,
        "importance": n.importance,
        "inDegree": n.in_degree,
        "outDegree": n.out_degree,
        "description": m.get("description", f"Module in {n.district} district."),
        "descriptionFa": m.get("description_fa", f"بخشی از ربات در منطقه {DISTRICT_META.get(n.district, {}).get('fa', n.district)}."),
        "runsWhen": m.get("runs_when", "On demand"),
        "riskIfRemoved": m.get("risk_if_removed", "Low — auxiliary component."),
        "calledBy": m.get("called_by", []),
        "calls": m.get("calls", []),
        "files": m.get("files", [n.file_path] if n.file_path else []),
        "stages": m.get("stages", []),
    }


def edge_to_json(e: Edge) -> dict:
    return {"source": e.source, "target": e.target, "type": e.edge_type, "label": e.label or e.edge_type}


def filter_graph(nodes: dict, edges: list, predicate) -> tuple[list, list]:
    ids = {nid for nid, n in nodes.items() if predicate(n)}
    ns = [nodes[i] for i in ids]
    es = [e for e in edges if e.source in ids and e.target in ids]
    return ns, es


GRAPH_FILTERS = {
    "architecture": lambda n: n.district in ("kernel", "application", "pipeline", "ports") and n.node_type != "function",
    "ml": lambda n: n.district in ("ml",) or "ml." in n.id,
    "trading": lambda n: n.district == "trading" or "strateg" in n.id or "signal" in n.id.lower(),
    "execution": lambda n: n.district == "execution" or "execution" in n.id or "mt5_execution" in n.id,
    "risk": lambda n: n.district == "risk" or "risk" in n.id.lower() or "gate" in n.id.lower(),
    "data": lambda n: n.district == "data" or "market_data" in n.id or "dataset" in n.id,
    "research": lambda n: n.research,
    "backtest": lambda n: n.district == "backtest" or "backtest" in n.id,
    "monitoring": lambda n: n.district == "monitoring" or n.district == "services",
    "services": lambda n: n.district == "services" or n.id.startswith("tradingbot.services"),
    "configuration": lambda n: n.district in ("config", "scripts") or "config" in n.id,
}


def to_mermaid(nodes: list[Node], edges: list[Edge], title: str) -> str:
    lines = ["flowchart TB", f"    %% {title}"]
    shown = {n.id for n in nodes[:MAX_NODES_MERMAID]}
    id_map = {}
    for i, n in enumerate(nodes[:MAX_NODES_MERMAID]):
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", n.id)[:40] + str(i)
        id_map[n.id] = safe
        shape = "{{" + n.label + "}}" if n.node_type == "folder" else "[" + n.label + "]"
        lines.append(f"    {safe}{shape}")
    for e in edges:
        if e.source in shown and e.target in shown:
            ls = id_map.get(e.source, "x")
            lt = id_map.get(e.target, "y")
            lines.append(f"    {ls} -->|{e.label}| {lt}")
    return "\n".join(lines)


SUBSYSTEM_ROOTS = [
    "tradingbot.kernel.trading_kernel",
    "tradingbot.adapters.risk_gate",
    "tradingbot.application.live_runner",
    "tradingbot.adapters.mt5_execution",
    "tradingbot.adapters.mt5_market_data",
    "tradingbot.services.kill_switch",
    "tradingbot.services.trade_journal",
    "tradingbot.backtest.engine",
    "tradingbot.ml.integration.factory",
    "tradingbot.pipeline",
    "tradingbot.services.startup_validator",
]


def subsystem_neighborhood(root: str, nodes: dict, edges: list, depth: int = 2) -> tuple[list, list]:
    frontier = {root}
    seen = set(frontier)
    for _ in range(depth):
        nxt = set()
        for e in edges:
            if e.source in frontier:
                nxt.add(e.target)
            if e.target in frontier:
                nxt.add(e.source)
        nxt -= seen
        seen |= nxt
        frontier = nxt
    seen.add(root)
    ns = [nodes[i] for i in seen if i in nodes][:MAX_NODES_MERMAID]
    ids = {n.id for n in ns}
    es = [e for e in edges if e.source in ids and e.target in ids]
    return ns, es


TIMELINE = [
    {
        "step": 1, "id": "start", "label": "User starts bot", "labelFa": "کاربر START_BOT را می‌زند", "icon": "▶",
        "roots": ["scripts.start_bot"],
        "files": ["start/START_BOT.bat", "scripts/start_bot.py", "scripts/start_live_daemon.ps1"],
        "flow": [("scripts.start_bot", "scripts.run_live_watchdog", "calls")],
    },
    {
        "step": 2, "id": "watchdog", "label": "Watchdog launches", "labelFa": "نگهبان پروسه ربات را بالا می‌آورد", "icon": "🔄",
        "roots": ["scripts.run_live_watchdog"],
        "files": ["scripts/run_live_watchdog.py", "scripts/stop_live_daemon.ps1", "logs/watchdog.log"],
        "flow": [("scripts.run_live_watchdog", "tradingbot.application.live_runner", "starts")],
    },
    {
        "step": 3, "id": "live_runner", "label": "LiveRunner init", "labelFa": "راننده زنده آماده می‌شود", "icon": "🚀",
        "roots": ["tradingbot.application.live_runner", "tradingbot.application.live_runner.LiveRunner"],
        "files": ["tradingbot/application/live_runner.py"],
        "flow": [
            ("tradingbot.application.live_runner", "tradingbot.kernel.trading_kernel", "creates"),
            ("tradingbot.application.live_runner", "tradingbot.services.kill_switch", "creates"),
        ],
    },
    {
        "step": 4, "id": "startup", "label": "Startup validation", "labelFa": "چک MT5 و تنظیمات", "icon": "✓",
        "roots": ["tradingbot.services.startup_validator"],
        "files": ["tradingbot/services/startup_validator.py", "data/startup/startup_report.json"],
        "flow": [
            ("tradingbot.application.live_runner", "tradingbot.services.startup_validator", "calls"),
            ("tradingbot.services.startup_validator", "tradingbot.adapters.mt5_health", "uses"),
            ("tradingbot.services.startup_validator", "tradingbot.services.demo_account_guard", "uses"),
        ],
    },
    {
        "step": 5, "id": "mt5", "label": "MT5 connection", "labelFa": "اتصال به MetaTrader 5", "icon": "🔌",
        "roots": ["tradingbot.adapters.mt5_utils", "tradingbot.adapters.mt5_market_data"],
        "files": ["tradingbot/adapters/mt5_utils.py", "tradingbot/adapters/mt5_health.py", "logs/mt5_ipc.lock"],
        "flow": [
            ("tradingbot.adapters.mt5_market_data", "tradingbot.adapters.mt5_utils", "uses"),
            ("tradingbot.adapters.mt5_execution", "tradingbot.adapters.mt5_utils", "uses"),
        ],
    },
    {
        "step": 6, "id": "models", "label": "Load strategies", "labelFa": "بارگذاری VOL_REGIME / ML", "icon": "🧠",
        "roots": ["tradingbot.ml.integration.factory", "tradingbot.adapters.vol_regime_strategy_registry"],
        "files": [
            "tradingbot/ml/integration/factory.py",
            "tradingbot/adapters/vol_regime_strategy_registry.py",
            "tradingbot/strategies/vol_regime_signal.py",
        ],
        "flow": [
            ("tradingbot.application.live_runner", "tradingbot.ml.integration.factory", "calls"),
            ("tradingbot.ml.integration.factory", "tradingbot.adapters.vol_regime_strategy_registry", "creates"),
            ("tradingbot.adapters.vol_regime_strategy_registry", "tradingbot.strategies.vol_regime_signal", "uses"),
        ],
    },
    {
        "step": 7, "id": "kernel", "label": "TradingKernel start", "labelFa": "موتور اصلی روشن", "icon": "⚙",
        "roots": ["tradingbot.kernel.trading_kernel", "tradingbot.kernel.trading_kernel.TradingKernel"],
        "files": ["tradingbot/kernel/trading_kernel.py"],
        "flow": [
            ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.data_stage", "creates"),
            ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.signal_stage", "creates"),
            ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.risk_stage", "creates"),
            ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.execution_stage", "creates"),
        ],
    },
    {
        "step": 8, "id": "cycle", "label": "Global cycle", "labelFa": "شروع چرخه ۳۰ ثانیه‌ای", "icon": "🔁",
        "roots": ["tradingbot.kernel.trading_kernel"],
        "files": ["tradingbot/kernel/trading_kernel.py"],
        "flow": [
            ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.data_stage", "runs"),
            ("tradingbot.pipeline.data_stage", "tradingbot.pipeline.indicator_stage", "then"),
            ("tradingbot.pipeline.indicator_stage", "tradingbot.pipeline.signal_stage", "then"),
            ("tradingbot.pipeline.signal_stage", "tradingbot.pipeline.risk_stage", "then"),
            ("tradingbot.pipeline.risk_stage", "tradingbot.pipeline.execution_stage", "then"),
        ],
    },
    {
        "step": 9, "id": "candle", "label": "New candle data", "labelFa": "دریافت کندل جدید M5", "icon": "📊",
        "roots": ["tradingbot.pipeline.data_stage", "tradingbot.adapters.mt5_market_data"],
        "files": ["tradingbot/pipeline/data_stage.py", "tradingbot/adapters/mt5_market_data.py"],
        "flow": [
            ("tradingbot.pipeline.data_stage", "tradingbot.adapters.mt5_market_data", "calls"),
            ("tradingbot.adapters.mt5_market_data", "tradingbot.adapters.mt5_utils", "reads"),
        ],
    },
    {
        "step": 10, "id": "features", "label": "Indicators", "labelFa": "محاسبه اندیکاتورها", "icon": "📈",
        "roots": ["tradingbot.pipeline.indicator_stage", "tradingbot.adapters.indicator_engine"],
        "files": ["tradingbot/pipeline/indicator_stage.py", "tradingbot/adapters/indicator_engine.py"],
        "flow": [
            ("tradingbot.pipeline.indicator_stage", "tradingbot.adapters.indicator_engine", "calls"),
        ],
    },
    {
        "step": 11, "id": "signal", "label": "Generate signal", "labelFa": "ساخت سیگنال خرید/فروش", "icon": "💡",
        "roots": ["tradingbot.pipeline.signal_stage", "tradingbot.strategies.vol_regime_signal"],
        "files": [
            "tradingbot/pipeline/signal_stage.py",
            "tradingbot/strategies/vol_regime_signal.py",
            "tradingbot/adapters/vol_regime_strategy_registry.py",
        ],
        "flow": [
            ("tradingbot.pipeline.signal_stage", "tradingbot.adapters.vol_regime_strategy_registry", "calls"),
            ("tradingbot.adapters.vol_regime_strategy_registry", "tradingbot.strategies.vol_regime_signal", "uses"),
        ],
    },
    {
        "step": 12, "id": "risk", "label": "Risk gate", "labelFa": "نگهبان ریسک بررسی می‌کند", "icon": "🛡",
        "roots": ["tradingbot.pipeline.risk_stage", "tradingbot.adapters.risk_gate"],
        "files": [
            "tradingbot/pipeline/risk_stage.py",
            "tradingbot/adapters/risk_gate.py",
            "tradingbot/domain/live_gates.py",
            "tradingbot/services/live_risk_tracker.py",
        ],
        "flow": [
            ("tradingbot.pipeline.risk_stage", "tradingbot.adapters.risk_gate", "calls"),
            ("tradingbot.adapters.risk_gate", "tradingbot.domain.live_gates", "reads"),
            ("tradingbot.adapters.risk_gate", "tradingbot.services.live_risk_tracker", "uses"),
        ],
    },
    {
        "step": 13, "id": "exec", "label": "Execution", "labelFa": "ارسال سفارش به MT5", "icon": "💰",
        "roots": ["tradingbot.pipeline.execution_stage", "tradingbot.adapters.mt5_execution"],
        "files": [
            "tradingbot/pipeline/execution_stage.py",
            "tradingbot/adapters/mt5_execution.py",
            "tradingbot/services/mt5_order_guard.py",
        ],
        "flow": [
            ("tradingbot.pipeline.execution_stage", "tradingbot.adapters.mt5_execution", "calls"),
            ("tradingbot.adapters.mt5_execution", "tradingbot.services.mt5_order_guard", "uses"),
        ],
    },
    {
        "step": 14, "id": "pm", "label": "Position manager", "labelFa": "مدیریت SL/TP/trailing", "icon": "📍",
        "roots": ["tradingbot.adapters.mt5_position_manager"],
        "files": ["tradingbot/adapters/mt5_position_manager.py", "tradingbot/services/position_protector.py"],
        "flow": [
            ("tradingbot.kernel.trading_kernel", "tradingbot.adapters.mt5_position_manager", "calls"),
        ],
    },
    {
        "step": 15, "id": "journal", "label": "Trade journal", "labelFa": "ثبت در دفترچه", "icon": "📝",
        "roots": ["tradingbot.services.trade_journal"],
        "files": ["tradingbot/services/trade_journal.py", "data/trade_journal.db"],
        "flow": [
            ("tradingbot.kernel.trading_kernel", "tradingbot.services.trade_journal", "writes"),
            ("tradingbot.adapters.mt5_execution", "tradingbot.services.trade_journal", "writes"),
        ],
    },
    {
        "step": 16, "id": "repeat", "label": "Repeat", "labelFa": "تکرار تا توقف", "icon": "∞",
        "roots": ["tradingbot.kernel.trading_kernel", "tradingbot.application.live_runner"],
        "files": ["tradingbot/kernel/trading_kernel.py", "tradingbot/application/live_runner.py"],
        "flow": [
            ("tradingbot.application.live_runner", "tradingbot.kernel.trading_kernel", "loops"),
            ("tradingbot.kernel.trading_kernel", "tradingbot.pipeline.data_stage", "repeats"),
        ],
    },
]


def build_timeline_graphs(
    timeline: list[dict],
    nodes: dict[str, Node],
    edges: list[Edge],
    json_by_id: dict[str, dict],
) -> dict[str, dict]:
    """Precompute subgraph per timeline step."""
    edge_list = edges
    out: dict[str, dict] = {}

    def resolve_id(nid: str) -> str | None:
        if nid in json_by_id:
            return nid
        for k in json_by_id:
            if k == nid or k.endswith("." + nid.split(".")[-1]) or nid in k:
                return k
        return None

    for step in timeline:
        sid = step["id"]
        seed: set[str] = set()
        for r in step.get("roots", []):
            rid = resolve_id(r)
            if rid:
                seed.add(rid)
            elif r in json_by_id:
                seed.add(r)

        # Match modules by file path
        for fp in step.get("files", []):
            stem = Path(fp).stem
            for nid, jn in json_by_id.items():
                if jn.get("file") == fp or (jn.get("file", "").endswith(stem + ".py")):
                    seed.add(nid)

        seen = set(seed)
        for _ in range(2):
            nxt: set[str] = set()
            for e in edge_list:
                if e.source in seen:
                    nxt.add(e.target)
                if e.target in seen:
                    nxt.add(e.source)
            nxt -= seen
            seen |= nxt

        # Prefer modules/classes, skip folders for clarity
        node_objs = []
        for nid in seen:
            if nid not in json_by_id:
                continue
            jn = json_by_id[nid]
            if jn.get("type") == "folder":
                continue
            node_objs.append(jn)
        node_objs.sort(key=lambda n: (-n.get("importance", 1), n.get("label", "")))
        node_objs = node_objs[:28]
        ids = {n["id"] for n in node_objs}

        step_edges = []
        for s, t, lb in step.get("flow", []):
            rs, rt = resolve_id(s), resolve_id(t)
            if rs and rt and rs in ids and rt in ids:
                step_edges.append({"source": rs, "target": rt, "type": "flow", "label": lb})

        for e in edge_list:
            if e.source in ids and e.target in ids:
                step_edges.append(edge_to_json(e))

        # Dedupe edges
        seen_e: set[tuple] = set()
        deduped = []
        for e in step_edges:
            key = (e["source"], e["target"], e.get("label", ""))
            if key not in seen_e:
                seen_e.add(key)
                deduped.append(e)

        out[sid] = {
            "step": step,
            "nodes": node_objs,
            "edges": deduped[:40],
            "files": step.get("files", []),
        }
    return out

SEQUENCES = {
    "buy_trade": """sequenceDiagram
    participant U as User/MT5
    participant LR as LiveRunner
    participant K as TradingKernel
    participant D as DataStage
    participant S as SignalStage
    participant R as RiskStage
    participant E as ExecutionStage
    participant MT5 as MetaTrader5
    participant J as TradeJournal
    LR->>K: run_global_cycle()
    K->>D: fetch OHLCV
    D->>MT5: copy_rates
    K->>S: generate signal BUY
    S-->>K: TradingSignal BUY
    K->>R: evaluate risk
    R-->>K: allowed + lot
    K->>E: execute order
    E->>MT5: order_send BUY
    MT5-->>E: ticket filled
    E->>J: log execution
""",
    "sell_trade": """sequenceDiagram
    participant K as TradingKernel
    participant S as SignalStage
    participant R as RiskStage
    participant E as ExecutionStage
    participant MT5 as MetaTrader5
    K->>S: VOL_REGIME signal
    S-->>K: TradingSignal SELL
    K->>R: evaluate
    R-->>K: allowed
    K->>E: execute SELL
    E->>MT5: order_send
    MT5-->>E: filled
""",
    "rejected_trade": """sequenceDiagram
    participant K as TradingKernel
    participant S as SignalStage
    participant R as RiskStage
    participant J as TradeJournal
    K->>S: signal generated
    S-->>K: signal present
    K->>R: evaluate
    R-->>K: blocked (spread/cooldown/etc)
    K->>J: log cycle blocked
    Note over K: No order sent
""",
    "cooldown": """sequenceDiagram
    participant R as RiskGate
    participant T as LiveRiskTracker
    participant K as TradingKernel
    K->>R: evaluate new signal
    R->>T: check entry cooldown M5
    T-->>R: cooldown active
    R-->>K: RiskDecision blocked
""",
    "daily_loss_stop": """sequenceDiagram
    participant KS as KillSwitchService
    participant R as LiveRiskTracker
    participant K as TradingKernel
    loop every cycle
        K->>KS: check account
        KS->>R: daily PnL vs limit
        R-->>KS: limit breached
        KS-->>K: EMERGENCY_STOP
    end
""",
    "trailing_stop": """sequenceDiagram
    participant K as TradingKernel
    participant PM as Mt5PositionManager
    participant MT5 as MetaTrader5
    K->>PM: manage_positions()
    PM->>MT5: positions_get
    PM->>PM: compute trailing SL
    PM->>MT5: order_send modify SL
""",
    "partial_tp": """sequenceDiagram
    participant PM as Mt5PositionManager
    participant MT5 as MetaTrader5
    PM->>MT5: check profit vs partial level
    PM->>MT5: close partial volume
    PM->>MT5: move SL to breakeven
""",
    "emergency_close": """sequenceDiagram
    participant KS as KillSwitchService
    participant K as TradingKernel
    participant PM as Mt5PositionManager
    participant MT5 as MetaTrader5
    KS->>K: emergency flag set
    K->>PM: close all bot positions
    PM->>MT5: close each ticket
""",
    "friday_close": """sequenceDiagram
    participant R as RiskGate
    participant G as live_gates
    participant K as TradingKernel
    K->>R: evaluate signal
    R->>G: check_friday_gate
    G-->>R: no new entries
    R-->>K: blocked friday window
""",
}


def main() -> None:
    print("Building Architecture Atlas (read-only scan)...")
    for sub in ("json", "json/subsystems", "graphs", "mermaid", "mermaid/sequences"):
        (ATLAS / sub).mkdir(parents=True, exist_ok=True)

    nodes, edges, import_counter, imported_by, py_files = build_graph()

    all_nodes_json = [node_to_json(n) for n in nodes.values()]
    all_edges_json = [edge_to_json(e) for e in edges]

    # Heatmaps
    prod_files = [str(p.relative_to(ROOT)).replace("\\", "/") for p in py_files if not _is_research(str(p.relative_to(ROOT)))]
    research_files = [str(p.relative_to(ROOT)).replace("\\", "/") for p in py_files if _is_research(str(p.relative_to(ROOT)))]

    module_nodes = {k: v for k, v in nodes.items() if v.node_type == "module"}
    most_connected = sorted(module_nodes.values(), key=lambda n: n.in_degree + n.out_degree, reverse=True)[:25]
    most_imported = sorted(module_nodes.values(), key=lambda n: n.in_degree, reverse=True)[:25]
    most_importers = sorted(module_nodes.values(), key=lambda n: n.out_degree, reverse=True)[:25]
    central = [n.id for n in most_connected[:10]]
    unused = [n.id for n in module_nodes.values() if n.in_degree == 0 and n.out_degree == 0 and n.production][:50]

    heatmaps = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "totalPythonFiles": len(py_files),
            "totalNodes": len(nodes),
            "totalEdges": len(edges),
            "productionFiles": len(prod_files),
            "researchFiles": len(research_files),
        },
        "mostConnected": [{"id": n.id, "label": n.label, "score": n.in_degree + n.out_degree} for n in most_connected],
        "mostImported": [{"id": n.id, "label": n.label, "inDegree": n.in_degree} for n in most_imported],
        "mostImporters": [{"id": n.id, "label": n.label, "outDegree": n.out_degree} for n in most_importers],
        "mostCentral": central,
        "mostDangerous": [
            "tradingbot.adapters.mt5_execution",
            "tradingbot.adapters.risk_gate",
            "tradingbot.kernel.trading_kernel",
            "tradingbot.services.kill_switch",
        ],
        "unusedModules": unused[:30],
        "deadModules": unused[:15],
        "researchOnly": [n.id for n in nodes.values() if n.research and n.node_type == "module"][:40],
        "productionModules": [n.id for n in nodes.values() if n.production and not n.research and n.node_type == "module"][:60],
    }

    master = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "projectRoot": str(ROOT.name),
        "nodes": all_nodes_json,
        "edges": all_edges_json,
        "districts": DISTRICT_META,
        "timeline": TIMELINE,
        "heatmaps": heatmaps,
    }

    (ATLAS / "json" / "master.json").write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")

    # Category graphs
    graphs_dir = ATLAS / "graphs"
    mermaid_dir = ATLAS / "mermaid"
    for name, pred in GRAPH_FILTERS.items():
        ns, es = filter_graph(nodes, edges, pred)
        ns = ns[:MAX_NODES_MERMAID]
        ids = {n.id for n in ns}
        es = [e for e in es if e.source in ids and e.target in ids][:200]
        payload = {"name": name, "nodes": [node_to_json(n) for n in ns], "edges": [edge_to_json(e) for e in es]}
        (graphs_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (mermaid_dir / f"{name}.mmd").write_text(to_mermaid(ns, es, name), encoding="utf-8")

    # Subsystem graphs
    sub_dir = ATLAS / "json" / "subsystems"
    for root in SUBSYSTEM_ROOTS:
        ns, es = subsystem_neighborhood(root, nodes, edges)
        slug = root.replace(".", "_")
        payload = {"root": root, "nodes": [node_to_json(n) for n in ns], "edges": [edge_to_json(e) for e in es]}
        (sub_dir / f"{slug}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (mermaid_dir / f"subsystem_{slug}.mmd").write_text(to_mermaid(ns, es, root), encoding="utf-8")

    # Timeline mermaid
    tl_lines = ["flowchart TD"]
    for i, step in enumerate(TIMELINE):
        sid = f"s{step['step']}"
        tl_lines.append(f'    {sid}["{step["label"]}"]')
        if i > 0:
            tl_lines.append(f"    s{TIMELINE[i-1]['step']} --> s{step['step']}")
    (mermaid_dir / "timeline.mmd").write_text("\n".join(tl_lines), encoding="utf-8")
    (ATLAS / "json" / "timeline.json").write_text(json.dumps(TIMELINE, ensure_ascii=False, indent=2), encoding="utf-8")

    json_by_id = {n["id"]: n for n in all_nodes_json}
    timeline_graphs = build_timeline_graphs(TIMELINE, nodes, edges, json_by_id)
    (ATLAS / "json" / "timeline_graphs.json").write_text(
        json.dumps(timeline_graphs, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Sequences
    seq_dir = mermaid_dir / "sequences"
    seq_json = {}
    for name, body in SEQUENCES.items():
        (seq_dir / f"{name}.mmd").write_text(body, encoding="utf-8")
        seq_json[name] = body
    (ATLAS / "json" / "sequences.json").write_text(json.dumps(seq_json, ensure_ascii=False, indent=2), encoding="utf-8")

    (ATLAS / "json" / "heatmaps.json").write_text(json.dumps(heatmaps, ensure_ascii=False, indent=2), encoding="utf-8")

    # Architecture map tree
    tree = {
        "label": "Desktop",
        "children": [
            {
                "label": "TradingBot new",
                "children": [
                    {
                        "label": "start/",
                        "meta": "Launchers (START_BOT.bat)",
                        "mapKey": "folder:start",
                        "roots": ["scripts.start_bot", "scripts.run_live_watchdog"],
                    },
                    {
                        "label": "tradingbot/",
                        "mapKey": "folder:tradingbot",
                        "roots": [
                            "tradingbot.kernel.trading_kernel",
                            "tradingbot.application.live_runner",
                        ],
                        "children": [
                            {
                                "label": "application/",
                                "children": [
                                    {
                                        "label": "LiveRunner",
                                        "id": "tradingbot.application.live_runner.LiveRunner",
                                    }
                                ],
                            },
                            {
                                "label": "kernel/",
                                "children": [
                                    {
                                        "label": "TradingKernel",
                                        "id": "tradingbot.kernel.trading_kernel.TradingKernel",
                                    }
                                ],
                            },
                            {
                                "label": "pipeline/",
                                "mapKey": "folder:pipeline",
                                "roots": [
                                    "tradingbot.pipeline.data_stage",
                                    "tradingbot.pipeline.signal_stage",
                                    "tradingbot.pipeline.risk_stage",
                                    "tradingbot.pipeline.execution_stage",
                                ],
                                "children": [
                                    {"label": "DataStage", "id": "tradingbot.pipeline.data_stage.DataStage"},
                                    {"label": "IndicatorStage", "id": "tradingbot.pipeline.indicator_stage.IndicatorStage"},
                                    {"label": "SignalStage", "id": "tradingbot.pipeline.signal_stage.SignalStage"},
                                    {"label": "SignalFilterStage", "id": "tradingbot.pipeline.signal_filter_stage.SignalFilterStage"},
                                    {"label": "RiskStage", "id": "tradingbot.pipeline.risk_stage.RiskStage"},
                                    {"label": "ExecutionStage", "id": "tradingbot.pipeline.execution_stage.ExecutionStage"},
                                ],
                            },
                            {
                                "label": "adapters/",
                                "children": [
                                    {"label": "Mt5MarketData", "id": "tradingbot.adapters.mt5_market_data"},
                                    {"label": "Mt5Execution", "id": "tradingbot.adapters.mt5_execution.Mt5ExecutionAdapter"},
                                    {"label": "RiskGate", "id": "tradingbot.adapters.risk_gate.RiskGate"},
                                    {"label": "VolRegime", "id": "tradingbot.adapters.vol_regime_strategy_registry"},
                                    {"label": "PositionManager", "id": "tradingbot.adapters.mt5_position_manager"},
                                ],
                            },
                            {
                                "label": "services/",
                                "children": [
                                    {"label": "KillSwitch", "id": "tradingbot.services.kill_switch.KillSwitchService"},
                                    {"label": "TradeJournal", "id": "tradingbot.services.trade_journal.TradeJournal"},
                                    {"label": "StartupValidator", "id": "tradingbot.services.startup_validator"},
                                ],
                            },
                        ],
                    },
                    {
                        "label": "scripts/",
                        "meta": "Ops & diagnostics",
                        "mapKey": "folder:scripts",
                        "roots": ["scripts.start_bot", "scripts.run_live_watchdog", "scripts.status_snapshot"],
                    },
                    {
                        "label": "docs/architecture_atlas/",
                        "meta": "This explorer",
                        "mapKey": "folder:atlas",
                        "roots": [],
                    },
                ],
            }
        ],
    }
    (ATLAS / "json" / "architecture_map.json").write_text(json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")

    # Offline bundle for file:// (browser blocks fetch on local files)
    graphs_payload: dict[str, dict] = {}
    for name in GRAPH_FILTERS:
        p = graphs_dir / f"{name}.json"
        if p.is_file():
            graphs_payload[name] = json.loads(p.read_text(encoding="utf-8"))

    bundle = {
        "master": master,
        "graphs": graphs_payload,
        "architectureMap": tree,
        "sequences": seq_json,
        "timeline": TIMELINE,
        "timelineGraphs": timeline_graphs,
        "heatmaps": heatmaps,
    }
    bundle_js = "window.ATLAS_BUNDLE=" + json.dumps(bundle, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (ATLAS / "assets" / "atlas-bundle.js").write_text(bundle_js, encoding="utf-8")

    print(f"Done: {len(nodes)} nodes, {len(edges)} edges")
    print(f"Output: {ATLAS}")
    print(f"Bundle: assets/atlas-bundle.js ({len(bundle_js) // 1024} KB)")


if __name__ == "__main__":
    main()
