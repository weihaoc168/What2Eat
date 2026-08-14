# What2Eat 家里的菜

一个家庭选菜应用：把家庭相册里的做菜照片变成带图菜单，一键生成早饭、午饭（自动带前一晚的菜）、晚饭的全日搭配，并从菜单聚合出带双店报价的采购清单。界面全中文，交互只有点按，产出是**一个单文件 HTML**，部署到任何静态服务器（或 NAS）都能用。

A family meal picker: turns a photo album of home cooking into an illustrated menu with daily meal plans and a priced grocery list. Ships as a single self-contained HTML file.

## 功能

- **今天吃什么 / 这周吃什么**：一键生成菜单；肉菜蔬菜数量可调（默认 1+1），加汤/加点心可选；午饭默认带前一晚的菜（带饭）；列表 / 网格 / 详细三种排列。
- **筛选**：营养类别、食材、辣度、菜系、忌口（高胆固醇 / 高饱和脂肪 / 反式脂肪）。
- **采购**：按整周计划聚合食材清单，双店实时报价成本估算，勾选划掉，一键复制；常买水果可选加入（来自小票历史均价）。
- **开销分析**（可选）：接入 Costco 账户小票后展示月度支出、类别占比、高频回购周期。
- **导入相册**：应用内保存云端相册地址；手机照片可直接给单道菜换图/补图（存本机，立即生效）。
- **微信小程序**：`miniprogram/` 下有同功能的原生小程序版。

## 三种使用方式

| 方式 | 适合谁 | 需要什么 |
|---|---|---|
| ① 内置预设菜单 | 想直接用、没有照片相册 | 只要 Python，5 分钟 |
| ② 自建识图管线 | 有自己的家庭菜品相册 | Synology 相册分享链接 + Anthropic API Key |
| ③ 现成托管版本 | 本仓库作者的家庭成员 | 什么都不用装，直接开分享链接 |

---

## ① 快速开始：用内置预设菜单（无需相册）

仓库自带三份整理好的家常菜单（`data/presets/`），选一份直接生成应用：

```bash
git clone https://github.com/weihaoc168/What2Eat && cd What2Eat
pip install pillow

python scripts/build_from_preset.py --list      # 看有哪些预设
python scripts/build_from_preset.py 经典家常     # 或 川湘风味 / 粤式清淡，可同时选多份合并
```

生成的 `dist/jiali-de-cai.html` 双击即可用；放到 NAS Web Station、Nginx、GitHub Pages（私有）等任何静态托管上，全家手机都能访问。预设菜单没有照片，可以随时用应用里「导入相册 → 手机照片」逐道补图，或按 ② 接入自己的相册。

内置预设：**经典家常**（30 道，通用）· **川湘风味**（18 道，偏辣）· **粤式清淡**（18 道，蒸煮为主）。

---

## ② 在自己主机上搭建识图管线（具体步骤）

目标：你的家庭相册新增做菜照片后，跑一条命令（或定时任务）自动认菜、入库、重建应用 —— 全程在你自己的机器上完成，不依赖任何人。

### 前置条件

- 一台能跑 Python 3.9+ 的主机（Windows / macOS / Linux / NAS 皆可），能访问你的 Synology NAS
- Synology Photos 里建一个**共享相册**存做菜照片（家庭成员手机开启 Synology Photos 自动备份后，拍照→选进相册即可，天然完成"手机→管线"这一步）
- 一个 Anthropic API Key（识图用，按量付费）

### 第 1 步：拿到相册分享链接

Synology Photos → 打开相册 → 共享 → 启用共享链接（**公开、无密码**）。
链接形如 `https://10.0.0.216:5001/mo/sharing/AbCdEfGh` —— 主机是 `10.0.0.216`，passphrase 是 `AbCdEfGh`。

### 第 2 步：拿到 Anthropic API Key

1. 注册 [platform.claude.com](https://platform.claude.com)，充值少量额度（$5 起）。
2. Settings → API Keys → Create Key，复制 `sk-ant-api03-...`。

费用参考：识图用 `claude-opus-5`，每张照片约 $0.01–0.03；一个每周新增十几张照片的家庭相册，每月不到 $2。

### 第 3 步：安装与配置

```bash
git clone https://github.com/weihaoc168/What2Eat && cd What2Eat
pip install anthropic pillow

cp .env.example .env
# 编辑 .env，填三个值：
#   SYNO_HOST=10.0.0.216
#   SHARE_PASSPHRASE=AbCdEfGh
#   ANTHROPIC_API_KEY=sk-ant-api03-...
```

### 第 4 步：建立基线并首次构建

```bash
python scripts/import_album.py
```

首次运行会把当前相册全部照片标记为基线（**不识图、不花钱**），此后新增的照片才会被识别。基线之前的存量菜单二选一：

- 相册照片不多（几十张）：`python scripts/import_album.py --backfill 50` 强制识别最近 50 张建库（一次性花约 $1）；
- 或先用预设起步：`python scripts/build_from_preset.py 经典家常`，以后新照片自动叠加进来。

### 第 5 步：日常运行

家人往相册加了新照片后：

```bash
python scripts/import_album.py
```

它会：拉取新照片 → Claude 逐张识别（匹配已有菜 / 创建新菜并自动打标签+生成食材清单 / 跳过非菜照片）→ 合并入库 → 自动重建 `dist/jiali-de-cai.html`。想先看识别结果不入库，加 `--dry-run`。

### 第 6 步：设为定时任务（可选，全自动）

- **Windows**：任务计划程序 → 新建任务 → 每周日 20:00 运行 `python C:\path\What2Eat\scripts\import_album.py`
- **Linux / NAS**：`crontab -e` 加一行 `0 20 * * 0 cd /path/What2Eat && python3 scripts/import_album.py`
- Synology DSM：控制面板 → 任务计划 → 新增用户定义脚本

### 第 7 步：部署给家人用

`dist/jiali-de-cai.html` 是单文件，怎么方便怎么来：

- **NAS Web Station**：把文件放进 web 目录，家人访问 `http://NAS地址/jiali-de-cai.html`（定时任务里加一行 `cp dist/jiali-de-cai.html /volume1/web/` 即可自动更新）；
- 任何 Nginx / Caddy / 静态托管；
- 注意文件内嵌全家照片，**不要放公网公开地址**，放内网或加认证。

### 常见问题

- **识别错了怎么办**：直接改 `data/album_tags.json` / `data/workflow_result.json` 里对应条目，重跑 `python scripts/build_app.py`。
- **换相册**：改 `.env` 里的 `SHARE_PASSPHRASE`，删掉 `private/imported_ids.json` 重新建基线。
- **照片是竖的/歪的**：构建时自动按 EXIF 转正，无需处理。
- **小程序**：`python scripts/build_miniprogram.py` 生成 `miniprogram/`，用微信开发者工具导入即可预览（正式发布需要自己的 AppID）。

---

## ③ 现成托管版本

本仓库作者家庭的实例托管在 Claude Artifact 上（含全部照片、价格、小票分析），仅通过私密分享链接提供给家庭成员，不公开。家庭成员无需安装任何东西；照片补图用应用内「导入相册 → 手机照片」。

---

## 仓库结构

```
app_template.html            界面模板（全部样式与交互逻辑，数据用占位符注入）
scripts/import_album.py      ★ 独立识图导入器：拉新照片 → Claude 认菜 → 入库 → 重建
scripts/build_from_preset.py ★ 无相册时用内置预设菜单直接生成应用
scripts/fetch_gallery.py     抓取 Synology 分享相册的清单与缩略图
scripts/build_app.py         合成单文件应用 dist/jiali-de-cai.html
scripts/build_miniprogram.py 生成微信小程序版
scripts/fetch_prices.py      （可选）H Mart / Costco 实时价格
scripts/fetch_receipts.py    （可选）Costco 账户小票抓取 → 开销分析
data/presets/                内置预设菜单（经典家常 / 川湘风味 / 粤式清淡）
data/*.json                  菜品库、标签、食材、价格（个人数据均已 gitignore）
miniprogram/                 微信小程序源码
docs/UPDATING.md             完整刷新流程（照片匹配多代理管线等）
```

隐私约定：`.env`、缩略图目录、`dist/`、小票与消费数据全部 gitignore —— 仓库只含代码与预设，不含任何家庭照片和个人数据。

## License

MIT（预设菜单数据整理自常见中餐家常菜谱，仅含菜名与常规食材信息）。
