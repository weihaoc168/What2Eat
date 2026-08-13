"""One-time interactive login per retailer, saved into a persistent browser profile.

Usage: python scripts/retail_login.py heb|costco|hmart

Opens a visible Chromium window on the retailer's sign-in page. Log in yourself
(password + any 2FA). The session lives in private/profiles/<retailer>/ and is
reused by fetch_prices.py and the receipt scrapers. Nothing is sent anywhere.
The window stays open up to 6 minutes; close it when you are done logging in.
"""
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOGIN_URLS = {
    "heb": "https://www.heb.com/my-account/login",
    "costco": "https://www.costco.com/myaccount/home",
    "hmart": "https://www.hmart.com/customer/account/login",
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in LOGIN_URLS:
        raise SystemExit(f"usage: python scripts/retail_login.py {'|'.join(LOGIN_URLS)}")
    retailer = sys.argv[1]
    profile = os.path.join(ROOT, "private", "profiles", retailer)
    os.makedirs(profile, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile, headless=False, viewport={"width": 1200, "height": 860},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(LOGIN_URLS[retailer], timeout=60000, wait_until="domcontentloaded")
        print(f"Log in to {retailer} in the window. It closes automatically in 6 minutes,\n"
              "or close it yourself once you are logged in. The session is saved either way.")
        try:
            page.wait_for_event("close", timeout=360000)
        except Exception:
            pass
        try:
            ctx.close()
        except Exception:
            pass
    print(f"Profile saved: {profile}")


if __name__ == "__main__":
    main()
