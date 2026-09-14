#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观 / 微观监测数据采集。

三条主线：
  A 海外宏观：美债收益率曲线与期限利差、美元指数、VIX、联邦基金利率、美国近期宏观数据实际 vs 预期
  B 国内宏观：LPR、CPI/PPI、PMI、M1/M2、社融、外汇与黄金储备、人民币汇率
  C AI 产业链：美股 AI 核心股、A 股算力/光模块/存储板块表现
  D 大宗黄金：COMEX 黄金、黄金 ETF、黄金概念板块
  E 市场速览：A 股 / 港股 / 美股主要指数
  F 未来事件日历

采集原则：任何一块失败都不影响整体，缺数据会在 JSON 里留下 None，
渲染时明确标注「本次未取到」，不静默跳过。

用法：
    python3 scripts/fetch_daily.py --date 2026-09-14 --out data/daily_20260914.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from westock_client import run, parse_md_table, parse_events, f  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- 标的清单
# 主要指数
CN_INDEX = [("sh000001", "上证指数"), ("sz399001", "深证成指"),
            ("sz399006", "创业板指"), ("sh000688", "科创50")]
HK_INDEX = [("hkHSI", "恒生指数"), ("hkHSTECH", "恒生科技")]

# AI 产业链核心标的美股
AI_US = [("usNVDA", "英伟达"), ("usAMD", "超威半导体"), ("usTSM", "台积电"),
         ("usAVGO", "博通"), ("usMSFT", "微软"), ("usGOOGL", "谷歌-A"),
         ("usMU", "美光科技"), ("usSMCI", "超微电脑")]

# A 股 AI 链：与用户持仓/观察池高度相关的场内代表
AI_A = [("sz300308", "中际旭创"), ("sz300502", "新易盛"), ("sz300394", "天孚通信"),
        ("sh688256", "寒武纪"), ("sh688041", "海光信息"), ("sh688825", "长鑫科技"),
        ("sh688012", "中微公司"), ("sz002371", "北方华创")]

# 黄金
GOLD = [("fuGC", "COMEX黄金"), ("sh518880", "黄金ETF华安"), ("sz159934", "黄金ETF易方达")]
GOLD_STOCK = [("sh600547", "山东黄金"), ("sh601899", "紫金矿业"), ("sz002155", "湖南黄金")]

# 外汇
FX = [("fxDINIW", "美元指数"), ("fxUSDCNY", "美元人民币"), ("fxCNH", "离岸人民币")]


def quote_rows(codes):
    """
    批量取行情，返回 {code: 标准化 dict}。
    混合品种（期货 / 外汇 / 股票）批量查询常缺项，
    所以对缺失的代码逐个回退单查。
    """
    if not codes:
        return {}

    def norm(r):
        if not r:
            return None
        price = (r.get("lastPrice") or r.get("price") or "").strip()
        chg = (r.get("changePct") or r.get("change_percent") or "").strip()
        return dict(code=r.get("code"), name=r.get("name", ""),
                    price=price, chg=chg,
                    high=r.get("high", "-"), low=r.get("low", "-"),
                    prev=(r.get("prevClose") or r.get("prev_close") or "-"),
                    time=(r.get("updateTime") or r.get("time") or "-"))

    out = run(f"westock quote {','.join(codes)}")
    got = {r.get("code"): r for r in parse_md_table(out) if r.get("code")}
    res = {}
    for c in codes:
        r = got.get(c)
        if r is None or not ((r.get("lastPrice") or r.get("price")) or "").strip():
            single = run(f"westock quote {c}")
            rows = {x.get("code"): x for x in parse_md_table(single) if x.get("code")}
            r = rows.get(c, r)
        n = norm(r)
        if n:
            res[c] = n
    return res


def indicator(name, asof):
    """取单个宏观指标，返回 list[dict]。"""
    out = run(f"westock macro indicator {name} --date {asof} --limit 12")
    return parse_md_table(out)


def collect(asof):
    d = {"asof": asof, "collected_at": datetime.now().isoformat(timespec="seconds"), "errors": []}

    def safe(label, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            d["errors"].append(f"{label}: {e}")
            return None

    # ---------------- A 海外宏观
    us = {}
    rows = safe("美债期限利差", lambda: indicator("us_term_spread_10y2y", asof))
    if rows:
        r = rows[-1]
        us["yield"] = dict(date=r.get("EndDate"), y10=f(r, "Yield10Y"), y2=f(r, "Yield2Y"),
                           spread=f(r, "TermSpread"), form=r.get("CurveFormD", "-"))
        # 近 10 日期限利差走势
        us["spread_hist"] = [(x.get("EndDate"), f(x, "TermSpread")) for x in rows]
    for key, name in [("key_index", "us_key_index"), ("vix", "us_vix"), ("usd_index", "us_usd_index")]:
        res = safe(name, lambda n=name: indicator(n, asof))
        if res:
            rows_map = {}
            for x in res:
                src = x.get("清单", "")
                rows_map.setdefault(src, x)
            # 取每个子指标最新一行
            latest = {}
            for x in res:
                for k, v in x.items():
                    if k in ("EndDate", "清单"):
                        continue
                    if v not in ("-", ""):
                        latest.setdefault(k, []).append((x.get("EndDate"), v))
            us[key] = latest
    # 美国宏观数据发布（实际 / 预期 / 前值）
    us_events = []
    for name in ("us_inflation", "us_employment", "us_manufacturing", "us_monetary"):
        res = safe(name, lambda n=name: indicator(n, asof))
        if res:
            us_events += parse_events(run(f"westock macro indicator {name} --date {asof}"))
    us["events"] = us_events
    d["us"] = us

    # ---------------- B 国内宏观
    cn = {}
    # LPR 是事件型指标（IndicatorName / OccurDate），按事件解析后取 1Y / 5Y 最新值
    lpr_ev = []
    res = safe("LPR", lambda: run(f"westock macro indicator cn_lpr --date {asof} --limit 12"))
    if res:
        lpr_ev = parse_events(res)
    if lpr_ev:
        def latest(kw):
            # 跳过尚未公布的行（ActualValue 为「未公布」）
            hit = [e for e in lpr_ev if kw in e["name"] and f(e, "actual") is not None]
            hit.sort(key=lambda e: e["date"], reverse=True)
            e = hit[0] if hit else None
            prev = hit[1] if len(hit) > 1 else None
            return (e, prev)
        e1, p1 = latest("一年期")
        e5, p5 = latest("五年期")
        cn["lpr"] = dict(
            lpr1y=f(e1, "actual") if e1 else None, lpr5y=f(e5, "actual") if e5 else None,
            lpr1y_date=e1["date"] if e1 else None, lpr5y_date=e5["date"] if e5 else None,
            lpr1y_prev=f(p1, "actual") if p1 else None, lpr5y_prev=f(p5, "actual") if p5 else None,
        )
        cn["lpr_events"] = lpr_ev[:6]
    rows = safe("核心宏观指标", lambda: indicator("cn_core_p1", asof))
    if rows:
        r = rows[-1]
        def jget(col):
            raw = r.get(col, "")
            if not raw or raw in ("-",):
                return {}
            try:
                return json.loads(raw)
            except Exception:  # noqa: BLE001
                return {}
        core = {}
        cpi = jget("CPI")
        if cpi:
            core["cpi"] = dict(yoy=cpi.get("CPI_CPI_YOY"), core=cpi.get("CPI_CPI_YOY_CORE"),
                               food=cpi.get("CPI_CPI_YOY_FOOD"), end=cpi.get("CPI_END_DATE"),
                               info=cpi.get("CPI_INFO_DATE"), scissors=cpi.get("CPI_PRICE_SCISSORS_CPI_PPI"))
        pmi = jget("PMI")
        if pmi:
            core["pmi"] = dict(manu=pmi.get("PMI_PMI_MANU"), mom=pmi.get("PMI_PMI_MANU_MOM"),
                               new_order=pmi.get("PMI_PMI_MANU_ORDER_NEW"),
                               non_manu=pmi.get("PMI_NON_MANU_BIZ_ACT"),
                               composite=pmi.get("PMI_PMI_COMPREHENSIVE_CCZS"), end=pmi.get("PMI_END_DATE"))
        cur = jget("CURV")
        if cur:
            core["money"] = dict(m1=cur.get("CURV_M1_YOY"), m2=cur.get("CURV_M2_YOY"),
                                 scissors=cur.get("CURV_SCISSORS_M1_M2"), end=cur.get("CURV_END_DATE"))
        fin = jget("FINANCING")
        if fin:
            core["financing"] = dict(size=fin.get("FINANCING_SR_SIZE"), size_yoy=fin.get("FINANCING_SR_SIZE_YOY"),
                                     gov_bond_yoy=fin.get("FINANCING_SR_SIZE_YOY_GOV_B"),
                                     loan_yoy=fin.get("FINANCING_SR_SIZE_YOY_LOAN"), end=fin.get("FINANCING_END_DATE"))
        exp = jget("EXP")
        if exp:
            core["reserve"] = dict(fx=exp.get("EXP_EX_RESERVES_MONTHLY"),
                                   gold=exp.get("EXP_GOLD_RESERVES_MONTHLY"), end=exp.get("EXP_END_DATE"))
        gdp = jget("GDP")
        if gdp:
            core["gdp"] = dict(real_yoy=gdp.get("GDP_REAL_GDP_CUR_YOY"),
                               cum_yoy=gdp.get("GDP_REAL_GDP_CUM_YOY"), end=gdp.get("GDP_END_DATE"))
        inv = jget("INV")
        if inv:
            core["re"] = dict(new_yoy=inv.get("INV_REALESTATE_NEW_CUM_YOY"),
                              invest_yoy=inv.get("INV_RE_AMT_TOTAL_CUM_YOY"))
        cn["core"] = core
        cn["core_raw"] = {k: r.get(k) for k in ("CPI", "PMI", "CURV", "FINANCING", "EXP", "GDP")}
    d["cn"] = cn

    # ---------------- 未来事件日历
    cal = []
    for area in ("usa", "chn", "euz", "jpn"):
        code = f"westock macro expect --area {area}"
        res = safe(f"预期日历-{area}", lambda c=code: run(c))
        if res:
            evs = parse_events(res)
            cal += [dict(e, area=area) for e in evs]
    res = safe("全球日历", lambda: run("westock macro indicator cn_calendar_future"))
    if res:
        for e in parse_events(res):
            if e["name"]:
                cal.append(dict(area=e["area"], name=e["name"], actual="-", forecast="-",
                                former="-", date=e["date"], time=e["time"], importance="-"))
    # 只保留今天之后、且重要性或关键词命中的
    today_i = int(asof.replace("-", ""))
    kw = ("利率", "议息", "决议", "纪要", "货币政策", "非农", "CPI", "PCE", "GDP", "PMI", "FOMC", "鲍威尔", "LPR")
    upcoming = [e for e in cal if e["date"].isdigit() and int(e["date"]) >= today_i]
    upcoming.sort(key=lambda e: (int(e["date"]), e["time"]))
    seen, ded = set(), []
    for e in upcoming:
        k = (e["date"], e["name"])
        if k in seen:
            continue
        seen.add(k)
        ded.append(e)
    d["calendar"] = [e for e in ded if any(k in e["name"] for k in kw)][:25]
    d["calendar_all"] = ded[:40]

    # ---------------- 跟踪标的实时行情（用于覆盖技术快照里的旧收盘价）
    tracked_codes, tracked_names = [], {}
    tp = os.path.join(ROOT, "data", "technical.json")
    if os.path.exists(tp):
        try:
            with open(tp, encoding="utf-8") as fh:
                tj = json.load(fh)
            for grp in ("holdings", "watch", "hedges"):
                for code, v in (tj.get(grp) or {}).items():
                    tracked_codes.append(code)
                    tracked_names[code] = v.get("name", code)
        except Exception as e:  # noqa: BLE001
            d["errors"].append(f"读取 technical.json: {e}")
    if tracked_codes:
        got = {}
        for i in range(0, len(tracked_codes), 10):
            batch = tracked_codes[i:i + 10]
            got.update(safe(f"跟踪标的行情-{i}", lambda b=batch: quote_rows(b)) or {})
        d["tracked"] = got
        d["tracked_names"] = tracked_names

    # ---------------- E 市场速览 / C AI 链 / D 黄金
    d["index"] = dict(cn=safe("A股指数", lambda: quote_rows([c for c, _ in CN_INDEX])),
                      hk=safe("港股指数", lambda: quote_rows([c for c, _ in HK_INDEX])))
    d["index"]["names"] = dict(CN_INDEX + HK_INDEX)
    d["ai_us"] = safe("美股AI", lambda: quote_rows([c for c, _ in AI_US]))
    d["ai_us_names"] = dict(AI_US)
    d["ai_a"] = safe("A股AI", lambda: quote_rows([c for c, _ in AI_A]))
    d["ai_a_names"] = dict(AI_A)
    d["gold"] = safe("黄金", lambda: quote_rows([c for c, _ in GOLD]))
    d["gold_names"] = dict(GOLD)
    d["gold_stock"] = safe("黄金股", lambda: quote_rows([c for c, _ in GOLD_STOCK]))
    d["gold_stock_names"] = dict(GOLD_STOCK)
    d["fx"] = safe("外汇", lambda: quote_rows([c for c, _ in FX]))
    d["fx_names"] = dict(FX)

    # ---------------- 概念板块：抽 AI 算力 / 黄金 / 红利相关板块
    sec = {}
    for kind in ("concept", "industry"):
        for typ in ("changePct", "mainNetInflow"):
            out = safe(f"板块-{kind}-{typ}",
                       lambda k=kind, t=typ: run(f"westock sector ranking --kind {k} --type {t}"))
            if out:
                sec[(kind, typ)] = parse_md_table(out)
    kw_ai = ("光模块", "CPO", "算力", "AI", "半导体", "存储", "芯片", "服务器", "PCB", "先进封装", "HBM", "液冷")
    kw_gold = ("黄金", "贵金属", "有色")
    kw_div = ("红利", "高股息", "银行", "煤炭")
    def pick(k, rowset):
        hits = []
        for kind in ("concept", "industry"):
            rows = rowset.get((kind, k)) or []
            for r in rows:
                nm = r.get("name", "")
                if any(x in nm for x in kw_ai + kw_gold + kw_div):
                    hits.append(dict(code=r.get("code"), name=nm, kind=kind,
                                     pct=f(r, "changePct"), inflow=f(r, "mainNetInflow"),
                                     inflow5d=f(r, "mainNetInflow5d"),
                                     leader=r.get("leader", "-"), up=r.get("upCount", "-")))
        # 去重
        us_, res = set(), []
        for h in hits:
            if h["name"] in us_:
                continue
            us_.add(h["name"])
            res.append(h)
        return res
    d["sector"] = dict(changePct=pick("changePct", sec), inflow=pick("mainNetInflow", sec))
    d["sector_kw"] = dict(ai=kw_ai, gold=kw_gold, div=kw_div)

    # ---------------- 外部日历数据源（FOMC 官方 + 金十）----------------
    for key, fname in (("fomc", "fomc.json"), ("jin10", "jin10.json")):
        p = os.path.join(ROOT, "data", fname)
        if not os.path.exists(p):
            d[key] = None
            d["errors"].append(f"缺少 {fname}（未运行对应采集脚本）")
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                d[key] = json.load(fh)
        except Exception as e:  # noqa: BLE001
            d[key] = None
            d["errors"].append(f"读取 {fname}: {e}")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(ROOT, "data", f"daily_{args.date.replace('-','')}.json")
    data = collect(args.date)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print("written:", out, file=sys.stderr)
    if data["errors"]:
        print("采集异常：", file=sys.stderr)
        for e in data["errors"]:
            print("  -", e, file=sys.stderr)


if __name__ == "__main__":
    main()
