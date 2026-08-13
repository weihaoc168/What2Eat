# 更新菜品与照片

## 相册加了新照片，想让某道菜换图或补图

1. 重新抓取：`python scripts/fetch_gallery.py`，新照片会进入 `thumbs/`。
2. 打开 `data/workflow_result.json`，找到那道菜，把 `best` 改成新照片的文件名（形如 `123456.jpg`，即 `thumbs/` 里的文件名）。`photoCount` 可顺手加一，不改也不影响功能。
3. 抓高清版：`python scripts/fetch_gallery.py --m-size`
4. 重新构建：`python scripts/build_app.py`
5. 把 `dist/jiali-de-cai.html` 重新发布（让 Claude 用同一 artifact URL 重发，或替换静态服务器上的文件）。

不确定新照片对应哪张缩略图时，可以让 Claude 重跑识图流水线，它会自动匹配并挑代表照。

## 新增一道菜

1. 在 `data/dish_tags.json`（清单菜）或 `data/album_tags.json`（相册菜）加一条标签，字段含义见文件头 `_comment`。
2. 在 `data/workflow_result.json` 的 `dishes` 数组加一条：

```json
{"name": "新菜名", "source": "list", "best": "照片文件名.jpg 或 null", "confirmed": [], "photoCount": 0}
```

3. 重新构建并发布。

## 改标签（辣度、菜系、忌口等）

直接改 `data/dish_tags.json` 或 `data/album_tags.json` 里对应的字段，重新构建即可。字段取值：

- `meal`：早饭、主菜、副菜
- `cat`：蛋白、碳水、纤维（数组，可多选）
- `meat`：鸡、猪、牛、羊、鸭、鱼虾、蛋、豆制品（数组）
- `spice`：0 不辣，1 微辣，2 辣
- `cuisine`：粤、川、湘、淮扬、北方西北、家常、西式、日韩、其他（早饭菜写 早餐）
- `flags`：高胆固醇、高饱和脂肪、反式脂肪风险（数组，可为空）

筛选界面的菜系选项按数据自动生成，用了新菜系名会自动出现对应筛选项。

## 全量重跑识图（相册大量更新后）

把仓库交给 Claude，说明要刷新「家里的菜」匹配。流水线是：抓缩略图，13 个视觉代理逐张匹配菜名，归并相册新菜（出现 3 次以上才收），复核并挑代表照，结果写回 `data/workflow_result.json`。之后正常构建发布。
