"""
tests/test_currency.py

Unit tests for the currency conversion module.

Covers:
  - convert_to_usd()        -- happy path, unknown currency, USD pass-through
  - get_current_rates()     -- returns a dict with at least USD
  - _RateCache internals    -- cache staleness, API fetch, fallback on failure
  - Thread safety           -- concurrent calls do not corrupt the cache
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.utils.currency import (
    FALLBACK_RATES,
    _RateCache,
    convert_to_usd,
    get_current_rates,
)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _fresh_cache() -> _RateCache:
    """Return a brand-new _RateCache instance (never fetched)."""
    return _RateCache()


def _pre_populated_cache(rates: dict, age_seconds: float = 0) -> _RateCache:
    """
    Return a _RateCache already populated with *rates*.
    If *age_seconds* > 0, the cache's timestamp is backdated so staleness
    checks will treat it as old.
    """
    cache = _RateCache()
    with cache._lock:
        cache._rates = dict(rates)
        cache._fetched_at = time.monotonic() - age_seconds
    return cache


# ---------------------------------------------------------------------------
# convert_to_usd  (module-level singleton)
# ---------------------------------------------------------------------------

class TestConvertToUsd:
    """Tests for the module-level convert_to_usd() convenience function."""

    def test_usd_returns_same_amount(self):
        assert convert_to_usd(100.0, "USD") == 100.0

    def test_jpy_converts_to_usd(self):
        # 1 JPY ~ 0.0067 USD in FALLBACK_RATES -> 7800 JPY ~ 52.26 USD
        result = convert_to_usd(7800, "JPY")
        assert 40 < result < 70, f"Expected ~52 USD, got {result}"

    def test_cad_converts_to_usd(self):
        # 1 CAD ~ 0.74 USD in FALLBACK_RATES -> 100 CAD ~ 74 USD
        result = convert_to_usd(100, "CAD")
        assert 60 < result < 90, f"Expected ~74 USD, got {result}"

    def test_unknown_currency_returns_original_amount(self):
        # Unknown currency code -> amount returned unchanged
        result = convert_to_usd(50.0, "XYZ")
        assert result == 50.0

    def test_result_rounded_to_4_decimal_places(self):
        result = convert_to_usd(100.0, "JPY")
        # Check it has at most 4 decimal places
        assert result == round(result, 4)

    def test_case_insensitive_currency_code(self):
        lower = convert_to_usd(100, "jpy")
        upper = convert_to_usd(100, "JPY")
        assert lower == upper


# ---------------------------------------------------------------------------
# get_current_rates
# ---------------------------------------------------------------------------

class TestGetCurrentRates:
    """Tests for the module-level get_current_rates() function."""

    def test_returns_dict(self):
        rates = get_current_rates()
        assert isinstance(rates, dict)

    def test_usd_rate_is_one(self):
        rates = get_current_rates()
        assert rates.get("USD") == pytest.approx(1.0)

    def test_contains_fallback_currencies(self):
        rates = get_current_rates()
        for currency in FALLBACK_RATES:
            assert currency in rates, f"Missing currency: {currency}"


# ---------------------------------------------------------------------------
# _RateCache internals
# ---------------------------------------------------------------------------

class TestRateCacheInternals:
    """Tests for _RateCache private/internal behaviour."""

    # -- Staleness -----------------------------------------------------------

    def test_fresh_cache_is_stale(self):
        cache = _fresh_cache()
        assert cache._is_stale() is True

    def test_just_fetched_cache_is_not_stale(self):
        cache = _pre_populated_cache(FALLBACK_RATES, age_seconds=0)
        assert cache._is_stale() is False

    def test_cache_becomes_stale_after_ttl(self):
        # Backdate by slightly more than 24 h
        from app.utils.currency import _CACHE_TTL_SECONDS
        cache = _pre_populated_cache(FALLBACK_RATES, age_seconds=_CACHE_TTL_SECONDS + 1)
        assert cache._is_stale() is True

    # -- API fetch success ---------------------------------------------------

    def test_get_rates_calls_api_when_stale(self):
        cache = _fresh_cache()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "rates": {"USD": 1.0, "JPY": 150.0, "CAD": 1.35}
        }
        mock_response.raise_for_status = MagicMock()

        with patch("app.utils.currency.requests.get", return_value=mock_response) as mock_get:
            rates = cache.get_rates()
            mock_get.assert_called_once()
            # Inverted: 1/150 for JPY
            assert rates["JPY"] == pytest.approx(1 / 150, rel=1e-4)
            assert rates["CAD"] == pytest.approx(1 / 1.35, rel=1e-4)

    def test_get_rates_does_not_call_api_when_fresh(self):
        cache = _pre_populated_cache(FALLBACK_RATES, age_seconds=0)
        with patch("app.utils.currency.requests.get") as mock_get:
            cache.get_rates()
            mock_get.assert_not_called()

    # -- API fetch failure / fallback ----------------------------------------

    def test_get_rates_falls_back_to_hardcoded_on_network_error(self):
        cache = _fresh_cache()
        with patch(
            "app.utils.currency.requests.get",
            side_effect=Exception("Network error")
        ):
            rates = cache.get_rates()
            # Should fall back to FALLBACK_RATES
            assert rates["JPY"] == pytest.approx(FALLBACK_RATES["JPY"], rel=1e-4)

    def test_get_rates_falls_back_to_stale_cache_on_error(self):
        """If the cache already has stale data and the refresh fails,
        it should keep the stale data rather than resetting to FALLBACK_RATES."""
        stale_rates = {"USD": 1.0, "JPY": 0.006, "CAD": 0.70}
        from app.utils.currency import _CACHE_TTL_SECONDS
        cache = _pre_populated_cache(stale_rates, age_seconds=_CACHE_TTL_SECONDS + 1)
        with patch(
            "app.utils.currency.requests.get",
            side_effect=Exception("API down")
        ):
            rates = cache.get_rates()
            assert rates["JPY"] == pytest.approx(0.006, rel=1e-4)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestRateCacheThreadSafety:
    """Concurrent calls should not corrupt the cache."""

    def test_concurrent_calls_do_not_raise(self):
        cache = _fresh_cache()
        mock_response = MagicMock()
        mock_response.json.return_value = {"rates": {"USD": 1.0, "JPY": 150.0}}
        mock_response.raise_for_status = MagicMock()

        errors = []

        def _call():
            try:
                with patch("app.utils.currency.requests.get", return_value=mock_response):
                    cache.get_rates()
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_call) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"

    def test_concurrent_convert_does_not_raise(self):
        cache = _pre_populated_cache(FALLBACK_RATES, age_seconds=0)
        results = []
        errors = []

        def _convert():
            try:
                results.append(cache.convert_to_usd(7800, "JPY"))
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=_convert) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(results) == 50
        assert all(isinstance(r, float) for r in results)
