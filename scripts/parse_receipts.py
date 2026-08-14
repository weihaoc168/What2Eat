"""Normalize Costco receipt details into transactions + a unique item table.

Reads private/receipts/details.json, writes:
  private/receipts/transactions.json  [{date, warehouse, total, items:[...]}]
  private/receipts/unique_items.json  [{num, desc, dept, times, total}] for categorization
"""
import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECD = os.path.join(ROOT, "private", "receipts")

details = json.load(open(os.path.join(RECD, "details.json"), encoding="utf-8"))
txns = []
uniq = defaultdict(lambda: {"times": 0, "total": 0.0, "desc": "", "dept": None})
for bc, r in details.items():
    items = []
    for it in r.get("itemArray", []):
        desc = (it.get("itemDescription01") or "").strip()
        amt = it.get("amount")
        if not desc or amt is None:
            continue
        num = str(it.get("itemNumber") or "")
        qty = it.get("unit") or 1
        items.append({"num": num, "desc": desc, "dept": it.get("itemDepartmentNumber"),
                      "qty": qty, "amount": amt})
        u = uniq[num or desc]
        u["times"] += 1
        u["total"] += amt if isinstance(amt, (int, float)) else 0
        u["desc"] = desc
        u["dept"] = it.get("itemDepartmentNumber")
    txns.append({
        "barcode": bc,
        "date": (r.get("transactionDateTime") or "")[:10],
        "warehouse": r.get("warehouseName"),
        "total": r.get("total"),
        "items": items,
    })
txns.sort(key=lambda t: t["date"])
json.dump(txns, open(os.path.join(RECD, "transactions.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
uni = [{"num": k, **v, "total": round(v["total"], 2)} for k, v in uniq.items()]
uni.sort(key=lambda x: -x["total"])
json.dump(uni, open(os.path.join(RECD, "unique_items.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
line_items = sum(len(t["items"]) for t in txns)
print(f"transactions: {len(txns)}, line items: {line_items}, unique items: {len(uni)}")
print("top spend items:", [(u['desc'], u['total']) for u in uni[:8]])
