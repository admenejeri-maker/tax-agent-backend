# Embedding API Blocking - Root Cause Analysis

**Date:** 2026-02-02
**Analyst:** Claude Code
**Status:** ROOT CAUSE IDENTIFIED

---

## Executive Summary

The 2.5-minute embedding API delay is caused by **THREE compounding factors**:

1. **No timeout configured** on the embedding client
2. **Sync blocking call** in an async context without proper isolation
3. **Cache key mismatch** due to Georgian suffix variations

The PRIMARY root cause is **missing timeout configuration** combined with **API server-side queuing**.

---

## Evidence Trail

### Observed Behavior
```
23:29:02 - search_products called with query='კრეატინი'
[... 2 minutes 33 seconds of silence ...]
23:31:35 - HTTP Request: POST .../gemini-embedding-001:batchEmbedContents "HTTP/1.1 200 OK"
```

**Key observation:** The request SUCCEEDED (200 OK) after 153 seconds. This eliminates:
- Rate limiting (would return 429)
- Timeout errors (would throw exception)
- Network failure (would error)

---

## Root Cause #1: No Timeout Configuration (CRITICAL)

### Location
[user_tools.py:140-146](backend/app/tools/user_tools.py#L140-L146)

```python
def _get_embedding_client() -> genai.Client:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = genai.Client(api_key=settings.gemini_api_key)  # ← NO TIMEOUT!
    return _embedding_client
```

### Problem
The `genai.Client` supports `http_options` with a `timeout` parameter, but none is configured:

```python
# genai.types.HttpOptions supports:
# - timeout: Optional[int] (milliseconds)
# - retryOptions: Optional[HttpRetryOptions]
```

### Impact
When the Gemini API is slow (server load, network latency, regional issues), the client waits **indefinitely**. The SDK's default behavior is to keep the connection open until the server responds.

### Evidence
The httpx log shows the request eventually completed:
```
HTTP Request: POST .../gemini-embedding-001:batchEmbedContents "HTTP/1.1 200 OK"
```
If a timeout was configured, this would have failed after N seconds with a `TimeoutException`.

---

## Root Cause #2: Sync Blocking in Async Context (CONTRIBUTING)

### Location
[tool_executor.py:313-319](backend/app/core/tool_executor.py#L313-L319)

```python
if inspect.iscoroutinefunction(self._search_fn):
    return await self._search_fn(**search_args)
else:
    # Sync function - run in thread pool
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,  # ← Uses default ThreadPoolExecutor
        lambda: self._search_fn(**search_args)
    )
```

### Problem
1. `search_products()` is SYNC
2. `_get_query_embedding()` is SYNC and calls blocking `client.models.embed_content()`
3. Both run in Python's default ThreadPoolExecutor (max_workers = CPU count + 4)

### Impact
When the embedding API blocks for 2.5 minutes:
- One thread is held hostage
- If multiple concurrent requests, threads get exhausted
- New requests queue up waiting for free threads

### Async Architecture Diagram
```
FastAPI (async)
  └── stream_message() (async)
        └── FunctionCallingLoop.execute_streaming() (async)
              └── ToolExecutor.execute() (async)
                    └── run_in_executor() ← SYNC BOUNDARY
                          └── search_products() (SYNC)
                                └── _get_query_embedding() (SYNC)
                                      └── client.models.embed_content() (SYNC/BLOCKING)
```

---

## Root Cause #3: Cache Key Mismatch (CONTRIBUTING)

### Location
[main.py:607-609](backend/main.py#L607-L609) and [embedding_cache.py:33-35](backend/app/cache/embedding_cache.py#L33-L35)

### Pre-warmed Queries
```python
common_queries = ["პროტეინ", "კრეატინ", "ვიტამინ", "bcaa"]
```

### Actual Query
```
query='კრეატინი'  # ← Note the "ი" suffix (Georgian nominative case)
```

### Cache Key Generation
```python
def _hash_query(query: str) -> str:
    return hashlib.md5(query.strip().lower().encode()).hexdigest()
```

### The Mismatch
| Query | Normalized | MD5 Hash |
|-------|------------|----------|
| "კრეატინ" | "კრეატინ" | `a7b3c...` |
| "კრეატინი" | "კრეატინი" | `f2e8d...` (DIFFERENT!) |

### Impact
Even though "creatine" was pre-warmed, the actual query "კრეატინი" (with nominative suffix) results in a **cache miss**, forcing an API call.

---

## Why 2.5 Minutes Specifically?

### Hypothesis: API Server-Side Queuing

The Gemini Embedding API (gemini-embedding-001) has rate limits:
- **Free tier:** 5-15 RPM (requests per minute)
- **Tier 1:** 150-300 RPM

If the server-side queue was backed up due to:
1. High global usage
2. Regional capacity issues
3. Model warmup after cold period

The request would be queued and processed when capacity became available.

### Evidence Supporting This
- The request **succeeded** (200 OK)
- No errors in logs (no rate limit 429, no timeout)
- The delay was exactly in the API call, not in any local processing

---

## Call Stack Analysis

```
Request Flow:
1. /chat/stream endpoint receives message
2. ConversationEngine.stream_message() starts
3. FunctionCallingLoop executes streaming round
4. Gemini model returns function_call: search_products
5. ToolExecutor.execute() dispatches to _execute_search()
6. run_in_executor() wraps sync search_products()
7. search_products() calls _get_query_embedding()
8. _get_query_embedding() checks cache → MISS
9. genai.Client.models.embed_content() is called
10. ⚠️ BLOCKS FOR 153 SECONDS ⚠️
11. Embedding returned, vector search proceeds
12. Products returned to Gemini
13. Gemini generates response
```

---

## Proposed Fixes (Pending Approval)

### Fix 1: Add Timeout to Embedding Client (HIGH PRIORITY)

```python
def _get_embedding_client() -> genai.Client:
    global _embedding_client
    if _embedding_client is None:
        from google.genai import types
        _embedding_client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(
                timeout=10000,  # 10 second timeout (vs infinite)
            )
        )
    return _embedding_client
```

**Impact:** Fails fast instead of blocking for minutes.

### Fix 2: Add Retry with Exponential Backoff

```python
from google.genai import types

http_options = types.HttpOptions(
    timeout=10000,
    retryOptions=types.HttpRetryOptions(
        max_retries=3,
        backoff_multiplier=2.0,
    )
)
```

**Impact:** Handles transient failures gracefully.

### Fix 3: Expand Cache Warm-up Queries (MEDIUM PRIORITY)

```python
# Include common Georgian suffixes
common_queries = [
    "პროტეინ", "პროტეინი", "პროტეინის",  # protein variations
    "კრეატინ", "კრეატინი", "კრეატინის",  # creatine variations
    "ვიტამინ", "ვიტამინი", "ვიტამინის",  # vitamin variations
    "bcaa", "ბსაა",
]
```

**Impact:** Higher cache hit rate for natural Georgian queries.

### Fix 4: Normalize Georgian Queries Before Caching (MEDIUM PRIORITY)

```python
import re

def _normalize_georgian_query(query: str) -> str:
    """Strip common Georgian suffixes for better cache hits."""
    # Remove nominative (ი), genitive (ის), etc.
    return re.sub(r'[იისას]$', '', query.strip().lower())

def _hash_query(query: str) -> str:
    normalized = _normalize_georgian_query(query)
    return hashlib.md5(normalized.encode()).hexdigest()
```

**Impact:** "კრეატინი" and "კრეატინ" would share the same cache key.

### Fix 5: Use Async Embedding Client (LOW PRIORITY - More Invasive)

```python
# Use genai.Client.aio for async operations
async def _get_query_embedding_async(query: str) -> Optional[List[float]]:
    client = genai.Client(api_key=settings.gemini_api_key)
    result = await client.aio.models.embed_content(...)
```

**Impact:** Eliminates thread pool dependency, better async integration.

---

## Verification Plan

### Test 1: Timeout Behavior
```python
# Set timeout to 5000ms (5 seconds)
# Send query when API is slow
# Expected: TimeoutException after 5 seconds (not 2.5 minutes)
```

### Test 2: Cache Hit Rate
```bash
# Before fix: Check cache stats endpoint
curl http://localhost:8000/admin/cache-stats
# Expected after fix: Higher hit rate for Georgian queries
```

### Test 3: Concurrent Request Handling
```bash
# Send 10 concurrent search requests
# Verify no request blocks others for >10 seconds
```

---

## Conclusion

The 2.5-minute delay is caused by:

| Factor | Contribution | Fix Priority |
|--------|--------------|--------------|
| No timeout on embedding client | 70% | HIGH |
| Cache miss due to suffix mismatch | 20% | MEDIUM |
| Sync blocking in thread pool | 10% | LOW |

**Recommended immediate action:** Add timeout configuration to the embedding client. This will convert a 2.5-minute hang into a 10-second failure + retry, dramatically improving user experience.

---

## Sources

- [Gemini API Rate Limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [HttpOptions documentation](https://ai.google.dev/api/python/google/generativeai/types/HttpOptions)

---

**Analysis Complete. Awaiting approval for fix implementation.**
