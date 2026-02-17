# 🎯 HANDOFF: Scoop Backend Code Simplification

**Date:** 2026-02-02
**Target:** Claude Code (via `/opus-planning`)
**Objective:** Analyze, simplify, and stabilize the Scoop AI backend

---

## 📋 Mission Brief

**მიზანი:** კოდის გამარტივება სტაბილურობისა და სისწრაფისთვის

### Core Requirements:
1. **Response Time:** მაქსიმუმ **10 წამი** პასუხის დაბრუნებამდე
2. **Simplicity:** მარტივი კოდი, მარტივი დებაგინგი
3. **Stability:** სტაბილური მუშაობა ყველა შემთხვევაში
4. **Same Functionality:** იგივე ფუნქციონალი, უფრო მარტივი იმპლემენტაცია

---

## 📂 Files to Analyze

### Core Engine (Priority 1 - Critical)
```
backend/app/core/
├── engine.py           # Main conversation orchestrator (~600 lines)
├── function_loop.py    # Gemini function calling loop (~600 lines)  
├── tool_executor.py    # Tool execution layer (~500 lines)
├── types.py            # Data structures (~350 lines)
└── stream_orchestrator.py  # Streaming logic
```

### Tools & Search (Priority 2)
```
backend/app/tools/
├── user_tools.py       # Product search, user profile (~850 lines)
└── embedding_cache.py  # Vector embedding cache
```

### Memory System (Priority 3)
```
backend/app/memory/
├── tiered_memory.py    # Tiered memory implementation
├── context_compactor.py # Context compaction
└── hybrid_manager.py   # Memory orchestration
```

### API Layer
```
backend/app/api/
├── chat.py             # /chat endpoint
└── stream_chat.py      # /chat/stream endpoint
```

---

## 🔍 Analysis Instructions

### Step 1: Map Architecture
```bash
# Run these to understand the flow
grep -r "async def\|def " backend/app/core/*.py | head -50
grep -r "class " backend/app/core/*.py
```

### Step 2: Identify Complexity
Look for:
- [ ] რთული nested async/await chains
- [ ] ზედმეტი abstraction layers
- [ ] დუბლირებული ლოგიკა
- [ ] გადაჭარბებული error handling
- [ ] არასაჭირო state management

### Step 3: Trace Request Flow
```
User Request → /chat endpoint → ConversationEngine.process_message() 
→ FunctionCallingLoop → ToolExecutor → search_products() → Response
```

---

## 🎯 Simplification Goals

### 1. Latency Reduction (10 წამი target)
- Vector search cold-start elimination
- Embedding client pre-warming
- Reduce unnecessary async hops

### 2. Code Reduction
- Merge redundant classes
- Remove dead code paths
- Simplify state machines

### 3. Debugging Ease
- Clear logging at key points
- Simple data flow (A → B → C)
- No hidden magic

### 4. Error Resilience
- Graceful fallbacks
- Clear error messages
- No silent failures

---

## ⚠️ Known Issues to Address

1. **EmptyResponseError** - Occurs when model doesn't return text
2. **Search returning 0 products** - Deduplication sometimes too aggressive
3. **Cold-start latency** - First request takes longer
4. **Complex retry logic** - Multiple retry mechanisms overlap

---

## 📋 Deliverable Expected

### Implementation Plan (via /opus-planning)

```markdown
## Simplification Plan: Scoop Backend

### Approach Selection
- Option A: {describe}
- Option B: {describe}
- Recommended: {which and why}

### Files to Modify
| File | Action | Change Summary |
|------|--------|----------------|
| engine.py | Simplify | Remove X, merge Y |
| ... | ... | ... |

### Implementation Steps (TDD)
Step 1: ...
Step 2: ...

### Risk Mitigation
| Risk | Mitigation |
|------|------------|
| ... | ... |
```

---

## 🚫 Constraints

- **NO adding new abstractions** - გამარტივება გვინდა, არა გართულება
- **NO external dependencies** - არსებულს გამოვიყენებთ
- **NO breaking API** - endpoint-ები იგივე რჩება
- **NO data migration** - MongoDB schema უცვლელი

---

## ✅ Success Criteria

- [ ] `/chat` პასუხობს < 10 წამში (P95)
- [ ] კოდის ხაზები შემცირებულია 30%-ით მინიმუმ
- [ ] ერთი ფაილი = ერთი პასუხისმგებლობა
- [ ] არცერთი silent failure
- [ ] ლოგები აჩვენებს მთლიან flow-ს

---

## 🏁 How to Start

```bash
# 1. Run opus-planning workflow
/opus-planning

# 2. Analyze files listed above
# 3. Propose 2-3 simplification approaches
# 4. Create implementation plan
# 5. Get approval before coding
```

---

**Note:** შენ თვითონ გააანალიზე და გადაწყვიტე საუკეთესო გზა. ზემოთ მოცემული მხოლოდ მიმართულებებია, არა მზა გადაწყვეტილებები.
