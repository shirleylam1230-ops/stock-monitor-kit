#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""极简 Chrome DevTools Protocol 客户端。

为什么不用 agent-browser：
  本环境里 agent-browser 只能以无头模式运行（UA 暴露 HeadlessChrome、navigator.webdriver=true），
  会被抖音/小红书/金十这类站点风控拦死，而且 `--headed` / `--user-agent` 不生效。
  改用「真实 Chrome + 远程调试端口」：没有自动化指纹，且能直接复用用户已登录的浏览器配置目录。

依赖：websocket-client（装在 ~/.workbuddy/binaries/python/envs/default）
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request

import websocket  # type: ignore

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PROFILE = os.path.expanduser("~/.workbuddy/chrome-cdp")
DEFAULT_PORT = 9222


# ---------------------------------------------------------------- 进程管理
def port_alive(port=DEFAULT_PORT, timeout=2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ensure_chrome(port=DEFAULT_PORT, wait=25) -> bool:
    """确保存在一个带调试端口的真实 Chrome。已存在则直接复用。"""
    if port_alive(port):
        return True
    os.makedirs(PROFILE, exist_ok=True)
    # 不加 --restore-last-session：会话恢复会把博主监测时代遗留的抖音/微博/小红书
    # 旧标签页一起还原出来（2026-09-17 排查确认），博主模块已下线，只需干净启动。
    subprocess.Popen(
        [CHROME, f"--remote-debugging-port={port}", f"--user-data-dir={PROFILE}",
         "--no-first-run", "--no-default-browser-check"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(wait * 2):
        if port_alive(port, 1.0):
            return True
        time.sleep(0.5)
    return False


def sync_profile_from_user() -> str:
    """把用户主 Chrome 的登录态（cookie / 本地存储）复制到调试专用配置目录。

    前提：用户主 Chrome 已完全退出，否则 cookie 库可能处于写入中。
    """
    src = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    dst = PROFILE
    os.makedirs(os.path.join(dst, "Default"), exist_ok=True)
    n = 0
    for rel in ("Local State", "Default/Preferences", "Default/Secure Preferences",
                "Default/Web Data", "Default/Login Data", "Default/Cookies",
                "Default/Network/Cookies"):
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if os.path.exists(s):
            os.makedirs(os.path.dirname(d), exist_ok=True)
            try:
                shutil.copy2(s, d)
                n += 1
            except Exception:  # noqa: BLE001
                pass
    for rel in ("Default/Local Storage", "Default/Network"):
        s, d = os.path.join(src, rel), os.path.join(dst, rel)
        if os.path.isdir(s):
            try:
                shutil.copytree(s, d, dirs_exist_ok=True)
                n += 1
            except Exception:  # noqa: BLE001
                pass
    return f"已同步 {n} 项登录态文件到 {dst}"


# ---------------------------------------------------------------- HTTP 层
def _http(path, method="GET", port=DEFAULT_PORT, timeout=10):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", errors="ignore")
    return json.loads(body) if body.strip() else {}


def targets(port=DEFAULT_PORT):
    return [t for t in _http("/json", port=port) if t.get("type") == "page"]


def find_page(url_kw="", port=DEFAULT_PORT):
    for t in targets(port):
        if url_kw and url_kw not in t.get("url", ""):
            continue
        return t
    return None


def new_tab(url="about:blank", port=DEFAULT_PORT):
    try:
        return _http(f"/json/new?{url}", method="PUT", port=port)
    except Exception:  # noqa: BLE001
        return _http(f"/json/new?{url}", method="GET", port=port)


def close_tab(target_id, port=DEFAULT_PORT):
    try:
        _http(f"/json/close/{target_id}", port=port)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- WS 层
class Page:
    """绑定到一个页面 target 的 CDP 会话。"""

    def __init__(self, ws_url, timeout=30):
        self.ws = websocket.create_connection(ws_url, timeout=timeout,
                                              suppress_origin=True,
                                              max_size=64 * 1024 * 1024)
        self._id = 0
        self.target_id = None  # attach() 时填入，close() 时用于关标签页

    def call(self, method, params=None, timeout=30):
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:  # noqa: BLE001
                break
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(f"{method} 超时")

    def eval(self, expr, timeout=30, by_value=True):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": by_value,
                       "awaitPromise": True, "userGesture": True}, timeout=timeout)
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return res.get("value")

    def goto(self, url, wait=3.0, timeout=45):
        self.call("Page.enable")
        self.call("Page.navigate", {"url": url}, timeout=timeout)
        time.sleep(wait)
        return self

    def wait_for(self, js_cond, timeout=20, interval=0.6):
        """轮询直到 js_cond 求值为真，返回 True/False。"""
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.eval(f"!!({js_cond})"):
                    return True
            except Exception:  # noqa: BLE001
                pass
            time.sleep(interval)
        return False

    def text(self, limit=0):
        t = self.eval("document.body ? document.body.innerText : ''") or ""
        return t[:limit] if limit else t

    def close(self):
        """断开 WS 并关掉标签页（不关会无限堆积拖垮系统）。"""
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        if self.target_id:
            close_tab(self.target_id)


def attach(url_kw="", port=DEFAULT_PORT, new_url=None, wait=3.0):
    """打开/复用一个页面并返回 Page。"""
    t = None
    if new_url:
        t = new_tab(new_url, port=port)
    if not t:
        t = find_page(url_kw, port=port)
    if not t:
        t = new_tab(new_url or "about:blank", port=port)
        time.sleep(wait)
    ws = t.get("webSocketDebuggerUrl")
    if not ws:
        raise RuntimeError("该 target 没有 webSocketDebuggerUrl")
    pg = Page(ws)
    pg.target_id = t.get("id")
    return pg


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--url", default=None, help="打开该 URL 并输出文本")
    ap.add_argument("--eval", dest="js", default=None)
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--sync", action="store_true", help="从用户主 Chrome 同步登录态")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.sync:
        print(sync_profile_from_user())
    if not ensure_chrome(a.port):
        raise SystemExit("无法启动/连接调试 Chrome")
    print("CDP 就绪 →", _http("/json/version", port=a.port).get("Browser"))
    if a.list:
        for t in targets(a.port):
            print(" -", t.get("title", "")[:45], "|", t.get("url", "")[:70])
    if a.url or a.js or a.text:
        p = attach(new_url=a.url, port=a.port)
        if a.js:
            print(p.eval(a.js))
        if a.text or a.url:
            print(p.text(1500))
        p.close()
