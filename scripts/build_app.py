"""Build dist/jiali-de-cai.html: merge matching results, tags, and photos into the app.

Inputs (repo-relative):
  app_template.html            UI template with a /*__DISHES_JSON__*/[] placeholder
  data/workflow_result.json    photo-to-dish matching produced by the vision workflow
  data/dish_tags.json          tags for the menu-list dishes
  data/album_tags.json         tags for album-discovered dishes
  m_thumbs/ or thumbs/         representative photos (m-size preferred)

The output embeds photos as base64 data URIs, so dist/ is gitignored on a public repo.
"""
import base64
import io
import json
import os
import sys

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_EDGE = 620
JPEG_Q = 72


def load(rel, default=None):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        if default is not None:
            return default
        sys.exit(f"missing {rel}")
    return json.load(open(p, encoding="utf-8"))


result = load("data/workflow_result.json")
tags = {d["name"]: d for d in load("data/dish_tags.json")["dishes"]}
album_tags = {d["name"]: d for d in load("data/album_tags.json", {"dishes": []})["dishes"]}

DEFAULT_ALBUM = {"meal": "副菜", "cat": ["蛋白"], "meat": [], "spice": 0, "cuisine": "家常", "flags": []}


def img_uri(file):
    if not file:
        return None
    pid = file.split(".")[0]
    for sub in ("crops", "xl_thumbs", "m_thumbs", "thumbs"):
        p = os.path.join(ROOT, sub, pid + ".jpg")
        if os.path.exists(p) and open(p, "rb").read(3) == b"\xff\xd8\xff":
            raw = open(p, "rb").read()
            if Image is not None:
                im = Image.open(io.BytesIO(raw))
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((MAX_EDGE, MAX_EDGE))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=JPEG_Q, optimize=True, progressive=True)
                if buf.tell() < len(raw):
                    raw = buf.getvalue()
            return "data:image/jpeg;base64," + base64.b64encode(raw).decode()
    return None


gen_path = os.path.join(ROOT, "data", "gen_images.json")
gen_images = json.load(open(gen_path, encoding="utf-8")) if os.path.exists(gen_path) else {}

dishes = []
for d in result["dishes"]:
    name = d["name"]
    t = tags.get(name) or album_tags.get(name) or {**DEFAULT_ALBUM, "name": name}
    dishes.append({
        "name": name,
        "meal": t["meal"],
        "cat": t["cat"],
        "meat": t["meat"],
        "spice": t["spice"],
        "cui": t["cuisine"],
        "flags": t["flags"],
        "src": d["source"],
        "count": d.get("photoCount", 0),
        "img": img_uri(d.get("best")) or gen_images.get(name),
    })

order = {"早饭": 0, "主菜": 1, "副菜": 2}
dishes.sort(key=lambda x: (order.get(x["meal"], 3), x["src"] != "list", -x["count"]))

tpl = open(os.path.join(ROOT, "app_template.html"), encoding="utf-8").read()
payload = json.dumps(dishes, ensure_ascii=False, separators=(",", ":"))
html = tpl.replace("/*__DISHES_JSON__*/[]", payload, 1)
rest_path = os.path.join(ROOT, "data", "restaurants.json")
if os.path.exists(rest_path):
    rest_obj = json.load(open(rest_path, encoding="utf-8"))
    rh_path = os.path.join(ROOT, "data", "rest_health.json")
    rh = json.load(open(rh_path, encoding="utf-8")) if os.path.exists(rh_path) else {}
    for grp in ("visited", "wishlist"):
        for r in rest_obj.get(grp, []):
            if rh.get(r["name"]):
                r["health"] = rh[r["name"]]
    rp_path = os.path.join(ROOT, "data", "rest_photos.json")
    if os.path.exists(rp_path):
        rp = json.load(open(rp_path, encoding="utf-8"))
        for grp in ("visited", "wishlist"):
            for r in rest_obj.get(grp, []):
                f = rp.get(r["name"])
                p = os.path.join(ROOT, "rest_photos", f) if f else None
                if p and os.path.exists(p):
                    r["img"] = "data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode()
    rest = json.dumps(rest_obj, ensure_ascii=False, separators=(",", ":"))
else:
    rest = "null"
html = html.replace("/*__REST_JSON__*/null", rest, 1)

ing_path = os.path.join(ROOT, "data", "ingredients.json")
if os.path.exists(ing_path):
    ing = {d["name"]: d["ingredients"] for d in json.load(open(ing_path, encoding="utf-8"))["dishes"]}
    html = html.replace("/*__ING_JSON__*/null", json.dumps(ing, ensure_ascii=False, separators=(",", ":")), 1)

spend_path = os.path.join(ROOT, "data", "spending.json")
if os.path.exists(spend_path):
    html = html.replace("/*__SPEND_JSON__*/null",
                        json.dumps(json.load(open(spend_path, encoding="utf-8")),
                                   ensure_ascii=False, separators=(",", ":")), 1)

prices_path = os.path.join(ROOT, "data", "prices.json")
if os.path.exists(prices_path):
    raw = json.load(open(prices_path, encoding="utf-8"))
    pruned = {}
    for shop, terms in raw.items():
        keep = {}
        for term, rec in terms.items():
            prods = rec.get("products") or []
            if prods:
                # first result = search relevance; keep name for the tooltip
                keep[term] = {"name": prods[0]["name"], "price": prods[0]["price"]}
                if rec.get("source"):
                    keep[term]["src"] = rec["source"]
        pruned[shop] = keep
    html = html.replace("/*__PRICES_JSON__*/null", json.dumps(pruned, ensure_ascii=False, separators=(",", ":")), 1)
os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)
out = os.path.join(ROOT, "dist", "jiali-de-cai.html")
open(out, "w", encoding="utf-8").write(html)
size = os.path.getsize(out)
with_img = sum(1 for x in dishes if x["img"])
print(f"wrote dist/jiali-de-cai.html: {len(dishes)} dishes, {with_img} with photos, {size/1e6:.2f} MB")
if size > 15_000_000:
    sys.exit("output exceeds the 16 MB artifact limit, compress images first")
