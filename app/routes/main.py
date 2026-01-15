from flask import Blueprint, render_template, request
from app.models.product import Product
from app.models.retailer import Retailer
from app.services.price_service import PriceService

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def dashboard():
    """Main dashboard with price overview"""
    products = Product.query.filter_by(is_active=True).order_by(Product.set_code).all()
    retailers = Retailer.query.filter_by(is_active=True).all()

    price_service = PriceService()
    price_summary = price_service.get_dashboard_summary()

    return render_template('dashboard.html',
                           products=products,
                           retailers=retailers,
                           price_summary=price_summary)


@main_bp.route('/products')
def product_list():
    """List all tracked products"""
    product_type = request.args.get('type')

    query = Product.query.filter_by(is_active=True)
    if product_type:
        query = query.filter_by(product_type=product_type)

    products = query.order_by(Product.release_date.desc()).all()

    return render_template('products/list.html', products=products)


@main_bp.route('/products/<int:product_id>')
def product_detail(product_id):
    """Product detail with price history chart"""
    product = Product.query.get_or_404(product_id)
    retailers = Retailer.query.filter_by(is_active=True).all()

    price_service = PriceService()
    latest_prices = price_service.get_latest_prices(product_id)
    best_price = price_service.get_best_price(product_id)

    return render_template('products/detail.html',
                           product=product,
                           retailers=retailers,
                           latest_prices=latest_prices,
                           best_price=best_price)
