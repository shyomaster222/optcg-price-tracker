"""
tests/test_api.py

Integration tests for the REST API endpoints.

Each test uses the Flask test client with a seeded in-memory database.
All external HTTP calls (scrapers, webhooks) are not triggered.
"""

import json
import pytest


# ---------------------------------------------------------------------------
# GET /api/products
# ---------------------------------------------------------------------------

class TestListProducts:
    """GET /api/products"""

    def test_returns_200(self, client, sample_data):
        resp = client.get("/api/products")
        assert resp.status_code == 200

    def test_returns_list(self, client, sample_data):
        resp = client.get("/api/products")
        data = resp.get_json()
        assert isinstance(data, list)

    def test_contains_seeded_products(self, client, sample_data):
        resp = client.get("/api/products")
        data = resp.get_json()
        set_codes = [p["set_code"] for p in data]
        assert "OP-01" in set_codes

    def test_filter_by_type_box(self, client, sample_data):
        resp = client.get("/api/products?type=box")
        data = resp.get_json()
        for product in data:
            assert product["product_type"] == "box"

    def test_filter_by_type_case(self, client, sample_data):
        resp = client.get("/api/products?type=case")
        data = resp.get_json()
        for product in data:
            assert product["product_type"] == "case"

    def test_product_has_required_fields(self, client, sample_data):
        resp = client.get("/api/products")
        data = resp.get_json()
        assert len(data) > 0
        product = data[0]
        for field in ("id", "set_code", "set_name", "product_type", "display_name"):
            assert field in product, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# GET /api/products/<id>/latest
# ---------------------------------------------------------------------------

class TestGetLatestPrices:
    """GET /api/products/<id>/latest"""

    def test_returns_200_for_known_product(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.get(f"/api/products/{product_id}/latest")
        assert resp.status_code == 200

    def test_returns_404_for_unknown_product(self, client, sample_data):
        resp = client.get("/api/products/99999/latest")
        assert resp.status_code == 404

    def test_response_has_product_and_prices_keys(self, client, sample_data):
        product_id = sample_data["product_box"].id
        data = client.get(f"/api/products/{product_id}/latest").get_json()
        assert "product" in data
        assert "prices" in data

    def test_prices_list_contains_seeded_retailers(self, client, sample_data):
        product_id = sample_data["product_box"].id
        data = client.get(f"/api/products/{product_id}/latest").get_json()
        retailer_slugs = [p["retailer_slug"] for p in data["prices"]]
        assert "amazon-jp" in retailer_slugs
        assert "ebay" in retailer_slugs

    def test_price_entry_has_required_fields(self, client, sample_data):
        product_id = sample_data["product_box"].id
        data = client.get(f"/api/products/{product_id}/latest").get_json()
        assert len(data["prices"]) > 0
        price_entry = data["prices"][0]
        for field in ("retailer_name", "retailer_slug", "price", "price_usd", "currency", "in_stock", "scraped_at"):
            assert field in price_entry, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# GET /api/products/<id>/history
# ---------------------------------------------------------------------------

class TestGetPriceHistory:
    """GET /api/products/<id>/history"""

    def test_returns_200(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.get(f"/api/products/{product_id}/history")
        assert resp.status_code == 200

    def test_returns_dict_with_datasets(self, client, sample_data):
        product_id = sample_data["product_box"].id
        data = client.get(f"/api/products/{product_id}/history").get_json()
        assert "datasets" in data
        assert isinstance(data["datasets"], list)

    def test_dataset_has_required_fields(self, client, sample_data):
        product_id = sample_data["product_box"].id
        data = client.get(f"/api/products/{product_id}/history").get_json()
        if data["datasets"]:
            ds = data["datasets"][0]
            for field in ("label", "data", "borderColor"):
                assert field in ds

    def test_days_query_param_accepted(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.get(f"/api/products/{product_id}/history?days=7")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/alerts  +  GET /api/alerts
# ---------------------------------------------------------------------------

class TestAlertsCRUD:
    """POST /api/alerts, GET /api/alerts, DELETE /api/alerts/<id>"""

    def test_create_alert_returns_201(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.post(
            "/api/alerts",
            data=json.dumps({"card_id": product_id, "threshold": 40.0, "direction": "below"}),
            content_type="application/json",
        )
        assert resp.status_code == 201

    def test_create_alert_response_has_id(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.post(
            "/api/alerts",
            data=json.dumps({"card_id": product_id, "threshold": 40.0}),
            content_type="application/json",
        )
        data = resp.get_json()
        assert "id" in data

    def test_create_alert_missing_card_id_returns_400(self, client, sample_data):
        resp = client.post(
            "/api/alerts",
            data=json.dumps({"threshold": 40.0}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_create_alert_missing_threshold_returns_400(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.post(
            "/api/alerts",
            data=json.dumps({"card_id": product_id}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_list_alerts_returns_200(self, client, sample_data):
        resp = client.get("/api/alerts")
        assert resp.status_code == 200

    def test_list_alerts_returns_list(self, client, sample_data):
        data = client.get("/api/alerts").get_json()
        assert isinstance(data, list)

    def test_created_alert_appears_in_list(self, client, sample_data):
        product_id = sample_data["product_box"].id
        client.post(
            "/api/alerts",
            data=json.dumps({"card_id": product_id, "threshold": 35.0}),
            content_type="application/json",
        )
        alerts = client.get("/api/alerts").get_json()
        thresholds = [a["threshold"] for a in alerts]
        assert 35.0 in thresholds

    def test_delete_alert_returns_200(self, client, sample_data):
        product_id = sample_data["product_box"].id
        create_resp = client.post(
            "/api/alerts",
            data=json.dumps({"card_id": product_id, "threshold": 45.0}),
            content_type="application/json",
        )
        alert_id = create_resp.get_json()["id"]
        del_resp = client.delete(f"/api/alerts/{alert_id}")
        assert del_resp.status_code == 200

    def test_delete_nonexistent_alert_returns_404(self, client, sample_data):
        resp = client.delete("/api/alerts/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/export/cards  +  CSV/JSON export
# ---------------------------------------------------------------------------

class TestExportEndpoints:
    """GET /api/export/cards, /api/export/prices/<id>.csv, /api/export/prices/<id>.json"""

    def test_export_cards_returns_200(self, client, sample_data):
        resp = client.get("/api/export/cards")
        assert resp.status_code == 200

    def test_export_cards_returns_json_list(self, client, sample_data):
        data = client.get("/api/export/cards").get_json()
        assert isinstance(data, list)

    def test_export_prices_csv_returns_200(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.get(f"/api/export/prices/{product_id}.csv")
        assert resp.status_code == 200

    def test_export_prices_csv_content_type(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.get(f"/api/export/prices/{product_id}.csv")
        assert "text/csv" in resp.content_type

    def test_export_prices_json_returns_200(self, client, sample_data):
        product_id = sample_data["product_box"].id
        resp = client.get(f"/api/export/prices/{product_id}.json")
        assert resp.status_code == 200

    def test_export_prices_json_returns_list(self, client, sample_data):
        product_id = sample_data["product_box"].id
        data = client.get(f"/api/export/prices/{product_id}.json").get_json()
        assert isinstance(data, list)

    def test_export_prices_unknown_card_returns_404(self, client, sample_data):
        resp = client.get("/api/export/prices/99999.csv")
        assert resp.status_code == 404

    def test_export_all_csv_returns_200(self, client, sample_data):
        resp = client.get("/api/export/prices/all.csv")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /admin/health  +  /admin/health/json
# ---------------------------------------------------------------------------

class TestAdminHealth:
    """GET /admin/health and /admin/health/json"""

    def test_health_dashboard_returns_200(self, client, sample_data):
        resp = client.get("/admin/health")
        assert resp.status_code == 200

    def test_health_json_returns_200(self, client, sample_data):
        resp = client.get("/admin/health/json")
        assert resp.status_code == 200

    def test_health_json_returns_dict(self, client, sample_data):
        data = client.get("/admin/health/json").get_json()
        assert isinstance(data, dict)

    def test_ping_returns_ok(self, client):
        resp = client.get("/admin/ping")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
