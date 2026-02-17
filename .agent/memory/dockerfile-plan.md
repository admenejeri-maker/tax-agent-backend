# 🐳 P1.5 Dockerfile Security — Opus Planning v3.0

> **Phase**: Move 2 — Strategic Planning  
> **Task ID**: P1.5  
> **Priority**: MEDIUM  
> **Size**: M (4 new files, 4 modified files)  
> **Risk**: MEDIUM  
> **Estimated Time**: ~30-40 minutes  
> **Confidence**: 95%

---

## 📊 Status Assessment

Sprint 1 has 3 tasks — P0.1 Auth (✅), P1.3 Logging (pending), P1.5 Dockerfile (this task).  
Completing P1.5 brings Sprint 1 to 2/3 done. Zero dependencies — pure quick win.

---

## 🔍 Phase 1: Deep Analysis — Current Vulnerabilities

### Audit Summary

| Dockerfile | Non-Root | .dockerignore | Healthcheck | Secret Leak Risk |
|---|---|---|---|---|
| `backend/Dockerfile` | ❌ ROOT | ❌ MISSING | ⚠️ OK (urllib) | 🔴 HIGH — `COPY . .` leaks `.env`, `.git/`, `venv/` |
| `frontend/Dockerfile` | ✅ nextjs | ❌ MISSING | N/A (standalone) | 🟢 LOW — selective COPY in prod |
| `antigravity-brain/Dockerfile` | ❌ ROOT | ❌ MISSING | 🔴 BROKEN — uses `curl` (not installed) | 🟢 LOW — selective COPY |
| `deploy/semgrep-mcp/Dockerfile` | ❌ ROOT | N/A | N/A | 🟢 LOW — single file COPY |
| `deploy/mongodb-mcp/Dockerfile` | ❌ ROOT | N/A | N/A | 🟢 LOW — npm global install |

### Critical Finding: Backend Secret Leakage

The `backend/Dockerfile` uses `COPY . .` without `.dockerignore`. The following sensitive files are copied into the production image:

```
.env                    (265B — API keys, DB credentials)
.git/                   (full repository history)
__pycache__/            (compiled Python bytecode)
venv/                   (full virtual environment)
backend.log             (49KB — runtime logs)
tests/                  (34 files — test code in production)
evals/                  (19 files — evaluation data)
*.md                    (12+ documentation files)
```

> [!CAUTION]
> Anyone with `docker pull` access can extract `.env` secrets with:
> `docker run --rm image cat /app/.env`

---

## 🌳 Phase 2: Tree of Thoughts — Approach Selection

### Approach A: Minimal Fix (backend only)
- Fix only `backend/Dockerfile` + add `.dockerignore`
- **Pro**: Fastest (15 min), addresses highest risk
- **Con**: Leaves other Dockerfiles vulnerable
- **Rejected**: Doesn't align with enterprise goal

### Approach B: Comprehensive Hardening ✅ SELECTED
- Harden ALL Dockerfiles + add `.dockerignore` per service
- **Pro**: Complete CIS Docker Benchmark compliance, addresses all vulns
- **Con**: More files (~8 total changes)
- **Why**: Enterprise remediation demands holistic security

### Approach C: Distroless Migration
- Switch to `gcr.io/distroless/python3` base images
- **Pro**: Maximum security (no shell, no package manager)
- **Con**: Makes debugging extremely difficult, overkill for current maturity
- **Rejected**: Over-engineering for current stage

---

## 🕵️ Phase 3: Pre-Mortem

> *"It's 1 week after deploying P1.5. Something broke. What happened?"*

| Scenario | Cause | Mitigation |
|---|---|---|
| App won't start | Non-root user can't write to `/app` | `chown` app directory before `USER` switch |
| Healthcheck fails | brain uses `curl` which isn't installed | Replace with `python -c "import urllib..."` |
| Build breaks | `.dockerignore` too aggressive | Explicitly list exclusions, test with `--no-cache` |
| Cloud Run deploy fails | Port or user mismatch | Keep ports identical (8080/8000), test locally first |
| Secrets still visible | ENV vars in Dockerfile metadata | Only use ENV for non-sensitive config, runtime inject secrets |

---

## 📦 Phase 4: Implementation Blueprint

### Selected Approach: B — Comprehensive Hardening

### Files to CREATE (4):

| # | File | Purpose |
|---|------|---------|
| 1 | `backend/.dockerignore` | Block .env, .git, venv, __pycache__, logs, tests |
| 2 | `frontend/.dockerignore` | Block node_modules, .next, .git, .env.local |
| 3 | `antigravity-brain/.dockerignore` | Block .git, __pycache__, .env |
| 4 | (Optional) Root `.dockerignore` | Root-level safety net |

### Files to MODIFY (4):

| # | File | Changes |
|---|------|---------|
| 5 | `backend/Dockerfile` | + non-root user, + LABEL metadata |
| 6 | `antigravity-brain/Dockerfile` | + non-root user, FIX healthcheck (curl → python urllib) |
| 7 | `deploy/semgrep-mcp/Dockerfile` | + non-root user |
| 8 | `deploy/mongodb-mcp/Dockerfile` | + non-root user |

### Files UNCHANGED:
- `frontend/Dockerfile` — Already hardened (non-root, selective COPY) ✅

---

### Step-by-Step Execution (Bite-Sized)

#### Step 1: Create `backend/.dockerignore` (~2 min)
```dockerignore
# Secrets & environment
.env
.env.*
!.env.example

# Version control
.git
.gitignore

# Python artifacts
__pycache__
*.pyc
*.pyo
venv/
.pytest_cache/

# Logs
*.log

# Tests & evaluation (not needed in prod)
tests/
evals/

# Documentation (not needed in prod)
*.md
docs/
scripts/

# IDE & OS
.vscode/
.idea/
.DS_Store
```

#### Step 2: Harden `backend/Dockerfile` (~5 min)
```dockerfile
# --- Changes ---
# 1. Add LABEL metadata
# 2. Add non-root user (appuser, uid 1001)
# 3. chown /app to appuser
# 4. Switch to USER appuser before CMD

# Production stage additions:
LABEL maintainer="scoop-team" \
      description="Scoop AI Backend" \
      version="1.0"

RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/false appuser

COPY --chown=appuser:appgroup . .

USER appuser
```

#### Step 3: Create `frontend/.dockerignore` (~2 min)
```dockerignore
node_modules
.next
.git
.env.local
.env*.local
*.md
.DS_Store
```

#### Step 4: Fix `antigravity-brain/Dockerfile` (~5 min)
```dockerfile
# --- Changes ---
# 1. Add non-root user
# 2. FIX: Replace curl healthcheck with python urllib
# 3. Add LABEL metadata

RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/false appuser

USER appuser

# HEALTHCHECK fix (curl not available in python:3.11-slim):
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
```

#### Step 5: Create `antigravity-brain/.dockerignore` (~2 min)
```dockerignore
.git
__pycache__
*.pyc
.env
*.log
.DS_Store
```

#### Step 6: Harden `deploy/semgrep-mcp/Dockerfile` (~3 min)
```dockerfile
# Add before CMD:
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --shell /bin/false appuser
USER appuser
```

#### Step 7: Harden `deploy/mongodb-mcp/Dockerfile` (~3 min)
```dockerfile
# Add before CMD (Alpine syntax):
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser
USER appuser
```

---

## ✅ Verification Plan

### Automated Tests
```bash
# 1. Build backend image
cd /Users/maqashable/Desktop/scoop/backend
docker build -t scoop-backend-test .

# 2. Verify no secrets in image
docker run --rm scoop-backend-test ls -la /app/.env  # Should FAIL (file not found)
docker run --rm scoop-backend-test ls -la /app/venv   # Should FAIL

# 3. Verify non-root user
docker run --rm scoop-backend-test whoami  # Should print "appuser"

# 4. Verify healthcheck
docker run -d --name hc-test scoop-backend-test
docker inspect --format='{{.State.Health.Status}}' hc-test

# 5. Build frontend image
cd /Users/maqashable/Desktop/scoop/frontend
docker build -t scoop-frontend-test .

# 6. Verify frontend non-root
docker run --rm scoop-frontend-test whoami  # Should print "nextjs"
```

### Security Audit Checklist
- [ ] No `.env` in any built image
- [ ] No `.git/` in any built image
- [ ] All containers run as non-root (uid 1001)
- [ ] All healthchecks use available tools (no missing `curl`)
- [ ] Ports unchanged (8080 backend/frontend, 8000 brain)
- [ ] Cloud Run compatibility maintained

---

## 🎯 Post-Completion Impact

```
Before:  ██████████░░░░░░░░░░░░░░░░ 10/26 (38%)
After:   ███████████░░░░░░░░░░░░░░░ 11/26 (42%)
Sprint 1: 2/3 complete (only P1.3 Logging remains)
```

**Next recommended task**: P1.1 Prompt Injection Blocking (HIGH risk, unblocked)

---

*Generated by Opus Planning v3.0 — "Think deeply now, code confidently later!"*
