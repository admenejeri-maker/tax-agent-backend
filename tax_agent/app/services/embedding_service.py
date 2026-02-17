"""
Embedding Service — Vector Embedding Pipeline
===============================================

Generates 768-dim vector embeddings for tax articles and definitions
using Google's text-embedding-004 model, then persists them via CRUD stores.

SDK Compatibility:
    Uses asyncio.to_thread wrapper for sync client.models.embed_content,
    matching Scoop's gemini_adapter pattern. Works with google-genai >= 1.14.0.
"""

import asyncio
from typing import List, Optional

import structlog

logger = structlog.get_logger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

MAX_EMBEDDING_CHARS = 8000  # ~2000 Georgian tokens (4 bytes/char avg)
EXPECTED_DIMENSIONS = 3072  # gemini-embedding-001 output dimensions
DEFAULT_BATCH_SIZE = 100  # Conservative; Google docs say 250 max

# ─── Lazy Client Singleton ───────────────────────────────────────────────────

_client = None


def _get_client():
    """
    Lazy-initialize the Google GenAI client (singleton).

    Returns:
        google.genai.Client configured with API key from settings.
    """
    global _client
    if _client is None:
        from google import genai
        from config import settings

        _client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("genai_client_initialized")
    return _client


def reset_client():
    """Reset the client singleton (for testing)."""
    global _client
    _client = None


def get_genai_client():
    """Public accessor for the Google GenAI client singleton.

    Used by rag_pipeline.py for generate_content calls.
    Shares the same lazy-initialized client as embedding operations.

    Returns:
        google.genai.Client configured with API key from settings.
    """
    return _get_client()


# ─── Text Builders ───────────────────────────────────────────────────────────


def build_embedding_text(article: dict) -> str:
    """
    Build rich embedding text with Georgian hierarchy prefix.

    Format: "კარი IX → თავი I → მუხლი 169. Title\nBody"

    Args:
        article: Dict with keys: kari, tavi, article_number, title, body

    Returns:
        Formatted text string for embedding.
    """
    kari = article.get("kari", "")
    tavi = article.get("tavi", "")
    num = article.get("article_number", "")
    title = article.get("title", "")
    body = article.get("body", "")

    text = f"{kari} → {tavi} → მუხლი {num}. {title}\n{body}"
    return text.strip()


def build_definition_text(defn: dict) -> str:
    """
    Build embedding text for a definition.

    Format: "term_ka: definition"

    Args:
        defn: Dict with keys: term_ka, definition

    Returns:
        Formatted text string for embedding.
    """
    term = defn.get("term_ka", "")
    definition = defn.get("definition", "")
    return f"{term}: {definition}"


# ─── Core Embedding Functions ────────────────────────────────────────────────


def _truncate_text(text: str) -> str:
    """
    Truncate text to MAX_EMBEDDING_CHARS if needed.

    Logs a warning when truncation occurs.

    Args:
        text: Input text to possibly truncate.

    Returns:
        Text, truncated if longer than MAX_EMBEDDING_CHARS.
    """
    if len(text) > MAX_EMBEDDING_CHARS:
        logger.warning(
            "text_truncated",
            original_length=len(text),
            truncated_to=MAX_EMBEDDING_CHARS,
        )
        return text[:MAX_EMBEDDING_CHARS]
    return text


async def embed_content(text: str, model: Optional[str] = None) -> List[float]:
    """
    Generate embedding for a single text.

    Uses asyncio.to_thread to call the sync SDK method without blocking
    the event loop (matches Scoop's gemini_adapter pattern).

    Args:
        text: Text to embed (will be truncated if > MAX_EMBEDDING_CHARS).
        model: Embedding model name (defaults to settings.embedding_model).

    Returns:
        List of 768 floats.

    Raises:
        ValueError: If embedding dimensions != 768.
    """
    from config import settings

    if model is None:
        model = settings.embedding_model

    text = _truncate_text(text)
    client = _get_client()

    result = await asyncio.to_thread(
        client.models.embed_content,
        model=model,
        contents=text,
    )

    embedding = result.embeddings[0].values
    if len(embedding) != EXPECTED_DIMENSIONS:
        raise ValueError(
            f"Expected {EXPECTED_DIMENSIONS} dimensions, got {len(embedding)}"
        )
    return embedding


async def embed_batch(
    texts: List[str],
    batch_size: int = DEFAULT_BATCH_SIZE,
    model: Optional[str] = None,
) -> List[List[float]]:
    """
    Generate embeddings for a batch of texts with chunking.

    Processes texts in chunks of `batch_size`, with a small sleep between
    chunks for rate limiting (free tier protection).

    Args:
        texts: List of texts to embed.
        batch_size: Max texts per API call (default 100).
        model: Embedding model name.

    Returns:
        List of embeddings (each 768 floats), same order as input texts.
    """
    from config import settings

    if model is None:
        model = settings.embedding_model

    all_embeddings: List[List[float]] = []

    for i in range(0, len(texts), batch_size):
        chunk = texts[i : i + batch_size]
        # Truncate each text in the chunk
        chunk = [_truncate_text(t) for t in chunk]

        client = _get_client()
        result = await asyncio.to_thread(
            client.models.embed_content,
            model=model,
            contents=chunk,
        )

        for emb in result.embeddings:
            if len(emb.values) != EXPECTED_DIMENSIONS:
                raise ValueError(
                    f"Expected {EXPECTED_DIMENSIONS} dims, got {len(emb.values)}"
                )
            all_embeddings.append(emb.values)

        # Rate limit: sleep between batches (skip after last batch)
        if i + batch_size < len(texts):
            await asyncio.sleep(0.1)

        logger.info(
            "batch_embedded",
            batch_start=i,
            batch_size=len(chunk),
            total=len(texts),
        )

    return all_embeddings


# ─── Orchestrator ─────────────────────────────────────────────────────────────


async def embed_and_store_all(
    article_store,
    definition_store,
) -> dict:
    """
    Full embedding pipeline: fetch all → embed → persist.

    Error isolation: if one article/definition fails to embed,
    it is logged and skipped — the pipeline continues.

    Args:
        article_store: TaxArticleStore instance (injected by caller).
        definition_store: DefinitionStore instance (injected by caller).

    Returns:
        {"articles_embedded": int, "definitions_embedded": int,
         "errors": int}
    """
    from config import settings

    model = settings.embedding_model
    articles_embedded = 0
    definitions_embedded = 0
    errors = 0

    # ── Embed Articles ────────────────────────────────────────────────────
    articles = await article_store.find_all()
    logger.info("embedding_articles_start", count=len(articles))

    for article in articles:
        try:
            text = build_embedding_text(article)
            embedding = await embed_content(text, model=model)
            await article_store.update_embedding(
                article_number=article["article_number"],
                embedding=embedding,
                embedding_model=model,
                embedding_text=text[:MAX_EMBEDDING_CHARS],
            )
            articles_embedded += 1
        except Exception as e:
            errors += 1
            logger.error(
                "article_embedding_failed",
                article_number=article.get("article_number"),
                error=str(e),
            )

    # ── Embed Definitions ─────────────────────────────────────────────────
    definitions = await definition_store.find_all()
    logger.info("embedding_definitions_start", count=len(definitions))

    for defn in definitions:
        try:
            text = build_definition_text(defn)
            embedding = await embed_content(text, model=model)
            await definition_store.update_embedding(
                term_ka=defn["term_ka"],
                embedding=embedding,
                embedding_model=model,
                embedding_text=text[:MAX_EMBEDDING_CHARS],
            )
            definitions_embedded += 1
        except Exception as e:
            errors += 1
            logger.error(
                "definition_embedding_failed",
                term_ka=defn.get("term_ka"),
                error=str(e),
            )

    stats = {
        "articles_embedded": articles_embedded,
        "definitions_embedded": definitions_embedded,
        "errors": errors,
    }
    logger.info("embedding_pipeline_complete", extra=stats)
    return stats
