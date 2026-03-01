"""
app/tasks/archival.py

Database archival and cleanup task.

Strategy
--------
- Prices older than ARCHIVE_AFTER_DAYS (default 90) are moved to the
  `price_archive` table.
- Prices older than DELETE_AFTER_DAYS (default 365) are hard-deleted
  from the archive.
- The task is idempotent and safe to run multiple times.
- Intended to be scheduled weekly via APScheduler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app.extensions import db

logger = logging.getLogger(__name__)

ARCHIVE_AFTER_DAYS: int = 90
DELETE_AFTER_DAYS: int = 365


_CREATE_ARCHIVE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS price_archive (
    id               INTEGER PRIMARY KEY,
    product_id       INTEGER,
    retailer_id      INTEGER,
    price            NUMERIC(10, 2),
    price_usd        NUMERIC(10, 2),
    currency         TEXT,
    in_stock         INTEGER,
    scraped_at       DATETIME,
    archived_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_archive_table() -> None:
    db.session.execute(text(_CREATE_ARCHIVE_TABLE_SQL))
    db.session.commit()


def archive_old_prices(archive_after_days: int = ARCHIVE_AFTER_DAYS) -> int:
    _ensure_archive_table()
    cutoff = datetime.utcnow() - timedelta(days=archive_after_days)

    insert_sql = text("""
        INSERT OR IGNORE INTO price_archive
            (id, product_id, retailer_id, price, price_usd,
             currency, in_stock, scraped_at)
        SELECT id, product_id, retailer_id, price, price_usd,
               currency, in_stock, scraped_at
        FROM   price_history
        WHERE  scraped_at < :cutoff
    """)
    db.session.execute(insert_sql, {"cutoff": cutoff})

    delete_sql = text("""
        DELETE FROM price_history
        WHERE  scraped_at < :cutoff
    """)
    result = db.session.execute(delete_sql, {"cutoff": cutoff})
    db.session.commit()

    moved = result.rowcount
    logger.info("Archived %d price rows older than %s", moved, cutoff.date())
    return moved


def purge_old_archive(delete_after_days: int = DELETE_AFTER_DAYS) -> int:
    _ensure_archive_table()
    cutoff = datetime.utcnow() - timedelta(days=delete_after_days)

    purge_sql = text("""
        DELETE FROM price_archive
        WHERE  scraped_at < :cutoff
    """)
    result = db.session.execute(purge_sql, {"cutoff": cutoff})
    db.session.commit()

    deleted = result.rowcount
    logger.info("Purged %d rows from price_archive older than %s", deleted, cutoff.date())
    return deleted


def run_archival_task() -> dict:
    moved = archive_old_prices()
    purged = purge_old_archive()
    summary = {"archived": moved, "purged": purged}
    logger.info("Archival task complete: %s", summary)
    return summary
