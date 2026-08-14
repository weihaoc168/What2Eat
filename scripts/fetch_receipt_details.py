"""Fetch full item detail for every Costco warehouse receipt.

Opens the Warehouse orders tab, clicks the first receipt to capture the
detail GraphQL request (URL, auth headers, query template), then replays
that request for every barcode in private/receipts/barcodes.json.
Details land in private/receipts/details.json (local only).
"""
import io
import json
import os
import sys

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECD = os.path.join(ROOT, "private", "receipts")
PROFILE = os.path.join(ROOT, "private", "profiles", "costco_real")

barcodes = json.load(open(os.path.join(RECD, "barcodes.json"), encoding="utf-8"))
template = {}


def on_request(req):
    if "ecom-api.costco.com" in req.url and req.post_data and "receiptsWithCounts($barcode" in req.post_data:
        if not template:
            template.update({"url": req.url, "post": req.post_data, "headers": dict(req.headers)})
            print("captured detail request template")


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE, headless=False, channel="chrome", viewport={"width": 1280, "height": 900})
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("request", on_request)
    page.goto("https://www.costco.com/myaccount/orders", timeout=60000, wait_until="domcontentloaded")
    page.wait_for_timeout(9000)
    for sel_try in ('[role="tab"]:has-text("Warehouse")', 'button:text-is("Warehouse")', 'text="Warehouse"'):
        loc = page.locator(sel_try)
        hit = None
        for i in range(loc.count()):
            if loc.nth(i).is_visible():
                hit = loc.nth(i)
                break
        if hit:
            hit.click()
            break
    page.wait_for_timeout(8000)

    # open the first receipt to observe the detail call
    for sel_try in ("button:has-text('View Receipt')", "a:has-text('View Receipt')",
                    "text=/View.*Receipt/i", "[class*='receipt'] a"):
        loc = page.locator(sel_try).first
        try:
            if loc.count() and loc.is_visible():
                loc.click()
                print("opened first receipt via", sel_try)
                break
        except Exception:
            continue
    page.wait_for_timeout(8000)

    if not template:
        print("FAILED to capture detail request; dumping visible buttons")
        print(page.evaluate("[...document.querySelectorAll('button,a')].filter(e=>e.offsetParent).map(e=>e.innerText.trim()).filter(Boolean).slice(0,40)"))
        ctx.close()
        sys.exit(1)

    post = json.loads(template["post"])
    hdrs = {k: v for k, v in template["headers"].items()
            if not k.startswith(":") and k.lower() not in ("content-length", "host")}
    out = {}
    ok = fail = 0
    for bc, meta in barcodes.items():
        vars_ = dict(post.get("variables") or {})
        vars_["barcode"] = bc
        vars_["documentType"] = "warehouse"
        payload = {"query": post["query"], "variables": vars_}
        try:
            res = ctx.request.post(template["url"], headers=hdrs, data=json.dumps(payload), timeout=30000)
            body = res.json()
            node = (body.get("data") or {}).get("receiptsWithCounts") or {}
            recs = node.get("receipts") or []
            if recs:
                out[bc] = recs[0] if isinstance(recs, list) else recs
                ok += 1
            else:
                fail += 1
                if fail <= 2:
                    print("empty:", bc[:20], str(body)[:150])
        except Exception as e:
            fail += 1
            if fail <= 3:
                print("err:", str(e)[:100])
    json.dump(out, open(os.path.join(RECD, "details.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"details fetched: {ok} ok, {fail} failed -> private/receipts/details.json")
    ctx.close()
