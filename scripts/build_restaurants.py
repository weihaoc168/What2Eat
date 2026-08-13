"""Merge place candidates, their classification, and the Ohio-era taste profile
into data/restaurants.json for the weekend 下馆子 picker.

Inputs (all under private/, produced by parse_places.py and the two
classification workflows):
  places_candidates.json   local candidates + ohio corpus
  places_classified.json   {"results": [{name, category, cuisine, local}]}
  ohio_classified.json     {"results": [{name, category, cuisine}]}  (optional)

Output data/restaurants.json:
  visited:  local eating places the family reviewed (去过)
  wishlist: local 正餐 they saved but never reviewed (想去)
  pref:     cuisine -> 0..1 affinity learned from the pre-relocation Ohio saves
            (reviewed places weigh 3x a plain save)
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CUISINE_NORM = {
    "川菜": "川湘", "湘菜": "川湘", "串串": "火锅", "韩式烧烤": "韩餐",
    "饮品": "奶茶", "烘焙": "甜品", "早茶": "粤菜", "寿司": "日料", "拉面": "日料",
    "土耳其": "中东", "西班牙": "西餐", "意大利": "西餐", "法餐": "西餐",
    "云南米线": "面食", "炸鸡": "美式", "汉堡": "美式",
}
FOOD_CATS = ("正餐", "快餐", "饮品甜品")


def norm(c):
    return CUISINE_NORM.get(c, c)


def load(rel):
    p = os.path.join(ROOT, rel)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def main():
    cand = load("private/places_candidates.json")
    cls = {c["name"]: c for c in load("private/places_classified.json")["results"]}

    visited, wishlist = [], []
    for p in cand["places"]:
        c = cls.get(p["name"])
        if not c or not c["local"] or c["category"] not in ("正餐", "快餐"):
            continue
        entry = {
            "name": p["name"], "cuisine": norm(c["cuisine"]), "km": p["km"],
            "fast": c["category"] == "快餐", "url": p.get("url", ""),
        }
        if p["reviewed"]:
            entry["rating"] = p.get("rating")
            entry["v"] = True
            visited.append(entry)
        else:
            # a fast-food chain nobody has been to is not a weekend recommendation
            if not entry["fast"]:
                wishlist.append(entry)
    wishlist.sort(key=lambda x: x["km"] if x["km"] is not None else 999)

    pref = {}
    ohio_cls = load("private/ohio_classified.json")
    if ohio_cls:
        reviewed = {p["name"] for p in cand.get("ohio", []) if p["reviewed"]}
        # reviews of far-away places live outside the ohio saved list too
        reviewed |= {p["name"] for p in cand["places"] if p["reviewed"]}
        scores = {}
        for r in ohio_cls["results"]:
            if r["category"] not in FOOD_CATS:
                continue
            cu = norm(r["cuisine"])
            scores[cu] = scores.get(cu, 0) + (3 if r["name"] in reviewed else 1)
        if scores:
            top = max(scores.values())
            pref = {k: round(v / top, 2) for k, v in sorted(scores.items(), key=lambda x: -x[1])}

    out = {"visited": visited, "wishlist": wishlist, "pref": pref}
    json.dump(out, open(os.path.join(ROOT, "data", "restaurants.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"visited: {len(visited)}, wishlist: {len(wishlist)}, pref cuisines: {len(pref)}")
    print("pref:", json.dumps(pref, ensure_ascii=False))


if __name__ == "__main__":
    main()
