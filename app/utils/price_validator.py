"""
app/utils/price_validator.py

Price anomaly detection and validation helpers.

The validator compares a newly scraped price against the card's recent
history and flags it when:

  - The price deviates more than SPIKE_THRESHOLD_PCT from the rolling
    median (default ± 200 %).
  - The price is outside hard absolute bounds (negative, or above
    MAX_SINGLE_CARD_USD).
  - A retailer submitted a suspiciously round number that looks like a
    placeholder (e.g. 999.00 or 1000.00) AND it is far from the median.

Usage
-----
    from app.utils.price_validator import validate_price, PriceValidationResult

    result = validate_price(card_id=42, new_price_usd=1.23)
    if result.is_anomaly:
        # skip or quarantine the price
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from statistics import median
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tuneable constants
# ---------------------------------------------------------------------------
# Maximum allowed deviation from rolling median before flagging as anomaly.
# 2.0 means the price may be up to 200 % higher or lower than the median.
SPIKE_THRESHOLD_PCT: float = 2.0

# Hard upper bound for a single card price (USD). Adjust if legitimately
# expensive cards are being tracked.
MAX_SINGLE_CARD_USD: float = 10_000.0

# Minimum number of historical data-points required to compute a median.
# If fewer are available, deviation checks are skipped.
MIN_HISTORY_FOR_SPIKE_CHECK: int = 5

# Placeholder prices that retailers sometimes use when they run out of stock.
_PLACEHOLDER_PRICES = {999.0, 999.99, 1000.0, 9999.0, 9999.99}


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PriceValidationResult:
    is_anomaly: bool = False
    reasons: List[str] = field(default_factory=list)
    median_price: Optional[float] = None
    deviation_pct: Optional[float] = None

    def add_reason(self, msg: str) -> None:
        self.reasons.append(msg)
        self.is_anomaly = True

    def __repr__(self) -> str:
        return (
            f"<PriceValidationResult anomaly={self.is_anomaly} "
            f"reasons={self.reasons}>"
        )


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------

def validate_price(
    new_price_usd: float,
    historical_prices: Optional[List[float]] = None,
    card_id: Optional[int] = None,          # used only for logging context
    spike_threshold_pct: float = SPIKE_THRESHOLD_PCT,
    max_price_usd: float = MAX_SINGLE_CARD_USD,
) -> PriceValidationResult:
    """
    Validate *new_price_usd* against optional history and hard bounds.

    Parameters
    ----------
    new_price_usd       : the freshly scraped price in USD.
    historical_prices   : recent prices for the same card (USD), oldest first.
                          If None or too short, spike checks are skipped.
    card_id             : optional, used only in log messages.
    spike_threshold_pct : fractional deviation threshold (default 2.0 = 200%).
    max_price_usd       : hard upper-bound (default $10,000).

    Returns
    -------
    PriceValidationResult
    """
    result = PriceValidationResult()

    # ------------------------------------------------------------------
    # 1. Hard bounds
    # ------------------------------------------------------------------
    if new_price_usd < 0:
        result.add_reason(f"Negative price: {new_price_usd:.4f}")
        logger.warning("card_id=%s  negative price=%.4f", card_id, new_price_usd)

    if new_price_usd > max_price_usd:
        result.add_reason(
            f"Price {new_price_usd:.2f} exceeds hard cap {max_price_usd:.2f}"
        )
        logger.warning(
            "card_id=%s  price %.2f exceeds cap %.2f",
            card_id,
            new_price_usd,
            max_price_usd,
        )

    # ------------------------------------------------------------------
    # 2. Placeholder check (run before history check)
    # ------------------------------------------------------------------
    if new_price_usd in _PLACEHOLDER_PRICES:
        result.add_reason(f"Suspected placeholder price: {new_price_usd}")
        logger.warning("card_id=%s  placeholder price=%.2f", card_id, new_price_usd)

    # ------------------------------------------------------------------
    # 3. Spike / deviation check (requires enough history)
    # ------------------------------------------------------------------
    if historical_prices and len(historical_prices) >= MIN_HISTORY_FOR_SPIKE_CHECK:
        med = median(historical_prices)
        result.median_price = med

        if med > 0:
            deviation = abs(new_price_usd - med) / med
            result.deviation_pct = round(deviation * 100, 2)

            if deviation > spike_threshold_pct:
                result.add_reason(
                    f"Price deviation {result.deviation_pct:.1f}% exceeds "
                    f"threshold {spike_threshold_pct * 100:.0f}%  "
                    f"(new={new_price_usd:.4f}, median={med:.4f})"
                )
                logger.warning(
                    "card_id=%s  spike detected  new=%.4f  median=%.4f  deviation=%.1f%%",
                    card_id,
                    new_price_usd,
                    med,
                    result.deviation_pct,
                )

    if not result.is_anomaly:
        logger.debug(
            "card_id=%s  price=%.4f passed validation", card_id, new_price_usd
        )

    return result


# ---------------------------------------------------------------------------
# Convenience: validate and pull history from the DB
# ---------------------------------------------------------------------------

def validate_price_for_card(
    card_id: int,
    new_price_usd: float,
    lookback: int = 30,
) -> PriceValidationResult:
    """
    Convenience wrapper that fetches the last *lookback* prices for
    *card_id* from the database, then calls :func:`validate_price`.

    Requires an active Flask application context.

    Parameters
    ----------
    card_id       : card to look up.
    new_price_usd : freshly scraped price in USD.
    lookback      : how many historical prices to consider.
    """
    from app.models.price import Price  # local import to avoid circular deps

    history = (
        Price.query.filter_by(card_id=card_id)
        .order_by(Price.scraped_at.desc())
        .limit(lookback)
        .all()
    )
    historical_prices = [p.price_usd for p in reversed(history)]
    return validate_price(
        new_price_usd=new_price_usd,
        historical_prices=historical_prices,
        card_id=card_id,
    )
