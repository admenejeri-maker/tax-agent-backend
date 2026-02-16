"""
Test Configuration — Tax Agent
===============================

Shared fixtures for async testing with httpx + FastAPI TestClient.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
