#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标的清单加载器。

设计原则：仓库内不存放任何个人标的与持仓信息。
- 持仓 / 观察池：直接读 data/positions.json（云端 holdings/watchlist 的本地镜像，
  该文件在 .gitignore 中，永不入库），因此无需手工维护
- AI 产业链篮子 / 对冲篮子：读 config/targets.json（同样不入库）；
  该文件缺失时回退到 config/targets.example.json 的示例清单

自定义方法：复制 config/targets.example.json 为 config/targets.json 后按需修改。
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSITIONS = os.path.join(ROOT, "data", "positions.json")
CONFIG = os.path.join(ROOT, "config", "targets.json")
EXAMPLE = os.path.join(ROOT, "config", "targets.example.json")


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return default


def _pairs(items):
    out = []
    for it in items or []:
        code, name = it.get("code"), it.get("name")
        if code and name:
            out.append((code, name))
    return out


def positions():
    """云端持仓/观察池镜像；不存在时返回空结构。"""
    return _load(POSITIONS, {"holdings": [], "watchlist": []})


def config():
    """个人篮子配置；无 config/targets.json 时用示例清单兜底。"""
    return _load(CONFIG, None) or _load(EXAMPLE, {})


def holdings():
    """持仓标的 [(code, name)]，来自 data/positions.json。"""
    return _pairs(positions().get("holdings"))


def watchlist():
    """观察池标的 [(code, name)]，来自 data/positions.json。"""
    return _pairs(positions().get("watchlist"))


def ai_a():
    """A 股 AI 产业链代表标的 [(code, name)]。"""
    return _pairs(config().get("ai_a"))


def ai_chain():
    """核心 AI 算力链映射 {code: name}，用于集中度口径。"""
    out = {}
    for it in config().get("ai_chain") or []:
        if it.get("code") and it.get("name"):
            out[it["code"]] = it["name"]
    return out


def hedge():
    """对冲篮子 [(code, name, bucket)]。"""
    out = []
    for it in config().get("hedge") or []:
        if it.get("code") and it.get("name"):
            out.append((it["code"], it["name"], it.get("tag") or "其他"))
    return out


if __name__ == "__main__":
    print(f"持仓 {len(holdings())} 只 | 观察池 {len(watchlist())} 只 | "
          f"AI链表 {len(ai_a())} 只 | 算力链核心 {len(ai_chain())} 只 | "
          f"对冲篮子 {len(hedge())} 只")
