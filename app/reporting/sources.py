"""Read-only Shopify and Google Search Console clients for weekly reporting."""

from __future__ import annotations

import logging
import random
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests


logger = logging.getLogger(__name__)


class ReportSourceError(RuntimeError):
    """A source could not provide trustworthy report data."""


class ShopifyReportClient:
    ORDERS_QUERY = """
    query ReportOrders($after: String, $query: String!) {
      orders(first: 100, after: $after, query: $query, sortKey: PROCESSED_AT) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          name
          processedAt
          createdAt
          test
          unpaid
          cancelledAt
          tags
          sourceName
          app { id name }
          netPaymentSet { shopMoney { amount currencyCode } }
          totalRefundedSet { shopMoney { amount currencyCode } }
          shippingAddress { countryCodeV2 }
          billingAddress { countryCodeV2 }
        }
      }
    }
    """.strip()

    LINE_ITEMS_QUERY = """
    query ReportLineItems($id: ID!, $after: String) {
      order(id: $id) {
        lineItems(first: 250, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes {
            id
            title
            variantTitle
            sku
            quantity
            currentQuantity
            priceAfterAllDiscountsBeforeTaxesSet {
              shopMoney { amount currencyCode }
            }
            product { id title handle }
            variant { id title sku }
          }
        }
      }
    }
    """.strip()

    FIRST_TOUCH_QUERY = """
    query FirstTouches($ids: [ID!]!) {
      nodes(ids: $ids) {
        ... on Order {
          id
          customerJourneySummary {
            ready
            customerOrderIndex
            daysToConversion
            firstVisit {
              landingPage
              referrerUrl
              source
              sourceDescription
              sourceType
              utmParameters { source medium campaign term content }
            }
          }
        }
      }
    }
    """.strip()

    CATALOG_QUERY = """
    query ActiveCatalog($after: String) {
      products(first: 100, after: $after, query: "status:active", sortKey: ID) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          title
          handle
          status
          variants(first: 250) {
            pageInfo { hasNextPage endCursor }
            nodes {
              id
              title
              sku
              price
              inventoryQuantity
              sellableOnlineQuantity
              inventoryPolicy
              availableForSale
            }
          }
        }
      }
    }
    """.strip()

    PRODUCT_VARIANTS_QUERY = """
    query ProductVariants($id: ID!, $after: String) {
      product(id: $id) {
        variants(first: 250, after: $after) {
          pageInfo { hasNextPage endCursor }
          nodes {
            id
            title
            sku
            price
            inventoryQuantity
            sellableOnlineQuantity
            inventoryPolicy
            availableForSale
          }
        }
      }
    }
    """.strip()

    BOOTSTRAP_QUERY = """
    query ReportBootstrap {
      shop { myshopifyDomain currencyCode }
      currentAppInstallation { accessScopes { handle } }
    }
    """.strip()

    def __init__(
        self,
        *,
        shop: str,
        token: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        api_version: str = "2026-07",
        session=None,
        timeout: float = 45,
        max_retries: int = 3,
        sleeper=time.sleep,
        clock=time.monotonic,
    ):
        if not shop:
            raise ValueError("Shopify shop is required")
        if bool(client_id) != bool(client_secret):
            raise ValueError(
                "Shopify report client ID and client secret must be provided together"
            )
        if not token and not (client_id and client_secret):
            raise ValueError(
                "Shopify report token or client credentials are required"
            )
        self.shop = shop.removeprefix("https://").rstrip("/")
        self.token = token
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_version = api_version
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleeper = sleeper
        self.clock = clock
        self._oauth_access_token: str | None = None
        self._oauth_token_expires_at = 0.0
        self.warnings: list[str] = []

    @property
    def endpoint(self) -> str:
        return f"https://{self.shop}/admin/api/{self.api_version}/graphql.json"

    @property
    def token_endpoint(self) -> str:
        return f"https://{self.shop}/admin/oauth/access_token"

    def _delay(self, response, attempt: int) -> float:
        value = (getattr(response, "headers", {}) or {}).get("Retry-After")
        if value:
            try:
                return min(float(value), 30.0)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(value)
                    return max(
                        min((retry_at - datetime.now(timezone.utc)).total_seconds(), 30.0),
                        0.0,
                    )
                except (TypeError, ValueError):
                    pass
        return min((2 ** attempt) + random.random(), 10.0)

    def _mint_client_credentials_token(self) -> str:
        """Exchange Dev Dashboard credentials for a short-lived Admin token."""

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    self.token_endpoint,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                    },
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                self.sleeper(min((2 ** attempt) + random.random(), 10.0))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = ReportSourceError(
                    f"Shopify token endpoint returned HTTP {response.status_code}"
                )
                if attempt >= self.max_retries:
                    break
                self.sleeper(self._delay(response, attempt))
                continue

            if response.status_code in {401, 403}:
                raise ReportSourceError(
                    "Shopify report client credentials are unauthorized"
                )
            if response.status_code >= 400:
                raise ReportSourceError(
                    "Shopify client credentials request failed with "
                    f"HTTP {response.status_code}"
                )
            try:
                body = response.json()
            except ValueError as exc:
                raise ReportSourceError(
                    "Shopify client credentials response was not valid JSON"
                ) from exc
            if not isinstance(body, dict):
                raise ReportSourceError(
                    "Shopify client credentials response was not a JSON object"
                )

            access_token = body.get("access_token")
            if not access_token:
                raise ReportSourceError(
                    "Shopify client credentials response did not contain an access token"
                )
            try:
                expires_in = float(body.get("expires_in", 86400))
            except (TypeError, ValueError) as exc:
                raise ReportSourceError(
                    "Shopify client credentials response had an invalid expiry"
                ) from exc
            if expires_in <= 0:
                raise ReportSourceError(
                    "Shopify client credentials response had an invalid expiry"
                )

            # Refresh before Shopify's expiry boundary. A report process normally
            # exits after one run, but this also keeps long-lived workers safe.
            refresh_margin = min(60.0, expires_in * 0.1)
            self._oauth_access_token = str(access_token)
            self._oauth_token_expires_at = (
                self.clock() + expires_in - refresh_margin
            )
            return self._oauth_access_token

        error_type = type(last_error).__name__ if last_error else "unknown error"
        raise ReportSourceError(
            "Shopify client credentials request failed after retries "
            f"({error_type})"
        )

    def _access_token(self) -> str:
        # Dev Dashboard credentials are preferred when configured. The static
        # token remains a compatibility fallback for existing custom apps.
        if self.client_id and self.client_secret:
            if (
                self._oauth_access_token
                and self.clock() < self._oauth_token_expires_at
            ):
                return self._oauth_access_token
            return self._mint_client_credentials_token()
        return str(self.token)

    def _post(self, payload: dict):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    self.endpoint,
                    headers={
                        "X-Shopify-Access-Token": self._access_token(),
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                self.sleeper(min((2 ** attempt) + random.random(), 10.0))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                last_error = ReportSourceError(
                    f"Shopify returned HTTP {response.status_code}"
                )
                if attempt >= self.max_retries:
                    break
                self.sleeper(self._delay(response, attempt))
                continue

            if response.status_code in {401, 403}:
                raise ReportSourceError(
                    "Shopify report token is unauthorized or missing required scopes"
                )
            try:
                response.raise_for_status()
                body = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise ReportSourceError(f"Invalid Shopify response: {exc}") from exc

            actual_version = response.headers.get("X-Shopify-API-Version")
            if actual_version and actual_version != self.api_version:
                raise ReportSourceError(
                    f"Shopify served API {actual_version}, expected {self.api_version}"
                )
            return body

        raise ReportSourceError(f"Shopify request failed after retries: {last_error}")

    def graphql(self, query: str, variables: dict | None = None, *, allow_partial=False) -> dict:
        last_errors = None
        for attempt in range(self.max_retries + 1):
            body = self._post({"query": query, "variables": variables or {}})
            errors = body.get("errors") or []
            if not errors:
                return body.get("data") or {}

            if all((error.get("extensions") or {}).get("code") == "THROTTLED" for error in errors):
                last_errors = errors
                if attempt < self.max_retries:
                    self.sleeper(min((2 ** attempt) + random.random(), 10.0))
                    continue

            if allow_partial and body.get("data"):
                self.warnings.append("Shopify returned partial GraphQL data")
                return body.get("data") or {}
            messages = "; ".join(str(error.get("message") or error) for error in errors)
            raise ReportSourceError(f"Shopify GraphQL error: {messages}")
        raise ReportSourceError(f"Shopify GraphQL throttled after retries: {last_errors}")

    def validate_access(self) -> dict:
        data = self.graphql(self.BOOTSTRAP_QUERY)
        shop = data.get("shop") or {}
        actual_domain = str(shop.get("myshopifyDomain") or "").lower()
        if actual_domain and actual_domain != self.shop.lower():
            raise ReportSourceError(
                f"Shopify token belongs to {actual_domain}, not {self.shop}"
            )
        scopes = {
            str(item.get("handle"))
            for item in ((data.get("currentAppInstallation") or {}).get("accessScopes") or [])
        }
        required = {"read_orders", "read_all_orders", "read_products"}
        missing = sorted(required - scopes)
        if missing:
            raise ReportSourceError(
                "Shopify report token is missing scopes: " + ", ".join(missing)
            )
        return {
            "shop": actual_domain or self.shop,
            "currency": shop.get("currencyCode"),
            "scopes": sorted(scopes),
            "api_version": self.api_version,
        }

    @staticmethod
    def _utc(value: datetime) -> str:
        return (
            value.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _fetch_line_items(self, order_id: str) -> list[dict]:
        nodes, cursor = [], None
        while True:
            data = self.graphql(
                self.LINE_ITEMS_QUERY,
                {"id": order_id, "after": cursor},
            )
            connection = ((data.get("order") or {}).get("lineItems") or {})
            nodes.extend(connection.get("nodes") or [])
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return nodes
            cursor = page.get("endCursor")

    def _fetch_first_touches(self, ids: list[str]) -> dict[str, dict | None]:
        result: dict[str, dict | None] = {}
        for index in range(0, len(ids), 100):
            chunk = ids[index:index + 100]
            data = self.graphql(self.FIRST_TOUCH_QUERY, {"ids": chunk}, allow_partial=True)
            for node in data.get("nodes") or []:
                if node and node.get("id"):
                    result[node["id"]] = node.get("customerJourneySummary")
        return result

    def fetch_orders(self, start: datetime, end: datetime) -> list[dict]:
        query_string = (
            f"processed_at:>='{self._utc(start)}' "
            f"processed_at:<'{self._utc(end)}' test:false"
        )
        orders, cursor = [], None
        while True:
            data = self.graphql(
                self.ORDERS_QUERY,
                {"after": cursor, "query": query_string},
                # Sales is the report's source of truth. Partial order pages
                # must fail closed rather than silently understating revenue.
                allow_partial=False,
            )
            connection = data.get("orders") or {}
            orders.extend(connection.get("nodes") or [])
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")

        positive = [
            order
            for order in orders
            if float(
                (((order.get("netPaymentSet") or {}).get("shopMoney") or {}).get("amount"))
                or 0
            ) > 0
            and not order.get("cancelledAt")
        ]
        for order in positive:
            order["lineItems"] = {"nodes": self._fetch_line_items(order["id"])}

        online_ids = [
            order["id"]
            for order in positive
            if str(order.get("sourceName") or "").lower() == "web"
            or str((order.get("app") or {}).get("name") or "").lower() == "online store"
        ]
        touches = self._fetch_first_touches(online_ids)
        for order in positive:
            if order["id"] in touches:
                order["customerJourneySummary"] = touches[order["id"]]
        return orders

    def fetch_catalog(self) -> list[dict]:
        products, cursor = [], None
        while True:
            data = self.graphql(self.CATALOG_QUERY, {"after": cursor})
            connection = data.get("products") or {}
            batch = connection.get("nodes") or []
            for product in batch:
                variants = product.get("variants") or {}
                nodes = list(variants.get("nodes") or [])
                page = variants.get("pageInfo") or {}
                variant_cursor = page.get("endCursor")
                while page.get("hasNextPage"):
                    extra = self.graphql(
                        self.PRODUCT_VARIANTS_QUERY,
                        {"id": product["id"], "after": variant_cursor},
                    )
                    variants_connection = ((extra.get("product") or {}).get("variants") or {})
                    nodes.extend(variants_connection.get("nodes") or [])
                    page = variants_connection.get("pageInfo") or {}
                    variant_cursor = page.get("endCursor")
                product["variants"] = {"nodes": nodes}
                products.append(product)
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                return products
            cursor = page.get("endCursor")


class GoogleSearchConsoleClient:
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    API_ROOT = "https://www.googleapis.com/webmasters/v3/sites"
    _EMAIL_RE = re.compile(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b")
    _LONG_NUMBER_RE = re.compile(r"\b\d{7,}\b")

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        property_uri: str = "sc-domain:rarecardsjapan.com",
        session=None,
        timeout: float = 45,
        max_retries: int = 3,
        sleeper=time.sleep,
    ):
        if not all([client_id, client_secret, refresh_token, property_uri]):
            raise ValueError("Google Search Console OAuth settings are incomplete")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.property_uri = property_uri
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleeper = sleeper
        self._access_token: str | None = None

    @property
    def query_url(self) -> str:
        return (
            f"{self.API_ROOT}/{quote(self.property_uri, safe='')}"
            "/searchAnalytics/query"
        )

    def _request(self, method: str, url: str, **kwargs):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=self.timeout,
                    **kwargs,
                )
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                self.sleeper(min((2 ** attempt) + random.random(), 10.0))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_error = ReportSourceError(f"Google returned HTTP {response.status_code}")
                if attempt >= self.max_retries:
                    break
                self.sleeper(min((2 ** attempt) + random.random(), 10.0))
                continue
            if response.status_code in {401, 403}:
                raise ReportSourceError(
                    "Google Search Console credentials are unauthorized"
                )
            try:
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                raise ReportSourceError(f"Invalid Google response: {exc}") from exc
        raise ReportSourceError(f"Google request failed after retries: {last_error}")

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        body = self._request(
            "POST",
            self.TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        token = body.get("access_token")
        if not token:
            raise ReportSourceError("Google OAuth response did not contain an access token")
        self._access_token = str(token)
        return self._access_token

    def query(self, body: dict) -> dict:
        return self._request(
            "POST",
            self.query_url,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
            },
            json=body,
        )

    @staticmethod
    def _date(value: date) -> str:
        return value.isoformat()

    def latest_final_date(self, *, today: date | None = None) -> date:
        anchor = today or date.today()
        body = self.query(
            {
                "startDate": self._date(anchor - timedelta(days=14)),
                "endDate": self._date(anchor),
                "dimensions": ["date"],
                "type": "web",
                "dataState": "all",
                "rowLimit": 50,
            }
        )
        first_incomplete = (body.get("metadata") or {}).get("first_incomplete_date")
        if first_incomplete:
            return date.fromisoformat(first_incomplete) - timedelta(days=1)

        final = self.query(
            {
                "startDate": self._date(anchor - timedelta(days=14)),
                "endDate": self._date(anchor),
                "dimensions": ["date"],
                "type": "web",
                "dataState": "final",
                "rowLimit": 50,
            }
        )
        rows = final.get("rows") or []
        if not rows:
            raise ReportSourceError("Search Console returned no finalized dates")
        return max(date.fromisoformat(row["keys"][0]) for row in rows)

    def _range_query(
        self,
        start: date,
        end: date,
        *,
        dimensions: list[str] | None = None,
        row_limit: int = 25000,
        aggregation: str = "byProperty",
    ) -> dict:
        payload = {
            "startDate": self._date(start),
            "endDate": self._date(end),
            "type": "web",
            "dataState": "final",
            "aggregationType": aggregation,
            "rowLimit": row_limit,
        }
        if dimensions:
            payload["dimensions"] = dimensions
        return self.query(payload)

    @staticmethod
    def _totals(body: dict) -> dict:
        row = (body.get("rows") or [{}])[0]
        return {
            "clicks": float(row.get("clicks") or 0),
            "impressions": float(row.get("impressions") or 0),
            "ctr": float(row.get("ctr") or 0),
            "position": float(row.get("position") or 0),
        }

    @classmethod
    def _safe_query(cls, value: str) -> str:
        value = cls._EMAIL_RE.sub("[redacted]", str(value))
        return cls._LONG_NUMBER_RE.sub("[redacted]", value)[:160]

    @classmethod
    def _query_rows(cls, body: dict) -> list[dict]:
        result = []
        for row in body.get("rows") or []:
            keys = list(row.get("keys") or [])
            if keys:
                keys[0] = cls._safe_query(keys[0])
            result.append(
                {
                    "keys": keys,
                    "clicks": float(row.get("clicks") or 0),
                    "impressions": float(row.get("impressions") or 0),
                    "ctr": float(row.get("ctr") or 0),
                    "position": float(row.get("position") or 0),
                }
            )
        return result

    def fetch_report(self, *, today: date | None = None) -> dict:
        latest = self.latest_final_date(today=today)
        week_start = latest - timedelta(days=6)
        previous_end = week_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=6)
        query_start = latest - timedelta(days=27)
        prior_query_end = query_start - timedelta(days=1)
        prior_query_start = prior_query_end - timedelta(days=27)

        current = self._totals(self._range_query(week_start, latest, row_limit=1))
        previous = self._totals(
            self._range_query(previous_start, previous_end, row_limit=1)
        )
        current_queries = self._query_rows(
            self._range_query(query_start, latest, dimensions=["query"])
        )
        previous_queries = self._query_rows(
            self._range_query(prior_query_start, prior_query_end, dimensions=["query"])
        )
        pages = self._query_rows(
            self._range_query(
                query_start,
                latest,
                dimensions=["page"],
                row_limit=250,
                # Search Console rejects byProperty when page is a dimension.
                aggregation="auto",
            )
        )
        query_pages = self._query_rows(
            self._range_query(
                query_start,
                latest,
                dimensions=["query", "page"],
                aggregation="auto",
            )
        )

        previous_by_query = {
            (row.get("keys") or [""])[0]: row for row in previous_queries
        }
        movers = []
        for row in current_queries:
            query_text = (row.get("keys") or [""])[0]
            prior = previous_by_query.get(query_text, {})
            movers.append(
                {
                    **row,
                    "query": query_text,
                    "click_delta": row["clicks"] - float(prior.get("clicks") or 0),
                    "impression_delta": row["impressions"]
                    - float(prior.get("impressions") or 0),
                    "ctr_delta_pp": 100
                    * (row["ctr"] - float(prior.get("ctr") or 0)),
                    "position_improvement": float(prior.get("position") or 0)
                    - row["position"]
                    if prior
                    else None,
                }
            )

        opportunities = []
        for row in query_pages:
            if (
                row["impressions"] >= 100
                and row["position"] <= 20
                and row["ctr"] < 0.03
            ):
                opportunities.append(
                    {
                        **row,
                        "query": (row.get("keys") or [""])[0],
                        "page": (row.get("keys") or ["", ""])[1],
                        "type": "CTR gap",
                    }
                )
            elif row["impressions"] >= 50 and 8 <= row["position"] <= 20:
                opportunities.append(
                    {
                        **row,
                        "query": (row.get("keys") or [""])[0],
                        "page": (row.get("keys") or ["", ""])[1],
                        "type": "Striking distance",
                    }
                )

        return {
            "status": "ok",
            "as_of": latest.isoformat(),
            "timezone": "America/Los_Angeles",
            "weekly_window": {
                "start": week_start.isoformat(),
                "end": latest.isoformat(),
            },
            "previous_weekly_window": {
                "start": previous_start.isoformat(),
                "end": previous_end.isoformat(),
            },
            "query_window": {
                "start": query_start.isoformat(),
                "end": latest.isoformat(),
            },
            "previous_query_window": {
                "start": prior_query_start.isoformat(),
                "end": prior_query_end.isoformat(),
            },
            "current": current,
            "previous": previous,
            "comparison": {
                key: {
                    "absolute": current[key] - previous[key],
                    "percent": (
                        (current[key] - previous[key]) / abs(previous[key])
                        if previous[key]
                        else None
                    ),
                }
                for key in ("clicks", "impressions", "ctr", "position")
            },
            "top_queries": current_queries[:10],
            "query_movers": sorted(
                movers,
                key=lambda row: (-abs(row["click_delta"]), -row["impressions"]),
            )[:10],
            "top_pages": pages[:10],
            "opportunities": sorted(
                opportunities,
                key=lambda row: (-row["impressions"], row["position"]),
            )[:10],
            "query_rows_are_partial": True,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
