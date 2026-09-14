#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观历史序列采集（App「宏观趋势」屏的数据源）。

与 fetch_daily.py 的区别：fetch_daily 取「当期值」，本脚本取「历史序列」，
专门喂趋势图。全部走 westock macro indicator，一次运行约 10 个请求。

指标与窗口：
  海外（30 期 / 全年）：
    us_yield_curve    美债 10Y / 2Y 收益率 → 期限利差序列
    us_usd_index      美元指数 DXY
    us_vix            VIX
    us_key_index      三大股指（纳指/道指/标普）
  国内（全年月度）：
    cn_cpi_ppi        CPI / PPI 同比
    cn_pmi            制造业 PMI
    cn_fundquantity   M1 / M2 同比与剪刀差
    cn_financing      社融存量同比
    cn_lpr            LPR（事件序列）
    cn_premium_curve  股债溢价率 / 红利溢价（快照）

用法：
    python3 scripts/fetch_macro_history.py [--date 2026-09-14] [--year 2026]
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from westock_client import run, parse_md_table, parse_events, f  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def series(rows, date_key, value_key, digits=2):
    """从 markdown 行里抽 (date, value) 序列，按日期升序。"""
    out = []
    for r in rows:
        d = (r.get(date_key) or "").strip()
        v = f(r, value_key)
        if not d or v is None:
            continue
        out.append([d, round(v, digits)])
    out.sort(key=lambda x: x[0])
    return out


def dedup(seq):
    """同日期多行（比如按月与按旬混排）保留最新一条。"""
    seen = {}
    for d, v in seq:
        seen[d] = v
    return sorted(seen.items())


def collect(asof, year):
    d = {"asof": asof, "year": year,
         "collected_at": datetime.now().isoformat(timespec="seconds"),
         "errors": [], "sources": {}}

    def safe(label, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            d["errors"].append(f"{label}: {e}")
            return None

    def ind(name, window, limit=None):
        cmd = f"westock macro indicator {name}"
        if window == "year":
            cmd += f" --year {year}"
        else:
            cmd += f" --date {asof}"
        if limit:
            cmd += f" --limit {limit}"
        return parse_md_table(run(cmd))

    # ---------------- 海外
    us = {}
    rows = safe("美债收益率曲线", lambda: ind("us_yield_curve", "year", 60))
    if rows:
        y10 = dedup(series(rows, "EndDate", "YIELD_10Y"))
        y2 = dedup(series(rows, "EndDate", "YIELD_2Y"))
        # 利差按两边都有值的日期对齐
        m2 = dict(y2)
        spread = [[dt, round(v - m2[dt], 2)] for dt, v in y10 if dt in m2]
        us["yield10y"], us["yield2y"], us["spread"] = y10, y2, spread
        d["sources"]["us_yield_curve"] = f"us_yield_curve --year {year} --limit 60"
    for key, name, val, lim in (("usd", "us_usd_index", "DXY", 30),
                                ("vix", "us_vix", "VIX", 30),
                                ("spx", "us_key_index", "SPX", 30),
                                ("ndx", "us_key_index", "COMP_NASDAQ", 30)):
        rows = safe(name, lambda n=name, l=lim: ind(n, "date", l))
        if rows:
            us[key] = dedup(series(rows, "EndDate", val))
            d["sources"][name] = f"{name} --date {asof} --limit {lim}"
    d["us"] = us

    # ---------------- 国内
    cn = {}
    rows = safe("CPI/PPI", lambda: ind("cn_cpi_ppi", "year", 24))
    if rows:
        cn["cpi"] = dedup(series(rows, "CPI_END_DATE", "CPI_CPI_YOY"))
        cn["cpi_core"] = dedup(series(rows, "CPI_END_DATE", "CPI_CPI_YOY_CORE"))
        cn["ppi"] = dedup(series(rows, "CPI_END_DATE", "PPI_PPI_YOY"))
        d["sources"]["cn_cpi_ppi"] = f"cn_cpi_ppi --year {year} --limit 24"
    rows = safe("PMI", lambda: ind("cn_pmi", "year", 24))
    if rows:
        cn["pmi"] = dedup(series(rows, "PMI_END_DATE", "PMI_PMI_MANU"))
        cn["pmi_non_manu"] = dedup(series(rows, "PMI_END_DATE", "PMI_NON_MANU_BIZ_ACT"))
        d["sources"]["cn_pmi"] = f"cn_pmi --year {year} --limit 24"
    rows = safe("M1/M2", lambda: ind("cn_fundquantity", "year", 24))
    if rows:
        cn["m1"] = dedup(series(rows, "CURV_END_DATE", "CURV_M1_YOY"))
        cn["m2"] = dedup(series(rows, "CURV_END_DATE", "CURV_M2_YOY"))
        cn["m1_m2"] = dedup(series(rows, "CURV_END_DATE", "CURV_SCISSORS_M1_M2"))
        d["sources"]["cn_fundquantity"] = f"cn_fundquantity --year {year} --limit 24"
    rows = safe("社融", lambda: ind("cn_financing", "year", 24))
    if rows:
        cn["financing"] = dedup(series(rows, "FINANCING_END_DATE", "FINANCING_SR_SIZE_YOY"))
        d["sources"]["cn_financing"] = f"cn_financing --year {year} --limit 24"
    res = safe("LPR", lambda: run(f"westock macro indicator cn_lpr --date {asof} --limit 24"))
    if res:
        evs = parse_events(res)
        lpr1, lpr5 = [], []
        for e in evs:
            if f(e, "actual") is None:
                continue
            if "一年期" in e["name"]:
                lpr1.append([e["date"], f(e, "actual")])
            elif "五年期" in e["name"]:
                lpr5.append([e["date"], f(e, "actual")])
        cn["lpr1y"], cn["lpr5y"] = sorted(lpr1), sorted(lpr5)
        d["sources"]["cn_lpr"] = f"cn_lpr --date {asof} --limit 24"
    rows = safe("股债溢价率", lambda: ind("cn_premium_curve", "date"))
    if rows:
        # 快照，取全部数值列留档（列名随行情变化，前端按需挑）
        cn["premium_raw"] = rows[-1] if rows else None
        d["sources"]["cn_premium_curve"] = f"cn_premium_curve --date {asof}"
    d["cn"] = cn
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--year", default=datetime.now().strftime("%Y"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    out = args.out or os.path.join(ROOT, "data", "macro_history.json")
    data = collect(args.date, args.year)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    print("written:", out, file=sys.stderr)
    n_us = sum(len(v) for v in data["us"].values() if isinstance(v, list))
    n_cn = sum(len(v) for k, v in data["cn"].items() if isinstance(v, list))
    print(f"海外序列点 {n_us} 个，国内序列点 {n_cn} 个", file=sys.stderr)
    if data["errors"]:
        print("采集异常：", file=sys.stderr)
        for e in data["errors"]:
            print("  -", e, file=sys.stderr)


if __name__ == "__main__":
    main()
