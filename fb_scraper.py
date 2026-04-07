import asyncio
import logging
import os
import random
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from scraper import Listing, ScrapeResult
import db
from config import FB_LOCATION_ID  # optional override; empty = rely on IP geolocation

logger = logging.getLogger(__name__)

FB_ITEM_BASE = "https://www.facebook.com/marketplace/item"
FB_MARKETPLACE_BASE = "https://www.facebook.com/marketplace"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def build_fb_url(cfg: dict) -> str:
    """Build the FB Marketplace vehicles search URL.

    Location: if FB_LOCATION_ID env var is set, embed it in the path for an
    explicit location scope. Otherwise omit it and let Facebook use the
    browser's IP geolocation (correct when the bot runs in Israel).
    """
    params = {}
    if cfg.get("price_min"):
        params["minPrice"] = cfg["price_min"]
    if cfg.get("price_max"):
        params["maxPrice"] = cfg["price_max"]
    if cfg.get("year_min"):
        params["minYear"] = cfg["year_min"]
    if cfg.get("year_max"):
        params["maxYear"] = cfg["year_max"]
    if cfg.get("km_max"):
        params["maxMileage"] = cfg["km_max"]

    if FB_LOCATION_ID:
        # /{location_id}/vehicles — scopes to a specific city/country.
        # Find your city's ID: open FB Marketplace, change location, copy the
        # numeric ID from the URL. Set it as FB_LOCATION_ID in .env
        base = f"{FB_MARKETPLACE_BASE}/{FB_LOCATION_ID}/vehicles"
    else:
        # /category/vehicles — correct vehicle category but no location pin.
        # FB will default to San Francisco for unauthenticated users.
        # Set FB_LOCATION_ID in .env to fix the location.
        base = f"{FB_MARKETPLACE_BASE}/category/vehicles"

    if params:
        return f"{base}?{urlencode(params)}"
    return base


async def _dismiss_modal(page) -> None:
    """Try to close FB's login/signup modal that appears for unauthenticated visitors."""
    await asyncio.sleep(1.5)
    for selector in ['[aria-label="Close"]', '[aria-label="סגור"]', '[data-testid="dialog-close-button"]']:
        try:
            btn = await page.query_selector(selector)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            pass
    try:
        await page.keyboard.press("Escape")
        await asyncio.sleep(0.5)
    except Exception:
        pass


async def _extract_cards(page) -> list[dict]:
    """Extract raw listing data from the FB Marketplace search results page."""
    try:
        await page.wait_for_selector('a[href*="/marketplace/item/"]', timeout=15000)
    except Exception:
        logger.warning("FB Marketplace: timed out waiting for listing cards")
        return []

    anchors = await page.query_selector_all('a[href*="/marketplace/item/"]')
    cards = []
    seen_ids = set()

    for anchor in anchors:
        try:
            href = await anchor.get_attribute("href") or ""
            m = re.search(r'/marketplace/item/(\d+)/', href)
            if not m:
                continue
            listing_id = m.group(1)
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

            # Title: aria-label on the anchor first, fallback to first line of text
            title = (await anchor.get_attribute("aria-label") or "").strip()
            if not title:
                title = (await anchor.inner_text()).strip().splitlines()[0].strip()

            # Image
            img_el = await anchor.query_selector("img")
            image_url = None
            if img_el:
                image_url = await img_el.get_attribute("src")

            # Price and city from span text nodes inside the card
            spans = await anchor.query_selector_all("span")
            texts = []
            for span in spans:
                t = (await span.inner_text()).strip()
                if t:
                    texts.append(t)

            price = None
            city = None
            for t in texts:
                if price is None and ("₪" in t or re.match(r'^\d[\d,]+$', t)):
                    cleaned = re.sub(r'[^\d]', '', t)
                    if cleaned:
                        price = int(cleaned)
                elif city is None and t and not re.match(r'^\d', t) and "₪" not in t:
                    city = t.split("·")[0].strip()

            logger.debug("FB card: id=%s title=%r price=%s city=%r", listing_id, title, price, city)
            cards.append({
                "listing_id": listing_id,
                "title": title,
                "price": price,
                "city": city,
                "image_url": image_url,
                "listing_url": f"{FB_ITEM_BASE}/{listing_id}/",
            })
        except Exception as e:
            logger.debug("FB: error parsing card: %s", e)
            continue

    return cards


async def _extract_detail(page, listing_id: str) -> dict:
    """Navigate to a detail page and extract year, km, and listed_at."""
    url = f"{FB_ITEM_BASE}/{listing_id}/"
    try:
        await page.goto(url, timeout=20000, wait_until="domcontentloaded")
        await asyncio.sleep(random.uniform(1.5, 3.0))
    except Exception as e:
        logger.debug("FB: failed to load detail page %s: %s", listing_id, e)
        return {}

    await _dismiss_modal(page)

    detail: dict = {}

    try:
        time_el = await page.query_selector("time[datetime]")
        if time_el:
            dt_str = await time_el.get_attribute("datetime")
            if dt_str:
                detail["listed_at"] = datetime.fromisoformat(
                    dt_str.replace("Z", "+00:00")
                ).replace(tzinfo=None)
    except Exception:
        pass

    try:
        body_text = await page.inner_text("body")

        year_m = re.search(r'\b(19[9]\d|20[0-3]\d)\b', body_text)
        if year_m:
            detail["year"] = int(year_m.group(1))

        km_m = re.search(r'([\d,]+)\s*(?:ק["\u2019\u0027]מ|km)', body_text, re.IGNORECASE)
        if km_m:
            detail["km"] = int(km_m.group(1).replace(",", ""))
    except Exception:
        pass

    return detail


async def scrape_fb(cfg: dict, since: Optional[datetime] = None) -> ScrapeResult:
    """
    Scrape FB Marketplace for vehicle listings matching cfg.
    No login required — uses a fresh unauthenticated browser context each run.
    Returns ScrapeResult compatible with scraper.scrape() output.
    """
    from playwright.async_api import async_playwright

    url = build_fb_url(cfg)
    logger.info("FB Marketplace scan: %s", url)

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            ctx = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="he-IL",
                timezone_id="Asia/Jerusalem",
                geolocation={"latitude": 32.0853, "longitude": 34.7818},  # Tel Aviv
                permissions=["geolocation"],
            )
            page = await ctx.new_page()
            # Mask the navigator.webdriver property that reveals headless automation
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            try:
                await page.goto(url, timeout=45000, wait_until="networkidle")
            except Exception as e:
                # networkidle can time out on heavy pages — fall through and try anyway
                logger.warning("FB: navigation warning (continuing): %s", e)

            # Log where we actually landed (helps diagnose redirects / login walls)
            logger.info("FB: landed on %s", page.url)

            await _dismiss_modal(page)
            # Scroll down to trigger lazy-loaded listing cards
            await page.evaluate("window.scrollTo(0, 600)")
            await asyncio.sleep(random.uniform(2.0, 3.5))

            # Save page HTML when FB_DEBUG=1 for diagnosing selector/content issues
            if os.environ.get("FB_DEBUG"):
                html = await page.content()
                with open("fb_debug_page.html", "w", encoding="utf-8") as f:
                    f.write(html)
                logger.info("FB: debug HTML saved to fb_debug_page.html")

            raw_cards = await _extract_cards(page)
            total_on_page = len(raw_cards)
            logger.info("FB: found %d listing cards", total_on_page)

            if not raw_cards:
                await browser.close()
                return ScrapeResult([], 0, 0, 0)

            for card in raw_cards:
                card["listing_id"] = f"fb_{card['listing_id']}"

            all_ids = [c["listing_id"] for c in raw_cards]
            unseen_ids = set(db.filter_new(all_ids))
            unseen_cards = [c for c in raw_cards if c["listing_id"] in unseen_ids]
            logger.info("FB: %d unseen out of %d", len(unseen_cards), total_on_page)

            listings = []
            skipped_since = 0
            filtered_by_brand = 0

            brands_filter = cfg.get("brands", [])
            model_filter = cfg.get("model_filter", [])

            for card in unseen_cards:
                title = card.get("title") or ""
                # Brand filter based on title
                if brands_filter:
                    if not any(brand in title for brand in brands_filter):
                        filtered_by_brand += 1
                        continue
                # Model filter based on title
                if model_filter:
                    if not any(kw.lower() in title.lower() for kw in model_filter):
                        filtered_by_brand += 1
                        continue

                raw_id = card["listing_id"][3:]  # strip "fb_" for URL
                detail = await _extract_detail(page, raw_id)

                listed_at: Optional[datetime] = detail.get("listed_at")

                if since and listed_at and listed_at < since:
                    skipped_since += 1
                    continue

                listings.append(Listing(
                    listing_id=card["listing_id"],
                    title=card.get("title") or "Facebook Marketplace",
                    price=card.get("price"),
                    km=detail.get("km"),
                    year=detail.get("year"),
                    hand=None,
                    city=card.get("city"),
                    image_url=card.get("image_url"),
                    listing_url=card["listing_url"],
                    brand=None,
                    color=None,
                    test_date=None,
                    listed_at=listed_at,
                ))

            await browser.close()
            return ScrapeResult(
                listings=listings,
                total_on_page=total_on_page,
                filtered_by_brand=filtered_by_brand,
                filtered_by_since=skipped_since,
            )

    except Exception as e:
        logger.error("FB scraper unexpected error: %s", e, exc_info=True)
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        return ScrapeResult([], 0, 0, 0)
