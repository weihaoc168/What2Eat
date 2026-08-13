"""Parse Google Timeline exports into data/restaurants.json for weekend restaurant picks.

Drop export files into private/timeline/ (any mix of both accounts):
  - Phone export (current): Google Maps -> avatar -> Your Timeline -> settings ->
    Export Timeline data. Produces JSON with "semanticSegments".
  - Legacy Takeout: Semantic Location History monthly JSONs with "timelineObjects".

Usage: python scripts/parse_timeline.py

Output: data/restaurants.json with visit counts and last-visit dates, food places only.
Places that come without a display name (common in phone exports) are kept under their
placeId so they can be resolved later; the summary prints how many need resolving.
"""
import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "private", "timeline")

FOOD_TYPES = re.compile(r"restaurant|food|cafe|coffee|bakery|bar|meal|dining|tea|dessert|noodle|bbq|hot ?pot", re.I)
NON_FOOD_NAMES = re.compile(r"^(home|work|gym|school|church|airport)$", re.I)


def norm_key(name, place_id):
    return (name or "").strip().lower() or f"pid:{place_id}"


def walk_files():
    pats = [os.path.join(SRC, "**", "*.json")]
    for pat in pats:
        for f in glob.glob(pat, recursive=True):
            yield f


def visits_from_file(path):
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print(f"skip {os.path.basename(path)}: {e}")
        return
    # current phone export
    for seg in data.get("semanticSegments", []):
        v = seg.get("visit")
        if not v:
            continue
        cand = v.get("topCandidate", {})
        yield {
            "name": cand.get("name") or (cand.get("placeLocation") or {}).get("name"),
            "placeId": cand.get("placeId") or cand.get("placeID"),
            "type": cand.get("semanticType") or "",
            "time": seg.get("startTime") or "",
        }
    # legacy Takeout
    for obj in data.get("timelineObjects", []):
        pv = obj.get("placeVisit")
        if not pv:
            continue
        loc = pv.get("location", {})
        yield {
            "name": loc.get("name"),
            "placeId": loc.get("placeId"),
            "type": " ".join(loc.get("sourceInfo", {}).get("deviceTag", []) if isinstance(loc.get("sourceInfo"), dict) else []) or loc.get("semanticType", ""),
            "time": (pv.get("duration") or {}).get("startTimestamp", ""),
        }


def main():
    if not os.path.isdir(SRC) or not any(walk_files()):
        raise SystemExit(f"No exports found. Put Timeline JSON files under {SRC}")
    places = {}
    total = 0
    for f in walk_files():
        for v in visits_from_file(f):
            total += 1
            name = v["name"]
            if name and NON_FOOD_NAMES.match(name.strip()):
                continue
            # keep everything that looks food-related OR is unnamed (resolved later)
            if name and not FOOD_TYPES.search(v.get("type") or "") and not FOOD_TYPES.search(name):
                # unnamed types still pass through when type hints food; otherwise keep
                # named non-food places out only when the type clearly says non-food
                if v.get("type") and not FOOD_TYPES.search(v["type"]):
                    continue
            k = norm_key(name, v.get("placeId"))
            p = places.setdefault(k, {"name": name, "placeId": v.get("placeId"), "visits": 0, "lastVisit": ""})
            p["visits"] += 1
            if v["time"] > p["lastVisit"]:
                p["lastVisit"] = v["time"]
    out = sorted(places.values(), key=lambda x: -x["visits"])
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    json.dump({"places": out}, open(os.path.join(ROOT, "data", "restaurants.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    unnamed = sum(1 for p in out if not p["name"])
    print(f"visits scanned: {total}; places kept: {len(out)}; unnamed (need placeId lookup): {unnamed}")
    for p in out[:15]:
        print(f"  {p['visits']:>3}x  {p['name'] or p['placeId']}")


if __name__ == "__main__":
    main()
