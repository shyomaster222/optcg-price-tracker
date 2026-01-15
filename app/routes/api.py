from flask import Blueprint, jsonify, request
from app.models.product import Product
from app.models.price import PriceHistory
from app.models.retailer import Retailer
from app.services.chart_service import ChartService
from app.services.price_service import PriceService

api_bp = Blueprint('api', __name__, url_prefix='/api')


@api_bp.route('/prices/<int:product_id>')
def get_price_history(product_id):
    """Get price history for Chart.js"""
    days = request.args.get('days', 30, type=int)
    retailer_id = request.args.get('retailer_id', type=int)

    chart_service = ChartService()
    data = chart_service.get_price_chart_data(
        product_id=product_id,
        days=days,
        retailer_id=retailer_id
    )

    return jsonify(data)


@api_bp.route('/prices/compare')
def compare_prices():
    """Get current prices across all retailers for comparison"""
    product_id = request.args.get('product_id', type=int)

    if not product_id:
        return jsonify({'error': 'product_id required'}), 400

    chart_service = ChartService()
    data = chart_service.get_comparison_data(product_id)

    return jsonify(data)


@api_bp.route('/products/<int:product_id>/latest')
def get_latest_prices(product_id):
    """Get latest prices from all retailers"""
    product = Product.query.get_or_404(product_id)

    price_service = PriceService()
    prices = price_service.get_latest_prices(product_id)

    return jsonify({
        'product': product.display_name,
        'prices': prices
    })


@api_bp.route('/products')
def list_products():
    """List all products with their latest prices"""
    product_type = request.args.get('type')

    query = Product.query.filter_by(is_active=True)
    if product_type:
        query = query.filter_by(product_type=product_type)

    products = query.order_by(Product.set_code).all()

    price_service = PriceService()

    result = []
    for product in products:
        best = price_service.get_best_price(product.id)
        result.append({
            'id': product.id,
            'set_code': product.set_code,
            'set_name': product.set_name,
            'product_type': product.product_type,
            'display_name': product.display_name,
            'best_price': best
        })

    return jsonify(result)


@api_bp.route('/scrape', methods=['POST'])
def trigger_scrape():
    """Trigger a manual scrape job (runs in background thread)"""
    import threading
    from flask import current_app
    from app.scrapers.scraper_manager import ScraperManager

    retailer_slug = request.args.get('retailer')

    def run_scrape(app, slug):
        with app.app_context():
            try:
                manager = ScraperManager()
                manager.run_scrape_job(slug)
            except Exception as e:
                print(f"Scrape error: {e}")

    # Run scrape in background thread
    app = current_app._get_current_object()
    thread = threading.Thread(target=run_scrape, args=(app, retailer_slug))
    thread.daemon = True
    thread.start()

    return jsonify({
        'status': 'started',
        'message': f'Scrape job started for {"all retailers" if not retailer_slug else retailer_slug}. Check back in a few minutes for results.'
    })
