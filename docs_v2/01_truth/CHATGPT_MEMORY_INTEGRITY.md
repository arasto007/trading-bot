# ChatGPT Memory Integrity (Phase 1.5.78)

**Status:** VERIFIED by documentation-only test  
**Last verified:** 2026-09-01  
**Production source used in the test:** **NO**

The synthetic external-model test reads only:

- `PROJECT_SOURCE_OF_TRUTH.md`
- `CHATGPT_BOOTSTRAP.md`
- `docs_v2/*.md` paths those two files reference

Runner: `tradingbot/ml/research/documentation_memory_hardening/memory_integrity.py`  
JSON: `data/ml/reports/documentation_memory_hardening/memory_integrity.json`  
Test: `tests/test_chatgpt_memory_integrity.py`

If a question cannot be answered from that corpus, classification is **DOCUMENTATION_GAP** — the test must fail rather than inventing an answer.

Answers expected in-corpus (not copied from production at test time):

1. Default run = PA via MultiEngineRouter  
2. Symbol `XAUUSD_i`  
3. Timeframe M5 / 5m  
4. Strategy `priceaction`  
5. Preset `gold_ny_sweep`  
6. START_BOT → … → RiskGate → Mt5ExecutionAdapter  
7. ML off (`USE_ML_KERNEL` false/off)  
8. v41 inactive / class C  
9. Factor 1.0 via `engine_calibration_factor`  
10. RiskGate mandatory / evaluate  
11. Missing tick → 999  
12. Production vs research (`ml/research`)  
13. UNKNOWN including identity/env  
14. `london_sweep` vs NY 15  
15. Production-affecting / PRODUCTION-CRITICAL  
16. Update protocol / impact map  
17. Costs unknown (commission / round-trip / class-A)  
18. Operator `.env` UNKNOWN  
19. Safety locks (`PA_PRODUCTION_LOCK`, Do not …)  
20. Start at PROJECT_SOURCE_OF_TRUTH then CHATGPT_BOOTSTRAP  

This does **not** mean ChatGPT knows the entire repository. It means the listed questions are **A = documented and code-cited** in the ChatGPT-facing layer.
