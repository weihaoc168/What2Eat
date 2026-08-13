"""Parse Google Takeout saved places and reviews into a candidate list for
restaurant recommendations.

Reads every Takeout folder under private/timeline/:
  - "Saved Places.json" / "已保存的地点.json"  -> saved (wishlist candidates)
  - "评价.json" / "Reviews.json"               -> reviewed (visited evidence)
  - "Labeled places.json"                      -> home coordinates for distance

Output: private/places_candidates.json, deduped by Maps cid (falling back to
name), each with distance from home. Places beyond --max-km (default 60) are
dropped: weekend dinner stays in the metro area, travel saves are noise here.
"""
import argparse
import glob
import json
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "private", "timeline")


def feats(path):
    try:
        return json.load(open(path, encoding="utf-8")).get("features", [])
    except Exception:
        return []


def cid_of(props):
    m = re.search(r"cid=(\d+)", props.get("google_maps_url", ""))
    return m.group(1) if m else None


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[1], a[0], b[1], b[0]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-km", type=float, default=60.0)
    args = ap.parse_args()

    home = None
    saved, reviews = {}, {}
    for f in glob.glob(os.path.join(SRC, "**", "*.json"), recursive=True):
        base = os.path.basename(f)
        if "Labeled" in base or "已加标签" in base:
            for ft in feats(f):
                if ft.get("properties", {}).get("name") == "Home":
                    home = ft["geometry"]["coordinates"]
        elif "Saved Places" in base or "已保存的地点" in base:
            for ft in feats(f):
                p = ft.get("properties", {})
                loc = p.get("location", {})
                if not loc.get("name"):
                    continue
                key = cid_of(p) or loc["name"].lower()
                e = saved.setdefault(key, {
                    "name": loc["name"], "address": loc.get("address", ""),
                    "coords": ft.get("geometry", {}).get("coordinates"),
                    "saved": p.get("date", ""), "accounts": 0,
                    "url": p.get("google_maps_url", ""),
                })
                e["accounts"] += 1
        elif "评价" in base or "Reviews" in base:
            for ft in feats(f):
                p = ft.get("properties", {})
                loc = p.get("location", {})
                if not loc.get("name"):
                    continue
                key = loc["name"].lower()
                reviews[key] = {
                    "name": loc["name"], "address": loc.get("address", ""),
                    "rating": p.get("five_star_rating_published"),
                    "date": p.get("date", ""),
                }
    if home is None:
        raise SystemExit("No labeled Home found; add --home lat,lng support or label Home in Maps")

    out = []
    away = []
    for e in saved.values():
        d = km(home, e["coords"]) if e.get("coords") else None
        rev = reviews.get(e["name"].lower())
        row = {
            "name": e["name"], "address": e["address"],
            "km": round(d, 1) if d is not None else None,
            "saved": e["saved"], "accounts": e["accounts"],
            "reviewed": bool(rev), "rating": rev["rating"] if rev else None,
            "url": e.get("url", ""),
        }
        if d is not None and d > args.max_km:
            away.append(row)
        else:
            out.append(row)
    # reviewed places that were never saved still count as visited candidates
    saved_names = {e["name"].lower() for e in saved.values()}
    for r in reviews.values():
        if r["name"].lower() not in saved_names:
            out.append({"name": r["name"], "address": r["address"], "km": None,
                        "saved": "", "accounts": 0, "reviewed": True, "rating": r["rating"]})
    out.sort(key=lambda x: (not x["reviewed"], x["km"] if x["km"] is not None else 999))
    # pre-relocation life area (Ohio and neighbors) is kept separately as the
    # taste-preference corpus; other far places are travel noise
    ohio = [a for a in away if re.search(r",\s*(OH|IN|KY)\s+\d{5}", a["address"])]
    os.makedirs(os.path.join(ROOT, "private"), exist_ok=True)
    dst = os.path.join(ROOT, "private", "places_candidates.json")
    json.dump({"home": home, "places": out, "ohio": ohio},
              open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"saved places deduped: {len(saved)}; reviews: {len(reviews)}; "
          f"kept within {args.max_km:.0f}km: {len(out)}; ohio-era corpus: {len(ohio)}; "
          f"other far/travel: {len(away) - len(ohio)}")


if __name__ == "__main__":
    main()
