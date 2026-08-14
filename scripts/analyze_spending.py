"""Aggregate receipt transactions into the spending summary the app embeds.

Reads private/receipts/transactions.json + item_categories.json, writes
data/spending.json (gitignored, personal data):
  months     last 12 months of spend (total + food-only)
  cats       category breakdown over the full window
  topRepeat  frequently repurchased items with average cycle in days
  stats      receipts count, avg basket, visits/month, food share
"""
import json
import os
from collections import defaultdict
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECD = os.path.join(ROOT, "private", "receipts")

txns = json.load(open(os.path.join(RECD, "transactions.json"), encoding="utf-8"))
cats = {c["num"]: c for c in json.load(open(os.path.join(RECD, "item_categories.json"), encoding="utf-8"))["items"]}
FOOD = {"肉类", "海鲜", "蔬菜", "水果", "蛋奶", "主食", "零食", "饮料", "调味", "熟食"}

by_month = defaultdict(lambda: {"total": 0.0, "food": 0.0})
by_cat = defaultdict(float)
item_dates = defaultdict(list)
item_amts = defaultdict(list)

for t in txns:
    ym = t["date"][:7]
    for it in t["items"]:
        amt = it["amount"] or 0
        c = cats.get(it["num"] or it["desc"], {})
        cat = c.get("cat", "其他")
        by_month[ym]["total"] += amt
        if cat in FOOD:
            by_month[ym]["food"] += amt
        by_cat[cat] += amt
        key = it["num"] or it["desc"]
        item_dates[key].append(t["date"])
        item_amts[key].append(amt)

months = sorted(by_month)[-12:]
month_rows = [{"ym": m, "total": round(by_month[m]["total"], 2), "food": round(by_month[m]["food"], 2)} for m in months]

total_all = sum(by_cat.values())
cat_rows = [{"cat": k, "total": round(v, 2), "pct": round(100 * v / total_all, 1)}
            for k, v in sorted(by_cat.items(), key=lambda x: -x[1])]

top = []
for key, ds in item_dates.items():
    times = len(ds)
    if times < 3:
        continue
    dds = sorted(date.fromisoformat(d) for d in ds)
    gaps = [(b - a).days for a, b in zip(dds, dds[1:]) if (b - a).days > 0]
    cycle = round(sum(gaps) / len(gaps)) if gaps else None
    c = cats.get(key, {})
    top.append({
        "cn": c.get("cn") or key, "cat": c.get("cat", "其他"), "times": times,
        "avg": round(sum(item_amts[key]) / times, 2), "cycle": cycle,
        "last": dds[-1].isoformat(),
    })
top.sort(key=lambda x: -x["times"])

fruits = []
for key, ds in item_dates.items():
    c = cats.get(key, {})
    if c.get("cat") != "水果" or len(ds) < 2:
        continue
    dds = sorted(date.fromisoformat(d) for d in ds)
    gaps = [(b - a).days for a, b in zip(dds, dds[1:]) if (b - a).days > 0]
    fruits.append({
        "cn": c.get("cn") or key, "times": len(ds),
        "avg": round(sum(item_amts[key]) / len(ds), 2),
        "cycle": round(sum(gaps) / len(gaps)) if gaps else None,
    })
fruits.sort(key=lambda x: -x["times"])

n_months = max(1, len({t["date"][:7] for t in txns}))
out = {
    "updated": date.today().isoformat(),
    "source": "Costco 仓库小票",
    "window": f"{txns[0]['date']} ~ {txns[-1]['date']}",
    "months": month_rows,
    "cats": cat_rows,
    "topRepeat": top[:14],
    "fruits": fruits[:16],
    "stats": {
        "receipts": len(txns),
        "avgBasket": round(sum(t["total"] or 0 for t in txns) / len(txns), 2),
        "visitsPerMonth": round(len(txns) / n_months, 1),
        "foodShare": round(100 * sum(m["food"] for m in month_rows) / max(1e-9, sum(m["total"] for m in month_rows)), 1),
    },
}
json.dump(out, open(os.path.join(ROOT, "data", "spending.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("stats:", out["stats"])
print("top cats:", [(c['cat'], c['pct']) for c in cat_rows[:6]])
print("top repeats:", [(t['cn'], t['times'], t['cycle']) for t in top[:6]])
