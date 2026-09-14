#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拉取技术指标（MACD / DIF / DEA / MA / RSI / KDJ / BOLL）并落盘为 JSON。

westock CLI 单次批量上限 10 个代码，这里自动分批。
用法：
    python3 scripts/fetch_technical.py --asof 2026-09-11 --limit 26
"""

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 需要技术面数据的标的（持仓，含场内基金）
HOLDING_CODES = [
    ("sz300308", "中际旭创"), ("sh601869", "长飞光纤"), ("sh688825", "长鑫科技"),
    ("sh600584", "长电科技"), ("sz002428", "云南锗业"), ("sz300408", "三环集团"),
    ("sz300054", "鼎龙股份"), ("sz300661", "圣邦股份"), ("sz002384", "东山精密"),
    ("sz300502", "新易盛"), ("sz159501", "纳指ETF嘉实"), ("sh588080", "科创50ETF易方达"),
    ("sh506002", "易方达科创板"),
]

# 观察池科技标的（14 只，与持仓高度同向，用于对比 MACD 走向）
WATCH_CODES = [
    ("sz301183", "东田微"), ("sh603186", "华正新材"), ("sh688146", "中船特气"),
    ("sh688820", "盛合晶微"), ("sh688012", "中微公司"), ("sh688256", "寒武纪"),
    ("sh688041", "海光信息"), ("sz002371", "北方华创"), ("sh688498", "源杰科技"),
    ("sh688361", "中科飞测"), ("sh688347", "华虹宏力"), ("sz300394", "天孚通信"),
    ("hk00700", "腾讯控股"), ("hk09988", "阿里巴巴-W"),
]

# 科技对冲篮子（与 AI 算力链低相关 / 负相关的方向）
HEDGE_CODES = [
    ("sh510880", "红利ETF华泰柏瑞", "红利"),
    ("sh515180", "红利ETF易方达", "红利"),
    ("sh515220", "煤炭ETF国泰", "煤炭"),
    ("sz159748", "创新药ETF富国", "创新药"),
    ("sh516080", "创新药ETF易方达", "创新药"),
    ("sh512800", "银行ETF华宝", "银行"),
    ("sh518880", "黄金ETF华安", "黄金"),
]

CACHE = dict(HOLDING_CODES + WATCH_CODES)


def run(cmd):
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return proc.stdout


def parse_md_table(text):
    """把 westock 的 markdown 表格解析成 list[dict]。"""
    rows = []
    header = None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def fetch_one(code):
    # westock 的 --date 是截面模式（只返回单日），取历史序列必须用区间模式
    out = run(f"westock technical {code} --start {ARGS.start} --end {ARGS.asof} --limit {ARGS.limit}")
    rows = parse_md_table(out)
    def num(r, key):
        v = r.get(key)
        if v is None or v in ("-", "", "null", "None"):
            return None
        try:
            return float(v)
        except ValueError:
            return None

    series = []
    for r in rows:
        if not r.get("date") or num(r, "closePrice") is None:
            continue
        series.append(dict(
            date=r["date"],
            close=num(r, "closePrice"),
            dif=num(r, "DIF"), dea=num(r, "DEA"), macd=num(r, "MACD"),
            ma5=num(r, "MA_5"), ma10=num(r, "MA_10"), ma20=num(r, "MA_20"),
            ma60=num(r, "MA_60"), ma120=num(r, "MA_120"),
            rsi6=num(r, "RSI_6"), rsi12=num(r, "RSI_12"),
            k=num(r, "KDJ_K"), d=num(r, "KDJ_D"), j=num(r, "KDJ_J"),
            boll_up=num(r, "BOLL_UPPER"), boll_mid=num(r, "BOLL_MID"),
            boll_low=num(r, "BOLL_LOWER"),
        ))
    return series


def main():
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="2026-09-11")
    ap.add_argument("--start", default="2026-07-20")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "technical.json"))
    ARGS = ap.parse_args()

    result = {"asof": ARGS.asof, "holdings": {}, "watch": {}, "hedges": {}}

    print(f"[1/3] 拉取持仓技术面 {len(HOLDING_CODES)} 只 …", file=sys.stderr)
    for c, nm in HOLDING_CODES:
        s = fetch_one(c)
        result["holdings"][c] = {"name": nm, "series": s}
        print(f"      {nm}({c})  {len(s)} 条", file=sys.stderr)

    print(f"[2/3] 拉取观察池技术面 {len(WATCH_CODES)} 只 …", file=sys.stderr)
    for c, nm in WATCH_CODES:
        s = fetch_one(c)
        result["watch"][c] = {"name": nm, "series": s}
        print(f"      {nm}({c})  {len(s)} 条", file=sys.stderr)

    print(f"[3/3] 拉取对冲篮子 {len(HEDGE_CODES)} 只 …", file=sys.stderr)
    for c, nm, bucket in HEDGE_CODES:
        s = fetch_one(c)
        result["hedges"][c] = {"name": nm, "bucket": bucket, "series": s}
        print(f"      {nm}({c})  {len(s)} 条", file=sys.stderr)

    os.makedirs(os.path.dirname(ARGS.out), exist_ok=True)
    with open(ARGS.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print("written:", ARGS.out, file=sys.stderr)


if __name__ == "__main__":
    main()
