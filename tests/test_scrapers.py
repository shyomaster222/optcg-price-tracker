"""
tests/test_scrapers.py

Unit tests for scraper parsing logic and URL builders.

All network I/O is mocked -- these tests exercise only the HTML-parsing code
and URL-generation logic without hitting any real web servers.
"""

import pytest
from unittest.mock import MagicMock
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_product(set_code="OP-01", product_type="box"):
    """Return a lightweight mock product object."""
    product = MagicMock()
    product.set_code = set_code
    product.product_type = product_type
    return product


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def _retailer_config(name="Test Retailer", base_url="https://example.com"):
    return {
        "name": name,
        "base_url": base_url,
        "min_delay_seconds": 0,
        "max_delay_seconds": 0,
        "requests_per_minute": 60,
        "selectors": {},
    }


# ---------------------------------------------------------------------------
# AmazonJPScraper
# ---------------------------------------------------------------------------

AMAZON_JP_SEARCH_HTML = """
<html><body>
  <div data-component-type="s-search-result">
    <h2><a href="/dp/B0001"><span>One Piece Card Game OP-01 BOX Booster</span></a></h2>
    <span class="a-price-whole">7,800</span>
    <span class="a-price-fraction">00</span>
  </div>
</body></html>
"""

AMAZON_JP_NO_MATCH_HTML = """
<html><body>
  <div data-component-type="s-search-result">
    <h2><a href="/dp/B0002"><span>Some Other Product OP-99</span></a></h2>
    <span class="a-price-whole">3,000</span>
  </div>
</body></html>
"""

AMAZON_JP_MALFORMED_HTML = """
<html><body>
  <div data-component-type="s-search-result">
    <!-- title element is missing entirely -->
    <span class="a-price-whole">INVALID</span>
  </div>
</body></html>
"""


class TestAmazonJPScraper:
    """Tests for AmazonJPScraper parsing and URL construction."""

    @pytest.fixture
    def scraper(self):
        from app.scrapers.amazon_jp_scraper import AmazonJPScraper
        return AmazonJPScraper(_retailer_config("Amazon Japan", "https://www.amazon.co.jp"))

    def test_parse_price_returns_price_and_currency(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(AMAZON_JP_SEARCH_HTML), product)
        assert result is not None
        assert result["price"] == 7800
        assert result["currency"] == "JPY"

    def test_parse_price_no_matching_product_returns_none(self, scraper):
        """No result matches OP-01 -- should return None."""
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(AMAZON_JP_NO_MATCH_HTML), product)
        assert result is None

    def test_parse_price_empty_html_returns_none(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup("<html><body></body></html>"), product)
        assert result is None

    def test_parse_price_malformed_html_returns_none(self, scraper):
        """Malformed HTML (missing title span) should not raise -- returns None."""
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(AMAZON_JP_MALFORMED_HTML), product)
        assert result is None

    def test_build_search_url_box(self, scraper):
        product = _make_product("OP-01", "box")
        url = scraper.build_search_url(product)
        assert "OP-01" in url
        assert "BOX" in url or "%2BBOX" in url or "+" in url

    def test_build_search_url_case(self, scraper):
        product = _make_product("OP-01", "case")
        url = scraper.build_search_url(product)
        assert "OP-01" in url
        assert "amazon.co.jp" in url


# ---------------------------------------------------------------------------
# TCGRepublicScraper
# ---------------------------------------------------------------------------

TCGREPUBLIC_SEARCH_HTML = """
<html><body>
  <div class="product_unit">
    <div class="product_name"><a href="/product/op01box">ONE PIECE OP-01 Booster Box</a></div>
    <span class="figure">$54.99</span>
    <button class="add_to_cart_button">Add to Cart</button>
  </div>
</body></html>
"""

TCGREPUBLIC_NO_MATCH_HTML = """
<html><body>
  <div class="product_unit">
    <div class="product_name"><a href="/product/op99box">ONE PIECE OP-99 Booster Box</a></div>
    <span class="figure">$30.00</span>
  </div>
</body></html>
"""

TCGREPUBLIC_MALFORMED_HTML = """
<html><body>
  <div class="product_unit">
    <!-- No product_name or figure elements -->
    <p>Something else</p>
  </div>
</body></html>
"""


class TestTCGRepublicScraper:
    """Tests for TCGRepublicScraper parsing and URL construction."""

    @pytest.fixture
    def scraper(self):
        from app.scrapers.tcgrepublic_scraper import TCGRepublicScraper
        return TCGRepublicScraper(_retailer_config("TCGRepublic", "https://tcgrepublic.com"))

    def test_parse_price_returns_price_and_currency(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(TCGREPUBLIC_SEARCH_HTML), product)
        assert result is not None
        assert result["price"] == pytest.approx(54.99, rel=1e-3)
        assert result["currency"] == "USD"

    def test_parse_price_no_matching_product_returns_none(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(TCGREPUBLIC_NO_MATCH_HTML), product)
        assert result is None

    def test_parse_price_empty_html_returns_none(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup("<html><body></body></html>"), product)
        assert result is None

    def test_parse_price_malformed_html_returns_none(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(TCGREPUBLIC_MALFORMED_HTML), product)
        assert result is None

    def test_build_search_url_box(self, scraper):
        product = _make_product("OP-01", "box")
        url = scraper.build_search_url(product)
        assert "OP-01" in url or "op-01" in url.lower()
        assert "tcgrepublic.com" in url

    def test_build_search_url_case(self, scraper):
        product = _make_product("OP-02", "case")
        url = scraper.build_search_url(product)
        assert "OP-02" in url or "op-02" in url.lower()
        assert "Case" in url or "case" in url.lower() or "CASE" in url


# ---------------------------------------------------------------------------
# EbayScraper
# ---------------------------------------------------------------------------

EBAY_SEARCH_HTML = """
<html><body>
  <ul>
    <li class="s-item">
      <div class="s-item__title">Shop on eBay</div>
      <span class="s-item__price">$0.99</span>
    </li>
    <li class="s-item">
      <div class="s-item__title">One Piece Card Game OP-01 Japanese Booster Box</div>
      <span class="s-item__price">$55.00</span>
    </li>
    <li class="s-item">
      <div class="s-item__title">ONE PIECE OP-01 JP Booster Box Sealed</div>
      <span class="s-item__price">$58.00</span>
    </li>
  </ul>
</body></html>
"""

EBAY_NO_MATCH_HTML = """
<html><body>
  <ul>
    <li class="s-item">
      <div class="s-item__title">Shop on eBay</div>
    </li>
    <li class="s-item">
      <div class="s-item__title">Dragon Ball OP-99 Booster Box</div>
      <span class="s-item__price">$40.00</span>
    </li>
  </ul>
</body></html>
"""

EBAY_MALFORMED_HTML = """
<html><body>
  <ul>
    <li class="s-item"><!-- no title or price children --></li>
  </ul>
</body></html>
"""


class TestEbayScraper:
    """Tests for EbayScraper HTML parsing and URL construction."""

    @pytest.fixture
    def scraper(self):
        from app.scrapers.ebay_scraper import EbayScraper
        return EbayScraper(_retailer_config("eBay", "https://www.ebay.com"))

    def test_parse_price_returns_price_and_currency(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(EBAY_SEARCH_HTML), product)
        assert result is not None
        assert 50 < result["price"] < 70
        assert result["currency"] == "USD"

    def test_parse_price_no_matching_product_returns_none(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(EBAY_NO_MATCH_HTML), product)
        assert result is None

    def test_parse_price_empty_html_returns_none(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup("<html><body></body></html>"), product)
        assert result is None

    def test_parse_price_malformed_html_returns_none(self, scraper):
        product = _make_product("OP-01", "box")
        result = scraper.parse_price(_soup(EBAY_MALFORMED_HTML), product)
        assert result is None

    def test_build_search_url_box(self, scraper):
        product = _make_product("OP-01", "box")
        url = scraper.build_search_url(product)
        assert "ebay.com" in url
        assert "OP-01" in url or "op-01" in url.lower() or "OP-01" in url.replace("+", " ")

    def test_build_search_url_case(self, scraper):
        product = _make_product("OP-03", "case")
        url = scraper.build_search_url(product)
        assert "OP-03" in url or "op-03" in url.lower() or "OP-03" in url.replace("+", " ")
        assert "Case" in url or "case" in url.lower() or "CASE" in url.replace("%20", " ").replace("+", " ").upper()


# ---------------------------------------------------------------------------
# PriceValidator
# ---------------------------------------------------------------------------

class TestPriceValidator:
    """
    Tests for app.utils.price_validator.PriceValidator.
    """

    @pytest.fixture
    def validator(self):
        from app.utils.price_validator import PriceValidator
        return PriceValidator()

    def test_valid_price_passes(self, validator):
        is_valid, reason = validator.validate_price(
            product_id=1, retailer_id=1,
            price=50.0, currency="USD", product_type="box"
        )
        assert is_valid is True
        assert reason == ""

    def test_valid_jpy_price_passes(self, validator):
        is_valid, _ = validator.validate_price(
            product_id=1, retailer_id=1,
            price=7800, currency="JPY", product_type="box"
        )
        assert is_valid is True

    def test_zero_price_fails(self, validator):
        is_valid, reason = validator.validate_price(
            product_id=1, retailer_id=1,
            price=0, currency="USD", product_type="box"
        )
        assert is_valid is False
        assert reason != ""

    def test_negative_price_fails(self, validator):
        is_valid, reason = validator.validate_price(
            product_id=1, retailer_id=1,
            price=-10.0, currency="USD", product_type="box"
        )
        assert is_valid is False

    def test_price_below_absolute_minimum_fails(self, validator):
        is_valid, _ = validator.validate_price(
            product_id=1, retailer_id=1,
            price=0.001, currency="USD", product_type="box"
        )
        assert is_valid is False

    def test_price_above_absolute_maximum_fails(self, validator):
        is_valid, _ = validator.validate_price(
            product_id=1, retailer_id=1,
            price=50000, currency="USD", product_type="box"
        )
        assert is_valid is False
