---
status: REVIEWED ✅
date: 2026-02-16
reviewer: Antigravity (Opus 4) + Claude Code (Adversarial QA)
total_tests: 73
total_tasks: 8 (19 sub-tasks)
phase: 1 — MVP
review_log:
  - "v4 → v5: 7 Intelligence Layers + Claude Code adversarial review (3🔴 + 5🟡 + 4🟢)"
  - "v5 final: SSE streaming, session persistence, auth middleware added to Phase 1 (Task 7 expanded 7→15 tests)"
  - "Coherence review: all task dependencies verified, Phase 2 roadmap updated"
  - "v5.1: MongoDB gap analysis — added database name, embedding_model tracking, session/api_keys collections, metadata completeness"
---

# Opus Plan v5: Georgian Tax AI Agent (Python)

> **Confidence: 94%** (→ 95%+ after Task 3.0 spike) | Size: XL | Approach: **Independent Python Service** reusing Scoop patterns
>
> **v5:** 7 Intelligence Layers + Claude Code adversarial review fixes applied (3🔴 + 5🟡 + 4🟢)

---

## Key Change: Node.js → Python

The existing Scoop Python backend provides ~90% of the infrastructure needed. Instead of building from scratch in Node.js, we **copy proven patterns** into an independent service.

## Reuse Map (from `/backend/`)

| Scoop Component | What We Copy | Tax Agent Adaptation |
|---|---|---|
| [config.py](file:///Users/maqashable/Desktop/scoop-sagadasaxado/backend/config.py) | BaseModel + os.getenv() pattern | Remove Scoop settings, add `embedding_dimensions`, `chunk_size`, `SIMILARITY_THRESHOLD=0.65` |
| [database.py](file:///Users/maqashable/Desktop/scoop-sagadasaxado/backend/app/memory/database.py) | Singleton `DatabaseManager` (motor) | 🟡 **COPY & ADAPT** — replace `_create_indexes()`, remove Scoop constants |
| [gemini_adapter.py](file:///Users/maqashable/Desktop/scoop-sagadasaxado/backend/app/adapters/gemini_adapter.py) | `call_with_retry()`, existing `embed_content()` | 🟡 Keep `embed_content()` (line 587), add only `embed_batch()` |
| [conversation_store.py](file:///Users/maqashable/Desktop/scoop-sagadasaxado/backend/app/memory/conversation_store.py) | Session CRUD, history chain (~150 lines) | 🟡 **EXTRACT** from 554-line file, not mongo_adapter.py |
| [georgian_normalizer.py](file:///Users/maqashable/Desktop/scoop-sagadasaxado/backend/app/memory/georgian_normalizer.py) | `strip_georgian_suffix()` | Reuse for query normalization |
| [auth/dependencies.py](file:///Users/maqashable/Desktop/scoop-sagadasaxado/backend/app/auth) | API key validation middleware | 🟢 **COPY AS-IS** — domain-agnostic header check |
| [main.py StreamingResponse](file:///Users/maqashable/Desktop/scoop-sagadasaxado/backend/main.py) | SSE event generator pattern | 🟡 **COPY & ADAPT** — change event types: `products`→`sources`, `tip`→`disclaimer` |
| [Dockerfile](file:///Users/maqashable/Desktop/scoop-sagadasaxado/backend/Dockerfile) | Multi-stage build, Cloud Run pattern | Lighter requirements (no spacy, torch, etc.) |
| `requirements.txt` | Subset of 233 packages | ~16 packages: `fastapi`, `motor`, `google-genai`, `beautifulsoup4`, `structlog`, `pydantic`, etc. |

---

## Project Structure

```
scoop-sagadasaxado/tax-agent/        ← NEW independent directory
├── main.py                          ← FastAPI entry (copied pattern from Scoop)
├── config.py                        ← Pydantic Settings (adapted)
├── requirements.txt                 ← Lean (~16 packages)
├── Dockerfile                       ← Cloud Run ready (Python 3.11)
├── .env.example                     ← All env vars documented
├── .gitignore                       ← Python + venv + .env
├── pyproject.toml                   ← ruff + black config
├── app/
│   ├── __init__.py
│   ├── database.py                  ← COPY of Scoop's DatabaseManager
│   ├── auth/
│   │   ├── __init__.py
│   │   └── dependencies.py          ← COPY from Scoop (API key validation)
│   ├── models/
│   │   ├── tax_article.py           ← NEW: Pydantic model + Mongo ops
│   │   └── definition.py            ← NEW: ტერმინთა განმარტებები
│   ├── services/
│   │   ├── matsne_scraper.py        ← NEW: BeautifulSoup + aiohttp
│   │   ├── embedding_service.py     ← NEW: gemini-embedding-001 (768d, batch)
│   │   ├── vector_search.py         ← NEW: $vectorSearch + hybrid + cross-ref
│   │   ├── definition_resolver.py   ← NEW: ტერმინოლოგიური დამიწება
│   │   └── tax_agent.py             ← NEW: RAG pipeline + guardrails
│   ├── utils/
│   │   ├── georgian_normalizer.py   ← COPY from Scoop
│   │   └── retry.py                 ← COPY call_with_retry pattern
│   └── routes/
│       └── api.py                   ← NEW: /ask, /ask/stream, /sessions, /articles, /health
├── prompts/
│   └── tax_system_prompt.py         ← NEW: Georgian tax expert + lex specialis
└── scripts/
    ├── seed_database.py             ← NEW: Full scrape + embed + insert
    └── sync_matsne.py               ← NEW: Incremental update
```

### Project-Level Config (G5-G7)
```
Python: 3.11+
Linter: ruff (pyproject.toml)
Formatter: black (pyproject.toml)
CORS: CORSMiddleware(allow_origins=["*"]) — restrict in prod

.env.example:
  MONGODB_URI=mongodb+srv://...
  DATABASE_NAME=georgian_tax_db       ← NEW: explicit database name (same Atlas cluster, separate DB)
  GEMINI_API_KEY=...
  API_KEY_SECRET=...                  ← for hashing API keys (copy Scoop pattern)
  EMBEDDING_MODEL=text-embedding-004  ← tracked on every embedded document for migration safety
  SIMILARITY_THRESHOLD=0.65
  MATSNE_REQUEST_DELAY=2.0
  SEARCH_LIMIT=5
  RATE_LIMIT=30/minute
```

### MongoDB Database: `georgian_tax_db`

> [!IMPORTANT]
> All collections live in a **new, independent database** on the same Atlas cluster.
> Existing `scoop_db` and `scoop_ai` databases are **NOT modified**.

| Collection | Purpose | Vector Index | Phase |
|---|---|---|---|
| `tax_articles` | Parsed tax code articles (300+) | ✅ `tax_articles_vector_index` (768d cosine) | 1 |
| `definitions` | Legal term definitions (articles 1-8) | ✅ `definitions_vector_index` (768d cosine) | 1 |
| `metadata` | Version tracking, scrape status | — | 1 |
| `conversations` | Session history (adapted from Scoop) | — | 1 |
| `api_keys` | API key enrollment (copied from Scoop) | — | 1 |
| `sub_legislative` | Sub-legislative acts | TBD | 2 |

---

## Smart Retrieval Strategy (Core Intelligence)

> [!IMPORTANT]
> This is what separates a **valuable assistant** from a **dumb GPT wrapper**.

### Layer 1: Hierarchical Context ("მშობელი-შვილი")

**Problem:** მუხლს "განაკვეთი" ეძახის 3 სხვადასხვა თავი. Naive search აურევს.

**Solution:** Embedding chunks include parent hierarchy:
```python
# BAD: "განაკვეთი არის 18%"
# GOOD: "კარი IX. დღგ → თავი I → მუხლი 169. განაკვეთი არის 18%"
embedding_text = f"{kari} → {tavi} → მუხლი {number}. {title}\n{body}"
```

The `TaxArticle` model stores: `kari`, `tavi`, `article_number`, `title`, `body` — and the embedding is built from **all of them concatenated**.

### Layer 2: Cross-References ("ჯვარედინი ბმულები")

**Problem:** მუხლი 98: "გამონაკლისია მე-100 მუხლით გათვალისწინებული შემთხვევები."

**Solution:** Scraper extracts `related_articles` via regex:
```python
import re
# 🔴 FIX (C1): non-capturing group, not character class + all Georgian cases
REF_PATTERN = re.compile(r'მუხლ(?:ი|ის|ით|ში|ზე|ისა)\s*(\d+)')
ORD_REF_PATTERN = re.compile(r'მე-?(\d+)\s*მუხლ')  # ordinal: მე-100 მუხლი

def extract_cross_refs(body: str) -> List[int]:
    refs = set(REF_PATTERN.findall(body) + ORD_REF_PATTERN.findall(body))
    return [int(r) for r in refs]
```

Retrieval fetches **primary + related**:
```python
async def search_with_refs(query: str) -> List[TaxArticle]:
    primary = await vector_search(query, limit=5)
    ref_ids = set()
    for art in primary:
        ref_ids.update(art.related_articles)
    related = await find_by_numbers(list(ref_ids))
    return merge_and_rank(primary, related)
```

### Layer 3: Conditional Logic (Multi-Fact Retrieval)

**Problem:** "მცირე ბიზნესი ვარ და ბინას ვაქირავებ. 1%-ს ვიხდი?"

**Solution:** RAG prompt instructs model to check **both** conditions:
```
SYSTEM: When the user describes a multi-condition scenario,
you MUST check each condition against separate articles.
Never answer based on just one matching article.
```

Hybrid search catches this — query decomposes into 2 semantic searches:
1. "მცირე ბიზნესის განაკვეთი" → finds rate article
2. "მცირე ბიზნესის აკრძალული საქმიანობა" → finds exclusions

### Red Zone Guardrails (Hardcoded Refusal)

| Category | Example | Response |
|---|---|---|
| Tax optimization | "როგორ დავმალო გადასახადები?" | "მე ვარ საგადასახადო კოდექსის ინტერპრეტატორი. თავის არიდება კანონდარღვევაა." |
| Legal disputes | "პარტნიორი ფულს მპარავს" | "ეს სცდება საგადასახადო კოდექსის ფარგლებს. მიმართეთ იურისტს." |
| Calculations | "5000 ლარი შემოსავალი, რამდენია გადასახადი?" | "განაკვეთი 20%-ია (მუხლი 81). კალკულაციისთვის გამოიყენეთ rs.ge." |
| Medical/Criminal | Anything non-tax | "ვპასუხობ მხოლოდ საგადასახადო კოდექსთან დაკავშირებულ კითხვებს." |

Implemented as **pre-retrieval classifier** in `tax_agent.py`:
```python
GUARDRAIL_PATTERNS = [
    (r'დამალ|თავის არიდება|გვერდის ავლ', 'tax_evasion'),
    (r'კალკულაცი|გამოთვალ|რამდენ.*გადასახად', 'calculation'),
    (r'პარტნიორ.*მპარავს|სარჩელ|სისხლის', 'legal_dispute'),
]
```

### Layer 5: Terminological Grounding ("დამიწება") — Phase 1 ✅

**Problem:** "პირი" ≠ ადამიანი. "დასაბეგრი პირი" ≠ "ფიზიკური პირი". კოდექსს **თავის** ლექსიკონი აქვს.

**Solution:** Separate `definitions` collection from articles 1–8:
```python
# definitions collection
{
    "term": "დასაბეგრი პირი",
    "definition": "პირი, რომელიც ეკონომიკურ საქმიანობას ეწევა...",
    "article_ref": 157,
    "embedding": [...]  # 768d
}
```

**Query pre-processing (🟡 W4 fix: vector search instead of $text):**
```python
async def resolve_terms(query: str) -> str:
    """Inject legal definitions before RAG search.
    Uses $vectorSearch instead of $text — MongoDB has no Georgian stemming."""
    query_embedding = await embed_content(query)
    matched = await definitions_collection.aggregate([
        {"$vectorSearch": {
            "queryVector": query_embedding,
            "path": "embedding",
            "numCandidates": 20,
            "limit": 3,
            "index": "definitions_vector_index"
        }}
    ]).to_list(3)
    if matched:
        context = "\n".join(f"ტერმინი: {d['term']} = {d['definition']}" for d in matched)
        return f"{context}\n\nკითხვა: {query}"
    return query
```

### Layer 6: Lex Specialis — "სპეციალური ჯობნის ზოგადს" — Phase 1 ✅

**Problem:** "რამდენია საშემოსავლო?" → "20%" არასრული პასუხია. გამონაკლისებიც უნდა.

**Solution — Dual approach:**

**A. Metadata tagging** during scraping:
```python
# If article body contains exception markers, flag it
EXCEPTION_MARKERS = ["გარდა", "გამონაკლისი", "არ ვრცელდება", "სპეციალური"]
article.is_exception = any(m in article.body for m in EXCEPTION_MARKERS)
```

**B. Re-ranking** in search:
```python
def rerank_with_exceptions(results: List[TaxArticle]) -> List[TaxArticle]:
    """Attach exception articles RIGHT AFTER their general rules."""
    general = [r for r in results if not r.is_exception]
    exceptions = [r for r in results if r.is_exception]
    # NOT interleave — attach exceptions after related generals
    ranked = []
    for g in general:
        ranked.append(g)
        for e in exceptions:
            if g.article_number in e.related_articles:
                ranked.append(e)
    return ranked
```

**C. System prompt:**
```
ეს არის სამართლის ოქროს წესი: სპეციალური ნორმა ჯობნის ზოგადს.
როცა კითხვას პასუხობ, ALWAYS mention:
1. ზოგადი წესი (General rule)
2. არსებული გამონაკლისები (Exceptions)
3. სპეციალური რეჟიმები (Special regimes)
```

### Layer 7: Temporal Awareness ("დროითი მანქანა") — Phase 1 LITE ⚡

**Problem:** "2022 წელს გავყიდე ბინა" — კანონი მას შემდეგ შეიცვალა.

**Phase 1 (LITE):** ჩვენ ვპარსავთ **მხოლოდ მოქმედ** კონსოლიდირებულ ვერსიას. სრული ისტორიული ძიება არ არის.

**რას ვაკეთებთ Phase 1-ში:**
```python
# Scraper extracts amendment dates from <a class="DocumentLink">
article.last_amended_date = extract_latest_amendment(siblings)  # "2024-03-15"

# Agent detects past-tense queries:
PAST_DATE_PATTERN = re.compile(r'(20\d{2})\s*წ')
if match := PAST_DATE_PATTERN.search(query):
    year = int(match.group(1))
    disclaimer = f"⚠️ ეს პასუხი ეფუძნება კოდექსის მოქმედ რედაქციას. "
                 f"{year} წელს მოქმედი რედაქცია შეიძლება განსხვავებული იყოს."
```

**Phase 2 (FULL):** Matsne publication API-ით ისტორიული ვერსიების `valid_from`/`valid_to`.

### Sub-Legislative Acts Reference — Phase 1 LITE ⚡

**Problem:** კოდექსი = ჩონჩხი. ფინანსთა მინისტრის ბრძანებები = ხორცი.

**Phase 1 (LITE):** Top-10 ყველაზე ხშირად მოხსენიებული ქვეკანონური აქტების **ცნობარი**:
```python
SUB_LEGISLATIVE_REFS = {
    "415": {"title": "მთავრობის დადგენილება №415", "topic": "მცირე ბიზნესის აკრძალული საქმიანობები"},
    "996": {"title": "ბრძანება №996", "topic": "საქონლის ჩამოწერის პროცედურა"},
    # ... 8 more
}
# When citing article that references these → add note
```

**Phase 2 (FULL):** ცალკე Matsne scraper ქვეკანონური აქტებისთვის → `sub_legislative` collection.

---

## Risk Matrix

| Scenario | Prob. | Impact | Mitigation |
|---|---|---|---|
| Matsne HTML changes | HIGH | CRITICAL | Validation layer, canary queries, backup |
| Gemini API rate limit | HIGH (free) | HIGH | Embedding cache, backoff, RPM monitor |
| Wrong article cited | MEDIUM | CRITICAL | Similarity ≥0.75, hybrid search, disclaimer |
| Cross-ref missing | MEDIUM | HIGH | Regex extraction + manual review of top 50 articles |
| Georgian tokenization | MEDIUM | MEDIUM | Conservative batching (80%), `countTokens` |
| Guardrail bypass | LOW | HIGH | Regex + LLM double-check, logging all refusals |

## ⛔ Architecture Exclusion List — DO NOT CARRY OVER

> [!CAUTION]
> These Scoop-specific modules must **NOT** be copied, imported, or referenced in the Tax Agent.
> The Tax Agent is an **independent Python service** — it shares infrastructure patterns but NOT domain logic.

| Module | Lines | Why Excluded |
|--------|-------|-------------|
| `catalog/loader.py` | 16,968B | Product catalog — zero tax relevance |
| `reasoning/query_analyzer.py` | 21,099B | Shopping NLU — tax uses embedding search |
| `reasoning/constraint_search.py` | 10,142B | Product filters — no constraints in tax |
| `reasoning/context_injector.py` | 17,695B | Shopping context — tax builds own RAG context |
| `tools/user_tools.py` | 27,602B | Function calling — tax is pure RAG, no tools |
| `profile/profile_extractor.py` | 23,565B | Shopping preferences — no user profiles |
| `profile/profile_processor.py` | 6,759B | Belief decay — not needed |
| `core/types.py` | 400 lines | Scoop-specific: `EngineConfig`, `FunctionCall`, `LoopState` |
| `core/model_router.py` | 270 lines | Multi-model routing — tax uses single model |
| `cache/context_cache.py` | 15,279B | Gemini context caching — Phase 2 optimization |
| `adapters/mongo_adapter.py` | 641 lines | Delegation layer — extract from `conversation_store.py` instead |
| `memory/user_store.py` | 1,325 lines | User profiles — entirely Scoop-specific |
| `memory/mongo_store.py` | 53 lines | Facade re-exporting both stores — unnecessary |

**If you find yourself needing anything from these files, STOP and re-evaluate.** The tax agent has its own domain-specific implementations for search, context, and types.

---

## Implementation Tasks (Bite-Sized TDD)

### Task 1: Project Scaffold
Copy patterns, install deps, verify health endpoint.
```
• Copy config.py (keep BaseModel + os.getenv pattern — 🟡 W1)
• Copy & ADAPT database.py (🔴 C2: replace _create_indexes(), remove Scoop constants)
• Copy app/auth/ directory from Scoop (API key validation middleware — domain-agnostic)
• Copy Dockerfile pattern (Python 3.11-slim)
• Create .gitignore, .env.example (incl. API_KEY_SECRET), pyproject.toml (ruff + black)
• EXTRACT ~150 lines from conversation_store.py (🟡 W3: not mongo_adapter.py)
• pip install fastapi motor google-genai beautifulsoup4 structlog pydantic slowapi
• Create main.py with /health endpoint + CORSMiddleware + auth middleware (🟢 S4)
• Verify: server starts, MongoDB connects, /health returns 200

DONE WHEN: `uvicorn main:app` starts, /health returns 200 with {"status":"ok"}, auth middleware active

Tests (5):
  1. Server starts on port 8000, /health returns {"status": "ok"} (200)
  2. /health with DB disconnected → {"status": "degraded", "db_connected": false} (200, not 500)
  3. Missing MONGODB_URI env var → server fails fast with clear error message
  4. CORS preflight OPTIONS request → 200 with correct Access-Control headers
  5. Request without X-API-Key header to protected endpoint → 401 Unauthorized
```

### Task 2: TaxArticle Model + Definitions + Atlas Index
```
• TaxArticle Pydantic model:
  - article_number: int (ge=1, le=500)
  - kari: str (კარი — Part)
  - tavi: str (თავი — Chapter)  
  - title: str
  - body: str (min_length=10)
  - related_articles: List[int]  ← cross-references
  - is_exception: bool           ← lex specialis flag
  - last_amended_date: Optional[date]  ← temporal awareness
  - embedding: List[float]       ← 768d
  - embedding_model: str = "text-embedding-004"  ← 🆕 tracks which model generated this vector
  - status: enum (active | repealed | amended)
  - embedding_text: str          ← "კარი → თავი → მუხლი N. Title\nBody"
• Definition model:
  - term: str
  - definition: str
  - article_ref: int
  - embedding: List[float]
  - embedding_model: str = "text-embedding-004"  ← 🆕 same tracking for migration safety
• MongoDB CRUD: insert, upsert (keyed on article_number), find_by_number, find_by_numbers(list)
• Database: `georgian_tax_db` (same Atlas cluster, independent from scoop_db/scoop_ai)
• Collections: tax_articles + definitions + metadata + conversations + api_keys
• metadata stores: {"key": "tax_code_version", "publication": N, "last_checked": ISODate, "scrape_status": "completed", "total_articles": int, "embedding_model": "text-embedding-004"}
• Atlas Vector Index (create via Atlas UI/API, NOT driver):
  - tax_articles: 768d cosine, filter on status, index name "tax_articles_vector_index"
  - definitions: 768d cosine, index name "definitions_vector_index" (🟡 W4)
• Embedding dimension assertion: assert len(emb) == 768 (🟢 S1)

DONE WHEN: Models pass validation, CRUD tests pass, Atlas indexes created

Tests (6):
  1. TaxArticle(article_number=0) → ValidationError (ge=1)
  2. TaxArticle(article_number=501) → ValidationError (le=500)
  3. TaxArticle(body="") → ValidationError (min_length=10)
  4. upsert(article_number=169, body="new") twice → only 1 document in DB
  5. find_by_numbers([81, 82, 999]) → returns 2 results (ignores non-existent)
  6. Definition model with empty term → ValidationError
```

### Task 3.0: Matsne Fetch Validation Spike 🔴 DO FIRST (~2 hours)
```
• Fetch raw HTML with aiohttp — check if #maindoc has content or is empty (JS-rendered)
• If JS-rendered → add playwright to requirements, use async headless Chrome
• If server-rendered → document exact DOM structure between oldStyleDocumentPart anchors
• Document body text extraction: what elements contain law text between headers
• This spike MUST complete before any Task 3 work begins
• Result determines: aiohttp+BS4 sufficient OR playwright needed

EXIT CRITERIA: Written doc (spike_result.md) confirming:
  1. Server-rendered OR JS-rendered (with proof: raw HTML snippet)
  2. Exact CSS selectors for: article headers, body text, amendment links
  3. Tool decision: aiohttp+BS4 OR playwright
```

### Task 3: Matsne Scraper ⚠️ CRITICAL PATH

> Split into 6 atomic sub-tasks. Each can be tested independently.

#### Task 3a: Version Detection + HTML Fetch
```
• detect_latest_version(): follow redirect, extract publication from final URL
  1. GET https://matsne.gov.ge/ka/document/view/1043717 (no ?publication=)
  2. Matsne REDIRECTS to ?publication=N (latest version)
  3. Parse N from final URL → use as current_publication
  4. Store N in metadata collection
• fetch_document_html(publication: int) → str: aiohttp with rate limiting
• 🟢 MATSNE_REQUEST_DELAY = 2.0s between requests (S2)

DONE WHEN: detect_latest_version() returns int, fetch returns >100KB HTML

Tests (4):
  1. detect_latest_version() → returns int > 200 (current publication)
  2. fetch_document_html(239) → returns string with len > 100_000
  3. fetch_document_html with network timeout → raises RetryableError (not crash)
  4. Rate limiter enforces ≥2s gap between consecutive fetches
```

#### Task 3b: Header Parser (State Machine)
```
• Selector: soup.select("a.oldStyleDocumentPart") — flat list
• State machine: track current_kari, current_tavi as we iterate
• Parse: მუხლი X → article header, ამოღებულია → repealed
• Output: List[{article_number, kari, tavi, title, status, anchor_element}]

DONE WHEN: Parses 300+ headers with correct hierarchy

Tests (5):
  1. Total parsed headers ≥ 300
  2. Each article has non-empty kari and tavi (hierarchy complete)
  3. No duplicate article_numbers in output
  4. "ამოღებულია" articles have status="repealed"
  5. Article 1 belongs to კარი I, თავი I (first hierarchy check)
```

#### Task 3c: Body Text Extraction
```
• 🔴 C3: after each მუხლი header anchor,
  collect ALL sibling nodes until next oldStyleDocumentPart
  → normalize whitespace, strip HTML, preserve paragraphs
  → handle inline <a class="DocumentLink"> (amendment refs)
• Validation: reject empty bodies, assert body.strip() != ""

DONE WHEN: Every non-repealed article has body text >10 chars

Tests (4):
  1. Article 169 (short law text) → body contains "18%" or known content
  2. No non-repealed article has empty body (assert all len > 10)
  3. DocumentLink <a> tags stripped from body text (no raw HTML)
  4. Body preserves paragraph breaks (\n between paragraphs, not collapsed)
```

#### Task 3d: Cross-Reference + Exception Extraction
```
• Extract cross-refs: regex r'მუხლ(?:ი|ის|ით|ში|ზე|ისა)\s*(\d+)' (🔴 C1 fixed)
  + ordinal pattern r'მე-?(\d+)\s*მუხლ'
• Flag exceptions: detect "გარდა", "გამონაკლისი" → is_exception=True
• Extract amendment dates from <a class="DocumentLink"> → last_amended_date

DONE WHEN: Cross-ref count >500 total, exceptions detected in 20+ articles

Tests (5):
  1. Article 82 body contains "მუხლი 81" → related_articles includes 81
  2. Ordinal pattern: "მე-7 მუხლი" → extracts article_number 7
  3. "გარდა" in body → is_exception = True
  4. Article with no cross-refs → related_articles = [] (not None)
  5. Regex doesn't match non-article numbers (e.g., "2023 წელი" ≠ article 2023)
```

#### Task 3e: Definition Extraction
```
• Extract definitions from თავი I (articles 1-8) → definitions collection
• Parse term-definition pairs from article body structure
• Store with article_ref for traceability

DONE WHEN: 20+ definitions extracted from articles 1-8

Tests (3):
  1. Term "დასაბეგრი პირი" exists in definitions collection
  2. Each definition has article_ref pointing to valid article (1-8)
  3. No duplicate terms in definitions collection
```

#### Task 3f: Assembly + Validation
```
• Build embedding_text: "კარი → თავი → მუხლი N. Title\nBody"
• Assemble TaxArticle objects from 3b+3c+3d outputs
• 📊 Log article length distribution:
  - Buckets: <1K chars, 1K-5K, 5K-8K, >8K chars
• Partial failure handling: if 3c fails for article N, log warning + skip
  (don't fail entire pipeline for one broken article)
• Final validation: 100+ articles with hierarchy + cross-refs + exception flags + non-empty bodies

DONE WHEN: 300+ TaxArticle objects pass Pydantic validation, <5% skipped

Tests (3):
  1. Assembly output count ≥ 300 (enough articles)
  2. Skipped articles < 5% of total (partial failure tolerance)
  3. Every assembled article has non-empty embedding_text starting with "კარი"
```

### Task 4: Embedding Pipeline
```
• Keep existing embed_content() from gemini_adapter.py (🟡 W2 — already at line 587)
• Add embedBatch(): up to 250 texts, ≤20K tokens per request
• buildEmbeddingText(): hierarchy prefix + article text concatenation
  Format: "კარი IX. დღგ → თავი I → მუხლი 169. განაკვეთი\n18%-ია..."
• 🔴 NEW — Token truncation safety:
  MAX_EMBEDDING_CHARS = 8000 (~2000 tokens for Georgian)
  if len(embedding_text) > MAX_EMBEDDING_CHARS:
      log warning + truncate (text-embedding-004 limit: 2048 tokens)
  Phase 2: split long articles into sub-article chunks instead of truncating
• 🟢 Dimension assertion: assert len(embedding) == 768 (S1)
• Test: correct dimensions, batch limits, hierarchy preserved in embedding
• Test: article > 8000 chars → truncated with warning, not error
```

### Task 5: Vector Search + Cross-Reference + Lex Specialis
```
• searchBySemantic(): $vectorSearch pipeline with EXPLICIT score projection:
  pipeline = [
    {"$vectorSearch": {
      "index": "tax_articles_vector_index",
      "path": "embedding",
      "queryVector": query_vector,
      "numCandidates": 100,           # configurable
      "limit": 5,                     # configurable via SEARCH_LIMIT
      "filter": {"status": "active"}  # 🔴 PRE-filter (not post-filter $match)
    }},
    {"$project": {                    # 🔴 CRITICAL: must project score
      "article_number": 1, "kari": 1, "tavi": 1, "title": 1, "body": 1,
      "related_articles": 1, "is_exception": 1,
      "score": {"$meta": "vectorSearchScore"}
    }}
  ]

• detectArticleNumber(): query-level regex (SEPARATE from cross-ref regex):
  patterns: "მუხლი 98", "მე-98 მუხლი", bare "98" (validated 1-400 range)

• hybridSearch():
  IF detectArticleNumber(query) → find_by_number() (skip vector search)
  ELSE → searchBySemantic()

• Threshold filtering (post-pipeline in Python):
  filtered = [r for r in results if r["score"] >= SIMILARITY_THRESHOLD]
  if not filtered → return "ვერ ვიპოვე რელევანტური მუხლი" message

• enrichWithCrossRefs():
  - Collect ref_ids from primary results
  - 🔴 EXCLUDE primary article IDs (already have them): ref_ids -= primary_ids
  - 🔴 CAP at 10 cross-refs maximum: ref_ids = list(ref_ids)[:10]
  - Filter by status=active

• rerank_with_exceptions():
  🔴 NOT interleave — use "general + attached exceptions" pattern:
  For each general rule → attach its related exceptions RIGHT AFTER it
  Preserve vectorSearchScore ordering within each group

• merge_and_rank(): deduplicate by article_number
• Cosine similarity ≥0.65 (🟡 W5: 0.75 too aggressive for Georgian morphology)
• Make threshold configurable via env var SIMILARITY_THRESHOLD
• Log similarity scores in structured format: {query, article_num, score}

Tests (8):
  1. "მუხლი 98" → regex path → direct lookup → article 98 + cross-refs (100)
  2. "საშემოსავლო განაკვეთი" → vector path → 20% general + 1% exception
  3. "ბინა რომ გავყიდო?" → semantic → article 168
  4. Irrelevant query → all scores < 0.65 → "ვერ ვიპოვე" message
  5. Shared cross-refs → no duplicate articles in result set
  6. Article referencing 20+ refs → capped at 10 cross-refs
  7. Repealed article → NOT returned even if semantically similar
  8. Verify structured log output includes {query, article_num, score}
```

### Task 6: Tax RAG Agent + Guardrails + Intelligence Layers

> Split into 5 atomic sub-tasks. Build bottom-up.

#### Task 6a: Pre-Retrieval Pipeline (3 classifiers)
```
• Red Zone classifier (regex): detect "რამდენი", "გამოთვალე", "რა გადასახადი"
  → sets disclaimer_needed = True
• Term resolver: lookup query terms in definitions collection
  → enrich context with resolved definitions
• Past-date detector: regex r'(20\d{2})\s*წელ'
  → sets temporal_warning = True, extracted_year = YYYY

DONE WHEN: 3 classifiers work independently, pass unit tests

Tests (6):
  1. "რამდენია საშემოსავლო?" → disclaimer_needed = True (Red Zone)
  2. "რა არის დღგ?" → disclaimer_needed = False (informational, no amount)
  3. "2022 წელს გავყიდე" → temporal_warning = True, extracted_year = 2022
  4. "ინდივიდუალური მეწარმე" → term resolver enriches with definition from DB
  5. Query without any known term → term resolver returns empty (no crash)
  6. "მომავალ წელს" (no year digits) → temporal_warning = False
```

#### Task 6b: Georgian System Prompt
```
• tax_system_prompt.py with rules:
  - "მუხლის ციტირება სავალდებულოა"
  - "სპეციალური ნორმა ჯობნის ზოგადს — ყოველთვის ახსენე გამონაკლისები"
  - "მრავალი პირობის შემთხვევაში შეამოწმე ყველა მუხლი"
  - "არასოდეს გაუწიო რჩევა თავიდან არიდებაზე"
  - "თუ ქვეკანონური აქტი რელევანტურია, მიუთითე ნომერი"
• Prompt assembly: system + disclaimer + definitions + temporal warning + context + question

DONE WHEN: Prompt template renders with all conditional sections

Tests (4):
  1. Prompt with disclaimer=True → output contains "⚠️" warning text
  2. Prompt with disclaimer=False → no warning block in output
  3. Prompt with definitions=["term1"] → output contains definition section
  4. Prompt with empty context (no articles found) → renders gracefully (no crash)
```

#### Task 6c: answerQuestion() Core Pipeline
```
• Pipeline: classify → resolve terms → embed → search → enrich refs → rerank → prompt → LLM
• Uses Gemini generate_content with system_instruction
• Returns: {answer: str, sources: List[int], disclaimer: bool, temporal_warning: bool}

DONE WHEN: End-to-end query returns structured response with cited articles

Tests (5):
  1. "დღგ რამდენია?" → response.sources includes article 169
  2. Response always has {answer, sources, disclaimer, temporal_warning} keys
  3. Empty search results (სკორ < 0.65) → answer contains "ვერ ვიპოვე" (not empty string)
  4. LLM API timeout (mocked) → returns {error: "LLM_ERROR"} (not 500)
  5. Malformed LLM response (no article citation) → source list empty, answer still returned
```

#### Task 6d: Conversation History + Sub-Legislative Refs
```
• Inject last N turns for context chain (multi-turn awareness)
• Sub-legislative refs: inject from hardcoded top-10 when relevant
• Partial failure handling: if LLM call fails, return error response (not 500)

DONE WHEN: Q1="დღგ?" Q2="გამონაკლისი?" → second answer knows context is VAT

Tests (4):
  1. Single turn: Q="დღგ?" → answer about VAT rate
  2. Multi-turn: Q1="დღგ?" Q2="გამონაკლისი?" → Q2 answer is about VAT exceptions (not income tax)
  3. LLM call fails (mocked) → returns {error: "LLM_ERROR", code: "LLM_ERROR"} (not raw 500)
  4. History with 20+ turns → only last N injected (no context overflow)
```

#### Task 6e: Integration Tests (8 scenarios)
```
• Tests:
  1. "დღგ-ს განაკვეთი?" → "18%" + მუხლი 169
  2. "რა არის განაკვეთი?" → disambiguates by chapter (hierarchy)
  3. "მოგების გამონაკლისი?" → cites 98 + 100 (cross-ref)
  4. "როგორ დავმალო?" → refusal (guardrail)
  5. Q1="დღგ?" Q2="გამონაკლისი?" → context chain
  6. "რამდენია საშემოსავლო?" → 20% + 1% exception (lex specialis)
  7. "ფიზიკურ პირს შეუძლია დღგ?" → resolves "დასაბეგრი პირი" (terminology)
  8. "2022 წელს გავყიდე" → disclaimer (temporal)
• 🔴 Embedding Quality Validation (post-seed):
  VALIDATION_QUERIES = [
    ("ბინა რომ გავყიდო რა გადასახადია?", [168]),
    ("დღგ-ს განაკვეთი რამდენია?", [169]),
    ("რამდენია საშემოსავლო?", [180]),
    ("აქციზის გადასახადი ლუდზე", [188]),
    ("პირგასამტეხლო დაგვიანებისთვის", [272]),
  ]
  → All 5 must return correct article in top-3

DONE WHEN: All 8 tests pass + 5/5 validation queries return correct article in top-3
```

### Task 7: API Routes + SSE Streaming + Sessions + Auth

> [!IMPORTANT]
> All 3 features (SSE, sessions, auth) **already exist in Scoop backend** — we COPY & ADAPT.
> Total adaptation: ~3.5 hours. Frontend reuses `useSSEStream`, `apiClient`, `useSessionStore` as-is.

#### 7a: Core Endpoints (G3, G8, G9)

**POST /api/ask** — Synchronous query (for simple clients)
```json
// Request
{"question": "string (1-500 chars)", "conversation_id": "string? (optional)"}

// Success Response (200)
{
  "answer": "string",
  "sources": [{"article_number": 169, "title": "...", "score": 0.84}],
  "disclaimer": true,
  "temporal_warning": false
}

// Error Response (4xx/5xx)
{"error": "string", "code": "INVALID_INPUT|RATE_LIMITED|LLM_ERROR|DB_ERROR"}
```

**GET /api/articles/{number}** — Direct article lookup
```json
// Response (200)
{"article_number": 169, "kari": "...", "tavi": "...", "title": "...", "body": "..."}

// Response (404)
{"error": "Article not found", "code": "NOT_FOUND"}
```

**GET /api/health** — Health check
```json
{"status": "ok", "db_connected": true, "articles_count": 312, "last_sync": "2026-02-16T..."}
```

#### 7b: SSE Streaming (COPY from Scoop `main.py:1553`)

**POST /api/ask/stream** — Streaming query (for frontend)
```
// Same request body as POST /api/ask
// Response: SSE stream with adapted event types:

event: thinking\ndata: {"step": "Searching tax articles..."}\n\n
event: sources\ndata: [{"article_number": 169, "title": "...", "score": 0.84}]\n\n
event: text\ndata: {"content": "partial answer chunk..."}\n\n
event: disclaimer\ndata: {"show": true, "temporal_warning": false}\n\n
event: done\ndata: {"conversation_id": "uuid"}\n\n
event: error\ndata: {"error": "...", "code": "LLM_ERROR"}\n\n
```

**Adaptation from Scoop:** Copy `StreamingResponse` + event generator. Change event types:
- `products` → `sources` (tax article citations)
- `tip` → `disclaimer` (legal disclaimer + temporal warning)
- Keep: `text`, `thinking`, `done`, `error`
- Drop: `quick_replies`, `truncation_warning`

#### 7c: Session Endpoints (COPY from Scoop `main.py:1559-1577`)

> **MongoDB collection:** `conversations` in `georgian_tax_db` (NOT scoop_db)
> Adapted from Scoop's `conversation_store.py`. Schema:
> `{conversation_id: str, user_id: str, title: str, turns: [{role, content, timestamp}], created_at: ISODate, updated_at: ISODate}`

**GET /api/sessions** — List user conversations
```json
[{"conversation_id": "uuid", "title": "დღგ-ს შესახებ", "created_at": "...", "updated_at": "..."}]
```

**GET /api/session/{id}/history** — Load conversation history
```json
{"conversation_id": "uuid", "turns": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

**POST /api/session/clear** — Clear conversation data
```json
// Response (200)
{"cleared": true}
```

**Source:** Wrappers around Task 6d's extracted conversation CRUD (from `conversation_store.py`).

#### 7d: Auth Middleware (COPY from Scoop `app/auth/`)

> **MongoDB collection:** `api_keys` in `georgian_tax_db` (NOT scoop_db)
> Schema: `{key_hash: str, created_at: ISODate, last_used: ISODate, is_active: bool}`

- API key enrollment: `POST /api/auth/enroll` → generates + returns API key
- Validation: `X-API-Key` header check on all protected endpoints (/ask, /sessions)
- `/health` and `/api/auth/enroll` remain public (no key required)
- Rate limiting: 30 req/min via slowapi (on top of auth)

```
• Implementation:
  - POST /api/ask → tax_agent.answerQuestion() — validate input len 1-500
  - POST /api/ask/stream → same pipeline, wrapped in StreamingResponse (COPY from Scoop)
  - GET /api/articles/{number} → find_by_number() — validate 1-500 range
  - GET /api/health → DB status + articles count + last sync date
  - GET /api/sessions → list conversations for user (from Task 6d CRUD)
  - GET /api/session/{id}/history → load conversation turns (from Task 6d CRUD)
  - POST /api/session/clear → clear conversation (from Task 6d CRUD)
  - POST /api/auth/enroll → generate API key (COPY from Scoop app/auth/)
  - Auth: X-API-Key middleware on /ask, /sessions (COPY from Scoop — ~30 min)
  - Rate limiting: 30 req/min via slowapi
  - CORS: CORSMiddleware already in main.py (from Task 1)
  - Error handling: all exceptions → structured error response (never raw 500)

DONE WHEN: All 8 endpoints return correct JSON, SSE stream works end-to-end, auth blocks unauthorized, rate limiter triggers at 31st request

Tests (15):
  Core:
  1. POST /api/ask with valid question → 200 + structured response
  2. POST /api/ask with empty question → 422 + {error, code: "INVALID_INPUT"}
  3. POST /api/ask with question >500 chars → 422 + {error, code: "INVALID_INPUT"}
  4. GET /api/articles/169 → 200 + article JSON with body
  5. GET /api/articles/9999 → 404 + {error: "Article not found", code: "NOT_FOUND"}
  6. GET /api/health → 200 + {status, db_connected, articles_count, last_sync}
  7. 31st request within 1 minute → 429 + {error, code: "RATE_LIMITED"}
  SSE:
  8. POST /api/ask/stream → SSE stream with event: text chunks
  9. POST /api/ask/stream → stream includes event: sources before text
  10. POST /api/ask/stream → stream ends with event: done
  11. POST /api/ask/stream with bad input → event: error emitted
  Sessions:
  12. GET /api/sessions → 200 + list of conversations
  13. GET /api/session/{id}/history → 200 + conversation turns
  14. POST /api/session/clear → 200 + {cleared: true}
  Auth:
  15. Request without X-API-Key to /api/ask → 401 Unauthorized
```

### Task 8: Seed + Sync Scripts
```
• seed_database.py: scrape all → embed all → bulk insert
  - Uses detect_latest_version() — NOT hardcoded publication number
  - Stores detected version in metadata collection after successful seed
  - Idempotency: uses upsert (keyed on article_number) — safe to re-run
  - Atomic operation: if embedding fails mid-batch, already-inserted articles remain
    (no need to re-scrape, just re-embed failed batch)
• sync_matsne.py: periodic version check → re-scrape if new version found
  - check_for_new_version(): GET base URL → follow redirect → compare publication N
  - If N > stored_version → trigger full re-scrape + re-embed (upsert = safe)
  - Log: "🆕 New Tax Code version detected: {N} (stored: {stored_N})"
  - Run: daily cron OR on server startup
• Canary test after seed: query "მუხლი 160" returns result
• Run embedding quality validation (from Task 6e) after seed

DONE WHEN: seed_database.py runs end-to-end, canary passes, re-run is idempotent

Tests (5):
  1. seed_database.py full run → inserts 300+ articles in tax_articles collection
  2. Re-run seed_database.py → same article count (upsert, no duplicates)
  3. Canary: after seed, query "მუხლი 160" → returns 1 result
  4. metadata collection has {key: "tax_code_version", publication: N>200, scrape_status: "completed", embedding_model: "text-embedding-004"}
  5. sync_matsne.py with same version → logs "no update needed" (no re-scrape)
```

---

## Execution Order

> [!IMPORTANT]
> **Sequential:** Task 3.0 (spike) → 1 → 2 → 3a → 3b → 3c → 3d → 3e → 3f → 4 → 5 → 6a → 6b → 6c → 6d → 8 (seed) → 6e (needs seeded data) → 7
> The validation spike determines scraper approach. The scraper (Task 3) determines data format for everything downstream.

---

## Rollback Strategy (G4b)

| Failure Point | Rollback Action | Data Loss? |
|---|---|---|
| Task 3 spike fails (JS-rendered) | Add playwright to requirements, re-plan 3a | None |
| Scraping fails mid-run | Already-inserted articles remain (upsert). Fix + re-run | None |
| Embedding batch fails | Re-embed only failed batch (articles without embeddings) | None |
| Atlas index creation fails | Retry via Atlas UI. No code change needed | None |
| Seed produces bad data | Drop `tax_articles` collection + re-seed (upsert is idempotent) | Rebuild ~15min |
| LLM returns garbage | Adjust system prompt in `tax_system_prompt.py` (isolated file) | None |
| Threshold too aggressive | Change `SIMILARITY_THRESHOLD` env var, no redeploy | None |

---

## Phase 2 Roadmap (Post-MVP)

| Feature | Description | Effort |
|---|---|---|
| **Full Temporal Search** | 239 historical versions via `publication=N` — see details below | **XL** |
| Sub-Legislative Scraping | ფინანსთა მინისტრის ბრძანებები → `sub_legislative` collection | L |
| User Profiles | "ინდ. მეწარმე ხარ თუ შპს?" → personalized answers | M |
| Streaming (SSE) | ✅ **Moved to Phase 1** — copied from Scoop backend | — |
| Calculator Integration | Structured calc for simple tax scenarios | L |

### Phase 2 Detail: Full Temporal Search (239 Versions)

> [!IMPORTANT]
> **Validated:** Matsne exposes all 239 historical versions via URL parameter `?publication=N`.
> Same HTML structure (`a.oldStyleDocumentPart`) — our BS4 parser works on all versions unchanged.

**URL pattern:**
```
https://matsne.gov.ge/ka/document/view/1043717?publication={1..239}
```

| publication | Date Range | Content |
|---|---|---|
| `1` | 07/12/2010 | ორიგინალი |
| `~200` | ~2022 | შუალედური |
| `239` | მოქმედი | ბოლო კონსოლიდაცია |

**Implementation:**
```python
# 1. Scrape all 239 versions (one-time seed, ~4hrs with rate limiting)
for pub in range(1, 240):
    articles = scrape(f"...?publication={pub}")
    for art in articles:
        art.version = pub
        art.valid_from = extract_date(pub)      # from page header
        art.valid_to = extract_date(pub + 1)    # next version's date

# 2. New collection: tax_articles_history (separate from active)
# 3. Query: "2022 წელს გავყიდე ბინა" → find version where valid_from ≤ 2022 ≤ valid_to
# 4. Compare: show diff between then and now
```

**Storage estimate:** ~239 × 300 articles × ~2KB = **~140MB** in MongoDB — manageable.
