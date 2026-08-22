# TradingBot Documentation v2

> Single Source of Truth for the TradingBot project.

---

## Read Order (Required)

Every AI agent must read documents in this order:

1. `01_truth/SOURCE_OF_TRUTH.md`
2. `01_truth/CURRENT_STATE.md`
3. `02_architecture/ARCHITECTURE.md`
4. `03_runtime/STARTUP.md`
5. `03_runtime/LIVE_LOOP.md`
6. Relevant document for the requested subsystem.

---

## Documentation Structure

| Folder | Purpose |
|--------|---------|
| 01_truth | Current verified truth of the project. |
| 02_architecture | System architecture and module relationships. |
| 03_runtime | Startup chain, runtime loop, configuration. |
| 04_strategy | Strategy engine and signal flow. |
| 05_risk | RiskGate, execution authority, lifecycle. |
| 06_data | Market data pipeline and caching. |
| 07_ml | ML architecture and current ML status. |
| 08_testing | Tests and validation system. |
| 09_operations | Runbook, monitoring, observability. |
| 10_history | Changelog and historical behavior. |
| _generated | Auto-generated documentation. Never edit manually. |
| _system | Documentation engine rules and schemas. |

---

## Documentation States

Every document must declare one status.

- VERIFIED
- GENERATED
- HISTORICAL
- DRAFT

---

## Update Policy

Documentation is updated only after code verification.

Code changes must trigger documentation review according to:

`_system/DOCUMENTATION_RULES.md`