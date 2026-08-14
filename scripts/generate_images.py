"""One-click AI illustrations for every dish that has no photo.

Requires ANTHROPIC_API_KEY in .env — without a key the script refuses to run.
Claude draws a flat-style SVG for each photo-less dish (consistent palette
matching the app), saved to data/gen_images.json; build_app.py embeds them as
the dish image wherever no real photo exists. A later real photo (album import
or in-app 手机照片) always wins over the illustration.

Usage:
  python scripts/generate_images.py            # all photo-less dishes
  python scripts/generate_images.py --limit 2  # first N only (testing)
  python scripts/generate_images.py --force 菜名 # regenerate one dish
"""
import argparse
import base64
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "gen_images.json")
MODEL = "claude-opus-5"

STYLE = (
    "画一张扁平风格的中式家常菜插画 SVG。要求：\n"
    "- viewBox='0 0 480 360'，背景整块 #F3EDE1，无边框\n"
    "- 俯视 45 度角的一盘/一碗菜居中，占画面 60% 左右\n"
    "- 配色温暖克制：餐具用白色/米色描边 #C9BFAE，食物用低饱和的自然色，"
    "点缀色可用 #B0382E（红）与 #4F7F6B（青绿）\n"
    "- 简洁几何形状，细节适度（葱花、蒸汽两三缕这类小元素可加），不要文字、不要渐变滤镜\n"
    "- 只输出一个完整的 <svg>...</svg>，不要任何解释"
)


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def photoless_dishes():
    wf = json.load(open(os.path.join(ROOT, "data", "workflow_result.json"), encoding="utf-8"))
    ing_p = os.path.join(ROOT, "data", "ingredients.json")
    ing = {d["name"]: d["ingredients"] for d in json.load(open(ing_p, encoding="utf-8"))["dishes"]} \
        if os.path.exists(ing_p) else {}
    out = []
    for d in wf["dishes"]:
        pid = (d.get("best") or "").split(".")[0]
        has_photo = pid and any(
            os.path.exists(os.path.join(ROOT, sub, pid + ".jpg"))
            for sub in ("crops", "xl_thumbs", "m_thumbs", "thumbs"))
        if not has_photo:
            items = "、".join(i["item"] for i in ing.get(d["name"], [])[:5])
            out.append((d["name"], items))
    return out


def gen_svg(client, name, items):
    hint = f"，主要食材：{items}" if items else ""
    response = client.messages.create(
        model=MODEL, max_tokens=8000,
        messages=[{"role": "user", "content": f"菜名：{name}{hint}\n\n{STYLE}"}],
    )
    if response.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in response.content if b.type == "text")
    m = re.search(r"<svg[\s\S]*?</svg>", text)
    if not m:
        return None
    svg = re.sub(r"<script[\s\S]*?</script>", "", m.group(0))
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--force", default=None, help="重新生成指定菜名")
    args = ap.parse_args()

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("此功能需要绑定 API Key：在 .env 里配置 ANTHROPIC_API_KEY（参考 .env.example）")
    import anthropic
    client = anthropic.Anthropic()

    done = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    todo = photoless_dishes()
    if args.force:
        todo = [t for t in todo if t[0] == args.force] or [(args.force, "")]
        done.pop(args.force, None)
    else:
        todo = [t for t in todo if t[0] not in done]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("所有无图菜都已有生成插画")
        return
    print(f"为 {len(todo)} 道无图菜生成插画 ...")

    for i, (name, items) in enumerate(todo, 1):
        uri = gen_svg(client, name, items)
        if uri:
            done[name] = uri
            json.dump(done, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  [{i}/{len(todo)}] {name} ✓ ({len(uri) // 1024}KB)")
        else:
            print(f"  [{i}/{len(todo)}] {name} ✗ 生成失败，跳过")

    print("完成。运行 python scripts/build_app.py 生效")


if __name__ == "__main__":
    main()
