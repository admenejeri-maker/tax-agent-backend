"""Tests for CRITIC — Confidence-Gated QA Reviewer — Step 4."""
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from app.services import critic
from app.services.critic import critique_answer, CriticResult, _extract_json


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_refs():
    """Sample source references matching rag_pipeline output."""
    return [
        {"id": 1, "article_number": "168", "title": "დღგ-ს გადამხდელად რეგისტრაცია"},
        {"id": 2, "article_number": "169", "title": "დღგ-ს განაკვეთი"},
    ]


def _mock_genai_response(text: str):
    """Create a mock Gemini response with .text attribute."""
    mock = MagicMock()
    mock.text = text
    return mock


# ─── Tests ───────────────────────────────────────────────────────────────────


async def test_critic_disabled_returns_approved(monkeypatch, sample_refs):
    """Flag off → approved without API call."""
    # Default: CRITIC_ENABLED not set (False)
    from config import Settings
    monkeypatch.setattr(critic, "settings", Settings())

    result = await critique_answer("answer", sample_refs, confidence=0.3)
    assert result.approved is True
    assert result.feedback is None


async def test_critic_high_confidence_skips(monkeypatch, sample_refs):
    """Confidence above threshold → approved without API call."""
    monkeypatch.setenv("CRITIC_ENABLED", "true")
    from config import Settings
    monkeypatch.setattr(critic, "settings", Settings())

    result = await critique_answer("answer", sample_refs, confidence=0.95)
    assert result.approved is True


async def test_critic_approved_response(monkeypatch, sample_refs):
    """LLM returns approved JSON → CriticResult.approved=True."""
    monkeypatch.setenv("CRITIC_ENABLED", "true")
    monkeypatch.setenv("CRITIC_CONFIDENCE_THRESHOLD", "0.7")
    from config import Settings
    monkeypatch.setattr(critic, "settings", Settings())

    approved_json = json.dumps({"approved": True, "feedback": None})
    mock_response = _mock_genai_response(approved_json)

    async def mock_to_thread(func, *args, **kwargs):
        return mock_response

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

    result = await critique_answer("valid answer", sample_refs, confidence=0.3)
    assert result.approved is True
    assert result.feedback is None


async def test_critic_rejected_response(monkeypatch, sample_refs):
    """LLM returns rejected JSON → CriticResult with feedback."""
    monkeypatch.setenv("CRITIC_ENABLED", "true")
    monkeypatch.setenv("CRITIC_CONFIDENCE_THRESHOLD", "0.7")
    from config import Settings
    monkeypatch.setattr(critic, "settings", Settings())

    rejected = json.dumps({"approved": False, "feedback": "Citation [1] does not match source"})
    mock_response = _mock_genai_response(rejected)

    async def mock_to_thread(func, *args, **kwargs):
        return mock_response

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

    result = await critique_answer("bad answer", sample_refs, confidence=0.3)
    assert result.approved is False
    assert "Citation [1]" in result.feedback


async def test_critic_malformed_json_approves(monkeypatch, sample_refs):
    """LLM returns garbled text → fail-open, approved."""
    monkeypatch.setenv("CRITIC_ENABLED", "true")
    monkeypatch.setenv("CRITIC_CONFIDENCE_THRESHOLD", "0.7")
    from config import Settings
    monkeypatch.setattr(critic, "settings", Settings())

    mock_response = _mock_genai_response("Sure! The answer looks good to me.")

    async def mock_to_thread(func, *args, **kwargs):
        return mock_response

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

    result = await critique_answer("answer", sample_refs, confidence=0.3)
    assert result.approved is True  # fail-open


async def test_critic_api_exception_approves(monkeypatch, sample_refs):
    """API crash → fail-open, approved."""
    monkeypatch.setenv("CRITIC_ENABLED", "true")
    monkeypatch.setenv("CRITIC_CONFIDENCE_THRESHOLD", "0.7")
    from config import Settings
    monkeypatch.setattr(critic, "settings", Settings())

    async def mock_to_thread(func, *args, **kwargs):
        raise ConnectionError("API unreachable")

    monkeypatch.setattr("asyncio.to_thread", mock_to_thread)

    result = await critique_answer("answer", sample_refs, confidence=0.3)
    assert result.approved is True


async def test_critic_result_immutable(sample_refs):
    """CriticResult is frozen — cannot mutate after creation."""
    result = CriticResult(approved=True, feedback=None)
    with pytest.raises(AttributeError):
        result.approved = False


def test_extract_json_strips_fences():
    """_extract_json handles ```json...``` wrapping."""
    fenced = '```json\n{"approved": true, "feedback": null}\n```'
    assert json.loads(_extract_json(fenced)) == {"approved": True, "feedback": None}

    # Plain JSON passthrough
    plain = '{"approved": false, "feedback": "error"}'
    assert json.loads(_extract_json(plain)) == {"approved": False, "feedback": "error"}
