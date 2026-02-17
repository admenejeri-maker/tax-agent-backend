# Project Brief — Georgian Tax AI Agent

## Vision
AI-powered assistant that interprets the Georgian Tax Code using RAG (Retrieval-Augmented Generation) with legal-grade accuracy.

## Core Goals
1. Parse and index the full Georgian Tax Code from Matsne.gov.ge
2. Provide accurate, article-cited answers to tax questions in Georgian
3. Deploy as an independent FastAPI service with Scoop frontend integration

## Architecture
- **Backend**: Python 3.11 + FastAPI + Motor (async MongoDB) + Google Gemini
- **Frontend**: Next.js (Scoop frontend with Tax Agent compat layer)
- **Database**: MongoDB Atlas (`georgian_tax_db`)
- **Search**: Atlas Vector Search (768d cosine, `gemini-embedding-001`)

## Repositories (Canonical)

| Component | Repository | Local Directory |
|-----------|-----------|-----------------|
| **Backend** | [tax-agent-backend](https://github.com/admenejeri-maker/tax-agent-backend) | `/Users/maqashable/Desktop/scoop-sagadasaxado/tax_agent` |
| **Frontend** | [tax-agent-frontend](https://github.com/admenejeri-maker/tax-agent-frontend) | `/Users/maqashable/Desktop/scoop/frontend` |

## Local Development Ports (Canonical)

| Service | Port |
|---------|------|
| **Tax Agent Backend** | `:8000` |
| **Frontend** | `:3010` |

> ⚠️ Scoop backend (`:8080`) is NOT used in this project.

## Key Config Files
- `tax_agent/.env` — Backend secrets + PORT=8000 + ALLOWED_ORIGINS=http://localhost:3010
- `frontend/.env.local` — NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
