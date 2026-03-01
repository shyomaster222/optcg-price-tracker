"""
tests/test_services.py

Unit tests for the service layer:
  - PriceService   (get_latest_prices, get_price_history, bulk_upsert)
  - ChartService   (get_chart_data)
  - AlertService   (create_alert, get_alerts, evaluate_alerts, delete_alert)
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# PriceService
# ---------------------------------------------------------------------------

class TestPriceService:
    """Tests for app.services.price_service.PriceService."""

    @pytest.fixture
    def svc(self, app):
        from app.services.price_service import PriceService
        with app.app_context():
            yield PriceService()

    def test_get_latest_prices_returns_list(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_latest_prices(product_id)
            assert isinstance(result, list)

    def test_get_latest_prices_includes_seeded_retailers(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_latest_prices(product_id)
            slugs = [r["retailer_slug"] for r in result]
            assert "amazon-jp" in slugs
            assert "ebay" in slugs

    def test_get_latest_prices_out_of_stock_not_included_by_default(self, svc, sample_data, app):
        """The amazon-jp case entry is out of stock; it should be excluded
        when in_stock_only=True (the default).
        """
        with app.app_context():
            product_id = sample_data["product_case"].id
            result = svc.get_latest_prices(product_id, in_stock_only=True)
            slugs = [r["retailer_slug"] for r in result]
            assert "amazon-jp" not in slugs

    def test_get_latest_prices_includes_out_of_stock_when_requested(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_case"].id
            result = svc.get_latest_prices(product_id, in_stock_only=False)
            slugs = [r["retailer_slug"] for r in result]
            assert "amazon-jp" in slugs

    def test_get_price_history_returns_list(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_price_history(product_id)
            assert isinstance(result, list)

    def test_get_price_history_respects_days_param(self, svc, sample_data, app):
        """Requesting 0 days should return no history."""
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_price_history(product_id, days=0)
            assert result == []

    def test_bulk_upsert_returns_count(self, svc, sample_data, app):
        with app.app_context():
            records = [
                {
                    "product_id": sample_data["product_box"].id,
                    "retailer_id": sample_data["retailer_ebay"].id,
                    "price": 60.0,
                    "price_usd": 60.0,
                    "currency": "USD",
                    "in_stock": True,
                    "source_url": "https://ebay.com/test",
                }
            ]
            count = svc.bulk_upsert(records)
            assert count == 1

    def test_bulk_upsert_empty_list_returns_zero(self, svc, app):
        with app.app_context():
            count = svc.bulk_upsert([])
            assert count == 0


# ---------------------------------------------------------------------------
# ChartService
# ---------------------------------------------------------------------------

class TestChartService:
    """Tests for app.services.chart_service.ChartService."""

    @pytest.fixture
    def svc(self, app):
        from app.services.chart_service import ChartService
        with app.app_context():
            yield ChartService()

    def test_get_chart_data_returns_dict_with_datasets(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_chart_data(product_id)
            assert isinstance(result, dict)
            assert "datasets" in result

    def test_get_chart_data_datasets_is_list(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_chart_data(product_id)
            assert isinstance(result["datasets"], list)

    def test_get_chart_data_dataset_has_required_keys(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_chart_data(product_id)
            if result["datasets"]:
                ds = result["datasets"][0]
                for key in ("label", "data", "borderColor", "backgroundColor"):
                    assert key in ds, f"Missing key: {key}"

    def test_get_chart_data_known_retailer_has_correct_color(self, svc, sample_data, app):
        """PVPShoppe should have its specific brand color, not the fallback grey."""
        with app.app_context():
            from app.services.chart_service import RETAILER_COLORS, DEFAULT_COLOR
            assert RETAILER_COLORS.get("PVPShoppe") is not None
            assert RETAILER_COLORS["PVPShoppe"] != DEFAULT_COLOR

    def test_get_chart_data_days_zero_returns_empty_datasets(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_chart_data(product_id, days=0)
            assert result["datasets"] == []

    def test_get_chart_data_retailer_filter(self, svc, sample_data, app):
        with app.app_context():
            product_id = sample_data["product_box"].id
            result = svc.get_chart_data(product_id, retailers=["ebay"])
            for ds in result["datasets"]:
                assert ds["label"] == "ebay" or "ebay" in ds["label"].lower()


# ---------------------------------------------------------------------------
# AlertService (via service functions)
# ---------------------------------------------------------------------------

class TestAlertService:
    """Tests for app.services.alert_service functions."""

    def test_create_alert_persists_to_db(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert, get_alerts
            product_id = sample_data["product_box"].id
            alert = create_alert(card_id=product_id, threshold=30.0, direction="below")
            assert alert.id is not None
            alerts = get_alerts(card_id=product_id)
            assert any(a.id == alert.id for a in alerts)

    def test_create_alert_invalid_direction_raises(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert
            product_id = sample_data["product_box"].id
            with pytest.raises(ValueError, match="direction"):
                create_alert(card_id=product_id, threshold=30.0, direction="sideways")

    def test_create_alert_zero_threshold_raises(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert
            product_id = sample_data["product_box"].id
            with pytest.raises(ValueError):
                create_alert(card_id=product_id, threshold=0.0)

    def test_get_alerts_active_only_default(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert, get_alerts
            product_id = sample_data["product_box"].id
            alert = create_alert(card_id=product_id, threshold=25.0)
            # Mark as triggered
            alert.mark_triggered()
            from app.extensions import db as _db
            _db.session.commit()
            # active_only=True (default) should exclude it
            active = get_alerts(card_id=product_id, active_only=True)
            assert all(a.is_active for a in active)

    def test_delete_alert_removes_from_db(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert, delete_alert, get_alerts
            product_id = sample_data["product_box"].id
            alert = create_alert(card_id=product_id, threshold=20.0)
            alert_id = alert.id
            deleted = delete_alert(alert_id)
            assert deleted is True
            remaining = get_alerts(card_id=product_id)
            assert all(a.id != alert_id for a in remaining)

    def test_delete_nonexistent_alert_returns_false(self, app, db_session):
        with app.app_context():
            from app.services.alert_service import delete_alert
            result = delete_alert(99999)
            assert result is False

    def test_evaluate_alerts_triggers_below_alert(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert, evaluate_alerts
            product_id = sample_data["product_box"].id
            alert = create_alert(card_id=product_id, threshold=60.0, direction="below")
            # Current price is 30, which is below 60 -> should trigger
            triggered = evaluate_alerts(card_id=product_id, current_price_usd=30.0)
            assert any(a.id == alert.id for a in triggered)

    def test_evaluate_alerts_does_not_trigger_above_threshold_when_direction_below(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert, evaluate_alerts
            product_id = sample_data["product_box"].id
            alert = create_alert(card_id=product_id, threshold=20.0, direction="below")
            # Price 50 is above 20 -> should NOT trigger for 'below' direction
            triggered = evaluate_alerts(card_id=product_id, current_price_usd=50.0)
            assert not any(a.id == alert.id for a in triggered)

    def test_evaluate_alerts_triggers_above_alert(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert, evaluate_alerts
            product_id = sample_data["product_box"].id
            alert = create_alert(card_id=product_id, threshold=40.0, direction="above")
            # Price 50 is above 40 -> should trigger
            triggered = evaluate_alerts(card_id=product_id, current_price_usd=50.0)
            assert any(a.id == alert.id for a in triggered)

    def test_evaluate_alerts_deactivates_triggered_alert(self, app, sample_data, db_session):
        with app.app_context():
            from app.services.alert_service import create_alert, evaluate_alerts
            product_id = sample_data["product_box"].id
            alert = create_alert(card_id=product_id, threshold=100.0, direction="below")
            evaluate_alerts(card_id=product_id, current_price_usd=50.0)
            from app.extensions import db as _db
            _db.session.refresh(alert)
            assert alert.is_active is False
            assert alert.triggered_at is not None
