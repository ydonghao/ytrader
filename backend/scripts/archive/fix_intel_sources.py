"""Fix intel_sources data inconsistencies.

Fixes:
1. Rename old "newsnow" row → split into "newsnow_finance" + "newsnow_hotlist"
   (two NewsnowProvider instances now use distinct names).
2. Normalize "FinnHub" → "finnhub" (lowercase consistency).

Usage:
    python scripts/fix_intel_sources.py
"""

import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from loguru import logger

from src.infra.database.sql_engine.dsn import get_dsn


def fix_intel_sources() -> None:
    dsn = get_dsn()
    conn = psycopg2.connect(dsn)
    conn.autocommit = True

    try:
        cur = conn.cursor()

        # ── 1. Split "newsnow" into "newsnow_finance" + "newsnow_hotlist" ──
        cur.execute(
            "SELECT name, category FROM intel_sources WHERE name = 'newsnow'"
        )
        rows = cur.fetchall()

        if rows:
            old_category = rows[0][1]
            logger.info(
                f"Found old 'newsnow' row (category={old_category})"
            )

            # Create both new rows (one may have been overwritten)
            for name, cat in [
                ("newsnow_finance", "finance"),
                ("newsnow_hotlist", "hotlist"),
            ]:
                cur.execute(
                    """
                    INSERT INTO intel_sources
                        (name, provider_type, category, is_active,
                         fetch_count, error_count)
                    VALUES (%s, 'api', %s, true, 0, 0)
                    ON CONFLICT (name) DO NOTHING
                    """,
                    (name, cat),
                )
                logger.info(f"Created '{name}' row")

            # Delete old row
            cur.execute(
                "DELETE FROM intel_sources WHERE name = 'newsnow'"
            )
            logger.info("Deleted old 'newsnow' row")
        else:
            logger.info("No 'newsnow' row to fix (already migrated)")

        # ── 2. Normalize "FinnHub" → "finnhub" ──
        cur.execute(
            "SELECT name FROM intel_sources WHERE name = 'FinnHub'"
        )
        if cur.fetchone():
            cur.execute(
                """
                UPDATE intel_sources
                SET name = 'finnhub'
                WHERE name = 'FinnHub'
                """
            )
            logger.info("Renamed 'FinnHub' → 'finnhub'")
        else:
            logger.info(
                "No 'FinnHub' row to fix "
                "(already renamed or never existed)"
            )

        cur.close()
        logger.info("Migration complete")

    finally:
        conn.close()


if __name__ == "__main__":
    fix_intel_sources()
