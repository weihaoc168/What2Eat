"""Fetch grocery prices for the app's ingredient search terms (build-time bake).

Usage:
  python scripts/fetch_prices.py hmart            # works headless, no login needed
  python scripts/fetch_prices.py heb costco       # needs profiles from retail_login.py
  python scripts/fetch_prices.py --all

Reads unique non-pantry ingredient "en" terms from data/ingredients.json, searches
each retailer, and writes/merges data/prices.json:
  {"<retailer>": {"<term>": {"fetched": "...", "products": [{"name","price"}]}}}

HEB and Costco run inside the persistent logged-in profile (headed, because both
sites block plain headless traffic). H Mart runs headless. Selectors are
best-effort heuristics: each product tile is found by walking up from a $price
text node to a container that also carries a title-like text.
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

SEARCH_URLS = {
    "hmart": "https://www.hmart.com/?search={q}",
    "heb": "https://www.heb.com/search?q={q}",
    "costco": "https://www.costco.com/s?keyword={q}",
}
HEADLESS = {"hmart": True, "heb": False, "costco": False}

# walk up from each $x.yz text node to a small container that also has a name-ish
# text; return top tiles as {name, price}
EXTRACT_JS = """
() => {
  const seen = new Set(), out = [];
  const priceRe = /\\$\\d{1,3}(?:\\.\\d\\d)/;
  const nodes = document.evaluate("//*[contains(text(), '$')]", document, null,
    XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
  for (let i = 0; i < nodes.snapshotLength && out.length < 8; i++) {
    let el = nodes.snapshotItem(i);
    const m = (el.textContent || '').match(priceRe);
    if (!m) continue;
    let box = el;
    for (let up = 0; up < 6 && box.parentElement; up++) {
      box = box.parentElement;
      const t = box.innerText || '';
      if (t.length > 400) break;
      const lines = t.split('\\n').map(s => s.trim()).filter(Boolean);
      const name = lines.find(s => s.length > 12 && !s.includes('$') && !/^(add|sign|save|sale|each|log)/i.test(s));
      if (name) {
        const key = name + m[0];
        if (!seen.has(key)) { seen.add(key); out.push({ name: name.slice(0, 90), price: m[0] }); }
        break;
      }
    }
  }
  return out;
}
"""


def load_terms():
    ing = json.load(open(os.path.join(ROOT, "data", "ingredients.json"), encoding="utf-8"))
    terms = []
    for d in ing["dishes"]:
        for i in d["ingredients"]:
            if not i["pantry"] and i["en"] not in terms:
                terms.append(i["en"])
    return terms


def fetch_hmart_api(terms, prices):
    """H Mart runs on VTEX; the public catalog API returns products with prices."""
    store = prices.setdefault("hmart", {})
    stamp = dt.date.today().isoformat()
    ctx = ssl.create_default_context()
    ok = fail = 0
    def query(q):
        url = ("https://www.hmart.com/api/catalog_system/pub/products/search/"
               f"{urllib.parse.quote(q)}?_from=0&_to=4")
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
            data = json.loads(r.read())
        products = []
        for p in data:
            try:
                offer = p["items"][0]["sellers"][0]["commertialOffer"]
            except (KeyError, IndexError):
                continue
            price = offer.get("Price")
            if price:
                products.append({"name": p.get("productName", ""), "price": f"${price:.2f}"})
        return products

    def variants(t):
        yield t
        if t.endswith("es"):
            yield t[:-2]
        elif t.endswith("s"):
            yield t[:-1]
        words = t.split()
        if len(words) > 1:
            tail = words[-1]
            yield tail[:-1] if tail.endswith("s") and len(tail) > 3 else tail

    for t in terms:
        cur = store.get(t)
        if cur and cur.get("fetched") == stamp and cur.get("products"):
            continue
        products = []
        try:
            for q in variants(t):
                products = query(q)
                if products:
                    break
        except Exception as e:
            print(f"[hmart] {t}: ERROR {str(e)[:80]}")
        store[t] = {"fetched": stamp, "products": products[:5]}
        ok += 1 if products else 0
        fail += 0 if products else 1
        print(f"[hmart] {t}: {len(products)} products {products[0]['price'] if products else ''}")
    print(f"[hmart] done: {ok} with prices, {fail} empty/failed")


def fetch_retailer(p, retailer, terms, prices):
    url_tpl = SEARCH_URLS[retailer]
    profile = os.path.join(ROOT, "private", "profiles", retailer)
    if HEADLESS[retailer]:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="en-US", viewport={"width": 1366, "height": 900})
    else:
        if not os.path.isdir(profile):
            print(f"[{retailer}] no profile yet, run: python scripts/retail_login.py {retailer}")
            return
        ctx = p.chromium.launch_persistent_context(
            profile, headless=False, viewport={"width": 1366, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
    page = ctx.new_page()
    store = prices.setdefault(retailer, {})
    stamp = dt.date.today().isoformat()
    ok = fail = 0
    for t in terms:
        if t in store and store[t].get("fetched") == stamp:
            continue
        try:
            page.goto(url_tpl.format(q=t.replace(" ", "+")), timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(4500)
            products = page.evaluate(EXTRACT_JS)
            store[t] = {"fetched": stamp, "products": products[:5]}
            ok += 1 if products else 0
            fail += 0 if products else 1
            print(f"[{retailer}] {t}: {len(products)} products {products[0]['price'] if products else ''}")
        except Exception as e:
            fail += 1
            print(f"[{retailer}] {t}: ERROR {str(e)[:80]}")
    ctx.close()
    print(f"[{retailer}] done: {ok} with prices, {fail} empty/failed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("retailers", nargs="*", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only first N terms (for testing)")
    args = ap.parse_args()
    targets = list(SEARCH_URLS) if args.all else args.retailers
    if not targets:
        raise SystemExit("name retailers (hmart/heb/costco) or pass --all")
    terms = load_terms()
    if args.limit:
        terms = terms[: args.limit]
    print(f"{len(terms)} search terms")
    ppath = os.path.join(ROOT, "data", "prices.json")
    prices = json.load(open(ppath, encoding="utf-8")) if os.path.exists(ppath) else {}
    if "hmart" in targets:
        fetch_hmart_api(terms, prices)
        targets = [t for t in targets if t != "hmart"]
    if targets:
        with sync_playwright() as p:
            for r in targets:
                fetch_retailer(p, r, terms, prices)
    json.dump(prices, open(ppath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote data/prices.json")


if __name__ == "__main__":
    main()
