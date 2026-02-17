# Enterprise Remediation — Task Registry

> თითოეული ტასკის დეტალური დოკუმენტაცია: ბაგები, ცვლილებები, კორექციები.
> **Last Updated:** 2026-02-08 (21:52 GMT+4)

---

## ✅ Completed Tasks

### P0.2 — CI/CD Pipeline Skeleton
| | |
|---|---|
| **Status** | ✅ Done |
| **Files Created** | `backend/.github/workflows/ci.yml`, `frontend/.github/workflows/ci.yml` |
| **Commits** | Backend: `734d643`, Frontend: `72b53df` |
| **What Changed** | GitHub Actions CI workflows created for both repos |
| **Bugs Found** | None |
| **Corrections** | None |

### P0.3 — React Error Boundaries
| | |
|---|---|
| **Status** | ✅ Done |
| **What Changed** | Error boundaries added to frontend components |
| **Bugs Found** | None |
| **Corrections** | None |

### P0.4 — .gitignore Hardening
| | |
|---|---|
| **Status** | ✅ Done |
| **What Changed** | `.gitignore` files hardened for both frontend and backend |
| **Bugs Found** | None |
| **Corrections** | None |

---

## Sprint 0 — Quick Wins

### P1.4 — Pin Dependency Versions
| | |
|---|---|
| **Status** | ✅ Done |
| **Original Plan** | `pip freeze` → overwrite `requirements.txt` |
| **Bug Found (QA)** | Worker discovered most deps already pinned with `==` |
| **What Changed** | Scope reduced: only `aiohttp>=3.10.0` needs `==` pin |
| **Correction** | Sprint 0 task est. reduced from 15min to 2min |
| **How** | Changed line 3: `aiohttp>=3.10.0` → `aiohttp==3.11.18` (latest stable) |
| **Verification** | `grep ">=" requirements.txt` → 0 results. All 232 deps now pinned with `==` |
| **File** | `backend/requirements.txt` |

### P2.7 — Drop Dead Collections
| | |
|---|---|
| **Status** | ✅ Done |
| **Plan** | Backup then `db.conversations_v2.drop()`, `db.cache.drop()` |
| **Bugs Found** | None — both had 0 documents and 0 code references |
| **Changes** | Dropped `conversations_v2` and `cache` from `scoop_db` |
| **Verification** | `list-collections` confirms 8 remaining: `products`, `chat_turns`, `users`, `conversations`, `user_memory`, `failed_searches`, `knowledge`, `intent_prototypes` |
| **File** | No code files affected (collections were orphaned) |

### P2.8 — Audit MongoDB Collections
| | |
|---|---|
| **Status** | ✅ Done |
| **Plan** | Schema + count + index audit for all 8 remaining collections |
| **Collections** | `products`(209), `chat_turns`(1491), `users`(262), `conversations`(66), `user_memory`(11), `failed_searches`(66), `knowledge`(5), `intent_prototypes`(98) |
| **Bugs Found** | 1. `chat_turns` — no index on `conversation_id` or `user_id` (perf risk at scale) |
| | 2. `user_memory` — schema inconsistency (40-80% confidence on `diet`, `goal`, `stimulant_sensitivity`) |
| | 3. `conversations` — orphaned `summary_expires_at` index (field not in schema) |
| | 4. `knowledge` — loose schema (20-40% confidence on `key_ingredients`, `types`, `side_effects`) |
| **Corrections** | Logged as future Sprint 1/2 items. No blocking issues for Sprint 0 |
| **Verification** | All 8 collections inspected: schema, count, and indexes documented |

### P3.2 — History Tag Stripping
| | |
|---|---|
| **Status** | ✅ Done (Verified — No Fix Needed) |
| **Plan** | Regex in response pipeline to strip internal tags |
| **Findings** | Already implemented in `ResponseBuffer` (`response_buffer.py`): |
| | 1. `extract_and_set_tip()` — strips `[TIP]...[/TIP]` via regex |
| | 2. `parse_quick_replies()` — strips `[QUICK_REPLIES]...[/QUICK_REPLIES]` + Georgian fallback |
| | 3. `finalize()` — orchestrates both extractors, returns clean text |
| **Pipeline Integration** | Called at two points: |
| | - **Stream path**: `engine.py:320` — `buffer.finalize()` after streaming completes |
| | - **Sync path**: `engine.py:541` — `buffer.finalize()` in `_execute_pipeline()` |
| | Clean `tip` and `quick_replies` SSE events yielded post-finalization |
| **Bugs Found** | None — architecture is correct as designed |
| **Corrections** | None required — no code changes |
| **Files Inspected** | `response_buffer.py`, `engine.py`, `stream_orchestrator.py` |

### P3.7 — HSTS Headers
| | |
|---|---|
| **Status** | ✅ Done |
| **Plan** | `Strict-Transport-Security` middleware in `main.py` |
| **Implementation** | Added `@app.middleware("http")` at line 757 (after CORS, before rate limiter) |
| | Header: `max-age=31536000; includeSubDomains` (OWASP recommended) |
| | Gated behind `not settings.debug` to avoid local HTTP dev issues |
| **Verification** | `ast.parse` syntax check passed ✅ |
| **Bugs Found** | None |
| **Corrections** | None |
| **Files Modified** | `backend/main.py` |

---

## Sprint 1 — Foundation

### P0.1 — User Authentication (API Key — Session-Scoped)
| | |
|---|---|
| **Status** | 🔄 Reverted (Steps 1-9 implemented → user reverted all changes) |
| **Plan** | Auto-generated API key per session, stored in MongoDB with TTL, validated via `X-API-Key` header |
| **What Was Built** | MongoDB index (`api_keys` collection), key generator + store (`auth.py`), FastAPI dependency (`get_api_key`), `/auth/key` endpoint, protected 6 endpoints, frontend key lifecycle in `useChatSession.ts` |
| **Revert Reason** | User reverted all auth changes manually. CSP bug (P1.6) discovered during debugging of post-revert frozen frontend |
| **Key Risk** | Breaking change — all existing `/chat` calls unauthenticated |
| **Mitigation** | Re-implementation planned with backward-compatible optional auth |
| **Files Modified** | `backend/main.py`, `backend/config.py`, `frontend/src/hooks/useChatSession.ts`, `frontend/src/hooks/useSSEStream.ts`, `frontend/src/components/Chat.tsx`, `frontend/src/types/api.ts` |
| **Corrections** | All reverted to pre-auth state. Re-implementation pending |

### P1.3 — Structured Logging
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Replace `logging` → `structlog` + JSON + correlation IDs |
| **Existing Code** | Standard Python `logging` at `main.py:120-124` |
| **Bugs Found** | N/A |
| **QA Note** | Can run **parallel** with P0.1 (different files) |
| **Files** | `logging_config.py` [NEW], `main.py` [MODIFY] |
| **Corrections** | None yet |

### P1.5 — Dockerfile Security
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Non-root user, improved healthcheck, `.dockerignore` |
| **Existing Code** | Dockerfile runs as ROOT, healthcheck uses `python -c urllib` |
| **Bug Found (QA)** | ❌ No `.dockerignore` exists — Docker copies `.env`, `.git/`, `venv/` into image |
| **What Changed** | `.dockerignore` creation added to task scope |
| **Correction** | Added to plan: CREATE `.dockerignore` excluding `.env`, `*.pyc`, `__pycache__/`, `.git/`, `venv/`, `tests/` |
| **Files** | `backend/Dockerfile` [MODIFY], `backend/.dockerignore` [NEW] |

---

## Sprint 2 — Security Hardening

### P1.1 — Prompt Injection Blocking
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Upgrade log-only → blocking middleware |
| **Existing Code** | `SUSPICIOUS_PATTERNS` at `main.py:47-50` — logs but doesn't block |
| **Bug Found (QA)** | ❌ Original plan said P1.1 depends on P0.1 (Auth) — **WRONG** |
| **What Changed** | P1.1 reclassified as **INDEPENDENT** — no auth dependency |
| **Correction** | Dependency graph updated, P1.1 can run parallel with Sprint 0 on Day 1 |
| **How** | Injection middleware operates on raw input BEFORE auth check |
| **Files** | `middleware/injection_guard.py` [NEW], `main.py` [MODIFY] |

### P1.6 — CSP Headers
| | |
|---|---|
| **Status** | ✅ Done + 🐛 Hotfix Applied |
| **Plan** | Starlette middleware (backend) + `next.config.ts` headers (frontend) |
| **Implementation** | **Backend** (`main.py`): Extended `add_security_headers` middleware — `default-src 'none'; frame-ancestors 'none'` + `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` |
| | **Frontend** (`next.config.ts`): Full CSP — `script-src 'self'`, `style-src 'self' 'unsafe-inline' fonts.googleapis.com`, `font-src 'self' fonts.gstatic.com`, `connect-src 'self'`, `frame-ancestors 'none'` + `Permissions-Policy` |
| | Both gated behind production mode (`not settings.debug` for backend) |
| **Verification** | `ast.parse` ✅, `tsc --noEmit` ✅ |
| **🐛 Bug Found** | **CRITICAL** — `script-src 'self'` blocked Next.js inline hydration scripts. React rendered static HTML but never attached event handlers → **entire frontend frozen** (no clicks, no typing, no sidebar). `connect-src` also missing backend URL → all API calls blocked |
| **Root Cause** | Next.js injects inline `<script>` tags for hydration. `script-src 'self'` without `'unsafe-inline'` drops them silently. No JS errors in console — only CSP violation reports |
| **Hotfix** | `script-src 'self'` → `script-src 'self' 'unsafe-inline'`; `connect-src 'self'` → `connect-src 'self' ${NEXT_PUBLIC_BACKEND_URL}` |
| **Hotfix Verification** | Browser test ✅ — sidebar loads, quick pills clickable, chat sends messages, new sessions created |
| **Files Modified** | `backend/main.py`, `frontend/next.config.ts` (hotfix: `next.config.ts` only) |

### P2.6 — CSRF Protection
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | `SameSite=Strict` cookies + CSRF token for mutations |
| **Dependency** | Requires P0.1 Auth (needs session/cookie model) |
| **Bugs Found** | N/A |
| **Key Risk** | Over-aggressive CSRF could block SSE endpoints |
| **Mitigation** | Exempt SSE + public read endpoints |
| **Files** | `auth/csrf.py` [NEW], `main.py` [MODIFY] |

### P1.2 — Save Pipeline Retry
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | `tenacity` retry + dead-letter collection |
| **Existing Code** | `save_session` at `main.py:444-470` — no retry logic |
| **Bugs Found** | N/A |
| **Corrections** | None |
| **Files** | `main.py` [MODIFY] |

---

## Sprint 3 — API & Testing

### P2.2 — API Versioning
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | `APIRouter` with `/api/v1/` prefix + 301 redirects |
| **Existing Code** | All routes at root level (`/chat`, `/sessions/`, `/health`) |
| **Bug Found (QA)** | ❌ SSE endpoint `/chat/stream` also needs versioning to `/api/v1/chat/stream` |
| **What Changed** | SSE endpoint added to versioning scope |
| **Key Risk** | Breaking change — frontend must update ALL API calls atomically |
| **Mitigation** | 301 redirects for old routes during 1 sprint transition |
| **Files** | `routes/v1/` [NEW dir], `main.py` [MODIFY], frontend hooks [MODIFY] |

### P2.5 — Error Standardization
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | `ErrorResponse` model with `{code, message, details}` |
| **Bugs Found** | N/A |
| **Corrections** | None |

### P2.1 — Frontend Tests
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Vitest + React Testing Library |
| **Existing Code** | ❌ Zero tests, no test framework |
| **QA Note** | `parseProducts.ts` referenced in test plan but no note if parsing logic changes |
| **Files** | `frontend/__tests__/` [NEW dir], `package.json` [MODIFY] |

### P2.3 — Pagination
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | `skip/limit` params on list endpoints |
| **Bugs Found** | N/A |
| **Corrections** | None |

---

## Sprint 4 — UX & Observability

### P2.4 — SSE Auto-Reconnect
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Exponential backoff in `useSSEStream.ts` |
| **Existing Code** | `frontend/src/hooks/useSSEStream.ts` — no reconnect logic |
| **Bugs Found** | N/A |
| **Corrections** | None |

### P3.3 — OpenTelemetry
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Uncomment and configure existing tracing |
| **Existing Code** | Commented-out OTel code at `main.py:128-138` |
| **Bug Found (QA)** | ❌ Original plan said lines 132-136 — actual lines are **128-138** |
| **What Changed** | Line reference corrected |
| **Corrections** | Plan updated with correct line numbers |

### P3.5 — Zustand State Management
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Replace React hooks with centralized Zustand store |
| **Existing Code** | `useChatSession.ts` at `frontend/src/hooks/useChatSession.ts` |
| **QA Note** | Worker flagged: useChatSession.ts needs review BEFORE migration |
| **Dependency** | Requires P2.1 frontend tests first (safety net) |
| **Files** | `frontend/src/store/` [NEW dir], hooks [MODIFY] |

### P3.6 — Bundle Optimization
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | `next/bundle-analyzer`, lazy imports, code splitting |
| **Bugs Found** | N/A |
| **Corrections** | None |

---

## Sprint 5 — Polish

### P3.1 — Belief Decay Wiring
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Risk assessment → conditional wiring |
| **Bugs Found** | N/A |
| **Corrections** | None |

### P3.4 — E2E Playwright Tests
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Chat flow, product cards, session persistence |
| **QA Note** | ❌ Playwright setup requirements not detailed in plan |
| **What Changed** | Flagged as needing setup step (install, config, first test) |
| **Files** | `frontend/e2e/` [NEW dir], `playwright.config.ts` [NEW] |

### P3.8 — Feature Flags
| | |
|---|---|
| **Status** | ⏳ Pending |
| **Plan** | Environment-based + runtime toggle |
| **Bugs Found** | N/A |
| **Corrections** | None |

---

## Global Risks (QA-Discovered)

| # | Risk | Severity | Source |
|---|------|----------|--------|
| 1 | No `.dockerignore` — copies `.env`, `.git/` into image | MEDIUM | Worker QA |
| 2 | Secrets in plain env vars (`config.py:24`) | LOW | Worker QA |
| 3 | ~~`next.config.ts` has zero security headers~~ | ~~LOW~~ ✅ RESOLVED | P1.6 CSP (+ Hotfix) |
| 4 | Model name `gemini-3-flash-preview` hardcoded (`config.py:39`) | INFO | Worker QA |
| 5 | CORS defaults to `*` via env var | MEDIUM | Codebase analysis |
| 6 | SSE endpoint needs versioning too | MEDIUM | Worker QA |

---

## Correction Log

| Date | Task | What Was Wrong | What Was Corrected | How |
|------|------|---------------|-------------------|-----|
| 2026-02-08 | P1.4 | "pip freeze needed" | Most deps already pinned, only `aiohttp` uses `>=` | Reduced scope to 1-line fix |
| 2026-02-08 | P1.1 | Marked dependent on P0.1 | P1.1 is **independent** — injection middleware doesn't need auth | Dependency graph updated, parallelization enabled |
| 2026-02-08 | P1.5 | `.dockerignore` not mentioned | `.dockerignore` creation added to task | Worker QA discovered missing file |
| 2026-02-08 | P3.3 | OTel at lines 132-136 | Actual lines are **128-138** | Line reference corrected |
| 2026-02-08 | Codebase | "32 backend tests" | Actually **30** test files | Worker counted with `find` |
| 2026-02-08 | Codebase | "CORS wildcard not enforced" | CORS is configurable via env var, defaults to `*` | Nuance added |
| 2026-02-08 | P2.2 | SSE endpoint not in scope | `/chat/stream` → `/api/v1/chat/stream` needed | Worker flagged missing endpoint |
| 2026-02-08 | P3.4 | Playwright setup not detailed | Setup step needed (install, config) | Worker QA flagged gap |
| 2026-02-08 | P1.6 | "No bugs found" in CSP | **CRITICAL**: `script-src 'self'` froze entire frontend by blocking Next.js hydration | Hotfix: added `'unsafe-inline'` to `script-src`, backend URL to `connect-src` |
| 2026-02-08 | P0.1 | Status was "⏳ Pending" | All 9 steps were implemented then **user reverted** — status changed to 🔄 Reverted | Updated plan, files, and description to reflect actual history |
