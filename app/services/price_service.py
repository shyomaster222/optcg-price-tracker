from datetime import datetime, timedelta
from typing import Dict, Any, List
from sqlalchemy import func

from app.models.product import Product
from app.models.price import PriceHistory
from app.models.retailer import Retailer
from app.extensions import db

# Exchange rate: 1 USD = ~150 JPY (approximate)
JPY_TO_USD_RATE = 0.0067


def convert_to_usd(price: float, currency: str) -> float:
    """Convert price to USD"""
    if currency == 'JPY':
        return round(price * JPY_TO_USD_RATE, 2)
    return round(price, 2)


class PriceService:
    """Service for price calculations and aggregations"""

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get summary statistics for dashboard"""
        today = datetime.utcnow().date()
        today_start = datetime.combine(today, datetime.min.time())

        total_products = Product.query.filter_by(is_active=True).count()
        prices_today = PriceHistory.query.filter(
            PriceHistory.scraped_at >= today_start
        ).count()

        last_price = PriceHistory.query.order_by(
            PriceHistory.scraped_at.desc()
        ).first()

        last_update = None
        if last_price:
            last_update = last_price.scraped_at.strftime('%Y-%m-%d %H:%M UTC')

        return {
            'total_products': total_products,
            'prices_today': prices_today,
            'last_update': last_update,
        }

    def get_latest_prices(self, product_id: int) -> List[Dict[str, Any]]:
        """Get latest prices for a product from all retailers (all converted to USD)"""
        retailers = Retailer.query.filter_by(is_active=True).all()
        prices = []

        for retailer in retailers:
            latest = PriceHistory.query.filter_by(
                product_id=product_id,
                retailer_id=retailer.id
            ).order_by(PriceHistory.scraped_at.desc()).first()

            if latest:
                original_price = float(latest.price)
                price_usd = convert_to_usd(original_price, latest.currency)

                prices.append({
                    'retailer': retailer.name,
                    'retailer_slug': retailer.slug,
                    'retailer_id': retailer.id,
                    'price': price_usd,
                    'price_original': original_price,
                    'currency': 'USD',
                    'currency_original': latest.currency,
                    'in_stock': latest.in_stock,
                    'scraped_at': latest.scraped_at.isoformat(),
                    'source_url': latest.source_url
                })

        return prices

    def get_best_price(self, product_id: int) -> Dict[str, Any]:
        """Get the best (lowest) current price for a product"""
        prices = self.get_latest_prices(product_id)

        if not prices:
            return None

        # Filter to in-stock items and find lowest
        in_stock_prices = [p for p in prices if p['in_stock']]

        if in_stock_prices:
            return min(in_stock_prices, key=lambda x: x['price'])

        # If nothing in stock, return lowest anyway
        return min(prices, key=lambda x: x['price'])
