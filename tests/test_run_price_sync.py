"""Regression tests for the ordered scrape-first RCJ price-sync job."""

import pytest

from scripts.run_price_sync import refresh_prices_or_raise


class _FakeManager:
    results = {}

    def run_all(self):
        return self.results


def test_refresh_prices_returns_fuji_row_count(monkeypatch):
    _FakeManager.results = {"FujiCardShop": [{"price": 100}, {"price": 200}]}
    monkeypatch.setattr(
        "app.scrapers.scraper_manager.ScraperManager", _FakeManager
    )

    assert refresh_prices_or_raise() == 2


def test_refresh_prices_refuses_stale_report(monkeypatch):
    _FakeManager.results = {"FujiCardShop": []}
    monkeypatch.setattr(
        "app.scrapers.scraper_manager.ScraperManager", _FakeManager
    )

    with pytest.raises(RuntimeError, match="refusing to sync or send a stale report"):
        refresh_prices_or_raise()
