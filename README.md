# OPTCG Price Tracker

A web application to track and compare prices for Japanese One Piece TCG sealed products (booster boxes and cases) across multiple retailers.

## Features

- Track prices from Amazon Japan, TCGRepublic, eBay, and more
- Price history charts with 30/60/90 day views
- Compare prices across retailers
- Automated scraping every 24 hours (configurable)
- Best price highlighting
- Stock availability tracking

## Products Tracked

- All main booster sets (OP-01 through OP-12)
- Extra boosters (EB-01, EB-02, EB-03)
- Premium boosters (PRB-01)
- Both booster boxes and sealed cases

## Quick Start

### 1. Clone and Setup

```bash
cd optcg-price-tracker

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 2. Configure Environment

```bash
# Copy example env file
cp .env.example .env

# Edit .env with your settings (optional)
```

### 3. Initialize Database

```bash
# Seed the database with products and retailers
python scripts/seed_products.py
```

### 4. Run the Application

```bash
# Development server
python wsgi.py

# Or use Flask CLI
flask run
```

Visit `http://localhost:5000` in your browser.

## Deploy to Production

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for:

- **Railway** (recommended) – deploy and run daily scrapes via cron
- **Render** and other hosts
- How to set up 24-hour automatic price updates

## Manual Scraping

```bash
# Scrape all retailers
python scripts/run_scraper.py

# Scrape specific retailer
python scripts/run_scraper.py tcgrepublic

# List available retailers
python scripts/run_scraper.py --list
```

## Project Structure

```
optcg-price-tracker/
├── app/
│   ├── models/          # Database models
│   ├── routes/          # Flask routes and API
│   ├── scrapers/        # Web scrapers for each retailer
│   ├── services/        # Business logic
│   ├── tasks/           # Scheduled jobs
│   ├── templates/       # Jinja2 templates
│   └── static/          # CSS, JS, images
├── scripts/             # CLI utilities
├── requirements.txt
└── wsgi.py              # Application entry point
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/products` | List all products with best prices |
| `GET /api/products/<id>/latest` | Get latest prices for a product |
| `GET /api/prices/<id>` | Get price history (query: days, retailer_id) |
| `GET /api/prices/compare` | Compare prices across retailers |

## Retailers Supported

| Retailer | Currency | Notes |
|----------|----------|-------|
| Amazon Japan | JPY | Search-based scraping |
| TCGRepublic | USD | Direct search |
| eBay | USD | Filter for Japanese products |

## Adding New Retailers

1. Create a new scraper in `app/scrapers/` extending `BaseScraper`
2. Implement `build_search_url()`, `parse_price()`, and `parse_stock_status()`
3. Register the scraper in `ScraperManager.SCRAPER_CLASSES`
4. Add the retailer to the seed script

## Technologies

- **Backend:** Python 3.11+, Flask
- **Database:** SQLite (dev) / PostgreSQL (prod)
- **Scraping:** Playwright
- **Frontend:** Bootstrap 5, Chart.js
- **Scheduling:** Flask-APScheduler

## License

MIT License
