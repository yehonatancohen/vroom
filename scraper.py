import random
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.yad2.co.il/vehicles/cars",
}

API_URL = "https://gw.yad2.co.il/feed-search-legacy/vehicles/cars"


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


def _build_params(cfg: dict) -> dict:
    params = {
        "carFamilyType": "1",   # private cars
        "priceOnly": "1",
    }

    if cfg.get("price_min", 0) > 0:
        params["price"] = f"{cfg['price_min']}-{cfg['price_max']}"
    elif cfg.get("price_max", 0) > 0:
        params["price"] = f"0-{cfg['price_max']}"

    if cfg.get("km_max", 0) > 0:
        params["km"] = f"0-{cfg['km_max']}"

    year_min = cfg.get("year_min", 0)
    year_max = cfg.get("year_max", 0)
    if year_min or year_max:
        params["year"] = f"{year_min or 1980}-{year_max or 2025}"

    hand_max = cfg.get("hand_max", 0)
    if hand_max and hand_max > 0:
        params["hand"] = f"1-{hand_max}"

    return params


def _parse_listing(item: dict) -> Optional[Listing]:
    try:
        lid = str(item.get("id") or item.get("orderId", ""))
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

        # Image URL: try multiple paths in the response
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
        logger.warning("Failed to parse listing: %s | item: %s", e, item)
        return None


def _matches_brands(listing: Listing, brands: list[str]) -> bool:
    if not brands:
        return True
    brand = (listing.brand or "").strip()
    title = (listing.title or "").strip()
    for b in brands:
        if b in brand or b in title:
            return True
    return False


def scrape(cfg: dict) -> list[Listing]:
    params = _build_params(cfg)
    delay = random.uniform(2, 5)
    time.sleep(delay)

    try:
        resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.HTTPError as e:
        logger.error("HTTP error scraping Yad2: %s", e)
        return []
    except Exception as e:
        logger.error("Error scraping Yad2: %s", e)
        return []

    # Navigate feed response structure
    feed = data.get("data", {})
    if isinstance(feed, dict):
        items = feed.get("feed", {}).get("feed_items", [])
    elif isinstance(feed, list):
        items = feed
    else:
        items = []

    if not items:
        # Try alternate path
        items = data.get("feed_items") or data.get("items") or []

    listings = []
    brands_filter = cfg.get("brands", [])

    for item in items:
        if not isinstance(item, dict):
            continue
        # Skip ad/banner items
        if item.get("type") in ("ad", "banner", "yad1"):
            continue

        listing = _parse_listing(item)
        if listing is None:
            continue

        if not _matches_brands(listing, brands_filter):
            continue

        listings.append(listing)

    logger.info("Scraped %d matching listings", len(listings))
    return listings
