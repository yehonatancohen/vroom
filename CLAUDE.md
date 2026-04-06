# Vroom — Claude Development Notes

## What this project is

A single-user Telegram bot that scrapes car listings from **Yad2** and **Facebook Marketplace** and sends new matches based on the user's configured filters.

## Key files

| File | Purpose |
|---|---|
| `main.py` | Telegram bot, command handlers, `run_scan()` orchestration |
| `scraper.py` | Yad2 scraper — `scrape(cfg, since) -> ScrapeResult` |
| `fb_scraper.py` | FB Marketplace scraper — `scrape_fb(cfg, since) -> ScrapeResult` |
| `db.py` | SQLite: seen listings dedup, user config persistence |
| `formatter.py` | Formats `Listing` objects into Telegram markdown |
| `config.py` | Constants, env vars, `DEFAULT_CONFIG` |
| `debug_scan.py` | Manual test script — runs both scrapers and prints results |

## debug_scan.py — keep it in sync

`debug_scan.py` is the primary tool for testing scraper changes locally.

**Run it:**
```bash
python debug_scan.py              # both scrapers
python debug_scan.py --yad2-only  # skip FB
python debug_scan.py --fb-only    # skip Yad2
```

**Keep it updated when changing:**
- `scraper.scrape()` or `fb_scraper.scrape_fb()` signatures
- `ScrapeResult` or `Listing` fields
- Config keys in `DEFAULT_CONFIG`
- How `run_scan()` in `main.py` calls the scrapers

The script mirrors what `run_scan()` does: reads config from DB (falls back to `DEFAULT_CONFIG`), sets `since` to one week ago, runs both scrapers, and prints formatted output.

## Scraper architecture

Both scrapers share the same `Listing` dataclass and `ScrapeResult` return type (defined in `scraper.py`).

**Yad2** (`scraper.py`): sync, uses `curl_cffi` with Chrome impersonation. Run via `loop.run_in_executor()` in `main.py`.

**FB Marketplace** (`fb_scraper.py`): async, uses Playwright headless Chromium. No login required — uses a fresh unauthenticated browser context per scan. Handles FB's login modal with `_dismiss_modal()`. FB listing IDs are prefixed with `fb_` to avoid collision in the `seen_listings` table.

Both scrapers run in **parallel** via `asyncio.gather(..., return_exceptions=True)` in `run_scan()`. If FB fails, Yad2 continues unaffected.

## Config

Filters live in `DEFAULT_CONFIG` (config.py) and are persisted per-user in the `user_config` SQLite table. FB uses the same `price_min/max`, `year_min/max`, `km_max` keys. No brand filter for FB.

`FB_LOCATION_ID` env var controls the FB Marketplace location (default: `109097929135922` = Israel national).

## Docker

```bash
docker-compose up --build
```

Playwright Chromium deps are installed manually in the Dockerfile (not via `playwright install-deps`) to avoid font package naming issues in newer Debian.
