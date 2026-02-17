---
description: Start local dev servers - Backend :8000, Frontend :3010
---

# Local Development Servers

Start the Tax Agent backend (FastAPI/Uvicorn) on port **8000** and the Scoop frontend (Next.js) on port **3010**.

## Port Assignment (Canonical)

| Service | Port | Directory |
|---------|------|-----------|
| **Tax Agent Backend** | `:8000` | `/Users/maqashable/Desktop/scoop-sagadasaxado/tax_agent` |
| **Scoop Frontend** | `:3010` | `/Users/maqashable/Desktop/scoop/frontend` |

> ⚠️ Scoop backend (`:8080`) is NOT used in this project. Frontend connects directly to Tax Agent on `:8000`.

## Prerequisites

- Tax Agent virtualenv exists at `tax_agent/.venv/`
- Frontend dependencies installed (`node_modules/`)
- `tax_agent/.env` configured (MONGODB_URI, GEMINI_API_KEY, PORT=8000, ALLOWED_ORIGINS=http://localhost:3010)
- `frontend/.env.local` has `NEXT_PUBLIC_BACKEND_URL=http://localhost:8000`

---

## Step 1: Kill existing processes on ports 8000 and 3010

```bash
lsof -ti:8000,3010 2>/dev/null | xargs kill -9 2>/dev/null; echo "Ports cleared"
```

> This ensures no ghost processes block the ports.

---

## Step 2: Start Tax Agent Backend (port 8000)

```bash
/Users/maqashable/Desktop/scoop-sagadasaxado/tax_agent/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Working directory:** `/Users/maqashable/Desktop/scoop-sagadasaxado/tax_agent`

**Important notes:**
- Uses the Tax Agent venv directly (not Scoop backend venv)
- `--reload` is safe for local dev (watches `tax_agent/` directory)
- Must run as a **background command** (WaitMsBeforeAsync=5000) so it stays alive.

**Expected output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
database_connected             database=georgian_tax_db
indexes_created                collections=5
INFO:     Application startup complete.
```

---

## Step 3: Start Frontend (port 3010)

```bash
cd /Users/maqashable/Desktop/scoop/frontend && npx next dev -p 3010
```

**Important notes:**
- Use `npx next dev` instead of `npm run dev`. The `npm run dev` wrapper sometimes exits prematurely in managed terminal environments.
- Must run as a **background command** (WaitMsBeforeAsync=8000) so it stays alive.

**Expected output:**
```
▲ Next.js 16.1.1 (Turbopack)
- Local:         http://localhost:3010
- Environments: .env.local
✓ Ready in ~500ms
```

---

## Step 4: Verify both servers

// turbo
```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```

Expected: `{"status": "healthy", "service": "tax-agent", "database": "connected"}`

// turbo
```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:3010
```

Expected: `200`

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Backend exits with code 0 | `reload=True` kills child process | Use `uvicorn main:app` directly with `--reload` flag |
| Port already in use (Errno 48) | Ghost process on port | Run Step 1 to kill existing processes |
| Frontend `Failed to fetch` | Backend not reachable or CORS | Check `.env.local` URL matches backend port, check `ALLOWED_ORIGINS` in `tax_agent/.env` |
| `Connection refused` on 8000 | Backend crashed during startup | Check for missing env vars (MONGODB_URI, GEMINI_API_KEY) |
| MongoDB connection timeout | No MongoDB access | Check MONGODB_URI in `.env` or allow network access |
| CORS error in browser | ALLOWED_ORIGINS mismatch | Ensure `tax_agent/.env` has `ALLOWED_ORIGINS=http://localhost:3010` |

---

## Quick Reference (Copy-Paste)

```bash
# 1. Clear ports
lsof -ti:8000,3010 2>/dev/null | xargs kill -9 2>/dev/null

# 2. Backend (run in separate terminal)
cd /Users/maqashable/Desktop/scoop-sagadasaxado/tax_agent && \
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 3. Frontend (run in separate terminal)
cd /Users/maqashable/Desktop/scoop/frontend && npx next dev -p 3010
```
