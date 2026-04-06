"""
First-time Facebook Marketplace login setup.

Run once on a machine with a display:
    python setup_fb.py

In Docker with X11 forwarding (Linux):
    docker-compose run --rm -e DISPLAY=$DISPLAY \
        -v /tmp/.X11-unix:/tmp/.X11-unix yad2bot python setup_fb.py

The session is saved to FB_PROFILE_DIR (default: fb_profile/).
Subsequent bot runs reuse this profile in headless mode.
"""
import asyncio
import os

from playwright.async_api import async_playwright

from config import FB_PROFILE_DIR


async def main():
    profile_dir = os.path.abspath(FB_PROFILE_DIR)
    os.makedirs(profile_dir, exist_ok=True)
    print(f"Profile will be saved to: {profile_dir}")
    print("A browser window will open. Log in to Facebook, then come back here.")

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        await page.goto("https://www.facebook.com/marketplace/")

        input("\nPress Enter here once you are logged in to Facebook...\n")

        if "login" in page.url:
            print("WARNING: Still on login page — session may not have been saved.")
        else:
            print("Login detected. Session saved successfully.")

        await ctx.close()

    print(f"\nDone. Profile saved to: {profile_dir}")
    print("You can now run the bot normally: python main.py")


if __name__ == "__main__":
    asyncio.run(main())
