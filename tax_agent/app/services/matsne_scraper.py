"""
Matsne Tax Code Scraper

Fetches the Georgian Tax Code from matsne.gov.ge, parses articles and
definitions, and persists them via TaxArticleStore / DefinitionStore.

Architecture: Single module with clear internal functions.
DOM note: Matsne uses a FLAT DOM — articles are not wrapped in containers.
Body paragraphs sit at the same level as header paragraphs.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional

import aiohttp
from bs4 import BeautifulSoup, Tag

from config import settings

logger = logging.getLogger(__name__)

# ─── Constants (update here if DOM changes) ──────────────────────────────────

MATSNE_TAX_CODE_URL = (
    "https://matsne.gov.ge/ka/document/view/1043717?publication=239"
)
ARTICLE_HEADER_SELECTOR = "p.muxlixml"
HEADER_TEXT_SELECTOR = ".oldStyleDocumentPart"
ARTICLE_BODY_SELECTOR = "p.abzacixml"
CROSS_REF_SELECTOR = "a.DocumentLink"
DEFINITIONS_ARTICLE_NUMBER = 8
FETCH_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 50 * 1024 * 1024  # 50 MB safety cap
USER_AGENT = "ScoopTaxAgent/1.0 (+tax-agent-backend)"

# Georgian patterns
ARTICLE_NUMBER_RE = re.compile(r"მუხლი\s+(\d+)")
KARI_RE = re.compile(r"^კარი\s+[IVXLCDM]+\.\s*(.+)")
TAVI_RE = re.compile(r"^თავი\s+[IVXLCDM]+\.\s*(.+)")
REPEALED_KEYWORDS = ("ძალადაკარგულია", "ამოღებულია")
EXCEPTION_KEYWORDS = ("გარდა", "გამონაკლისი", "არ ვრცელდება")


# ─── 3a: Transport ───────────────────────────────────────────────────────────


async def fetch_tax_code_html(session: aiohttp.ClientSession) -> str:
    """Fetch Georgian Tax Code HTML from Matsne.

    Applies rate-limit delay before request.
    Raises on non-200 status or timeout (no retry — caller decides).
    """
    delay = getattr(settings, "matsne_request_delay", 2.0)
    await asyncio.sleep(delay)

    timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT_SECONDS)
    headers = {"User-Agent": USER_AGENT}
    logger.info("matsne_fetch_start", extra={"url": MATSNE_TAX_CODE_URL})

    async with session.get(
        MATSNE_TAX_CODE_URL, timeout=timeout, headers=headers,
    ) as response:
        if response.status != 200:
            raise aiohttp.ClientResponseError(
                request_info=response.request_info,
                history=response.history,
                status=response.status,
                message=f"Matsne returned HTTP {response.status}",
            )
        raw = await response.read()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError(
                f"Response too large: {len(raw)} bytes "
                f"(limit {MAX_RESPONSE_BYTES})"
            )
        html = raw.decode("utf-8", errors="replace")
        logger.info(
            "matsne_fetch_complete",
            extra={"bytes": len(html)},
        )
        return html


def detect_version(html: str) -> Optional[str]:
    """Extract publication number from HTML content.

    Looks for 'publication=NNN' pattern in the page.
    Returns version string like '239' or None.
    """
    match = re.search(r"publication[=:]\s*(\d+)", html)
    return match.group(1) if match else None


# ─── 3b: Header Parsing ─────────────────────────────────────────────────────


def parse_article_headers(soup: BeautifulSoup) -> List[Dict]:
    """Extract article numbers, titles, and tag references from DOM.

    Returns list of dicts with keys:
        article_number (int), title (str), status (str),
        kari (str), tavi (str), header_tag (Tag)

    Tracks the current კარი (Part) and თავი (Chapter) context
    as we walk through all headers. Each article inherits the
    most recent kari/tavi values.

    The header_tag reference is CRITICAL for body slicing — it marks
    where each article starts in the flat DOM.
    """
    results: List[Dict] = []
    seen: set = set()
    current_kari = "ზოგადი"  # Default Part
    current_tavi = "ზოგადი"  # Default Chapter

    for tag in soup.select(ARTICLE_HEADER_SELECTOR):
        text_span = tag.select_one(HEADER_TEXT_SELECTOR)
        if not text_span:
            continue

        text = text_span.get_text(strip=True)

        # Track hierarchy context (კარი → თავი → მუხლი)
        kari_match = KARI_RE.match(text)
        if kari_match:
            current_kari = kari_match.group(1).strip()
            continue

        tavi_match = TAVI_RE.match(text)
        if tavi_match:
            current_tavi = tavi_match.group(1).strip()
            continue

        match = ARTICLE_NUMBER_RE.search(text)
        if not match:
            continue

        article_number = int(match.group(1))
        if article_number in seen:
            continue
        seen.add(article_number)

        # Title: everything after "მუხლი N. "
        title = re.sub(r"^მუხლი\s+\d+[\.\s]*", "", text).strip()

        # Detect repealed status
        full_text = tag.get_text(strip=True)
        status = "active"
        for kw in REPEALED_KEYWORDS:
            if kw in full_text.lower():
                status = "repealed"
                break

        results.append({
            "article_number": article_number,
            "title": title,
            "status": status,
            "kari": current_kari,
            "tavi": current_tavi,
            "header_tag": tag,
        })

    logger.info("headers_parsed", extra={"count": len(results)})
    return results


# ─── 3c: Body Parsing (Flat-DOM Slicing) ─────────────────────────────────────


def parse_article_body(
    header_tag: Tag,
    next_header_tag: Optional[Tag] = None,
) -> str:
    """Collect body paragraphs between this header and the next.

    FLAT-DOM ALGORITHM:
    1. Start from header_tag
    2. Walk next_siblings
    3. Stop at next_header_tag or any other p.muxlixml
    4. Collect text from p.abzacixml elements only
    5. Join with newlines, strip HTML
    """
    paragraphs: List[str] = []

    for sibling in header_tag.next_siblings:
        if not isinstance(sibling, Tag):
            continue

        # Stop at next article header boundary
        if sibling is next_header_tag:
            break

        # Safety boundary: stop at any other article header
        if sibling.name == "p" and "muxlixml" in sibling.get("class", []):
            break

        # Collect body paragraphs
        if sibling.name == "p" and "abzacixml" in sibling.get("class", []):
            text = sibling.get_text(strip=True)
            if text:
                paragraphs.append(text)

    return "\n".join(paragraphs)


# ─── 3d: Cross-References ───────────────────────────────────────────────────


def extract_cross_references(
    header_tag: Tag,
    next_header_tag: Optional[Tag] = None,
) -> List[int]:
    """Find article cross-references within this article's DOM scope.

    Extracts article numbers from a.DocumentLink hrefs only
    (not from body text — avoids false positives).
    Returns deduplicated sorted list.
    """
    refs: set = set()

    for sibling in header_tag.next_siblings:
        if not isinstance(sibling, Tag):
            continue

        if sibling is next_header_tag:
            break

        if sibling.name == "p" and "muxlixml" in sibling.get("class", []):
            break

        # Search for DocumentLink anchors within this paragraph
        for link in sibling.select(CROSS_REF_SELECTOR):
            href = link.get("href", "")
            # Parse article number from href patterns like #Article7
            match = re.search(r"#?[Aa]rticle(\d+)", href)
            if match:
                refs.add(int(match.group(1)))
            # Also try Georgian pattern: მუხლი N in href
            match_ka = ARTICLE_NUMBER_RE.search(href)
            if match_ka:
                refs.add(int(match_ka.group(1)))

    return sorted(refs)


def detect_exception_article(body: str) -> bool:
    """Check if body text contains lex specialis (exception) keywords.

    Note: Georgian mkhedruli script has no case distinction,
    so no .lower() normalization is needed.
    """
    return any(kw in body for kw in EXCEPTION_KEYWORDS)


# ─── 3e: Definition Extraction ──────────────────────────────────────────────


def extract_definitions(
    soup: BeautifulSoup,
    headers: List[Dict],
) -> List[Dict]:
    """Parse definitions from Article 8 (definitions article).

    Returns list of dicts with keys:
        term_ka (str), definition (str), article_ref (int = 8)

    Parses each body paragraph by splitting on em-dash (–).
    Deduplicates by term_ka.
    """
    # Find Article 8 header
    art8_header = None
    art8_next = None
    for i, h in enumerate(headers):
        if h["article_number"] == DEFINITIONS_ARTICLE_NUMBER:
            art8_header = h["header_tag"]
            if i + 1 < len(headers):
                art8_next = headers[i + 1]["header_tag"]
            break

    if art8_header is None:
        logger.warning("definitions_article_not_found", extra={
            "expected_article": DEFINITIONS_ARTICLE_NUMBER,
        })
        return []

    body_text = parse_article_body(art8_header, art8_next)
    if not body_text:
        return []

    definitions: List[Dict] = []
    seen_terms: set = set()

    for line in body_text.split("\n"):
        # Split on em-dash (–) or regular dash (-)
        for separator in ["–", "—", " - "]:
            if separator in line:
                parts = line.split(separator, 1)
                term = parts[0].strip().rstrip(".")
                defn = parts[1].strip() if len(parts) > 1 else ""

                if term and defn and term not in seen_terms:
                    seen_terms.add(term)
                    definitions.append({
                        "term_ka": term,
                        "definition": defn,
                        "article_ref": DEFINITIONS_ARTICLE_NUMBER,
                    })
                break

    logger.info("definitions_extracted", extra={"count": len(definitions)})
    return definitions


# ─── 3f: Orchestrator ────────────────────────────────────────────────────────


async def scrape_and_store(
    article_store,
    definition_store,
) -> Dict[str, int]:
    """Full scraping pipeline: fetch → parse → upsert.

    Args:
        article_store: TaxArticleStore instance (injected by caller)
        definition_store: DefinitionStore instance (injected by caller)

    Returns:
        {"articles_count": int, "definitions_count": int, "skipped": int}
    """
    from app.models.tax_article import TaxArticle
    from app.models.definition import Definition

    async with aiohttp.ClientSession() as session:
        html = await fetch_tax_code_html(session)

    soup = BeautifulSoup(html, "html.parser")
    headers = parse_article_headers(soup)

    articles_count = 0
    skipped = 0
    errors = 0

    for i, header in enumerate(headers):
        try:
            next_header_tag = (
                headers[i + 1]["header_tag"] if i + 1 < len(headers) else None
            )

            body = parse_article_body(header["header_tag"], next_header_tag)
            if not body:
                skipped += 1
                continue

            refs = extract_cross_references(
                header["header_tag"], next_header_tag,
            )
            is_exception = detect_exception_article(body)
            embedding_text = (
                f"Article {header['article_number']}: {header['title']}\n{body}"
            )

            article = TaxArticle(
                article_number=header["article_number"],
                kari=header["kari"],
                tavi=header["tavi"],
                title=header["title"],
                body=body,
                status=header["status"],
                related_articles=refs,
                is_exception=is_exception,
                embedding_text=embedding_text,
            )
            await article_store.upsert(article)
            articles_count += 1
        except Exception as e:
            errors += 1
            logger.error(
                "article_processing_failed",
                extra={
                    "article_number": header.get("article_number"),
                    "error": str(e),
                },
            )

    # Extract and store definitions
    defs = extract_definitions(soup, headers)
    defs_stored = 0
    for d in defs:
        try:
            defn = Definition(
                term_ka=d["term_ka"],
                definition=d["definition"],
                article_ref=d["article_ref"],
            )
            await definition_store.upsert(defn)
            defs_stored += 1
        except Exception as e:
            errors += 1
            logger.error(
                "definition_processing_failed",
                extra={
                    "term_ka": d.get("term_ka"),
                    "error": str(e),
                },
            )

    stats = {
        "articles_count": articles_count,
        "definitions_count": defs_stored,
        "skipped": skipped,
        "errors": errors,
    }
    logger.info("scrape_complete", extra=stats)
    return stats
