"""
Tax Agent Models Package
========================

Pydantic models + MongoDB CRUD stores for:
- TaxArticle: Georgian Tax Code articles (309 articles)
- Definition: Legal term definitions from Article 8

Adapted from v5 implementation plan (Fat Model pattern).
"""

from .tax_article import TaxArticle, TaxArticleStore, ArticleStatus
from .definition import Definition, DefinitionStore

__all__ = [
    "TaxArticle",
    "TaxArticleStore",
    "ArticleStatus",
    "Definition",
    "DefinitionStore",
]
