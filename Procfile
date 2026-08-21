web: gunicorn wsgi:app --timeout 300
scraper: python scripts/run_scraper.py
pricesync: python scripts/run_price_sync.py --refresh-prices --email
weeklyreport: python scripts/run_weekly_business_report.py
