import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from scraper import Listing, ScrapeResult
import db
from config import FB_LOCATION_ID

logger = logging.getLogger(__name__)

FB_ITEM_BASE = "https://www.facebook.com/marketplace/item"
FB_MARKETPLACE_BASE = "https://www.facebook.com/marketplace"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def build_fb_url(cfg: dict) -> str:
    """Build the FB Marketplace search URL from config."""
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

    base = f"{FB_MARKETPLACE_BASE}/{FB_LOCATION_ID}/vehicles"
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
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
                locale="he-IL",
            )
            page = await ctx.new_page()

            try:
                await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            except Exception as e:
                logger.warning("FB: page navigation failed: %s", e)
                await browser.close()
                return ScrapeResult([], 0, 0, 0)

            await _dismiss_modal(page)
            await asyncio.sleep(random.uniform(1.0, 2.0))

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

            for card in unseen_cards:
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
                filtered_by_brand=0,
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
