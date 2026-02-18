# Georgian Tax AI Agent — Backend Architecture

## Overview

A RAG (Retrieval-Augmented Generation) backend for Georgian tax law, built on **FastAPI** + **MongoDB Atlas** + **Google Gemini**. It ingests the Georgian Tax Code from Matsne.gov.ge, embeds articles as 3072-dim vectors, and answers user questions with cited, domain-routed responses streamed via SSE.

## Tech Stack

| Layer | Technology | Version |
|-------|-----------|---------|
| Framework | FastAPI | 0.115 |
| Server | Uvicorn | 0.34 |
| Database | MongoDB Atlas (Motor async driver) | Motor 3.7 |
| LLM | Google Gemini (google-genai SDK) | 1.14 |
| Embeddings | `gemini-embedding-001` | 3072-dim |
| Validation | Pydantic v2 | 2.10 |
| Logging | Structlog (JSON in prod, Console in dev) | 24.4 |
| Rate Limiting | SlowAPI | 0.1.9 |
| Scraper | aiohttp + BeautifulSoup4 | — |

## Project Structure

```
tax_agent/
├── main.py                     # FastAPI app, lifespan, CORS, routes
├── config.py                   # Settings (env vars via pydantic)
├── app/
│   ├── database.py             # Singleton DatabaseManager (Motor)
│   ├── api/
│   │   ├── api_router.py       # /api endpoints (ask, stream, articles, sessions)
│   │   └── frontend_compat.py  # /api/v1/* legacy compat layer for Scoop frontend
│   ├── auth/
│   │   ├── dependencies.py     # verify_api_key FastAPI dependency
│   │   ├── api_key_store.py    # HMAC key hashing + MongoDB CRUD
│   │   ├── key_generator.py    # Key generation utility
│   │   └── router.py           # /auth endpoints (enroll, validate)
│   ├── models/
│   │   ├── api_models.py       # Pydantic request/response schemas
│   │   ├── rag_response.py     # RAGResponse + SourceMetadata dataclasses
│   │   ├── tax_article.py      # TaxArticle Pydantic model + TaxArticleStore
│   │   └── definition.py       # Definition Pydantic model + DefinitionStore
│   ├── services/
│   │   ├── rag_pipeline.py     # Core orchestrator — answer_question()
│   │   ├── vector_search.py    # Hybrid search (semantic + keyword + direct)
│   │   ├── embedding_service.py# Embed articles/definitions → 3072-dim vectors
│   │   ├── router.py           # Tiered query router (compound → keyword → semantic → default)
│   │   ├── classifiers.py      # Pre-retrieval: red-zone, term resolver, past-date
│   │   ├── critic.py           # Post-generation QA reviewer (confidence-gated)
│   │   ├── query_rewriter.py   # Query expansion / rewriting
│   │   ├── tax_system_prompt.py# Dynamic system prompt builder
│   │   ├── logic_loader.py     # Load JSON logic rules from data/logic/
│   │   ├── conversation_store.py# Session persistence (MongoDB)
│   │   └── matsne_scraper.py   # Matsne.gov.ge scraper (aiohttp + BS4)
│   └── utils/
│       └── sse_helpers.py      # SSE event formatting helpers
├── data/
│   └── logic/                  # JSON logic rules (loaded at runtime)
├── tests/                      # Pytest test suite (343+ tests)
└── requirements.txt
```

## RAG Pipeline Flow

```
User Query
    │
    ▼
┌─────────────────────────────────┐
│  1. PRE-RETRIEVAL CLASSIFIERS   │
│  ├── Red Zone Detector          │  → needs_disclaimer flag
│  ├── Term Resolver              │  → matched definitions from DB
│  └── Past-Date Detector         │  → temporal_warning + year
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  2. QUERY ROUTING               │
│  Tiered routing (0ms):          │
│  ├── Tier 0: Compound rules     │  → multi-keyword intent patterns
│  ├── Tier 1: Keyword scan       │  → Georgian tax term matching
│  ├── Tier 2: Semantic (stub)    │  → future: cosine similarity
│  └── Tier 3: Default → GENERAL  │
│  Returns: RouteResult{domain,   │
│           confidence, method}   │
└─────────────────────────────────┘
    │  domain (VAT, INDIVIDUAL_INCOME, CORPORATE_TAX, etc.)
    ▼
┌─────────────────────────────────┐
│  3. HYBRID SEARCH               │
│  Three-way merge + RRF dedup:   │
│  ├── Direct article lookup      │  → article_number match (score=1.0)
│  ├── Semantic ($vectorSearch)   │  → 3072-dim cosine similarity
│  └── Keyword ($search)          │  → Atlas text index
│  + Cross-reference enrichment   │
│  + Lex specialis re-ranking     │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  4. SYSTEM PROMPT BUILDING      │
│  Dynamic prompt with:           │
│  ├── Domain-specific rules      │
│  ├── Retrieved article context  │
│  ├── Matched definitions        │
│  ├── Logic rules (JSON)         │
│  ├── Active disambiguation      │
│  └── Disclaimers (red-zone,     │
│      temporal, confidence)      │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  5. LLM GENERATION              │
│  Gemini generate_content()      │
│  with conversation history      │
│  (last 5 turns)                 │
└─────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────┐
│  6. CRITIC (QA REVIEWER)        │
│  Confidence-gated:              │
│  ├── Skip if confidence > 0.8   │
│  ├── Skip if feature flag off   │
│  └── Gemini reviews citations   │
│  Fail-open: approves on error   │
└─────────────────────────────────┘
    │
    ▼
  RAGResponse {answer, sources, confidence, disclaimers}
```

## Database Architecture

**Engine:** MongoDB Atlas with Motor async driver  
**Pattern:** Singleton `DatabaseManager` with connection pooling (min=1, max=10)

### Collections

| Collection | Purpose | Key Indexes |
|-----------|---------|-------------|
| `tax_articles` | Georgian Tax Code articles + embeddings | `article_number` (unique), `domain`, `embedding_model`, text index on titles |
| `definitions` | Legal term definitions + embeddings | `term_ka` (unique), `embedding_model` |
| `conversations` | Chat sessions | `(user_id, updated_at)`, TTL on `expires_at` |
| `api_keys` | HMAC-hashed API keys | `key_hash` (unique), `user_id`, TTL on `expires_at` |
| `metadata` | Scrape status, sync state | `type` (unique) |

### Vector Search

- **Index:** Atlas Vector Search on `tax_articles.embedding` (3072 dimensions, cosine similarity)
- **Pre-filter:** Optional domain filter for contextual isolation
- **Fallback:** If domain-filtered search returns too few results, retries without filter

## Authentication

**Mechanism:** HMAC API key authentication  
**Flow:**
1. Frontend calls `POST /auth/enroll` with `user_id` → receives raw API key
2. Key is HMAC-SHA256 hashed and stored in `api_keys` collection
3. All `/api/*` endpoints require `X-API-Key` header
4. `verify_api_key` FastAPI dependency validates hash against stored keys

## API Routes

### Auth (`/auth`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/enroll` | Generate API key for user |
| POST | `/auth/validate` | Validate existing key |

### API (`/api`)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ask` | Synchronous RAG query |
| POST | `/api/ask/stream` | SSE streaming RAG query |
| GET | `/api/articles/{number}` | Direct article lookup |
| GET | `/api/articles/{number}/text` | Article source text |
| GET | `/api/sessions` | List user's sessions |
| GET | `/api/session/{id}/history` | Load conversation history |
| POST | `/api/session/clear` | Delete conversation data |

### Frontend Compat (`/api/v1/*`)
Legacy compatibility layer mapping Scoop frontend routes to tax agent endpoints. Handles SSE event format translation.

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | DB status + version |

## SSE Streaming Protocol

Streaming responses use Server-Sent Events with typed event payloads:

| Event Type | Payload | Description |
|-----------|---------|-------------|
| `text` | `{content: string}` | Incremental answer text |
| `sources` | `[{title, article_number, score, url, text}]` | Citation sources |
| `thinking` | `{content: string}` | Model reasoning (debug) |
| `quick_replies` | `[{label, prompt}]` | Suggested follow-ups |
| `done` | `{session_id}` | Stream complete signal |
| `error` | `{message}` | Error message |

## Deployment

- **Runtime:** Cloud Run (source deploy)
- **Port:** 8000 (configurable via `PORT` env var)
- **Health Check:** `GET /health`
- **Environment Variables:** MongoDB URI, Gemini API key, CORS origins, feature flags
