"""
Health Endpoint Tests — Tax Agent
==================================

Verify /health endpoint returns correct status.
"""
import pytest


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
