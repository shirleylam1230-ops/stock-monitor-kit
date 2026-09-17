# 股票投资监控套件（Stock Monitor Kit）

一个面向个人投资者的**自动化监控与日报系统**：持仓/观察池 MACD 技术面分析、宏观微观指标监测、FOMC 与财经日历、可选社媒关注追踪，产出一个多屏网页 App + 每日邮件推送。

设计运行环境是 [WorkBuddy](https://www.workbuddy.cn)（提供云数据库、定时任务、应用发布、浏览器自动化），但核心脚本均为独立 Python，稍加改造即可脱离运行。

## 功能总览

| 模块 | 内容 | 数据来源 |
|---|---|---|
| 持仓分析 | 一票一卡：现价/盈亏/占比 + MACD 五级判定 + 背离检测 | westock 行情接口 |
| 观察池 | 21 只标的 + 科技对冲组（红利/创新药/煤炭），MACD 走向排序条形图 | 同上 |
| 宏观微观 | 美债收益率/利差、美元/VIX、CPI/PPI、PMI、M1/M2、社融、LPR 历史趋势图 | westock 宏观指标 |
| 事件日历 | FOMC 决议倒计时（美联储官网）+ 金十「大事」（需登录态） | CDP 浏览器抓取 |
| 博主动态（可选） | T-1 窗口更新检测、改名检测、抖音视频 AI 章节要点总结 | CDP 真实 Chrome |
| 产出 | 4 屏网页 App（首页/持仓/宏观/归档）+ 邮件摘要 | 静态 HTML + SMTP/邮件机器人 |

涨红跌绿（A 股惯例）；日报强调**差分**——只突出相对上次的变化。

## 目录结构

```
股票投资/
├── scripts/            # 全部脚本（无个人数据，可直接复用）
│   ├── westock_client.py      # 行情/宏观数据 CLI 封装（markdown 表格解析）
│   ├── macd.py                # MACD 计算 + 五级趋势判定 + 背离
│   ├── cdp.py                 # Chrome DevTools Protocol 客户端（真实 Chrome，防无头检测）
│   ├── fetch_technical.py     # 拉取持仓/观察池 K 线与 MACD → data/technical.json
│   ├── fetch_daily.py         # 拉取宏观微观当日截面 → data/daily_YYYYMMDD.json
│   ├── fetch_macro_history.py # 宏观指标历史序列 → data/macro_history.json
│   ├── fetch_fomc.py          # 美联储官网 FOMC 日历 → data/fomc.json
│   ├── fetch_jin10.py         # 金十「大事」日历（登录态）→ data/jin10.json
│   ├── fetch_social.py        # 四平台博主抓取（可选模块）→ data/social_YYYYMMDD.json
│   ├── build_daily_report.py  # 日报 HTML + 邮件摘要 + 归档页
│   ├── build_app.py           # 网页 App 四屏生成
│   └── targets.py             # 标的清单加载器（持仓/观察池 + 个人篮子）
├── config/
│   └── targets.example.json   # 标的清单示例（复制为 config/targets.json 后填自己的）
├── data/               # 运行数据（个人数据 + 产物，git 忽略）
│   ├── creators.json          # ★ 用户专属：关注博主清单
│   └── positions.json         # ★ 用户专属：持仓/观察池镜像（来自云端表）
└── reports/            # 生成的 HTML（发布目录）
```

## 快速开始（在 WorkBuddy 中复刻）

给 AI 助手的引导词——把这份 README 丢给 WorkBuddy，说「照这个帮我搭一套」，按顺序完成：

1. **建云数据库**（WorkBuddy 云服务）四张表：
   - `holdings`：market, code, name, asset_type, shares, cost_price, currency, note
   - `watchlist`：market, code, name, asset_type, tags, reason
   - `creators`：platform, platform_uid, name, note, enabled
   - `snapshots` / `daily_reports`：状态快照与报告登记（可选，用于差分）
2. **导入个人数据**：持仓 Excel / 观察池 / 关注博主清单（写入 `data/creators.json` 与云端表）
3. **配置脚本**：`data/positions.json` 由云端表自动镜像（持仓/观察池无需写进代码）；个人篮子复制 `config/targets.example.json` → `config/targets.json` 后填写；如启用社媒模块，`data/creators.json` 填自己的博主
4. **登录态准备**：启动调试 Chrome（`scripts/cdp.py` 会在首次运行时自动拉起），手动登录 weibo.com、金十 rili.jin10.com、抖音/小红书（各登录一次即可）
5. **发布应用**：`reports/` 目录发布为静态站
6. **建两个定时任务**（工作日）：
   - 08:00 隔夜版：美股复盘 + 当日事件 + 开盘提示
   - 19:00 盘后版：A 股收盘复盘 + 技术状态变化 + 机构解读
   完整任务提示词见下文「自动化任务模板」。

## 自动化任务模板（盘后版核心步骤）

```
1. fetch_technical.py --asof <D> --start <90天前> --limit 60
2. fetch_fomc.py --today <D>
3. fetch_jin10.py --date <D> --days 5          # 需登录态
4. fetch_social.py --date <D> --max-items 3    # 可选模块，需登录态，约 8 分钟
5. fetch_daily.py --date <D>
6. fetch_macro_history.py --date <D>
7. 从云端 holdings/watchlist 查询 → 覆盖 data/positions.json
8. build_daily_report.py --date <D> --mode evening
9. build_app.py --date <D>
10. 发布 reports/ 目录 + 生成邮件摘要推送
```

## 已知限制（踩过的坑）

- **微信公众号不可行**：腾讯无「按公众号拉文章」的开放接口，登录态解不开；搜狗微信索引滞后数月，等同无效。方案已内置移除，保留解析代码备将来镜像源用。
- **无头浏览器会被风控**：抖音/小红书/金十均检测 HeadlessChrome，必须用真实 Chrome + CDP（`cdp.py`）。
- **小红书 xsec_token**：主页 URL 缺 token 会静默重定向到自己的账号，必须校验落地 uid。
- **CDP 标签页泄漏**：`Page.close()` 必须同时关 target，否则数天累积上百标签页拖垮系统（已修复）。
- **快照型宏观指标无历史**：美债利差历史需用 `us_yield_curve --year` 的 10Y/2Y 两列相减自算。
- **搜狗/抖音限速**：查询间隔 ≥2s（搜狗 ≥4s），过密会断连或验证码。

## 隐私与数据边界

- `data/` 与 `config/targets.json` 承载全部个人数据（`data/positions.json` 存持仓/观察池镜像、`config/targets.json` 存个人标的篮子），两者均在 `.gitignore` 中，永不入库
- 脚本目录不含任何个人标的、持仓、成本价或本地用户名（标的清单统一由 `scripts/targets.py` 在运行时从上述本地文件读取，缺失时回退到 `config/targets.example.json` 示例清单）
- 若把本套件分享给他人，直接分发仓库即可；`data/`、`config/targets.json` 不会被带走
- 云端表启用 RLS，`owner_id` 隔离
- 所有产出仅为公开信息整理与参考性推演，不构成投资建议

## License

MIT
