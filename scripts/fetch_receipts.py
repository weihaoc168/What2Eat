"""Pull Costco warehouse receipts by driving the logged-in profile.

Opens Orders & Purchases -> Warehouse tab, walks every option in the
"Showing" date-range dropdown, and records every ecom-api GraphQL response.
Raw captures land in private/receipts/costco_raw_<n>.json; nothing leaves
this machine. Run scripts/parse_receipts.py afterwards.
"""
import io
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "private", "receipts")
os.makedirs(OUT, exist_ok=True)
PROFILE = os.path.join(ROOT, "private", "profiles", "costco_real")

captures = []
seen = set()


def on_response(res):
    try:
        if "ecom-api.costco.com" not in res.url:
            return
        req = res.request
        body = ""
        try:
            body = res.text()
        except Exception:
            return
        key = hash((req.post_data or "") + body[:200])
        if key in seen or len(body) < 60:
            return
        seen.add(key)
        captures.append({"url": res.url, "post": req.post_data or "", "body": body})
        q = ""
        if req.post_data and '"query"' in req.post_data:
            q = req.post_data.split("query ")[1][:40] if "query " in req.post_data else ""
        print(f"  captured {len(body)} bytes  {q}")
    except Exception:
        pass


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome", viewport={"width": 1280, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto("https://www.costco.com/myaccount/orders", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(10000)

    wh = None
    for sel_try in ('[role="tab"]:has-text("Warehouse")', 'button:text-is("Warehouse")',
                    'a:text-is("Warehouse")', 'text="Warehouse"'):
        loc = page.locator(sel_try)
        for i in range(loc.count()):
            cand = loc.nth(i)
            try:
                if cand.is_visible():
                    wh = cand
                    break
            except Exception:
                continue
        if wh:
            break
    if wh:
        wh.click()
        print("opened Warehouse tab")
        page.wait_for_timeout(8000)
    else:
        print("WARN: Warehouse tab not found")

    # walk every option of the Showing dropdown
    sel = page.locator("select").first
    options = []
    if sel.count():
        options = sel.evaluate("s => [...s.options].map(o => o.value)")
        print("date-range options:", options)
        for val in options:
            try:
                sel.select_option(val)
                print("range:", val)
                page.wait_for_timeout(9000)
                # click through pagination if present
                for _ in range(30):
                    nxt = page.locator("button[aria-label*='next' i], a[aria-label*='next' i], li.forward a").first
                    try:
                        if nxt.count() and nxt.is_visible() and nxt.is_enabled():
                            nxt.click()
                            page.wait_for_timeout(6000)
                        else:
                            break
                    except Exception:
                        break
            except Exception as e:
                print("range error:", str(e)[:80])
    else:
        print("WARN: Showing dropdown not found")

    page.screenshot(path=os.path.join(OUT, "warehouse_tab.png"))
    ctx.close()

stamp = time.strftime("%Y%m%d_%H%M%S")
dst = os.path.join(OUT, f"costco_raw_{stamp}.json")
json.dump(captures, open(dst, "w", encoding="utf-8"), ensure_ascii=False)
print(f"saved {len(captures)} captures -> {dst}")
