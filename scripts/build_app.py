#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
投资 App 壳 · 页面生成器。

把「对话版」的日报能力产品化成常驻站点。当前覆盖两屏：
  reports/index.html     首页总览（市场速览 + 持仓 KPI + MACD 分布 + 事件）
  reports/holdings.html  持仓分析（一票一卡 + 排序筛选）

数据来源（全部读本地文件，不联网）：
  data/positions.json          云端 holdings / watchlist 的本地镜像
  data/technical.json          行情序列 + MACD 全套指标
  data/daily_YYYYMMDD.json     tracked 实时行情 / 指数 / 宏观
  data/jin10.json, fomc.json   事件日历

用法：
    python3 scripts/build_app.py [--date 2026-09-14]
"""
import argparse
import glob
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macd as M  # noqa: E402
import market_read as MR  # noqa: E402
import targets  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
REPORTS = os.path.join(ROOT, "reports")

RED = "#C62828"
GREEN = "#2E7D32"
INK = "#1F2933"
SUB = "#6B7280"
LINE = "#E5E7EB"
BG = "#F5F6F8"
ACCENT = "#185FA5"
WARN = "#C2410C"

# MACD 五档信号 → 颜色 / 底色
SIG_COLOR = {"strong": RED, "turn": RED, "hold": "#B45309", "weak": GREEN, "bear": GREEN}
SIG_BG = {"strong": "#FEF2F2", "turn": "#FEF2F2", "hold": "#FFFBEB", "weak": "#F0FDF4", "bear": "#F0FDF4"}
SIG_ORDER = ["strong", "turn", "hold", "weak", "bear"]

# AI 算力链成分（用于集中度口径）：读 config/targets.json（git 忽略）
AI_CHAIN = targets.ai_chain()


# ---------------------------------------------------------------- 工具
def num(v, d=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if d is None else round(x, d)


def col(v):
    x = num(v)
    if x is None:
        return SUB
    return RED if x > 0 else (GREEN if x < 0 else SUB)


def money(v, digits=0):
    x = num(v)
    if x is None:
        return "—"
    s = f"{abs(x):,.{digits}f}"
    return f"-{s}" if x < 0 else s


def pct(v, digits=2, sign=True):
    x = num(v)
    if x is None:
        return "—"
    p = f"{abs(x):.{digits}f}%"
    if not sign:
        return p
    return f"+{p}" if x > 0 else (f"-{p}" if x < 0 else p)


def esc(s):
    return (str(s if s is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def latest(pattern):
    files = sorted(glob.glob(os.path.join(DATA, pattern)))
    return files[-1] if files else None


# ---------------------------------------------------------------- 取数
def load_inputs():
    pos = load_json(os.path.join(DATA, "positions.json"), {}) or {}
    tech = load_json(os.path.join(DATA, "technical.json"), {}) or {}
    dp = latest("daily_*.json")
    daily = load_json(dp, {}) or {}
    fomc = load_json(os.path.join(DATA, "fomc.json"), {}) or {}
    macro = load_json(os.path.join(DATA, "macro_history.json"), {}) or {}
    return pos, tech, daily, fomc, macro


def tech_block(tech, group, code):
    """取某分组的 MACD 分析结果 + 60 日涨跌。"""
    grp = tech.get(group) or {}
    node = grp.get(code)
    if not node:
        return None
    series = node.get("series") or []
    a = M.analyze(series) if series else {"ok": False, "reason": "无序列"}
    closes = [num(s.get("close")) for s in series if num(s.get("close")) is not None]
    d60 = None
    if len(closes) >= 2:
        base = closes[-61] if len(closes) > 60 else closes[0]
        if base:
            d60 = (closes[-1] / base - 1) * 100
    # 当日涨跌（序列最后一根 vs 前一根收盘，口径与技术快照一致）
    a["close"] = closes[-1] if closes else None
    if len(closes) >= 2 and closes[-2]:
        a["chg"] = (closes[-1] / closes[-2] - 1) * 100
    else:
        a["chg"] = None
    a["d60"] = d60
    a["name"] = node.get("name")
    a["bucket"] = node.get("bucket")
    return a


def build_rows(pos, tech, daily):
    """合并持仓 + 实时行情 + MACD，算出每只的持仓指标。"""
    tracked = daily.get("tracked") or {}
    rows = []
    for h in pos.get("holdings") or []:
        code = h["code"]
        shares = num(h.get("shares")) or 0
        cost = num(h.get("cost_price")) or 0
        q = tracked.get(code) or {}
        price = num(q.get("price"))
        prev = num(q.get("prev"))
        chg = num(q.get("chg"))
        mv = price * shares if price is not None else None
        cost_total = cost * shares
        pnl = (mv - cost_total) if (mv is not None) else None
        pnl_pct = None
        cost_usable = cost > 0
        if cost_usable and mv is not None:
            pnl_pct = (mv / cost_total - 1) * 100
        day_pnl = (price - prev) * shares if (price is not None and prev is not None) else None
        rows.append({
            **{k: h.get(k) for k in ("code", "name", "market", "asset_type", "currency", "note")},
            "shares": shares, "cost": cost, "cost_total": cost_total,
            "price": price, "prev": prev, "chg": chg, "day_pnl": day_pnl,
            "mv": mv, "pnl": pnl, "pnl_pct": pnl_pct, "cost_usable": cost_usable,
            "macd": tech_block(tech, "holdings", code),
        })
    total_mv = sum(r["mv"] for r in rows if r["mv"] is not None)
    for r in rows:
        r["weight"] = (r["mv"] / total_mv * 100) if (r["mv"] is not None and total_mv) else None
    return rows, total_mv


def summarize(rows, total_mv):
    """汇总口径：成本为负的标的（做 T 摊薄）不计入累计盈亏，避免口径失真。"""
    valid = [r for r in rows if r["mv"] is not None]
    usable = [r for r in valid if r["cost_usable"]]
    total_cost = sum(r["cost_total"] for r in usable)
    total_pnl = sum(r["pnl"] for r in usable) if usable else None
    day_pnl = sum(r["day_pnl"] for r in valid if r["day_pnl"] is not None)
    day_base = sum(r["mv"] - r["day_pnl"] for r in valid if r["day_pnl"] is not None)
    top3 = sorted([r for r in valid], key=lambda x: -(x["mv"] or 0))[:3]
    top3_share = sum(r["mv"] for r in top3) / total_mv * 100 if total_mv else None
    ai_mv = sum(r["mv"] for r in valid if r["code"] in AI_CHAIN)
    ai_share = ai_mv / total_mv * 100 if total_mv else None
    return {
        "total_mv": total_mv, "total_cost": total_cost, "total_pnl": total_pnl,
        "pnl_pct": (total_pnl / total_cost * 100) if (total_pnl is not None and total_cost) else None,
        "day_pnl": day_pnl,
        "day_pct": (day_pnl / day_base * 100) if (day_base and day_pnl is not None) else None,
        "top3_share": top3_share, "top3": top3, "ai_share": ai_share,
        "count": len(rows), "quoted": len(valid),
        "excluded": [r for r in rows if r["mv"] is None],
        "neg_cost": [r for r in rows if not r["cost_usable"] and r["cost"] != 0],
    }


# ---------------------------------------------------------------- 样式 / 骨架
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
     color:#1F2933;background:#F5F6F8;line-height:1.6;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.wrap{max-width:1080px;margin:0 auto;padding:0 18px 48px}
nav{background:#fff;border-bottom:1px solid #E5E7EB;position:sticky;top:0;z-index:9}
nav .inner{max-width:1080px;margin:0 auto;padding:0 18px;display:flex;align-items:center;gap:4px;height:52px}
nav .brand{font-size:14.5px;font-weight:600;margin-right:16px;color:#1F2933}
nav a.tab{font-size:13.5px;color:#6B7280;padding:6px 12px;border-radius:7px}
nav a.tab:hover{background:#F1F3F6;color:#1F2933}
nav a.tab.on{background:#E8F0FA;color:#185FA5;font-weight:600}
header.head{padding:22px 0 6px}
header.head h1{font-size:21px;font-weight:600;letter-spacing:-.2px}
header.head .meta{color:#6B7280;font-size:12.5px;margin-top:3px}
h2{font-size:14.5px;font-weight:600;margin:26px 0 10px;padding-left:9px;border-left:3px solid #185FA5}
h3{font-size:13.5px;font-weight:600;margin:18px 0 8px;color:#374151}
.card{background:#fff;border:1px solid #E5E7EB;border-radius:11px}
.grid{display:grid;gap:10px}
.g4{grid-template-columns:repeat(auto-fit,minmax(158px,1fr))}
.g6{grid-template-columns:repeat(auto-fit,minmax(132px,1fr))}
.tile{background:#fff;border:1px solid #E5E7EB;border-radius:11px;padding:12px 14px}
.tile .k{font-size:11.5px;color:#6B7280;margin-bottom:3px}
.tile .v{font-size:19px;font-weight:600;letter-spacing:-.3px}
.tile .s{font-size:11.5px;color:#6B7280;margin-top:2px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:#6B7280;font-weight:500;padding:7px 8px;border-bottom:1px solid #E5E7EB;white-space:nowrap}
td{padding:7px 8px;border-bottom:1px solid #F1F3F6;vertical-align:top}
tr:last-child td{border-bottom:none}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;white-space:nowrap}
.miss{color:#9AA1AC;font-size:12px}
.note{background:#FFF8F1;border:1px solid #F5D6BC;color:#7C3A0B;border-radius:9px;
      padding:9px 12px;font-size:12px;margin-top:12px;line-height:1.65}
.hint{color:#6B7280;font-size:12px;margin-top:8px;line-height:1.7}
footer{color:#9AA1AC;font-size:11.5px;margin-top:34px;line-height:1.7;text-align:center}
.bar{display:block;height:7px;border-radius:4px;background:#EDEFF3;overflow:hidden}
.bar i{display:block;height:100%;border-radius:4px}
/* 持仓卡片 */
.cards{display:grid;gap:11px;grid-template-columns:repeat(auto-fill,minmax(316px,1fr))}
.hcard{background:#fff;border:1px solid #E5E7EB;border-radius:12px;padding:14px 15px}
.hcard .top{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}
.hcard .nm{font-size:15px;font-weight:600;letter-spacing:-.2px}
.hcard .cd{font-size:11.5px;color:#9AA1AC;margin-top:1px}
.hcard .px{font-size:21px;font-weight:600;letter-spacing:-.4px;margin-top:9px}
.hcard .chl{font-size:12.5px;margin-top:1px}
.kv{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px;margin-top:11px;
    padding-top:10px;border-top:1px solid #F1F3F6}
.kv div{font-size:12px;display:flex;justify-content:space-between;gap:6px}
.kv .k{color:#6B7280}
.ma{display:flex;flex-wrap:wrap;gap:5px;margin-top:10px}
.ma span{font-size:10.5px;padding:1px 6px;border-radius:5px;background:#F1F3F6;color:#6B7280}
.tip{margin-top:9px;font-size:11.5px;color:#6B7280;line-height:1.6;
     border-top:1px solid #F1F3F6;padding-top:8px}
.tools{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:4px 0 14px}
.tools .lb{font-size:12px;color:#6B7280;margin-right:2px}
.btn{font-size:12.5px;padding:4px 11px;border:1px solid #E0E4EA;background:#fff;border-radius:7px;
     color:#374151;cursor:pointer;font-family:inherit}
.btn:hover{border-color:#C6CDD6}
.btn.on{background:#E8F0FA;border-color:#A9C7E8;color:#185FA5;font-weight:600}
"""

NAV = """<nav><div class="inner">
<a class="brand" href="index.html">投资 App</a>
<a class="tab{t0}" href="index.html">首页总览</a>
<a class="tab{t1}" href="holdings.html">持仓分析</a>
<a class="tab{t2}" href="macro.html">宏观趋势</a>
<a class="tab{t3}" href="archive.html">日报归档</a>
</div></nav>"""


def shell(active, title, body, asof, extra_js=""):
    tabs = {i: "" for i in range(4)}
    tabs[active] = " on"
    nav = NAV.format(t0=tabs[0], t1=tabs[1], t2=tabs[2], t3=tabs[3])
    page = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
{nav}
<div class="wrap">
<header class="head"><h1>{esc(title)}</h1>
<div class="meta">数据截至 {esc(asof)}　·　生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</div></header>
{body}
<footer>本页为个人持仓与公开信息的整理，不构成投资建议。<br>
行情为盘中快照，MACD 基于日线收盘序列计算。</footer>
</div>{extra_js}</body></html>"""
    # CDN 缓存治理：发布平台的 CDN 按完整 URL 缓存，子页面更新后旧 URL 可能长时间
    # 返回旧内容且强刷无效。给所有站内链接追加 ?v=<发布时刻>，每次构建生成新 URL，
    # 保证用户从任一页面出发点开的都是最新版本。
    import re
    v = datetime.now().strftime("%m%d%H%M")
    page = re.sub(r"(href=[\"'])((?:index|holdings|macro|archive|daily-\d+)\.html)",
                  rf"\1\2?v={v}", page)
    return page


# ---------------------------------------------------------------- 首页总览
def sig_badge(a, small=False):
    if not a or not a.get("ok"):
        return "<span class='pill' style='background:#F1F3F6;color:#9AA1AC'>无数据</span>"
    sig = a.get("signal")
    fs = "font-size:10.5px;" if small else ""
    return (f"<span class='pill' style='background:{SIG_BG.get(sig, '#F1F3F6')};"
            f"color:{SIG_COLOR.get(sig, SUB)};{fs}'>{esc(a.get('label'))}</span>")


def render_index(pos, tech, daily, rows, total_mv, sumr, asof, fomc):
    idx = daily.get("index") or {}
    out = []

    # 市场速览
    out.append("<h2>市场速览</h2><div class='grid g6'>")
    for grp, label in (("cn", "A 股"), ("hk", "港股")):
        for code, row in (idx.get(grp) or {}).items():
            c = col(row.get("chg"))
            out.append(f"<div class='tile'><div class='k'>{esc(label)} · {esc(row.get('name'))}</div>"
                       f"<div class='v' style='color:{INK}'>{esc(row.get('price'))}</div>"
                       f"<div class='s' style='color:{c}'>{pct(row.get('chg'))}</div></div>")
    out.append("</div>")

    # 持仓 KPI
    out.append("<h2>我的持仓</h2><div class='grid g4'>")
    out.append(f"<div class='tile'><div class='k'>总市值</div><div class='v'>¥{money(sumr['total_mv'])}</div>"
               f"<div class='s'>{sumr['quoted']}/{sumr['count']} 只有行情</div></div>")
    out.append(f"<div class='tile'><div class='k'>当日盈亏</div>"
               f"<div class='v' style='color:{col(sumr['day_pnl'])}'>{money(sumr['day_pnl'])}</div>"
               f"<div class='s' style='color:{col(sumr['day_pnl'])}'>{pct(sumr['day_pct'])}</div></div>")
    out.append(f"<div class='tile'><div class='k'>累计浮动盈亏</div>"
               f"<div class='v' style='color:{col(sumr['total_pnl'])}'>{money(sumr['total_pnl'])}</div>"
               f"<div class='s' style='color:{col(sumr['total_pnl'])}'>{pct(sumr['pnl_pct'])}</div></div>")
    ai_names = "、".join(AI_CHAIN.values())
    top3_codes = {r["code"] for r in sumr["top3"]}
    if top3_codes == set(AI_CHAIN):
        conc_sub = f"前三大即 AI 算力链（{ai_names}）"
    else:
        conc_sub = f"AI 算力链 {pct(sumr['ai_share'], 1, sign=False)}"
    out.append(f"<div class='tile'><div class='k'>前三大集中度</div>"
               f"<div class='v'>{pct(sumr['top3_share'], 1, sign=False)}</div>"
               f"<div class='s'>{esc(conc_sub)}</div></div>")
    out.append("</div>")

    # 持仓异动（领跌只列真正下跌的标的，不足不硬凑）
    q = [r for r in rows if r.get("chg") is not None]
    up = sorted([r for r in q if r["chg"] > 0], key=lambda r: -r["chg"])[:3]
    dn = sorted([r for r in q if r["chg"] < 0], key=lambda r: r["chg"])[:3]
    out.append("<h2>今日异动</h2><div class='grid' style='grid-template-columns:repeat(auto-fit,minmax(300px,1fr))'>")
    panels = [("领涨", up), ("领跌", dn)]
    for title, items in panels:
        out.append(f"<div class='card' style='padding:13px 15px'><h3 style='margin:0 0 8px'>{title}</h3>")
        if not items:
            out.append(f"<div class='miss'>当日{'无持仓上涨' if title == '领涨' else '无持仓下跌'}"
                       f"（{'全部收跌' if title == '领涨' else '全部收涨或平盘'}），不列示。</div>")
        for r in items:
            out.append(f"<div style='display:flex;justify-content:space-between;font-size:12.5px;padding:3px 0'>"
                       f"<span>{esc(r['name'])} <span style='color:#9AA1AC;font-size:11px'>{esc(r['code'])}</span></span>"
                       f"<span style='color:{col(r['chg'])}'>{pct(r['chg'])}　{money(r['price'],2)}</span></div>")
        out.append("</div>")
    out.append("</div>")

    # MACD 分布（持仓）
    dist = {k: 0 for k in SIG_ORDER}
    for r in rows:
        a = r.get("macd")
        if a and a.get("ok") and a.get("signal") in dist:
            dist[a["signal"]] += 1
    tot = sum(dist.values()) or 1
    out.append("<h2>持仓 MACD 信号分布</h2><div class='card' style='padding:14px 16px'>")
    for k in SIG_ORDER:
        n = dist[k]
        if not n:
            continue
        w = n / tot * 100
        out.append(f"<div style='display:flex;align-items:center;gap:10px;margin:5px 0'>"
                   f"<span style='width:66px;font-size:12px;color:{SIG_COLOR[k]}'>{esc(M_LABEL[k])}</span>"
                   f"<span style='flex:1'><span class='bar'><i style='width:{w:.1f}%;background:{SIG_COLOR[k]}'></i></span></span>"
                   f"<span style='width:34px;text-align:right;font-size:12px;color:#6B7280'>{n} 只</span></div>")
    weak = [r["name"] for r in rows if (r.get("macd") or {}).get("signal") in ("weak", "bear")]
    if weak:
        out.append(f"<div class='hint'>走弱 / 空头 {len(weak)} 只：{esc('、'.join(weak))}。"
                   f"这部分是趋势判断上需要优先关注减仓的。</div>")
    out.append("</div>")

    # 事件
    out.append("<h2>近期事件</h2><div class='card' style='padding:14px 16px'>")
    nx = (fomc or {}).get("next")
    if isinstance(nx, dict):
        # 用精确到时的时间差，避免和日报的「N 天后」口径不一致
        dleft = ""
        try:
            dt = datetime.strptime(nx.get("decision_cn"), "%Y-%m-%d %H:%M")
            mins = int((dt - datetime.now()).total_seconds() // 60)
            if mins >= 0:
                d, h = divmod(mins // 60, 24)
                dleft = f"（距今 {d} 天 {h} 小时）" if d else f"（距今 {h} 小时）"
        except Exception:  # noqa: BLE001
            pass
        tags = []
        if nx.get("sep"):
            tags.append("含经济预测 + 点阵图")
        if nx.get("press"):
            tags.append("主席发布会")
        out.append(f"<div style='font-size:13px'><b>FOMC 决议</b>　北京时间 {esc(nx.get('decision_cn'))} "
                   f"{esc(dleft)}"
                   f"<div class='hint' style='margin-top:2px'>会议 {esc(str(nx.get('month')))} 月 "
                   f"{esc(str(nx.get('dates')))}　·　{esc(' · '.join(tags))}"
                   f"　·　纪要公布 {esc(nx.get('minutes_cn'))}</div></div>")
    else:
        out.append("<div class='miss'>未取到 FOMC 日历</div>")
    ji = daily.get("jin10") or {}
    evs = (ji.get("events") or [])[:5]
    if evs:
        out.append("<h3>金十「大事」</h3><table><tbody>")
        for e in evs:
            out.append(f"<tr><td style='width:132px;color:#6B7280'>{esc(e.get('date'))} "
                       f"{esc(e.get('time'))}</td><td>{esc(e.get('title'))[:96]}</td></tr>")
        out.append("</tbody></table>")
    else:
        out.append("<div class='miss' style='margin-top:8px'>金十「大事」本次未取到</div>")
    out.append("</div>")

    # 博主模块已于 2026-09-16 下线

    # 入口
    out.append("<h2>更多</h2><div class='grid g4'>")
    for href, t, s in (("holdings.html", "持仓分析", "一票一卡 · 可排序筛选"),
                       ("macro.html", "宏观趋势", "美债/CPI/PMI/M2 · 60 日相对走势"),
                       ("archive.html", "日报归档", "按日期查历史日报")):
        out.append(f"<a class='tile' href='{href}'><div class='k'>{t}</div>"
                   f"<div style='font-size:13px;color:#185FA5;margin-top:5px'>{s} →</div></a>")
    out.append("</div>")

    # 口径说明
    notes = []
    if sumr["excluded"]:
        notes.append("无行情未计入汇总：" + "、".join(r["name"] for r in sumr["excluded"]))
    if sumr["neg_cost"]:
        notes.append("成本为负不计入累计盈亏：" + "、".join(r["name"] for r in sumr["neg_cost"])
                     + "（做 T 摊薄所致，成本价数值本身正确）")
    if notes:
        out.append("<div class='note'>" + "<br>".join(notes) + "</div>")
    return "".join(out)


M_LABEL = {"strong": "强势上行", "turn": "低位转强", "hold": "多头蓄势",
           "weak": "多头区走弱", "bear": "空头趋势"}


# ---------------------------------------------------------------- 持仓分析
def render_holdings(rows, sumr, asof):
    out = []
    out.append("<h2>持仓汇总</h2><div class='grid g4'>")
    out.append(f"<div class='tile'><div class='k'>总市值</div><div class='v'>¥{money(sumr['total_mv'])}</div>"
               f"<div class='s'>成本基础 ¥{money(sumr['total_cost'])}</div></div>")
    out.append(f"<div class='tile'><div class='k'>当日盈亏</div>"
               f"<div class='v' style='color:{col(sumr['day_pnl'])}'>{money(sumr['day_pnl'])}</div>"
               f"<div class='s' style='color:{col(sumr['day_pnl'])}'>{pct(sumr['day_pct'])}</div></div>")
    out.append(f"<div class='tile'><div class='k'>累计浮动盈亏</div>"
               f"<div class='v' style='color:{col(sumr['total_pnl'])}'>{money(sumr['total_pnl'])}</div>"
               f"<div class='s' style='color:{col(sumr['total_pnl'])}'>{pct(sumr['pnl_pct'])}</div></div>")
    top3_codes = {r["code"] for r in sumr["top3"]}
    t3 = "、".join(r["name"] for r in sumr["top3"])
    conc_sub = (f"即 AI 算力链（{t3}）" if top3_codes == set(AI_CHAIN)
                else f"AI 算力链 {pct(sumr['ai_share'], 1, sign=False)}")
    out.append(f"<div class='tile'><div class='k'>前三大集中度</div>"
               f"<div class='v'>{pct(sumr['top3_share'], 1, sign=False)}</div>"
               f"<div class='s'>{esc(conc_sub)}</div></div>")
    out.append("</div>")

    out.append("""<h2>持仓明细</h2>
<div class="tools">
<span class="lb">排序</span>
<button class="btn on" data-sort="mv">按市值</button>
<button class="btn" data-sort="chg">按当日涨跌</button>
<button class="btn" data-sort="pnl_pct">按累计盈亏</button>
<button class="btn" data-sort="sig">按 MACD 强度</button>
<span class="lb" style="margin-left:12px">筛选</span>
<button class="btn on" data-filter="all">全部</button>
<button class="btn" data-filter="stock">个股</button>
<button class="btn" data-filter="fund">ETF / LOF</button>
</div>
<div class="cards" id="cards">""")

    for r in rows:
        a = r.get("macd") or {}
        kind = "stock" if r["asset_type"] == "stock" else "fund"
        sigk = SIG_ORDER.index(a["signal"]) if (a.get("ok") and a.get("signal") in SIG_ORDER) else 9
        d60 = a.get("d60")
        # MA 位置
        ma_chips = []
        if a.get("ok"):
            for key, lab in (("ma5", "MA5"), ("ma10", "MA10"), ("ma20", "MA20"), ("ma60", "MA60")):
                v = num(a.get(key))
                if v is None or r["price"] is None:
                    continue
                rel = "上" if r["price"] >= v else "下"
                c = RED if rel == "上" else GREEN
                ma_chips.append(f"<span style='background:#F7F8FA;color:{c}'>{lab} {rel}</span>")
            if a.get("ma_bull"):
                ma_chips.append("<span style='background:#FEF2F2;color:#C62828'>均线多头排列</span>")
        # 盈亏
        if r["mv"] is None:
            pnl_html = "<span class='miss'>无行情，未计入汇总</span>"
        elif not r["cost_usable"]:
            pnl_html = (f"<span style='color:{WARN}'>成本为负（做 T 摊薄）</span>"
                        f"<div class='hint' style='margin-top:1px'>市值 ¥{money(r['mv'])}，盈亏比例不适用</div>")
        else:
            pnl_html = (f"<span style='color:{col(r['pnl'])}'>{money(r['pnl'])}　{pct(r['pnl_pct'])}</span>")

        out.append(f"""<div class="hcard" data-kind="{kind}" data-mv="{r['mv'] or 0}"
 data-chg="{r['chg'] if r['chg'] is not None else -999}"
 data-pnl="{r['pnl_pct'] if r['pnl_pct'] is not None else -999}"
 data-sig="{sigk}">
<div class="top"><div><div class="nm">{esc(r['name'])}</div>
<div class="cd">{esc(r['code'])}　·　{esc({'stock':'个股','etf':'ETF','lof':'LOF'}.get(r['asset_type'], r['asset_type']))}</div></div>
{sig_badge(a, small=True)}</div>
<div class="px">{money(r['price'], 2) if r['price'] is not None else '—'}
<span class="chl" style="color:{col(r['chg'])}">{pct(r['chg'])}</span></div>
<div class="kv">
<div><span class="k">持仓</span><span>{money(r['shares'], 0)} 股</span></div>
<div><span class="k">成本</span><span>{money(r['cost'], 2)}</span></div>
<div><span class="k">市值</span><span>{('¥' + money(r['mv'])) if r['mv'] is not None else '—'}</span></div>
<div><span class="k">占比</span><span>{pct(r['weight'], 1, sign=False)}</span></div>
<div><span class="k">浮动盈亏</span><span>{pnl_html if 'hint' not in pnl_html else pnl_html.split('<div')[0]}</span></div>
<div><span class="k">近 60 日</span><span style="color:{col(d60)}">{pct(d60)}</span></div>
</div>
<div class="ma">{''.join(ma_chips) if ma_chips else "<span>MA 数据不足</span>"}</div>
<div class="tip">{esc(a.get('desc') or a.get('reason') or 'MACD 数据不足')}
{'<br><span style="color:' + WARN + '">' + esc(a.get('trigger')) + '</span>' if a.get('trigger') else ''}</div>
{('<div class="tip" style="color:' + WARN + '">备注：' + esc(r['note']) + '</div>') if r.get('note') else ''}
</div>""")

    out.append("</div>")

    # 观察池
    pos = load_json(os.path.join(DATA, "positions.json"), {}) or {}
    tech = load_json(os.path.join(DATA, "technical.json"), {}) or {}
    watch = pos.get("watchlist") or []
    wrows = []
    for w in watch:
        a = tech_block(tech, "watch", w["code"]) or tech_block(tech, "hedges", w["code"])
        if not a:
            continue
        wrows.append({**w, "macd": a, "hedge": "hedge" in (w.get("tags") or [])})
    if wrows:
        wrows.sort(key=lambda x: (0 if x["hedge"] else 1,
                                  SIG_ORDER.index(x["macd"]["signal"])
                                  if (x["macd"].get("ok") and x["macd"].get("signal") in SIG_ORDER) else 9))
        out.append("<h2>观察池<span style='font-size:12px;color:#6B7280;font-weight:400'>"
                   "　只看 MACD 走向，不做逐票深挖</span></h2><div class='card' style='padding:6px 4px'>")
        out.append("<table><thead><tr><th>标的</th><th>类型</th><th>最新收盘</th><th>MACD 状态</th>"
                   "<th>近 60 日</th><th>走势说明</th></tr></thead><tbody>")
        for w in wrows:
            a = w["macd"]
            tag = ("<span class='pill' style='background:#FEF2F2;color:#C62828'>科技对冲</span>"
                   if w["hedge"] else "<span class='pill' style='background:#F1F3F6;color:#6B7280'>个股</span>")
            close = (f"{a.get('close'):,.2f}" if a.get("close") is not None else "—")
            out.append(f"<tr><td><b>{esc(w['name'])}</b><div style='color:#9AA1AC;font-size:11px'>{esc(w['code'])}</div></td>"
                       f"<td>{tag}</td>"
                       f"<td>{close}<div style='font-size:11px;color:{col(a.get('chg'))}'>{pct(a.get('chg'))}</div></td>"
                       f"<td>{sig_badge(a)}</td>"
                       f"<td style='color:{col(a.get('d60'))}'>{pct(a.get('d60'))}</td>"
                       f"<td style='color:#4B5563'>{esc((a.get('desc') or '')[:88])}</td></tr>")
        out.append("</tbody></table></div>")
        out.append("<div class='hint'>对冲标的（标签含 hedge）排在前面。"
                   "“暂缓”类标的的判读依据是：下跌趋势本身不等于对冲，需待 DIF/DEA 站上零轴再评估。</div>")

    notes = []
    if sumr["neg_cost"]:
        notes.append("累计浮动盈亏已排除成本为负的标的：" + "、".join(r["name"] for r in sumr["neg_cost"])
                     + "。该标的成本价为负是做 T 摊薄的真实结果，数值本身正确，但分母为负时盈亏比例无意义，故单列。")
    if sumr["excluded"]:
        notes.append("无行情标的未计入市值与盈亏：" + "、".join(r["name"] for r in sumr["excluded"]))
    if notes:
        out.append("<div class='note'>" + "<br>".join(notes) + "</div>")

    js = """<script>
(function(){
  var cards=[].slice.call(document.querySelectorAll('#cards .hcard'));
  var sort='mv', filter='all';
  function apply(){
    cards.sort(function(a,b){
      return parseFloat(b.dataset[sort==='sig'?'sig':sort])-parseFloat(a.dataset[sort==='sig'?'sig':sort]);
    });
    var box=document.getElementById('cards');
    cards.forEach(function(c){
      c.style.display=(filter==='all'||c.dataset.kind===filter)?'':'none';
      box.appendChild(c);
    });
  }
  document.querySelectorAll('.tools .btn').forEach(function(b){
    b.addEventListener('click',function(){
      var s=b.dataset.sort, f=b.dataset.filter;
      if(s){sort=s; document.querySelectorAll('.tools .btn[data-sort]').forEach(function(x){x.classList.remove('on')});}
      if(f){filter=f; document.querySelectorAll('.tools .btn[data-filter]').forEach(function(x){x.classList.remove('on')});}
      b.classList.add('on'); apply();
    });
  });
  apply();
})();
</script>"""
    return "".join(out), js


# ---------------------------------------------------------------- SVG 趋势图
def _fd(d):
    """20260911 → 09-11；202608 → 26-08（月度）。"""
    s = str(d)
    if len(s) == 8:
        return f"{s[4:6]}-{s[6:]}"
    if len(s) >= 6:
        return f"{s[2:4]}.{s[4:6]}"
    return s


def svg_chart(seqs, w=430, h=132, refs=None, digits=2, pad_r=64, log=False):
    """
    服务端生成折线图（无 JS 依赖）。
    seqs : [(label, color, [[date, val], ...])]
    refs : [(value, label, color)] 水平参考线（如 PMI 荣枯线 50）
    log  : 对数刻度（序列跨度大时用，如含数倍涨幅的次新股）
    """
    import math
    refs = refs or []
    pts_all = [p for _, _, s in seqs for p in s]
    if not pts_all:
        return "<div class='miss'>无数据</div>"
    tf = (lambda v: math.log(max(v, 1e-9))) if log else (lambda v: v)
    vals = [v for _, v in pts_all] + [r[0] for r in refs]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    span = tf(hi) - tf(lo)
    tlo = tf(lo) - span * 0.08
    thi = tf(hi) + span * 0.10
    dates = sorted({d for _, _, s in seqs for d, _ in s})
    # x 轴按日期字符串排序即可（YYYYMMDD 定长）
    n = len(dates)
    xi = {d: i for i, d in enumerate(dates)}
    px = lambda i: 4 + (w - pad_r - 8) * (i / max(n - 1, 1))
    py = lambda v: 8 + (h - 30) * (1 - (tf(v) - tlo) / (thi - tlo))

    parts = [f"<svg viewBox='0 0 {w} {h}' style='width:100%;height:auto;display:block'>"]
    for v, lab, c in refs:
        y = py(v)
        parts.append(f"<line x1='4' y1='{y:.1f}' x2='{w - pad_r}' y2='{y:.1f}' "
                     f"stroke='{c}' stroke-width='1' stroke-dasharray='4 4' opacity='.55'/>")
        parts.append(f"<text x='{w - pad_r + 4}' y='{y + 3.5:.1f}' font-size='10' fill='{c}'>{esc(lab)}</text>")
    for label, c, s in seqs:
        if not s:
            continue
        pline = " ".join(f"{px(xi[d]):.1f},{py(v):.1f}" for d, v in s)
        parts.append(f"<polyline points='{pline}' fill='none' stroke='{c}' "
                     f"stroke-width='1.8' stroke-linejoin='round' stroke-linecap='round'/>")
        lv = s[-1][1]
        parts.append(f"<circle cx='{px(xi[s[-1][0]]):.1f}' cy='{py(lv):.1f}' r='2.6' fill='{c}'/>")
        parts.append(f"<text x='{px(xi[s[-1][0]]) - 3:.1f}' y='{py(lv) - 6:.1f}' font-size='10.5' "
                     f"font-weight='600' fill='{c}' text-anchor='end'>{lv:.{digits}f}</text>")
    if dates:
        parts.append(f"<text x='4' y='{h - 4}' font-size='10' fill='#9AA1AC'>{esc(_fd(dates[0]))}</text>")
        parts.append(f"<text x='{w - pad_r}' y='{h - 4}' font-size='10' fill='#9AA1AC' "
                     f"text-anchor='end'>{esc(_fd(dates[-1]))}</text>")
    parts.append("</svg>")
    return "".join(parts)


def chart_card(title, seqs, refs=None, digits=2, note=""):
    legend = "　".join(f"<span style='color:{c};font-size:11px'>■ {esc(l)}</span>" for l, c, _ in seqs if _)
    sub = f"<div class='hint' style='margin:2px 0 6px'>{esc(note)}</div>" if note else ""
    return (f"<div class='card' style='padding:13px 15px'>"
            f"<div style='font-size:13px;font-weight:600'>{esc(title)}</div>"
            f"<div style='margin-top:2px'>{legend}</div>{sub}"
            f"<div style='margin-top:6px'>{svg_chart(seqs, refs=refs, digits=digits)}</div></div>")


# ---------------------------------------------------------------- 宏观趋势
def render_macro(daily, macro, rows):
    out = []
    us = (macro or {}).get("us") or {}
    cn = (macro or {}).get("cn") or {}

    # 最新结论（规则化判读，阈值见 scripts/market_read.py）
    blocks = [b for b in MR.market_read(daily) if b["tag"] != "市场画像"] or []
    ob = MR.overview_block(daily)
    if ob:
        blocks.append(ob)
    if blocks:
        out.append("<h2>最新结论</h2><div class='grid g4' style='grid-template-columns:repeat(auto-fit,minmax(240px,1fr))'>")
        for b in blocks:
            c = MR.LEVEL_COLOR.get(b["level"], MR.GRAY)
            out.append(f"<div class='tile' style='border-top:3px solid {c}'>"
                       f"<div style='display:flex;justify-content:space-between;align-items:baseline'>"
                       f"<span class='k'>{esc(b['tag'])}</span>"
                       f"<span style='font-size:12.5px;font-weight:700;color:{c}'>{esc(b['verdict'])}</span></div>"
                       f"<div style='font-size:12px;color:#4B5563;margin-top:6px;line-height:1.55'>"
                       f"{esc(b['detail'])}</div></div>")
        out.append("</div>")
        out.append("<div class='hint'>结论基于固定阈值的规则化判读（阈值见 scripts/market_read.py），"
                   "市场画像来自 westock 量化打分。仅供参考，不构成投资建议。</div>")

    # 最新值速览（与日报口径一致）
    d_us = daily.get("us") or {}
    yld = d_us.get("yield") or {}
    out.append("<h2>海外宏观</h2><div class='grid g6'>")
    if yld:
        out.append(f"<div class='tile'><div class='k'>美债 10Y / 2Y</div>"
                   f"<div class='v'>{num(yld.get('y10'), 2)} / {num(yld.get('y2'), 2)}</div>"
                   f"<div class='s'>利差 {num(yld.get('spread'), 1)}bp · {esc(yld.get('form'))}</div></div>")
    vix_last = (us.get("vix") or [[None, None]])[-1][1]
    out.append(f"<div class='tile'><div class='k'>VIX</div><div class='v'>{num(vix_last, 2) or '—'}</div>"
               f"<div class='s'>恐慌指数 · 30 日序列</div></div>")
    usd_last = (us.get("usd") or [[None, None]])[-1][1]
    out.append(f"<div class='tile'><div class='k'>美元指数</div><div class='v'>{num(usd_last, 2) or '—'}</div>"
               f"<div class='s'>DXY · 30 日序列</div></div>")
    d_cn = daily.get("cn") or {}
    core = d_cn.get("core") or {}
    cpi = core.get("cpi") or {}
    pmi = core.get("pmi") or {}
    mo = core.get("money") or {}
    fin = core.get("financing") or {}
    out.append(f"<div class='tile'><div class='k'>CPI 同比</div><div class='v'>{num(cpi.get('yoy'), 1) or '—'}%</div>"
               f"<div class='s'>核心 {num(cpi.get('core'), 1) or '—'}%</div></div>")
    out.append(f"<div class='tile'><div class='k'>制造业 PMI</div><div class='v'>{num(pmi.get('manu'), 1) or '—'}</div>"
               f"<div class='s'>{'荣枯线上' if (num(pmi.get('manu')) or 0) >= 50 else '荣枯线下'}</div></div>")
    out.append(f"<div class='tile'><div class='k'>M2 同比</div><div class='v'>{num(mo.get('m2'), 1) or '—'}%</div>"
               f"<div class='s'>社融存量 {num(fin.get('size_yoy'), 1) or '—'}%</div></div>")
    out.append("</div>")

    grid = []
    y10, y2, sp = us.get("yield10y") or [], us.get("yield2y") or [], us.get("spread") or []
    if y10 and y2:
        grid.append(chart_card("美债收益率与期限利差（年内）",
                               [("10Y", "#185FA5", y10), ("2Y", "#B45309", y2)], digits=2,
                               note="利差最新 " + (f"{sp[-1][1]}bp" if sp else "—") +
                                    "，倒挂/收窄都值得盯；数据源：美联储国债收益率曲线"))
    if sp:
        grid.append(chart_card("10Y-2Y 期限利差（bp）", [("利差", "#7C3AED", sp)], digits=2,
                               refs=[(0, "0", "#9AA1AC")],
                               note="跌破 0 为倒挂，历史上多对应衰退预期升温"))
    if us.get("usd"):
        grid.append(chart_card("美元指数 DXY（30 日）", [("DXY", "#185FA5", us["usd"])], digits=2,
                               note="美元走弱利多新兴市场与商品"))
    if us.get("vix"):
        grid.append(chart_card("VIX（30 日）", [("VIX", "#C2410C", us["vix"])], digits=2,
                               refs=[(20, "20", "#9AA1AC")],
                               note="20 以下偏贪婪，快速抬升常伴随指数急跌"))
    if us.get("ndx"):
        grid.append(chart_card("纳指 vs 标普（30 日）",
                               [("纳指", "#185FA5", us["ndx"]), ("标普", "#B45309", us.get("spx") or [])],
                               digits=0, note="AI 算力链的锚，隔夜版日报重点看这里"))

    cpi_s, ppi_s = cn.get("cpi") or [], cn.get("ppi") or []
    if cpi_s or ppi_s:
        grid.append(chart_card("CPI / PPI 同比（月度）",
                               [("CPI", "#185FA5", cpi_s), ("PPI", "#B45309", ppi_s)],
                               refs=[(0, "0", "#9AA1AC")], digits=1,
                               note="剪刀差收窄一般对应中下游利润改善"))
    if cn.get("pmi"):
        grid.append(chart_card("制造业 PMI（月度）", [("制造业", "#185FA5", cn["pmi"]),
                                                    ("非制造业", "#B45309", cn.get("pmi_non_manu") or [])],
                               refs=[(50, "荣枯线 50", "#9AA1AC")], digits=1,
                               note="连续低于 50 提示景气收缩，政策加码概率上升"))
    if cn.get("m2"):
        grid.append(chart_card("M1 / M2 同比与剪刀差（月度）",
                               [("M1", "#185FA5", cn.get("m1") or []), ("M2", "#B45309", cn["m2"]),
                                ("M1-M2", "#7C3AED", cn.get("m1_m2") or [])],
                               refs=[(0, "0", "#9AA1AC")], digits=1,
                               note="M1 回升是资金活化信号，对权益市场偏正面"))
    if cn.get("financing"):
        grid.append(chart_card("社融存量同比（月度）", [("社融", "#185FA5", cn["financing"])], digits=1,
                               note="信用扩张节奏，领先企业盈利预期"))
    if cn.get("lpr1y"):
        grid.append(chart_card("LPR（事件序列）",
                               [("1Y", "#185FA5", cn["lpr1y"]), ("5Y", "#B45309", cn.get("lpr5y") or [])],
                               digits=1, note="报价走平不代表宽松结束，看金十「大事」的议息窗口"))
    out.append("<div class='grid' style='grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:11px'>")
    out += grid
    out.append("</div>")

    # 微观：持仓 60 日相对走势（折线）+ 观察池 60 日涨跌（条形）
    out.append("<h2>微观趋势 · 持仓 60 日相对走势</h2>")
    tech = load_json(os.path.join(DATA, "technical.json"), {}) or {}
    series_map = {}
    for grp in ("holdings", "watch", "hedges"):
        for code, node in (tech.get(grp) or {}).items():
            if code not in series_map and node.get("series"):
                series_map[code] = node
    palette = ["#185FA5", "#C62828", "#2E7D32", "#B45309", "#7C3AED", "#0E7490",
               "#BE185D", "#4D7C0F", "#9A3412", "#1D4ED8", "#A16207", "#155E75",
               "#86198F", "#374151", "#C2410C", "#065F46"]
    hold_codes = [r["code"] for r in rows if r.get("macd")]
    seqs, legend = [], []
    for i, code in enumerate(hold_codes):
        node = series_map.get(code)
        if not node:
            continue
        pts = [(s["date"], s["close"]) for s in node["series"][-60:] if num(s.get("close"))]
        if len(pts) < 10:
            continue
        base = pts[0][1]
        norm = [[d, round(v / base * 100, 1)] for d, v in pts]
        c = palette[i % len(palette)]
        seqs.append((node.get("name") or code, c, norm))
        chg = norm[-1][1] - 100
        legend.append(f"<span style='color:{c};font-size:11.5px'>■ {esc(node.get('name') or code)} "
                      f"({'+' if chg >= 0 else ''}{chg:.1f}%)</span>")
    if seqs:
        out.append("<div class='card' style='padding:13px 15px'>")
        out.append("<div style='display:flex;flex-wrap:wrap;gap:4px 14px;margin-bottom:6px'>"
                   + "".join(legend) + "</div>")
        out.append(f"<div style='margin-top:4px'>{svg_chart(seqs, w=1010, h=210, digits=1, pad_r=44, log=True)}</div>")
        out.append("<div class='hint'>起点归一化为 100，对数刻度（长鑫科技 60 日涨幅大，"
                   "普通坐标会把其他线压扁）。跑赢的继续持有，"
                   "持续跑输且 MACD 走弱的优先处理（回到持仓分析页看信号）。</div></div>")
    else:
        out.append("<div class='miss'>技术序列缺失，请先运行 fetch_technical.py</div>")

    # 观察池 60 日涨跌条形（避免个股暴涨把折线 y 轴压扁）
    watch_rows = []
    posj = load_json(os.path.join(DATA, "positions.json"), {}) or {}
    hold_set = set(hold_codes)
    for w in posj.get("watchlist") or []:
        node = series_map.get(w["code"])
        if not node or w["code"] in hold_set:
            continue
        closes = [num(s.get("close")) for s in node["series"][-60:] if num(s.get("close"))]
        if len(closes) < 10:
            continue
        d60 = (closes[-1] / closes[0] - 1) * 100
        watch_rows.append((w.get("name") or w["code"], d60, "hedge" in (w.get("tags") or [])))
    if watch_rows:
        watch_rows.sort(key=lambda x: -x[1])
        lo = min(min(r[1] for r in watch_rows), 0)
        hi = max(max(r[1] for r in watch_rows), 0)
        zero = (0 - lo) / (hi - lo) if hi > lo else 0
        out.append("<h2>观察池与对冲 60 日涨跌</h2><div class='card' style='padding:13px 15px'>")
        for nm, d60, hedge in watch_rows:
            w = abs(d60) / max(abs(hi - lo), 1e-9) * 46
            left = d60 >= 0
            tag = ("<span class='pill' style='background:#FEF2F2;color:#C62828;margin-left:6px'>对冲</span>"
                   if hedge else "")
            bar = (f"<span style='flex:1;position:relative;height:14px'>"
                   f"<span style='position:absolute;left:{zero * 100:.1f}%;top:0;bottom:0;"
                   f"border-left:1px solid #D6DAE0'></span>"
                   f"<span style='position:absolute;top:2px;bottom:2px;"
                   f"{'left' if left else 'right'}:{(zero if left else 1 - zero) * 100:.1f}%;"
                   f"width:{w:.1f}%;background:{RED if left else GREEN};border-radius:3px'></span></span>")
            out.append(f"<div style='display:flex;align-items:center;gap:9px;margin:4px 0'>"
                       f"<span style='width:112px;font-size:12px;text-align:right'>{esc(nm)}{tag}</span>"
                       f"{bar}"
                       f"<span style='width:56px;font-size:12px;color:{col(d60)}'>"
                       f"{'+' if d60 >= 0 else ''}{d60:.1f}%</span></div>")
        out.append("</div>")

    # 板块资金流
    sec = (daily.get("sector") or {}).get("inflow") or []
    if sec:
        out.append("<h2>板块主力净流入（AI / 黄金 / 红利相关）</h2>"
                   "<div class='card' style='padding:6px 4px'><table>"
                   "<thead><tr><th>板块</th><th>今日净流入(亿)</th><th>5 日(亿)</th>"
                   "<th>领涨股</th><th>涨跌家数</th></tr></thead><tbody>")
        for s0 in sec[:12]:
            inflow = num(s0.get("inflow"))
            v = f"{inflow / 10000:.1f}" if inflow is not None else "—"
            c = col(inflow)
            out.append(f"<tr><td><b>{esc(s0.get('name'))}</b></td>"
                       f"<td style='color:{c}'>{v}</td>"
                       f"<td style='color:{col(s0.get('inflow5d'))}'>"
                       f"{(num(s0.get('inflow5d')) or 0) / 10000:.1f}</td>"
                       f"<td style='color:#4B5563'>{esc(s0.get('leader') or '—')}</td>"
                       f"<td style='color:#6B7280'>{esc(s0.get('up') or '—')}</td></tr>")
        out.append("</tbody></table></div>")

    if not us and not cn:
        out.append("<div class='note'>宏观历史序列未生成，请先运行 scripts/fetch_macro_history.py。</div>")
    return "".join(out)


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    pos, tech, daily, fomc, macro = load_inputs()
    if not pos.get("holdings"):
        print("缺少 data/positions.json 或无持仓", file=sys.stderr)
        sys.exit(1)
    asof = args.date or tech.get("asof") or daily.get("asof") or datetime.now().strftime("%Y-%m-%d")

    rows, total_mv = build_rows(pos, tech, daily)
    sumr = summarize(rows, total_mv)

    os.makedirs(REPORTS, exist_ok=True)
    p1 = os.path.join(REPORTS, "index.html")
    with open(p1, "w", encoding="utf-8") as fh:
        fh.write(shell(0, "投资 App · 首页总览",
                       render_index(pos, tech, daily, rows, total_mv, sumr, asof, fomc), asof))
    print("written:", p1)

    body, js = render_holdings(rows, sumr, asof)
    p2 = os.path.join(REPORTS, "holdings.html")
    with open(p2, "w", encoding="utf-8") as fh:
        fh.write(shell(1, "投资 App · 持仓分析", body, asof, extra_js=js))
    print("written:", p2)

    p3 = os.path.join(REPORTS, "macro.html")
    with open(p3, "w", encoding="utf-8") as fh:
        fh.write(shell(2, "投资 App · 宏观趋势", render_macro(daily, macro, rows), asof))
    print("written:", p3)

    # 博主动态屏（social.html）已于 2026-09-16 下线，不再生成

    # 归档页由日报脚本维护（单一来源），这里顺手刷新一次，保证导航不 404
    try:
        import build_daily_report as BDR
        print("written:", BDR.build_index())
    except Exception as e:  # noqa: BLE001
        print(f"[warn] 归档页刷新失败（不影响 App 两屏）：{e}", file=sys.stderr)

    print(f"持仓 {len(rows)} 只，有行情 {sumr['quoted']} 只，总市值 ¥{money(total_mv)}")


if __name__ == "__main__":
    main()
