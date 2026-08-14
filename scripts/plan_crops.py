"""Turn detections + name clusters into a concrete crop plan.

Reads:
  private/detections.json   per-photo dish detections with fractional bboxes
  private/clusters.json     canonical new-dish clusters (variants merged)
  data/workflow_result.json existing dishes (to know which lack photos)
  data/manifest.json        photo timestamps for recency ranking

Writes:
  private/xl_wanted.json    photo files needing the 1280px original
  private/crop_plan.json    [{file, bbox, out}] for crop_dishes.py
  private/crop_index.json   {dish: {meal, new, candidates: [out...]}} ranked
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load = lambda rel: json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))

det = load("private/detections.json")["results"]
clusters = load("private/clusters.json")["clusters"]
wf = load("data/workflow_result.json")
manifest = {m["id"]: m for m in load("data/manifest.json")}

existing = {d["name"]: d for d in wf["dishes"]}
photoless = {n for n, d in existing.items() if not d.get("best")}

canon = {}
meal_of = {}
for c in clusters:
    for v in c["variants"]:
        canon[v] = c["name"]
    meal_of[c["name"]] = c["meal"]

CONF = {"high": 3, "med": 2, "low": 1}
cands = {}
for ph in det:
    pid = int(ph["file"].split(".")[0])
    t = manifest.get(pid, {}).get("time", 0)
    for d in ph["dishes"]:
        name = d["name"] if d["name"] in existing else canon.get(d["name"])
        if not name:
            continue
        is_new = name not in existing
        if not is_new and name not in photoless:
            continue  # existing dish already has a photo
        x, y, w, h = d["bbox"]
        area = max(0.0, min(1.0, w)) * max(0.0, min(1.0, h))
        if area < 0.03:
            continue  # too tiny to make a card photo
        score = (CONF.get(d["conf"], 1), 1 if 0.06 <= area <= 0.55 else 0, t)
        cands.setdefault(name, []).append({"file": ph["file"], "bbox": d["bbox"], "score": score})

plan, index, wanted = [], {}, set()
for name, lst in cands.items():
    lst.sort(key=lambda c: c["score"], reverse=True)
    outs = []
    for k, c in enumerate(lst[:4]):
        out = f"{c['file'].split('.')[0]}_c{k}.jpg"
        plan.append({"file": c["file"], "bbox": c["bbox"], "out": out})
        outs.append(out)
        wanted.add(c["file"])
    index[name] = {
        "meal": meal_of.get(name) or existing.get(name, {}).get("meal") or "副菜",
        "new": name not in existing,
        "detections": len(lst),
        "candidates": outs,
    }

json.dump(sorted(wanted), open(os.path.join(ROOT, "private", "xl_wanted.json"), "w", encoding="utf-8"))
json.dump(plan, open(os.path.join(ROOT, "private", "crop_plan.json"), "w", encoding="utf-8"))
json.dump(index, open(os.path.join(ROOT, "private", "crop_index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
new_n = sum(1 for v in index.values() if v["new"])
old_n = sum(1 for v in index.values() if not v["new"])
print(f"dishes to crop for: {len(index)} ({new_n} new, {old_n} existing photo-less)")
print(f"crops planned: {len(plan)} from {len(wanted)} source photos")
