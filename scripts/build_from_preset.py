"""Build the app from a bundled preset menu instead of a photo album.

For self-hosters without a photo album (or before the recognition pipeline is
set up): pick a preset under data/presets/, and this generates the same
data/workflow_result.json + data/album_tags.json + data/ingredients.json the
photo pipeline would produce (photo-less), then runs build_app.py. Photos can
be layered on later — in-app 手机照片补图, or the full import_album.py pipeline.

Usage:
  python scripts/build_from_preset.py --list
  python scripts/build_from_preset.py 经典家常
  python scripts/build_from_preset.py 经典家常 川湘风味   # merge several presets
"""
import argparse
import json
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESETS = os.path.join(ROOT, "data", "presets")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="preset 名称（data/presets/ 下的文件名，不含 .json）")
    ap.add_argument("--list", action="store_true", help="列出可用的预设")
    args = ap.parse_args()

    available = sorted(f[:-5] for f in os.listdir(PRESETS) if f.endswith(".json"))
    if args.list or not args.names:
        for n in available:
            p = json.load(open(os.path.join(PRESETS, n + ".json"), encoding="utf-8"))
            print(f"  {n} — {len(p['dishes'])} 道 — {p.get('note', '')}")
        if not args.names:
            print("\n用法: python scripts/build_from_preset.py <预设名>")
        return

    dishes, ing, seen = [], [], set()
    for n in args.names:
        path = os.path.join(PRESETS, n + ".json")
        if not os.path.exists(path):
            sys.exit(f"没有预设 {n}，可用: {', '.join(available)}")
        for d in json.load(open(path, encoding="utf-8"))["dishes"]:
            if d["name"] in seen:
                continue
            seen.add(d["name"])
            dishes.append(d)
            if d.get("ingredients"):
                ing.append({"name": d["name"], "ingredients": d["ingredients"]})

    for existing in ("workflow_result.json", "album_tags.json", "ingredients.json"):
        p = os.path.join(ROOT, "data", existing)
        if os.path.exists(p):
            os.replace(p, p + ".bak")
            print(f"已有 data/{existing} 备份为 .bak")

    json.dump({"stats": {"preset": args.names}, "dishes": [
        {"name": d["name"], "source": "list", "best": None, "confirmed": [], "photoCount": 0}
        for d in dishes
    ], "albumClusters": [], "photoMap": {}},
        open(os.path.join(ROOT, "data", "workflow_result.json"), "w", encoding="utf-8"),
        ensure_ascii=False, indent=1)
    json.dump({"dishes": [{k: d[k] for k in ("name", "meal", "cat", "meat", "spice", "cuisine", "flags")}
                          for d in dishes]},
              open(os.path.join(ROOT, "data", "album_tags.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"dishes": ing}, open(os.path.join(ROOT, "data", "ingredients.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    # dish_tags.json holds the photo pipeline's menu-list tags; presets carry
    # their own tags in album_tags, so an empty list file keeps build_app happy
    dt = os.path.join(ROOT, "data", "dish_tags.json")
    if not os.path.exists(dt):
        json.dump({"dishes": []}, open(dt, "w", encoding="utf-8"))

    print(f"预设菜单就绪：{len(dishes)} 道（{'、'.join(args.names)}），开始构建应用 ...")
    subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "build_app.py")], check=True)


if __name__ == "__main__":
    main()
