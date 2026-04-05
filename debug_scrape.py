"""
Debug scraping script — fetches a sample Yad2 search page and shows what was extracted.

Usage:
    python debug_scrape.py [url]

If no URL is provided, uses the default search URL with sample filters.
"""

import json
import sys

from scraper import (
    YAD2_SEARCH_URL,
    HEADERS,
    _fetch_html,
    _extract_next_data,
    _extract_from_html,
    _parse_listing,
)

DEFAULT_URL = f"{YAD2_SEARCH_URL}?price=9000-14000&km=0-100000&year=2000-2014&hand=1-3"


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print(f"Fetching: {url}\n")

    try:
        html = _fetch_html(url)
    except Exception as e:
        print(f"[ERROR] HTTP fetch failed: {e}")
        sys.exit(1)

    print(f"Got {len(html)} bytes of HTML")

    # --- Strategy 1: __NEXT_DATA__ ---
    print("\n=== Strategy 1: __NEXT_DATA__ ===")
    items = _extract_next_data(html)
    if items:
        print(f"Found {len(items)} items")
        _print_sample(items)
    else:
        print("No items found in __NEXT_DATA__")

        # --- Strategy 2: HTML parsing ---
        print("\n=== Strategy 2: HTML parsing ===")
        items = _extract_from_html(html, url)
        if items:
            print(f"Found {len(items)} items")
            _print_sample(items)
        else:
            print("No items found in HTML either")
            print("\nFirst 2000 chars of HTML for inspection:")
            print(html[:2000])


def _print_sample(items, n=3):
    for item in items[:n]:
        listing = _parse_listing(item)
        if listing:
            print(json.dumps({
                "id": listing.listing_id,
                "title": listing.title,
                "price": listing.price,
                "year": listing.year,
                "km": listing.km,
                "hand": listing.hand,
                "city": listing.city,
                "url": listing.listing_url,
            }, ensure_ascii=False, indent=2))
        else:
            print(f"  (raw, could not parse): {json.dumps(item, ensure_ascii=False, default=str)[:200]}")


if __name__ == "__main__":
    main()
