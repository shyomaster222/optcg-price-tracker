"""
app/scrapers/base_scraper.py

Abstract base class for all OPTCG price scrapers.

Key improvements in this revision
----------------------------------
1. Retry logic with exponential backoff (up to MAX_RETRIES attempts).
2. Rotating / updated User-Agent pool (Chrome 124 strings, mid-2024).
3. ScraperStatus dataclass for structured health tracking.
4. Price validation via app.utils.price_validator before persisting.
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3
BACKOFF_FACTOR: float = 1.5     # wait 1.5 s, 2.25 s, 3.375 s …
RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
REQUEST_TIMEOUT: int = 30       # seconds

# Updated Chrome 124 / mid-2024 user-agent strings
USER_AGENTS: List[str] = [
    # Chrome 124 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    # Chrome 124 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    # Chrome 124 – Linux
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    # Firefox 125 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Safari 17 – macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.4 Safari/605.1.15",
    # Edge 124 – Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


# ---------------------------------------------------------------------------
# Scraper health / status dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScraperStatus:
    name: str
    last_run: Optional[datetime] = None
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    consecutive_failures: int = 0
    total_runs: int = 0
    total_successes: int = 0
    total_failures: int = 0
    recent_errors: List[str] = field(default_factory=list)

    _MAX_RECENT_ERRORS: int = field(default=10, init=False, repr=False)

    def record_success(self) -> None:
        self.last_run = self.last_success = datetime.utcnow()
        self.consecutive_failures = 0
        self.total_runs += 1
        self.total_successes += 1

    def record_failure(self, error: str) -> None:
        self.last_run = self.last_failure = datetime.utcnow()
        self.consecutive_failures += 1
        self.total_runs += 1
        self.total_failures += 1
        self.recent_errors.append(f"{datetime.utcnow().isoformat()} {error}")
        if len(self.recent_errors) > self._MAX_RECENT_ERRORS:
            self.recent_errors = self.recent_errors[-self._MAX_RECENT_ERRORS :]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "last_run": self.last_run,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "consecutive_failures": self.consecutive_failures,
            "total_runs": self.total_runs,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "recent_errors": list(self.recent_errors),
        }


# ---------------------------------------------------------------------------
# Base scraper
# ---------------------------------------------------------------------------

class BaseScraper(ABC):
    """
    Abstract base for all scrapers.

    Subclasses must implement:
      - retailer_name (property) – unique string identifier
      - scrape()                 – do the actual work, return list of dicts
    """

    # Override in subclass if the retailer requires a custom set of headers
    EXTRA_HEADERS: Dict[str, str] = {}

    def __init__(self) -> None:
        self._status = ScraperStatus(name=self.retailer_name)
        self._session: Optional[requests.Session] = None

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def retailer_name(self) -> str:  # pragma: no cover
        """Unique, human-readable name, e.g. 'PVPShoppe'."""

    @abstractmethod
    def scrape(self) -> List[dict]:  # pragma: no cover
        """
        Perform the scrape and return a list of raw price dicts.

        Each dict should contain at minimum:
          {"card_id": int, "price": float, "currency": str, "in_stock": bool}
        """

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get_session(self) -> requests.Session:
        """Return a requests Session with retry / backoff pre-configured."""
        if self._session is not None:
            return self._session

        session = requests.Session()

        retry = Retry(
            total=MAX_RETRIES,
            backoff_factor=BACKOFF_FACTOR,
            status_forcelist=RETRY_STATUS_CODES,
            allowed_methods=["GET", "HEAD", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        self._session = session
        return session

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
        headers.update(self.EXTRA_HEADERS)
        return headers

    def fetch(self, url: str, **kwargs) -> requests.Response:
        """
        Fetch *url* with retry / timeout / random user-agent.

        Raises requests.HTTPError on 4xx/5xx after all retries are exhausted.
        """
        session = self._get_session()
        headers = self._get_headers()
        response = session.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        response.raise_for_status()
        return response

    # ------------------------------------------------------------------
    # Run wrapper  (records status, validates prices)
    # ------------------------------------------------------------------

    def run(self) -> List[dict]:
        """
        Execute :meth:`scrape`, record status, and return results.

        Validates each price with :func:`app.utils.price_validator.validate_price`
        before passing it downstream; anomalous prices are logged and skipped.
        """
        from app.utils.price_validator import validate_price_for_card

        try:
            results = self.scrape()
        except Exception as exc:  # pylint: disable=broad-except
            self._status.record_failure(str(exc))
            logger.error("%s scrape failed: %s", self.retailer_name, exc, exc_info=True)
            return []

        # Validate prices and filter out anomalies
        clean: List[dict] = []
        for item in results:
            card_id = item.get("card_id")
            price_usd = item.get("price_usd") or item.get("price")
            if card_id is not None and price_usd is not None:
                vr = validate_price_for_card(card_id, float(price_usd))
                if vr.is_anomaly:
                    logger.warning(
                        "%s: skipping anomalous price for card_id=%s: %s",
                        self.retailer_name,
                        card_id,
                        vr.reasons,
                    )
                    continue
            clean.append(item)

        self._status.record_success()
        return clean

    # ------------------------------------------------------------------
    # Status access
    # ------------------------------------------------------------------

    @property
    def status(self) -> ScraperStatus:
        return self._status

    def get_status(self) -> dict:
        return self._status.to_dict()
