"""
app/routes/api_alerts.py

REST endpoints for the price-alert / watchlist system.

Endpoints
---------
GET    /api/alerts              – list active alerts
POST   /api/alerts              – create an alert
DELETE /api/alerts/<id>         – delete an alert
POST   /api/alerts/evaluate     – manually trigger evaluation (debug/admin)
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.services.alert_service import (
    create_alert,
    delete_alert,
    get_alerts,
    run_all_alerts,
)

alerts_bp = Blueprint("alerts", __name__, url_prefix="/api/alerts")


@alerts_bp.route("", methods=["GET"])
def list_alerts():
    """
    Query params:
      card_id   (int, optional)
      active    (bool, default true)
    """
    card_id = request.args.get("card_id", type=int)
    active_only = request.args.get("active", "true").lower() != "false"
    alerts = get_alerts(card_id=card_id, active_only=active_only)
    return jsonify([a.to_dict() for a in alerts])


@alerts_bp.route("", methods=["POST"])
def create_alert_endpoint():
    """
    Body (JSON):
      card_id   : int   (required)
      threshold : float (required, > 0)
      direction : str   (optional, 'below' | 'above', default 'below')
      user_id   : int   (optional)
    """
    data = request.get_json(force=True, silent=True) or {}

    card_id = data.get("card_id")
    threshold = data.get("threshold")

    if card_id is None or threshold is None:
        return jsonify({"error": "card_id and threshold are required"}), 400

    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        return jsonify({"error": "threshold must be a number"}), 400

    direction = data.get("direction", "below")
    user_id = data.get("user_id")

    try:
        alert = create_alert(
            card_id=int(card_id),
            threshold=threshold,
            direction=direction,
            user_id=int(user_id) if user_id is not None else None,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify(alert.to_dict()), 201


@alerts_bp.route("/<int:alert_id>", methods=["DELETE"])
def delete_alert_endpoint(alert_id: int):
    found = delete_alert(alert_id)
    if not found:
        return jsonify({"error": "Alert not found"}), 404
    return jsonify({"deleted": alert_id}), 200


@alerts_bp.route("/evaluate", methods=["POST"])
def evaluate_all():
    """Manually run alert evaluation across all active alerts."""
    result = run_all_alerts()
    return jsonify(result)
