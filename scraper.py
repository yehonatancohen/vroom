import random
import asyncio
import logging
import json
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

YAD2_SEARCH_URL = "https://www.yad2.co.il/vehicles/cars"
API_HOST = "gw.yad2.co.il"


@dataclass
class Listing:
    listing_id: str
    title: str
    price: Optional[int]
    km: Optional[int]
    year: Optional[int]
    hand: Optional[int]
    city: Optional[str]
    image_url: Optional[str]
    listing_url: str
    brand: Optional[str] = field(default=None)


def _build_url_params(cfg: dict) -> dict:
    params = {}

    price_min = cfg.get("price_min", 0)
    price_max = cfg.get("price_max", 0)
    if price_min or price_max:
        params["price"] = f"{price_min or 0}-{price_max or 999999}"

    km_max = cfg.get("km_max", 0)
    if km_max:
        params["km"] = f"0-{km_max}"

    year_min = cfg.get("year_min", 0)
    year_max = cfg.get("year_max", 0)
    if year_min or year_max:
        params["year"] = f"{year_min or 1980}-{year_max or 2030}"

    hand_max = cfg.get("hand_max", 0)
    if hand_max and hand_max > 0:
        params["hand"] = f"1-{hand_max}"

    return params


def _parse_listing(item: dict) -> Optional[Listing]:
    try:
        lid = str(item.get("id") or item.get("orderId") or item.get("token", ""))
        if not lid:
            return None

        title_parts = [
            item.get("manufacturer", ""),
            item.get("model", ""),
            item.get("subModel", ""),
        ]
        title = " ".join(p for p in title_parts if p).strip() or item.get("title", "")

        price_raw = item.get("price")
        try:
            price = int(str(price_raw).replace(",", "").replace("₪", "").strip()) if price_raw else None
        except (ValueError, AttributeError):
            price = None

        km_raw = item.get("km") or item.get("kilometers")
        try:
            km = int(str(km_raw).replace(",", "").strip()) if km_raw else None
        except (ValueError, AttributeError):
            km = None

        year = item.get("year")
        try:
            year = int(year) if year else None
        except (ValueError, TypeError):
            year = None

        hand = item.get("hand")
        try:
            hand = int(hand) if hand else None
        except (ValueError, TypeError):
            hand = None

        city = item.get("city") or item.get("area")

        images = item.get("images") or []
        image_url = None
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, dict):
                image_url = first.get("src") or first.get("url")
            elif isinstance(first, str):
                image_url = first
        if not image_url:
            image_url = item.get("mainImage") or item.get("image")

        token = item.get("token") or lid
        listing_url = f"https://www.yad2.co.il/item/{token}"
        brand = item.get("manufacturer", "")

        return Listing(
            listing_id=lid,
            title=title,
            price=price,
            km=km,
            year=year,
            hand=hand,
            city=city,
            image_url=image_url,
            listing_url=listing_url,
            brand=brand,
        )
    except Exception as e:
        logger.warning("Failed to parse listing: %s", e)
        return None


def _matches_brands(listing: Listing, brands: list[str]) -> bool:
    if not brands:
        return True
    brand = (listing.brand or "").strip()
    title = (listing.title or "").strip()
    return any(b in brand or b in title for b in brands)


async def _scrape_with_playwright(cfg: dict) -> list[dict]:
    """Launch a headless browser, navigate to Yad2, intercept the API response."""
    from playwright.async_api import async_playwright

    params = _build_url_params(cfg)
    # Build query string to append to the page URL so Yad2 pre-filters server-side
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    page_url = f"{YAD2_SEARCH_URL}?{qs}" if qs else YAD2_SEARCH_URL

    captured: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="he-IL",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        api_response_future: asyncio.Future = asyncio.get_event_loop().create_future()

        async def handle_response(response):
            if API_HOST in response.url and "vehicles/cars" in response.url:
                if not api_response_future.done():
                    try:
                        body = await response.json()
                        api_response_future.set_result(body)
                    except Exception as e:
                        logger.warning("Could not parse intercepted API response: %s", e)

        page.on("response", handle_response)

        await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

        # Wait up to 15s for the API call to be intercepted
        try:
            data = await asyncio.wait_for(api_response_future, timeout=15)
            captured = _extract_items(data)
        except asyncio.TimeoutError:
            logger.warning("API response not intercepted; falling back to DOM parsing.")
            captured = await _parse_dom(page)

        await browser.close()

    return captured


async def _parse_dom(page) -> list[dict]:
    """Best-effort DOM scrape when API interception fails."""
    items = []
    try:
        cards = await page.query_selector_all("[data-testid='feed-item'], .feed_item, li[class*='item']")
        for card in cards:
            item: dict = {}
            for attr in ["data-id", "data-order-id", "id"]:
                val = await card.get_attribute(attr)
                if val:
                    item["id"] = val.strip()
                    break
            if not item.get("id"):
                continue

            title_el = await card.query_selector("h2, h3, [class*='title']")
            if title_el:
                item["title"] = (await title_el.inner_text()).strip()

            price_el = await card.query_selector("[class*='price']")
            if price_el:
                item["price"] = re.sub(r"[^\d]", "", await price_el.inner_text())

            img_el = await card.query_selector("img")
            if img_el:
                item["image"] = await img_el.get_attribute("src")

            link_el = await card.query_selector("a[href]")
            if link_el:
                href = await link_el.get_attribute("href")
                if href:
                    item["token"] = href.split("/")[-1]

            items.append(item)
    except Exception as e:
        logger.error("DOM parse failed: %s", e)
    return items


def _extract_items(data: dict) -> list[dict]:
    feed = data.get("data", data)
    if isinstance(feed, dict):
        items = (
            feed.get("feed", {}).get("feed_items")
            or feed.get("feed_items")
            or feed.get("items")
            or []
        )
    elif isinstance(feed, list):
        items = feed
    else:
        items = []
    return [i for i in items if isinstance(i, dict)]


def scrape(cfg: dict) -> list[Listing]:
    delay = random.uniform(2, 5)
    import time; time.sleep(delay)

    try:
        raw_items = asyncio.run(_scrape_with_playwright(cfg))
    except Exception as e:
        logger.error("Playwright scrape failed: %s", e)
        return []

    brands_filter = cfg.get("brands", [])
    listings = []

    for item in raw_items:
        if item.get("type") in ("ad", "banner", "yad1"):
            continue
        listing = _parse_listing(item)
        if listing and _matches_brands(listing, brands_filter):
            listings.append(listing)

    logger.info("Scraped %d matching listings", len(listings))
    return listings
