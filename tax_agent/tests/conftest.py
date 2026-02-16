"""
Test Configuration — Tax Agent
===============================

Shared fixtures for async testing with httpx + FastAPI TestClient.
Includes mock fixtures for Gemini LLM and DefinitionStore (Task 6).
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_genai_client():
    """Mock Google GenAI client for LLM generation tests.

    Patches get_genai_client in rag_pipeline module.
    Returns a mock client whose generate_content returns a canned response.
    """
    with patch("app.services.rag_pipeline.get_genai_client") as mock_getter:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "ტესტ პასუხი. მუხლი 169 მიხედვით, დღგ-ს განაკვეთი შეადგენს 18%-ს."
        mock_client.models.generate_content.return_value = mock_response
        mock_getter.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_hybrid_search():
    """Mock hybrid_search for RAG pipeline tests.

    Returns a list with one mock TaxArticle-like object.
    """
    with patch("app.services.rag_pipeline.hybrid_search") as mock_search:
        mock_article = MagicMock()
        mock_article.article_number = 169
        mock_article.title = "დღგ-ს განაკვეთი"
        mock_article._similarity_score = 0.85
        mock_article.model_dump.return_value = {
            "article_number": 169,
            "title": "დღგ-ს განაკვეთი",
            "body": "დღგ-ს განაკვეთი არის 18 პროცენტი.",
            "kari": "XII",
            "tavi": "1",
        }

        async def async_search(*args, **kwargs):
            return [mock_article]

        mock_search.side_effect = async_search
        yield mock_search
