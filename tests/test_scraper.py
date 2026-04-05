import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from scraper import (
    _build_url_params,
    _parse_listing,
    _matches_brands,
    _extract_items,
    scrape,
    Listing,
)


# ---------------------------------------------------------------------------
# _build_url_params
# ---------------------------------------------------------------------------

def test_build_url_params_full():
    cfg = {
        "price_min": 9000, "price_max": 14000,
        "km_max": 100000,
        "year_min": 2000, "year_max": 2014,
        "hand_max": 3,
    }
    params = _build_url_params(cfg)
    assert params["price"] == "9000-14000"
    assert params["km"] == "0-100000"
    assert params["year"] == "2000-2014"
    assert params["hand"] == "1-3"


def test_build_url_params_no_hand():
    params = _build_url_params({"hand_max": 0})
    assert "hand" not in params


def test_build_url_params_empty():
    params = _build_url_params({})
    assert params == {}


# ---------------------------------------------------------------------------
# _parse_listing
# ---------------------------------------------------------------------------

SAMPLE_ITEM = {
    "id": "abc123",
    "manufacturer": "טויוטה",
    "model": "קורולה",
    "subModel": "GLi",
    "price": "55,000",
    "km": "120,000",
    "year": 2018,
    "hand": 2,
    "city": "תל אביב",
    "images": [{"src": "https://img.example.com/car.jpg"}],
    "token": "abc123",
}


def test_parse_listing_basic():
    listing = _parse_listing(SAMPLE_ITEM)
    assert listing is not None
    assert listing.listing_id == "abc123"
    assert listing.title == "טויוטה קורולה GLi"
    assert listing.price == 55000
    assert listing.km == 120000
    assert listing.year == 2018
    assert listing.hand == 2
    assert listing.city == "תל אביב"
    assert listing.image_url == "https://img.example.com/car.jpg"
    assert listing.listing_url == "https://www.yad2.co.il/item/abc123"


def test_parse_listing_missing_id_returns_none():
    assert _parse_listing({}) is None


def test_parse_listing_bad_price():
    item = {**SAMPLE_ITEM, "price": "N/A"}
    listing = _parse_listing(item)
    assert listing is not None
    assert listing.price is None


def test_parse_listing_image_string_list():
    item = {**SAMPLE_ITEM, "images": ["https://img.example.com/x.jpg"]}
    listing = _parse_listing(item)
    assert listing.image_url == "https://img.example.com/x.jpg"


def test_parse_listing_fallback_image():
    item = {**SAMPLE_ITEM, "images": [], "mainImage": "https://img.example.com/main.jpg"}
    listing = _parse_listing(item)
    assert listing.image_url == "https://img.example.com/main.jpg"


# ---------------------------------------------------------------------------
# _matches_brands
# ---------------------------------------------------------------------------

def make_listing(**kwargs) -> Listing:
    defaults = dict(
        listing_id="1", title="טויוטה קורולה", price=50000,
        km=80000, year=2018, hand=1, city="חיפה",
        image_url=None, listing_url="https://www.yad2.co.il/item/1",
        brand="טויוטה",
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def test_matches_brands_hit():
    assert _matches_brands(make_listing(), ["טויוטה", "מאזדה"]) is True


def test_matches_brands_miss():
    assert _matches_brands(make_listing(), ["הונדה"]) is False


def test_matches_brands_empty_filter():
    assert _matches_brands(make_listing(), []) is True


# ---------------------------------------------------------------------------
# _extract_items
# ---------------------------------------------------------------------------

def test_extract_items_nested_feed():
    data = {"data": {"feed": {"feed_items": [{"id": "1"}, {"id": "2"}]}}}
    items = _extract_items(data)
    assert len(items) == 2


def test_extract_items_flat_list():
    data = {"data": [{"id": "1"}]}
    items = _extract_items(data)
    assert len(items) == 1


def test_extract_items_filters_non_dicts():
    data = {"data": {"items": [{"id": "1"}, "bad", None]}}
    items = _extract_items(data)
    assert items == [{"id": "1"}]


# ---------------------------------------------------------------------------
# scrape (integration-style, Playwright mocked)
# ---------------------------------------------------------------------------

RAW_ITEMS = [
    {**SAMPLE_ITEM, "manufacturer": "טויוטה"},
    {**SAMPLE_ITEM, "id": "ad1", "type": "ad"},          # should be filtered
    {**SAMPLE_ITEM, "id": "xyz", "manufacturer": "הונדה"},  # wrong brand
]

CFG = {
    "brands": ["טויוטה"],
    "price_min": 0, "price_max": 200000,
    "km_max": 300000,
    "year_min": 2000, "year_max": 2025,
    "hand_max": 3,
    "scan_interval": 30,
}


@pytest.mark.asyncio
async def test_scrape_filters_ads_and_brands():
    with patch("scraper._scrape_with_playwright", new=AsyncMock(return_value=RAW_ITEMS)):
        listings = await scrape(CFG)

    assert len(listings) == 1
    assert listings[0].brand == "טויוטה"


@pytest.mark.asyncio
async def test_scrape_returns_empty_on_playwright_failure():
    with patch("scraper._scrape_with_playwright", side_effect=RuntimeError("boom")):
        listings = await scrape(CFG)

    assert listings == []
