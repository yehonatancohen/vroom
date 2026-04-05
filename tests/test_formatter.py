from datetime import datetime
from scraper import Listing
from formatter import format_listing, format_config


def make_listing(**kwargs) -> Listing:
    defaults = dict(
        listing_id="1", title="מאזדה 3", price=45000,
        km=75000, year=2016, hand=2, city="ירושלים",
        image_url="https://img.example.com/car.jpg",
        listing_url="https://www.yad2.co.il/item/1",
        brand="מאזדה", color="כסף", test_date="06/2026",
        listed_at=datetime(2025, 11, 17, 20, 34, 59),
    )
    defaults.update(kwargs)
    return Listing(**defaults)


def test_format_listing_contains_title():
    text = format_listing(make_listing())
    assert "מאזדה 3" in text


def test_format_listing_contains_price():
    text = format_listing(make_listing())
    assert "45,000" in text


def test_format_listing_no_price():
    text = format_listing(make_listing(price=None))
    assert "מחיר לא צוין" in text


def test_format_listing_contains_url():
    text = format_listing(make_listing())
    assert "https://www.yad2.co.il/item/1" in text


def test_format_listing_contains_city():
    text = format_listing(make_listing())
    assert "ירושלים" in text


def test_format_listing_contains_km():
    text = format_listing(make_listing())
    assert "75,000" in text


def test_format_listing_contains_color():
    text = format_listing(make_listing())
    assert "כסף" in text


def test_format_listing_contains_test_date():
    text = format_listing(make_listing())
    assert "06/2026" in text


def test_format_listing_contains_listed_at():
    text = format_listing(make_listing())
    assert "17/11/2025" in text


def test_format_listing_no_optional_fields():
    listing = make_listing(km=None, color=None, test_date=None, listed_at=None)
    text = format_listing(listing)
    assert "טסט" not in text
    assert "פורסם" not in text


def test_format_config_brands():
    cfg = {"brands": ["טויוטה", "הונדה"], "price_min": 0, "price_max": 200000,
           "km_max": 100000, "year_min": 2010, "year_max": 2025,
           "hand_max": 2, "scan_interval": 30, "max_results": 5}
    text = format_config(cfg)
    assert "טויוטה" in text
    assert "הונדה" in text


def test_format_config_no_brands():
    cfg = {"brands": [], "price_min": 0, "price_max": 200000,
           "km_max": 100000, "year_min": 2010, "year_max": 2025,
           "hand_max": 0, "scan_interval": 30, "max_results": 0}
    text = format_config(cfg)
    assert "הכל" in text
    assert "ללא הגבלה" in text
