# Active Context — Tax Agent Backend
**Date**: 2026-02-18 07:10
**Session ID**: 1f21c79a-6e11-4f17-95e2-5cf3bd060109
**Previous Session**: 240e8091-3be5-4720-933d-79c01820eb56 (Blueprint gap fixes)

---

## Current Focus
**Phase 2.5 (Logic Tuning) COMPLETE.** All phases through 2.5 are done. Next: Phase 3 or deployment.

## Build Status — Complete Through Phase 2.5

| Phase | Description | Tests | Status |
|-------|-------------|-------|--------|
| Steps 0–5 | Orchestrator core (config, router, loader, critic, prompt) | 259 | ✅ |
| Step 6 | RAG pipeline wiring | 287 | ✅ |
| Phase 1 | INCOME_TAX domain split → INDIVIDUAL/CORPORATE/ADMIN | 323 | ✅ |
| Phase 2 | Contextual Isolation (compound routing + domain search filter) | 323 | ✅ |
| Phase 2.5 | Logic Tuning (3 rule files + env fix + test isolation) | 336 | ✅ |
| **Current Suite** | **336 passing** | **0 failures** | |

## Completed This Session (Feb 18)

### Phase 2: Contextual Isolation
- Tier 0 compound rules in `router.py`
- Domain-filtered `$vectorSearch` with fallback in `vector_search.py`
- `rag_pipeline.py` passes domain to `hybrid_search()`
- Atlas index updated with `domain` as filterable field
- 10 new tests (6 router + 4 search filter/fallback)

### Phase 2.5: Logic Tuning
- `corporate_tax_rules.md` — Estonian model, Art 97/98, conflict resolution
- `individual_income_rules.md` — Salary formula (Gross=Net/0.78), pension guard
- `micro_business_rules.md` — NEW: 1%/3% rates, IT exception, cancellation
- `.env` — Added `ROUTER_ENABLED=true` + `LOGIC_RULES_ENABLED=true`
- Fixed 2 test isolation bugs (`monkeypatch.delenv`)
- **QA**: 336 tests + 0 semgrep + 8/8 curl queries PASS

## Git State
- **Branch**: `main` (clean, pushed)
- **Latest commit**: `40a4213` feat: Phase 2 contextual isolation + Phase 2.5 logic tuning
- **Remote**: `admenejeri-maker/tax-agent-backend`

## Next Steps
1. 🟡 **Phase 3**: End-to-end integration tests (34 planned)
2. 🟡 **Bug B3**: Router compound rule #4 too broad for "ხელზე" alone
3. 🟢 **Deployment**: Cloud Run update with new logic rules
4. 🟢 **Legal verification**: Decree №415 IT consulting exception (A9)

## Known Deferred Items
| # | Issue | Priority |
|---|-------|----------|
| D1 | Compound rule #4 catches ALL "ხელზე" queries | Medium |
| D2 | No rental-specific compound rule | Low |
| D3 | 500k micro-business transition timing | Low |
| D4 | IT consulting exception not verified against Decree №415 | Low |

## Repositories (Canonical)
| Component | Repository |
|-----------|------------|
| **Backend** | [`admenejeri-maker/tax-agent-backend`](https://github.com/admenejeri-maker/tax-agent-backend) |
| **Frontend** | [`admenejeri-maker/tax-agent-frontend`](https://github.com/admenejeri-maker/tax-agent-frontend) |

---
*Context saved by Antigravity — Phase 2.5 Logic Tuning Complete*
