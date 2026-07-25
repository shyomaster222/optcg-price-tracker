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

## Weekly business report — Friday 09:00 HKT

Run the weekly report as its own short-lived Railway cron service. Do not run
it from the web process.

### 1. Create the weekly service

1. In the same Railway project, choose **+ New** → **GitHub Repo** and select
   this repository again.
2. Name the service `weekly-report`.
3. In **Settings** → **Config as Code**, set **Config file path** to:
   `/railway.weekly-report.toml`
4. Do not add a public domain or a health check.
5. Give the service the same PostgreSQL `DATABASE_URL` as the web service,
   preferably with a Railway reference/shared variable.

The checked-in config runs:

```text
python scripts/run_weekly_business_report.py
```

with cron expression `0 1 * * 5`. Railway evaluates cron in UTC, so this is
Friday 01:00 UTC / Friday 09:00 Hong Kong time. The command is a one-shot
process and must exit when the report finishes.

### 2. Set weekly-report variables

Add these to the `weekly-report` service:

```dotenv
ENABLE_IN_PROCESS_SCHEDULER=false
WEEKLY_REPORT_ENABLED=true
WEEKLY_REPORT_EMAIL_TO=admin@rarecardsjapan.com
WEEKLY_REPORT_EMAIL_FROM=admin@rarecardsjapan.com
WEEKLY_REPORT_TIMEZONE=Asia/Hong_Kong
WEEKLY_REPORT_REVISION=1
WEEKLY_REPORT_LEASE_SECONDS=3600
WEEKLY_REPORT_SOURCE_TIMEOUT_SECONDS=45
WEEKLY_REPORT_B2B_TAGS=B2B,Wholesale

SHOPIFY_REPORT_SHOP=48wpjk-rh.myshopify.com
SHOPIFY_REPORT_API_VERSION=2026-07
SHOPIFY_REPORT_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SHOPIFY_REPORT_CLIENT_SECRET=shpss_xxxxxxxxxxxxxxxxxxxxxxxx

GSC_CLIENT_ID=xxxxxxxxxxxx.apps.googleusercontent.com
GSC_CLIENT_SECRET=GOCSPX_xxxxxxxxxxxxxxxxxxxx
GSC_REFRESH_TOKEN=1//xxxxxxxxxxxxxxxxxxxx
GSC_PROPERTY=sc-domain:rarecardsjapan.com

OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
OPENAI_WEEKLY_REPORT_MODEL=gpt-5.6-terra
OPENAI_WEEKLY_REPORT_TIMEOUT_SECONDS=30

RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxx
COMPANY_EMAIL=admin@rarecardsjapan.com
```

`WEEKLY_REPORT_EMAIL_TO` and `WEEKLY_REPORT_EMAIL_FROM` each fall back to
`COMPANY_EMAIL`, but setting them explicitly on the cron service makes the
delivery target auditable.

Create and install a dedicated Shopify Dev Dashboard app with only
`read_orders`, `read_all_orders`, and `read_products`. Set its client ID and
client secret as `SHOPIFY_REPORT_CLIENT_ID` and
`SHOPIFY_REPORT_CLIENT_SECRET`. Each report process exchanges those credentials
at `/admin/oauth/access_token` for a short-lived Admin API token and refreshes
it before expiry; the access token does not need to be stored in Railway.

For compatibility with an existing custom app, `SHOPIFY_REPORT_TOKEN` can be
used when both client-credential settings are unset. When client credentials
are present they take precedence. Never copy the write-capable
`SHOPIFY_ADMIN_TOKEN` into any reporting setting. The reporting shop, version,
and credentials are intentionally separate from `SHOPIFY_SHOP`,
`SHOPIFY_API_VERSION`, and `SHOPIFY_ADMIN_TOKEN` used by price sync.

The Google OAuth user represented by `GSC_REFRESH_TOKEN` must have access to
the property named by `GSC_PROPERTY`. The Resend sender must be on a verified
domain.

### 3. Deploy and verify

Deploy the service and confirm its settings show:

- Start command: `python scripts/run_weekly_business_report.py`
- Cron schedule: `0 1 * * 5`
- Restart policy: `Never`
- No public domain

Before enabling delivery, run a source-backed preview from Railway's **Run
Command**:

```bash
python scripts/run_weekly_business_report.py \
  --dry-run \
  --output /tmp/rcj-weekly-preview
```

The dry run fetches Shopify and Search Console and renders the complete HTML,
plain-text, and chart files, but does not call OpenAI, write report-run state,
or send email. After reviewing the preview, set
`WEEKLY_REPORT_ENABLED=true` and run:

```bash
python scripts/run_weekly_business_report.py
```

The database record for each Friday window and revision makes retries
resumable and delivery idempotent. Exit code `0` means the run was safely
handled. Exit code `1` is a generation or delivery failure. Exit code `2`
means delivery is disabled or its state is unknown and needs operator review.
An unknown delivery state is never resent automatically; reconcile the
provider message ID in Resend before using `--force-resend --window-end
YYYY-MM-DD`.

Pre-delivery failures attempt a concise failure notice through Resend. Also
configure Railway deployment/cron failure notifications so database failures
and email-provider outages are visible even when Resend itself is unavailable.

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
