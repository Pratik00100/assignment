#!/usr/bin/env python3
"""
Flight price tracker for MEL <-> KTM (Melbourne to Kathmandu), round trip.

Queries the Apify actor "johnvc/Google-Flights-Data-Scraper-Flight-and-Price-Search"
for a primary fixed-date search plus a flexible date sweep, applies a set of
"clean itinerary" filters, ranks what's left by price, appends the result to a
CSV price-history log, and sends an email alert if the price dropped
meaningfully or hit a new all-time low.

Reminder: do not book until Bridging Visa B is granted. This script only
tracks and alerts on prices -- it never books or holds anything.

Run manually:
    APIFY_API_TOKEN=xxx python3 track_flights.py

Run in GitHub Actions: see ../.github/workflows/flight-price-tracker.yml
"""

from __future__ import annotations

import csv
import json
import os
import smtplib
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

APIFY_ACTOR = "johnvc/Google-Flights-Data-Scraper-Flight-and-Price-Search"
APIFY_API_BASE = "https://api.apify.com/v2"

ORIGIN = "MEL"
DESTINATION = "KTM"
ADULTS = 2
CURRENCY = "AUD"
COUNTRY = "au"
LANGUAGE = "en"

PRIMARY_DEPART = "2026-11-03"
PRIMARY_RETURN = "2026-12-23"

# Flexible sweep: depart anywhere 1-20 Nov 2026, return anywhere
# 15 Dec 2026 - 5 Jan 2027, trip length 38-50 days. Checking every possible
# combination would be hundreds of paid searches, so we sample a small,
# evenly-spaced grid of depart dates and pair each with the return date that
# lands closest to a 44-day (midpoint of 38-50) trip length, within range.
FLEX_DEPART_START = date(2026, 11, 1)
FLEX_DEPART_END = date(2026, 11, 20)
FLEX_RETURN_START = date(2026, 12, 15)
FLEX_RETURN_END = date(2027, 1, 5)
FLEX_TRIP_LEN_MIN = 38
FLEX_TRIP_LEN_MAX = 50
FLEX_DEPART_SAMPLE_STEP_DAYS = 4  # ~5 sampled depart dates across the window
FLEX_TARGET_TRIP_LEN = 44

# Ranking / filtering rules
MAX_STOPS = 1
MAX_TOTAL_DURATION_MIN = 20 * 60
MIN_LAYOVER_MIN = 90
MAX_LAYOVER_MIN = 6 * 60
BANNED_HUB_CODES = {"CAN", "TFU"}  # mainland-China hub routings to avoid

DATA_DIR = Path(__file__).parent / "data"
HISTORY_CSV = DATA_DIR / "price-history.csv"
CSV_FIELDS = [
    "run_timestamp",
    "search_type",
    "depart_date",
    "return_date",
    "trip_length_days",
    "cheapest_clean_price",
    "currency",
    "airline",
    "flight_numbers",
    "stops",
    "duration_minutes",
    "layover_airports",
    "candidates_considered",
    "candidates_after_filter",
]

PRICE_DROP_ALERT_PCT = 5.0

BOOKING_REMINDER = "Reminder: do not book until Bridging Visa B is granted."


# ---------------------------------------------------------------------------
# Apify call
# ---------------------------------------------------------------------------

def run_apify_actor(token: str, input_payload: dict, timeout_secs: int = 120) -> list[dict]:
    """Runs the actor synchronously via the run-sync-get-dataset-items endpoint
    and returns the dataset items (should be a single search result item)."""
    actor_path = APIFY_ACTOR.replace("/", "~")
    url = (
        f"{APIFY_API_BASE}/acts/{actor_path}/run-sync-get-dataset-items"
        f"?token={token}&timeout={timeout_secs}"
    )
    body = json.dumps(input_payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_secs + 30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Apify actor call failed ({e.code}): {detail}") from e


def search_flights(token: str, depart_date: str, return_date: str) -> dict | None:
    payload = {
        "departure_id": ORIGIN,
        "arrival_id": DESTINATION,
        "outbound_date": depart_date,
        "return_date": return_date,
        "adults": ADULTS,
        "currency": CURRENCY,
        "gl": COUNTRY,
        "hl": LANGUAGE,
        "max_pages": 1,
    }
    items = run_apify_actor(token, payload)
    if not items:
        return None
    return items[0]


# ---------------------------------------------------------------------------
# Filtering / ranking
# ---------------------------------------------------------------------------

@dataclass
class Itinerary:
    price: float
    currency: str
    airlines: str
    flight_numbers: str
    stops: int
    total_duration_min: int
    layover_airports: list[str] = field(default_factory=list)
    layover_durations_min: list[int] = field(default_factory=list)
    often_delayed: bool = False


def extract_itineraries(search_result: dict) -> list[Itinerary]:
    """Combines best_flights + other_flights (which carry per-layover
    durations) into a flat list of Itinerary objects."""
    out: list[Itinerary] = []
    for bucket in ("best_flights", "other_flights"):
        for entry in search_result.get(bucket, []) or []:
            legs = entry.get("flights", []) or []
            layovers = entry.get("layovers", []) or []
            airlines = ", ".join(sorted({leg.get("airline", "") for leg in legs if leg.get("airline")}))
            flight_numbers = ", ".join(leg.get("flight_number", "") for leg in legs if leg.get("flight_number"))
            often_delayed = any(leg.get("often_delayed_by_over_30_min") for leg in legs)
            out.append(
                Itinerary(
                    price=entry.get("price") or 0,
                    currency=search_result.get("search_parameters", {}).get("currency", CURRENCY),
                    airlines=airlines or "unknown",
                    flight_numbers=flight_numbers,
                    stops=max(len(legs) - 1, 0),
                    total_duration_min=entry.get("total_duration") or 0,
                    layover_airports=[lo.get("id", "") for lo in layovers],
                    layover_durations_min=[lo.get("duration") or 0 for lo in layovers],
                    often_delayed=often_delayed,
                )
            )
    return out


def passes_filters(it: Itinerary) -> bool:
    if it.price <= 0:
        return False
    if it.stops > MAX_STOPS:
        return False
    if it.total_duration_min > MAX_TOTAL_DURATION_MIN:
        return False
    if it.often_delayed:
        return False
    if any(code in BANNED_HUB_CODES for code in it.layover_airports):
        return False
    for dur in it.layover_durations_min:
        if dur < MIN_LAYOVER_MIN or dur > MAX_LAYOVER_MIN:
            return False
    return True


def cheapest_clean(itineraries: list[Itinerary]) -> Itinerary | None:
    clean = [it for it in itineraries if passes_filters(it)]
    if not clean:
        return None
    return min(clean, key=lambda it: it.price)


# ---------------------------------------------------------------------------
# Flexible date sweep
# ---------------------------------------------------------------------------

def sampled_flex_depart_dates() -> list[date]:
    dates = []
    d = FLEX_DEPART_START
    while d <= FLEX_DEPART_END:
        dates.append(d)
        d += timedelta(days=FLEX_DEPART_SAMPLE_STEP_DAYS)
    if dates[-1] != FLEX_DEPART_END:
        dates.append(FLEX_DEPART_END)
    return dates


def best_return_for_depart(depart: date) -> date | None:
    """Pick the return date closest to the target trip length that is both
    inside the flexible return window and inside the trip-length window."""
    best = None
    best_diff = None
    for length in range(FLEX_TRIP_LEN_MIN, FLEX_TRIP_LEN_MAX + 1):
        candidate = depart + timedelta(days=length)
        if not (FLEX_RETURN_START <= candidate <= FLEX_RETURN_END):
            continue
        diff = abs(length - FLEX_TARGET_TRIP_LEN)
        if best_diff is None or diff < best_diff:
            best, best_diff = candidate, diff
    return best


# ---------------------------------------------------------------------------
# CSV history
# ---------------------------------------------------------------------------

def ensure_csv_header():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORY_CSV.exists():
        with HISTORY_CSV.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()


def append_history_row(row: dict):
    ensure_csv_header()
    with HISTORY_CSV.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writerow(row)


def read_history_rows(search_type: str) -> list[dict]:
    if not HISTORY_CSV.exists():
        return []
    with HISTORY_CSV.open(newline="") as f:
        reader = csv.DictReader(f)
        return [r for r in reader if r.get("search_type") == search_type]


def last_price(search_type: str) -> float | None:
    rows = read_history_rows(search_type)
    if not rows:
        return None
    try:
        return float(rows[-1]["cheapest_clean_price"])
    except (ValueError, KeyError):
        return None


def all_time_low_before_this_run(search_type: str) -> float | None:
    rows = read_history_rows(search_type)
    prices = []
    for r in rows:
        try:
            prices.append(float(r["cheapest_clean_price"]))
        except (ValueError, KeyError):
            continue
    return min(prices) if prices else None


# ---------------------------------------------------------------------------
# Email alert
# ---------------------------------------------------------------------------

def send_email_alert(subject: str, body: str):
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    to_addr = os.environ.get("ALERT_EMAIL_TO")
    from_addr = os.environ.get("ALERT_EMAIL_FROM", user)

    missing = [
        name
        for name, val in [
            ("SMTP_HOST", host),
            ("SMTP_USER", user),
            ("SMTP_PASSWORD", password),
            ("ALERT_EMAIL_TO", to_addr),
        ]
        if not val
    ]
    if missing:
        print(f"[warn] Skipping email alert, missing env vars: {', '.join(missing)}")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        server.sendmail(from_addr, [to_addr], msg.as_string())
    print(f"[info] Alert email sent to {to_addr}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_search(search_type: str, depart: str, ret: str, token: str) -> dict | None:
    print(f"[info] Searching {search_type}: {ORIGIN}->{DESTINATION} {depart} / {ret}")
    try:
        result = search_flights(token, depart, ret)
    except Exception as e:
        print(f"[error] Search failed for {search_type} {depart}/{ret}: {e}")
        return None
    if not result:
        print(f"[warn] No result for {search_type} {depart}/{ret}")
        return None

    itineraries = extract_itineraries(result)
    best = cheapest_clean(itineraries)
    trip_len = (date.fromisoformat(ret) - date.fromisoformat(depart)).days

    run_ts = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    row = {
        "run_timestamp": run_ts,
        "search_type": search_type,
        "depart_date": depart,
        "return_date": ret,
        "trip_length_days": trip_len,
        "cheapest_clean_price": best.price if best else "",
        "currency": best.currency if best else CURRENCY,
        "airline": best.airlines if best else "",
        "flight_numbers": best.flight_numbers if best else "",
        "stops": best.stops if best else "",
        "duration_minutes": best.total_duration_min if best else "",
        "layover_airports": ";".join(best.layover_airports) if best else "",
        "candidates_considered": len(itineraries),
        "candidates_after_filter": len([i for i in itineraries if passes_filters(i)]),
    }
    append_history_row(row)

    if not best:
        print(f"[warn] No itinerary passed the clean-route filters for {search_type} {depart}/{ret}")
        return row

    print(
        f"[info] Cheapest clean price for {search_type}: "
        f"{best.price} {best.currency} on {best.airlines} ({best.stops} stop(s), "
        f"{best.total_duration_min} min)"
    )
    return row


def maybe_alert(search_type: str, row: dict, label: str) -> str | None:
    """Returns an alert message body if this run's price warrants one, else None."""
    if not row or row.get("cheapest_clean_price") in ("", None):
        return None
    new_price = float(row["cheapest_clean_price"])

    # all_time_low_before_this_run() reads history INCLUDING the row we just
    # appended, so subtract it back out by comparing against prior rows only.
    rows = read_history_rows(search_type)
    prior_prices = []
    for r in rows[:-1]:  # exclude the row we just wrote (last one)
        try:
            prior_prices.append(float(r["cheapest_clean_price"]))
        except (ValueError, KeyError):
            continue

    reasons = []

    if prior_prices:
        prev = prior_prices[-1]
        if prev > 0:
            pct_change = (prev - new_price) / prev * 100
            if pct_change > PRICE_DROP_ALERT_PCT:
                reasons.append(
                    f"Price dropped {pct_change:.1f}% since last run "
                    f"({prev:.0f} -> {new_price:.0f} {row['currency']})"
                )
        ath_low = min(prior_prices)
        if new_price < ath_low:
            reasons.append(
                f"New all-time low: {new_price:.0f} {row['currency']} "
                f"(previous low was {ath_low:.0f})"
            )
    else:
        # First-ever recorded price for this search type: no baseline to
        # compare against, so stay quiet (per "no daily email for no change").
        pass

    if not reasons:
        return None

    lines = [
        f"{label} price alert: {ORIGIN} -> {DESTINATION}, round trip, 2 adults, Economy",
        "",
        *reasons,
        "",
        f"Depart: {row['depart_date']}  Return: {row['return_date']}  "
        f"({row['trip_length_days']} days)",
        f"Airline: {row['airline']}  Flights: {row['flight_numbers']}",
        f"Stops: {row['stops']}  Duration: {row['duration_minutes']} min  "
        f"Layovers: {row['layover_airports'] or 'none'}",
        f"Price: {new_price:.0f} {row['currency']} total for {ADULTS} adults",
        "",
        BOOKING_REMINDER,
    ]
    return "\n".join(lines)


def main():
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("[error] APIFY_API_TOKEN is not set. Export it or add it as a GitHub Secret.")
        sys.exit(1)

    alert_bodies = []

    # 1. Primary fixed-date search.
    row = process_search("primary", PRIMARY_DEPART, PRIMARY_RETURN, token)
    alert = maybe_alert("primary", row, "Primary dates")
    if alert:
        alert_bodies.append(alert)

    # 2. Flexible sweep: sample a handful of depart dates, each paired with
    #    the return date that best matches the 38-50 day trip length window.
    #    We record the sweep's overall cheapest clean fare under search_type
    #    "flexible" so it gets its own price-history line and its own
    #    drop/all-time-low comparison.
    flex_candidates = []
    for depart in sampled_flex_depart_dates():
        ret = best_return_for_depart(depart)
        if not ret:
            continue
        time.sleep(1)  # be polite to the actor/API rate limits
        r = process_search(
            "flexible_leg", depart.isoformat(), ret.isoformat(), token
        )
        if r and r.get("cheapest_clean_price") not in ("", None):
            flex_candidates.append(r)

    if flex_candidates:
        best_flex = min(flex_candidates, key=lambda r: float(r["cheapest_clean_price"]))
        # Re-log the sweep's overall best as its own "flexible" series so
        # alerting has a stable baseline independent of which specific
        # depart/return combo happened to win this run.
        flex_row = dict(best_flex)
        flex_row["search_type"] = "flexible"
        flex_row["run_timestamp"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        append_history_row(flex_row)
        alert = maybe_alert("flexible", flex_row, "Flexible dates")
        if alert:
            alert_bodies.append(alert)

    if alert_bodies:
        subject = "Flight price alert: MEL -> KTM"
        body = ("\n\n" + "-" * 40 + "\n\n").join(alert_bodies)
        send_email_alert(subject, body)
    else:
        print("[info] No price drop or new low this run -- staying quiet.")

    print(f"[info] {BOOKING_REMINDER}")


if __name__ == "__main__":
    main()
