#!/usr/bin/env python3
"""
One-time migration: backfill `domain` field on tax_articles.

Usage:
    python scripts/migrate_article_domains.py --dry-run   # preview only
    python scripts/migrate_article_domains.py              # apply migration

Requires MONGODB_URI env var. Reads DATABASE_NAME (default: "georgian_tax_db").
Idempotent — safe to re-run.
"""

import argparse
import os
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Allow imports from tax_agent root
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_ROOT)

from pymongo import MongoClient, UpdateOne  # noqa: E402
from app.services.matsne_scraper import get_domain  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill domain field on tax_articles collection."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print domain distribution without modifying the database.",
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
    articles = list(collection.find({}, {"article_number": 1}))
    if not articles:
        print("No articles found in tax_articles. Nothing to migrate.")
        return

    # ── Compute domains ─────────────────────────────────────────────────
    ops: list[UpdateOne] = []
    distribution: Counter = Counter()

    for article in articles:
        article_number = article.get("article_number")
        if article_number is None:
            print(f"  WARN: Document {article['_id']} has no article_number, skipping.")
            continue

        domain = get_domain(article_number)
        distribution[domain] += 1
        ops.append(
            UpdateOne(
                {"_id": article["_id"]},
                {"$set": {"domain": domain}},
            )
        )

    # ── Print distribution ──────────────────────────────────────────────
    print(f"\nDomain distribution ({len(articles)} articles):")
    print("-" * 40)
    for domain, count in sorted(distribution.items(), key=lambda x: -x[1]):
        print(f"  {domain:<25} {count:>4}")
    print("-" * 40)
    print(f"  {'TOTAL':<25} {sum(distribution.values()):>4}")

    # ── Apply or dry-run ────────────────────────────────────────────────
    if args.dry_run:
        print("\n✅ --dry-run: No changes made to the database.")
        return

    result = collection.bulk_write(ops, ordered=False)
    print(f"\n✅ Migration complete:")
    print(f"   Matched:  {result.matched_count}")
    print(f"   Modified: {result.modified_count}")

    # ── Post-migration verification ─────────────────────────────────────
    pipeline = [
        {"$group": {"_id": "$domain", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    print("\nPost-migration verification (from MongoDB):")
    print("-" * 40)
    for doc in collection.aggregate(pipeline):
        print(f"  {doc['_id']:<25} {doc['count']:>4}")


if __name__ == "__main__":
    main()
