"""
app/tasks/archival.py

Database archival and cleanup task.

Strategy
--------
- Prices older than ARCHIVE_AFTER_DAYS (default 90) are moved to the
  `price_archive` table (which mirrors `prices` structure).
- Prices older than DELETE_AFTER_DAYS (default 365) are hard-deleted
  from the archive as well.
- The task is idempotent and safe to run multiple times.
- Intended to be scheduled weekly via APScheduler.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

from app import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------
ARCHIVE_AFTER_DAYS: int = 90    # move prices older than this to archive table
DELETE_AFTER_DAYS: int = 365    # hard-delete archive rows older than this


# ---------------------------------------------------------------------------
# Archive table DDL  (created lazily if it doesn’t exist)
# ---------------------------------------------------------------------------

_CREATE_ARCHIVE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS price_archive (
    id               INTEGER PRIMARY KEY,
    card_id          INTEGER,
    retailer         TEXT,
    price_usd        REAL,
    original_price   REAL,
    original_currency TEXT,
    in_stock         INTEGER,
    scraped_at       DATETIME,
    archived_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_archive_table() -> None:
    """Create the archive table if it doesn’t already exist."""
    db.session.execute(text(_CREATE_ARCHIVE_TABLE_SQL))
    db.session.commit()


# ---------------------------------------------------------------------------
# Core archival logic
# ---------------------------------------------------------------------------

def archive_old_prices(archive_after_days: int = ARCHIVE_AFTER_DAYS) -> int:
    """
    Copy prices older than *archive_after_days* from `prices` to
    `price_archive`, then delete them from `prices`.

    Returns the number of rows moved.
    """
    _ensure_archive_table()
    cutoff = datetime.utcnow() - timedelta(days=archive_after_days)

    # Insert into archive
    insert_sql = text("""
        INSERT OR IGNORE INTO price_archive
            (id, card_id, retailer, price_usd, original_price,
             original_currency, in_stock, scraped_at)
        SELECT id, card_id, retailer, price_usd, original_price,
               original_currency, in_stock, scraped_at
        FROM   prices
        WHERE  scraped_at < :cutoff
    """)
    db.session.execute(insert_sql, {"cutoff": cutoff})

    # Delete from live table
    delete_sql = text("""
        DELETE FROM prices
        WHERE  scraped_at < :cutoff
    """)
    result = db.session.execute(delete_sql, {"cutoff": cutoff})
    db.session.commit()

    moved = result.rowcount
    logger.info("Archived %d price rows older than %s", moved, cutoff.date())
    return moved


def purge_old_archive(delete_after_days: int = DELETE_AFTER_DAYS) -> int:
    """
    Hard-delete rows from `price_archive` that are older than
    *delete_after_days*.

    Returns the number of rows deleted.
    """
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


# ---------------------------------------------------------------------------
# Composite task (called by the scheduler)
# ---------------------------------------------------------------------------

def run_archival_task() -> dict:
    """
    Run both archive and purge steps.

    Returns a summary dict suitable for logging or an API response.
    """
    moved = archive_old_prices()
    purged = purge_old_archive()
    summary = {"archived": moved, "purged": purged}
    logger.info("Archival task complete: %s", summary)
    return summary
