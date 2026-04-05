import json
import pytest
from unittest.mock import patch, MagicMock

from scraper import (
    _build_url_params,
    _parse_listing,
    _matches_brands,
    _extract_items,
    _extract_next_data,
    _extract_from_html,
    build_search_url,
    scrape,
    Listing,
)


# ---------------------------------------------------------------------------
# build_search_url
# ---------------------------------------------------------------------------

def test_build_search_url_from_config():
    cfg = {"price_min": 9000, "price_max": 14000, "km_max": 100000,
           "year_min": 2000, "year_max": 2014, "hand_max": 3}
    url = build_search_url(cfg)
    assert "price=9000-14000" in url
    assert "km=0-100000" in url
    assert "year=2000-2014" in url
    assert "hand=1-3" in url


def test_build_search_url_custom_overrides():
    cfg = {"search_url": "https://www.yad2.co.il/vehicles/cars?price=1-2",
           "price_min": 9000, "price_max": 14000}
    url = build_search_url(cfg)
    assert url == "https://www.yad2.co.il/vehicles/cars?price=1-2"


def test_build_search_url_empty_custom_falls_back():
    cfg = {"search_url": "", "price_min": 5000, "price_max": 20000}
    url = build_search_url(cfg)
    assert "price=5000-20000" in url


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
# _extract_next_data
# ---------------------------------------------------------------------------

def test_extract_next_data_feed_items():
    payload = {"props": {"pageProps": {"feed_items": [
        {"id": "1", "manufacturer": "טויוטה"},
        {"id": "2", "manufacturer": "הונדה"},
    ]}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    items = _extract_next_data(html)
    assert len(items) == 2


def test_extract_next_data_no_script():
    assert _extract_next_data("<html><body>nothing</body></html>") == []


def test_extract_next_data_bad_json():
    html = '<script id="__NEXT_DATA__">{bad json</script>'
    assert _extract_next_data(html) == []


# ---------------------------------------------------------------------------
# _extract_from_html
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<html><body>
  <ul>
    <li data-id="t1">
      <a href="/item/t1"><img src="https://img.example.com/1.jpg"></a>
      <h2>טויוטה קורולה</h2>
      <span class="price">45,000</span>
    </li>
    <li data-id="t2">
      <a href="/item/t2"><img src="https://img.example.com/2.jpg"></a>
      <h2>הונדה סיוויק</h2>
      <span class="price">38,000</span>
    </li>
  </ul>
</body></html>
"""


def test_extract_from_html_finds_items():
    items = _extract_from_html(SAMPLE_HTML, "https://www.yad2.co.il/vehicles/cars")
    # Should find items via the /item/ link fallback
    ids = [i.get("id") or i.get("token") for i in items]
    assert "t1" in ids
    assert "t2" in ids


# ---------------------------------------------------------------------------
# scrape (HTTP mocked)
# ---------------------------------------------------------------------------

RAW_ITEMS = [
    {**SAMPLE_ITEM, "manufacturer": "טויוטה"},
    {**SAMPLE_ITEM, "id": "ad1", "type": "ad"},
    {**SAMPLE_ITEM, "id": "xyz", "manufacturer": "הונדה"},
]

CFG = {
    "brands": ["טויוטה"],
    "price_min": 0, "price_max": 200000,
    "km_max": 300000,
    "year_min": 2000, "year_max": 2025,
    "hand_max": 3,
    "scan_interval": 30,
    "search_url": "",
}


def test_scrape_filters_ads_and_brands():
    with patch("scraper._fetch_html", return_value="<html></html>"), \
         patch("scraper._extract_next_data", return_value=RAW_ITEMS), \
         patch("scraper.time") as mock_time:
        mock_time.sleep = MagicMock()
        listings = scrape(CFG)

    assert len(listings) == 1
    assert listings[0].brand == "טויוטה"


def test_scrape_returns_empty_on_http_error():
    with patch("scraper._fetch_html", side_effect=Exception("connection error")), \
         patch("scraper.time") as mock_time:
        mock_time.sleep = MagicMock()
        listings = scrape(CFG)

    assert listings == []


def test_scrape_falls_back_to_html_when_no_next_data():
    payload = {"props": {"pageProps": {"feed_items": [
        {"id": "n1", "manufacturer": "טויוטה", "token": "n1"},
    ]}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    with patch("scraper._fetch_html", return_value=html), \
         patch("scraper.time") as mock_time:
        mock_time.sleep = MagicMock()
        listings = scrape({**CFG, "brands": []})

    assert any(l.listing_id == "n1" for l in listings)
