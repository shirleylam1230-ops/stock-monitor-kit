#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
当日市场解读（规则化判读模块）。

输入 fetch_daily.py 的产出（daily_YYYYMMDD.json），输出结构化结论：
  - 美债收益率是否高位
  - VIX 是否达到恐慌
  - 国内流动性释放程度
  - A 股当天量能
  - 市场总览画像（westock 量化打分的情绪 / 宽度 / 估值等维度）

判定阈值全部显式写在这里，方便回溯与调整。level 含义：
  0 = 低位/平静（绿）  1 = 中性（灰）  2 = 偏热/警惕（橙）  3 = 高位/恐慌（红）

注意：本模块只做基于公开数据与固定阈值的参考性推演，不构成投资建议。
"""

RED, ORANGE, GRAY, GREEN = "#C62828", "#E65100", "#6B7280", "#2E7D32"
LEVEL_COLOR = {0: GREEN, 1: GRAY, 2: ORANGE, 3: RED}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _latest(series):
    """VIX/美元指数这类 ["YYYYMMDD", "值"] 序列取最新值与 5 个数据点前的值。"""
    if not series:
        return None, None
    rows = sorted(series, key=lambda x: x[0])
    vals = [(d, _num(v)) for d, v in rows if _num(v) is not None]
    if not vals:
        return None, None
    last = vals[-1][1]
    prev = vals[-6][1] if len(vals) >= 6 else vals[0][1]
    return last, prev


def bond_block(d):
    """美债：是否高位。阈值：10Y ≥5.0% 极高位，≥4.5% 高位，≥3.5% 中性，否则低位。"""
    y = (d.get("us") or {}).get("yield") or {}
    y10, y2, spread, form = y.get("y10"), y.get("y2"), y.get("spread"), y.get("form")
    if y10 is None:
        return dict(tag="美债", verdict="本次未取到", level=1,
                    detail="美债收益率数据缺失，无法判断。")
    if y10 >= 5.0:
        verdict, level = "极高位", 3
        note = "10Y 处 2007 年以来最高区间，对成长股估值的压制是全局性的"
    elif y10 >= 4.5:
        verdict, level = "高位", 2
        note = "10Y 高于 4.5% 的历史敏感位，高估值板块承压"
    elif y10 >= 3.5:
        verdict, level = "中性", 1
        note = "10Y 处近年中性区间"
    else:
        verdict, level = "低位", 0
        note = "10Y 处低位，利率环境友好"
    # 期限利差形态
    curve = f"期限利差 {spread:.0f}bp（{form}）" if spread is not None else ""
    if spread is not None and form:
        if "熊" in str(form):
            curve += "，收益率上行为长端驱动，对风险资产更不利"
        elif "牛" in str(form):
            curve += "，长端下行主导，多为避险/降息交易"
    hist = (d.get("us") or {}).get("spread_hist") or []
    if len(hist) >= 6 and spread is not None:
        old = _num(hist[-6][1])
        if old is not None:
            curve += f"；较 5 个数据点前 {spread - old:+.0f}bp"
    return dict(tag="美债收益率", verdict=verdict, level=level,
                detail=f"10Y {y10:.2f}% / 2Y {y2:.2f}%，{curve}。{note}。")


def vix_block(d):
    """VIX：是否恐慌。≥30 恐慌，25–30 高度避险，20–25 警惕，15–20 平静，<15 极低。"""
    vix_series = ((d.get("us") or {}).get("vix") or {}).get("VIX")
    vix, prev = _latest(vix_series)
    if vix is None:
        return dict(tag="恐慌指数", verdict="本次未取到", level=1,
                    detail="VIX 数据缺失，无法判断。")
    if vix >= 30:
        verdict, level = "恐慌", 3
        note = "已进入恐慌区，历史上此区域常伴随流动性冲击，不宜追跌砍仓"
    elif vix >= 25:
        verdict, level = "高度避险", 3
        note = "避险情绪浓重，风险资产波动放大"
    elif vix >= 20:
        verdict, level = "警惕", 2
        note = "波动率抬升，市场开始定价不确定性"
    elif vix >= 15:
        verdict, level = "平静", 1
        note = "波动率处常态区间"
    else:
        verdict, level = "极低", 0
        note = "波动率极低≠安全：低波动常伴随仓位拥挤，一旦有事件冲击（如议息）放大反而更剧烈"
    delta = f"，较 5 个数据点前 {vix - prev:+.1f}" if prev is not None else ""
    return dict(tag="VIX 恐慌指数", verdict=verdict, level=level,
                detail=f"VIX {vix:.2f}{delta}。{note}。")


def liquidity_block(d):
    """国内流动性：M2 与名义增长之差、M1 活化程度、社融、LPR 动向。"""
    core = (d.get("cn") or {}).get("core") or {}
    money, fin, gdp, cpi = core.get("money") or {}, core.get("financing") or {}, core.get("gdp") or {}, core.get("cpi") or {}
    m2, m1 = money.get("m2"), money.get("m1")
    if m2 is None:
        return dict(tag="国内流动性", verdict="本次未取到", level=1,
                    detail="M1/M2 数据缺失，无法判断。")
    # 名义增速近似 = 实际 GDP + CPI（缺省按 5% 估）
    nominal = None
    if gdp.get("real_yoy") is not None and cpi.get("yoy") is not None:
        nominal = gdp["real_yoy"] + cpi["yoy"]
    gap = (m2 - nominal) if nominal is not None else None
    if gap is not None and gap >= 2.5:
        verdict, level = "充裕", 1
        note = f"M2 高于名义增长约 {gap:.1f} 个百分点，宏观流动性宽松"
    elif gap is not None and gap >= 1:
        verdict, level = "中性偏宽", 1
        note = f"M2 略高于名义增长约 {gap:.1f} 个百分点，流动性合理充裕"
    else:
        verdict, level = "偏紧", 2
        note = "M2 未明显高于名义增长，流动性支撑有限"
    extra = []
    if m1 is not None:
        extra.append(f"M1 {m1:.1f}%" + ("（资金活化偏弱，向经营/投资转化不足）" if m1 < 5 else ""))
    if fin.get("size_yoy") is not None:
        sy = fin["size_yoy"]
        extra.append(f"社融存量同比 {sy:.1f}%" + ("（扩张偏慢）" if sy < 7.5 else ""))
    lpr = ((d.get("cn") or {}).get("lpr") or {})
    if lpr.get("lpr1y") is not None:
        moved = "" if lpr.get("lpr1y") == lpr.get("lpr1y_prev") else "（近期有调整）"
        extra.append(f"LPR 1Y {lpr['lpr1y']:.1f}%/5Y {lpr.get('lpr5y', 0):.1f}%{moved}，政策利率按兵不动")
    detail = "；".join(extra)
    return dict(tag="国内流动性", verdict=verdict, level=level,
                detail=f"{note}。{detail}。" if detail else f"{note}。")


def turnover_block(d):
    """A 股量能：两市成交额绝对水平 + westock 画像的量能判定。≥2 万亿显著放量。"""
    t = d.get("turnover") or {}
    total = t.get("total_yi") or (_num(t.get("total")) and _num(t.get("total")) / 1e8)
    if not total:
        return dict(tag="A 股量能", verdict="本次未取到", level=1,
                    detail="两市成交额数据缺失，无法判断。")
    if total >= 20000:
        verdict, level, note = "显著放量", 2, "成交 ≥2 万亿，情绪偏亢奋，注意冲高兑现节奏"
    elif total >= 15000:
        verdict, level, note = "活跃", 1, "成交 1.5–2 万亿，交投活跃、承接良好"
    elif total >= 10000:
        verdict, level, note = "常态", 0, "成交 1–1.5 万亿，属近期常态水平"
    else:
        verdict, level, note = "缩量", 1, "成交不足 1 万亿，观望情绪浓，反弹动能受限"
    ov = (d.get("market_overview") or {})
    dim = next((x for x in ov.get("dims") or [] if x.get("dim") == "成交量能"), None)
    extra = f"市场画像判定：{dim['status']}" if dim else ""
    return dict(tag="A 股量能", verdict=verdict, level=level,
                detail=f"两市成交额约 {total/10000:.2f} 万亿元（沪 {t.get('沪市_yi') or '—'}/深 {t.get('深市_yi') or '—'} 亿）。{note}。{extra}。")


def overview_block(d):
    """市场总览画像：westock 量化打分的关键维度。"""
    ov = d.get("market_overview") or {}
    dims = ov.get("dims") or []
    if not dims:
        return None
    keep = ("情绪指标", "个股宽度", "短期趋势方向", "估值水平")
    picked = [x for x in dims if x.get("dim") in keep]
    score = ov.get("score_adj") or ov.get("score_raw")
    head = f"westock 市场总评 {score}/25" if score else "westock 市场画像"
    detail = "；".join(f"{x['dim']}：{x['status']}" for x in picked)
    avg = sum(x.get("score", 0) for x in dims) / max(len(dims), 1)
    if avg >= 4:
        verdict, level = "偏热", 2
    elif avg >= 3:
        verdict, level = "中性", 1
    else:
        verdict, level = "偏冷", 1
    return dict(tag="市场画像", verdict=verdict, level=level,
                detail=f"{head}。{detail}。")


def market_read(d):
    """返回解读块列表（顺序：美债 → VIX → 流动性 → 量能 → 画像）。"""
    blocks = [bond_block(d), vix_block(d), liquidity_block(d), turnover_block(d)]
    ob = overview_block(d)
    if ob:
        blocks.append(ob)
    return blocks


def read_lines(d):
    """邮件摘要用的纯文本行。"""
    lines = []
    for b in market_read(d):
        mark = {0: "🟢", 1: "⚪", 2: "🟠", 3: "🔴"}.get(b["level"], "")
        lines.append(f"{mark} **{b['tag']}·{b['verdict']}**：{b['detail']}")
    return lines
