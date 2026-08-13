# What2Eat 家里的菜

一个家庭选菜小应用。它把 Synology Photos 相册「家里的菜」十一年的 516 张照片变成一份带图菜单，一键生成早饭、午饭、晚饭的全日搭配。界面全中文，交互只有点按。

A family meal picker. It turns 516 photos from a Synology Photos shared album into an illustrated menu of 70 dishes, then draws a random daily plan that respects your filters. UI is Chinese only.

## 功能

- **今天吃什么**：一键生成早饭和晚饭（主菜加副菜）。午饭不生成，默认带前一晚的菜（带饭），来自本机记录的昨晚晚饭。早饭和晚饭可单独「换一换」。
- **这周吃什么**：一键生成周一到周日的整周计划，每天早饭一道，晚饭主菜加副菜，一周内主菜尽量不重复。每天的午饭自动等于前一天的晚饭，周一午饭暂留空。任意一天可单独「换一换」，第二天的带饭会跟着变。
- **筛选**：营养类别（蛋白、碳水、纤维）、食材（鸡、猪、牛、羊、鸭、鱼虾、蛋、豆制品）、辣度、菜系（粤、川、淮扬、北方西北、家常、西式、日韩、其他）、忌口（忌高胆固醇、忌高饱和脂肪、忌反式脂肪）。
- **菜单总览**：70 道菜按早饭、主菜、副菜分组，59 道配有从相册挑出的代表照。点卡片看大图和标签。
- **健康提示**：含蛋黄或虾类的菜标高胆固醇，排骨、牛腩、羊肉、鸡翅类标高饱和脂肪，起酥类烘焙标反式脂肪风险。只是常规食材提示，不是医学建议。
- 筛选条件、当天菜单、整周计划和最近 14 天的晚饭记录都存在浏览器 localStorage，刷新不丢。带饭逻辑按日期取昨晚的记录，换了设备或清了浏览器数据会从空开始。

## 数据从哪来

菜单分两部分。41 道来自家里手写的菜单清单。29 道是 AI 看相册照片时发现的常出现的菜（照片出现 3 次以上），在应用里标「相册」，可以在筛选里排除。

照片匹配由一次多代理流水线完成：13 个视觉代理逐张看完 516 张缩略图，把每张照片对到菜名；1 个代理归并清单之外的菜名；9 个代理复核每道菜的候选照片并挑出最好的一张代表照。

## 仓库结构

```
app_template.html        界面模板（含全部样式和交互逻辑）
scripts/fetch_gallery.py 从 Synology 分享链接抓取相册清单和缩略图
scripts/build_app.py     把匹配结果、标签、照片合成 dist/jiali-de-cai.html
data/dish_tags.json      菜单清单 41 道菜的标签
data/album_tags.json     相册发现 29 道菜的标签
data/workflow_result.json AI 识图匹配结果（照片与菜的对应关系）
```

`thumbs/`、`m_thumbs/`、`dist/` 与 `.env` 不入库。前三者含家庭照片，最后一个含相册分享口令。

## 本地构建

1. 复制 `.env.example` 为 `.env`，填入 NAS 地址和相册分享口令。
2. 抓取照片：`python scripts/fetch_gallery.py --m-size`
3. 构建：`python scripts/build_app.py`
4. 产物是单文件 `dist/jiali-de-cai.html`，浏览器直接打开即可，也可发布为 Claude Artifact 或放到任何静态服务器。

依赖：Python 3，Pillow 可选（装了会把内嵌照片压到约 1.7 MB，不装约 4 MB）。

## 更新菜品

见 [docs/UPDATING.md](docs/UPDATING.md)。

## Phase III 采购与消费（搭建中）

方向：按周计划聚合食材生成采购清单，构建时从 Costco、HEB、H Mart 抓取当期价格烤进页面，给出成本估算；消费追踪走零售账号的订单历史抓取。周末外食推荐来自 Google Timeline 的到访历史。

已就绪的部分：

- `data/ingredients.json`：全部 70 道菜的两人份食材清单（中文名、英文搜索词、用量、分类、是否常备）。
- `scripts/fetch_prices.py`：按食材搜索词抓零售商报价并写入 `data/prices.json`。H Mart 可直接无头抓取；HEB 和 Costco 有反爬，需要先用登录过的浏览器档案。
- `scripts/retail_login.py`：给每家零售商开一个可见浏览器窗口做一次性登录，会话存在 `private/profiles/`，之后抓价和抓小票复用。
- `scripts/parse_timeline.py`：解析 Google Timeline 导出（手机导出与旧版 Takeout 两种格式都认），产出就餐地点的到访统计。

`private/` 整个目录不入库：里面是 Timeline 导出、登录态浏览器档案等个人数据。价格与餐厅数据文件同样不入库。

## 已知限制

- 11 道菜暂无照片，多为早饭组合（如牛角包加炒蛋、蒸蛋）。相册里拍了新照片后重跑管线即可补上。
- 菜系和辣度按常识标注，家常菜口径本就模糊，发现不对改 `data/*.json` 再重新构建即可。
- 牛肉和羊肉在照片里不易区分，个别匹配可能有误。
