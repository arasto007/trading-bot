# Component Boundaries

**Status:** VERIFIED  
**Last verified:** 2026-09-01  

| Boundary | Inside | Outside |
|----------|--------|---------|
| Kernel | cycle, stages, freeze hooks | Research phase scripts |
| Factory | registry selection | Must not be edited to “help docs” |
| Router | PA vs VOL vs Adaptive **selection** | ML kernel |
| PA lock | `is_pa_production_lock` | If Adaptive or VOL env true, lock **does not hold** |
| RiskGate | allow/deny + size | Does not send orders |
| Execution adapter | order_send / paper / dry-run | Does not choose strategy |
| Meta | score + optional reject | Not the signal generator |
| ML kernel | only if `USE_ML_KERNEL` and gate | Default live |
| Shadow wrap | logs comparison | Inner signal unchanged |
| Docs / research JSON | memory | Not imported by `build_kernel_live` |

Detail: `PRODUCTION_RESEARCH_BOUNDARY.md`.
