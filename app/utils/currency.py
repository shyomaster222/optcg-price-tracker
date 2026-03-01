"""
app/utils/currency.py

Live currency conversion with in-memory caching (24-hour TTL).
Primary source: https://api.exchangerate-api.com/v4/latest/USD
Falls back to hardcoded rates if the API is unavailable.
Thread-safe via threading.Lock.
"""

import logging
import threading
import time
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback / seed rates  (1 unit of foreign currency → USD)
# ---------------------------------------------------------------------------
FALLBACK_RATES: Dict[str, float] = {
    "JPY": 0.0067,   # ~149 JPY per USD
    "CAD": 0.74,
    "EUR": 1.08,
    "GBP": 1.27,
    "USD": 1.0,
}

# Cache TTL: 24 hours expressed in seconds
_CACHE_TTL_SECONDS = 86_400

# Exchange-rate API endpoint (free tier, no key required)
_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"


class _RateCache:
    """Thread-safe in-memory cache for exchange rates."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # rates[currency] = USD equivalent of 1 unit of that currency
        self._rates: Dict[str, float] = dict(FALLBACK_RATES)
        self._fetched_at: Optional[float] = None  # epoch seconds

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_stale(self) -> bool:
        if self._fetched_at is None:
            return True
        return (time.monotonic() - self._fetched_at) >= _CACHE_TTL_SECONDS

    def _fetch_from_api(self) -> Dict[str, float]:
        """
        Fetch latest rates from the free exchangerate-api endpoint.

        The API returns rates as  { "USD": 1, "JPY": 149.5, ... }  meaning
        "how many units of that currency per 1 USD".  We invert them so our
        internal representation is always "USD per 1 unit of foreign currency".
        """
        resp = requests.get(_API_URL, timeout=10)
        resp.raise_for_status()
        raw: Dict[str, float] = resp.json()["rates"]
        return {k: 1.0 / v for k, v in raw.items() if v > 0}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_rates(self) -> Dict[str, float]:
        """Return a snapshot of current rates, refreshing if stale."""
        with self._lock:
            if self._is_stale():
                try:
                    fresh = self._fetch_from_api()
                    self._rates = fresh
                    self._fetched_at = time.monotonic()
                    logger.info("Currency rates refreshed from API")
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        "Failed to fetch exchange rates (%s); using cached/fallback values",
                        exc,
                    )
                    # Keep whatever we have (either stale API data or FALLBACK_RATES)
                    if self._fetched_at is None:
                        self._rates = dict(FALLBACK_RATES)
            return dict(self._rates)

    def convert_to_usd(self, amount: float, currency: str) -> float:
        """
        Convert *amount* in *currency* to USD.

        Parameters
        ----------
        amount:   value in the source currency
        currency: ISO-4217 code, e.g. "JPY", "CAD"

        Returns
        -------
        float: equivalent amount in USD, rounded to 4 decimal places.
               Returns the original amount unchanged if the currency code
               is unknown.
        """
        if currency == "USD":
            return round(amount, 4)
        rates = self.get_rates()
        rate = rates.get(currency.upper())
        if rate is None:
            logger.warning("Unknown currency %r; returning amount unchanged", currency)
            return round(amount, 4)
        return round(amount * rate, 4)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_cache = _RateCache()


def convert_to_usd(amount: float, currency: str) -> float:
    """Module-level convenience wrapper around the singleton cache."""
    return _cache.convert_to_usd(amount, currency)


def get_current_rates() -> Dict[str, float]:
    """Return a snapshot of all currently cached exchange rates."""
    return _cache.get_rates()
