# 🔬 CRITICAL INVESTIGATION: Embedding API Blocking Issue

**Handoff Created:** 2026-02-02 23:34 UTC+4
**Priority:** P0 - Critical User Experience Issue
**Handoff From:** Gemini CLI (Strategic Orchestrator)
**Handoff To:** Claude Code (Worker Agent)

---

## 🎯 Mission

**Investigate the root cause of why the Gemini Embedding API is blocking for 2+ minutes during `search_products` execution.**

DO NOT propose solutions until root cause is fully understood. This is a **Deep Analysis** task.

---

## 📍 Problem Statement

During live chat testing, the `/chat/stream` endpoint hangs for **2+ minutes** on the **last question** in a sequence of product queries. The hang occurs specifically in the `search_products` tool function when calling the embedding API.

### Observed Behavior

```
23:29:02 - 🔎 search_products called with query='კრეატინი'
[... 2 minutes 33 seconds of silence ...]
23:31:35 - HTTP Request: POST .../gemini-embedding-001:batchEmbedContents "HTTP/1.1 200 OK"
```

**Total Time to First Token (TTFT):** 165,109ms (2.75 minutes)
**Total Stream Time:** 172,168ms (2.87 minutes)

---

## 🔎 Investigation Scope

### 1. Primary Code Path to Analyze

```
/chat/stream endpoint
  → main.py: stream_chat()
    → engine.py: stream_message()
      → function_loop.py: streaming round
        → tool_executor.py: execute_function()
          → user_tools.py: search_products()
            → user_tools.py: _get_query_embedding() ⚠️ BLOCKING HERE
              → genai.Client.models.embed_content()
```

### 2. Key Files to Examine

| File | Purpose | Focus Area |
|------|---------|------------|
| `backend/app/tools/user_tools.py` | Tool functions | Lines 149-177: `_get_query_embedding()` |
| `backend/app/tools/user_tools.py` | Tool functions | Lines 417-510: `search_products()` |
| `backend/app/cache/embedding_cache.py` | Embedding cache | Cache hit/miss logic |
| `backend/app/core/tool_executor.py` | Tool execution | How tools are called |
| `backend/config.py` | Settings | Embedding model config |

### 3. Questions to Answer

1. **Why did the API call take 2.5 minutes?**
   - Is there rate limiting?
   - Is there network latency?
   - Is there a blocking issue in the event loop?

2. **Why didn't the cache help?**
   - Was "კრეატინი" not in the warm-up queries?
   - Is the cache working correctly?
   - Check `get_cached_embedding()` logic

3. **Is there an async/sync conflict?**
   - `_get_query_embedding()` is sync
   - `search_products()` is sync
   - Are they being called from an async context incorrectly?

4. **Is there connection pooling or client reuse issue?**
   - `_embedding_client` is a singleton
   - Is it thread-safe?
   - Is it being blocked by another request?

5. **What are the Gemini API quotas/limits?**
   - Check for 429 errors in logs
   - Check if we're hitting rate limits

---

## 📊 Evidence from Logs

### Server Logs (Relevant Excerpt)

```log
2026-02-02 23:28:49,392 - main - INFO - 🔥 Embedding client pre-warmed with 4 common queries
INFO:     Application startup complete.

# First question - user sends კრეატინი query
2026-02-02 23:28:57,555 - main - INFO - 🚀 v2.0 Stream: user=widget_qo1jgidgfma, session=3p3y3w9uivu
2026-02-02 23:28:59,441 - app.core.function_loop - INFO - 🔄 Streaming round 1/5
2026-02-02 23:29:02,106 - app.core.tool_executor - INFO - 🔧 Executing: search_products({'query': 'კრეატინი', ...})
2026-02-02 23:29:02,106 - app.tools.user_tools - INFO - 🔎 search_products called with query='კრეატინი'

# ⚠️ GAP: 2 minutes 33 seconds with NO logs

2026-02-02 23:31:35,240 - httpx - INFO - HTTP Request: POST .../gemini-embedding-001:batchEmbedContents "HTTP/1.1 200 OK"
2026-02-02 23:31:35,874 - app.tools.user_tools - INFO - 🧠 Vector search found 10 products for 'კრეატინი'
```

### Warm-up Queries (Check These)

In `main.py`, see what queries are warmed up:
```python
# Look for warmup_queries or similar
```

---

## 🧪 Reproduction Steps

1. Start backend server with debug logging:
   ```bash
   cd /Users/maqashable/Desktop/scoop/backend
   source venv/bin/activate
   uvicorn main:app --host 0.0.0.0 --port 8000 --log-level debug
   ```

2. Open browser to `http://localhost:3000`

3. Send multiple product questions in sequence:
   - "რა პროტეინები გაქვთ?"
   - "რა კრეატინები გაქვთ?"
   - "რა ვიტამინები გაქვთ?"
   - "რა BCAA გაქვთ?"
   - "რა პრევორკაუტები გაქვთ?"

4. Observe if last question hangs significantly longer

---

## 🔍 Specific Investigation Tasks

### Task 1: Analyze `_get_query_embedding()` function

```python
# File: backend/app/tools/user_tools.py, lines 149-177
def _get_query_embedding(query: str) -> Optional[List[float]]:
    # Check cache first
    cached = get_cached_embedding(query)
    if cached is not None:
        return cached
    
    # Cache miss - generate embedding
    try:
        client = _get_embedding_client()  # ← Is this blocking?
        result = client.models.embed_content(  # ← Is this the bottleneck?
            model=settings.embedding_model,
            contents=query,
            config={"output_dimensionality": 768}
        )
        # ...
```

**Investigate:**
- Does `_get_embedding_client()` create a new client each time or reuse?
- Is `embed_content()` a blocking sync call?
- What is the timeout configuration?
- Is there httpx client connection pooling?

### Task 2: Check Embedding Cache

```python
# File: backend/app/cache/embedding_cache.py
```

**Investigate:**
- What is the cache implementation (in-memory, Redis, etc.)?
- What is the cache TTL?
- What queries are pre-warmed?
- Is "კრეატინი" being cached after first call?

### Task 3: Analyze Tool Executor Context

```python
# File: backend/app/core/tool_executor.py
```

**Investigate:**
- How are tools being called (sync vs async)?
- Is there `asyncio.to_thread()` usage?
- Could there be event loop blocking?

### Task 4: Check Network/API Configuration

```python
# File: backend/config.py
```

**Investigate:**
- What is `settings.embedding_model`?
- Are there any timeout settings?
- Is there retry configuration?

### Task 5: Check Gemini API Quotas

**Investigate:**
- What are the rate limits for `gemini-embedding-001`?
- Are we hitting quota limits after multiple queries?
- Check for any 429 responses in full logs

---

## 📁 Key File Paths

```
/Users/maqashable/Desktop/scoop/backend/
├── app/
│   ├── tools/user_tools.py          # 🔴 PRIMARY: _get_query_embedding, search_products
│   ├── cache/embedding_cache.py     # Cache implementation
│   ├── core/
│   │   ├── tool_executor.py         # How tools are executed
│   │   ├── function_loop.py         # Streaming loop
│   │   └── engine.py                # Main engine
│   └── adapters/
│       └── gemini_adapter.py        # Gemini client
├── config.py                        # Settings
└── main.py                          # Startup, warm-up
```

---

## ✅ Expected Deliverables

1. **Root Cause Analysis Document** explaining:
   - Exactly why the API call blocked for 2.5 minutes
   - Whether this is a code issue, API issue, or configuration issue
   - Evidence supporting the root cause

2. **Proposed Fix** (only after root cause is confirmed):
   - Code changes needed
   - Configuration changes if any
   - Testing strategy

---

## 🚫 Constraints

- DO NOT implement fixes until root cause is confirmed
- DO NOT restart the server without documenting current state
- DO NOT modify code without explicit approval
- Focus on investigation FIRST

---

## 📞 Communication

Report findings by updating this file or creating a new analysis document at:
`/Users/maqashable/Desktop/scoop/.agent/memory/EMBEDDING_ROOT_CAUSE_ANALYSIS.md`

---

**End of Handoff**
