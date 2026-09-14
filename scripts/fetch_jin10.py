#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取金十数据财经日历（rili.jin10.com）「大事」页签。

背景：
  金十的公开接口（flash-api / rili-api / api.jin10.com）已全部加签名，
  直接 HTTP 请求拿不到数据；且日历明细在登录墙之后。
  因此本脚本走**真实 Chrome + CDP**，复用已登录的浏览器配置。

抓取内容：
  1. 「大事」页签下今天 + 未来若干天的事件（时间 / 地区 / 事件名）
  2. 央行政策利率表（公开数据）

用法：
  python scripts/fetch_jin10.py [--days 6] [--tab 大事]
产出：
  data/jin10.json
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://rili.jin10.com/"
LOGIN_WALL = "请登录后查看金十财经日历"

JS_ROWS = """
(()=>{
  const rows=[];
  document.querySelectorAll('.jin-table-row').forEach(r=>{
    const cells=[...r.querySelectorAll('.cell')].map(c=>(c.innerText||c.textContent||'').replace(/\\s+/g,' ').trim());
    if(cells.length<3) return;
    const time=cells[0], area=cells[1]||'';
    if(!/^(\\d{1,2}:\\d{2}|待定|全天)$/.test(time)) return;
    // 正文在第 3 或第 4 格（中间可能有空的重要性列），取最长的一段
    const cand=cells.slice(2).filter(Boolean);
    if(!cand.length) return;
    const body=cand.sort((a,b)=>b.length-a.length)[0];
    const title=body.replace(/查看数据库\\s*/g,'').trim();
    if(!title) return;
    rows.push({time:time, area:area, title:title.slice(0,200)});
  });
  return JSON.stringify(rows);
})()"""

JS_BANKS = """
(()=>{
  const out=[];
  document.querySelectorAll('.jin-table-row, tr').forEach(r=>{
    const cells=[...r.querySelectorAll('.cell, td')].map(c=>(c.innerText||c.textContent||'').trim());
    if(cells.length<3) return;
    const bank=cells[0], rate=cells[1]||'', chg=cells[2]||'';
    if(!/[\\u4e00-\\u9fa5]/.test(bank)) return;          // 央行名必须含中文
    if(!/^[\\d.]+%?$/.test(rate)) return;               // 利率形如 3.75 或 3.75%
    if(!/^[\\d]{1,2}-[\\d]{1,2}$|^[\\d]{4}-[\\d]{1,2}-[\\d]{1,2}$/.test(chg)) return;
    out.push({bank:bank, rate:rate, changed:chg});
  });
  return JSON.stringify(out);
})()"""


def js(page, expr, default=None, tries=2):
    for _ in range(tries):
        try:
            v = page.eval(expr)
            if v is None:
                time.sleep(1.5)
                continue
            if not isinstance(v, str):
                return v
            s = v.strip()
            if s in ("", "null", "undefined"):
                return default
            try:
                return json.loads(s)
            except Exception:
                return s
        except Exception:
            time.sleep(1.5)
    return default


def click_text(page, txt, exact=True):
    """点击页面里文案完全等于 txt 的叶子节点。"""
    return js(page, """
    (()=>{
      const el=[...document.querySelectorAll('*')].find(e=>e.children.length===0&&(e.textContent||'').trim()===%s);
      if(el){ el.click(); return true; }
      return false;
    })()""" % json.dumps(txt, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--days", type=int, default=6, help="除今天外再抓几天（滑块最多 6 天）")
    ap.add_argument("--tab", default="大事")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    result = dict(source=URL, tab=args.tab, date=args.date,
                  fetched_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  ok=False, need_login=None, events=[], banks=[], note="")

    if not cdp.port_alive():
        if not cdp.ensure_chrome():
            result["note"] = "未检测到调试浏览器（需 Chrome 带 --remote-debugging-port=9222）"
            _dump(result, args.out)
            print("[jin10] " + result["note"], file=sys.stderr)
            return

    page = cdp.attach(new_url=URL, wait=5)
    try:
        time.sleep(3)
        wall = LOGIN_WALL in (page.text(2000) or "")
        result["need_login"] = wall

        # 切到「大事」页签
        click_text(page, args.tab)
        time.sleep(3)

        base = dt.date.fromisoformat(args.date)
        all_events = []
        for k in range(0, args.days + 1):
            day = base + dt.timedelta(days=k)
            if k > 0:
                # 点日期滑块上对应的一天
                ok = click_text(page, str(day.day))
                time.sleep(2.5)
                if not ok:
                    break
            rows = js(page, JS_ROWS, default=[], tries=2) or []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                all_events.append(dict(date=day.isoformat(), **r))
            if not rows:
                # 该日无大事，属正常
                pass

        # 去重（切日期后页面可能重复渲染）
        seen, uniq = set(), []
        for e in all_events:
            key = (e["date"], e["time"], e["title"][:40])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(e)
        result["events"] = uniq

        # 央行利率表（在「宏观数据」页签下）
        click_text(page, "宏观数据")
        time.sleep(3)
        result["banks"] = js(page, JS_BANKS, default=[], tries=2) or []

        result["ok"] = bool(result["events"]) or bool(result["banks"])
        if wall:
            result["note"] = "金十未登录，日历明细可能不完整；央行利率表为公开数据。"
        else:
            result["note"] = (f"已取到「{args.tab}」事件 {len(result['events'])} 条、"
                              f"央行利率 {len(result['banks'])} 条。")
    except Exception as e:  # noqa: BLE001
        result["note"] = f"抓取异常：{str(e)[:150]}"
    finally:
        page.close()

    _dump(result, args.out)
    print(f"[jin10] {result['note']}")


def _dump(result, out):
    out = out or os.path.join(ROOT, "data", "jin10.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
