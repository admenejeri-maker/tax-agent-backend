# P0.1 — User Authentication Architecture Plan (v2.0 — Post-Mortem Revision)

> **Task:** P0.1 User Authentication (API Keys → JWT)  
> **Size:** XL | **Priority:** P0 (Blocker) | **Planning Level:** Deep  
> **Date:** 2026-02-08 | **Revision:** v2.0 (incorporates lessons from failed v1.0 attempt)

---

## 0. Post-Mortem: Why v1.0 Failed

> [!CAUTION]
> The first implementation attempt was fully reverted. This section documents the 5 critical mistakes to prevent recurrence.

### Mistake #1: Config + Feature Flag Was Step 7 (Should Be Step 1)
**Impact:** `dependencies.py` imported `settings.require_api_key` which didn't exist → `AttributeError` at runtime.  
**Fix:** Config changes are now **Step 1** — all code that depends on settings must find them already in place.

### Mistake #2: No Verification Gates Between Steps
**Impact:** Backend + CORS + frontend were deployed as a single batch. When frontend broke, everything had to be reverted.  
**Fix:** Each major phase now has an explicit **GATE** — a `curl` or browser test that must pass before proceeding.

### Mistake #3: Frontend Deployed Without Graceful Degradation
**Impact:** Frontend assumed `/auth/key` would always return 200. When it failed, the entire chat UI broke with no fallback.  
**Fix:** Frontend key management must include `try/catch` with fallback to unauthenticated mode.

### Mistake #4: CORS Not Updated Before Frontend Deploy
**Impact:** `X-API-Key` header wasn't in `allow_headers` → browser preflight rejected all requests.  
**Fix:** CORS update is now **Step 2** (immediately after config), before any frontend changes.

### Mistake #5: SSE Stream Headers Not Addressed
**Impact:** `EventSource` API cannot send custom headers. `X-API-Key` injection for SSE was never planned.  
**Fix:** SSE auth uses query parameter `?api_key=xxx` as a documented exception, validated server-side.

---

## 1. Current State Analysis (Move 1: Deep Analysis)

### 1.1 Attack Surface Audit

| Endpoint | Method | Auth | Vulnerability |
|----------|--------|------|---------------|
| `/` | GET | None | LOW — Info disclosure only |
| `/health` | GET | None | LOW — Operational data |
| `/chat` | POST | None | **CRITICAL** — Any `user_id` accepted |
| `/chat/stream` | POST | None | **CRITICAL** — SSE stream, same issue |
| `/cache/metrics` | GET | Admin Token | OK |
| `/cache/refresh` | POST | Admin Token | OK |
| `/session/clear` | POST | Admin Token | OK |
| `/sessions` | GET | Admin Token | OK |
| `/sessions/{user_id}` | GET | None | **HIGH** — IDOR: anyone can read any user's sessions |
| `/session/{session_id}/history` | GET | None | **HIGH** — IDOR: session history exposed |
| `/user/{user_id}/data` | DELETE | None | **CRITICAL** — Delete any user's data |

### 1.2 Existing Auth Primitives (Reusable)

The following backend code **already exists** from the reverted v1.0 attempt and is largely correct:

| File | Status | Notes |
|------|--------|-------|
| `app/auth/key_generator.py` | ✅ Intact | `secrets` module, SHA-256 hashing, `wk_` prefix |
| `app/auth/api_key_store.py` | ✅ Intact | MongoDB CRUD, timing-safe compare, concurrent upsert |
| `app/auth/dependencies.py` | ⚠️ Needs fix | References `settings.require_api_key` which doesn't exist yet |
| `config.py` | ❌ Missing auth fields | `require_api_key`, `api_key_max_per_ip` never added |
| `main.py` | ❌ Auth disconnected | No imports, no `Depends()` on endpoints |

---

## 2. Recommended Architecture: Approach C (Hybrid Phased)

> Evaluated 3 approaches (A: API Keys only, B: JWT only, C: Hybrid). See Appendix for full Tree of Thoughts.

**Phase 1 (This sprint):** API key auth for all public endpoints. Frontend auto-generates key. Feature flag for gradual rollout.  
**Phase 2 (Future sprint):** Optional JWT login. API keys become "anonymous" tier.

### 2.1 Data Model: `api_keys` Collection

```python
{
    "_id": ObjectId,
    "key_hash": "<sha256>",             # NEVER store raw key
    "key_prefix": "wk_a3f2...",         # First 8 chars for admin identification
    "user_id": "widget_abc123",          # Links to existing user_id
    "created_at": datetime,
    "expires_at": datetime,              # TTL: 365 days
    "last_used_at": datetime,
    "is_active": True,
    "rate_limit_tier": "standard",       # "standard" | "premium"
    "metadata": {
        "user_agent": "...",
        "origin": "https://scoop.ge",
        "ip_hash": "<sha256>"            # Hashed IP for privacy
    }
}
# Indexes: unique on key_hash, TTL on expires_at
```

### 2.2 API Changes

#### New Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/key` | POST | Generate new API key (rate-limited per IP) |
| `/auth/key/verify` | GET | Verify key is valid |

#### Protected Endpoints (Add `Depends(verify_api_key)`)
| Endpoint | Additional Check |
|----------|-----------------|
| `/chat` | Key valid only |
| `/chat/stream` | Key valid (via query param) |
| `/sessions/{user_id}` | + ownership check |
| `/session/{session_id}/history` | + session ownership check |
| `/user/{user_id}/data` | + ownership check |

### 2.3 SSE Auth Strategy

> [!IMPORTANT]
> `EventSource` cannot send custom headers. SSE endpoints use query parameter auth.

```
POST /chat/stream?api_key=wk_xxx    → Backend extracts from query param
                                    → Same validation as X-API-Key header
```

Server-side: Accept key from either `X-API-Key` header OR `api_key` query param. Log a warning when query param is used (for future deprecation when switching to JWT).

---

## 3. Implementation Order (v2.0 — Config-First, Gated)

> [!WARNING]
> **Each GATE must pass before proceeding to the next step.** This is the primary defense against the v1.0 failure mode.

### Step 1: Config + Feature Flag ⏱️ 15m
**Files:** `config.py`, `.env.example`

Add auth settings to `config.py`:
```python
require_api_key: bool = Field(
    default_factory=lambda: os.getenv("REQUIRE_API_KEY", "false").lower() == "true"
)
api_key_max_per_ip: int = Field(
    default_factory=lambda: int(os.getenv("API_KEY_MAX_PER_IP", "10"))
)
```

**🚦 GATE 1:** `python -c "from config import settings; print(settings.require_api_key)"` → prints `False`

---

### Step 2: CORS Header Update ⏱️ 10m
**Files:** `main.py` (CORSMiddleware)

Add `"X-API-Key"` to `allow_headers` in CORSMiddleware config.

**🚦 GATE 2:** `curl -X OPTIONS -H "Origin: http://localhost:3000" -H "Access-Control-Request-Headers: X-API-Key" http://localhost:8080/chat` → 200 with `X-API-Key` in `Access-Control-Allow-Headers`

---

### Step 3: MongoDB Index + Collection Setup ⏱️ 15m
**Files:** `app/memory/database.py`

Create `api_keys` collection with:
- Unique index on `key_hash`
- TTL index on `expires_at`

**🚦 GATE 3:** `db.api_keys.getIndexes()` shows both indexes

---

### Step 4: Reconnect Auth Module ⏱️ 1.5h
**Files:** `app/auth/dependencies.py` (fix config import), `main.py` (add imports)

1. Fix `dependencies.py` to import the now-existing config fields
2. Add auth module imports to `main.py`
3. Add `/auth/key` POST endpoint (key generation, rate-limited)
4. Add `/auth/key/verify` GET endpoint

**🚦 GATE 4a:** `curl -X POST http://localhost:8080/auth/key` → 200 with `{"key": "wk_...", "user_id": "...", "expires_at": "..."}`  
**🚦 GATE 4b:** `curl -H "X-API-Key: <key_from_4a>" http://localhost:8080/auth/key/verify` → 200  
**🚦 GATE 4c:** All existing endpoints still work WITHOUT keys (feature flag is `false`)  

---

### Step 5: Protect Chat Endpoints ⏱️ 30m
**Files:** `main.py` (modify `/chat`, `/chat/stream`)

Add `Depends(verify_api_key)` to `/chat` and `/chat/stream`. Since `REQUIRE_API_KEY=false`, the dependency should pass through when no key is provided.

Add query param extraction for SSE: accept `api_key` query parameter as alternative to header.

**🚦 GATE 5a:** `curl -X POST http://localhost:8080/chat -d '{"message":"hi","user_id":"test"}'` → 200 (no key, flag off)  
**🚦 GATE 5b:** `curl -X POST -H "X-API-Key: <valid_key>" http://localhost:8080/chat -d '{"message":"hi","user_id":"test"}'` → 200 (with key)  

---

### Step 6: Protect Data Endpoints + IDOR Fix ⏱️ 1h
**Files:** `main.py` (modify session/user endpoints)

Add `verify_ownership` and `verify_session_ownership` dependencies to:
- `GET /sessions/{user_id}` 
- `GET /session/{session_id}/history`
- `DELETE /user/{user_id}/data`

**🚦 GATE 6a:** `curl -H "X-API-Key: <user_A_key>" http://localhost:8080/sessions/user_B` → 403 (IDOR blocked)  
**🚦 GATE 6b:** `curl -H "X-API-Key: <user_A_key>" -X DELETE http://localhost:8080/user/user_B/data` → 403  

---

### Step 7: Frontend Key Management ⏱️ 1.5h
**Files:** `useChatSession.ts`, `Chat.tsx`, `useSSEStream.ts`, `api.ts`

> [!IMPORTANT]
> Frontend MUST implement graceful degradation. If `/auth/key` fails, fall back to unauthenticated mode.

```typescript
// Pseudocode for key management
try {
    let apiKey = localStorage.getItem('scoop_api_key');
    if (!apiKey) {
        const res = await fetch(`${BACKEND_URL}/auth/key`, { method: 'POST' });
        if (!res.ok) throw new Error(`Key generation failed: ${res.status}`);
        const data = await res.json();
        apiKey = data.key;
        localStorage.setItem('scoop_api_key', apiKey);
    }
    // Inject X-API-Key header into all fetch calls
    // For SSE: append ?api_key=xxx to stream URL
} catch (err) {
    console.warn('Auth unavailable, continuing without key:', err);
    // Graceful degradation: chat still works if REQUIRE_API_KEY=false
}
```

**🚦 GATE 7a:** Open browser → Console shows "API key generated" or "Auth unavailable" — no crashes  
**🚦 GATE 7b:** Send a chat message → Response streams back successfully  
**🚦 GATE 7c:** Inspect Network tab → `X-API-Key` header present on `/chat` requests  
**🚦 GATE 7d:** Inspect Network tab → SSE request includes `?api_key=` query param  

---

### Step 8: Feature Flag ON ⏱️ 5m
**Action:** Set `REQUIRE_API_KEY=true` in environment

**🚦 GATE 8a:** `curl -X POST http://localhost:8080/chat -d '{"message":"hi","user_id":"test"}'` → 401 (no key = rejected)  
**🚦 GATE 8b:** Full browser test → chat works end-to-end with key  
**🚦 GATE 8c:** Clear localStorage → page reloads → new key auto-generated → chat works  

---

### Step 9: Unit Tests ⏱️ 2.5h
**Files:** `tests/test_auth.py`, `tests/test_endpoints_auth.py`

| Test | Validates |
|------|-----------|
| Key generation returns valid format | `wk_` prefix, correct length |
| Invalid key → 401 | Key validation works |
| Expired key → 401 | TTL enforcement |
| Revoked key → 403 | `is_active=false` check |
| IDOR: user A key → user B sessions → 403 | Ownership check |
| IDOR: user A key → delete user B data → 403 | Delete protection |
| Session ownership: key → unowned session → 403 | `verify_session_ownership` |
| Feature flag off → no key required | Graceful degradation |
| Feature flag on → key required | Enforcement |
| Concurrent key generation → single key | Upsert idempotency |
| Timing-safe comparison | No timing side-channel |
| Query param auth for SSE | Alternative auth path |

**🚦 GATE 9:** `pytest tests/test_auth.py tests/test_endpoints_auth.py -v` → all pass

---

**Total Estimated: ~7.5 hours** (reduced from 9.5h by reusing existing auth module code)

---

## 4. Migration Strategy (3-Day Rollout)

| Day | Action | Rollback |
|-----|--------|----------|
| 1 | Deploy backend (Steps 1-6). Feature flag OFF. Auth module active but optional. | Remove auth imports from `main.py` |
| 2 | Deploy frontend (Step 7). Keys auto-generated. Backend logs key presence but doesn't enforce. | Revert `useChatSession.ts` changes only |
| 3 | Set `REQUIRE_API_KEY=true` (Step 8). All requests without key get 401. | Set flag to `false` → instant rollback |

---

## 5. Premortem Risk Analysis

| Risk | Prob | Impact | Mitigation |
|------|:----:|:------:|------------|
| API key leaked in client JS | HIGH | MED | Keys are per-widget, auto-regenerable |
| MongoDB query bottleneck | LOW | HIGH | Index on `key_hash`; LRU cache for hot keys |
| Frontend breaks during migration | MED | HIGH | Feature flag OFF + graceful degradation in `try/catch` |
| Key generation race condition | LOW | LOW | Idempotent upsert on `user_id` |
| localStorage cleared | MED | LOW | Auto-regenerate; old key remains valid |
| CORS preflight rejects header | MED | MED | Step 2 ensures `X-API-Key` in `allow_headers` BEFORE frontend |
| SSE can't send headers | HIGH | HIGH | Query param fallback (Step 5) |

---

## 6. Adversarial Review Verdict

> Reviewed by Claude (QA Role) on 2026-02-08

### Accepted (integrated above)
| Item | Impact |
|------|--------|
| `secrets.compare_digest()` timing-safe comparison | Prevents timing attacks |
| `key_prefix` field (first 8 chars) | Admin identification without key exposure |
| `ip_hash` in metadata | Privacy-aware logging |
| `verify_session_ownership()` dependency | Fixes `/session/{session_id}` gap |
| Concurrent key gen handling (upsert) | Multi-tab safety |
| `expires_at` with 365-day TTL | Security hygiene |
| MongoDB index at Step 3 (before any key ops) | Dependency order |

### Rejected (over-engineered for Phase 1)
| Item | Reason |
|------|--------|
| Middleware pattern (replace Depends) | Breaks FastAPI idiom |
| HTTPS enforcement middleware | Cloud Run handles this |
| Circuit breaker for MongoDB | App-wide concern, not auth-specific |
| Audit logging collection | Depends on P1.3 (structlog) — not yet implemented |

### Deferred (Phase 1.5 / Phase 2)
| Item | When |
|------|------|
| Key revocation endpoint | Phase 1.5 (admin dashboard) |
| Key rotation mechanism | Phase 2 (with JWT) |
| Safari ITP localStorage wipe | Cross-cutting concern |

---

*Generated by Opus Planning + Adversarial Review workflow — v2.0 revision incorporating 5 post-mortem lessons from failed v1.0 attempt.*
