"""Fetch each restaurant's hero photo from its Google Maps place page.

The business photo is JS-rendered, so this drives headless Chromium, opens each
place URL, and grabs the first googleusercontent.com/p/ image (the page's cover
photo). Thumbnails land in rest_photos/ + data/rest_photos.json — gitignored,
derived from the family's saved places.

Usage: python scripts/fetch_rest_photos.py [--limit N] [--force]
"""
import io
import json
import os
import re
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTD = os.path.join(ROOT, "rest_photos")
IDX = os.path.join(ROOT, "data", "rest_photos.json")
SIZE = 168


def main():
    from PIL import Image
    from playwright.sync_api import sync_playwright

    rest = json.load(open(os.path.join(ROOT, "data", "restaurants.json"), encoding="utf-8"))
    entries = rest.get("visited", []) + rest.get("wishlist", [])
    dp = os.path.join(ROOT, "data", "rest_discover.json")
    if os.path.exists(dp):
        entries = entries + json.load(open(dp, encoding="utf-8"))
    done = {} if "--force" in sys.argv else (
        json.load(open(IDX, encoding="utf-8")) if os.path.exists(IDX) else {})
    os.makedirs(OUTD, exist_ok=True)

    todo = [r for r in entries if r.get("url") and done.get(r["name"]) is None]
    if "--limit" in sys.argv:
        todo = todo[: int(sys.argv[sys.argv.index("--limit") + 1])]
    if not todo:
        print("没有需要抓取的餐厅")
        return
    print(f"抓取 {len(todo)} 家餐厅的地图封面照片 ...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900},
                                locale="en-US")
        for i, r in enumerate(todo, 1):
            try:
                page.goto(r["url"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                src = page.evaluate(
                    "() => { const im = [...document.querySelectorAll('img')]"
                    ".find(i => /googleusercontent\.com\/(p\/|gps-cs-s\/)/.test(i.src));"
                    " return im ? im.src : null; }")
                if not src:
                    print(f"  [{i}] {r['name']}: 页面上没有商家照片")
                    done[r["name"]] = None
                    continue
                src = re.sub(r"=w\d+-h\d+[^\"']*$", f"=w{SIZE * 2}-h{SIZE * 2}-k-no", src)
                raw = urllib.request.urlopen(urllib.request.Request(
                    src, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read()
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                w, h = im.size
                s = min(w, h)
                im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
                im = im.resize((SIZE, SIZE), Image.LANCZOS)
                fname = f"r{abs(hash(r['name'])) % 99999}.jpg"
                im.save(os.path.join(OUTD, fname), "JPEG", quality=80)
                done[r["name"]] = fname
                print(f"  [{i}] {r['name']} ✓")
            except Exception as e:
                print(f"  [{i}] {r['name']}: {type(e).__name__}")
                done.setdefault(r["name"], None)
            json.dump(done, open(IDX, "w", encoding="utf-8"), ensure_ascii=False)
        browser.close()
    got = sum(1 for v in done.values() if v)
    print(f"完成：{got}/{len(done)} 家有照片")


if __name__ == "__main__":
    main()
