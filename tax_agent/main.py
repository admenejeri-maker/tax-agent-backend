"""
Georgian Tax AI Agent — Main Application
=========================================

Lean FastAPI scaffold (~130 lines) with:
- MongoDB connection via lifespan
- Structlog structured logging
- SlowAPI rate limiting
- CORS middleware
- Auth router at /auth
- Health endpoint

Adapted from Scoop backend/main.py (1700+ lines → ~130 lines)
"""
import os
import logging
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import settings
from app.database import db_manager
from app.auth.router import router as auth_router
from app.api.api_router import router as api_router

# =============================================================================
# LOGGING
# =============================================================================

_log_level = logging.DEBUG if settings.debug else logging.INFO

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(_log_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# =============================================================================
# RATE LIMITING
# =============================================================================

limiter = Limiter(key_func=get_remote_address)


# =============================================================================
# LIFESPAN
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    logger.info("starting_tax_agent", version="0.1.0")

    # Connect to MongoDB
    if settings.mongodb_uri:
        await db_manager.connect(settings.mongodb_uri, settings.database_name)

    yield

    # Shutdown
    logger.info("shutting_down_tax_agent")
    await db_manager.disconnect()


# =============================================================================
# FASTAPI APP
# =============================================================================

app = FastAPI(
    title="Georgian Tax AI Agent",
    description="AI Assistant for Georgian Tax Code",
    version="0.1.0",
    lifespan=lifespan,
)

# Attach rate limiter
app.state.limiter = limiter

# CORS
cors_origins = settings.allowed_origins.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """Custom 429 handler for SlowAPI"""
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."},
    )


# =============================================================================
# ROUTES
# =============================================================================

# Auth endpoints at /auth
app.include_router(auth_router, prefix="/auth")

# API endpoints at /api
app.include_router(api_router, prefix="/api")

# Frontend compat endpoints (no prefix — routes have /api/v1/... built in)
from app.api.frontend_compat import compat_router
app.include_router(compat_router)


@app.get("/health")
async def health():
    """Health check endpoint reporting DB status"""
    db_ok = False
    if settings.mongodb_uri:
        db_ok = await db_manager.ping()

    return {
        "status": "healthy" if db_ok else "degraded",
        "service": "tax-agent",
        "version": "0.1.0",
        "database": "connected" if db_ok else "disconnected",
    }


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
