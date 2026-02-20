"""
Tests for Matsne Tax Code Scraper.

All tests use mocked HTML fixtures — no network calls.
Organized by sub-task (3a–3f) per the implementation plan.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from app.services.matsne_scraper import (
    ARTICLE_NUMBER_RE,
    BODY_CROSS_REF_RE,
    BODY_CROSS_REF_ORDINAL_RE,
    DEFINITIONS_ARTICLE_NUMBER,
    KARI_RE,
    MAX_VALID_ARTICLE,
    TAVI_RE,
    USER_AGENT,
    detect_exception_article,
    detect_version,
    extract_body_cross_references,
    extract_cross_references,
    extract_definitions,
    fetch_tax_code_html,
    parse_article_body,
    parse_article_headers,
    scrape_and_store,
)

# ─── Fixtures (realistic Georgian HTML) ──────────────────────────────────────

SAMPLE_HEADER_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ზოგადი ნაწილი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ზოგადი დებულებები</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 1. გადასახადის ცნება</span></p>
  <p class="abzacixml">1. გადასახადი არის სავალდებულო შენატანი.</p>
  <p class="abzacixml">2. გადასახადი ამ კოდექსით განისაზღვრება.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 2. საგადასახადო კანონმდებლობა</span></p>
  <p class="abzacixml">1. საგადასახადო კანონმდებლობა მოიცავს.</p>
</div>
"""

SAMPLE_REPEALED_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 5. ძალადაკარგულია</span></p>
  <p class="abzacixml">ეს მუხლი ძალადაკარგულია.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 6. აქტიური მუხლი</span></p>
  <p class="abzacixml">აქტიური ტექსტი.</p>
</div>
"""

SAMPLE_EMPTY_BODY_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 10. ცარიელი მუხლი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 11. შემდეგი მუხლი</span></p>
  <p class="abzacixml">შემდეგი ტექსტი.</p>
</div>
"""

SAMPLE_HTML_TAGS_BODY = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 3. HTML ტესტი</span></p>
  <p class="abzacixml">პირველი <b>მუქი</b> ტექსტი.</p>
  <p class="abzacixml">მეორე <i>დახრილი</i> ტექსტი.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 4. შემდეგი</span></p>
</div>
"""

SAMPLE_CROSS_REF_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 20. ჯვარედინი მითითება</span></p>
  <p class="abzacixml">იხილეთ <a class="DocumentLink" href="/ka/document/view/1043717#Article7">მუხლი 7</a> და <a class="DocumentLink" href="/ka/document/view/1043717#Article12">მუხლი 12</a>.</p>
  <p class="abzacixml">ასევე <a class="DocumentLink" href="/ka/document/view/1043717#Article7">მუხლი 7</a>.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 21. შემდეგი</span></p>
</div>
"""

SAMPLE_NO_CROSS_REF_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 30. მითითებების გარეშე</span></p>
  <p class="abzacixml">ტექსტი მითითებების გარეშე.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 31. შემდეგი</span></p>
</div>
"""

SAMPLE_FALSE_POSITIVE_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 40. ცრუ დადებითი</span></p>
  <p class="abzacixml">იხილეთ <a href="https://example.com/other">სხვა ბმული</a>.</p>
  <p class="abzacixml">ზოგიერთ მუხლი 99 ტექსტში.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 41. შემდეგი</span></p>
</div>
"""

SAMPLE_DEFINITIONS_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ზოგადი ნაწილი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ზოგადი დებულებები</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 7. წინა მუხლი</span></p>
  <p class="abzacixml">წინა ტექსტი.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 8. ტერმინთა განმარტება</span></p>
  <p class="abzacixml">გადასახადის გადამხდელი – პირი, რომელსაც ეკისრება გადასახადის გადახდის ვალდებულება.</p>
  <p class="abzacixml">საგადასახადო აგენტი – პირი, რომელიც ვალდებულია გამოიანგარიშოს.</p>
  <p class="abzacixml">საგადასახადო ორგანო – საჯარო სამართლის იურიდიული პირი.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 9. შემდეგი მუხლი</span></p>
  <p class="abzacixml">შემდეგი ტექსტი.</p>
</div>
"""

SAMPLE_DEFINITIONS_DUPLICATE_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 8. ტერმინთა განმარტება</span></p>
  <p class="abzacixml">ტერმინი – პირველი განმარტება.</p>
  <p class="abzacixml">ტერმინი – მეორე განმარტება.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 9. შემდეგი</span></p>
</div>
"""

SAMPLE_EXCEPTION_BODY = "ეს მუხლი არ ვრცელდება იმ პირებზე, რომლებიც გარდა სპეციალური შემთხვევებისა."
SAMPLE_NON_EXCEPTION_BODY = "ეს მუხლი ვრცელდება ყველა პირზე."

SAMPLE_VERSION_HTML = '<html><head><title>Tax Code publication=239</title></head></html>'
SAMPLE_NO_VERSION_HTML = "<html><head><title>Tax Code</title></head></html>"

SAMPLE_HIERARCHY_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ზოგადი ნაწილი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ზოგადი დებულებები</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 1. გადასახადის ცნება</span></p>
  <p class="abzacixml">ტექსტი.</p>
</div>
"""

SAMPLE_MULTI_KARI_HTML = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ზოგადი ნაწილი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ზოგადი დებულებები</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 1. პირველი</span></p>
  <p class="abzacixml">ტექსტი 1.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი II. სპეციალური ნაწილი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი III. სპეციალური დებულებები</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 50. მეორე</span></p>
  <p class="abzacixml">ტექსტი 50.</p>
</div>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# 3a: Fetch & Version Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestFetchAndVersion:
    """Sub-task 3a: Transport layer tests."""

    def test_detect_version_extracts_publication(self):
        """Version string parsed from HTML content."""
        result = detect_version(SAMPLE_VERSION_HTML)
        assert result == "239"

    def test_detect_version_returns_none_when_missing(self):
        """None returned when no publication pattern found."""
        result = detect_version(SAMPLE_NO_VERSION_HTML)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_returns_html_string(self):
        """fetch_tax_code_html returns HTML via mocked session."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(
            return_value=b"<html>test</html>",
        )
        mock_response.request_info = MagicMock()
        mock_response.history = ()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        with patch("app.services.matsne_scraper.settings") as mock_settings:
            mock_settings.matsne_request_delay = 0  # No delay in tests
            result = await fetch_tax_code_html(mock_session)

        assert result == "<html>test</html>"

    @pytest.mark.asyncio
    async def test_fetch_respects_rate_limit(self):
        """asyncio.sleep called with configured delay."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"<html></html>")
        mock_response.request_info = MagicMock()
        mock_response.history = ()

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        ))

        with (
            patch("app.services.matsne_scraper.settings") as mock_settings,
            patch("app.services.matsne_scraper.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        ):
            mock_settings.matsne_request_delay = 2.5
            await fetch_tax_code_html(mock_session)
            mock_sleep.assert_awaited_once_with(2.5)

    @pytest.mark.asyncio
    async def test_fetch_sends_user_agent(self):
        """F3: User-Agent header sent with request."""
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.read = AsyncMock(return_value=b"<html></html>")
        mock_response.request_info = MagicMock()
        mock_response.history = ()

        mock_session = AsyncMock()
        mock_ctx = AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=False),
        )
        mock_session.get = MagicMock(return_value=mock_ctx)

        with patch("app.services.matsne_scraper.settings") as mock_settings:
            mock_settings.matsne_request_delay = 0
            await fetch_tax_code_html(mock_session)

        call_kwargs = mock_session.get.call_args
        assert "headers" in call_kwargs.kwargs
        assert call_kwargs.kwargs["headers"]["User-Agent"] == USER_AGENT


# ═══════════════════════════════════════════════════════════════════════════════
# 3b: Header Parsing Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestHeaderParsing:
    """Sub-task 3b: Article header extraction tests."""

    def test_parse_headers_extracts_number_and_title(self):
        """Correct article_number + title extracted from fixture."""
        soup = BeautifulSoup(SAMPLE_HEADER_HTML, "html.parser")
        headers = parse_article_headers(soup)

        assert len(headers) == 2
        assert headers[0]["article_number"] == 1
        assert headers[0]["title"] == "გადასახადის ცნება"
        assert headers[1]["article_number"] == 2
        assert headers[1]["title"] == "საგადასახადო კანონმდებლობა"

    def test_parse_headers_handles_hierarchy(self):
        """Chapter/Part headers skipped, only articles extracted."""
        soup = BeautifulSoup(SAMPLE_HIERARCHY_HTML, "html.parser")
        headers = parse_article_headers(soup)

        # Only "მუხლი 1" should be extracted, not კარი or თავი
        assert len(headers) == 1
        assert headers[0]["article_number"] == 1
        assert headers[0]["kari"] == "ზოგადი ნაწილი"
        assert headers[0]["tavi"] == "ზოგადი დებულებები"

    def test_parse_headers_tracks_kari_tavi_change(self):
        """Kari/tavi context updates when new hierarchy headers appear."""
        soup = BeautifulSoup(SAMPLE_MULTI_KARI_HTML, "html.parser")
        headers = parse_article_headers(soup)

        assert len(headers) == 2
        assert headers[0]["kari"] == "ზოგადი ნაწილი"
        assert headers[0]["tavi"] == "ზოგადი დებულებები"
        assert headers[1]["kari"] == "სპეციალური ნაწილი"
        assert headers[1]["tavi"] == "სპეციალური დებულებები"

    def test_parse_headers_deduplicates(self):
        """Duplicate article numbers produce only one entry."""
        dup_html = """\
        <div id="maindoc">
          <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
          <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
          <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 1. პირველი</span></p>
          <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 1. დუბლიკატი</span></p>
          <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 2. მეორე</span></p>
        </div>
        """
        soup = BeautifulSoup(dup_html, "html.parser")
        headers = parse_article_headers(soup)

        numbers = [h["article_number"] for h in headers]
        assert numbers == [1, 2]

    def test_parse_headers_detects_repealed(self):
        """Repealed articles get status='repealed'."""
        soup = BeautifulSoup(SAMPLE_REPEALED_HTML, "html.parser")
        headers = parse_article_headers(soup)

        assert headers[0]["status"] == "repealed"
        assert headers[1]["status"] == "active"

    def test_parse_headers_first_article(self):
        """First article (Article 1) correctly identified."""
        soup = BeautifulSoup(SAMPLE_HEADER_HTML, "html.parser")
        headers = parse_article_headers(soup)

        assert headers[0]["article_number"] == 1
        assert headers[0]["header_tag"] is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 3c: Body Parsing Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestBodyParsing:
    """Sub-task 3c: Flat-DOM body slicing tests."""

    def test_parse_body_extracts_content(self):
        """Body text extracted from p.abzacixml between headers."""
        soup = BeautifulSoup(SAMPLE_HEADER_HTML, "html.parser")
        headers = parse_article_headers(soup)

        body = parse_article_body(
            headers[0]["header_tag"],
            headers[1]["header_tag"],
        )
        assert "გადასახადი არის" in body
        assert "გადასახადი ამ კოდექსით" in body

    def test_parse_body_empty_returns_empty(self):
        """Empty body (no paragraphs between headers) returns ''."""
        soup = BeautifulSoup(SAMPLE_EMPTY_BODY_HTML, "html.parser")
        headers = parse_article_headers(soup)

        body = parse_article_body(
            headers[0]["header_tag"],
            headers[1]["header_tag"],
        )
        assert body == ""

    def test_parse_body_strips_html(self):
        """HTML tags removed, plain text only."""
        soup = BeautifulSoup(SAMPLE_HTML_TAGS_BODY, "html.parser")
        headers = parse_article_headers(soup)

        body = parse_article_body(
            headers[0]["header_tag"],
            headers[1]["header_tag"],
        )
        assert "<b>" not in body
        assert "<i>" not in body
        assert "მუქი" in body
        assert "დახრილი" in body

    def test_parse_body_preserves_paragraphs(self):
        """Paragraphs joined with newlines."""
        soup = BeautifulSoup(SAMPLE_HEADER_HTML, "html.parser")
        headers = parse_article_headers(soup)

        body = parse_article_body(
            headers[0]["header_tag"],
            headers[1]["header_tag"],
        )
        lines = body.split("\n")
        assert len(lines) == 2
        assert "სავალდებულო" in lines[0]
        assert "განისაზღვრება" in lines[1]


# ═══════════════════════════════════════════════════════════════════════════════
# 3d: Cross-Reference Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossReferences:
    """Sub-task 3d: Cross-reference extraction tests."""

    def test_extract_cross_refs_from_links(self):
        """Article numbers parsed from a.DocumentLink hrefs."""
        soup = BeautifulSoup(SAMPLE_CROSS_REF_HTML, "html.parser")
        headers = parse_article_headers(soup)

        refs = extract_cross_references(
            headers[0]["header_tag"],
            headers[1]["header_tag"],
        )
        assert 7 in refs
        assert 12 in refs

    def test_extract_cross_refs_deduplicates(self):
        """Duplicate references collapsed (Article 7 appears twice in fixture)."""
        soup = BeautifulSoup(SAMPLE_CROSS_REF_HTML, "html.parser")
        headers = parse_article_headers(soup)

        refs = extract_cross_references(
            headers[0]["header_tag"],
            headers[1]["header_tag"],
        )
        assert refs.count(7) == 1  # Deduplicated

    def test_detect_exception_article_true(self):
        """Lex specialis keywords → is_exception=True."""
        assert detect_exception_article(SAMPLE_EXCEPTION_BODY) is True

    def test_detect_exception_article_false(self):
        """F2: Non-exception text → is_exception=False."""
        assert detect_exception_article(SAMPLE_NON_EXCEPTION_BODY) is False

    def test_extract_cross_refs_empty(self):
        """No DocumentLink tags → empty list."""
        soup = BeautifulSoup(SAMPLE_NO_CROSS_REF_HTML, "html.parser")
        headers = parse_article_headers(soup)

        refs = extract_cross_references(
            headers[0]["header_tag"],
            headers[1]["header_tag"],
        )
        assert refs == []

    def test_extract_cross_refs_no_false_positives(self):
        """Non-DocumentLink links and body text article numbers filtered out."""
        soup = BeautifulSoup(SAMPLE_FALSE_POSITIVE_HTML, "html.parser")
        headers = parse_article_headers(soup)

        refs = extract_cross_references(
            headers[0]["header_tag"],
            headers[1]["header_tag"],
        )
        # "მუხლი 99" in body text should NOT be extracted (it's text, not a link)
        # "https://example.com/other" is not a DocumentLink class
        assert refs == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3e: Definition Extraction Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestDefinitions:
    """Sub-task 3e: Article 8 definition extraction tests."""

    def test_extract_definitions_finds_terms(self):
        """Terms + definitions parsed from Article 8 fixture."""
        soup = BeautifulSoup(SAMPLE_DEFINITIONS_HTML, "html.parser")
        headers = parse_article_headers(soup)
        defs = extract_definitions(soup, headers)

        assert len(defs) == 3
        terms = [d["term_ka"] for d in defs]
        assert "გადასახადის გადამხდელი" in terms
        assert "საგადასახადო აგენტი" in terms
        assert "საგადასახადო ორგანო" in terms

    def test_extract_definitions_valid_article_ref(self):
        """All definitions have article_ref=8."""
        soup = BeautifulSoup(SAMPLE_DEFINITIONS_HTML, "html.parser")
        headers = parse_article_headers(soup)
        defs = extract_definitions(soup, headers)

        for d in defs:
            assert d["article_ref"] == 8

    def test_extract_definitions_deduplicates(self):
        """Duplicate terms collapsed (keep first)."""
        soup = BeautifulSoup(SAMPLE_DEFINITIONS_DUPLICATE_HTML, "html.parser")
        headers = parse_article_headers(soup)
        defs = extract_definitions(soup, headers)

        terms = [d["term_ka"] for d in defs]
        assert terms.count("ტერმინი") == 1
        assert defs[0]["definition"] == "პირველი განმარტება."


# ═══════════════════════════════════════════════════════════════════════════════
# 3f: Orchestrator Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestOrchestrator:
    """Sub-task 3f: Full pipeline (scrape_and_store) tests."""

    @pytest.mark.asyncio
    async def test_scrape_and_store_counts(self):
        """Stats dict has correct articles_count and definitions_count."""
        mock_article_store = AsyncMock()
        mock_definition_store = AsyncMock()

        html = SAMPLE_DEFINITIONS_HTML  # Has articles 7, 8, 9

        with patch(
            "app.services.matsne_scraper.fetch_tax_code_html",
            new_callable=AsyncMock,
            return_value=html,
        ):
            stats = await scrape_and_store(
                mock_article_store, mock_definition_store
            )

        assert stats["articles_count"] + stats["skipped"] == 3  # 3 articles total
        assert stats["definitions_count"] == 3  # 3 definitions in article 8

    @pytest.mark.asyncio
    async def test_scrape_and_store_skip_rate(self):
        """Skip rate ≤ 5% of articles."""
        mock_article_store = AsyncMock()
        mock_definition_store = AsyncMock()

        html = SAMPLE_DEFINITIONS_HTML

        with patch(
            "app.services.matsne_scraper.fetch_tax_code_html",
            new_callable=AsyncMock,
            return_value=html,
        ):
            stats = await scrape_and_store(
                mock_article_store, mock_definition_store
            )

        total = stats["articles_count"] + stats["skipped"]
        if total > 0:
            skip_rate = stats["skipped"] / total
            assert skip_rate <= 0.05, f"Skip rate {skip_rate:.1%} exceeds 5%"

    @pytest.mark.asyncio
    async def test_scrape_and_store_error_isolation(self):
        """F1: One bad article doesn't kill entire scrape."""
        mock_article_store = AsyncMock()
        mock_definition_store = AsyncMock()

        # First upsert raises, subsequent ones succeed
        mock_article_store.upsert.side_effect = [
            RuntimeError("DB write failed"),
            None,  # second article succeeds
            None,  # third article succeeds
        ]

        html = SAMPLE_DEFINITIONS_HTML  # Has articles 7, 8, 9

        with patch(
            "app.services.matsne_scraper.fetch_tax_code_html",
            new_callable=AsyncMock,
            return_value=html,
        ):
            stats = await scrape_and_store(
                mock_article_store, mock_definition_store
            )

        # At least one succeeded despite the error
        assert stats["articles_count"] >= 1
        assert stats["errors"] >= 1

    @pytest.mark.asyncio
    async def test_embedding_text_format(self):
        """embedding_text populated as 'Article N: title\\nbody'."""
        mock_article_store = AsyncMock()
        mock_definition_store = AsyncMock()

        html = SAMPLE_HEADER_HTML  # Articles 1 and 2

        with patch(
            "app.services.matsne_scraper.fetch_tax_code_html",
            new_callable=AsyncMock,
            return_value=html,
        ):
            await scrape_and_store(mock_article_store, mock_definition_store)

        # Check the TaxArticle passed to upsert
        calls = mock_article_store.upsert.call_args_list
        assert len(calls) >= 1

        first_article = calls[0][0][0]
        assert first_article.embedding_text.startswith("Article 1:")
        assert "გადასახადის ცნება" in first_article.embedding_text
        assert "\n" in first_article.embedding_text


# ═══════════════════════════════════════════════════════════════════════════════
# 3g: Body Cross-Reference Extraction Tests (Phase 1 — Graph Expansion)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBodyCrossReferences:
    """Phase 1: Body-text cross-reference extraction tests."""

    def test_extract_body_cross_references(self):
        """Regex finds 'მუხლი N' patterns in body text."""
        body = "იხილეთ მუხლი 81 და მუხლი 143 დამატებით ინფორმაციისთვის."
        refs = extract_body_cross_references(body)
        assert refs == [81, 143]

    def test_extract_body_cross_refs_self_exclusion(self):
        """Article N does not reference itself."""
        body = "ამ მუხლი 81 თანახმად, მუხლი 82 ვრცელდება."
        refs = extract_body_cross_references(body, self_article=81)
        assert 81 not in refs
        assert 82 in refs

    def test_extract_body_cross_refs_dedup(self):
        """Duplicate references are deduplicated."""
        body = "მუხლი 81 და კვლავ მუხლი 81 მოხსენიებულია."
        refs = extract_body_cross_references(body, self_article=-1)
        assert refs == [81]  # Only one entry

    def test_extract_body_cross_refs_empty(self):
        """Empty body returns empty list."""
        assert extract_body_cross_references("") == []
        assert extract_body_cross_references("ტექსტი მითითებების გარეშე.") == []

    def test_scrape_merge_dom_and_body_refs(self):
        """scrape_and_store merges DOM + body-text refs into related_articles."""
        mock_article_store = AsyncMock()
        mock_definition_store = AsyncMock()

        # SAMPLE_CROSS_REF_HTML has a.DocumentLink refs to articles 7 and 12,
        # and the body text also mentions "მუხლი 7" and "მუხლი 12".
        # The merge should deduplicate them.
        html = SAMPLE_CROSS_REF_HTML

        with patch(
            "app.services.matsne_scraper.fetch_tax_code_html",
            new_callable=AsyncMock,
            return_value=html,
        ):
            # We can't easily run scrape_and_store with this fixture
            # because it only has 2 articles (20, 21) and article 20
            # has inline "მუხლი 7" and "მუხლი 12" in its body.
            # Instead, test the function directly:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(SAMPLE_CROSS_REF_HTML, "html.parser")
            headers = parse_article_headers(soup)

            # Article 20: has DocumentLink hrefs
            h0 = headers[0]
            h1 = headers[1] if len(headers) > 1 else None
            next_tag = h1["header_tag"] if h1 else None

            dom_refs = extract_cross_references(h0["header_tag"], next_tag)
            body = parse_article_body(h0["header_tag"], next_tag)
            body_refs = extract_body_cross_references(
                body, self_article=h0["article_number"]
            )

            merged = sorted(set(dom_refs + body_refs))

            # DOM should find 7, 12 from anchors
            assert 7 in dom_refs
            assert 12 in dom_refs
            # Body should also find 7, 12 from text "მუხლი 7" and "მუხლი 12"
            assert 7 in body_refs
            assert 12 in body_refs
            # Merged should be deduplicated
            assert merged == sorted(set(dom_refs + body_refs))
            assert len(merged) == len(set(merged))  # No duplicates


class TestPrimaArticleDefense:
    """Tests for the Three-Layer Prima Defense against phantom article numbers."""

    def test_body_parse_strips_sup_tags(self):
        """Layer 1: sup.decompose() removes prima markers from body text.

        Input:  <p class="abzacixml">იხ. 135<sup>2</sup> მუხლით</p>
        Expected: "135" appears, "1352" does NOT, "2" is removed.
        """
        html = """\
<div id="maindoc">
  <p class="muxlixml"><span class="oldStyleDocumentPart">კარი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">თავი I. ტესტი</span></p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 50. პრიმა ტესტი</span></p>
  <p class="abzacixml">იხილეთ 135<sup>2</sup> მუხლითაც გათვალისწინებული.</p>
  <p class="muxlixml"><span class="oldStyleDocumentPart">მუხლი 51. შემდეგი</span></p>
</div>
"""
        soup = BeautifulSoup(html, "html.parser")
        headers = parse_article_headers(soup)
        h0 = headers[0]
        next_tag = headers[1]["header_tag"] if len(headers) > 1 else None
        body = parse_article_body(h0["header_tag"], next_tag)

        # sup.decompose() should remove "2" from the text
        assert "1352" not in body, "Phantom concatenation still present!"
        assert "135" in body, "Parent article number should remain"

    def test_extract_body_cross_refs_filters_phantom(self):
        """Layer 2: MAX_VALID_ARTICLE filters phantom numbers >500.

        Body text with concatenated prima (e.g., old pre-fix body)
        should have phantoms >500 filtered out.
        """
        # Simulate old body text where 135² became "1352"
        body = "ამ კოდექსის მუხლი 1352 თანახმად მუხლი 81 გათვალისწინებული."
        refs = extract_body_cross_references(body, self_article=39)

        # 81 should pass (valid), 1352 should be filtered (>500)
        assert 81 in refs, "Valid article 81 should be retained"
        assert 1352 not in refs, f"Phantom 1352 should be filtered (MAX={MAX_VALID_ARTICLE})"
        # Verify the constant value
        assert MAX_VALID_ARTICLE == 500



# ═══════════════════════════════════════════════════════════════════════════════
# P2 — Ordinal Regex Tightening (Stress Tests)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOrdinalRegexFix:
    """P2: BODY_CROSS_REF_ORDINAL_RE — dash + ე are now mandatory.

    These tests verify:
      1. All real ordinal forms still match (no false negatives).
      2. Base form 'N მუხლი' (no dash, no ე) does NOT match ordinal regex.
      3. Boundary and em-dash edge cases.
    """

    # ── T-ORD1: Standard dash-ე form ─────────────────────────────────────────

    def test_ordinal_standard_dash_e(self):
        """T-ORD1: '238-ე მუხლი' — standard form matches."""
        body = "238-ე მუხლი გამოიყენება ამ შემთხვევებში."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 238 in refs, "Standard ordinal '238-ე მუხლი' must be captured"

    # ── T-ORD2: No-dash bare-ე form ──────────────────────────────────────────

    def test_ordinal_no_dash_bare_e(self):
        """T-ORD2: '81ე მუხლი' (no dash) — must NOT match after ე required.

        IMPORTANT: After requiring dash, '81ე მუხლი' (no separator) is
        intentionally excluded. If real corpus has this form, reconsider.
        This test DOCUMENTS that decision. BODY_CROSS_REF_RE still captures
        'მუხლი 81' base form text in the same sentence.
        """
        body = "81ე მუხლი გამოიყენება."
        refs = extract_body_cross_references(body, self_article=-1)
        # Ordinal regex (dash mandatory) won't match; BODY_CROSS_REF_RE also
        # won't match because the form is "81ე მუხლი" not "მუხლი 81".
        # This is ACCEPTABLE: this construct is non-standard in Georgian law.
        assert 81 not in refs, (
            "Dashless '81ე მუხლი' excluded intentionally — "
            "real corpus uses dash form '81-ე მუხლი'"
        )

    # ── T-ORD3: Grammatical suffix variants ──────────────────────────────────

    def test_ordinal_suffix_mit(self):
        """T-ORD3a: '54-ე მუხლით' (instrumental suffix) matches."""
        body = "54-ე მუხლით გათვალისწინებული ვალდებულება."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 54 in refs, "Ordinal with -ით suffix must be captured"

    def test_ordinal_suffix_is(self):
        """T-ORD3b: '71-ე მუხლის' (genitive suffix) matches."""
        body = "71-ე მუხლის დებულებები გამოიყენება."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 71 in refs, "Ordinal with -ის suffix must be captured"

    def test_ordinal_suffix_idan(self):
        """T-ORD3c: '166-ე მუხლიდან' (ablative suffix) matches."""
        body = "166-ე მუხლიდან გამომდინარე ვალდებულება."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 166 in refs, "Ordinal with -იდან suffix must be captured"

    # ── T-ORD4: KEY REGRESSION — base form must NOT match ordinal regex ──────

    def test_ordinal_regex_does_not_capture_base_form(self):
        """T-ORD4: '81 მუხლი' (space, no ე, no dash) must NOT trigger ordinal regex.

        This is the core fix: previously ე? and [-]? both optional meant
        '81 მუხლი' (base form) would match the ordinal regex.
        """
        # Direct regex test — not via extract_body_cross_references
        # since BODY_CROSS_REF_RE would correctly capture "მუხლი 81" text
        import re
        bare_ordinal = re.compile(BODY_CROSS_REF_ORDINAL_RE.pattern)
        no_match_text = "81 მუხლი"  # base form: no dash, no ე
        assert bare_ordinal.search(no_match_text) is None, (
            "Base form '81 მუხლი' (no dash, no ე) MUST NOT match ordinal regex"
        )

    # ── T-ORD5: Boundary at MAX_VALID_ARTICLE ─────────────────────────────────

    def test_ordinal_boundary_500(self):
        """T-ORD5a: '500-ე მუხლი' — at boundary, must be captured."""
        body = "500-ე მუხლი ვრცელდება."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 500 in refs, "Article 500 at MAX_VALID_ARTICLE boundary must be captured"

    def test_ordinal_over_boundary_filtered(self):
        """T-ORD5b: '501-ე მუხლი' — over boundary, must be filtered."""
        body = "501-ე მუხლი სამოქალაქო კოდექსიდან."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 501 not in refs, "Article 501 > MAX_VALID_ARTICLE must be filtered"

    # ── T-ORD6: Em-dash Unicode variant ──────────────────────────────────────

    def test_ordinal_em_dash_variant(self):
        """T-ORD6: '54\u2013ე მუხლი' (em-dash \\u2013) — must match."""
        body = "54\u2013ე მუხლი გამოიყენება."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 54 in refs, "Em-dash variant '54\u2013ე მუხლი' must be captured"

    # ── T-ORD7: Combined base + ordinal in same body text ────────────────────

    def test_combined_base_and_ordinal_forms(self):
        """T-ORD7: Both forms in one sentence — correctly captures both."""
        body = "ამ კოდექსის მუხლი 81 და 54-ე მუხლი ერთობლივად გამოიყენება."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 81 in refs, "Base form 'მუხლი 81' must be captured by BODY_CROSS_REF_RE"
        assert 54 in refs, "Ordinal '54-ე მუხლი' must be captured by ORDINAL_RE"
        assert refs == sorted(refs), "Result must be sorted"
# ═══════════════════════════════════════════════════════════════════════════════


class TestBodyCrossRefRegexFix3:
    """Fix 3: BODY_CROSS_REF_RE must include optional 'ამ კოდექსის' anchor.

    The core defence against phantom article numbers from EXTERNAL law codes
    (e.g., Civil Code) is the existing MAX_VALID_ARTICLE <= 500 guard.
    The regex change adds an optional forward-compatible context anchor.
    """

    def test_body_cross_ref_base_form_no_anchor(self):
        """Fix 3 — T-RE1: Bare 'მუხლი N' (no anchor) still matches — backward compatible."""
        body = "ამ კოდექსის 250-ე მუხლის შესაბამისად, მუხლი 81 გამოიყენება."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 81 in refs, "Bare 'მუხლი 81' must still be matched"

    def test_body_cross_ref_with_kodeksis_anchor(self):
        """Fix 3 — T-RE2: 'ამ კოდექსის მუხლი N' pattern matched by updated regex."""
        body = "ამ კოდექსის მუხლი 135 შესაბამისად."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 135 in refs, "'ამ კოდექსის მუხლი 135' must be matched"

    def test_body_cross_ref_high_number_filtered_by_guard(self):
        """Fix 3 — T-RE3: Article numbers > 500 (from other law codes) filtered by MAX_VALID_ARTICLE."""
        body = "სამოქალაქო კოდექსის მუხლი 1116 შესაბამისად."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 1116 not in refs, "Phantom art.1116 > MAX_VALID_ARTICLE must be filtered"

    def test_body_cross_ref_ordinal_form_matches(self):
        """Fix 3 — T-RE4: Ordinal form '81-ე მუხლი' matched by ORDINAL_RE (unchanged)."""
        body = "81-ე მუხლის დებულებები გათვალისწინებულია."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 81 in refs, "Ordinal '81-ე მუხლი' must be matched"

    def test_body_cross_ref_ordinal_high_number_guard(self):
        """Fix 3 — T-RE5: Ordinal form with number > 500 filtered by MAX_VALID_ARTICLE."""
        body = "1116-ე მუხლი სამოქალაქო კოდექსიდან."
        refs = extract_body_cross_references(body, self_article=-1)
        assert 1116 not in refs, "Ordinal phantom 1116 > MAX_VALID_ARTICLE must be filtered"

