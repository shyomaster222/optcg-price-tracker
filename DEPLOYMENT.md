# Deployment Guide

## Recommended Hosting: Railway

**Railway** is the best fit for this app:

- **Already configured** – `railway.toml` and `Procfile` are set up
- **Simple deploy** – Push to GitHub, connect repo, done
- **PostgreSQL included** – Free database with $5 monthly credit
- **Cron jobs** – Native support for scheduled scraping
- **Usage-based pricing** – ~$5–10/month for a small app

### Alternatives

| Platform | Pros | Cons |
|----------|------|-----|
| **Render** | Free web tier, managed Postgres | Cron jobs cost $1/mo; free instances sleep after 15 min |
| **Fly.io** | Global regions, low latency | More setup, you manage more |
| **PythonAnywhere** | Python-focused, free tier | Limited CPU (100 sec/day), not ideal for scrapers |

---

## Deploy to Railway

### 1. Create a Railway account

Sign up at [railway.app](https://railway.app).

### 2. New project from GitHub

1. Click **New Project** → **Deploy from GitHub repo**
2. Connect your GitHub account and select this repository
3. Railway will detect the project and create a web service

### 3. Add PostgreSQL

1. In your project, click **+ New** → **Database** → **PostgreSQL**
2. Railway creates a database and sets `DATABASE_URL`

### 4. Configure environment variables

In your web service → **Variables**, add:

```
# Required (Railway sets DATABASE_URL)
FLASK_ENV=production
SECRET_KEY=your-random-secret-key-here

# eBay API (required for eBay prices)
EBAY_APP_ID=YourApp-PRD-xxxxxxxx-xxxxxxxx
EBAY_CERT_ID=PRD-xxxxxxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxx

# Disable in-process scheduler when using Railway Cron (see step 6)
ENABLE_IN_PROCESS_SCHEDULER=false
```

Create a strong `SECRET_KEY` (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`).

### 5. Deploy

- Railway deploys on each push to your main branch
- After deploy, open the generated URL (e.g. `https://your-app.up.railway.app`)

### 6. Seed the database (first run)

Use Railway CLI or the **Run Command**:

```bash
python scripts/seed_products.py
```

---

## Automatic price updates every 24 hours

### Option A: Railway Cron (recommended)

A separate cron service runs the scraper daily:

1. **New service from GitHub**
   - **+ New** → **GitHub Repo** → same repo
   - Name it `price-scraper` (or similar)

2. **Configure as Cron**
   - Open the new service → **Settings**
   - Find **Cron Schedule**
   - Set: `0 0 * * *` (every day at midnight UTC)
   - Set **Start Command**: `python scripts/run_scraper.py`

3. **Start command** for the cron service:
   - Use: `python scripts/run_scraper.py`
   - (Or the `scraper` process type from the Procfile if your platform supports it)

4. **Variables** – Cron uses the same project; `DATABASE_URL`, `EBAY_APP_ID`, and `EBAY_CERT_ID` from the web service apply.

5. **Disable in-process scheduler** (if not already):
   - In the **web** service: `ENABLE_IN_PROCESS_SCHEDULER=false`
   - This avoids duplicate scrapes

Cron services must finish and exit; `run_scraper.py` does this. A full scrape can take 30–60 minutes; Railway will keep the cron process running until it completes.

### Option B: In-process scheduler (one service)

If you prefer a single service:

1. **Do not set** `ENABLE_IN_PROCESS_SCHEDULER` (or set it to `true`)
2. **Procfile** uses `--workers 1` so only one process runs the scheduler
3. Scrape runs daily at **00:00 UTC**

This is simpler but ties scraping to the web process and may be less robust under scaling or restarts.

---

## Cron schedule examples

| Schedule   | Expression    | Meaning                         |
|-----------|---------------|----------------------------------|
| Daily 00:00 UTC | `0 0 * * *`   | Every day at midnight           |
| Daily 06:00 UTC | `0 6 * * *`   | Every day at 6:00               |
| Every 12 hours | `0 */12 * * *` | Every 12 hours                  |

---

## Troubleshooting

### Scraper times out

- Increase service resources or timeout
- Use `--limit` for a quick test: `python scripts/run_scraper.py --limit 5`

### eBay returns no prices

- Confirm `EBAY_APP_ID` and `EBAY_CERT_ID` in variables
- Check [eBay Developer](https://developer.ebay.com) for key status and quotas

### Database connection issues

- Ensure the cron service can reach the same `DATABASE_URL` as the web service
- In Railway, variables set at project level are available to all services
