#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
westock CLI 的轻量封装：命令执行 + markdown 表格解析。

所有上层脚本（fetch_technical / fetch_daily）共用这一层，
避免重复实现解析逻辑，也方便统一做容错与重试。
"""

import subprocess


def run(cmd, retries=1):
    """执行 westock 命令并返回 stdout。失败重试一次。"""
    for attempt in range(retries + 1):
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        out = proc.stdout or ""
        if out.strip():
            return out
    return ""


def parse_md_table(text):
    """
    把 westock 输出的 markdown 表格解析为 list[dict]。

    注意：外汇/期货行情的 marketStatus 字段内含竖线（如
    "2026-09-14 10:47:58|USDCNY_open_交易中"），会多切出一个单元格，
    因此解析前先做一次净化。
    """
    import re as _re
    text = _re.sub(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\|", r"\1 ", text)
    rows, header = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = cells
            continue
        if len(cells) != len(header):
            continue
        if all(set(c) <= set("-: ") and c for c in cells):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def f(row, key, default=None):
    """取 float，失败返回 default。"""
    v = row.get(key)
    if v is None or v in ("-", "", "null", "None", "未公布"):
        return default
    try:
        return float(v)
    except ValueError:
        return default


def parse_events(text):
    """
    解析宏观事件类表格（含 ActualValue / ForecastValue / FormerValue /
    IndicatorName / OccurDate / OccurTime / Importance）。
    """
    out = []
    for r in parse_md_table(text):
        name = r.get("IndicatorName") or r.get("Event")
        if not name:
            continue
        out.append(dict(
            name=name,
            actual=r.get("ActualValue", "-"),
            forecast=r.get("ForecastValue", "-"),
            former=r.get("FormerValue", "-"),
            date=r.get("OccurDate", "-"),
            time=r.get("OccurTime", "-"),
            importance=r.get("Importance", "-"),
            area=r.get("AreaName", "-"),
        ))
    return out
