import os


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return bool(default)
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


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
    ENABLE_IN_PROCESS_SCHEDULER = _env_bool(
        'ENABLE_IN_PROCESS_SCHEDULER',
        True,
    )

    # Scraping
    SCRAPER_DELAY_MIN = int(os.environ.get('SCRAPER_DELAY_MIN', 2))
    SCRAPER_DELAY_MAX = int(os.environ.get('SCRAPER_DELAY_MAX', 5))
    SCRAPER_REQUESTS_PER_MINUTE = int(os.environ.get('SCRAPER_REQUESTS_PER_MINUTE', 10))

    # Daily email (Resend)
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY')
    COMPANY_EMAIL = os.environ.get('COMPANY_EMAIL')

    # ------------------------------------------------------------------
    # Weekly business report
    # ------------------------------------------------------------------
    WEEKLY_REPORT_ENABLED = _env_bool('WEEKLY_REPORT_ENABLED', False)
    WEEKLY_REPORT_EMAIL_TO = (
        os.environ.get('WEEKLY_REPORT_EMAIL_TO') or COMPANY_EMAIL
    )
    WEEKLY_REPORT_EMAIL_FROM = (
        os.environ.get('WEEKLY_REPORT_EMAIL_FROM') or COMPANY_EMAIL
    )
    WEEKLY_REPORT_TIMEZONE = os.environ.get(
        'WEEKLY_REPORT_TIMEZONE',
        'Asia/Hong_Kong',
    )
    WEEKLY_REPORT_REVISION = int(
        os.environ.get('WEEKLY_REPORT_REVISION', '1')
    )
    WEEKLY_REPORT_LEASE_SECONDS = int(
        os.environ.get('WEEKLY_REPORT_LEASE_SECONDS', '3600')
    )
    WEEKLY_REPORT_SOURCE_TIMEOUT_SECONDS = float(
        os.environ.get('WEEKLY_REPORT_SOURCE_TIMEOUT_SECONDS', '45')
    )
    WEEKLY_REPORT_B2B_TAGS = os.environ.get(
        'WEEKLY_REPORT_B2B_TAGS',
        'B2B,Wholesale',
    )

    # Dedicated read-only Shopify reporting connection. Keeping these
    # separate prevents report deployments from changing the price-sync API.
    SHOPIFY_REPORT_SHOP = os.environ.get(
        'SHOPIFY_REPORT_SHOP',
        '48wpjk-rh.myshopify.com',
    )
    SHOPIFY_REPORT_API_VERSION = os.environ.get(
        'SHOPIFY_REPORT_API_VERSION',
        '2026-07',
    )
    SHOPIFY_REPORT_TOKEN = os.environ.get('SHOPIFY_REPORT_TOKEN')

    # ------------------------------------------------------------------
    # Price sync (RCJ Shopify <- Fuji, undercut)
    # ------------------------------------------------------------------
    # Shopify Admin API (create a custom app in the RCJ store with write_products)
    SHOPIFY_SHOP = os.environ.get('SHOPIFY_SHOP', 'rare-cards-japan.myshopify.com')
    SHOPIFY_ADMIN_TOKEN = os.environ.get('SHOPIFY_ADMIN_TOKEN')
    SHOPIFY_API_VERSION = os.environ.get('SHOPIFY_API_VERSION', '2025-01')

    # Google Search Console OAuth
    GSC_CLIENT_ID = os.environ.get('GSC_CLIENT_ID')
    GSC_CLIENT_SECRET = os.environ.get('GSC_CLIENT_SECRET')
    GSC_REFRESH_TOKEN = os.environ.get('GSC_REFRESH_TOKEN')
    GSC_PROPERTY = os.environ.get(
        'GSC_PROPERTY',
        'sc-domain:rarecardsjapan.com',
    )

    # OpenAI narrative generation
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    OPENAI_WEEKLY_REPORT_MODEL = os.environ.get(
        'OPENAI_WEEKLY_REPORT_MODEL',
        'gpt-5.6-terra',
    )
    OPENAI_WEEKLY_REPORT_TIMEOUT_SECONDS = float(
        os.environ.get('OPENAI_WEEKLY_REPORT_TIMEOUT_SECONDS', '30')
    )

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
    ENABLE_IN_PROCESS_SCHEDULER = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
