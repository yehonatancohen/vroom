import random
import time
import logging
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
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
    color: Optional[str] = field(default=None)
    test_date: Optional[str] = field(default=None)   # "MM/YYYY"
    listed_at: Optional[datetime] = field(default=None)


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
    """Pull listing items from the __NEXT_DATA__ JSON Yad2 embeds in the page."""
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []

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


def _extract_detail(html: str) -> Optional[dict]:
    """Extract the full listing dict from a detail page's __NEXT_DATA__."""
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        return (
            data
            .get("props", {})
            .get("pageProps", {})
            .get("dehydratedState", {})
            .get("queries", [{}])[0]
            .get("state", {})
            .get("data")
        )
    except (json.JSONDecodeError, IndexError, AttributeError):
        return None


def fetch_listing_detail(token: str) -> Optional[dict]:
    """Fetch the detail page for a listing and return its raw data dict."""
    url = f"https://www.yad2.co.il/item/{token}"
    try:
        time.sleep(random.uniform(0.5, 1.5))
        html = _fetch_html(url)
        return _extract_detail(html)
    except Exception as e:
        logger.warning("Failed to fetch detail for %s: %s", token, e)
        return None


def _extract_from_html(html: str, page_url: str) -> list[dict]:
    """Fallback: parse visible feed cards from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    items = []

    cards = (
        soup.select("[data-testid='feed-item']")
        or soup.select(".feed_item")
        or soup.select("li[class*='feedItem']")
        or soup.select("li[class*='item']")
    )

    if not cards:
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


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt[:len(raw[:19])])
        except ValueError:
            continue
    return None


def _parse_listing(item: dict, detail: Optional[dict] = None) -> Optional["Listing"]:
    """Parse a search-result item, optionally enriched with detail-page data."""
    try:
        src = detail if detail else item
        lid = str(src.get("token") or src.get("id") or src.get("orderId", "")
                  or item.get("token") or item.get("id") or item.get("orderId", ""))
        if not lid:
            return None

        manufacturer = _text(src.get("manufacturer") or item.get("manufacturer"))
        model = _text(src.get("model") or item.get("model"))
        sub_model = _text(src.get("subModel") or item.get("subModel"))
        title = " ".join(p for p in [manufacturer, model, sub_model] if p).strip() or lid

        price_raw = src.get("price") or item.get("price")
        try:
            price = int(str(price_raw).replace(",", "").replace("₪", "").strip()) if price_raw else None
        except (ValueError, AttributeError):
            price = None

        km_raw = src.get("km") or src.get("kilometers")
        try:
            km = int(str(km_raw).replace(",", "").strip()) if km_raw is not None else None
        except (ValueError, AttributeError):
            km = None

        vehicle_dates = src.get("vehicleDates") or item.get("vehicleDates") or {}
        year_raw = src.get("year") or vehicle_dates.get("yearOfProduction")
        try:
            year = int(year_raw) if year_raw else None
        except (ValueError, TypeError):
            year = None

        hand_raw = src.get("hand") or item.get("hand")
        try:
            hand = int(hand_raw["id"]) if isinstance(hand_raw, dict) else (int(hand_raw) if hand_raw else None)
        except (ValueError, TypeError, KeyError):
            hand = None

        address = src.get("address") or item.get("address") or {}
        city = (
            _text(address.get("city"))
            or _text(address.get("area"))
            or item.get("city")
        ) or None

        meta = src.get("metaData") or item.get("metaData") or {}
        image_url = (
            meta.get("coverImage")
            or (meta.get("images") or [None])[0]
            or item.get("mainImage") or item.get("image")
        )

        color = _text(src.get("color")) or None

        test_date_raw = vehicle_dates.get("testDate")
        test_date = None
        if test_date_raw:
            try:
                dt = datetime.strptime(test_date_raw[:10], "%Y-%m-%d")
                test_date = f"{dt.month:02d}/{dt.year}"
            except ValueError:
                pass

        dates = src.get("dates") or {}
        listed_at = _parse_dt(dates.get("createdAt"))

        token = src.get("token") or item.get("token") or lid
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
            color=color,
            test_date=test_date,
            listed_at=listed_at,
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


def _matches_model_filter(listing: "Listing", model_filter: list[str]) -> bool:
    if not model_filter:
        return True
    title = (listing.title or "").lower()
    return any(kw.lower() in title for kw in model_filter)


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


@dataclass
class ScrapeResult:
    listings: list  # list[Listing] matching all filters
    total_on_page: int  # raw items found (excluding ads/banners)
    filtered_by_brand: int  # items that passed brand filter
    filtered_by_since: int  # items skipped because listed_at <= since


def scrape(cfg: dict, since: Optional[datetime] = None) -> ScrapeResult:
    """
    Fetch search results and enrich each new listing with detail-page data.
    `since`: if set, only return listings created after this datetime.
    Returns a ScrapeResult with counts for reporting.
    """
    time.sleep(random.uniform(2, 5))

    url = build_search_url(cfg)
    logger.info("Scraping URL: %s", url)

    try:
        html = _fetch_html(url)
    except Exception as e:
        logger.error("HTTP error scraping Yad2: %s", e)
        return ScrapeResult(listings=[], total_on_page=0, filtered_by_brand=0, filtered_by_since=0)

    raw_items = _extract_next_data(html)
    if not raw_items:
        logger.info("No __NEXT_DATA__ items found, falling back to HTML parsing")
        raw_items = _extract_from_html(html, url)

    brands_filter = cfg.get("brands", [])
    model_filter = cfg.get("model_filter", [])
    listings = []
    total_on_page = 0
    filtered_by_brand = 0
    filtered_by_since = 0

    for item in raw_items:
        if item.get("type") in ("ad", "banner", "yad1"):
            continue

        total_on_page += 1

        # Quick brand+model pre-filter using search-result data before fetching detail
        pre = _parse_listing(item)
        if not pre or not _matches_brands(pre, brands_filter):
            continue
        if not _matches_model_filter(pre, model_filter):
            continue

        filtered_by_brand += 1

        # Fetch detail page for km, color, test date, listed_at
        token = item.get("token") or pre.listing_id
        detail = fetch_listing_detail(token)
        listing = _parse_listing(item, detail)
        if not listing:
            continue

        if since and listing.listed_at and listing.listed_at <= since:
            logger.debug("Skipping %s listed at %s (before since=%s)", token, listing.listed_at, since)
            filtered_by_since += 1
            continue

        listings.append(listing)

    logger.info("Scraped %d matching listings (total_on_page=%d, brand_match=%d, skipped_since=%d)",
                len(listings), total_on_page, filtered_by_brand, filtered_by_since)
    return ScrapeResult(
        listings=listings,
        total_on_page=total_on_page,
        filtered_by_brand=filtered_by_brand,
        filtered_by_since=filtered_by_since,
    )
