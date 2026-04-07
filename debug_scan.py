"""
Manual scan script — runs both Yad2 and FB Marketplace and prints results.

Usage:
    python debug_scan.py              # uses config from DB (or defaults)
    python debug_scan.py --fb-only    # skip Yad2
    python debug_scan.py --yad2-only  # skip FB Marketplace
    python debug_scan.py --fb-only --debug   # also save fb_debug_page.html

Keep this script in sync with fb_scraper.scrape_fb() and scraper.scrape()
when changing scraper interfaces or config keys.
"""
import asyncio
import argparse
import logging
import os
from datetime import datetime, timedelta

import db
import scraper
import fb_scraper
import formatter
from config import DEFAULT_CONFIG

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)


def _print_results(label: str, result) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  total_on_page={result.total_on_page}  "
          f"filtered_by_brand={result.filtered_by_brand}  "
          f"filtered_by_since={result.filtered_by_since}  "
          f"listings={len(result.listings)}")
    print(f"{'='*60}")
    for listing in result.listings:
        text = formatter.format_listing(listing)
        text = text.replace("*", "").replace("[לצפייה במודעה]", "")
        print(text)
        print()
    if not result.listings:
        print("  (no listings)")


async def main(skip_yad2: bool, skip_fb: bool) -> None:
    db.init_db()
    cfg = db.get_config()
    since = datetime.now() - timedelta(weeks=1)

    print(f"\nConfig: {cfg}")
    print(f"Since:  {since.strftime('%Y-%m-%d %H:%M')}\n")

    yad2_result = None
    fb_result = None

    if not skip_yad2:
        print("Running Yad2 scraper...")
        loop = asyncio.get_event_loop()
        try:
            yad2_result = await loop.run_in_executor(None, scraper.scrape, cfg, since)
        except Exception as e:
            print(f"[Yad2 ERROR] {e}")

    if not skip_fb:
        print("Running FB Marketplace scraper...")
        try:
            fb_result = await fb_scraper.scrape_fb(cfg, since)
        except Exception as e:
            print(f"[FB ERROR] {e}")

    if yad2_result is not None:
        _print_results("YAD2 RESULTS", yad2_result)

    if fb_result is not None:
        _print_results("FACEBOOK MARKETPLACE RESULTS", fb_result)

    total = len(yad2_result.listings if yad2_result else []) + \
            len(fb_result.listings if fb_result else [])
    print(f"\nTotal listings: {total}")

    if not skip_fb and os.environ.get("FB_DEBUG"):
        print("\nfb_debug_page.html saved — open it in a browser to see what FB returned.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug scan for both scrapers")
    parser.add_argument("--fb-only", action="store_true", help="Skip Yad2")
    parser.add_argument("--yad2-only", action="store_true", help="Skip FB Marketplace")
    parser.add_argument("--debug", action="store_true",
                        help="Save FB page HTML to fb_debug_page.html for inspection")
    args = parser.parse_args()

    if args.debug:
        os.environ["FB_DEBUG"] = "1"

    asyncio.run(main(skip_yad2=args.fb_only, skip_fb=args.yad2_only))
