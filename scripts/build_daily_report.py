#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观 / 微观监测日报渲染器。

输入：
  data/daily_<YYYYMMDD>.json   fetch_daily.py 产出
  data/technical.json          fetch_technical.py 产出
输出：
  reports/daily-<YYYYMMDD>.html
  data/state_<YYYYMMDD>.json   （MACD 状态快照，供下次差分）

核心原则：**差分优先**。静态数值天天重复没意义，
只报告「今天相比上次发生了变化的东西」。

用法：
    python3 scripts/build_daily_report.py --date 2026-09-14 --mode evening
"""

import argparse
import glob
import json
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macd as M  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RED = "#C62828"
GREEN = "#2E7D32"
INK = "#1F2933"
SUB = "#6B7280"
LINE = "#E5E7EB"
BG = "#F7F8FA"
ACCENT = "#185FA5"
WARN = "#C2410C"
MACD_COLOR = {"up": RED, "flat": "#B45309", "down": GREEN}
MACD_BG = {"up": "#FEF2F2", "flat": "#FFFBEB", "down": "#F0FDF4"}
SIGNAL_ORDER = {"strong": 0, "turn": 1, "hold": 2, "weak": 3, "bear": 4}

# 场内基金 / ETF：不计入「个股」统计
FUND_CODES = {"sz159501", "sh588080", "sh506002", "hk03431"}


def num(v, digits=2):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def col(v):
    """数值涨跌配色：涨红跌绿。"""
    x = num(v)
    if x is None:
        return SUB
    return RED if x > 0 else (GREEN if x < 0 else SUB)


def pct(v, digits=2):
    x = num(v)
    if x is None:
        return "—"
    return f"{x:+.{digits}f}%"


def dash(v):
    return "—" if v in (None, "", "-") else str(v)


def load_state(run_date):
    """加载上次的状态快照用于差分。"""
    files = sorted(glob.glob(os.path.join(ROOT, "data", "state_*.json")))
    prev = None
    for p in files:
        try:
            with open(p, encoding="utf-8") as fh:
                s = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        if s.get("date") == run_date:
            continue
        prev = s
    return prev


def save_state(run_date, tech):
    cur = {"date": run_date, "stocks": {}}
    for group in ("holdings", "watch", "hedges"):
        for code, v in (tech.get(group) or {}).items():
            r = M.analyze(v["series"])
            if not r.get("ok"):
                continue
            cur["stocks"][code] = dict(
                name=v["name"], group=group, signal=r["signal"], label=r["label"],
                cross=r["cross_type"], cross_ago=r["cross_ago"], close=r["close"],
                hist=r["hist"], hist_bp=r["hist_bp"], streak=r["streak"],
            )
    path = os.path.join(ROOT, "data", f"state_{run_date.replace('-','')}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cur, fh, ensure_ascii=False, indent=1)
    return cur, path


def diff_states(cur, prev):
    """返回变化列表：信号档位变化 / 新交叉 / 新增或移除标的。"""
    if not prev:
        return dict(first=True, changes=[], added=[], removed=[])
    pc, cc = prev.get("stocks", {}), cur["stocks"]
    changes, added, removed = [], [], []
    for code, c in cc.items():
        p = pc.get(code)
        if p is None:
            added.append((code, c))
            continue
        if p["signal"] != c["signal"]:
            changes.append((code, p, c, "signal"))
        elif p["cross"] != c["cross"] or (c["cross"] and abs((c["cross_ago"] or 0) - (p["cross_ago"] or 0)) > 3
                                          and c["cross_ago"] == 0):
            changes.append((code, p, c, "cross"))
    for code, p in pc.items():
        if code not in cc:
            removed.append((code, p))
    return dict(first=False, changes=changes, added=added, removed=removed)


CSS = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;color:{INK};
     background:#fff;line-height:1.65;padding:30px 18px}}
.wrap{{max-width:1080px;margin:0 auto}}
h1{{font-size:23px;font-weight:600;margin-bottom:4px}}
h2{{font-size:17px;font-weight:600;margin:30px 0 12px;padding-left:10px;border-left:3px solid {ACCENT}}}
h3{{font-size:14.5px;font-weight:600;margin:18px 0 8px;color:#374151}}
.meta{{color:{SUB};font-size:12.5px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:10px;margin:12px 0}}
.tile{{background:{BG};border:1px solid {LINE};border-radius:10px;padding:12px 14px}}
.tile .l{{font-size:11.5px;color:{SUB}}}
.tile .v{{font-size:19px;font-weight:600;margin-top:2px}}
.tile .s{{font-size:11.5px;color:{SUB};margin-top:1px}}
table{{width:100%;border-collapse:collapse;font-size:12.8px;margin-top:6px}}
th{{text-align:right;padding:7px 7px;border-bottom:2px solid {LINE};color:{SUB};font-weight:500;font-size:11.5px;white-space:nowrap}}
th:first-child,td:first-child{{text-align:left}}
td{{text-align:right;padding:7px 7px;border-bottom:1px solid {LINE}}}
tbody tr:hover{{background:{BG}}}
.box{{border:1px solid {LINE};border-radius:10px;padding:12px 15px;margin:10px 0;background:#FCFCFD;font-size:13px}}
.box b{{color:{WARN}}}
.chg{{border-left:3px solid {RED};background:#FFF8F8;padding:9px 12px;border-radius:6px;margin:6px 0;font-size:13px}}
.chg.g{{border-left-color:{GREEN};background:#F7FCF8}}
.chg.n{{border-left-color:{ACCENT};background:#F8FAFF}}
.miss{{color:{SUB};font-size:12.5px;font-style:italic}}
.foot{{margin-top:32px;padding-top:14px;border-top:1px solid {LINE};font-size:11.5px;color:{SUB}}}
@media(max-width:640px){{body{{padding:14px 8px}}th,td{{font-size:11.5px;padding:5px 3px}}}}
"""


def tile(label, value, sub="", color=None):
    c = f" style='color:{color}'" if color else ""
    return f"<div class='tile'><div class='l'>{label}</div><div class='v'{c}>{value}</div><div class='s'>{sub}</div></div>"


def q_row(row, code_name):
    """渲染一行行情（标准化后的 row）。"""
    if not row:
        return f"<tr><td>{code_name}</td><td colspan='3' class='miss'>本次未取到</td></tr>"
    return (f"<tr><td>{row.get('name') or code_name}</td>"
            f"<td>{dash(row.get('price'))}</td>"
            f"<td style='color:{col(row.get('chg'))}'>{pct(row.get('chg'))}</td>"
            f"<td style='color:{SUB};font-size:11.5px'>{dash(row.get('code'))}</td></tr>")


# ------------------------------------------------------------------ 各板块
def sec_overview(d):
    out = ["<h2>一、市场速览</h2>", "<div class='grid'>"]
    idx = d.get("index") or {}
    names = (idx.get("names") or {})
    for grp, label in (("cn", "A 股"), ("hk", "港股")):
        rows = idx.get(grp) or {}
        for code, row in rows.items():
            out.append(tile(f"{label} · {row.get('name') or names.get(code, code)}",
                            dash(row.get("price")), pct(row.get("chg")), col(row.get("chg"))))
    out.append("</div>")
    # 美股三大指数来自宏观指标（收盘口径）
    ki = (d.get("us") or {}).get("key_index") or {}
    out.append("<h3>美股三大指数（收盘口径）</h3><table><thead><tr><th>指数</th><th>最新</th><th>区间起点</th><th>区间涨跌</th></tr></thead><tbody>")
    mapping = [("SPX", "标普500"), ("COMP_NASDAQ", "纳斯达克"), ("DJI", "道琼斯")]
    for key, cn in mapping:
        seq = ki.get(key) or []
        if len(seq) < 2:
            out.append(f"<tr><td>{cn}</td><td colspan='3' class='miss'>本次未取到</td></tr>")
            continue
        latest = float(seq[0][1])
        old = float(seq[-1][1])
        span = len(seq)
        out.append(f"<tr><td>{cn}</td><td>{latest:,.2f}</td><td>{old:,.2f}（{span} 日前）</td>"
                   f"<td style='color:{col(latest-old)}'>{pct((latest/old-1)*100)}</td></tr>")
    out.append("</tbody></table>")
    out.append("<div class='miss'>美股三大指数取自宏观指标接口，为已收盘日数据；"
               "A 股 / 港股为盘中 T+0 实时价，两者时点与口径不同，不要直接横向比较当日涨跌。</div>")
    return "".join(out)


def sec_us_macro(d):
    us = d.get("us") or {}
    out = ["<h2>二、海外宏观</h2>"]
    y = us.get("yield") or {}
    out.append("<h3>美债收益率与期限利差</h3><div class='grid'>")
    out.append(tile("美债 10Y", f"{y.get('y10')}%" if y.get("y10") is not None else "—", dash(y.get("date"))))
    out.append(tile("美债 2Y", f"{y.get('y2')}%" if y.get("y2") is not None else "—", "政策利率敏感端"))
    sp = y.get("spread")
    out.append(tile("10Y-2Y 利差", f"{sp:.0f} bp" if sp is not None else "—",
                    "倒挂=衰退预期" if (sp is not None and sp < 0) else "已转正",
                    RED if (sp is not None and sp < 0) else None))
    out.append(tile("曲线形态", dash(y.get("form")), "熊平/牛陡等形态标签"))
    out.append("</div>")
    # VIX / 美元指数
    out.append("<h3>风险偏好</h3><div class='grid'>")
    vix = (us.get("vix") or {}).get("VIX") or []
    if vix:
        v_now, v_old = float(vix[0][1]), (float(vix[-1][1]) if len(vix) > 1 else None)
        out.append(tile("VIX", f"{v_now:.2f}", f"{len(vix)} 日前 {v_old:.2f}" if v_old else dash(vix[0][0]),
                        GREEN if v_old and v_now < v_old else RED))
    else:
        out.append(tile("VIX", "—", "本次未取到"))
    dxy_m = (us.get("usd_index") or {}).get("DXY") or []
    fx = d.get("fx") or {}
    dxy_live = fx.get("fxDINIW")
    if dxy_live:
        out.append(tile("美元指数", dash(dxy_live.get("price")), pct(dxy_live.get("chg")), col(dxy_live.get("chg"))))
    elif dxy_m:
        out.append(tile("美元指数", f"{float(dxy_m[0][1]):.2f}", dash(dxy_m[0][0])))
    for code, label in (("fxUSDCNY", "美元 / 人民币"), ("fxCNH", "离岸人民币")):
        r = fx.get(code)
        if r:
            out.append(tile(label, dash(r.get("price")), pct(r.get("chg")), col(r.get("chg"))))
    out.append("</div>")
    # 美国宏观数据实际 vs 预期
    ev = us.get("events") or []
    ev = [e for e in ev if e.get("actual") not in ("-", "", "未公布")]
    if ev:
        out.append("<h3>美国宏观数据（最近已公布）</h3><table><thead><tr>"
                   "<th>指标</th><th>公布日</th><th>实际</th><th>预期</th><th>前值</th><th>差异判断</th></tr></thead><tbody>")
        for e in ev[:12]:
            a, fo, pr = num(e.get("actual")), num(e.get("forecast")), num(e.get("former"))
            judge, jc = "—", SUB
            if a is not None and fo is not None:
                judge, jc = ("超预期" if a > fo else ("不及预期" if a < fo else "符合预期")), col(1 if a > fo else (-1 if a < fo else 0))
            out.append(f"<tr><td>{e.get('name')}</td><td>{dash(e.get('date'))}</td>"
                       f"<td>{dash(e.get('actual'))}</td><td>{dash(e.get('forecast'))}</td>"
                       f"<td>{dash(e.get('former'))}</td>"
                       f"<td style='color:{jc}'>{judge}</td></tr>")
        out.append("</tbody></table>")
    else:
        out.append("<div class='miss'>近期美国宏观数据本次未取到（接口返回为空）。</div>")
    return "".join(out)


def sec_cn_macro(d):
    cn = d.get("cn") or {}
    core = cn.get("core") or {}
    out = ["<h2>三、国内宏观</h2>", "<div class='grid'>"]
    lpr = cn.get("lpr") or {}
    out.append(tile("LPR 1 年期", f"{lpr.get('lpr1y')}%" if lpr.get("lpr1y") is not None else "—",
                    f"公布日 {dash(lpr.get('lpr1y_date'))}"))
    out.append(tile("LPR 5 年期", f"{lpr.get('lpr5y')}%" if lpr.get("lpr5y") is not None else "—",
                    f"公布日 {dash(lpr.get('lpr5y_date'))}"))
    cpi = core.get("cpi") or {}
    out.append(tile("CPI 同比", f"{cpi.get('yoy')}%" if cpi.get("yoy") is not None else "—",
                    f"核心 {cpi.get('core')}%" if cpi.get("core") is not None else "", col(cpi.get("yoy"))))
    pmi = core.get("pmi") or {}
    pmv = pmi.get("manu")
    out.append(tile("制造业 PMI", f"{pmv}" if pmv is not None else "—",
                    "荣枯线下" if (pmv is not None and pmv < 50) else "扩张区间",
                    GREEN if (pmv is not None and pmv < 50) else RED))
    money = core.get("money") or {}
    out.append(tile("M2 同比", f"{money.get('m2')}%" if money.get("m2") is not None else "—",
                    f"M1 {money.get('m1')}%" if money.get("m1") is not None else ""))
    fin = core.get("financing") or {}
    out.append(tile("社融存量同比", f"{fin.get('size_yoy')}%" if fin.get("size_yoy") is not None else "—",
                    f"政府债 {fin.get('gov_bond_yoy')}%" if fin.get("gov_bond_yoy") is not None else ""))
    gdpv = (core.get("gdp") or {}).get("real_yoy")
    out.append(tile("GDP 当季同比", f"{gdpv}%" if gdpv is not None else "—", "不变价累计口径参考"))
    res = core.get("reserve") or {}
    if res.get("gold") is not None:
        out.append(tile("央行黄金储备", f"{res.get('gold'):,.0f} 盎司" if isinstance(res.get("gold"), (int, float)) else dash(res.get("gold")),
                        f"截至 {dash(res.get('end'))}"))
    out.append("</div>")
    re_ = core.get("re") or {}
    if re_:
        out.append("<div class='box'>地产链条仍在收缩："
                   f"新开工累计同比 {dash(re_.get('new_yoy'))}%，房地产开发投资累计同比 {dash(re_.get('invest_yoy'))}%。"
                   "这组数据决定了「红利 + 银行」的对冲逻辑何时具备基本面支撑——在地产投资转正之前，"
                   "银行股更多是防御属性而非周期属性。</div>")
    return "".join(out)


def sec_ai(d, tech):
    out = ["<h2>四、AI 产业链</h2>", "<h3>美股 AI 核心股（隔夜收盘）</h3>",
           "<table><thead><tr><th>标的</th><th>代码</th><th>价格</th><th>涨跌</th></tr></thead><tbody>"]
    ai_us = d.get("ai_us") or {}
    for code, row in ai_us.items():
        out.append(q_row(row, (d.get("ai_us_names") or {}).get(code, code)))
    out.append("</tbody></table>")
    out.append("<h3>A 股 AI 链代表股</h3><table><thead><tr>"
               "<th>标的</th><th>代码</th><th>价格</th><th>涨跌</th></tr></thead><tbody>")
    for code, row in (d.get("ai_a") or {}).items():
        out.append(q_row(row, (d.get("ai_a_names") or {}).get(code, code)))
    out.append("</tbody></table>")
    # 相关概念板块
    sec_data = d.get("sector") or {}
    kw = (d.get("sector_kw") or {}).get("ai", [])
    rows = [s for s in (sec_data.get("changePct") or []) if any(k in s["name"] for k in kw)][:12]
    if rows:
        out.append("<h3>相关概念板块表现（涨跌幅前 12）</h3><table><thead><tr>"
                   "<th>板块</th><th>涨跌</th><th>主力净流入(万)</th><th>领涨股</th></tr></thead><tbody>")
        for s in rows:
            out.append(f"<tr><td>{s['name']}</td>"
                       f"<td style='color:{col(s['pct'])}'>{pct(s['pct'])}</td>"
                       f"<td style='color:{col(s['inflow'])}'>{s['inflow']:,.0f}</td>"
                       f"<td style='font-size:11.5px;color:{SUB}'>{dash(s['leader'])}</td></tr>")
        out.append("</tbody></table>")
    # 与你持仓的关系
    hold = tech.get("holdings") or {}
    hres = []
    for code, v in hold.items():
        if code in FUND_CODES:
            continue
        r = M.analyze(v["series"])
        if r.get("ok"):
            hres.append((v["name"], r))
    bear = [x for x in hres if x[1]["signal"] == "bear"]
    if hres:
        out.append("<div class='box'>与你持仓的关系："
                   f"持仓的 <b>{len(hres)} 只个股</b>中有 <b>{len(bear)} 只处于 MACD 空头趋势</b>"
                   f"（{'、'.join(x[0] for x in bear) if bear else '无'}）。"
                   "这是在上周的持仓报告里就识别出的结论——本轮 AI 算力链的调整是趋势级别而非单日波动，"
                   "因此在新增 AI 相关仓位之前，先观察这条链的板块资金是否回流。</div>")
    return "".join(out)


def sec_gold(d):
    out = ["<h2>五、大宗 · 黄金</h2>", "<div class='grid'>"]
    for code, row in (d.get("gold") or {}).items():
        if row:
            unit = "美元/盎司" if code == "fuGC" else "元"
            out.append(tile(f"{row.get('name') or code}", dash(row.get("price")),
                            f"{pct(row.get('chg'))} · {unit}", col(row.get("chg"))))
    out.append("</div>")
    out.append("<h3>A 股黄金股</h3><table><thead><tr><th>标的</th><th>代码</th><th>价格</th><th>涨跌</th></tr></thead><tbody>")
    for code, row in (d.get("gold_stock") or {}).items():
        out.append(q_row(row, (d.get("gold_stock_names") or {}).get(code, code)))
    out.append("</tbody></table>")
    kw = (d.get("sector_kw") or {}).get("gold", [])
    rows = [s for s in ((d.get("sector") or {}).get("changePct") or []) if any(k in s["name"] for k in kw)][:6]
    if rows:
        out.append("<table><thead><tr><th>黄金相关板块</th><th>涨跌</th><th>主力净流入(万)</th></tr></thead><tbody>")
        for s in rows:
            out.append(f"<tr><td>{s['name']}</td><td style='color:{col(s['pct'])}'>{pct(s['pct'])}</td>"
                       f"<td style='color:{col(s['inflow'])}'>{s['inflow']:,.0f}</td></tr>")
        out.append("</tbody></table>")
    return "".join(out)


def sec_diff(diff, cur, tracked=None):
    tracked = tracked or {}
    out = ["<h2>六、今日变化（相对上次运行）</h2>"]
    if diff.get("first"):
        out.append("<div class='box'>首次运行，尚未建立对比基线。明日开始将只列出<b>新发生的变化</b>，"
                   "不再重复罗列静态数据。</div>")
    else:
        ch = diff.get("changes") or []
        if not ch:
            out.append("<div class='box'>持仓与观察池的 MACD 状态<b>今日无变化</b>，"
                       "没有出现新的金叉 / 死叉，也没有标的跨档跳跃。</div>")
        else:
            out.append(f"<div class='box'>今日共有 <b>{len(ch)} 处</b>技术状态变化：</div>")
            for item in ch:
                code, p, c = item[0], item[1], item[2]
                kind = item[3]
                q = tracked.get(code) or {}
                px_txt = f"{q.get('price')}" if q.get("price") else f"{c['close']:,.2f}"
                if q.get("chg") not in (None, "", "-"):
                    px_txt += f" <span style='color:{col(q.get('chg'))}'>{pct(q.get('chg'))}</span>"
                if kind == "signal":
                    worsened = SIGNAL_ORDER.get(c["signal"], 9) > SIGNAL_ORDER.get(p["signal"], 9)
                    cls = "chg" if worsened else "chg g"
                    mark = "⚠ 恶化" if worsened else "✅ 改善"
                    out.append("<div class='" + cls + "'><b>" + c["name"] + "</b>（" + code + "）　" + mark + "　"
                               + p["label"] + " → <b>" + c["label"] + "</b>　现价 " + px_txt
                               + "　柱 " + f"{c['hist']:+.2f}" + "（" + f"{c['hist_bp']:+.0f}" + "bp）</div>")
                else:
                    golden = c["cross"] == "golden"
                    cls = "chg g" if golden else "chg"
                    txt = "MACD 金叉" if golden else "MACD 死叉"
                    out.append("<div class='" + cls + "'><b>" + c["name"] + "</b>（" + code + "）　" + txt + "　"
                               + f"{c['cross_ago']} 日前　状态 " + c["label"] + "　现价 " + px_txt + "</div>")
        for code, c in (diff.get("added") or []):
            out.append(f"<div class='chg n'><b>{c['name']}</b>（{code}）　新加入跟踪　状态 {c['label']}</div>")
        for code, p in (diff.get("removed") or []):
            out.append(f"<div class='chg'><b>{p['name']}</b>（{code}）　已移出跟踪</div>")
    # 当前状态总表
    out.append("<h3>当前跟踪状态一览</h3>")
    out.append("<div class='miss'>「现价 / 当日」为本次采集的实时行情；"
               "「柱(bp)」与「最近交叉」来自上一交易日收盘的技术指标，两者口径不同。</div>")
    out.append("<table><thead><tr>"
               "<th>标的</th><th>分组</th><th>状态</th><th>现价</th><th>当日</th><th>柱(bp)</th><th>最近交叉</th></tr></thead><tbody>")
    GL = {"holdings": "持仓", "watch": "观察池", "hedges": "对冲篮子"}
    for code, c in sorted(cur["stocks"].items(), key=lambda kv: (SIGNAL_ORDER.get(kv[1]["signal"], 9))):
        cross = {"golden": f"金叉 {c['cross_ago']} 日前",
                 "dead": f"死叉 {c['cross_ago']} 日前"}.get(c["cross"], "无交叉")
        if c["signal"] in ("strong", "turn"):
            cls = "up"
        elif c["signal"] == "hold":
            cls = "flat"
        else:
            cls = "down"
        q = tracked.get(code) or {}
        px, chg = q.get("price"), q.get("chg")
        px_txt, chg_txt = (px if px else "—"), (pct(chg) if chg not in (None, "", "-") else "—")
        out.append("<tr><td>" + c["name"] + "</td>"
                   + "<td style='color:" + SUB + ";font-size:11.5px'>" + GL.get(c["group"], c["group"]) + "</td>"
                   + "<td><span style='display:inline-block;font-size:11.5px;padding:1px 8px;border-radius:20px;"
                   + "background:" + MACD_BG[cls] + ";color:" + MACD_COLOR[cls] + "'>" + c["label"] + "</span></td>"
                   + "<td>" + px_txt + "</td>"
                   + "<td style='color:" + col(chg) + "'>" + chg_txt + "</td>"
                   + "<td style='color:" + col(c["hist_bp"]) + "'>" + f"{c['hist_bp']:+.0f}" + "</td>"
                   + "<td style='font-size:11.5px'>" + cross + "</td></tr>")
    out.append("</tbody></table>")
    return "".join(out)


def sec_calendar(d):
    out = ["<h2>八、重大事件日历</h2>", "<h3>美联储 FOMC 决议</h3>"]
    fomc = d.get("fomc") or {}
    nxt = fomc.get("next")
    today_s = fomc.get("today") or ""
    if not nxt:
        out.append("<div class='miss'>本次未取到 FOMC 日历（源：美联储官网）。</div>")
    else:
        try:
            days = (date.fromisoformat(nxt["decision_us"]) - date.fromisoformat(today_s)).days
        except Exception:  # noqa: BLE001
            days = None
        dcn = nxt["decision_cn"]
        urgent = days is not None and days <= 3
        tag = "含经济预测 + 点阵图 + 发布会" if nxt.get("sep") else "仅决议声明"
        out.append("<div class='grid'>")
        out.append(tile("下次决议（美东）", nxt["decision_us"], f"会期 {nxt['dates']}"))
        out.append(tile("北京时间", dcn.split()[1], dcn.split()[0],
                        WARN if urgent else None))
        out.append(tile("距今", f"{days} 天" if days is not None else "—",
                        "本周内落地" if urgent else ""))
        out.append(tile("会议规格", "季度会议" if nxt.get("sep") else "常规会议", tag))
        out.append("</div>")
        nm = fomc.get("next_minutes")
        if urgent:
            out.append("<div class='box'><b>临近提示</b>：决议将在 "
                       f"{dcn}（北京时间）公布，{tag}。"
                       "决议前后 24 小时风险资产波动通常放大，持仓中 AI 算力链属于高 Beta 方向，"
                       "如需调整仓位建议在决议前完成，而不是等结果出来再追。"
                       + (f"纪要将于 {nm['minutes_cn']}（北京时间）公布。" if nm else "")
                       + "</div>")

        rest = [m for m in (fomc.get("meetings") or [])
                if m["decision_us"] > nxt["decision_us"]][:5]
        if rest:
            out.append("<table><thead><tr><th>会期（美东）</th><th>北京时间</th>"
                       "<th>规格</th><th>纪要（北京时间）</th></tr></thead><tbody>")
            for m in rest:
                out.append(f"<tr><td>{m['dates']}（{m['year']}）</td>"
                           f"<td>{m['decision_cn']}</td>"
                           f"<td>{'季度会议（点阵图）' if m['sep'] else '常规会议'}</td>"
                           f"<td>{m['minutes_cn']}</td></tr>")
            out.append("</tbody></table>")
        out.append(f"<div class='box' style='font-size:12px'>源：{fomc.get('source','')}"
                   f"（美联储官网，权威日历）· 抓取于 {dash(fomc.get('fetched_at'))}。"
                   "美东 14:00 公布 → 北京次日 02:00（夏令时）/ 03:00（冬令时）。</div>")

    # 金十：央行利率 + 大事日历
    j = d.get("jin10") or {}
    banks = j.get("banks") or []
    out.append("<h3>各国 / 地区央行政策利率<span style='font-weight:400;color:"
               f"{SUB};font-size:12px'>　源：金十数据</span></h3>")
    if banks:
        out.append("<table><thead><tr><th>央行</th><th>当前利率</th><th>最近变动</th></tr></thead><tbody>")
        for b in banks:
            out.append(f"<tr><td>{b['bank']}</td><td>{b['rate']}</td>"
                       f"<td style='font-size:11.5px;color:{SUB}'>{b['changed']}</td></tr>")
        out.append("</tbody></table>")
    else:
        out.append("<div class='miss'>本次未取到央行利率表。</div>")

    evs = j.get("events") or []
    if evs:
        out.append(f"<h3>金十「大事」事件<span style='font-weight:400;color:{SUB};font-size:12px'>"
                   f"　共 {len(evs)} 条，含今日与未来 5 天</span></h3>")
        out.append("<table><thead><tr><th>日期</th><th>时间</th>"
                   "<th>地区</th><th>事件</th></tr></thead><tbody>")
        for e in evs:
            when = e.get("time") or ""
            if when == "待定":
                when = "<span style='color:" + SUB + "'>待定</span>"
            out.append(f"<tr><td>{e.get('date','')}</td><td>{when}</td>"
                       f"<td>{e.get('area') or e.get('country') or ''}</td>"
                       f"<td style='text-align:left'>{e.get('title') or e.get('name') or ''}</td></tr>")
        out.append("</tbody></table>")
    elif j.get("need_login"):
        out.append("<div class='box'>金十日历的「大事」明细在<b>登录墙</b>之后，"
                   "未登录状态下取不到事件列表（上表央行利率为公开数据，可正常获取）。"
                   "如需每天自动带出「大事」，需要用浏览器登录一次金十账号并保存登录态。</div>")

    # 接口返回的宏观事件
    cal = d.get("calendar") or []
    out.append("<h3>其他宏观事件</h3>")
    if not cal:
        out.append("<div class='miss'>本次未取到其他未来事件日历（数据接口仅返回能源类周度数据）。</div>")
    else:
        out.append("<table><thead><tr><th>日期</th><th>地区</th><th>事件</th><th>时间</th></tr></thead><tbody>")
        for e in cal:
            s = e["date"]
            if len(s) == 8:
                s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
            out.append(f"<tr><td>{s}</td><td style='text-align:left'>{dash(e.get('area'))}</td>"
                       f"<td style='text-align:left'>{dash(e.get('name'))}</td>"
                       f"<td>{dash(e.get('time'))}</td></tr>")
        out.append("</tbody></table>")
    return "".join(out)


PLATFORM_CN = {"douyin": "抖音", "xhs": "小红书", "weibo": "微博",
               "xueqiu": "雪球", "wechat": "微信公众号"}


def sec_social(social):
    """关注博主 T-1 更新摘要。抓不到的平台明确标注，不静默跳过。"""
    out = ["<h2>七、关注博主 · T-1 更新</h2>"]
    if not social or not social.get("creators"):
        out.append("<div class='miss'>本次未取到社媒数据（脚本未运行或浏览器登录态失效）。</div>")
        return "".join(out)

    win = social.get("window") or []
    out.append(f"<div class='meta'>统计窗口 {'、'.join(win)}　·　"
               f"共 {len(social['creators'])} 位博主</div>")

    by_plat = {}
    for c in social["creators"]:
        by_plat.setdefault(c.get("platform", "?"), []).append(c)

    for plat in ["douyin", "xhs", "weibo", "xueqiu", "wechat"]:
        group = by_plat.get(plat)
        if not group:
            continue
        out.append(f"<h3>{PLATFORM_CN.get(plat, plat)}</h3>")
        out.append("<table><thead><tr><th>博主</th><th>状态</th>"
                   "<th style='text-align:left'>T-1 更新内容</th></tr></thead><tbody>")
        for c in group:
            nick = c.get("nickname") or "(未取到昵称)"
            uid = c.get("platform_uid", "")
            renamed = c.get("renamed")
            # 公众号只有名字没有 ID，uid 与昵称相同时不再重复显示
            uid_disp = "" if (uid and str(uid) == str(nick)) else uid
            name_cell = "<b>{}</b>".format(nick)
            if uid_disp:
                name_cell += f"　<span style='color:{SUB};font-size:11.5px'>{uid_disp}</span>"
            if renamed:
                name_cell += (f"<br><span style='color:{WARN};font-size:11.5px'>"
                              f"⚠ 已改名：{renamed} → {nick}</span>")
            home = c.get("home_url")
            if home:
                name_cell = f"<a href='{home}' style='color:{ACCENT};text-decoration:none'>{name_cell}</a>"

            st = c.get("status")
            posts = c.get("posts_window") or []
            if st != "ok":
                reason = {"login_required": "需要登录态", "not_found": "未找到该账号",
                          "error": "抓取异常", "no_posts": "未解析出内容"}.get(st, st)
                out.append(f"<tr><td>{name_cell}</td>"
                           f"<td style='color:{WARN};font-size:12px'>{reason}</td>"
                           f"<td style='text-align:left;color:{SUB}'>{c.get('note') or '—'}</td></tr>")
                continue

            if not posts:
                # 取有明确日期的最新一条（置顶帖往往很旧，排序后自然靠后）
                dated = [p for p in (c.get("posts_all") or []) if p.get("published")]
                dated.sort(key=lambda p: p["published"], reverse=True)
                latest = dated[0] if dated else {}
                last = latest.get("published")
                tail = f"最近一条 {last}：{(latest.get('title') or '')[:60]}" if last \
                    else "最近更新时间未取到（该平台未返回发布时间）"
                out.append(f"<tr><td>{name_cell}</td>"
                           f"<td style='color:{SUB};font-size:12px'>无更新</td>"
                           f"<td style='text-align:left;color:{SUB}'>{tail}</td></tr>")
                continue

            parts = []
            for p in posts:
                parts.append(f"<div style='margin:2px 0'>· {p.get('published') or '?'}　"
                             f"<a href='{p.get('url') or '#'}' style='color:{INK};text-decoration:none'>"
                             f"{(p.get('title') or '(无标题)')[:80]}</a></div>")
                s = (p.get("summary") or "").strip()
                if s:
                    parts.append(f"<div style='margin:1px 0 6px 10px;font-size:12px;color:{SUB};"
                                 f"line-height:1.5'>{s[:170]}{'…' if len(s) > 170 else ''}</div>")
            items = "".join(parts)
            out.append(f"<tr><td>{name_cell}</td>"
                       f"<td style='color:{RED};font-size:12px'>更新 {len(posts)} 条</td>"
                       f"<td style='text-align:left'>{items}</td></tr>")
        out.append("</tbody></table>")

    bad = [c for c in social["creators"] if c.get("status") != "ok"]
    if bad:
        # 公众号未取到是「搜狗未收录」，和浏览器登录态无关，分开说明免得误导
        wx = [c for c in bad if c.get("platform") == "wechat"]
        other = [c for c in bad if c.get("platform") != "wechat"]
        tips = []
        if other:
            tips.append("以下博主本次未取到："
                        + "、".join(f"{PLATFORM_CN.get(c.get('platform'), c.get('platform'))} "
                                    f"{c.get('nickname') or c.get('platform_uid')}" for c in other)
                        + "。常见原因是浏览器登录态过期，重新登录一次即可恢复。")
        if wx:
            tips.append("以下公众号未被搜狗微信收录（或名称不完全一致），与登录态无关："
                        + "、".join(c.get("nickname") or c.get("platform_uid") for c in wx)
                        + "。如需覆盖请提供准确的公众号全称。")
        out.append("<div class='box'>" + "<br>".join(tips) + "</div>")
    return "".join(out)


def build(d, tech, run_date, mode, social=None):
    prev = load_state(run_date)
    cur, path = save_state(run_date, tech)
    diff = diff_states(cur, prev)

    mode_cn = {"morning": "早报 · 隔夜版", "evening": "晚报 · 盘后版"}.get(mode, mode)
    errors = d.get("errors") or []

    html = ["<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width,initial=1'>",
            f"<title>投资日报 {run_date}</title><style>{CSS}</style></head><body><div class='wrap'>",
            f"<h1>宏观微观监测日报 · {mode_cn}</h1>",
            f"<div class='meta'>报告日 {run_date} · 生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
            f"跟踪标的 {len(cur['stocks'])} 只 · 数据接口 " + ("部分异常（见页脚）" if errors else "正常") + "</div>"]

    html.append(sec_overview(d))
    html.append(sec_us_macro(d))
    html.append(sec_cn_macro(d))
    html.append(sec_ai(d, tech))
    html.append(sec_gold(d))
    html.append(sec_diff(diff, cur, d.get("tracked") or {}))
    html.append(sec_social(social))
    html.append(sec_calendar(d))

    html.append("<div class='foot'>本报告由本地投资跟踪脚本自动生成。"
                "行情为 T+0 盘中数据（美股为上一交易日收盘），宏观指标按各自公布时点更新，两者口径不同，横向比较请注意。"
                "所有内容为公开信息整理与参考性推演，<b>不构成投资建议</b>，据此操作风险自负。"
                f"<br>状态快照：{os.path.basename(path)}"
                + (f"<br>采集异常：{'；'.join(errors)}" if errors else "")
                + f"<br><br>生成时间 {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>")
    html.append("</div></body></html>")
    return "".join(html)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--mode", default="evening", choices=["morning", "evening"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--summary", action="store_true", help="只输出邮件用 Markdown 摘要")
    ap.add_argument("--summary-out", default=None)
    ap.add_argument("--base-url", default="", help="在线日报主页链接，用于放进邮件正文")
    args = ap.parse_args()
    stamp = args.date.replace("-", "")
    dd = os.path.join(ROOT, "data", f"daily_{stamp}.json")
    if not os.path.exists(dd):
        print("缺少采集数据，请先运行 fetch_daily.py", file=sys.stderr)
        sys.exit(1)
    with open(dd, encoding="utf-8") as fh:
        d = json.load(fh)
    tech_path = os.path.join(ROOT, "data", "technical.json")
    tech = {}
    if os.path.exists(tech_path):
        with open(tech_path, encoding="utf-8") as fh:
            tech = json.load(fh)
    social = None
    sp = os.path.join(ROOT, "data", f"social_{stamp}.json")
    if os.path.exists(sp):
        with open(sp, encoding="utf-8") as fh:
            social = json.load(fh)
    else:
        print(f"[warn] 未找到社媒数据 {sp}，日报将标注「本次未取到」", file=sys.stderr)
    if social:
        d["social"] = social
    if args.summary:
        text = email_summary(d, tech, args.date, args.mode, args.base_url)
        if args.summary_out:
            with open(args.summary_out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print("written:", args.summary_out)
        else:
            print(text)
        return
    out = args.out or os.path.join(ROOT, "reports", f"daily-{stamp}.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(build(d, tech, args.date, args.mode, social))
    print("written:", out)
    index = build_index()
    print("written:", index)


INDEX_TMPL = """<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>投资日报与持仓分析</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
     color:#1F2933;background:#fff;line-height:1.6;padding:32px 18px}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:21px;font-weight:600;margin-bottom:4px}
.meta{color:#6B7280;font-size:12.5px;margin-bottom:20px}
h2{font-size:15px;font-weight:600;margin:22px 0 8px;padding-left:9px;border-left:3px solid #185FA5}
ul{list-style:none}
li{border-bottom:1px solid #EEE;padding:9px 2px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}
a{color:#185FA5;text-decoration:none;font-size:14px}
a:hover{text-decoration:underline}
.tag{font-size:11.5px;color:#6B7280}
@media(max-width:640px){body{padding:16px 10px}}
</style></head><body>
<nav style="background:#fff;border-bottom:1px solid #E5E7EB">
<div style="max-width:1080px;margin:0 auto;padding:0 18px;display:flex;align-items:center;gap:4px;height:52px">
<a href="index.html" style="font-size:14.5px;font-weight:600;color:#1F2933;text-decoration:none;margin-right:16px">投资 App</a>
<a href="index.html" style="font-size:13.5px;color:#6B7280;text-decoration:none;padding:6px 12px;border-radius:7px">首页总览</a>
<a href="holdings.html" style="font-size:13.5px;color:#6B7280;text-decoration:none;padding:6px 12px;border-radius:7px">持仓分析</a>
<a href="archive.html" style="font-size:13.5px;color:#185FA5;text-decoration:none;padding:6px 12px;border-radius:7px;background:#E8F0FA;font-weight:600">日报归档</a>
</div></nav>
<div class='wrap'>
<h1>日报归档</h1>
<div class='meta'>每交易日自动生成 · 共 __DAILY_N__ 份日报 / __HOLD_N__ 份持仓分析 · 最后更新 __NOW__</div>
<h2>每日日报</h2><ul>__DAILY__</ul>
<h2>持仓与观察池分析</h2><ul>__HOLD__</ul>
</div></body></html>"""


def email_summary(d, tech, run_date, mode, base_url=""):
    """生成邮件用的纯文本 / Markdown 摘要（正文放要点，详情看在线页）。"""
    us = d.get("us") or {}
    cn = d.get("cn") or {}
    core = cn.get("core") or {}
    lines = [f"# 投资日报 {run_date} · {'晚报（盘后版）' if mode == 'evening' else '早报（隔夜版）'}", ""]

    # 市场
    idx = d.get("index") or {}
    parts = []
    for grp in ("cn", "hk"):
        for code, row in (idx.get(grp) or {}).items():
            parts.append(f"{row.get('name')} {dash(row.get('price'))} {pct(row.get('chg'))}")
    lines.append("**市场速览**：" + "　".join(parts))

    # 海外
    y = us.get("yield") or {}
    if y:
        sp = y.get("spread")
        lines.append(f"**海外宏观**：美债 10Y {y.get('y10')}% / 2Y {y.get('y2')}%，"
                     f"期限利差 {sp:.0f}bp（{y.get('form')}），期限结构{'倒挂' if (sp is not None and sp < 0) else '已转正'}")
    vix = (us.get("vix") or {}).get("VIX") or []
    fx = d.get("fx") or {}
    tail = []
    if vix:
        tail.append(f"VIX {float(vix[0][1]):.2f}")
    if fx.get("fxDINIW"):
        tail.append(f"美元指数 {fx['fxDINIW']['price']} {pct(fx['fxDINIW']['chg'])}")
    if tail:
        lines.append("　" + "　".join(tail))

    # 国内
    lpr = cn.get("lpr") or {}
    cpi = core.get("cpi") or {}
    pmi = core.get("pmi") or {}
    bits = []
    if lpr.get("lpr1y") is not None:
        bits.append(f"LPR 1Y {lpr['lpr1y']}% / 5Y {lpr.get('lpr5y')}%")
    if cpi.get("yoy") is not None:
        bits.append(f"CPI 同比 {cpi['yoy']}%（核心 {cpi.get('core')}%）")
    if pmi.get("manu") is not None:
        bits.append(f"制造业 PMI {pmi['manu']}（{'荣枯线下' if pmi['manu'] < 50 else '扩张区间'}）")
    money = core.get("money") or {}
    if money.get("m2") is not None:
        bits.append(f"M2 {money['m2']}%")
    fin = core.get("financing") or {}
    if fin.get("size_yoy") is not None:
        bits.append(f"社融存量同比 {fin['size_yoy']}%")
    if bits:
        lines.append("**国内宏观**：" + "　".join(bits))

    # AI 链
    ai_us = d.get("ai_us") or {}
    if ai_us:
        top = sorted(ai_us.items(), key=lambda kv: num(kv[1].get("chg")) or 0, reverse=True)
        txt = "　".join(f"{v.get('name')} {pct(v.get('chg'))}" for _, v in top[:5])
        lines.append(f"**AI 产业链（美股）**：{txt}")
    ai_a = d.get("ai_a") or {}
    if ai_a:
        top = sorted(ai_a.items(), key=lambda kv: num(kv[1].get("chg")) or 0, reverse=True)
        txt = "　".join(f"{v.get('name')} {pct(v.get('chg'))}" for _, v in top[:4])
        lines.append(f"**AI 产业链（A股）**：{txt}")

    # 黄金
    g = d.get("gold") or {}
    if g:
        txt = "　".join(f"{v.get('name')} {dash(v.get('price'))} {pct(v.get('chg'))}" for v in g.values())
        lines.append(f"**黄金**：{txt}")

    # 差分
    prev = load_state(run_date)
    cur_path = os.path.join(ROOT, "data", f"state_{run_date.replace('-','')}.json")
    if os.path.exists(cur_path):
        with open(cur_path, encoding="utf-8") as fh:
            cur = json.load(fh)
        diff = diff_states(cur, prev)
        lines.append("")
        if diff.get("first"):
            lines.append("**技术状态变化**：首次运行，明日开始列出增量变化。")
        elif diff.get("changes") or diff.get("added") or diff.get("removed"):
            lines.append(f"**技术状态变化（{len(diff.get('changes') or [])} 处）**：")
            for item in (diff.get("changes") or []):
                p, c = item[1], item[2]
                worsened = SIGNAL_ORDER.get(c["signal"], 9) > SIGNAL_ORDER.get(p["signal"], 9)
                lines.append(f"- {c['name']}（{item[0]}）：{'⚠ 恶化' if worsened else '✅ 改善'} {p['label']} → {c['label']}　"
                             f"柱 {c['hist']:+.2f}（{c['hist_bp']:+.0f}bp）")
            for code, c in (diff.get("added") or []):
                lines.append(f"- {c['name']}（{code}）：新加入跟踪，状态 {c['label']}")
        else:
            lines.append("**技术状态变化**：今日无变化，持仓与观察池 MACD 状态维持。")

    # FOMC
    fomc = d.get("fomc") or {}
    nxt = fomc.get("next")
    if nxt:
        try:
            days = (date.fromisoformat(nxt["decision_us"]) - date.fromisoformat(fomc["today"])).days
        except Exception:  # noqa: BLE001
            days = None
        mark = "🔴 " if (days is not None and days <= 3) else ""
        lines.append("")
        lines.append(f"{mark}**FOMC**：下次决议 北京时间 **{nxt['decision_cn']}**"
                     + (f"（{days} 天后）" if days is not None else "")
                     + ("，含经济预测 + 点阵图 + 发布会" if nxt.get("sep") else "，仅决议声明"))

    # 关注博主 T-1 更新
    social = d.get("social")
    if social and (social.get("creators") or []):
        updated = [c for c in social["creators"] if (c.get("posts_window") or [])]
        lines.append("")
        if not updated:
            lines.append(f"**关注博主**：{len(social['creators'])} 位全部无 T-1 更新。")
        else:
            lines.append(f"**关注博主 T-1 更新（{len(updated)} 位）**：")
            for c in updated:
                nick = c.get("nickname") or c.get("platform_uid")
                plat = PLATFORM_CN.get(c.get("platform"), c.get("platform"))
                rn = f"　⚠原「{c['renamed']}」已改名" if c.get("renamed") else ""
                lines.append(f"- **{plat} {nick}**{rn}")
                for p in (c.get("posts_window") or [])[:4]:
                    lines.append(f"    · {p.get('published')}　{(p.get('title') or '')[:70]}")
                    s = (p.get("summary") or "").strip()
                    if s:
                        lines.append(f"      内容：{s[:150]}{'…' if len(s) > 150 else ''}")
        bad = [c for c in social["creators"] if c.get("status") != "ok"]
        if bad:
            lines.append(f"- 另有 {len(bad)} 位未取到（"
                         + "、".join(PLATFORM_CN.get(c.get("platform"), c.get("platform")) for c in bad)
                         + "），详见在线页")

    # 日历
    cal = d.get("calendar") or []
    if cal:
        lines.append("")
        lines.append("**未来事件**：")
        for e in cal[:6]:
            dt = e["date"]
            if len(dt) == 8:
                dt = f"{dt[:4]}-{dt[4:6]}-{dt[6:]}"
            lines.append(f"- {dt}　{e.get('name')}")

    lines.append("")
    if base_url:
        lines.append(f"完整日报（含全部板块数据表）：{base_url}")
    err = d.get("errors") or []
    if err:
        lines.append("")
        lines.append(f"> 本次采集有 {len(err)} 项异常：" + "；".join(err))
    lines.append("")
    lines.append("*本报告为公开信息整理与参考性推演，不构成投资建议。*")
    return "\n".join(lines)


def build_index():
    """生成日报归档页。

    注意：站点首页（index.html）现在由 build_app.py 生成，是本 App 的首页总览。
    这里只能写 archive.html，否则会把 App 首页覆盖掉。
    """
    import glob
    reports = os.path.join(ROOT, "reports")
    daily = sorted(glob.glob(os.path.join(reports, "daily-*.html")), reverse=True)
    hold = sorted(glob.glob(os.path.join(reports, "holdings-report-*.html")), reverse=True)

    def li(path, kind):
        name = os.path.basename(path)
        date = name.replace("daily-", "").replace("holdings-report-", "").replace(".html", "")
        if len(date) == 8:
            date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M")
        return f"<li><a href='{name}'>{date} {kind}</a><span class='tag'>{ts}</span></li>"

    html = (INDEX_TMPL
            .replace("__DAILY_N__", str(len(daily)))
            .replace("__HOLD_N__", str(len(hold)))
            .replace("__NOW__", datetime.now().strftime("%Y-%m-%d %H:%M"))
            .replace("__DAILY__", "".join(li(p, "投资日报") for p in daily))
            .replace("__HOLD__", "".join(li(p, "持仓分析") for p in hold)))
    path = os.path.join(reports, "archive.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


if __name__ == "__main__":
    main()
