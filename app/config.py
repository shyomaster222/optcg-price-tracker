import os

class Config:
    """Base configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

    # Database - Railway provides DATABASE_URL for PostgreSQL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///optcg_prices.db')

    # Fix for Railway PostgreSQL (postgres:// -> postgresql://)
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace('postgres://', 'postgresql://', 1)

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # APScheduler
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = 'UTC'

    # Scraping
    SCRAPER_DELAY_MIN = int(os.environ.get('SCRAPER_DELAY_MIN', 2))
    SCRAPER_DELAY_MAX = int(os.environ.get('SCRAPER_DELAY_MAX', 5))
    SCRAPER_REQUESTS_PER_MINUTE = int(os.environ.get('SCRAPER_REQUESTS_PER_MINUTE', 10))

    # Daily email (Resend)
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
    COMPANY_EMAIL = os.environ.get('COMPANY_EMAIL')

    # ------------------------------------------------------------------
    # Price sync (RCJ Shopify <- Fuji, undercut)
    # ------------------------------------------------------------------
    # Shopify Admin API (create a custom app in the RCJ store with write_products)
    SHOPIFY_SHOP = os.environ.get('SHOPIFY_SHOP', 'rare-cards-japan.myshopify.com')
    SHOPIFY_ADMIN_TOKEN = os.environ.get('SHOPIFY_ADMIN_TOKEN')
    SHOPIFY_API_VERSION = os.environ.get('SHOPIFY_API_VERSION', '2025-01')

    # Master switches
    PRICE_SYNC_ENABLED = os.environ.get('PRICE_SYNC_ENABLED', 'false').lower() == 'true'
    # Dry run: compute + log + email, but never write to Shopify. Default TRUE (safe).
    PRICE_SYNC_DRY_RUN = os.environ.get('PRICE_SYNC_DRY_RUN', 'true').lower() == 'true'

    # Pricing rule + guardrails (all fractions, e.g. 0.03 = 3%)
    UNDERCUT_PCT = float(os.environ.get('UNDERCUT_PCT', '0.03'))       # target = fuji * (1 - this)
    AUTO_TOLERANCE = float(os.environ.get('AUTO_TOLERANCE', '0.05'))   # auto-apply if |change| <= this
    MAX_DROP = float(os.environ.get('MAX_DROP', '0.30'))              # relative safety floor vs current
    FUJI_FRESH_HOURS = int(os.environ.get('FUJI_FRESH_HOURS', '48'))  # ignore Fuji prices older than this
    # Rounding of the target price: "dollar" (nearest whole $), "cent" (2 dp), "99" (.99 ending)
    PRICE_ROUNDING = os.environ.get('PRICE_ROUNDING', 'dollar')

    # Config file locations (repo-root relative by default)
    PRICE_MAP_PATH = os.environ.get('PRICE_MAP_PATH', 'price_map.json')
    PRICE_FLOORS_PATH = os.environ.get('PRICE_FLOORS_PATH', 'price_floors.json')


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
