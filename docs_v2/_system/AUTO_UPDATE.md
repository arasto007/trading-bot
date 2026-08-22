# TradingBot Documentation Auto-Update System

**Document Status:** VERIFIED
**System Status:** DESIGN / PARTIALLY PLANNED
**Last Updated:** 2026-08-20

---

## 1. Purpose

This document defines the rules and lifecycle for detecting, verifying, updating, and maintaining TradingBot documentation after changes to the repository.

The primary goal is to prevent documentation drift.

Documentation must reflect the actual repository source code, configuration, tests, and verified runtime evidence.

The documentation system must never assume that existing documentation is correct merely because it was previously verified.

---

## 2. Source of Truth Hierarchy

The documentation system follows this hierarchy:

```text
SOURCE CODE
    ↓
TESTS / RUNTIME EVIDENCE
    ↓
GENERATED EVIDENCE
    ↓
VERIFIED DOCUMENTATION
    ↓
HISTORICAL DOCUMENTATION
```

When two sources conflict, the higher-level source takes precedence.

### 2.1 Source Code

Source code is the primary authority for describing what the system actually implements.

Examples:

* Python source files
* configuration implementation
* pipeline implementation
* strategy implementation
* risk controls
* execution logic
* service implementations
* model integration code

Documentation must not claim behavior that cannot be supported by the source code or valid runtime evidence.

### 2.2 Tests

Tests provide executable evidence about expected and verified behavior.

Tests do not automatically override source code, but they are important evidence when determining whether implemented behavior is functioning as intended.

### 2.3 Runtime Evidence

Runtime evidence may be used when source code alone cannot prove actual runtime behavior.

Examples:

* MT5 runtime state
* execution logs
* broker responses
* heartbeat files
* runtime truth files
* startup reports
* SQLite trade journals
* monitoring data

Runtime evidence must always be explicitly labeled as runtime evidence.

### 2.4 Generated Documentation

Generated documentation describes repository facts discovered automatically from source code and configuration.

Generated documentation must be deterministic whenever possible.

### 2.5 Verified Documentation

Verified documentation is human-readable documentation that has been checked against the current source and available evidence.

### 2.6 Historical Documentation

Historical documentation describes previous states of the project.

Historical documentation must never be treated as evidence of current behavior unless independently verified.

---

## 3. Core Principle

The documentation system explains the TradingBot.

It does not define the TradingBot.

The system must follow:

```text
OBSERVE
    ↓
ANALYZE
    ↓
VERIFY
    ↓
DOCUMENT
```

It must never follow:

```text
DOCUMENTATION
    ↓
ASSUME
    ↓
CHANGE CODE
```

If documentation conflicts with executable source code, the conflict must be reported and the documentation must be reviewed.

The system must never modify production code merely to make documentation appear correct.

---

## 4. Documentation Lifecycle

Every meaningful documentation-affecting code change should follow this lifecycle:

```text
CODE CHANGE
    ↓
CHANGE DETECTION
    ↓
IMPACT ANALYSIS
    ↓
SOURCE VERIFICATION
    ↓
DOCUMENTATION REVIEW
    ↓
DOCUMENT / GENERATE
    ↓
DOCUMENTATION VALIDATION
    ↓
TEST VALIDATION
    ↓
CHANGELOG UPDATE
    ↓
GIT REVIEW
    ↓
COMMIT
```

No documentation update should bypass source verification.

---

## 5. Change Detection

The documentation system must detect changes to source files that may affect documented behavior.

Change detection should eventually operate through:

* Git diff
* dependency mappings
* source analysis
* symbol analysis
* configuration analysis
* generated inventories

The system must distinguish between:

1. Changes that affect behavior.
2. Changes that affect architecture.
3. Changes that affect documentation only.
4. Changes that are purely cosmetic.
5. Changes whose impact is unknown.

Unknown impact must be reported rather than silently ignored.

---

# 6. Change Categories

## 6.1 Runtime

Potential runtime-related paths include:

```text
tradingbot/__main__.py
tradingbot/application/**
tradingbot/kernel/**
scripts/start_*.py
scripts/start_*.ps1
scripts/run_*.py
start/**
```

Potentially affected documentation:

```text
docs_v2/03_runtime/**
docs_v2/02_architecture/**
docs_v2/01_truth/**
```

---

## 6.2 Architecture

Potential architecture-related paths include:

```text
tradingbot/kernel/**
tradingbot/pipeline/**
tradingbot/adapters/**
tradingbot/domain/**
tradingbot/application/**
```

Potentially affected documentation:

```text
docs_v2/02_architecture/**
docs_v2/01_truth/**
```

---

## 6.3 Strategy

Potential strategy-related paths include:

```text
engine/strategies/**
tradingbot/strategies/**
tradingbot/adapters/*strategy*
tradingbot/ml/integration/factory.py
tradingbot/config/strategies.py
tradingbot/config/pa_*.py
tradingbot/domain/gold_strategies/**
tradingbot/domain/price_action.py
```

Potentially affected documentation:

```text
docs_v2/04_strategy/**
docs_v2/01_truth/**
docs_v2/10_history/**
```

---

## 6.4 Risk

Potential risk-related paths include:

```text
tradingbot/adapters/risk_gate.py
tradingbot/services/live_risk_tracker.py
tradingbot/services/kill_switch.py
tradingbot/domain/risk_logic.py
tradingbot/adapters/mt5_execution.py
tradingbot/adapters/mt5_position_manager.py
tradingbot/services/position_protector.py
tradingbot/services/position_recovery_service.py
```

Potentially affected documentation:

```text
docs_v2/05_risk/**
docs_v2/01_truth/**
docs_v2/09_operations/**
```

---

## 6.5 Data

Potential data-related paths include:

```text
tradingbot/adapters/mt5_market_data.py
tradingbot/adapters/market_cache.py
tradingbot/pipeline/data_stage.py
tradingbot/pipeline/indicator_stage.py
tradingbot/domain/ohlcv.py
tradingbot/domain/indicators.py
tradingbot/services/*data*
```

Potentially affected documentation:

```text
docs_v2/06_data/**
docs_v2/02_architecture/**
docs_v2/01_truth/**
```

---

## 6.6 Machine Learning

Potential ML-related paths include:

```text
tradingbot/ml/**
ml/**
models/**
saved_models/**
scripts/*ml*
scripts/*model*
```

Potentially affected documentation:

```text
docs_v2/07_ml/**
docs_v2/01_truth/**
```

---

## 6.7 Testing

Potential testing-related paths include:

```text
tests/**
pytest.ini
pyproject.toml
setup.cfg
```

Potentially affected documentation:

```text
docs_v2/08_testing/**
docs_v2/01_truth/**
```

---

## 6.8 Operations

Potential operations-related paths include:

```text
scripts/**
start/**
tradingbot/services/**
dashboard/**
monitoring/**
notifier/**
```

Potentially affected documentation:

```text
docs_v2/09_operations/**
docs_v2/03_runtime/**
```

---

# 7. Impact Analysis

A code change must not automatically rewrite every document.

The system must determine which documentation areas are potentially affected.

For example:

```text
Changed:
tradingbot/adapters/risk_gate.py
```

Potential impact:

```text
docs_v2/05_risk/RISK.md
docs_v2/05_risk/POSITION_LIFECYCLE.md
docs_v2/01_truth/CURRENT_STATE.md
docs_v2/09_operations/RUNBOOK.md
docs_v2/10_history/CHANGELOG.md
```

Another example:

```text
Changed:
tradingbot/pipeline/signal_stage.py
```

Potential impact:

```text
docs_v2/02_architecture/PIPELINE.md
docs_v2/04_strategy/SIGNAL_FLOW.md
docs_v2/01_truth/CURRENT_STATE.md
docs_v2/10_history/CHANGELOG.md
```

Only affected documentation should require review.

---

# 8. Dependency Mapping

Important documentation files should eventually declare the source files and symbols that affect their validity.

Example:

```yaml
document: docs_v2/03_runtime/STARTUP.md

dependencies:
  - scripts/start_bot.py
  - scripts/start_live_daemon.ps1
  - scripts/run_live_watchdog.py
  - tradingbot/__main__.py
  - tradingbot/application/live_runner.py
```

Dependency mappings must be treated as references for validation.

They must not be treated as proof that the referenced files still contain the documented behavior.

The validator must inspect the actual current source.

---

# 9. Staleness Detection

A document is potentially stale when one or more of the following conditions are true:

1. A declared dependency changed after the document was last verified.
2. A referenced source symbol no longer exists.
3. A documented configuration key no longer exists.
4. A documented pipeline stage no longer exists.
5. A documented strategy is no longer reachable.
6. A documented startup path changed.
7. A documented class or function was renamed or removed.
8. A generated document is older than its source dependencies.
9. A current-state claim conflicts with generated evidence.
10. A documentation validation check fails.
11. A documented behavior cannot be supported by current source or runtime evidence.
12. A dependency mapping is missing or invalid.

Potentially stale documents must be marked:

```text
REVIEW_REQUIRED
```

They must not silently remain marked as verified.

---

# 10. Verification Process

When a document becomes stale, the system should:

1. Identify changed dependencies.
2. Re-read affected source files.
3. Verify documented symbols.
4. Verify configuration behavior.
5. Verify runtime reachability where applicable.
6. Verify active, disabled, planned, or unknown status.
7. Verify relevant tests.
8. Check generated evidence.
9. Update the affected document.
10. Run documentation validation.
11. Update verification metadata.

Verification must always be based on current evidence.

---

# 11. Generated Documentation

Files under:

```text
docs_v2/_generated/
```

are machine-generated unless explicitly documented otherwise.

Generated files must not be manually edited.

Generation should be deterministic.

Given:

```text
same repository state
+
same configuration
+
same generator version
```

the generator should produce the same result.

Generated documents should contain metadata such as:

```yaml
generated: true
generator: TradingBot Documentation Generator
generator_version: <version>
git_revision: <commit>
generated_at: <timestamp>
status: GENERATED
```

The exact metadata schema will be defined by the documentation system implementation.

---

# 12. Verified Documentation

Verified documentation is human-readable documentation that has been checked against the current repository state.

A verified document should contain metadata similar to:

```yaml
status: VERIFIED
verified_against: <git_commit>
verified_at: <timestamp>
```

A document must not remain `VERIFIED` after a relevant dependency changes without another verification pass.

If verification has not occurred, the document must not claim current verified status.

---

# 13. Documentation Status Model

Documents may use the following statuses:

```text
DRAFT
REVIEW_REQUIRED
VERIFIED
GENERATED
HISTORICAL
DEPRECATED
UNKNOWN
```

### DRAFT

The document is incomplete or still being developed.

### REVIEW_REQUIRED

The document may no longer accurately represent the current repository.

### VERIFIED

The document has been checked against current evidence.

### GENERATED

The document was generated automatically from repository evidence.

### HISTORICAL

The document describes a previous repository state.

### DEPRECATED

The document should no longer be used as an active reference.

### UNKNOWN

The system cannot currently determine the validity of the documented state.

---

# 14. Automatic Status Transitions

A verified document whose relevant dependencies change must transition to:

```text
REVIEW_REQUIRED
```

It must not automatically transition back to:

```text
VERIFIED
```

Verification requires a new evidence-based review.

Unknown states must remain:

```text
UNKNOWN
```

unless sufficient evidence is obtained.

---

# 15. Documentation Update Triggers

Documentation review is mandatory after:

* architecture changes
* pipeline changes
* strategy changes
* risk changes
* execution changes
* configuration changes
* startup changes
* ML changes
* data pipeline changes
* test architecture changes
* operational changes
* public runtime API changes
* renamed source modules
* deleted source modules
* changed strategy-selection logic
* changed risk authority
* changed position-management ownership
* changed configuration precedence
* changed execution ownership
* changed runtime entry points

Recommended review triggers include:

* significant refactoring
* new service
* new background process
* new environment variable
* changed default configuration
* changed CLI behavior
* changed logging or telemetry
* changed database schema
* changed model artifact
* changed broker integration

---

# 16. AI Agent Workflow

Every AI coding agent working on the repository must follow this workflow:

```text
1. Read docs_v2/README.md
2. Read the current Source of Truth documentation
3. Identify the requested change
4. Inspect relevant source code
5. Inspect relevant tests
6. Identify documentation impact
7. Propose the implementation
8. Make code changes
9. Run relevant tests
10. Run documentation validation
11. Update affected documentation
12. Update CHANGELOG.md
13. Review git diff
14. Report code changes
15. Report documentation changes
16. Report test results
17. Report unresolved uncertainty
```

The agent must not skip documentation review because a code change appears small.

---

# 17. AI Documentation Rules

AI agents must follow these rules:

### Rule 1 — Never invent facts

If the repository does not provide enough evidence, use:

```text
UNKNOWN
```

### Rule 2 — Never convert UNKNOWN into VERIFIED without evidence

### Rule 3 — Never assume a feature is active because code exists

Code existence does not necessarily prove runtime reachability.

### Rule 4 — Never assume a feature is disabled because it is not currently observed

Absence of evidence is not automatically evidence of absence.

### Rule 5 — Never rewrite historical documentation to make it match the present

Historical documents must preserve historical information.

### Rule 6 — Never modify code solely to satisfy documentation

### Rule 7 — Never silently hide documentation conflicts

### Rule 8 — Never mark documentation VERIFIED without verification evidence

### Rule 9 — Never claim a planned tool is implemented

### Rule 10 — Always distinguish:

```text
IMPLEMENTED
PARTIAL
PLANNED
DISABLED
DEPRECATED
UNKNOWN
```

---

# 18. Documentation Validation Commands

The project should eventually provide:

```bash
python tools/docs/check.py
```

Purpose:

* detect stale documents
* detect missing dependencies
* detect broken references
* detect missing evidence
* detect invalid metadata
* detect conflicting current-state claims
* detect invalid documentation status

This command is currently:

```text
PLANNED
```

until it actually exists and passes validation.

---

# 19. Documentation Verification Command

The project should eventually provide:

```bash
python tools/docs/verify.py
```

Purpose:

* verify source dependencies
* verify documented symbols
* verify configuration references
* verify runtime claims
* verify status claims
* report discrepancies

Current status:

```text
PLANNED
```

---

# 20. Documentation Generation Command

The project should eventually provide:

```bash
python tools/docs/generate.py
```

Purpose:

* scan the repository
* generate machine-readable inventories
* regenerate generated documentation
* update generated metadata
* produce deterministic output

Current status:

```text
PLANNED
```

---

# 21. Documentation Update Command

The project may eventually provide:

```bash
python tools/docs/update.py
```

Purpose:

* detect changed source files
* calculate documentation impact
* verify affected sources
* identify affected documents
* update or generate appropriate documentation
* record changes

Current status:

```text
PLANNED
```

---

# 22. Pre-Commit Integration

The documentation system should eventually integrate with Git.

Conceptual workflow:

```text
git diff
    ↓
detect changed source files
    ↓
calculate documentation impact
    ↓
run documentation validation
    ↓
run relevant tests
    ↓
report required documentation updates
    ↓
allow commit
```

A future Git hook may execute:

```bash
python tools/docs/check.py
```

The hook must not silently modify verified documentation.

If documentation requires an update, the change must be explicit and reviewable.

---

# 23. CI Integration

Continuous integration should eventually validate:

```text
Documentation
+
Generated Evidence
+
Verification
+
Tests
```

CI should fail when:

* required documentation is missing
* dependency mappings are invalid
* generated documentation is stale
* current-state claims conflict
* documented symbols are missing
* documentation metadata is invalid
* generated files were manually modified
* documentation references are broken
* required verification fails

Current CI integration status:

```text
PLANNED
```

---

# 24. No Silent Automatic Rewriting

Automatic documentation systems must not blindly rewrite verified documentation.

The system may:

* detect changes
* identify impacted documents
* generate reports
* regenerate generated files
* propose documentation updates
* identify contradictions
* mark documents for review

The system must not:

* invent facts
* overwrite verified documentation without verification
* delete historical information
* hide conflicts
* convert UNKNOWN into VERIFIED
* mark a document VERIFIED without evidence
* modify source code to satisfy documentation

---

# 25. Failure Handling

If documentation processing fails:

```text
CODE CHANGE
    ↓
DOCUMENTATION SYSTEM FAILURE
    ↓
MARK AFFECTED DOCUMENTATION REVIEW_REQUIRED
    ↓
REPORT FAILURE
```

A documentation failure must never be silently ignored.

If source verification cannot be completed, affected documentation must remain unverified.

A documentation failure must not automatically imply that the code change is invalid.

The failure must be reported clearly so that it can be resolved before the change is considered fully documented.

---

# 26. Runtime Evidence

When repository source code cannot prove a behavior, runtime evidence may be used.

Examples include:

```text
MT5 runtime state
SQLite trade journal
heartbeat files
runtime_truth.json
startup_report.json
execution logs
broker responses
monitoring data
```

Runtime evidence must contain enough metadata to establish:

* evidence type
* source
* timestamp
* repository context when relevant
* collection context when relevant

Example:

```yaml
evidence_type: RUNTIME
source: data/runtime_truth.json
collected_at: <timestamp>
```

Runtime evidence must not be represented as source-code proof.

---

# 27. Unknown State

If the system cannot determine whether a feature is active, disabled, partially implemented, or reachable, the documented state must be:

```text
UNKNOWN
```

Never replace:

```text
UNKNOWN
```

with:

```text
ACTIVE
```

or:

```text
DISABLED
```

without evidence.

Likewise, the existence of implementation code does not automatically establish:

```text
ACTIVE
```

---

# 28. Changelog Integration

Every meaningful behavior change must be recorded in:

```text
docs_v2/10_history/CHANGELOG.md
```

A changelog entry should contain:

* date
* change
* affected subsystem
* reason
* affected source files
* affected documentation
* verification status

Example:

```markdown
## 2026-08-20

### Risk

Changed the RiskGate spread threshold.

Affected source:

- `tradingbot/adapters/risk_gate.py`

Affected documentation:

- `docs_v2/05_risk/RISK.md`

Verification status:

VERIFIED
```

The example above is illustrative only and must not be treated as an actual project change unless the repository confirms it.

---

# 29. Documentation Audit

The documentation system should periodically perform a full audit.

The audit should check:

* source dependencies
* documentation dependencies
* runtime paths
* strategy reachability
* configuration precedence
* risk authority
* pipeline structure
* test coverage references
* generated documentation freshness
* broken references
* contradictory claims
* unknown states
* stale verification metadata
* incorrect implementation-status claims

A full audit should produce a report under:

```text
docs_v2/_generated/
```

The exact report format is implementation-defined.

---

# 30. Full Repository Rebuild

The documentation system must eventually support a full rebuild.

Full rebuild process:

```text
1. Scan repository
2. Discover runtime entry points
3. Discover modules
4. Discover configuration
5. Discover pipeline
6. Discover strategies
7. Discover risk controls
8. Discover execution paths
9. Discover data flow
10. Discover ML components
11. Discover tests
12. Discover operational services
13. Generate machine-readable inventory
14. Generate documentation
15. Validate documentation
16. Produce audit report
```

A full rebuild must be safe to run repeatedly.

A full rebuild must not delete historical documentation.

---

# 31. Documentation Integrity

The documentation system is healthy only when:

```text
NO UNRESOLVED STALE DOCUMENTS
+
NO BROKEN REFERENCES
+
NO UNVERIFIED CURRENT CLAIMS
+
NO GENERATED DRIFT
+
NO UNRESOLVED CURRENT-STATE CONFLICTS
```

If any condition fails, the system must report the failure.

A healthy documentation system does not mean that every uncertainty has been eliminated.

Known uncertainty must be explicitly represented.

---

# 32. Historical Documentation

Historical documentation must be preserved separately from active documentation.

Historical material should be stored under:

```text
docs_v2/archive/
```

or another explicitly designated historical location.

Historical documentation:

* must not be treated as current truth
* must not be silently rewritten
* must preserve its historical context
* may contain outdated architecture or behavior
* may be used to understand project evolution

Historical information is valuable evidence of project evolution but is not evidence of current runtime behavior.

---

# 33. Documentation Structure

The target documentation architecture may contain areas such as:

```text
docs_v2/
├── 00_project/
├── 01_truth/
├── 02_architecture/
├── 03_runtime/
├── 04_strategy/
├── 05_risk/
├── 06_data/
├── 07_ml/
├── 08_testing/
├── 09_operations/
├── 10_history/
├── _generated/
├── _system/
└── archive/
```

The exact final structure must be established only after the repository baseline and Source of Truth architecture are finalized.

This document must not be interpreted as final authorization to create every directory listed above.

---

# 34. Documentation System Implementation Status

The documentation system must explicitly distinguish between implemented capabilities and planned capabilities.

Initial status:

| Component                    | Status      |
| ---------------------------- | ----------- |
| Documentation rules          | IMPLEMENTED |
| Documentation structure      | PARTIAL     |
| Documentation schema         | PLANNED     |
| Source of Truth model        | IN DESIGN   |
| Dependency mapping           | PLANNED     |
| Change detection             | PLANNED     |
| Impact analysis              | PLANNED     |
| Staleness detection          | PLANNED     |
| Documentation generator      | PLANNED     |
| Documentation verifier       | PLANNED     |
| Documentation updater        | PLANNED     |
| Git integration              | PLANNED     |
| CI integration               | PLANNED     |
| Full repository audit        | PLANNED     |
| Runtime evidence integration | PLANNED     |
| Automatic status transitions | PLANNED     |

This table must be updated as the documentation system itself is implemented.

No component may be marked `IMPLEMENTED` until the repository contains the corresponding working implementation and it has been verified.

---

# 35. Critical Safety Rules

The documentation automation system must never become another source of truth.

Its job is:

```text
OBSERVE CODE
    ↓
ANALYZE CODE
    ↓
COLLECT EVIDENCE
    ↓
DETECT DRIFT
    ↓
UPDATE DOCUMENTATION
```

The system does not define what TradingBot does.

The executable repository and verified runtime evidence define what TradingBot actually does.

Documentation describes that reality.

---

# 36. Final Rule

When uncertainty exists:

```text
DO NOT GUESS.
```

When documentation conflicts with code:

```text
REPORT THE CONFLICT.
```

When evidence is insufficient:

```text
USE UNKNOWN.
```

When a dependency changes:

```text
REVIEW THE DOCUMENTATION.
```

When documentation is generated:

```text
DO NOT MANUALLY EDIT IT.
```

When historical documentation is encountered:

```text
PRESERVE IT AS HISTORY.
```

When an AI agent changes code:

```text
CHECK DOCUMENTATION IMPACT.
```

When documentation claims current behavior:

```text
REQUIRE CURRENT EVIDENCE.
```

The objective is not to create more documentation.

The objective is to create **trustworthy, traceable, evidence-based documentation that remains synchronized with the actual TradingBot system.**
