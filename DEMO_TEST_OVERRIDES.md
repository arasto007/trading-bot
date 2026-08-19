# Demo Test Overrides (ACTIVE)

These settings are **intentionally enabled for demo testing** and must be reverted before live or prop-firm deployment.

| Setting | Value | Effect |
|---------|-------|--------|
| `DEMO_DISABLE_SESSION_FILTER` | `true` | PA and Adaptive engines can scan **24h** — London/NY session windows bypassed |
| `USE_ML_KERNEL` | `false` | ML kernel not live — shadow only |
| `PA_PRODUCTION_LOCK` | `true` (default) | Only PA selected for trades; VOL/Adaptive log-only |

## Re-enable session filter

In `.env`:

```
DEMO_DISABLE_SESSION_FILTER=false
```

Then restart the bot (watchdog will pick up on next cycle, or stop/start manually).

## Date enabled

2026-08-10 — Phase demo testing (user request)
