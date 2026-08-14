"""Merge the crop pipeline output into the app's data files.

Reads private/final_pipeline.json ({verify, tags, ingredients}) plus
private/crop_index_compact.json, then:
  - fills photos for existing photo-less dishes,
  - appends new dishes to data/workflow_result.json (source "album"),
  - appends their tags to data/album_tags.json,
  - appends their ingredients to data/ingredients.json.
Idempotent: names already present are skipped.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = lambda rel: os.path.join(ROOT, rel)
load = lambda rel: json.load(open(p(rel), encoding="utf-8"))
save = lambda rel, obj: json.dump(obj, open(p(rel), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

pipe = load("private/final_pipeline.json")
index = {x["n"]: x for x in load("private/crop_index_compact.json")}
verify = {d["name"]: d for d in pipe["verify"]}
tags = {d["name"]: d for d in pipe["tags"]}
ing = {d["name"]: d for d in pipe["ingredients"]}

wf = load("data/workflow_result.json")
existing = {d["name"]: d for d in wf["dishes"]}

filled = added = 0
for name, ix in index.items():
    v = verify.get(name, {})
    best = v.get("best")
    if not ix["new"]:
        d = existing.get(name)
        if d is not None and not d.get("best") and best:
            d["best"] = best
            d["confirmed"] = v.get("ok", [])
            d["photoCount"] = max(d.get("photoCount", 0), ix["det"])
            filled += 1
        continue
    if name in existing:
        continue
    wf["dishes"].append({
        "name": name, "source": "album", "best": best,
        "confirmed": v.get("ok", []), "photoCount": ix["det"],
    })
    added += 1
save("data/workflow_result.json", wf)

at = load("data/album_tags.json")
have = {d["name"] for d in at["dishes"]}
tagged = 0
for name, ix in index.items():
    if not ix["new"] or name in have:
        continue
    t = tags.get(name)
    if not t:
        t = {"meal": ix["meal"], "cat": ["纤维"], "meat": [], "spice": 0, "cuisine": "家常", "flags": []}
    meat = [m for m in t.get("meat", []) if m != "无"]
    at["dishes"].append({
        "name": name, "meal": t.get("meal", ix["meal"]), "cat": t.get("cat", ["纤维"]) or ["纤维"],
        "meat": meat, "spice": t.get("spice", 0),
        "cuisine": t.get("cuisine", "家常"), "flags": t.get("flags", []),
    })
    tagged += 1
save("data/album_tags.json", at)

ig = load("data/ingredients.json")
have_i = {d["name"] for d in ig["dishes"]}
ing_added = 0
for name, ix in index.items():
    if not ix["new"] or name in have_i:
        continue
    rec = ing.get(name)
    if rec and rec.get("ingredients"):
        ig["dishes"].append({"name": name, "ingredients": rec["ingredients"]})
        ing_added += 1
save("data/ingredients.json", ig)

with_photo = sum(1 for d in wf["dishes"] if d.get("best"))
print(f"existing photo-less dishes filled: {filled}")
print(f"new dishes added: {added} (tags: {tagged}, ingredients: {ing_added})")
print(f"total dishes: {len(wf['dishes'])}, with photo: {with_photo}")
