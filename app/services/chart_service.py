from typing import Dict, Any, Optional
from datetime import datetime, timedelta

from app.models.price import PriceHistory
from app.models.retailer import Retailer
from app.services.price_service import convert_to_usd


class ChartService:
    """Service for preparing chart data"""

    RETAILER_COLORS = {
        'amazon-jp': 'rgb(255, 153, 0)',
        'tcgrepublic': 'rgb(75, 192, 192)',
        'ebay': 'rgb(255, 99, 132)',
        'buyee': 'rgb(54, 162, 235)',
    }

    def get_price_chart_data(self, product_id: int, days: int = 30,
                             retailer_id: Optional[int] = None) -> Dict[str, Any]:
        """Get price history formatted for Chart.js line chart (all prices in USD)"""
        start_date = datetime.utcnow() - timedelta(days=days)

        query = PriceHistory.query.filter(
            PriceHistory.product_id == product_id,
            PriceHistory.scraped_at >= start_date
        )

        if retailer_id:
            query = query.filter_by(retailer_id=retailer_id)

        prices = query.order_by(PriceHistory.scraped_at).all()

        # Group by retailer for multi-line chart
        datasets = {}
        retailers = Retailer.query.filter_by(is_active=True).all()
        retailer_map = {r.id: r for r in retailers}

        for price in prices:
            retailer = retailer_map.get(price.retailer_id)
            if not retailer:
                continue

            if retailer.slug not in datasets:
                datasets[retailer.slug] = {
                    'label': retailer.name,
                    'data': [],
                    'borderColor': self.RETAILER_COLORS.get(
                        retailer.slug, 'rgb(128, 128, 128)'
                    ),
                    'fill': False,
                    'tension': 0.1
                }

            # Convert to USD
            price_usd = convert_to_usd(float(price.price), price.currency)

            datasets[retailer.slug]['data'].append({
                'x': price.scraped_at.isoformat(),
                'y': price_usd
            })

        return {
            'datasets': list(datasets.values())
        }

    def get_comparison_data(self, product_id: int) -> Dict[str, Any]:
        """Get current prices for bar chart comparison (all prices in USD)"""
        retailers = Retailer.query.filter_by(is_active=True).all()

        labels = []
        prices = []
        colors = []

        color_map = {
            'amazon-jp': 'rgba(255, 153, 0, 0.8)',
            'tcgrepublic': 'rgba(75, 192, 192, 0.8)',
            'ebay': 'rgba(255, 99, 132, 0.8)',
            'buyee': 'rgba(54, 162, 235, 0.8)',
        }

        for retailer in retailers:
            latest = PriceHistory.query.filter_by(
                product_id=product_id,
                retailer_id=retailer.id
            ).order_by(PriceHistory.scraped_at.desc()).first()

            if latest:
                labels.append(retailer.name)
                # Convert to USD
                price_usd = convert_to_usd(float(latest.price), latest.currency)
                prices.append(price_usd)
                colors.append(color_map.get(retailer.slug, 'rgba(128, 128, 128, 0.8)'))

        return {
            'labels': labels,
            'datasets': [{
                'label': 'Current Price (USD)',
                'data': prices,
                'backgroundColor': colors
            }]
        }
