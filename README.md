# Dhruvan's Stocks Dashboard

A self-contained HTML dashboard showing ~4,000+ NSE & BSE stocks with
price performance since March 2020. Daily close prices come from Yahoo
Finance; live market caps and sector tags come from BSE. The dashboard
is rebuilt every night at **8:00 PM IST** by a GitHub Actions cron.

## Live dashboard

After you push this repo and enable GitHub Pages:

```
https://<your-username>.github.io/<repo-name>/nse-bse-dashboard.html
```

## What the workflow does

Every day at 14:30 UTC (20:00 IST) `/.github/workflows/refresh.yml`:

1. Downloads NSE's public `EQUITY_L.csv` and BSE's active-scrip JSON.
2. Runs `scripts/fetch_all.py` — pulls ~6 years of daily close prices
   for every ticker from Yahoo Finance (parallel curl).
3. Runs `scripts/fetch_sectors.py` — fetches sector/industry tags from
   BSE's `ComHeadernew` endpoint.
4. Runs `scripts/build_compressed.py` — compacts, gzip-compresses,
   base64-encodes the payload and bakes it into a single-file HTML
   that ships to `docs/nse-bse-dashboard.html`.
5. Commits the updated HTML to `main`. GitHub Pages serves it.

Typical runtime: ~8 minutes on an Ubuntu runner. Timeout is 30 minutes.

## First-time setup

```bash
# 1. Create an empty repo on GitHub (public, so Pages works on free tier)
# 2. From this folder, push:
git init
git add .
git commit -m "Initial dashboard + daily-refresh workflow"
git branch -M main
git remote add origin https://github.com/<your-username>/<repo-name>.git
git push -u origin main

# 3. In the repo on GitHub: Settings -> Pages
#      Source: Deploy from a branch
#      Branch: main, folder: /docs
#      Save. The dashboard URL becomes live in ~1 minute.

# 4. Optional: Actions -> Daily stock data refresh -> Run workflow
#    (to verify the pipeline end-to-end before tomorrow's 8 PM cron)
```

## Manual refresh

Push any commit, or go to the Actions tab and click **Run workflow**.

## Local preview

Just open `docs/nse-bse-dashboard.html` in Chrome. Everything is
self-contained — no server needed.

## Notes, caveats

- Yahoo Finance rate-limits aggressive Python clients. We fetch via
  `subprocess.run(["curl", ...])`, which uses a TLS fingerprint Yahoo
  accepts. Azure-hosted GitHub runner IPs occasionally get throttled —
  if a run returns <80% success, re-run the workflow.
- BSE's `ComHeadernew` endpoint returns partial data on ~25% of scrips
  (usually illiquid SMEs). Those stocks show as **Uncategorized**.
- Daily close prices are split/dividend-adjusted (Yahoo's adj close
  isn't used — we use the raw `close` array, which equals adj close
  for recent history).
- The dashboard is a single 14 MB HTML. The data is embedded as
  gzip+base64 and decoded in-browser via `DecompressionStream`
  (Chrome 80+, Edge, Safari 16+, Firefox 113+).

## Repo layout

```
.github/workflows/refresh.yml   Daily cron + Actions pipeline
scripts/fetch_all.py            Yahoo Finance downloader
scripts/fetch_sectors.py        BSE sector enrichment
scripts/build_compressed.py     HTML builder
docs/nse-bse-dashboard.html     The dashboard (committed by CI)
docs/index.html                 Redirect to the dashboard
```
