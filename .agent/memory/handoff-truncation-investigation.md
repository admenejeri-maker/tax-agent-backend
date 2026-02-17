# 🔧 Handoff: Low-Latency Truncation Detection Investigation

**Date:** 2026-02-04 ~19:57
**Priority:** HIGH
**Status:** RESEARCH_PENDING
**Orchestrator:** Antigravity → Claude Code
**Confidence Required:** 90%+

---

## 📋 Executive Summary

წინა სესიაში ჩატარდა `/deep-research` Tavily-ით და დადგინდა, რომ "Validator Agent" პატერნი (ტექსტის შემოწმება და regeneration) **არ გამოიყენება** industry-ში latency cost-ის გამო (+5-10s).

**შენი ამოცანა:** მოძებნე **ალტერნატიული გადაწყვეტა** რომელიც:
- არ დაამატებს 10 წამს latency-ს
- 90%+ confidence-ით იმუშავებს
- თუ ვერ იპოვი → **პირდაპირ თქვი რომ ვერ ნახე**

---

## 🚫 STRICT CONSTRAINTS

1. **არაფერი არ დანერგო** სანამ არ შეისწავლი პროექტს
2. **არ შესთავაზო** გადაწყვეტა < 90% confidence-ით
3. **თუ ვერ ნახე** → აღიარე პირდაპირ, ნუ გამოიგონებ
4. **Latency budget:** max +2-3 წამი, არა +10 წამი

---

## 📖 Previous Research Summary

### რა გამოიკვლია Antigravity:

| წყარო | აღმოჩენა |
|-------|----------|
| Tavily (ApX ML) | `finish_reason: length` = truncation signal |
| Tavily (arXiv) | Streaming content monitoring possible at 30% tokens |
| Context7 (Gemini) | finish_reason available in streaming |
| GitHub (328 issues) | No "validator agent" pattern in production |

### რატომ არ რეკომენდირდა Validator Agent:

| პრობლემა | ახსნა |
|----------|-------|
| Latency | +5-10 წამი (regeneration doubles response time) |
| Coherence | Continuation may break context |
| Low ROI | 90% truncations are SAFETY, not length |

### Scoop-ს უკვე აქვს:

- ✅ Hybrid Inference (Gemini 3→2.5→Flash fallback)
- ✅ SAFETY threshold 800 chars
- ✅ CircuitBreaker pattern
- ✅ finish_reason logging

---

## 🔬 Your Investigation Protocol

### Phase 1: Study the Project (MANDATORY FIRST!)

**არაფერი არ შესთავაზო სანამ ამას არ გააკეთებ:**

```bash
# 1. Backend Core Files
view_file /Users/maqashable/Desktop/scoop/backend/app/core/engine.py
view_file /Users/maqashable/Desktop/scoop/backend/app/core/function_loop.py
view_file /Users/maqashable/Desktop/scoop/backend/app/services/gemini_adapter.py
view_file /Users/maqashable/Desktop/scoop/backend/app/core/model_router.py

# 2. Config & Prompts
view_file /Users/maqashable/Desktop/scoop/backend/app/config.py
view_file /Users/maqashable/Desktop/scoop/backend/prompts/system_prompt.py

# 3. Frontend SSE Handling
view_file /Users/maqashable/Desktop/scoop/frontend/src/components/Chat.tsx
view_file /Users/maqashable/Desktop/scoop/frontend/src/hooks/useChatSession.ts

# 4. Previous Research
view_file /Users/maqashable/.gemini/antigravity/brain/5ecde4a4-713f-41db-8232-0c6cbc4262b6/truncation_research_report.md

# 5. Development History
view_file /Users/maqashable/Desktop/scoop/backend/CONTEXT.md
```

### Phase 2: Deep Research with Tavily (NEW ANGLES)

გაუშვი `/deep-research` ახალი კუთხეებით:

```yaml
Research Queries (Tavily):
  1. "LLM response streaming early termination detection low latency"
  2. "Gemini API partial response continuation without full regeneration"
  3. "incremental response validation AI chatbot pattern"
  4. "finish_reason handling continue generation same context"
  5. "streaming response completeness check heuristics"
```

### Phase 3: Synthesize & Evaluate

**თითოეული შესაძლო გადაწყვეტა შეაფასე:**

| Criteria | Threshold |
|----------|-----------|
| Latency overhead | ≤ 3 seconds |
| Implementation complexity | ≤ 50 lines |
| Reliability | ≥ 90% |
| Edge cases covered | Length + SAFETY |

---

## 🎯 Potential Solution Directions to Explore

### Direction 1: Continuation Instead of Regeneration

**Hypothesis:** If `finish_reason=length`, append "Please continue" instead of full regeneration.

```python
# Pseudocode
if finish_reason == "length":
    continuation = await gemini.generate(
        messages=[*history, {"role": "assistant", "content": partial_response}],
        prompt="Continue from where you left off."
    )
    return partial_response + continuation
```

**Questions to research:**
- Does Gemini/OpenAI support continuation from partial?
- What's the latency overhead?
- Does it break coherence?

### Direction 2: Heuristic Detection (No Extra API Call)

**Hypothesis:** Detect truncation via heuristics without extra LLM call.

```python
def is_likely_truncated(response: str, finish_reason: str) -> bool:
    if finish_reason in ["length", "SAFETY"]:
        return True
    # Heuristic checks (zero latency overhead)
    if len(response) < 50:
        return True
    if not response.rstrip().endswith((".", "!", "?", ":", ")")):
        return True
    if response.endswith(("...", "ა...", "ე...")):  # Mid-word cut
        return True
    return False
```

**Questions to research:**
- What's the false positive rate?
- Is this used in production systems?

### Direction 3: Streaming Mid-Stream Monitoring

**Hypothesis:** Monitor tokens during streaming, stop early if detecting truncation pattern.

**Questions to research:**
- Can we detect SAFETY trigger mid-stream?
- Is there a "continuation token" pattern?

---

## ❌ What NOT to Do

1. ❌ Don't implement anything without 90% confidence
2. ❌ Don't add +10s latency solutions
3. ❌ Don't guess - research with Tavily
4. ❌ Don't touch code until you understand the project
5. ❌ Don't force a solution if none exists

---

## ✅ Expected Output

### If Solution Found:

```markdown
## ✅ Solution Found

**Pattern:** [Name]
**Confidence:** [X]%
**Latency Overhead:** [X]s
**Implementation Location:** [file:line]

### Evidence
- Source 1: [link]
- Source 2: [link]

### Implementation Plan
1. [Step 1]
2. [Step 2]
```

### If No Solution Found:

```markdown
## ❌ No Viable Solution Found

**Research Conducted:**
- Tavily queries: [list]
- Documentation checked: [list]
- Patterns evaluated: [list]

**Conclusion:**
Industry does not have a low-latency (<3s) truncation detection + fix pattern.
Scoop's existing Hybrid Inference is the current best practice.

**Alternative Recommendations:**
1. Increase SAFETY threshold: 800 → 1000 chars
2. Increase max_tokens default
3. Accept occasional truncation as normal LLM behavior
```

---

## 📁 Project Structure Reference

```
/Users/maqashable/Desktop/scoop/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── engine.py          # Main chat engine
│   │   │   ├── function_loop.py   # FC handling + streaming
│   │   │   ├── model_router.py    # Hybrid inference routing
│   │   │   └── response_buffer.py # SSE buffering
│   │   ├── services/
│   │   │   └── gemini_adapter.py  # Gemini API wrapper
│   │   └── config.py              # ThinkingConfig, model settings
│   ├── prompts/
│   │   └── system_prompt.py       # Georgian system prompt
│   └── CONTEXT.md                 # 3000-line debug history
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   └── Chat.tsx           # SSE handling, TextDecoder
│   │   └── hooks/
│   │       └── useChatSession.ts  # Session persistence
└── .agent/
    └── workflows/
        └── deep-research.md       # Research protocol
```

---

## 🚀 Start Command

```
1. Read truncation_research_report.md
2. Study project files (Phase 1)
3. Run /deep-research with new Tavily queries (Phase 2)
4. Synthesize findings (Phase 3)
5. Report with 90%+ confidence OR admit no solution exists
```

---

*Handoff generated by Antigravity Orchestrator*
*Target: Claude Code Worker Agent*
