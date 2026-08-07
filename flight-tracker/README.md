# Flight price tracker: Melbourne (MEL) -> Kathmandu (KTM)

Tracks round-trip Economy fares for 2 adults, once a day, with no computer of
yours needing to be on. Runs on GitHub Actions, logs every run to
`data/price-history.csv`, and emails you only when the price actually moves.

**Reminder: do not book until Bridging Visa B is granted.** This script only
tracks and alerts — it never books or holds a fare.

## What it checks

1. **Primary dates**: depart 2026-11-03, return 2026-12-23.
2. **Flexible sweep**: samples ~6 depart dates spread across 1-20 Nov 2026,
   each paired with whichever return date (15 Dec 2026 - 5 Jan 2027) lands
   closest to a 44-day trip (the midpoint of your 38-50 day range). This is a
   sample, not an exhaustive search of every combination — that would be
   hundreds of paid API calls a day. Adjust `FLEX_DEPART_SAMPLE_STEP_DAYS` in
   `track_flights.py` if you want a denser (more expensive) sweep.

## Ranking rules (applied to every search)

An itinerary is dropped if any of these are true:
- More than 1 stop
- Total duration over 20 hours
- Any single layover under 90 minutes or over 6 hours
- Routes through a mainland-China hub (CAN — Guangzhou, TFU — Chengdu Tianfu)
- Flagged `often_delayed_by_over_30_min` on any leg

Whatever survives, the cheapest total price for 2 passengers wins.

## Data source: Apify

Uses the Apify actor **`johnvc/Google-Flights-Data-Scraper-Flight-and-Price-Search`**
via the plain REST API (`run-sync-get-dataset-items`), so the GitHub Actions
job needs nothing but Python's standard library — no `pip install` required.

Pricing is pay-per-event (roughly $0.01-0.04 per search including 1 processed
page). One daily run does ~7 searches (1 primary + ~6 flexible legs), so
expect well under $1/month.

### If Apify stops being workable

The alternative is **SerpApi's Google Flights API**
(https://serpapi.com/google-flights-api) — sign up for a SerpApi account, get
an API key from the dashboard, and the JSON shape is very similar (it's the
same underlying Google Flights data). You'd swap `run_apify_actor()` /
`search_flights()` in `track_flights.py` for a call to
`https://serpapi.com/search.json?engine=google_flights&...&api_key=...`
and re-map field names (SerpApi uses `best_flights` / `other_flights` with
the same `flights[]` / `layovers[]` shape, so the filtering logic in
`extract_itineraries()` needs only minor changes).

## One-time setup

### 1. Apify account + token

1. Sign up / log in at https://apify.com.
2. Open **Settings -> Integrations** and copy your **Personal API token**.
   (You don't need to manually configure the actor — the script calls it
   directly by name, and Apify will run it on your account the first time it
   fires.)

### 2. Email alerts (SMTP)

Any SMTP account works. Easiest path with Gmail:

1. Turn on 2-Step Verification on the Google account you want to send from:
   https://myaccount.google.com/security
2. Create an **App Password**: https://myaccount.google.com/apppasswords
   (choose "Mail" / "Other", name it "flight-tracker") — copy the 16-character
   password.
3. Your values will be:
   - `SMTP_HOST` = `smtp.gmail.com`
   - `SMTP_PORT` = `587`
   - `SMTP_USER` = your Gmail address
   - `SMTP_PASSWORD` = the app password from step 2
   - `ALERT_EMAIL_TO` = wherever you want the alert sent (can be the same address)
   - `ALERT_EMAIL_FROM` = optional, defaults to `SMTP_USER`

Any other provider (Outlook, Fastmail, a custom domain) works the same way —
just use that provider's SMTP host/port and an app-specific password if it
requires one.

### 3. Add GitHub Secrets

In this repo on GitHub: **Settings -> Secrets and variables -> Actions -> New
repository secret**. Add each of:

| Secret name | Value |
|---|---|
| `APIFY_API_TOKEN` | Your Apify personal API token |
| `SMTP_HOST` | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | e.g. `587` |
| `SMTP_USER` | Your sending email address |
| `SMTP_PASSWORD` | App password (never your normal account password) |
| `ALERT_EMAIL_TO` | Where alerts should land |
| `ALERT_EMAIL_FROM` | Optional — omit to default to `SMTP_USER` |

### 4. Confirm the workflow file

The workflow lives at `.github/workflows/flight-price-tracker.yml` in the repo
root (not inside `flight-tracker/`, since GitHub only reads workflows from
`.github/workflows/`). It:

- Runs on a daily cron (`0 20 * * *` = 20:00 UTC — adjust the hour to suit
  your timezone; comment in the file has the AEDT/AEST conversion).
- Can also be triggered manually from the **Actions** tab
  ("Flight price tracker (MEL -> KTM)" -> **Run workflow**) — use this for a
  first test run instead of waiting for the schedule.
- Commits the updated `flight-tracker/data/price-history.csv` back to the
  repo after each run.

**Important:** GitHub only fires `schedule:` triggers on the repository's
**default branch**. If you're working on a feature branch, merge this
workflow into `main` (or whatever your default branch is) before the cron
will actually run — until then, use "Run workflow" manually to test.

### 5. Test it

After adding the secrets and merging to your default branch:

1. Go to **Actions -> Flight price tracker (MEL -> KTM) -> Run workflow**.
2. Watch the run. On success you should see a new row (or several — one per
   search type) appended to `flight-tracker/data/price-history.csv`, committed
   back automatically.
3. No email should arrive on the very first run for a route (there's no prior
   price to compare against yet — that's intentional, see below).
4. Run it again later (or manually edit a price down in the CSV to simulate a
   drop) to confirm the alert email fires.

You can also run it locally to test without waiting on GitHub Actions:

```bash
cd flight-tracker
APIFY_API_TOKEN=xxx \
SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=you@gmail.com \
SMTP_PASSWORD=app-password ALERT_EMAIL_TO=you@gmail.com \
python3 track_flights.py
```

## Alerting logic

You get an email only when, for either the primary-dates search or the
flexible sweep:

- the new cheapest clean price is **more than 5% lower** than the previous
  run's cheapest clean price for that same search type, **or**
- the new price is a **new all-time low** compared to every previous run.

The very first recorded run for a search type never alerts (nothing to
compare against yet). Otherwise, no change / a price increase / a small drop
= silence, by design.

## Files

| File | Purpose |
|---|---|
| `track_flights.py` | Main script: search, filter, rank, log, alert |
| `data/price-history.csv` | Append-only log of every run |
| `requirements.txt` | Stdlib-only; present for future dependencies |
| `../.github/workflows/flight-price-tracker.yml` | Daily schedule + manual trigger |
