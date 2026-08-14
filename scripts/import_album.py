"""Standalone album importer: pull new photos from the Synology share, recognize
dishes with the Claude API, merge them into the dish library, and rebuild the app.

No interactive assistant involved — runs end to end on any host with:
  .env       SYNO_HOST / SYNO_PORT / SHARE_PASSPHRASE / ANTHROPIC_API_KEY
  pip install anthropic pillow

Usage:
  python scripts/import_album.py               # incremental: only photos newer than last run
  python scripts/import_album.py --dry-run     # recognize but write nothing (safe test)
  python scripts/import_album.py --backfill 3  # force the 3 newest photos through (testing)
  python scripts/import_album.py --init        # mark all current photos as imported (baseline)

State lives in private/imported_ids.json. First run without state auto-baselines
(current album = already imported) so only photos added afterwards are processed.
"""
import argparse
import base64
import json
import os
import ssl
import subprocess
import sys
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "private", "imported_ids.json")
MODEL = "claude-opus-5"
BATCH = 6

MEALS = ["早饭", "肉菜", "蔬菜", "小菜", "点心", "汤", "水果"]
ING_CATS = ["肉类", "海鲜", "蛋奶", "蔬菜", "豆制品", "主食", "干货", "调味"]


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    for k in ("SYNO_HOST", "SHARE_PASSPHRASE"):
        if not os.environ.get(k):
            sys.exit(f"缺少 {k}：请在仓库根目录 .env 里配置（参考 .env.example）")


# ---------- Synology share fetch (self-contained copy of the share API dance) ----------
CTX = ssl._create_unverified_context()
COOKIE = {}


def http(url, data=None, share_header=True):
    req = urllib.request.Request(url, data=data)
    if share_header:
        # the landing page only sets sharing_sid when this header is absent
        req.add_header("X-SYNO-SHARING", os.environ["SHARE_PASSPHRASE"])
    if COOKIE:
        req.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in COOKIE.items()))
    with urllib.request.urlopen(req, context=CTX, timeout=30) as r:
        for part in r.headers.get_all("Set-Cookie") or []:
            kv = part.split(";", 1)[0]
            if "=" in kv:
                k, v = kv.split("=", 1)
                COOKIE[k] = v
        return r.read()


def syno_connect():
    base = f"https://{os.environ['SYNO_HOST']}:{os.environ.get('SYNO_PORT', '5001')}"
    passp = os.environ["SHARE_PASSPHRASE"]
    http(f"{base}/mo/sharing/{passp}", share_header=False)

    def api(params):
        qs = urllib.parse.urlencode({**params, "passphrase": f'"{passp}"'})
        out = json.loads(http(f"{base}/mo/sharing/webapi/entry.cgi", qs.encode()))
        if not out.get("success"):
            sys.exit(f"Synology API error {out.get('error')} for {params.get('api')}")
        return out["data"]

    return base, passp, api


def fetch_manifest(api):
    items, offset = [], 0
    while True:
        data = api({
            "api": "SYNO.Foto.Browse.Item", "method": "list", "version": "4",
            "offset": offset, "limit": 500, "sort_by": "takentime", "sort_direction": "asc",
            "additional": '["thumbnail"]',
        })
        chunk = data.get("list", [])
        for it in chunk:
            th = (it.get("additional") or {}).get("thumbnail") or {}
            items.append({
                "id": it["id"],
                "unit_id": th.get("unit_id", it["id"]),
                "filename": it.get("filename", ""),
                "time": it.get("time", 0),
                "cache_key": th.get("cache_key", ""),
            })
        if len(chunk) < 500:
            return items
        offset += 500


def fetch_thumb(base, passp, item, size, dest):
    qs = urllib.parse.urlencode({
        "api": "SYNO.Foto.Thumbnail", "method": "get", "version": "2",
        "id": item["unit_id"], "type": '"unit"', "size": f'"{size}"',
        "cache_key": f'"{item["cache_key"]}"', "passphrase": f'"{passp}"',
    })
    raw = http(f"{base}/mo/sharing/webapi/entry.cgi?{qs}")
    if raw[:3] != b"\xff\xd8\xff":
        return False
    open(dest, "wb").write(raw)
    return True


# ---------- Claude vision recognition ----------
SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "kind": {"type": "string", "enum": ["existing", "new", "skip"]},
            "name": {"type": "string"},
            "meal": {"type": "string", "enum": MEALS},
            "cat": {"type": "array", "items": {"type": "string", "enum": ["蛋白", "碳水", "纤维"]}},
            "meat": {"type": "array", "items": {"type": "string", "enum": ["猪", "牛", "羊", "鸡", "鸭", "鱼", "虾", "蟹", "蛋"]}},
            "spice": {"type": "integer", "enum": [0, 1]},
            "cuisine": {"type": "string"},
            "flags": {"type": "array", "items": {"type": "string", "enum": ["高胆固醇", "高饱和脂肪", "反式脂肪风险"]}},
            "ingredients": {"type": "array", "items": {
                "type": "object",
                "properties": {
                    "item": {"type": "string"}, "en": {"type": "string"}, "qty": {"type": "string"},
                    "category": {"type": "string", "enum": ING_CATS}, "pantry": {"type": "boolean"},
                },
                "required": ["item", "en", "qty", "category", "pantry"],
                "additionalProperties": False,
            }},
        },
        "required": ["index", "kind", "name"],
        "additionalProperties": False,
    }}},
    "required": ["results"],
    "additionalProperties": False,
}


def recognize(client, batch, known_names):
    content = []
    for i, (item, path) in enumerate(batch):
        content.append({"type": "text", "text": f"图片{i}："})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.standard_b64encode(open(path, "rb").read()).decode(),
        }})
    content.append({"type": "text", "text": (
        "逐张识别以上家常菜照片，输出 results（每张一条，index 对应图片编号）。\n"
        "- 如果照片里的菜与已知菜名列表中的某道菜是同一道菜，kind=existing，name 用列表里的原名（一字不差）。\n"
        "- 如果是一道清晰的新菜（单盘为主），kind=new，起一个简洁家常菜名，并给出 meal 分类、cat（蛋白/碳水/纤维，可多选）、"
        "meat、spice（微辣为1）、cuisine（粤/川/湘/淮扬/东北/西北/家常/西式 等）、flags（含蛋黄或虾类→高胆固醇；"
        "排骨牛腩羊肉鸡翅类→高饱和脂肪），以及 2 人份 ingredients（en 为美国超市搜索用英文词，"
        "酱油盐糖等常备调味 pantry=true）。\n"
        "- 如果不是食物、太模糊、或一张桌子多道菜难以拆分，kind=skip，name 填原因。\n"
        f"已知菜名列表：{'、'.join(known_names)}"
    )})

    # extra_body instead of the typed output_config param: works on older SDK
    # versions too (e.g. the newest anthropic that still installs on Python 3.8)
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        extra_body={"output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}},
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        print("  模型拒答了这一批（罕见），跳过", file=sys.stderr)
        return []
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)["results"]


# ---------- merge into the dish library ----------
def apply_result(res, item, wf, album_tags, ingredients, by_name):
    fname = f"{item['id']}.jpg"
    if res["kind"] == "existing" and res["name"] in by_name:
        d = by_name[res["name"]]
        d["photoCount"] = d.get("photoCount", 0) + 1
        d.setdefault("confirmed", []).append(fname)
        if not d.get("best"):
            d["best"] = fname
        return "existing"
    if res["kind"] == "new" and res["name"] not in by_name:
        entry = {"name": res["name"], "source": "album", "best": fname,
                 "confirmed": [fname], "photoCount": 1}
        wf["dishes"].append(entry)
        by_name[res["name"]] = entry
        album_tags["dishes"].append({
            "name": res["name"], "meal": res.get("meal", "蔬菜"),
            "cat": res.get("cat") or ["蛋白"], "meat": res.get("meat") or [],
            "spice": res.get("spice", 0), "cuisine": res.get("cuisine", "家常"),
            "flags": res.get("flags") or [],
        })
        if res.get("ingredients"):
            ingredients["dishes"].append({"name": res["name"], "ingredients": res["ingredients"]})
        return "new"
    return "skip"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="识别但不写入任何文件")
    ap.add_argument("--backfill", type=int, default=0, help="强制处理最新 N 张（测试用）")
    ap.add_argument("--init", action="store_true", help="把当前相册全部标记为已导入")
    ap.add_argument("--no-build", action="store_true", help="导入后不重新构建应用")
    args = ap.parse_args()

    load_env()
    os.makedirs(os.path.join(ROOT, "private"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "m_thumbs"), exist_ok=True)

    base, passp, api = syno_connect()
    manifest = fetch_manifest(api)
    print(f"相册共 {len(manifest)} 张照片")
    json.dump(manifest, open(os.path.join(ROOT, "data", "manifest.json"), "w", encoding="utf-8"))

    if os.path.exists(STATE):
        seen = set(json.load(open(STATE, encoding="utf-8")))
    else:
        seen = {it["id"] for it in manifest}
        json.dump(sorted(seen), open(STATE, "w", encoding="utf-8"))
        print("首次运行：已把当前相册设为基线（此后新增的照片才会被识别导入）")
        if not args.backfill:
            return

    if args.init:
        json.dump(sorted({it["id"] for it in manifest}), open(STATE, "w", encoding="utf-8"))
        print("已把当前相册全部标记为已导入")
        return

    todo = [it for it in manifest if it["id"] not in seen]
    if args.backfill:
        todo = sorted(manifest, key=lambda x: -x["time"])[: args.backfill]
    if not todo:
        print("没有新照片，无需导入")
        return
    print(f"待识别 {len(todo)} 张新照片")

    fetched = []
    for it in todo:
        dest = os.path.join(ROOT, "m_thumbs", f"{it['id']}.jpg")
        if os.path.exists(dest) or fetch_thumb(base, passp, it, "m", dest):
            fetched.append((it, dest))
        else:
            print(f"  {it['filename']}: 缩略图下载失败，跳过")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("识图需要 ANTHROPIC_API_KEY：请在 .env 里配置（参考 .env.example / README 第②节）")
    import anthropic
    client = anthropic.Anthropic()

    wf = json.load(open(os.path.join(ROOT, "data", "workflow_result.json"), encoding="utf-8"))
    album_tags = json.load(open(os.path.join(ROOT, "data", "album_tags.json"), encoding="utf-8"))
    ing_path = os.path.join(ROOT, "data", "ingredients.json")
    ingredients = json.load(open(ing_path, encoding="utf-8")) if os.path.exists(ing_path) else {"dishes": []}
    by_name = {d["name"]: d for d in wf["dishes"]}

    counts = {"existing": 0, "new": 0, "skip": 0}
    new_names = []
    for i in range(0, len(fetched), BATCH):
        batch = fetched[i:i + BATCH]
        print(f"识别第 {i + 1}-{i + len(batch)} 张 ...")
        for res in recognize(client, batch, sorted(by_name)):
            idx = res.get("index", 0)
            if not 0 <= idx < len(batch):
                continue
            item = batch[idx][0]
            outcome = apply_result(res, item, wf, album_tags, ingredients, by_name)
            counts[outcome] += 1
            tag = {"existing": "已有菜", "new": "新菜", "skip": "跳过"}[outcome]
            print(f"  {item['filename']} → {tag}：{res['name']}")
            if outcome == "new":
                new_names.append(res["name"])

    if args.dry_run:
        print(f"\n[dry-run] 不写入。识别结果：已有菜 +{counts['existing']} 张照片，"
              f"新菜 {counts['new']} 道，跳过 {counts['skip']}")
        return

    json.dump(wf, open(os.path.join(ROOT, "data", "workflow_result.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(album_tags, open(os.path.join(ROOT, "data", "album_tags.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(ingredients, open(ing_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    seen |= {it["id"] for it, _ in fetched}
    json.dump(sorted(seen), open(STATE, "w", encoding="utf-8"))

    print(f"\n导入完成：已有菜 +{counts['existing']} 张照片，新菜 {counts['new']} 道"
          f"（{'、'.join(new_names) if new_names else '无'}），跳过 {counts['skip']}")

    if not args.no_build:
        subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_app.py")], check=True)
        if os.path.isdir(os.path.join(ROOT, "miniprogram")):
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_miniprogram.py")], check=True)
        print("应用已重新构建：dist/jiali-de-cai.html（部署到任意静态服务器 / NAS Web Station 即可）")


if __name__ == "__main__":
    main()
