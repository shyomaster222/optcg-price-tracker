"""
app/services/price_sync_config.py

Loaders for the two hand-verified config files the price sync depends on:

  price_map.json     - the RCJ<->Fuji whitelist (built by scripts/build_price_map.py).
                       Only products listed AND enabled here are ever auto-priced.
  price_floors.json  - optional per-product minimum USD prices.

Both are plain JSON at the repo root by default (overridable via PRICE_MAP_PATH /
PRICE_FLOORS_PATH). Missing files are treated as empty, not errors.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from flask import current_app

logger = logging.getLogger(__name__)

# repo root = two levels up from this file (app/services/ -> app/ -> repo)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(_REPO_ROOT, path)


def _load_json(config_key: str, default_name: str):
    path = _resolve(current_app.config.get(config_key, default_name))
    if not os.path.exists(path):
        logger.warning("price_sync: config file not found: %s", path)
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as exc:  # pragma: no cover - corrupt file
        logger.error("price_sync: failed to read %s: %s", path, exc)
        return None


def load_price_map() -> List[dict]:
    """Return the list of enabled map entries with a usable variant id + fuji url."""
    data = _load_json("PRICE_MAP_PATH", "price_map.json")
    if not data:
        return []
    entries = []
    for e in data:
        if not e.get("enabled", True):
            continue
        if not e.get("rcj_variant_id") or not e.get("fuji_url"):
            logger.warning("price_sync: skipping map entry missing variant id / fuji url: %s",
                           e.get("rcj_handle") or e.get("set_code"))
            continue
        entries.append(e)
    return entries


def floor_key(set_code: str, product_type: str) -> str:
    return f"{set_code}:{product_type}"


class PriceFloors:
    """Wraps price_floors.json; keys are 'SET-CODE:type' -> minimum USD price."""

    def __init__(self, data: Optional[dict]):
        self._data = {k: v for k, v in (data or {}).items() if not k.startswith("_")}

    def get(self, set_code: str, product_type: str) -> Optional[float]:
        val = self._data.get(floor_key(set_code, product_type))
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None


def load_price_floors() -> PriceFloors:
    return PriceFloors(_load_json("PRICE_FLOORS_PATH", "price_floors.json"))
