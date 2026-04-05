import random
import time
import logging
import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlencode

from curl_cffi import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

YAD2_SEARCH_URL = "https://www.yad2.co.il/vehicles/cars"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "he-IL,he;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.yad2.co.il/",
}


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


def build_search_url(cfg: dict) -> str:
    """Build the Yad2 search URL from config, or return the custom URL if set."""
    custom = (cfg.get("search_url") or "").strip()
    if custom:
        return custom

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

    qs = urlencode(params)
    return f"{YAD2_SEARCH_URL}?{qs}" if qs else YAD2_SEARCH_URL


# kept as a standalone helper for tests
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


def _fetch_html(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, impersonate="chrome124", timeout=20)
    if "ShieldSquare Captcha" in (resp.text[:2000]):
        raise RuntimeError("Bot detection triggered (ShieldSquare Captcha)")
    resp.raise_for_status()
    return resp.text


def _extract_next_data(html: str) -> list[dict]:
    """Try to pull listing items from the __NEXT_DATA__ JSON Yad2 embeds in the page."""
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

    # Walk the props tree looking for feed_items / items arrays
    def find_items(obj, depth=0):
        if depth > 10:
            return []
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict) and ("id" in obj[0] or "token" in obj[0]):
                return obj
            for v in obj:
                result = find_items(v, depth + 1)
                if result:
                    return result
        if isinstance(obj, dict):
            for key in ("feed_items", "feedItems", "items", "listings"):
                if key in obj and isinstance(obj[key], list):
                    return obj[key]
            for v in obj.values():
                result = find_items(v, depth + 1)
                if result:
                    return result
        return []

    items = find_items(data)
    logger.info("__NEXT_DATA__ extraction found %d raw items", len(items))
    return [i for i in items if isinstance(i, dict)]


def _extract_from_html(html: str, page_url: str) -> list[dict]:
    """
    Fallback: parse visible feed cards from HTML.
    Uses image src as a stable token (yad2-scraper approach).
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []

    cards = (
        soup.select("[data-testid='feed-item']")
        or soup.select(".feed_item")
        or soup.select("li[class*='feedItem']")
        or soup.select("li[class*='item']")
    )

    if not cards:
        # Last resort: any <a> with /item/ href
        for a in soup.select("a[href*='/item/']"):
            token = a["href"].rstrip("/").split("/")[-1]
            img = a.find("img")
            items.append({
                "token": token,
                "id": token,
                "image": img["src"] if img and img.get("src") else None,
            })
        logger.info("HTML fallback (links): found %d items", len(items))
        return items

    for card in cards:
        item: dict = {}

        # ID / token
        for attr in ("data-id", "data-order-id", "id"):
            val = card.get(attr, "").strip()
            if val and not val.startswith("feed"):
                item["id"] = val
                break
        link = card.find("a", href=re.compile(r"/item/"))
        if link:
            token = link["href"].rstrip("/").split("/")[-1]
            item.setdefault("id", token)
            item["token"] = token

        if not item.get("id"):
            continue

        title_el = card.find(["h2", "h3"]) or card.find(class_=re.compile("title", re.I))
        if title_el:
            item["title"] = title_el.get_text(strip=True)

        price_el = card.find(class_=re.compile("price", re.I))
        if price_el:
            item["price"] = re.sub(r"[^\d]", "", price_el.get_text())

        img = card.find("img")
        if img and img.get("src"):
            item["image"] = img["src"]

        items.append(item)

    logger.info("HTML fallback (cards): found %d items", len(items))
    return items


def _text(field) -> str:
    """Extract text from either a plain string or a Yad2 {id, text} dict."""
    if isinstance(field, dict):
        return field.get("text", "")
    return str(field) if field else ""


def _parse_listing(item: dict) -> Optional["Listing"]:
    try:
        lid = str(item.get("token") or item.get("id") or item.get("orderId", ""))
        if not lid:
            return None

        manufacturer = _text(item.get("manufacturer"))
        model = _text(item.get("model"))
        sub_model = _text(item.get("subModel"))
        title_parts = [manufacturer, model, sub_model]
        title = " ".join(p for p in title_parts if p).strip() or item.get("title", "") or lid

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

        # year: flat int or nested in vehicleDates
        year_raw = item.get("year") or (item.get("vehicleDates") or {}).get("yearOfProduction")
        try:
            year = int(year_raw) if year_raw else None
        except (ValueError, TypeError):
            year = None

        # hand: flat int or {id, text} dict
        hand_raw = item.get("hand")
        try:
            hand = int(hand_raw["id"]) if isinstance(hand_raw, dict) else (int(hand_raw) if hand_raw else None)
        except (ValueError, TypeError, KeyError):
            hand = None

        # city: flat string or nested address.area.text
        city = (
            item.get("city")
            or item.get("area")
            or _text((item.get("address") or {}).get("area"))
        ) or None

        # images: metaData.coverImage / metaData.images[], or legacy fields
        meta = item.get("metaData") or {}
        image_url = meta.get("coverImage")
        if not image_url:
            meta_images = meta.get("images") or []
            image_url = meta_images[0] if meta_images else None
        if not image_url:
            images = item.get("images") or []
            if isinstance(images, list) and images:
                first = images[0]
                image_url = first.get("src") or first.get("url") if isinstance(first, dict) else first
        if not image_url:
            image_url = item.get("mainImage") or item.get("image")

        token = item.get("token") or lid
        listing_url = f"https://www.yad2.co.il/item/{token}"

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
            brand=manufacturer,
        )
    except Exception as e:
        logger.warning("Failed to parse listing: %s", e)
        return None


def _matches_brands(listing: "Listing", brands: list[str]) -> bool:
    if not brands:
        return True
    brand = (listing.brand or "").strip()
    title = (listing.title or "").strip()
    return any(b in brand or b in title for b in brands)


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
    time.sleep(random.uniform(2, 5))

    url = build_search_url(cfg)
    logger.info("Scraping URL: %s", url)

    try:
        html = _fetch_html(url)
    except Exception as e:
        logger.error("HTTP error scraping Yad2: %s", e)
        return []

    # Try __NEXT_DATA__ first (richest data), fall back to HTML parsing
    raw_items = _extract_next_data(html)
    if not raw_items:
        logger.info("No __NEXT_DATA__ items found, falling back to HTML parsing")
        raw_items = _extract_from_html(html, url)

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
