#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MACD 趋势判定模块。

westock 返回的 MACD 柱 = 2 × (DIF - DEA)。

判定维度：
  1. 金叉 / 死叉状态，以及距上次交叉多少个交易日
  2. DIF / DEA 相对零轴的位置（多头区 / 空头区）
  3. 柱状体的连续扩张 / 收敛方向（动能变化）
  4. 顶背离 / 底背离（价格与 DIF 的背离）
最终给出五档信号：强势 / 转强 / 震荡 / 走弱 / 弱势
"""


def _hist(bar):
    return bar["macd"]


def _has(bar):
    """该交易日 MACD 三项是否齐全（上市初期可能为 None）。"""
    return bar["dif"] is not None and bar["dea"] is not None and bar["macd"] is not None


def last_cross(series, lookback=40):
    """返回 (类型, 距今交易日数)。只看最近 lookback 根。"""
    seq = [b for b in series if _has(b)][-lookback:]
    for i in range(len(seq) - 1, 0, -1):
        prev, cur = seq[i - 1], seq[i]
        pd, cd = prev["dif"] - prev["dea"], cur["dif"] - cur["dea"]
        if pd <= 0 < cd:
            return ("golden", len(seq) - 1 - i)
        if pd >= 0 > cd:
            return ("dead", len(seq) - 1 - i)
    return (None, None)


def hist_streak(series, lookback=12):
    """柱状体连续扩张(+) / 收敛(-) 的根数（按柱值的绝对值方向判断）。"""
    seq = [b for b in series if _has(b)][-lookback:]
    if len(seq) < 2:
        return 0, 0.0
    vals = [_hist(b) for b in seq]
    sign = 1 if vals[-1] > 0 else -1
    strength = [abs(v) * sign for v in vals]  # 转正时向上为正，转负时向下为正
    n = 0
    for i in range(len(strength) - 1, 0, -1):
        if strength[i] > strength[i - 1]:
            n += 1
        else:
            break
    return n, (strength[-1] - strength[-2])


def divergence(series, lookback=45):
    """
    极简背离识别。
    顶背离：价格创区间新高而 DIF 未同步创新高 → 动能衰竭
    底背离：价格创区间新低而 DIF 未同步创新低 → 抛压衰竭
    """
    seq = [b for b in series if _has(b)][-lookback:]
    if len(seq) < 12:
        return None
    hi_idx = max(range(len(seq)), key=lambda i: seq[i]["close"])
    dif_hi = seq[hi_idx]["dif"]
    recent_hi = max(seq[-5:], key=lambda b: b["dif"])["dif"]
    lo_idx = min(range(len(seq)), key=lambda i: seq[i]["close"])
    dif_lo = seq[lo_idx]["dif"]
    recent_lo = min(seq[-5:], key=lambda b: b["dif"])["dif"]
    if hi_idx >= len(seq) - 8 and recent_hi < dif_hi:
        return "top"
    if lo_idx >= len(seq) - 8 and recent_lo > dif_lo:
        return "bottom"
    return None


def analyze(series, lookback=40):
    seq = [b for b in series if _has(b)]
    if len(seq) < 3:
        return dict(ok=False, reason="MACD 数据不足（次新股或停牌）")

    cur = seq[-1]
    prev = seq[-2]
    dif, dea, hist = cur["dif"], cur["dea"], cur["macd"]
    above_cross = dif > dea
    above_zero = dif > 0 and dea > 0
    below_zero = dif < 0 and dea < 0
    cross_type, cross_ago = last_cross(series, lookback)
    streak, delta = hist_streak(series)
    div = divergence(series)
    hist_now, hist_prev = hist, prev["macd"]
    hist_expanding = abs(hist_now) > abs(hist_prev)
    # 过去 6 根柱状体的斜率
    recent = [_hist(b) for b in seq[-6:]]
    slope = recent[-1] - recent[0]

    # ---- 五档信号判定
    if above_cross and above_zero and hist_expanding and hist_now > 0:
        sig, label = "strong", "强势上行"
        cls = "up"
    elif above_cross and above_zero:
        sig, label = "hold", "多头蓄势"
        cls = "flat"
    elif above_cross:
        sig, label = "turn", "低位转强"
        cls = "up"
    elif above_zero:
        sig, label = "weak", "多头区走弱"
        cls = "down"
    else:
        sig, label = "bear", "空头趋势"
        cls = "down"

    if div == "top" and sig in ("strong", "hold"):
        label = "顶背离预警"
        sig = "weak"
        cls = "down"

    # ---- 生成描述
    pos = "零轴上方" if above_zero else ("零轴下方" if below_zero else "零轴附近")
    parts = [f"DIF {dif:.2f} / DEA {dea:.2f} / 柱 {hist:+.2f}，位于{pos}"]
    if cross_type == "golden":
        parts.append(f"{cross_ago} 个交易日前金叉")
    elif cross_type == "dead":
        parts.append(f"{cross_ago} 个交易日前死叉")
    else:
        parts.append("近期未发生交叉")
    if streak >= 2:
        direction = "持续放大" if hist_now > 0 else "绿柱持续拉长"
        parts.append(f"柱状体{direction}已连续 {streak} 日")
    elif streak == 0 and hist_expanding is False:
        parts.append("柱状体动能开始收敛")
    if div == "top":
        parts.append("⚠️ 价格创阶段新高但 DIF 未同步走高，出现顶背离")
    if div == "bottom":
        parts.append("价格创阶段新低但 DIF 未同步走低，出现底背离")

    # ---- 交易触发条件
    if sig == "strong":
        trigger = "持有。柱状体由放大转为连续 2 日收敛，且 DIF 拐头向下时开始减仓。"
    elif sig == "turn":
        trigger = "可持有观察。反弹若止步于零轴下方并形成死叉，视为反弹结束。"
    elif sig == "hold":
        trigger = "持有。跌破零轴或柱状体连续收敛 3 日需减仓。"
    elif sig == "weak":
        trigger = "⚠️ 已走弱，建议分批减仓；若出现死叉且柱转绿，清仓离场。"
    else:
        trigger = "⚠️ 空头趋势中，不建议补仓；等待零轴下方金叉且柱状体转正再考虑。"

    # 跨标的归一化：柱状体相对价格（基点），便于低价 ETF 与高价个股横向比较
    hist_bp = hist / cur["close"] * 10000 if cur["close"] else None
    # 均线排列
    ma_bull = None
    if cur["ma5"] and cur["ma10"] and cur["ma20"]:
        ma_bull = cur["ma5"] > cur["ma10"] > cur["ma20"]

    return dict(
        ok=True, date=cur["date"], close=cur["close"],
        dif=dif, dea=dea, hist=hist, hist_prev=hist_prev,
        above_cross=above_cross, above_zero=above_zero, below_zero=below_zero,
        cross_type=cross_type, cross_ago=cross_ago,
        streak=streak, slope=slope, divergence=div,
        ma5=cur["ma5"], ma10=cur["ma10"], ma20=cur["ma20"], ma60=cur["ma60"],
        ma_bull=ma_bull, hist_bp=hist_bp,
        rsi6=cur.get("rsi6"), rsi12=cur.get("rsi12"),
        signal=sig, label=label, cls=cls,
        desc="，".join(parts) + "。",
        trigger=trigger,
    )


def order_label(sig):
    return {"strong": 0, "turn": 1, "hold": 2, "weak": 3, "bear": 4}.get(sig, 9)
