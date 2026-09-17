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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import targets  # noqa: E402

# 标的清单一律从本地配置读取，代码内不含个人标的：
#   持仓 / 观察池 → data/positions.json（云端镜像，git 忽略）
#   AI 链 / 对冲篮子 → config/targets.json（git 忽略，缺失时用示例清单）
HOLDING_CODES = targets.holdings()
WATCH_CODES = targets.watchlist()
HEDGE_CODES = targets.hedge()

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
