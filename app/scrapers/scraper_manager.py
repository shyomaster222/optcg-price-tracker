"""
app/scrapers/scraper_manager.py

Orchestrates all scrapers.

Key improvements in this revision
----------------------------------
1. Parallel execution via ThreadPoolExecutor.
2. Per-scraper error isolation  – one failed scraper doesn’t abort others.
3. Exposed get_all_statuses() for the health dashboard.
4. Seeds / updates the DB with scraped prices using PriceService.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from app.scrapers.base_scraper import BaseScraper
from app.scrapers.pvpshoppe_scraper import PVPShoppeScraper
from app.scrapers.fptradingcards_scraper import FPTradingCardsScraper
from app.scrapers.rarecardsjapan_scraper import RareCardsJapanScraper
from app.services.price_service import PriceService

logger = logging.getLogger(__name__)

# Maximum number of scrapers to run concurrently
_MAX_WORKERS: int = 4


class ScraperManager:
    """
    Manages instantiation and parallel execution of all registered scrapers.
    """

    def __init__(self, max_workers: int = _MAX_WORKERS) -> None:
        self._scrapers: List[BaseScraper] = [
            PVPShoppeScraper(),
            FPTradingCardsScraper(),
            RareCardsJapanScraper(),
        ]
        self._max_workers = max_workers

    # ------------------------------------------------------------------
    # Core run methods
    # ------------------------------------------------------------------

    def run_all(self) -> Dict[str, List[dict]]:
        """
        Run every scraper in parallel and persist results.

        Returns a dict mapping retailer_name → list of raw result dicts.
        """
        results: Dict[str, List[dict]] = {}

        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            future_to_scraper = {
                pool.submit(self._run_one, scraper): scraper
                for scraper in self._scrapers
            }
            for future in as_completed(future_to_scraper):
                scraper = future_to_scraper[future]
                try:
                    name, data = future.result()
                    results[name] = data
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error(
                        "ScraperManager: unhandled error from %s: %s",
                        scraper.retailer_name,
                        exc,
                        exc_info=True,
                    )
                    results[scraper.retailer_name] = []

        return results

    def _run_one(self, scraper: BaseScraper):
        """
        Run a single scraper, persist its results, and return
        (retailer_name, results_list).
        """
        name = scraper.retailer_name
        logger.info("Starting scraper: %s", name)
        results = scraper.run()   # run() already handles exceptions internally

        if results:
            try:
                svc = PriceService()
                svc.bulk_upsert(results)
                logger.info("%s: persisted %d price records", name, len(results))
            except Exception as exc:  # pylint: disable=broad-except
                logger.error(
                    "%s: failed to persist results: %s", name, exc, exc_info=True
                )
        else:
            logger.warning("%s: no results returned", name)

        return name, results

    # ------------------------------------------------------------------
    # Status / health
    # ------------------------------------------------------------------

    def get_all_statuses(self) -> Dict[str, dict]:
        """
        Return a dict mapping retailer_name → status dict for every
        registered scraper.
        """
        return {s.retailer_name: s.get_status() for s in self._scrapers}

    def get_scraper(self, name: str) -> Optional[BaseScraper]:
        """Return the scraper instance for *name*, or None."""
        for s in self._scrapers:
            if s.retailer_name == name:
                return s
        return None

    def add_scraper(self, scraper: BaseScraper) -> None:
        """Dynamically register a new scraper at runtime."""
        self._scrapers.append(scraper)
        logger.info("ScraperManager: registered new scraper %s", scraper.retailer_name)
