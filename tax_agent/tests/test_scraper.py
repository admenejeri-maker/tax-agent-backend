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
    DEFINITIONS_ARTICLE_NUMBER,
    KARI_RE,
    TAVI_RE,
    USER_AGENT,
    detect_exception_article,
    detect_version,
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
