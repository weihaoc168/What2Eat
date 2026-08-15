"""Classify each saved restaurant's typical food into health categories
(requires ANTHROPIC_API_KEY). One batch call; output data/rest_health.json
({name: [tags]}) — gitignored, derived from the family's saved places.
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAGS = ["高蛋白", "高碳水", "高胆固醇", "高饱和脂肪", "反式脂肪风险", "蔬菜丰富", "清淡"]

SCHEMA = {
    "type": "object",
    "properties": {"restaurants": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string", "enum": TAGS}},
        },
        "required": ["name", "tags"],
        "additionalProperties": False,
    }}},
    "required": ["restaurants"],
    "additionalProperties": False,
}


def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("此功能需要绑定 API Key：在 .env 里配置 ANTHROPIC_API_KEY")
    import anthropic
    client = anthropic.Anthropic()

    rest = json.load(open(os.path.join(ROOT, "data", "restaurants.json"), encoding="utf-8"))
    entries = [(r["name"], r.get("cuisine", "")) for r in rest.get("visited", []) + rest.get("wishlist", [])]
    listing = "\n".join(f"- {n}（{c}）" for n, c in entries)

    response = client.messages.create(
        model="claude-opus-5", max_tokens=8000,
        extra_body={"output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}},
        messages=[{"role": "user", "content": (
            "以下是美国休斯顿地区的餐厅（附菜系）。根据每家餐厅典型菜品的营养特征，"
            f"从这些标签里选 1-3 个：{'、'.join(TAGS)}。\n"
            "判断依据：烧烤/牛排→高蛋白+高饱和脂肪；甜品/烘焙→高碳水+反式脂肪风险；"
            "海鲜/寿司→高蛋白(+虾蟹贝类为主时高胆固醇)；早午餐→高碳水+高胆固醇(蛋)；"
            "粤式蒸煮/越南粉→清淡；沙拉轻食→蔬菜丰富。name 一字不差返回。\n\n" + listing
        )}],
    )
    if response.stop_reason == "refusal":
        sys.exit("模型拒答")
    text = next(b.text for b in response.content if b.type == "text")
    out = {r["name"]: r["tags"] for r in json.loads(text)["restaurants"]}
    json.dump(out, open(os.path.join(ROOT, "data", "rest_health.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"已分类 {len(out)} 家：")
    for n, t in list(out.items())[:6]:
        print(f"  {n}: {'、'.join(t)}")


if __name__ == "__main__":
    main()
