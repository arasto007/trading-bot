# System Architecture

**Status:** VERIFIED  
**Last verified:** 2026-09-01  
**Canonical-Entry:** false  
**Epistemic-Role:** OWNER of ARCHITECTURE.  
**Operator-effective state:** UNKNOWN  

Supersedes `docs_v2/02_architecture/ARCHITECTURE.md` as the ChatGPT architecture file.

---

## Layers

```text
Windows BAT / PowerShell
  → Python CLI (__main__)
    → LiveRunner
      → TradingKernel
         DataStage → IndicatorStage → SignalStage → SignalFilterStage → RiskStage → ExecutionStage
      → background: KillSwitch, LiveOps, BackgroundServices
```

Ports: `tradingbot/ports/` (interfaces). Adapters: `tradingbot/adapters/`. Domain: `tradingbot/domain/`. Legacy engine strategies: `engine/strategies/`.

## Live signal ownership

Factory (`tradingbot/ml/integration/factory.py::build_strategy_registry`) branch order **in executable code**:

1. Downgrade ML if kernel requested but live gate closed  
2. `MultiEngineRouterRegistry` if router on and not ml  
3. Adaptive registry if Adaptive on and not ml  
4. VOL registry if VOL on and not ml  
5. `MLKernelRegistry` if ml still enabled  
6. `UnconfiguredEngineRegistry` if `USE_ML_KERNEL` unset and router/adaptive/vol off  
7. Else legacy (+ optional shadow wrap)

Default daemon hits step 2.

## Not the architecture

- Adaptive-as-default (legacy `docs/`)  
- VOL-as-default (old banners; KI-002 resolved in `start_bot.py` text)  
- ML kernel as live owner (`data/ml/live/` is historical)

## Related

`COMPONENT_BOUNDARIES.md`, `DATA_FLOW.md`, `PIPELINE.md` (supporting stage names).
