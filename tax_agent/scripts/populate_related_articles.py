#!/usr/bin/env python3
"""
One-time migration: backfill `related_articles` from body text.

Usage:
    python scripts/populate_related_articles.py --dry-run   # preview only
    python scripts/populate_related_articles.py              # apply migration

Requires MONGODB_URI env var. Reads DATABASE_NAME (default: "georgian_tax_db").
Idempotent — safe to re-run.
"""

import argparse
import os
import re
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Allow imports from tax_agent root
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from pymongo import MongoClient, UpdateOne  # noqa: E402

BODY_CROSS_REF_RE = re.compile(r"მუხლი\s+(\d+)")
BODY_CROSS_REF_ORDINAL_RE = re.compile(r"(\d+)[-\u2013]?\u10d4?\s*\u10db\u10e3\u10ee\u10da")
MAX_VALID_ARTICLE = 500  # Layer 3: filter phantoms from old body text


def extract_refs_from_body(body: str, self_article: int) -> list[int]:
    """Extract cross-reference article numbers from body text.

    Args:
        body: Article body text.
        self_article: Article number to exclude (self-reference).

    Returns:
        Sorted, deduplicated list of referenced article numbers.
    """
    if not body:
        return []
    refs: set[int] = set()
    for m in BODY_CROSS_REF_RE.findall(body):
        refs.add(int(m))
    for m in BODY_CROSS_REF_ORDINAL_RE.findall(body):
        refs.add(int(m))
    refs.discard(self_article)
    # Layer 3: Filter phantom refs from old concatenated body text
    refs = {r for r in refs if 1 <= r <= MAX_VALID_ARTICLE}
    return sorted(refs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill related_articles from body text."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without modifying the database.",
    )
    args = parser.parse_args()

    # ── Connect ─────────────────────────────────────────────────────────
    mongo_uri = os.environ.get("MONGODB_URI")
    if not mongo_uri:
        print("ERROR: MONGODB_URI environment variable is not set.")
        sys.exit(1)

    mongo_db = os.environ.get("DATABASE_NAME", "georgian_tax_db")
    client: MongoClient = MongoClient(mongo_uri)
    db = client[mongo_db]
    collection = db.tax_articles

    # ── Fetch all articles ──────────────────────────────────────────────
    articles = list(
        collection.find(
            {"status": "active"},
            {"article_number": 1, "body": 1, "related_articles": 1},
        )
    )
    if not articles:
        print("No active articles found. Nothing to migrate.")
        return

    # ── Compute new refs ────────────────────────────────────────────────
    ops: list[UpdateOne] = []
    stats: Counter = Counter()

    for article in articles:
        article_number = article.get("article_number")
        if article_number is None:
            print(f"  WARN: Document {article['_id']} has no article_number, skipping.")
            stats["skipped"] += 1
            continue

        body = article.get("body", "")
        existing_refs = article.get("related_articles", [])
        body_refs = extract_refs_from_body(body, article_number)

        # Merge existing + body-text refs
        merged = sorted(set(existing_refs + body_refs))

        if merged == existing_refs:
            stats["unchanged"] += 1
            continue

        new_count = len(merged) - len(existing_refs)
        stats["updated"] += 1
        stats["new_refs"] += new_count

        if args.dry_run:
            print(
                f"  [DRY RUN] Article {article_number}: "
                f"{existing_refs} → {merged} (+{new_count} refs)"
            )

        ops.append(
            UpdateOne(
                {"_id": article["_id"]},
                {"$set": {"related_articles": merged}},
            )
        )

    # ── Summary ─────────────────────────────────────────────────────────
    print(f"\nMigration summary ({len(articles)} articles):")
    print("-" * 40)
    print(f"  {'Updated':<25} {stats['updated']:>4}")
    print(f"  {'Unchanged':<25} {stats['unchanged']:>4}")
    print(f"  {'Skipped':<25} {stats['skipped']:>4}")
    print(f"  {'New refs added':<25} {stats['new_refs']:>4}")
    print("-" * 40)

    # ── Apply or dry-run ────────────────────────────────────────────────
    if args.dry_run:
        print("\n✅ --dry-run: No changes made to the database.")
        return

    if not ops:
        print("\n✅ No updates needed — all articles already up to date.")
        return

    result = collection.bulk_write(ops, ordered=False)
    print(f"\n✅ Migration complete:")
    print(f"   Matched:  {result.matched_count}")
    print(f"   Modified: {result.modified_count}")

    # ── Post-migration verification ─────────────────────────────────────
    pipeline = [
        {"$match": {"related_articles": {"$exists": True, "$ne": []}}},
        {"$project": {"article_number": 1, "ref_count": {"$size": "$related_articles"}}},
        {"$group": {"_id": None, "total_with_refs": {"$sum": 1}, "avg_refs": {"$avg": "$ref_count"}}},
    ]
    print("\nPost-migration verification:")
    for doc in collection.aggregate(pipeline):
        print(f"  Articles with refs: {doc['total_with_refs']}")
        print(f"  Avg refs per article: {doc['avg_refs']:.1f}")


if __name__ == "__main__":
    main()
