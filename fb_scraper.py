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
from config import FB_PROFILE_DIR, FB_LOCATION_ID

logger = logging.getLogger(__name__)

FB_ITEM_BASE = "https://www.facebook.com/marketplace/item"
FB_MARKETPLACE_BASE = "https://www.facebook.com/marketplace"


class FBSessionNotConfigured(Exception):
    pass


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

    location_id = FB_LOCATION_ID
    base = f"{FB_MARKETPLACE_BASE}/{location_id}/vehicles"
    if params:
        return f"{base}?{urlencode(params)}"
    return base


async def _get_browser_context(playwright, headless: bool, profile_dir: str):
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="he-IL",
    )


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

            # Title: look for the aria-label on the anchor, or fallback to text content
            title = (await anchor.get_attribute("aria-label") or "").strip()
            if not title:
                title = (await anchor.inner_text()).strip().splitlines()[0].strip()

            # Image
            img_el = await anchor.query_selector("img")
            image_url = None
            if img_el:
                image_url = await img_el.get_attribute("src")

            # Price and city: grab all span text nodes
            spans = await anchor.query_selector_all("span")
            texts = []
            for span in spans:
                t = (await span.inner_text()).strip()
                if t:
                    texts.append(t)

            price = None
            city = None
            for t in texts:
                # Price: contains ₪ or looks like a number
                if price is None and ("₪" in t or re.match(r'^\d[\d,]+$', t)):
                    cleaned = re.sub(r'[^\d]', '', t)
                    if cleaned:
                        price = int(cleaned)
                # City: short non-numeric text (FB shows "City · time_ago" in one span)
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
    """Fetch a detail page and extract year, km, and listed_at."""
    url = f"{FB_ITEM_BASE}/{listing_id}/"
    try:
        await page.goto(url, timeout=20000)
        await asyncio.sleep(random.uniform(1.5, 3.0))
    except Exception as e:
        logger.debug("FB: failed to load detail page %s: %s", listing_id, e)
        return {}

    detail: dict = {}

    # listed_at from <time datetime="...">
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

    # Year and km from the page text
    try:
        body_text = await page.inner_text("body")

        # Year: 4-digit number between 1990-2030
        year_m = re.search(r'\b(19[9]\d|20[0-3]\d)\b', body_text)
        if year_m:
            detail["year"] = int(year_m.group(1))

        # KM: number followed by ק"מ or ק''מ or km
        km_m = re.search(r'([\d,]+)\s*(?:ק["\u2019\u0027]מ|km)', body_text, re.IGNORECASE)
        if km_m:
            detail["km"] = int(km_m.group(1).replace(",", ""))
    except Exception:
        pass

    return detail


async def scrape_fb(cfg: dict, since: Optional[datetime] = None) -> ScrapeResult:
    """
    Scrape FB Marketplace for vehicle listings matching cfg.
    Returns ScrapeResult compatible with scraper.scrape() output.
    Raises FBSessionNotConfigured if the profile directory doesn't exist
    or if the browser lands on a login page.
    """
    profile_dir = os.path.abspath(FB_PROFILE_DIR)
    if not os.path.exists(profile_dir):
        raise FBSessionNotConfigured(
            f"FB profile dir not found: {profile_dir}. Run: python setup_fb.py"
        )

    url = build_fb_url(cfg)
    logger.info("FB Marketplace scan: %s", url)

    ctx = None
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            ctx = await _get_browser_context(p, headless=True, profile_dir=profile_dir)
            page = await ctx.new_page()

            try:
                await page.goto(url, timeout=20000)
            except Exception as e:
                logger.warning("FB: page navigation failed: %s", e)
                await ctx.close()
                return ScrapeResult([], 0, 0, 0)

            # Detect login redirect
            if "login" in page.url or "checkpoint" in page.url:
                await ctx.close()
                raise FBSessionNotConfigured(
                    "FB session expired — re-run: python setup_fb.py"
                )

            # Random delay to let the page hydrate
            await asyncio.sleep(random.uniform(2.0, 4.0))

            raw_cards = await _extract_cards(page)
            total_on_page = len(raw_cards)
            logger.info("FB: found %d listing cards", total_on_page)

            if not raw_cards:
                await ctx.close()
                return ScrapeResult([], 0, 0, 0)

            # Prefix all IDs before dedup check
            for card in raw_cards:
                card["listing_id"] = f"fb_{card['listing_id']}"

            # Only fetch detail pages for listings not yet seen
            all_ids = [c["listing_id"] for c in raw_cards]
            unseen_ids = set(db.filter_new(all_ids))
            unseen_cards = [c for c in raw_cards if c["listing_id"] in unseen_ids]
            logger.info("FB: %d unseen out of %d", len(unseen_cards), total_on_page)

            listings = []
            skipped_since = 0

            for card in unseen_cards:
                raw_id = card["listing_id"][3:]  # strip "fb_" prefix for URL
                detail = await _extract_detail(page, raw_id)

                listed_at: Optional[datetime] = detail.get("listed_at")

                # Apply since filter only when we have a timestamp
                if since and listed_at and listed_at < since:
                    skipped_since += 1
                    continue

                listing = Listing(
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
                )
                listings.append(listing)

            await ctx.close()
            return ScrapeResult(
                listings=listings,
                total_on_page=total_on_page,
                filtered_by_brand=0,
                filtered_by_since=skipped_since,
            )

    except FBSessionNotConfigured:
        raise
    except Exception as e:
        logger.error("FB scraper unexpected error: %s", e, exc_info=True)
        if ctx:
            try:
                await ctx.close()
            except Exception:
                pass
        return ScrapeResult([], 0, 0, 0)
