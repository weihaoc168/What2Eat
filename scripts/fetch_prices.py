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
import sys

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
    with sync_playwright() as p:
        for r in targets:
            fetch_retailer(p, r, terms, prices)
    json.dump(prices, open(ppath, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"wrote data/prices.json")


if __name__ == "__main__":
    main()
