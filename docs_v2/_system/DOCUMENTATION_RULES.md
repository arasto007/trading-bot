# TradingBot Documentation Rules

## 1. Purpose

This documentation system exists to maintain a single, reliable,
machine-assisted source of truth for the TradingBot repository.

Documentation must describe the actual code and runtime behavior,
not historical assumptions or intended architecture.

---

## 2. Source of Truth

The repository code is the primary source of truth.

Documentation is a derived representation of the codebase.

When documentation conflicts with code:

CODE > GENERATED DOCUMENTATION > MANUAL DOCUMENTATION

A manual document must never override proven runtime behavior.

---

## 3. Documentation Classes

### A. Generated Documentation

Generated automatically from source code, configuration,
tests, and runtime metadata.

Generated documentation must not be manually edited.

Location:

docs_v2/_generated/

---

### B. Verified Documentation

Human-readable documentation that has been checked against
the current codebase.

Examples:

- architecture
- runtime behavior
- strategy behavior
- risk behavior
- operational procedures

---

### C. Historical Documentation

Documents describing previous versions, experiments,
decisions, migrations, or deprecated behavior.

Historical information must never be presented as current behavior.

---

## 4. Current-State Rule

Every document describing current behavior must answer:

1. What exists?
2. What is active?
3. What is disabled?
4. What is reachable?
5. What is unreachable?
6. What is proven?
7. What is unknown?
8. What source proves the claim?

Never describe a feature as active merely because:

- a file exists
- a class exists
- a configuration key exists
- a test exists
- an example exists

Reachability and runtime execution must be verified.

---

## 5. Configuration Rule

Configuration documentation must distinguish between:

- defined
- default
- environment override
- active
- disabled
- shadow
- unreachable
- runtime-dependent
- unknown

`.env.example` is never considered proof of actual runtime configuration.

---

## 6. Strategy Rule

Every strategy must have a documented status:

ACTIVE
AVAILABLE
SHADOW
DISABLED
UNREACHABLE
DEPRECATED

Strategy availability does not imply strategy execution.

The documentation must identify the actual selection path.

---

## 7. Runtime Rule

Runtime documentation must describe the real execution path:

startup
→ configuration
→ initialization
→ kernel
→ pipeline
→ strategy
→ filters
→ risk
→ execution
→ position management
→ shutdown/recovery

The documented path must be traceable to source-code symbols.

---

## 8. Risk Rule

Risk documentation must identify the final authority for:

- entry approval
- position sizing
- stop loss
- take profit
- exposure
- daily loss
- drawdown
- emergency stop
- position management

Multiple implementations must be explicitly identified.

---

## 9. Unknowns Rule

Unknown information must be labeled:

UNKNOWN

Never convert an assumption into a fact.

If runtime state cannot be proven from the repository,
documentation must explicitly say so.

---

## 10. Change Rule

Every meaningful code change that affects:

- architecture
- runtime flow
- configuration
- strategy selection
- risk
- execution
- data pipeline
- ML
- testing
- operations

must trigger a documentation verification/update process.

---

## 11. No Silent Drift

Documentation must never silently become stale.

The documentation system should detect:

- changed source files
- changed configuration
- changed pipeline stages
- changed strategy registry
- changed startup chain
- changed risk controls
- changed tests
- changed runtime contracts

and report which documents may require review.

---

## 12. Evidence Rule

Important claims should contain evidence.

Preferred evidence:

1. source file
2. class/function
3. configuration key
4. test
5. generated analysis
6. runtime artifact

Statements without evidence must be marked:

UNVERIFIED

---

## 13. Historical Rule

Old documentation must never be silently rewritten to appear current.

When behavior changes:

1. current documentation is updated
2. historical information is moved to history
3. the change is recorded in CHANGELOG.md

---

## 14. AI Agent Rule

Any AI agent working on this repository must:

1. Read docs_v2/README.md
2. Read docs_v2/01_truth/SOURCE_OF_TRUTH.md
3. Determine the current runtime state
4. Verify relevant source code
5. Check documentation impact before modifying code
6. Update affected documentation
7. Run documentation validation
8. Report documentation changes

AI agents must not rely on old docs outside docs_v2
without explicitly verifying them against source code.

---

## 15. Forbidden Behavior

The documentation system must never:

- invent runtime behavior
- infer activation from file existence
- treat example configuration as live configuration
- silently delete historical information
- manually modify generated files
- claim profitability without evidence
- claim production readiness without evidence
- hide unknowns
- preserve contradictory current-state documents

---

## 16. Documentation Integrity

The documentation system must eventually provide automated checks for:

- stale documentation
- broken references
- missing evidence
- conflicting current-state claims
- changed source dependencies
- generated-document freshness
- undocumented architectural changes

Documentation integrity is a system requirement,
not a manual habit.