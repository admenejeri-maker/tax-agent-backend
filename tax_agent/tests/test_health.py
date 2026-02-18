"""
Health Endpoint Tests — Tax Agent
==================================

Verify /health endpoint returns correct status.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.mark.asyncio
async def test_health_endpoint_returns_200(client):
    """Health endpoint returns 200 with service info"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "tax-agent"
    assert data["version"] == "0.1.0"
    assert "status" in data
    assert "database" in data


@pytest.mark.asyncio
async def test_health_degraded_without_db(client):
    """Without MongoDB, health reports degraded"""
    response = await client.get("/health")
    data = response.json()
    # Without MONGODB_URI, db is disconnected
    assert data["database"] == "disconnected"
    assert data["status"] == "degraded"


@pytest.mark.asyncio
async def test_500_returns_json_not_plain_text():
    """Unhandled exceptions return JSON so CORS middleware can add headers.

    When DB is disconnected, session endpoints raise RuntimeError.
    The global_exception_handler in main.py should catch this and return
    a JSONResponse (not Starlette's default plain-text 500).

    Uses raise_app_exceptions=False so the test client receives the
    500 response instead of re-raising the server-side exception.
    """
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/sessions/test-user")
    assert response.status_code == 500
    assert response.headers.get("content-type", "").startswith("application/json")
    data = response.json()
    assert "detail" in data
