# Carvana Killer — Marketplace Watcher Skills

Source: "Build the Carvana killer" (The Hub, Episode 11) — angussewell.com

## GitHub repos for the Marketplace connectors

The PDF names two tools ("marketplace-mcp" and "facebook-marketplace-mcp") without linking to them. Found via search — verify before installing, these are third-party hobby projects that can break at any time:

| Connector | GitHub | Notes |
|---|---|---|
| facebook-marketplace-mcp | https://github.com/jdcodes1/facebook-marketplace-mcp | Direct GraphQL API via your Chrome session cookies, no browser automation at runtime. macOS + Chrome + Node 20+ required. |
| secondhand-mcp | https://github.com/jlsookiki/secondhand-mcp | Searches Facebook Marketplace, eBay, Depop, Poshmark. No login/browser required. Matches the "Secondhand MCP" hosted option in the PDF (secondhandmcp.com). |
| mcp-facebook-market-place | https://github.com/fisheyes/mcp-facebook-market-place | FastMCP + Playwright headless-browser scraper. |

Other links referenced in the PDF (not GitHub, included for completeness):
- Claude — https://claude.ai
- OpenAI Codex — https://openai.com/codex
- OpenClaw — https://openclaw.ai
- Hermes Agent (Nous Research) — https://nousresearch.com
- n8n — https://n8n.io
- Gumloop — https://www.gumloop.com
- Apify — https://apify.com
- Firecrawl — https://firecrawl.dev
- Kelley Blue Book — https://www.kbb.com/whats-my-car-worth/
- Edmunds appraisal — https://www.edmunds.com/appraisal-value/
- Vehicle Databases — https://vehicledatabases.com/api/used-car
- MarketCheck — https://www.marketcheck.com/apis/cars/
- Telegram — https://telegram.org
- Facebook Marketplace — https://www.facebook.com/marketplace
- Author — https://www.angussewell.com/

---

## The four prompts

Paste one at a time, in order. Each builds a separate skill; they hand off through a shared `cars.csv`.

### Prompt 1 — `carwatch-find` (uses your Marketplace MCP)

```
Create a skill called "carwatch-find".

Every time it runs, it should:

1. Use my Facebook Marketplace connector to search for these cars:
   Tacoma TRD, 4Runner, Civic Si, Miata NB — put your list here
   near your city, priced your min to your max.

2. Compare what comes back against the cars it already saved.
   Only count a car as new if the year, model, mileage and price
   together are ones it hasn't seen. Sellers delete and repost the
   same car to jump the feed, so a new listing link does NOT mean
   a new car.

3. Save every genuinely new car to a file called cars.csv:
   title, price, mileage, year, location, link, date found.

4. Tell me how many new cars it found.

Run it once now and show me what it found so I can check it works.
```

Then tell it: "run carwatch-find every hour." Prefer a spreadsheet? Say "save it to Google Sheets" or connect n8n instead.

### Prompt 2 — `carwatch-price` (uses your browser)

```
Create a separate skill called "carwatch-price".

It reads the same cars.csv file that carwatch-find writes to.

For every car in cars.csv that has no value yet, use my browser:

1. Go to kbb.com and click "What's my car worth".
2. Choose Make/Model, then enter the year, make, model, the mileage
   from the listing, and my ZIP code — your ZIP.
3. Work through the steps it asks: pick the trim, choose "Price with
   standard equipment", pick a colour if it asks, choose "Selling my
   car", leave "Trade-In & Private Party Values" ticked, and pick the
   condition — use Good unless the listing says otherwise.
4. If it asks for my email, click "Not now, maybe later".
5. Read the PRIVATE PARTY number. Not trade-in, not dealer retail.
   Private party is what a normal person pays a normal person.
6. Write that number into cars.csv next to the car, plus how far
   under it the asking price is, as a percentage.

Do the cars one at a time and show me the first one before doing
the rest, so I can check you're reading the right number.
```

Alternative one-page version: `edmunds.com/[make]/[model]/[year]/appraisal-value/` (assumes 12,000 mi/yr, so it's a quick check, not exact). API alternatives: Vehicle Databases, MarketCheck.

### Prompt 3 — `carwatch-message` (uses your browser)

```
Create a separate skill called "carwatch-message".

It reads the same cars.csv file the other two skills use.

For every car in cars.csv priced 15% to 40% under its private party
value:

1. Skip anything more than 40% under. That's not a deal, that's a
   scam listing — a real $28,000 truck is not on sale for $14,000.
2. Skip it if the seller is a dealer. I want private sellers.
3. Open the listing in my browser. Read the description and look at
   the photos. If the photos look like stock or stolen images, or
   the text doesn't match the car, skip it and tell me why.
4. Write a two-sentence message to the seller that mentions one real
   detail from the listing — the trim, the mileage, something you
   can see in the photos. Casual, lowercase, no emoji. Never write
   "is this still available" — every seller ignores that.
5. Show me the car and the message first. If I say send, then use
   the browser to send it from my Facebook account.

Never send a message without showing me first. Never send more than
5 a day. Never send the same wording twice.
```

### Prompt 4 — `carwatch-followup` (browser + your alerts)

```
Create a separate skill called "carwatch-followup".

It reads the same cars.csv file the other three skills use.

Once a day:

1. Open my Facebook messages in the browser and check for replies
   from any seller in cars.csv. Save what they said next to the car.
2. If someone replied, text me what they said with a link, so I can
   take over the conversation.
3. If a seller hasn't replied in 24 hours, write me a one-line nudge
   to approve. Drop it after 72 hours of silence.
4. Re-check the price of every car in cars.csv. If a seller has
   dropped their price, text me straight away — that's the moment
   they're ready to deal, and it's usually a better price than
   anything on day one.

Never agree a price for me. When a seller says yes, stop and hand
it to me.
```

---

## Two rules to keep in mind

1. **Facebook doesn't allow this.** Automating your account risks a lock. Keep it to a handful of messages a day, never repeat the same text, and read every message before it sends.
2. **Blue Book is personal-use only.** Fine to look up a car you're actually considering; not meant for storing hundreds of values in a spreadsheet.
