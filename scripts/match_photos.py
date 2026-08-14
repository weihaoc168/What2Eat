"""AI photo matching for photo-less dishes (requires ANTHROPIC_API_KEY).

Two sources, tried in order:
  1. Prior crop-pipeline detections (private/detections.json): dishes that were
     spotted in multi-dish table shots but never got a usable crop — re-crop the
     detected region from the xl image and let Claude verify / pick the best.
  2. --sweep: no detection data — scan every album thumbnail in batches asking
     Claude which (if any) of the photo-less dishes each photo shows.

Verified winners land in crops/ and data/workflow_result.json, so build_app.py
uses the real photo; illustrations (generate_images.py) stay as the fallback
for dishes the album truly never captured.

Usage:
  python scripts/match_photos.py                 # detection-based recovery
  python scripts/match_photos.py --names 酸辣汤   # limit to specific dishes
  python scripts/match_photos.py --sweep         # full-album vision sweep
"""
import argparse
import base64
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = "claude-opus-5"
PAD = 0.08

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from import_album import load_env, syno_connect, fetch_thumb  # noqa: E402


def photoless():
    wf = json.load(open(os.path.join(ROOT, "data", "workflow_result.json"), encoding="utf-8"))
    out = []
    for d in wf["dishes"]:
        pid = (d.get("best") or "").split(".")[0]
        if not (pid and any(os.path.exists(os.path.join(ROOT, s, pid + ".jpg"))
                            for s in ("crops", "xl_thumbs", "m_thumbs", "thumbs"))):
            out.append(d["name"])
    return wf, out


def crop_bbox(img_path, bbox, dest):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(img_path)).convert("RGB")
    W, H = im.size
    x, y, w, h = bbox
    x0 = max(0, (x - PAD * w) * W); y0 = max(0, (y - PAD * h) * H)
    x1 = min(W, (x + w * (1 + PAD)) * W); y1 = min(H, (y + h * (1 + PAD)) * H)
    if x1 - x0 < 60 or y1 - y0 < 60:
        return False
    im.crop((int(x0), int(y0), int(x1), int(y1))).save(dest, "JPEG", quality=88)
    return True


def img_block(path, max_edge=560):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((max_edge, max_edge))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                       "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def pick_best(client, name, cand_paths):
    content = []
    for i, p in enumerate(cand_paths):
        content.append({"type": "text", "text": f"候选{i}："})
        content.append(img_block(p))
    content.append({"type": "text", "text": (
        f"以上是从家庭餐桌合照裁出的候选图，目标菜是「{name}」。"
        "选出真的是这道菜、且画质构图可以当菜单封面的最好一张。"
        '只输出 JSON：{"best": 候选编号} 或都不合格时 {"best": -1}'
    )})
    r = client.messages.create(model=MODEL, max_tokens=2000,
                               messages=[{"role": "user", "content": content}])
    if r.stop_reason == "refusal":
        return -1
    text = "".join(b.text for b in r.content if b.type == "text")
    try:
        return int(json.loads(text[text.index("{"):text.rindex("}") + 1])["best"])
    except (ValueError, KeyError):
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", nargs="*", default=None)
    ap.add_argument("--sweep", action="store_true", help="全相册扫描（无检测数据时）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("此功能需要绑定 API Key：在 .env 里配置 ANTHROPIC_API_KEY")
    import anthropic
    client = anthropic.Anthropic()

    wf, missing = photoless()
    targets = [n for n in missing if not args.names or n in args.names]
    if not targets:
        print("没有需要匹配的无图菜")
        return
    print(f"目标 {len(targets)} 道：{'、'.join(targets)}")

    det_path = os.path.join(ROOT, "private", "detections.json")
    cand = {n: [] for n in targets}
    if os.path.exists(det_path) and not args.sweep:
        for r in json.load(open(det_path, encoding="utf-8"))["results"]:
            for d in r.get("dishes", []):
                if d["name"] in cand:
                    cand[d["name"]].append((r["file"], d["bbox"], d.get("conf", "low")))
    elif args.sweep:
        sys.exit("--sweep 模式：先运行 import_album.py 保证 thumbs/ 齐全后，"
                 "此模式逐批扫描全相册（约 $5/500张），本版本请先用检测数据模式")

    base, passp, api = syno_connect()
    manifest = {str(it["id"]): it for it in json.load(open(os.path.join(ROOT, "data", "manifest.json"), encoding="utf-8"))}
    os.makedirs(os.path.join(ROOT, "crops"), exist_ok=True)
    tmpdir = os.path.join(ROOT, "private", "match_tmp")
    os.makedirs(tmpdir, exist_ok=True)

    by_name = {d["name"]: d for d in wf["dishes"]}
    recovered = []
    for name in targets:
        cands = sorted(cand[name], key=lambda c: {"high": 0, "med": 1}.get(c[2], 2))[:4]
        if not cands:
            print(f"  {name}: 检测数据里没有候选，留给插画兜底")
            continue
        paths, metas = [], []
        for file, bbox, conf in cands:
            pid = file.split(".")[0]
            src = None
            for sub in ("xl_thumbs", "m_thumbs", "thumbs"):
                p = os.path.join(ROOT, sub, pid + ".jpg")
                if os.path.exists(p):
                    src = p
                    if sub == "xl_thumbs":
                        break
            if src is None or "xl" not in src:
                item = manifest.get(pid)
                if item:
                    dest = os.path.join(ROOT, "xl_thumbs", pid + ".jpg")
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    if fetch_thumb(base, passp, item, "xl", dest):
                        src = dest
            if not src:
                continue
            out = os.path.join(tmpdir, f"{pid}_{len(paths)}_{abs(hash(name)) % 9999}.jpg")
            if crop_bbox(src, bbox, out):
                paths.append(out)
                metas.append((pid, bbox))
        if not paths:
            print(f"  {name}: 候选裁切全部失败")
            continue
        best = pick_best(client, name, paths)
        if best < 0 or best >= len(paths):
            print(f"  {name}: AI 认为候选质量都不够，留给插画兜底")
            continue
        pid, bbox = metas[best]
        crop_name = f"{pid}m{abs(hash(name)) % 9999}"
        final = os.path.join(ROOT, "crops", crop_name + ".jpg")
        os.replace(paths[best], final)
        d = by_name[name]
        d["best"] = crop_name + ".jpg"
        d.setdefault("confirmed", []).append(crop_name + ".jpg")
        d["photoCount"] = max(d.get("photoCount", 0), 1)
        recovered.append(name)
        print(f"  {name}: ✓ 从 {pid}.jpg 裁得真实照片")

    if recovered and not args.dry_run:
        json.dump(wf, open(os.path.join(ROOT, "data", "workflow_result.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"\n已恢复 {len(recovered)} 道菜的真实照片，运行 python scripts/build_app.py 生效")
    elif not recovered:
        print("\n没有可恢复的真实照片")


if __name__ == "__main__":
    main()
