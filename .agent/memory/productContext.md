# Product Context — Georgian Tax AI Agent

## Tech Stack
- **Backend**: Python 3.11, FastAPI, Uvicorn, Motor (async MongoDB), Google Gemini API
- **Frontend**: Next.js 16.1.1 (Turbopack), TypeScript, React
- **Database**: MongoDB Atlas (cluster: `scoop.xbbeory.mongodb.net`, database: `georgian_tax_db`)
- **Embedding**: `gemini-embedding-001` (768 dimensions, cosine similarity)
- **LLM**: `gemini-2.0-flash` (RAG generation)
- **Deployment**: Google Cloud Run (europe-west1)

## Repositories

| Component | Repository | Branch |
|-----------|-----------|--------|
| **Backend** | [`admenejeri-maker/tax-agent-backend`](https://github.com/admenejeri-maker/tax-agent-backend) | `main` |
| **Frontend** | [`admenejeri-maker/tax-agent-frontend`](https://github.com/admenejeri-maker/tax-agent-frontend) | `main` |

## Local Dev Ports

| Service | Port | Start Command |
|---------|------|---------------|
| Backend | `:8000` | `cd tax_agent && .venv/bin/python -m uvicorn main:app --port 8000 --reload` |
| Frontend | `:3010` | `cd frontend && npx next dev -p 3010` |

## Conventions
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, etc.)
- Linting: `ruff` (backend), ESLint (frontend)
- Formatting: `black` (backend), Prettier (frontend)
- Testing: `pytest` (backend), 166 tests passing as of Phase 1

## Architecture Pattern
- **Independent Python Service** — NOT a module of Scoop backend
- **RAG Pipeline**: Query → Classify → Embed → Vector Search → Cross-ref → Rerank → LLM → Response
- **Frontend Compat Layer**: `frontend_compat.py` translates Scoop frontend API contract to Tax Agent endpoints
- **7 Intelligence Layers**: Hierarchy, Cross-refs, Multi-fact, Guardrails, Terminology, Lex Specialis, Temporal

## MongoDB Collections (`georgian_tax_db`)
| Collection | Purpose |
|-----------|---------|
| `tax_articles` | Parsed tax code articles (300+) with 768d embeddings |
| `definitions` | Legal term definitions (articles 1-8) |
| `metadata` | Version tracking, scrape status |
| `conversations` | Session history |
| `api_keys` | API key enrollment |
