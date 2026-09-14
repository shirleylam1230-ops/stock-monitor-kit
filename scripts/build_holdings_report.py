#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持仓分析报告生成器。

数据源：腾讯云自选股接口（westock CLI 拉取后落到本文件的数据结构里）。
用法：
    python3 scripts/build_holdings_report.py --asof 2026-09-11 --out reports/holdings-report-20260914.html

说明：RED 为涨、GREEN 为跌（A 股惯例）。
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macd as M

RED = "#C62828"      # 涨
GREEN = "#2E7D32"    # 跌
INK = "#1F2933"
SUB = "#6B7280"
LINE = "#E5E7EB"
BG = "#F7F8FA"
ACCENT = "#185FA5"

MACD_COLOR = {"up": RED, "flat": "#B45309", "down": GREEN}
MACD_BG = {"up": "#FEF2F2", "flat": "#FFFBEB", "down": "#F0FDF4"}

# ---------------------------------------------------------------- 持仓明细
# 字段：名称 代码 数量 成本 现价 当日% 近60日% PE(TTM) PE(fwd) PB 52周低 52周高 当日高 当日低 币种
HOLDINGS = [
    dict(name="中际旭创",   code="sz300308", shares=100,  cost=570.23,  price=926.00,   day=4.03,  d60=-32.30, pe=53.33, pefwd=39.95, pb=27.36, lo52=336.00, hi52=1416.88, hi=929.80,  lo=891.17, ccy="CNY", kind="stock"),
    dict(name="长飞光纤",   code="sh601869", shares=100,  cost=390.06,  price=473.99,   day=8.78,  d60=0.58,   pe=113.99, pefwd=67.09, pb=23.98, lo52=71.99,  hi52=599.71,  hi=475.52,  lo=428.00, ccy="CNY", kind="stock"),
    dict(name="长鑫科技",   code="sh688825", shares=200,  cost=43.03,   price=56.73,    day=-0.82, d60=555.08, pe=47.07,  pefwd=24.81, pb=19.16, lo52=38.11,  hi52=61.80,   hi=57.00,   lo=54.80,  ccy="CNY", kind="stock"),
    dict(name="长电科技",   code="sh600584", shares=100,  cost=-31.64,  price=67.74,    day=-0.56, d60=-18.32, pe=62.51,  pefwd=71.76, pb=4.19,  lo52=34.48,  hi52=113.87,  hi=68.12,   lo=65.50,  ccy="CNY", kind="stock"),
    dict(name="云南锗业",   code="sz002428", shares=100,  cost=108.80,  price=88.43,    day=-1.79, d60=-11.95, pe=799.20, pefwd=388.82, pb=37.79, lo52=24.02, hi52=132.87,  hi=89.38,   lo=85.08,  ccy="CNY", kind="stock"),
    dict(name="三环集团",   code="sz300408", shares=100,  cost=145.26,  price=124.36,   day=5.66,  d60=-21.24, pe=74.94,  pefwd=64.26, pb=10.97, lo52=40.46,  hi52=180.35,  hi=127.00,  lo=115.05, ccy="CNY", kind="stock"),
    dict(name="鼎龙股份",   code="sz300054", shares=100,  cost=88.50,   price=66.64,    day=-1.01, d60=-27.71, pe=67.78,  pefwd=60.08, pb=11.31, lo52=30.21,  hi52=111.03,  hi=67.12,   lo=64.56,  ccy="CNY", kind="stock"),
    dict(name="圣邦股份",   code="sz300661", shares=100,  cost=140.99,  price=107.98,   day=1.21,  d60=-18.67, pe=96.58,  pefwd=88.07, pb=7.57,  lo52=61.78,  hi52=151.90,  hi=108.43,  lo=104.22, ccy="CNY", kind="stock"),
    dict(name="东山精密",   code="sz002384", shares=100,  cost=254.61,  price=194.42,   day=0.35,  d60=-28.78, pe=99.33,  pefwd=60.22, pb=14.61, lo52=59.00,  hi52=280.08,  hi=199.50,  lo=187.13, ccy="CNY", kind="stock"),
    dict(name="新易盛",     code="sz300502", shares=200,  cost=493.88,  price=423.00,   day=2.94,  d60=-27.25, pe=44.96,  pefwd=39.17, pb=24.27, lo52=204.51, hi52=618.87,  hi=426.30,  lo=408.10, ccy="CNY", kind="stock"),
    dict(name="纳指ETF嘉实", code="sz159501", shares=1000, cost=1.75,   price=2.092,    day=-0.33, d60=-1.27,  pe=None,   pefwd=None,  pb=None,  lo52=1.554,  hi52=2.214,   hi=2.097,   lo=2.080,  ccy="CNY", kind="fund"),
    dict(name="科创50ETF易方达", code="sh588080", shares=4000, cost=2.02, price=1.593,  day=-0.99, d60=-18.43, pe=None,   pefwd=None,  pb=None,  lo52=1.275,  hi52=2.321,   hi=1.599,   lo=1.554,  ccy="CNY", kind="fund"),
    dict(name="易方达科创板", code="sh506002", shares=1900, cost=2.26,  price=2.060,    day=-0.82, d60=-16.36, pe=None,   pefwd=None,  pb=None,  lo52=0.915,  hi52=2.785,   hi=2.065,   lo=2.009,  ccy="CNY", kind="fund"),
    dict(name="南方港韩科技", code="hk03431", shares=100, cost=8.41,    price=None,     day=None,  d60=None,   pe=None,   pefwd=None,  pb=None,  lo52=None,   hi52=None,    hi=None,    lo=None,   ccy="HKD", kind="fund"),
]

# ---------------------------------------------------------------- 财报（2026 中报）
FINANCE = {
    "sz300308": dict(rev="417.78亿", rev_yoy=182.49, np="136.51亿", np_yoy=241.70, gm=46.25, roe=34.25, npm=35.27, ocf="18.00亿"),
    "sh601869": dict(rev="98.09亿",  rev_yoy=53.64,  np="29.25亿",  np_yoy=888.88, gm=53.36, roe=17.87, npm=32.48, ocf="18.26亿"),
    "sh688825": dict(rev="1503.10亿", rev_yoy=873.64, np="776.05亿", np_yoy=3427.76, gm=84.74, roe=57.60, npm=71.55, ocf="1311.56亿"),
    "sh600584": dict(rev="195.27亿", rev_yoy=4.96,   np="8.45亿",   np_yoy=79.41,  gm=15.15, roe=2.92,  npm=4.21,  ocf="29.64亿"),
    "sz002428": dict(rev="7.32亿",   rev_yoy=38.21,  np="0.74亿",   np_yoy=235.31, gm=27.87, roe=4.84,  npm=10.44, ocf="-1.57亿"),
    "sz300408": dict(rev="64.23亿",  rev_yoy=54.82,  np="19.32亿",  np_yoy=56.18,  gm=44.32, roe=8.53,  npm=30.08, ocf="12.97亿"),
    "sz300054": dict(rev="19.25亿",  rev_yoy=11.15,  np="5.29亿",   np_yoy=70.21,  gm=58.83, roe=9.39,  npm=29.26, ocf="5.67亿"),
    "sz300661": dict(rev="25.95亿",  rev_yoy=42.70,  np="4.20亿",   np_yoy=109.28, gm=51.84, roe=4.30,  npm=16.25, ocf="3.82亿"),
    "sz002384": dict(rev="277.98亿", rev_yoy=63.95,  np="29.57亿",  np_yoy=290.09, gm=20.15, roe=12.14, npm=10.74, ocf="23.84亿"),
    "sz300502": dict(rev="209.10亿", rev_yoy=100.34, np="75.29亿",  np_yoy=90.98,  gm=48.44, roe=30.99, npm=36.19, ocf="16.16亿"),
}

# ---------------------------------------------------------------- 个股分析（异动 / 供需 / 策略）
ANALYSIS = {
    "sz300308": dict(
        call="持有，但分批止盈",
        move="9/11 披露 H 股中期报告及翌日披露报表；近一周连续发布 H 股例行披露，属常规动作，无实质性经营异动。",
        ind="光博会反馈「供不应求」，产业焦点正从更高速率转向更高密度光互连；1.6T 订单已排至明年。花旗调研称供给缺口仍可能达 25%，瓶颈在 DSP 而非光芯片。",
        act="中报营收 +182%、净利 +242%，是本组合基本面最强的 AI 互联资产。但 PE(TTM) 53.3x、PB 27.4x 已计入高预期，且近 60 日回撤 32.3%。若跌破 891（当日低点）且放量，视为趋势走弱信号；若有效站回 950 上方，可继续持有。仓位已占 29.6%，不建议加仓。",
    ),
    "sh601869": dict(
        call="持有，弹性最大",
        move="9/11 召开 2026 年第二次临时股东会并决议通过；8/21 推出 H 股股份奖励计划。无负面异动。",
        ind="当日最大技术利好：空芯光纤衰减突破至 0.032dB/km，属国际领先水平；叠加《信息通信行业发展\"十五五\"规划》强化算力新基建。光纤环节正从「周期品」重估为「AI 基建耗材」。",
        act="净利同比 +888.88%、毛利率 53.4%，近 60 日是组合里唯一收正（+0.58%）的持仓，说明资金正在这条支线上做切换。PE 114x 偏贵但 PEG 可接受。回踩 428（当日低点）可作为加仓参考位，跌破 400 需重新评估。",
    ),
    "sh688825": dict(
        call="基本面最强但技术面刚转弱，加仓需等企稳",
        move="8/28 披露半年报、超额配售选择权实施结果，并公告 2026 年半年度计提资产减值准备——次新股计提减值需留意。",
        ind="存储超级周期确立：长鑫存储利润率登顶全球，HBM 与先进封装价值量转移，DRAM 供给持续紧张。3.85 万亿市值已居 A 股市值榜首。",
        act="这是全部持仓里基本面最强的：营收 +873.6%、净利 +3427.8%、毛利率 84.7%、ROE 57.6%、经营现金流 1311 亿，PE 仅 47x、前瞻 PE 24.8x，"
        "而你只持有 200 股约 1.13 万元，占总仓位 3.6%——反向看，云南锗业这种 ROE 4.8%、经营现金流为负的标的却占了 2.8%。配置失衡这一点没变。<br>"
        "<b>但上一版报告建议「加仓」，现在要打个折</b>：MACD 在 8 个交易日前死叉、DIF 跌破 DEA 且柱体转负（-86bp），MA5/10/20 已转为空头排列。"
        "基本面好不等于现在就能买——它上市仅一个多月、近 60 日 +555% 的涨幅存在次新股基数失真，此时追进去大概率买在动能衰竭的位置。"
        "建议改为：<b>等 DIF 重回 DEA 上方（重新金叉）、或回踩 MA20 不破再分批加</b>；在此之前维持现状，并把减出来的仓位优先预留给它。",
    ),
    "sh600584": dict(
        call="警惕摊薄，建议减仓或观望",
        move="⚠️ 9/3 连发五份公告，核心是「2026 年度向特定对象发行 A 股股票预案」——即定增，存在股本摊薄。9/10 公告股票期权激励计划授予结果。这是本组合唯一的股权融资类负面异动。",
        ind="先进封装受益于 AI（HBM 带动），无锡国资加码本地半导体扩产。逻辑成立但公司自身盈利质量弱。",
        act="营收仅 +4.96%、净利率 4.21%、ROE 2.92%，是持仓中盈利能力最弱的一只，PE 却高达 62.5x 且前瞻 PE 反升至 71.8x（说明盈利预期还在下修）。叠加定增摊薄，基本面与技术面双弱。<br>"
        "⚠️ 另：<b>MACD 空头趋势</b>——8 个交易日前死叉，绿柱已连续 4 日拉长，动能仍在恶化，技术上属于应减仓的一档。<br>"
        "但你的成本价已摊薄至 -31.64 元（本人确认，非录入错误），本金早已通过做 T 收回，剩余 100 股为零成本持有。"
        "这意味着它的下行不会侵蚀你的本金，真正的代价是<b>机会成本</b>：6774 元市值锁在一只 ROE 2.9%、盈利预期下修且正在定增摊薄的标的上。"
        "若认可这个判断，可择机了结并把资金转向长鑫科技这类基本面更强的标的；若看好先进封装周期，则至少不在定增完成前加仓。",
    ),
    "sz002428": dict(
        call="基本面最弱，建议择机减仓",
        move="9/11 披露投资者关系活动记录表；披露太阳能锗晶片产能 125 万片/年（折合 4 英寸）。无回购、无增持。",
        ind="锗受益于光伏与红外需求，但供给端弹性大、议价能力弱；同日行业新闻提示「光纤概念 10 家公司 2025 合计亏损 1.5 亿」，说明该链条整体盈利并未改善。",
        act="这是持仓里财务质量最差的一只：PE 799x、ROE 4.84%、净利率 10.4%、经营现金流 -1.57 亿（净流出），利息负债率 144%。营收 7.3 亿的体量撑不起 57.8 亿市值。近 60 日 -11.95%。若后续财报经营现金流转正，可重新评估；在此之前不建议补仓。",
    ),
    "sz300408": dict(
        call="持有，回购是加分项",
        move="✅ 9/1 公告「回购股份比例达到 1% 暨回购进展」——真金白银回购，管理层态度积极。9/3 H 股证券变动月报表。",
        ind="MLCC 进入 AI 通胀链：AI 服务器重塑 MLCC 供应格局，行业供给紧张、产能腾挪打开国产替代窗口；机构周报提示「重新关注 MLCC 等 AI 通胀链」。",
        act="中报营收 +54.8%、净利 +56.2%、毛利率 44.3%，资产负债率仅 20.4%（持仓中最健康的资产负债表）。回购 + 行业涨价 + 稳健财务，三者叠加。当日 +5.66% 放量反弹。参考 115（当日低点）作为短期支撑。",
    ),
    "sz300054": dict(
        call="观察，等待订单信号",
        move="✅ 9/1 公告回购公司股份进展。⚠️ 9/11 董事会决议拟变更经营范围——拟删除集成电路芯片设计及服务相关业务，同步修订章程，属业务收缩信号，需关注后续口径。",
        ind="HBM 与先进封装带动 CMP 抛光垫等材料需求；但 9/11 主力资金净流出 1.0 亿，短期情绪承压。",
        act="毛利率高达 58.8%（持仓最高），但营收增速仅 +11.15%，是增速最慢的一只，PE 67.8x 缺乏增长支撑。经营范围删减芯片设计业务，需确认是聚焦主业还是能力收缩。建议归为「等待订单信号验证」，不加仓。",
    ),
    "sz300661": dict(
        call="持有，机构在增持",
        move="✅ 摩根大通增持 10.09 万股，H 股好仓比例升至 16.05%；9/7 公告股票期权激励计划自主行权；9/4 H 股中期报告。",
        ind="模拟芯片国产替代逻辑延续，但当日主力资金净流出 6407 万，9/10 融资净买入 1178 万环比 +424%，多空分歧明显。",
        act="营收 +42.7%、净利 +109.3%，利润增速远快于营收（规模效应显现），毛利率 51.8%。但 ROE 仅 4.3%（总资产周转慢），PE 96.6x 偏贵。海外龙头增持是积极信号。参考 104（当日低点）为短期支撑。",
    ),
    "sz002384": dict(
        call="持有但需盯紧杠杆",
        move="✅ 9/1 公告回购股份进展；9/11 披露半年报（英文版）及临时股东会决议。",
        ind="PCB 新品放量 + 盈利修复，AI 服务器 PCB 需求旺盛；但同业出现「200 亿资本开支侵蚀隐性利润」的讨论，需警惕行业扩产过度。",
        act="营收 +63.9%、净利 +290.1%，弹性最大的一只是它；但毛利率仅 20.2%（持仓最低，重资产薄利属性），资产负债率 64.5%、有息负债 241 亿，杠杆最高。净利润现金含量偏低。这类标的利润波动会被杠杆放大。参考 187（当日低点）为短期支撑。",
    ),
    "sz300502": dict(
        call="持有，修复概率高于同类",
        move="9/11 召开业绩说明会；9/11 公告限制性股票激励计划预留授予第二期归属暨股份上市（小额流通增加）；9/7 披露新一期限制性股票激励计划自查报告。",
        ind="与中际旭创同享光模块景气；但竞争加剧——已有分析讨论美国厂商 AAOI 抢占份额的可能性，需持续跟踪份额变化。",
        act="营收 +100.3%、净利 +91.0%、毛利率 48.4%、ROE 31.0%。与同为光模块的中际旭创（PE 53.3x）相比，新易盛 PE 44.96x、前瞻 PE 39.2x 更便宜，基本面差距不大而估值更低——这解释了为何它 -14.4% 而中际旭创 +62.4%：是买入时点差异，不是资产质量差异。若光模块景气延续，它的修复空间反而更大。参考 408（当日低点）。",
    ),
}

FUND_NOTE = {
    "sz159501": "跟踪纳斯达克 100，是组合中唯一的海外敞口。近 60 日 -1.27%，波动最小，实际起到了稳定器的作用——但仓位太轻（0.67%），起不到分散效果。MACD 已死叉且柱体转负，短期动能回落，但幅度极小（-21bp），属高位横盘而非趋势反转。",
    "sh588080": "科创 50 宽基，占 2.03%，亏损 21.1%。它与你个股持仓高度同向（同为科创板半导体），并未起到分散作用，反而是叠加的风险敞口。MACD 空头趋势且均线空排，暂无修复迹象。",
    "sh506002": "科创板 LOF，占 1.25%，亏损 8.9%。同上，与个股持仓同向，MACD 同为空头排列。",
    "hk03431": "港股 ETF（港元计价），行情接口暂无数据，沿用表格市值 879.04 元。疑似跟踪港韩科技股，与你的 A 股半导体持仓构成跨境同赛道叠加。",
}

# 观察池科技标的的补充说明（仅用于 MACD 概览表的备注列）
WATCH_NOTE = {
    "hk00700": "仅防御性观察",
    "hk09988": "仅防御性观察",
}


def sig_chip(r):
    """MACD 状态小标签。"""
    if not r.get("ok"):
        return f"<span style='color:{SUB}'>—</span>"
    return (f"<span style='display:inline-block;font-size:12px;padding:2px 9px;border-radius:20px;"
            f"background:{MACD_BG[r['cls']]};color:{MACD_COLOR[r['cls']]};font-weight:500'>{r['label']}</span>")


def cross_text(r):
    if not r.get("ok"):
        return "—"
    if r["cross_type"] == "golden":
        return f"金叉 {r['cross_ago']} 日前"
    if r["cross_type"] == "dead":
        return f"死叉 {r['cross_ago']} 日前"
    return "无交叉"


def money(x):
    return f"{x:,.2f}"


def hist_fmt(x):
    """低价 ETF 的柱体绝对值很小，按量级自适应小数位。"""
    if x is None:
        return "—"
    a = abs(x)
    if a >= 1:
        return f"{x:+.2f}"
    if a >= 0.01:
        return f"{x:+.3f}"
    return f"{x:+.4f}"


def pct(x, digits=2):
    return f"{x:+.{digits}f}%"


def color(x):
    if x is None:
        return SUB
    return RED if x > 0 else (GREEN if x < 0 else SUB)


def build_html(asof, run_date, tech):
    rows, total_cost, total_mv = [], 0.0, 0.0
    for h in HOLDINGS:
        if h["price"] is None:
            mv = None
            cost = h["cost"] * h["shares"]
        else:
            cost = h["cost"] * h["shares"]
            mv = h["price"] * h["shares"]
        rows.append((h, cost, mv))
        total_cost += cost
        if mv:
            total_mv += mv

    # 剔除长电科技（成本为负，不可比）后的真实口径
    adj_cost = sum(c for h, c, m in rows if h["code"] != "sh600584")
    adj_mv = sum(m for h, c, m in rows if h["code"] != "sh600584" and m)
    adj_pl = adj_mv - adj_cost
    adj_pct = adj_pl / adj_cost * 100

    win = sum(1 for h, c, m in rows if m and c > 0 and m > c)
    lose = sum(1 for h, c, m in rows if m and c > 0 and m < c)
    # ETF/链接仓
    fund_mv = sum(m for h, c, m in rows if h["kind"] == "fund" and m)
    top2 = dict((h["name"], m) for h, c, m in rows if m)
    ai_cluster = top2.get("中际旭创", 0) + top2.get("新易盛", 0) + top2.get("长飞光纤", 0)
    ai_ratio = ai_cluster / total_mv * 100

    # ---- MACD 技术面
    tech_h = {}
    for code, v in tech.get("holdings", {}).items():
        tech_h[code] = M.analyze(v["series"])
    tech_w = {}
    for code, v in tech.get("watch", {}).items():
        tech_w[code] = M.analyze(v["series"])
    tech_g = {}
    for code, v in tech.get("hedges", {}).items():
        tech_g[code] = M.analyze(v["series"])

    stk_sig = [(c, r) for c, r in tech_h.items()
               if r.get("ok") and any(x["code"] == c and x["kind"] == "stock" for x in HOLDINGS)]
    weak = sorted([(c, r) for c, r in stk_sig if r["signal"] in ("weak", "bear")],
                  key=lambda kv: M.order_label(kv[1]["signal"]), reverse=True)
    strong = [c for c, r in stk_sig if r["signal"] in ("strong", "turn")]
    n_bear = sum(1 for _, r in stk_sig if r["signal"] == "bear")

    css = f"""
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;color:{INK};background:#fff;line-height:1.6;padding:32px 20px}}
    .wrap{{max-width:1080px;margin:0 auto}}
    h1{{font-size:24px;font-weight:600;margin-bottom:6px}}
    h2{{font-size:17px;font-weight:600;margin:34px 0 14px;padding-left:10px;border-left:3px solid {ACCENT}}}
    .meta{{color:{SUB};font-size:13px;margin-bottom:22px}}
    .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin:18px 0}}
    .kpi{{background:{BG};border:1px solid {LINE};border-radius:10px;padding:14px 16px}}
    .kpi .l{{font-size:12px;color:{SUB}}}
    .kpi .v{{font-size:21px;font-weight:600;margin-top:3px}}
    .kpi .s{{font-size:12px;color:{SUB};margin-top:2px}}
    .warn{{background:#FFF7ED;border:1px solid #FDBA74;border-radius:10px;padding:14px 16px;margin:18px 0;font-size:13.5px}}
    .warn b{{color:#C2410C}}
    table{{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}}
    th{{text-align:right;padding:9px 8px;border-bottom:2px solid {LINE};color:{SUB};font-weight:500;font-size:12px;white-space:nowrap}}
    th:first-child,td:first-child{{text-align:left}}
    td{{text-align:right;padding:9px 8px;border-bottom:1px solid {LINE};white-space:nowrap}}
    tbody tr:hover{{background:{BG}}}
    .card{{border:1px solid {LINE};border-radius:12px;padding:16px 18px;margin-bottom:14px}}
    .chead{{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:10px}}
    .cname{{font-size:16px;font-weight:600}}
    .ccode{{font-size:12px;color:{SUB};font-weight:400;margin-left:6px}}
    .tag{{font-size:12px;padding:3px 10px;border-radius:20px;background:#EEF2FF;color:{ACCENT};white-space:nowrap}}
    .tag.risk{{background:#FEF2F2;color:#B91C1C}}
    .tag.good{{background:#ECFDF5;color:#047857}}
    .kv{{display:grid;grid-template-columns:74px 1fr;gap:6px 12px;font-size:13.5px;margin-top:8px}}
    .kv dt{{color:{SUB};font-size:12.5px;padding-top:2px}}
    .kv dd{{}}
    .foot{{margin-top:36px;padding-top:16px;border-top:1px solid {LINE};font-size:12px;color:{SUB}}}
    .trend{{border:1px solid {LINE};border-radius:12px;padding:6px 4px;margin-top:10px;background:{BG}}}
    .trend td{{border-bottom:1px solid #EAECF0}}
    .trend tbody tr:last-child td{{border-bottom:none}}
    .trend th{{border-bottom:1px solid #D0D5DD}}
    .macdrow{{display:flex;gap:10px;align-items:flex-start;padding:9px 11px;margin-top:9px;
              border-radius:8px;background:{BG};border:1px solid {LINE}}}
    .macdrow .mb{{flex:0 0 92px;font-size:12px;color:{SUB};padding-top:1px}}
    .macdrow .mt{{flex:1;font-size:13px;line-height:1.55}}
    @media(max-width:640px){{body{{padding:16px 10px}}th,td{{font-size:12px;padding:7px 4px}}.macdrow{{flex-direction:column;gap:4px}}.macdrow .mb{{flex:none}}}}
    """

    html = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>持仓分析报告 {run_date}</title><style>{css}</style></head><body><div class='wrap'>",
        f"<h1>持仓分析报告</h1>",
        f"<div class='meta'>生成时间 {run_date} · 行情数据截至 {asof} 收盘 · 财报口径 2026 年中报 · 共 {len(HOLDINGS)} 个持仓标的</div>",
    ]

    # KPI
    html.append("<div class='kpis'>")
    html.append(f"<div class='kpi'><div class='l'>总市值（元）</div><div class='v'>{money(total_mv)}</div><div class='s'>含港股 ETF 按表值折算</div></div>")
    html.append(f"<div class='kpi'><div class='l'>浮动盈亏（剔除异常项）</div><div class='v' style='color:{color(adj_pl)}'>{money(adj_pl)}</div><div class='s'>{pct(adj_pct)}</div></div>")
    html.append(f"<div class='kpi'><div class='l'>盈利 / 亏损标的</div><div class='v'>{win} / {lose}</div><div class='s'>长电科技零成本持有，不参与统计</div></div>")
    html.append(f"<div class='kpi'><div class='l'>AI 算力链集中度</div><div class='v' style='color:#C2410C'>{ai_ratio:.1f}%</div><div class='s'>光模块 + 光纤三只合计</div></div>")
    html.append("</div>")

    # 风险提示
    html.append(
        "<div class='warn'><b>三个必须先看的结论</b><br>"
        f"① <b>集中度过高</b>：中际旭创 + 新易盛 + 长飞光纤合计占总仓位 {ai_ratio:.1f}%，且同属 AI 算力互联一条链。观察池的 14 只（中微、北方华创、寒武纪、海光、源杰、中科飞测、华虹、盛合晶微等）又是同一条链——若按观察池继续加仓，等于把风险敞口再放大一倍，建议观察池与持仓之间有意识地做行业错配。<br>"
        "② <b>配置失衡</b>：基本面最强的是长鑫科技（营收 +873%、净利 +3428%、毛利率 84.7%、ROE 57.6%），却只占 3.6%；财务质量最差的云南锗业（PE 799x、ROE 4.8%、经营现金流为负）反而占 2.8%。仓位与基本面质量倒挂。<br>"
        "③ <b>普涨止损在先</b>：近 60 日除长鑫科技（次新股，基数失真）外全部回撤，三环 -21%、东山 -28.8%、鼎龙 -27.7%、新易盛 -27.3%、中际旭创 -32.3%。这是板块级别的估值压缩，不是个股问题，分散持仓并不能解决。"
        "</div>"
    )

    names = {h["code"]: h["name"] for h in HOLDINGS}

    # 技术面总览
    html.append("<h2>技术面总览（MACD）</h2>")
    html.append(
        f"<div style='font-size:13px;color:{SUB};margin-bottom:6px'>"
        f"口径：日线 MACD（12,26,9），数据截至 {asof}。柱 = 2×(DIF−DEA)。"
        f"「强度」为柱体相对价格的基点值，用于跨价格标的横向比较。</div>"
    )
    html.append("<div class='trend'><table><thead><tr>"
                "<th>标的</th><th>状态</th><th>收盘</th><th>DIF</th><th>DEA</th><th>柱</th><th>强度(bp)</th>"
                "<th>最近交叉</th><th>动能</th><th>建议动作</th></tr></thead><tbody>")
    for code, r in sorted(stk_sig, key=lambda kv: (M.order_label(kv[1]["signal"]), -kv[1]["hist_bp"])):
        v = [b for b in tech["holdings"][code]["series"] if b["macd"] is not None][-1]
        prev = [b for b in tech["holdings"][code]["series"] if b["macd"] is not None][-2]
        kchg = (v["close"] / prev["close"] - 1) * 100
        hist_txt = f"<span style='color:{color(r['hist'])}'>{hist_fmt(r['hist'])}</span>"
        bp_txt = f"<span style='color:{color(r['hist_bp'])}'>{r['hist_bp']:+.0f}</span>"
        if r["streak"] >= 2:
            mom = f"柱连续{r['streak']}日{'放大' if r['hist'] > 0 else '拉长'}"
        elif r["slope"] > 0:
            mom = "缓慢转强"
        elif r["slope"] < 0:
            mom = "动能收敛"
        else:
            mom = "走平"
        if r["divergence"] == "bottom":
            mom += " · 底背离"
        if r["divergence"] == "top":
            mom += " · ⚠️顶背离"
        act = {"strong": "持有", "turn": "持有观察", "hold": "持有",
               "weak": "分批减仓", "bear": "减仓 / 不补仓"}[r["signal"]]
        act_c = SUB if r["signal"] in ("strong", "hold", "turn") else GREEN
        html.append(
            f"<tr><td>{names.get(code, code)}</td>"
            f"<td style='text-align:center'>{sig_chip(r)}</td>"
            f"<td>{v['close']:,.2f} <span style='color:{color(kchg)};font-size:11px'>{pct(kchg)}</span></td>"
            f"<td>{r['dif']:+.2f}</td><td>{r['dea']:+.2f}</td><td>{hist_txt}</td><td>{bp_txt}</td>"
            f"<td>{cross_text(r)}</td><td style='font-size:12px'>{mom}</td>"
            f"<td style='color:{act_c};font-size:12px'>{act}</td></tr>"
        )
    html.append("</tbody></table></div>")

    weak_names = "、".join(names.get(c, c) for c, _ in weak)
    turn_names = "、".join(names.get(c, c) for c in strong)
    html.append(
        f"<div class='warn' style='background:#F8FAFC;border-color:{LINE}'>"
        f"<b>技术面结论</b><br>"
        f"① <b>{len(weak)}/{len(stk_sig)} 只处于走弱或空头状态</b>（{weak_names}）——MACD 与近 60 日跌幅互相印证，"
        f"说明这不是普通回调而是趋势级别的动能衰竭，其中云南锗业、鼎龙股份、长电科技的柱状体仍在连续放大（绿柱拉长），"
        f"减仓优先级最高。<br>"
        f"② <b>中际旭创出现底背离</b>：价格创阶段新低但 DIF 未同步走低，且 4 个交易日前 MACD 金叉、柱体已连续 8 日放大，"
        f"是组合中最明确的超跌反弹信号。这与它 -32.3% 的最大回撤并不矛盾——跌得最深通常先看修复。<br>"
        f"③ <b>转强的有 {len(strong)} 只</b>（{turn_names}），均为零轴下方金叉的反弹形态，尚未收复零轴，"
        f"应按「反弹」而非「反转」处理：站上零轴前不加仓，跌破金叉起点即离场。"
        f"</div>"
    )

    # 明细表
    html.append("<h2>持仓明细</h2><table><thead><tr><th>标的</th><th>数量</th><th>成本</th><th>现价</th><th>市值</th><th>盈亏金额</th><th>盈亏比例</th><th>当日</th><th>近60日</th><th>PE(TTM)</th></tr></thead><tbody>")
    order = sorted(rows, key=lambda r: (r[2] or 0), reverse=True)
    for h, cost, mv in order:
        if mv is None:
            html.append(
                f"<tr><td>{h['name']}<span style='color:{SUB};font-size:11px'> ({h['code']})</span></td>"
                f"<td>{h['shares']:,.0f}</td><td>{h['cost']:.2f}</td><td>—</td><td>879.04</td>"
                f"<td colspan='4' style='text-align:center;color:{SUB};font-size:12px'>行情接口暂无数据</td><td>—</td></tr>"
            )
            continue
        pl = mv - cost
        plp = pl / cost * 100 if cost > 0 else None
        pes = f"{h['pe']:.1f}" if h["pe"] else "—"
        html.append(
            f"<tr><td>{h['name']}<span style='color:{SUB};font-size:11px'> ({h['code']})</span></td>"
            f"<td>{h['shares']:,.0f}</td><td>{h['cost']:,.2f}</td><td>{h['price']:,.3f}</td><td>{money(mv)}</td>"
            f"<td style='color:{color(pl)}'>{money(pl)}</td>"
            f"<td style='color:{color(plp)}'>{pct(plp) if plp is not None else '—'}</td>"
            f"<td style='color:{color(h['day'])}'>{pct(h['day'])}</td>"
            f"<td style='color:{color(h['d60'])}'>{pct(h['d60'])}</td><td>{pes}</td></tr>"
        )
    html.append("</tbody></table>")
    html.append(
        f"<div style='font-size:12px;color:{SUB};margin-top:10px'>"
        f"注：长电科技成本价为 -31.64 元（本人确认：反复做 T 摊薄所致，数据无误），本金已通过波段全部收回，"
        f"剩余持仓为零成本股，账面 {money(6774 - (-31.64 * 100))} 元均为浮盈；因其盈亏比例无意义，「浮动盈亏」仍剔除该项统计。"
        f"若按表格原值直接汇总，账面浮盈为 {money(total_mv - total_cost)}。"
        f"ETF / LOF 合计 {money(fund_mv)}，占 {(fund_mv/total_mv*100):.2f}%。</div>"
    )

    # 个股分析卡片
    html.append("<h2>个股分析</h2>")
    for h in HOLDINGS:
        code = h["code"]
        if h["kind"] == "fund":
            trf = tech_h.get(code, {})
            extra = ""
            if trf.get("ok"):
                extra = (f"<div class='macdrow' style='margin-top:10px'><div class='mb'>MACD</div><div class='mt'>"
                         f"<b style='color:{MACD_COLOR[trf['cls']]}'>{trf['label']}</b>　柱 {hist_fmt(trf['hist'])}（{trf['hist_bp']:+.0f}bp）　"
                         f"{cross_text(trf)}　<span style='color:{SUB}'>{trf['desc']}</span></div></div>")
            html.append(
                f"<div class='card'><div class='chead'><div><span class='cname'>{h['name']}</span>"
                f"<span class='ccode'>{code}</span></div><span class='tag'>基金 / ETF</span></div>"
                f"<div style='font-size:13.5px;color:#374151'>{FUND_NOTE.get(code,'')}</div>{extra}</div>"
            )
            continue
        a = ANALYSIS.get(code)
        f = FINANCE.get(code, {})
        mv = h["price"] * h["shares"]
        cost = h["cost"] * h["shares"]
        pl = mv - cost
        plp = pl / cost * 100 if cost > 0 else None
        tag_cls = "risk" if ("减仓" in a["call"] or "警惕" in a["call"] or "失衡" in a["call"]) else ("good" if "持有" in a["call"] else "")
        pos = mv / total_mv * 100
        html.append("<div class='card'>")
        html.append(
            f"<div class='chead'><div><span class='cname'>{h['name']}</span><span class='ccode'>{code} · 仓位 {pos:.1f}%</span></div>"
            f"<span class='tag {tag_cls}'>{a['call']}</span></div>"
        )
        html.append(
            f"<div style='font-size:13px;color:{SUB}'>持仓 {h['shares']:,.0f} 股 · 现价 {h['price']:,.2f} · "
            f"<span style='color:{color(pl)}'>盈亏 {money(pl)}（{pct(plp) if plp is not None else '—'}）</span> · "
            f"当日 <span style='color:{color(h['day'])}'>{pct(h['day'])}</span> · "
            f"近60日 <span style='color:{color(h['d60'])}'>{pct(h['d60'])}</span></div>"
        )
        html.append("<dl class='kv'>")
        html.append(
            f"<dt>财报</dt><dd>营收 {f.get('rev','—')}（<span style='color:{color(f.get('rev_yoy'))}'>{pct(f.get('rev_yoy',0),1)}</span>）· "
            f"归母净利 {f.get('np','—')}（<span style='color:{color(f.get('np_yoy'))}'>{pct(f.get('np_yoy',0),1)}</span>）· "
            f"毛利率 {f.get('gm','—')}% · ROE {f.get('roe','—')}% · 经营现金流 {f.get('ocf','—')}</dd>"
        )
        html.append("</dl>")
        # ---- MACD 趋势（用于判断是否该卖）
        tr = tech_h.get(code, {})
        if tr.get("ok"):
            ma_txt = "多头排列" if tr["ma_bull"] else ("空头排列" if tr["ma_bull"] is False else "均线纠缠")
            html.append(
                f"<div class='macdrow'><div class='mb'>MACD 趋势</div><div class='mt'>"
                f"<b style='color:{MACD_COLOR[tr['cls']]}'>{tr['label']}</b>　"
                f"DIF {tr['dif']:+.2f} / DEA {tr['dea']:+.2f} / 柱 {tr['hist']:+.2f}（{tr['hist_bp']:+.0f}bp）　"
                f"RSI6 {tr['rsi6']:.0f}　MA5/10/20 {ma_txt}<br>"
                f"<span style='color:{SUB}'>{tr['desc']}</span><br>"
                f"<b>减仓触发：</b>{tr['trigger']}"
                f"</div></div>"
            )
        html.append("<dl class='kv'>")
        html.append(f"<dt>异动</dt><dd>{a['move']}</dd>")
        html.append(f"<dt>行业供需</dt><dd>{a['ind']}</dd>")
        html.append(f"<dt>策略建议</dt><dd>{a['act']}</dd>")
        html.append(
            f"<dt>价位参考</dt><dd style='color:{SUB}'>当日区间 {h['lo']:,.2f} – {h['hi']:,.2f} · 52周区间 {h['lo52']:,.2f} – {h['hi52']:,.2f} · "
            f"距离52周高点 {(h['price']/h['hi52']-1)*100:.1f}%</dd>"
        )
        html.append("</dl></div>")

    # ============================================================ 观察池
    html.append("<h2>观察池 · MACD 走向</h2>")
    html.append(
        f"<div style='font-size:13px;color:{SUB};margin-bottom:8px'>"
        f"观察池不做逐票基本面深挖，只跟 MACD 走向，用于判断「什么时候可以动」。"
        f"数据截至 {asof}，共 {len(tech_w) + len(tech_g)} 个标的。</div>"
    )

    def trend_table(items, raw, note_map=None, show_bucket=False):
        out = ["<div class='trend'><table><thead><tr>"
               + ("<th>方向</th>" if show_bucket else "")
               + "<th>标的</th><th>状态</th><th>收盘</th><th>柱</th><th>强度(bp)</th>"
                 "<th>最近交叉</th><th>动能</th><th>备注</th></tr></thead><tbody>"]
        for code, r in items:
            nm = (note_map or {}).get(code, None)
            if not r.get("ok"):
                out.append(f"<tr><td colspan='{8 if not show_bucket else 9}'>{nm or code}：{r.get('reason')}</td></tr>")
                continue
            seq = [b for b in raw[code]["series"] if b["macd"] is not None]
            v, prev = seq[-1], seq[-2]
            kchg = (v["close"] / prev["close"] - 1) * 100
            if r["streak"] >= 2:
                mom = f"柱连续{r['streak']}日{'放大' if r['hist'] > 0 else '拉长'}"
            elif r["slope"] > 0:
                mom = "缓慢转强"
            elif r["slope"] < 0:
                mom = "动能收敛"
            else:
                mom = "走平"
            if r["divergence"] == "bottom":
                mom += " · 底背离"
            if r["divergence"] == "top":
                mom += " · ⚠️顶背离"
            wname = raw[code].get("name", code)
            bucket = f"<td>{raw[code].get('bucket','')}</td>" if show_bucket else ""
            out.append(
                f"<tr>{bucket}<td>{wname}<span style='color:{SUB};font-size:11px'> ({code})</span></td>"
                f"<td style='text-align:center'>{sig_chip(r)}</td>"
                f"<td>{v['close']:,.2f}</td>"
                f"<td style='color:{color(r['hist'])}'>{hist_fmt(r['hist'])}</td>"
                f"<td style='color:{color(r['hist_bp'])}'>{r['hist_bp']:+.0f}</td>"
                f"<td>{cross_text(r)}</td>"
                f"<td style='font-size:12px'>{mom}</td>"
                f"<td style='font-size:12px;color:{SUB}'>{(note_map or {}).get(code, '')}</td></tr>"
            )
        out.append("</tbody></table></div>")
        return "".join(out)

    w_sorted = sorted(tech_w.items(), key=lambda kv: M.order_label(kv[1]["signal"]))
    html.append("<h3 style='font-size:15px;font-weight:600;margin:20px 0 6px'>现有观察池（科技 / 半导体为主）</h3>")
    html.append(trend_table(w_sorted, tech.get("watch", {}), WATCH_NOTE))

    w_bear = sum(1 for _, r in w_sorted if r.get("ok") and r["signal"] == "bear")
    html.append(
        f"<div style='font-size:13px;margin-top:8px;color:#374151'>"
        f"<b>{w_bear}/{len(w_sorted)} 只处于 MACD 空头趋势</b>，且与你的持仓高度同向——中微公司、北方华创、中科飞测、"
        f"中船特气的柱状体仍在持续拉长（连 2~7 日），说明这条链还在下跌动能释放中。"
        f"<b>短期不具备按观察池加仓的条件</b>。真正逆势走强的只有东田微与华正新材（均为零轴上方金叉 + 均线多头排列），"
        f"但它们权重小、代表性有限。腾讯、阿里已死叉 20 日以上，仅作防御性观察。"
        f"</div>"
    )

    g_sorted = sorted(tech_g.items(), key=lambda kv: (M.order_label(kv[1]["signal"]), -kv[1]["hist_bp"]))
    html.append("<h3 style='font-size:15px;font-weight:600;margin:26px 0 6px'>科技对冲篮子（新增）</h3>")
    html.append(
        f"<div style='font-size:13px;color:{SUB};margin-bottom:8px'>"
        f"针对持仓中 AI 算力链过度集中的问题，补充四类低相关方向做候选。"
        f"同样只跟 MACD 走向。</div>"
    )
    html.append(trend_table(g_sorted, tech.get("hedges", {}), show_bucket=True))

    html.append(
        "<div class='warn' style='background:#F8FAFC;border-color:"
        + LINE
        + "'><b>对冲篮子的结论（说实话）</b><br>"
        "① <b>现在不是切换的最佳时点</b>。四类候选里只有银行 ETF 处于金叉状态（14 日前金叉、柱体仍为正、均线多头排列），"
        "是唯一「既在对立面、技术面又健康」的选项。<br>"
        "② <b>红利与煤炭刚刚走弱</b>：两者分别在 5、6 个交易日前死叉，但 DIF 仍在零轴上方、"
        "且近 60 日仍有 +9% 左右的正收益——这是强趋势中的正常回撤，不是趋势反转。等死叉后重新金叉（或回踩 MA20 站稳）再介入更安全。<br>"
        "③ <b>创新药已经是深水区</b>：死叉 14~15 日、DIF 与 DEA 双双在零轴下方、柱体负得最深（-180~-220bp），"
        "属下跌趋势本身，不属「对冲」——跌它不等于对冲 AI 下跌，只是换个地方亏。<b>不建议现在作为对冲入场。</b><br>"
        "④ <b>黄金理论上最对冲</b>（与利率/美股相关而非中国科技），但它自己也在调整：8 日前死叉、柱 -120bp。"
        "等它重新站上零轴再说，届时它的对冲属性才成立。<br>"
        "<b>一句话：先把银行 ETF 放进观察池做正式候选；红利/煤炭等重新金叉；创新药和黄金暂时只看不动。</b>"
        "</div>"
    )

    html.append(
        f"<div class='foot'>数据来源：腾讯自选股数据接口（行情 / 财报 / 公告 / 新闻 / 技术指标），经本地核对，与本人提供的持仓明细表逐条一致。"
        f"MACD 口径为日线 (12,26,9)，柱 = 2×(DIF−DEA)；「强度」为柱体相对收盘价的基点值，用于跨价格标的比较。"
        f"本报告为个人持仓跟踪工具自动生成的客观数据整理，所有「策略建议」均为基于公开信息的参考性推演，<b>不构成投资建议</b>。"
        f"行情 T+0 延迟，投资决策请以交易所官方数据为准，风险自负。<br><br>报告日期 {run_date}</div>"
    )
    html.append("</div></body></html>")
    return "".join(html)


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="2026-09-11")
    ap.add_argument("--date", default="2026-09-14")
    ap.add_argument("--tech", default=os.path.join(root, "data", "technical.json"))
    ap.add_argument("--out", default=os.path.join(root, "reports", "holdings-report-20260914.html"))
    args = ap.parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tech = {}
    if os.path.exists(args.tech):
        with open(args.tech, encoding="utf-8") as fh:
            tech = json.load(fh)
    else:
        print("警告：未找到技术指标文件，MACD 相关板块将被省略。", file=sys.stderr)
    html = build_html(args.asof, args.date, tech)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("written:", args.out)


if __name__ == "__main__":
    main()
