#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从美联储官网抓取 FOMC 会议日历（权威源），换算成北京时间。

数据源：https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
产出：data/fomc.json

字段：
  month / dates / sep(是否含经济预测+点阵图) / press(是否有发布会)
  decision_us   美东决议日（会议最后一天）
  decision_cn   北京时间决议时点（美东 14:00 → 北京次日 02:00(夏令时) / 03:00(冬令时)）
  minutes_us    纪要公布日（决议后 3 周）
  minutes_cn    北京时间纪要时点
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

# 美国夏令时：3 月第二个周日 ~ 11 月第一个周日（2026: 3/8 - 11/1）
def us_dst(d: dt.date) -> bool:
    if d.month < 3 or d.month > 11:
        return False
    if 3 < d.month < 11:
        return True
    if d.month == 3:
        # 第二个周日
        first = dt.date(d.year, 3, 1)
        sun = first + dt.timedelta(days=(6 - first.weekday()) % 7)
        second = sun + dt.timedelta(days=7)
        return d >= second
    # 11 月第一个周日
    first = dt.date(d.year, 11, 1)
    sun = first + dt.timedelta(days=(6 - first.weekday()) % 7)
    return d < sun


def to_beijing(d: dt.date) -> dt.datetime:
    """美东 14:00 发布会/决议时点 → 北京时间。"""
    hour = 2 if us_dst(d) else 3
    return dt.datetime(d.year, d.month, d.day, hour, 0) + dt.timedelta(days=1)


def fetch_html() -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse(html: str):
    marks = [(m.start(), int(m.group(1)))
             for m in re.finditer(r">(\d{4}) FOMC Meetings<", html)]
    if not marks:
        return []
    marks.append((len(html), None))
    out = []
    for idx in range(len(marks) - 1):
        s, year = marks[idx]
        e = marks[idx + 1][0]
        seg = html[s:e]
        for block in re.split(r'<div class="[^"]*row fomc-meeting', seg)[1:]:
            mm = re.search(r'fomc-meeting__month[^>]*><strong>(\w+)</strong>', block)
            dm = re.search(r'fomc-meeting__date[^>]*>([^<]+)<', block)
            if not mm or not dm:
                continue
            month = MONTHS.get(mm.group(1))
            raw = dm.group(1).strip()
            if month is None or not re.match(r"^\d{1,2}-\d{1,2}\*?$", raw):
                continue
            sep = raw.endswith("*")
            a, b = (int(x) for x in raw.rstrip("*").split("-"))
            cross = a > b  # 形如 "31-1" 跨月
            y2, m2 = (year, month + 1) if (cross and month < 12) else (year, month)
            if cross and month == 12:
                y2, m2 = year + 1, 1
            try:
                d_us = dt.date(y2, m2, b)
            except ValueError:
                continue
            # 未召开的会议官网还没挂发布会链接；含 SEP 的会议必定有发布会
            press = ("Press Conference" in block) or sep
            rm = re.search(r"\(Released\s+([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})\)", block)
            if rm and MONTHS.get(rm.group(1)):
                minutes_us = dt.date(int(rm.group(3)), MONTHS[rm.group(1)], int(rm.group(2)))
            else:
                minutes_us = d_us + dt.timedelta(days=21)  # 官网规则：决议后三周
            out.append(dict(
                year=year, month=month, dates=raw, sep=sep, press=press,
                decision_us=d_us.isoformat(),
                decision_cn=to_beijing(d_us).strftime("%Y-%m-%d %H:%M"),
                minutes_us=minutes_us.isoformat(),
                minutes_cn=to_beijing(minutes_us).strftime("%Y-%m-%d %H:%M"),
            ))
    out.sort(key=lambda x: x["decision_us"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=dt.date.today().isoformat())
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "fomc.json"))
    args = ap.parse_args()

    today = dt.datetime.strptime(args.today, "%Y-%m-%d").date()
    try:
        html = fetch_html()
        meetings = parse(html)
    except Exception as e:  # noqa: BLE001
        print(f"[fetch_fomc] 抓取失败：{e}", file=sys.stderr)
        meetings = []

    if not meetings:
        print("[fetch_fomc] 未取到任何会议，写入空结果", file=sys.stderr)

    nxt = [m for m in meetings if m["decision_us"] >= today.isoformat()]
    prev = [m for m in meetings if m["decision_us"] < today.isoformat()]
    payload = dict(
        source=URL, fetched_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        today=today.isoformat(), meetings=meetings,
        next=nxt[0] if nxt else None,
        next_minutes=next((m for m in meetings
                           if m["minutes_us"] >= today.isoformat()), None),
        last=prev[-1] if prev else None,
    )
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    n = payload["next"]
    print(f"[fetch_fomc] 共 {len(meetings)} 次会议 → {args.out}")
    if n:
        d = (dt.date.fromisoformat(n["decision_us"]) - today).days
        print(f"[fetch_fomc] 下次决议：美东 {n['decision_us']} / 北京 {n['decision_cn']}"
              f"（{d} 天后）{' 含点阵图+经济预测' if n['sep'] else ''}")


if __name__ == "__main__":
    main()
