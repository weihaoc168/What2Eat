"""Discover similar restaurants near home (requires ANTHROPIC_API_KEY).

Reads the family's cuisine preferences from data/restaurants.json, web-searches
for highly-rated places of the same cuisines around the home area, and writes
data/rest_discover.json (gitignored) with name / cuisine / Google rating /
health tags / a maps search link. Both builds merge them into the 下馆子 tab
as a 猜你喜欢 section, excluded names already saved.

Usage: python scripts/discover_restaurants.py [--area "Pearland / Houston TX"]
"""
import json
import os
import re
import sys
import urllib.parse

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "rest_discover.json")
HEALTH = ["高蛋白", "高碳水", "高胆固醇", "高饱和脂肪", "反式脂肪风险", "蔬菜丰富", "清淡"]


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    area = "Pearland / Houston TX"
    if "--area" in sys.argv:
        area = sys.argv[sys.argv.index("--area") + 1]

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("此功能需要绑定 API Key：在 .env 里配置 ANTHROPIC_API_KEY")
    import anthropic
    client = anthropic.Anthropic()

    rest = json.load(open(os.path.join(ROOT, "data", "restaurants.json"), encoding="utf-8"))
    existing = [r["name"] for r in rest.get("visited", []) + rest.get("wishlist", [])]
    pref = sorted(rest.get("pref", {}).items(), key=lambda x: -x[1])
    top_cuisines = [c for c, w in pref[:8] if c not in ("咖啡", "奶茶", "果汁")][:6]
    print(f"按口味搜索 {area} 的同类高分餐厅：{'、'.join(top_cuisines)}")

    response = client.messages.create(
        model="claude-opus-5",
        max_tokens=16000,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 10}],
        messages=[{"role": "user", "content": (
            f"帮一个住在 {area} 的家庭发现新餐厅。他们喜欢的菜系（按偏好排序）：{'、'.join(top_cuisines)}。\n"
            f"对每个菜系分别执行一次网络搜索（共约 6 次），找出当地评分最高的餐厅（Google 评分 4.2 以上即可收录），每个菜系尽量给足 3 家，目标总数 12-18 家，"
            f"排除他们已收藏的：{'、'.join(existing)}。\n\n"
            "最后只输出一个 ```json 代码块，格式：\n"
            '{"restaurants": [{"name": "英文原名", "cuisine": "菜系(中文,用他们的分类词)", '
            '"rating": 4.5, "area": "城市/区域", '
            f'"health": [从 {HEALTH} 里选1-3个], "note": "一句话推荐理由(中文)"}}]}}\n'
            "rating 必须来自搜索到的真实 Google 评分；找不到确切评分的餐厅不要收录。"
        )}],
    )
    if response.stop_reason == "refusal":
        sys.exit("模型拒答")
    text = "".join(b.text for b in response.content if b.type == "text")
    m = re.search(r"```json\s*([\s\S]*?)```", text) or re.search(r"(\{[\s\S]*\})", text)
    if not m:
        sys.exit("未找到 JSON 输出")
    items = json.loads(m.group(1))["restaurants"]

    out = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else []
    seen = set(n.lower() for n in existing) | set(r["name"].lower() for r in out)
    for r in items:
        if r["name"].lower() in seen:
            continue
        seen.add(r["name"].lower())
        q = urllib.parse.quote(f"{r['name']} {r.get('area', area)}")
        out.append({
            "name": r["name"], "cuisine": r.get("cuisine", "餐厅"),
            "rating": r.get("rating"), "km": None, "fast": False,
            "url": f"https://www.google.com/maps/search/?api=1&query={q}",
            "health": [h for h in r.get("health", []) if h in HEALTH],
            "note": r.get("note", ""), "disc": True,
        })
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"发现 {len(out)} 家：")
    for r in out:
        print(f"  {r['name']}（{r['cuisine']}·{r['rating']}分）{r['note']}")


if __name__ == "__main__":
    main()
