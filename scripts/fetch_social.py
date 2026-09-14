#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
社媒博主 T-1 更新抓取。

基于 CDP 真实浏览器（复用用户 Chrome 登录态），抓取抖音 / 小红书 / 雪球 / 微博
关注博主的最近发布内容，筛选出 T-1（及当天）更新的条目。

设计要点：
  1. 只存 platform_uid，昵称每次抓取实时反查 —— 博主改名不会断链，且能报出改名。
  2. 抓不到就是抓不到，明确标记 status，绝不编造。
  3. 每个平台一个 adapter，新增平台只需加一个函数。

用法：
  python scripts/fetch_social.py --date 2026-09-14 [--window 1] [--max-items 4]
输出：
  data/social_YYYYMMDD.json
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# 关注博主清单：优先读 data/creators.json（用户专属配置，git 忽略），
# 文件不存在时回退到下面的默认清单。改动博主请改 creators.json，与云端 creators 表保持一致。
def _load_creators():
    path = os.path.join(DATA, "creators.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                items = [(c.get("platform"), c.get("platform_uid"))
                         for c in json.load(fh) if c.get("enabled", True)]
            items = [(p, u) for p, u in items if p and u]
            if items:
                return items
        except Exception:  # noqa: BLE001
            pass
    return _DEFAULT_CREATORS


_DEFAULT_CREATORS = [
    # 示例占位：真实清单放 data/creators.json（git 忽略）。platform 取值：
    #   douyin（抖音号） / xhs（小红书号） / xueqiu（雪球数字ID） / weibo（微博主页数字ID）
    # 微信公众号不可行：腾讯无「按公众号拉文章」的开放接口，登录态也解不开；
    # 搜狗微信是唯一免登录入口但索引滞后数月，拿不到 T-1 内容等同无效（详见 fetch_wechat 注释）。
    # ("douyin", "123456789"),
    # ("xhs", "your_xhs_id"),
    # ("xueqiu", "12345678"),
    # ("weibo", "1234567890"),
]

CREATORS = _load_creators()

PLATFORM_CN = {"douyin": "抖音", "xhs": "小红书", "xueqiu": "雪球", "weibo": "微博", "wechat": "公众号"}


# ---------------------------------------------------------------- 时间解析
def parse_when(raw, today):
    """把各种相对/绝对时间文案解析成 YYYY-MM-DD。解析不了返回 None。"""
    if not raw:
        return None
    s = str(raw).strip()
    s = re.sub(r"^编辑于\s*", "", s)          # 小红书：「编辑于 05-14」
    s = re.sub(r"^(今天|昨天|前天)\s*", r"\1", s)
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        # 搜狗微信会给出「2026-2-25」这种不补零的格式，统一补零
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{1,2})-(\d{1,2})(?:\s|$)", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        y = today.year
        try:
            dt = datetime(y, mo, d).date()
        except ValueError:
            return None
        # 若算出来比今天还晚，说明是去年的
        if dt > today.date():
            dt = datetime(y - 1, mo, d).date()
        return dt.isoformat()
    if "刚刚" in s or "分钟前" in s or "小时前" in s:
        return today.date().isoformat()
    if "昨天" in s:
        return (today - timedelta(days=1)).date().isoformat()
    if "前天" in s:
        return (today - timedelta(days=2)).date().isoformat()
    m = re.search(r"(\d+)\s*天前", s)
    if m:
        return (today - timedelta(days=int(m.group(1)))).date().isoformat()
    return None


# ---------------------------------------------------------------- 通用工具
def js(page, expr, default=None, tries=1):
    """执行 JS 并解析结果。兼容 JSON 字符串与裸字符串两种返回。"""
    for i in range(tries):
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
                return s  # 裸字符串（JS 侧未 JSON.stringify）
        except Exception:
            time.sleep(1.5)
    return default


def blocked(page, keywords=("请登录后", "验证码", "存在风险", "前方有点拥堵")):
    """页面是否被登录墙/风控拦截。"""
    txt = ""
    try:
        txt = page.text(1500) or ""
    except Exception:
        return False
    return any(k in txt for k in keywords)


# ---------------------------------------------------------------- 抖音
def fetch_douyin(dy_id, today, max_items, page):
    """抖音号 → sec_uid → 主页 → 前 N 条作品 → 逐条取发布时间。"""
    out = {"platform_uid": dy_id, "status": "ok", "nickname": None,
           "resolved_uid": None, "home_url": None, "posts": [], "note": None}

    # 1) 搜索解析 sec_uid（抖音搜索偶发空结果，重试 2 次）
    info = None
    for attempt in range(3):
        page.goto(f"https://www.douyin.com/search/{dy_id}?type=user", wait=6 + attempt * 3)
        info = js(page, """
    (()=>{
      const links=[...document.querySelectorAll('a[href*="/user/MS4w"]')].map(a=>a.getAttribute('href'));
      let sec=null;
      if(links.length){ const m=links[0].match(/\\/user\\/(MS4w[A-Za-z0-9_-]+)/); if(m) sec=m[1]; }
      // 昵称：找紧邻「抖音号: xxx」的那个卡片
      let nick=null;
      const els=[...document.querySelectorAll('*')].filter(e=>e.children.length===0&&(e.textContent||'').trim()===('抖音号: %s')||(e.textContent||'').trim()===('抖音号：%s'));
      if(els.length){
        let n=els[0];
        for(let i=0;i<6&&n;i++){
          const t=(n.innerText||'').split('\\n').map(x=>x.trim()).filter(Boolean);
          if(t.length){ nick=t[0]; break; }
          n=n.parentElement;
        }
      }
      return JSON.stringify({sec:sec, nick:nick, blocked:(document.body.innerText||'').includes('验证码')});
    })()""" % (dy_id, dy_id), tries=2)
        if info and info.get("sec"):
            break
        time.sleep(2)

    if not info or not info.get("sec"):
        out["status"] = "login_required" if (info or {}).get("blocked") else "not_found"
        out["note"] = "搜索未解析出主页（可能需要登录或账号不存在）"
        return out

    out["resolved_uid"] = info["sec"]
    out["nickname"] = info.get("nick")
    out["home_url"] = f"https://www.douyin.com/user/{info['sec']}"

    # 2) 主页取作品列表
    page.goto(out["home_url"], wait=7)
    if blocked(page, ("验证码",)):
        out["status"] = "login_required"
        out["note"] = "主页被风控拦截"
        return out
    # 作品列表是懒加载，等 scroll-list 出现（实测 7 秒常不够，10+ 秒才渲染）
    try:
        page.wait_for("(()=>{return document.querySelectorAll('[data-e2e=scroll-list] > li').length>0})()",
                      timeout=18)
    except Exception:
        time.sleep(3)
    # 主页 h1 就是昵称（约 6 秒后渲染），title 形如「许戈的抖音 - 抖音」作兜底
    try:
        page.wait_for("(()=>{const h=document.querySelector('h1');return !!(h&&h.innerText.trim())})()",
                      timeout=20)
    except Exception:
        pass
    nick = js(page, """(()=>{
      const h=document.querySelector('h1');
      if(h&&h.innerText.trim()) return h.innerText.trim().slice(0,40);
      const m=(document.title||'').match(/^(.+?)的抖音/);
      return m?m[1].trim():null;
    })()""", tries=2)
    if nick:
        out["nickname"] = nick
    else:
        # 兜底：从搜索结果页文本里「昵称 + 抖音号: xxx」反查
        out["nickname"] = info.get("nick")

    items = js(page, """
    (()=>{
      const lis=[...document.querySelectorAll('[data-e2e=scroll-list] > li')]
        .filter(li=>!(li.innerText||'').includes('置顶'));   // 置顶作品时间很旧，跳过
      return JSON.stringify(lis.slice(0,%d).map(li=>{
        const a=li.querySelector('a[href*="/video/"], a[href*="/note/"]');
        const img=li.querySelector('img');
        return {href:a?a.getAttribute('href'):null,
                alt:img?img.getAttribute('alt'):null,
                txt:(li.innerText||'').replace(/\\s+/g,' ').trim().slice(0,120)};
      }));
    })()""" % max_items, default=[], tries=2)

    # 3) 逐条进视频页取发布时间
    for it in (items or []):
        href = it.get("href")
        if not href:
            continue
        url = "https:" + href if href.startswith("//") else href
        if not url.startswith("http"):
            url = "https://www.douyin.com" + href
        try:
            p2 = cdp.attach(new_url=url)
            try:
                p2.wait_for("(document.body.innerText||'').includes('发布时间')", timeout=15)
            except Exception:
                time.sleep(3)
            d = js(p2, """
            (()=>{
              const t=(document.body.innerText||'');
              const m=t.match(/发布时间[:：]\\s*([0-9]{4}-[0-9]{2}-[0-9]{2})/);
              const og=document.querySelector('meta[property="og:title"], meta[name="description"]');
              const h=document.querySelector('h1');
              // 抖音 AI 章节要点（口播内容总结）：从「章节要点」到「内容由 AI 生成」之间
              let chapter=null;
              const cm=t.match(/章节要点([\\s\\S]*?)(?:内容由\\s*AI\\s*生成|内容由AI生成)/);
              if(cm) chapter=cm[1].replace(/[ \\t]+/g,' ').replace(/\\s*\\n\\s*/g,'\\n').trim().slice(0,600);
              // 视频描述全文
              const de=document.querySelector('[data-e2e="video-desc"]') || document.querySelector('.video-info-detail');
              const desc=de?(de.innerText||'').trim().slice(0,400):null;
              return JSON.stringify({pub:m?m[1]:null,
                                     title:(og&&og.content)?og.content.trim().slice(0,100):(h?h.innerText.trim().slice(0,100):null),
                                     chapter:chapter, desc:desc});
            })()""", tries=3)
            p2.close()
        except Exception as e:
            out["posts"].append({"title": (it.get("alt") or it.get("txt") or "")[:80],
                                 "url": url, "published": None, "err": str(e)[:80]})
            continue
        title = ((d or {}).get("title") or it.get("alt") or it.get("txt") or "")
        # og:title 常带尾巴：「标题 - 昵称于20260914发布在抖音，…」或「标题 - 昵称（被截断）」
        title = re.sub(r"\s*-\s*.*?于\d{8}发布在抖音.*$", "", title)
        if out.get("nickname"):
            title = re.sub(r"\s*-\s*%s.*$" % re.escape(out["nickname"][:4]), "", title)
        title = re.sub(r"\s*-\s*抖音\s*$", "", title).strip()
        title = re.sub(r"^%s[:：]" % re.escape(out["nickname"] or ""), "", title).strip()
        # AI 章节要点 → 内容总结；描述去话题标签 → 正文
        chapter = (d or {}).get("chapter")
        summary = None
        if chapter:
            lines = [x.strip() for x in chapter.split("\n") if x.strip()]
            if lines and not re.match(r"^\d{1,2}:\d{2}", lines[0]):
                summary = lines[0]           # 首行无时间戳 = 视频总述
        desc = (d or {}).get("desc")
        content = re.sub(r"#\S+", "", desc or "").strip() if desc else None
        if content and len(content) < 8:
            content = None                   # 去完标签剩不下几个字 = 纯标签文案
        out["posts"].append({
            "title": title[:100] or (it.get("txt") or "")[:100],
            "url": url,
            "published": (d or {}).get("pub"),
            "when_raw": (d or {}).get("pub"),
            "summary": summary,              # 抖音 AI 章节要点总述
            "chapter": chapter,              # 完整分章节要点（含时间戳）
            "content": content,              # 描述去话题标签后的正文
        })
        # 已经明显早于窗口，后面的更老，可以停
        if (d or {}).get("pub") and parse_when((d or {}).get("pub"), today):
            pass
    return out


# ---------------------------------------------------------------- 小红书
def fetch_xhs(xhs_id, today, max_items, page):
    """小红书号 → 搜索解析 user_id + token → 主页 → 前 N 条笔记 → 逐条取时间。"""
    out = {"platform_uid": xhs_id, "status": "ok", "nickname": None,
           "resolved_uid": None, "home_url": None, "posts": [], "note": None}

    # 1) 搜索
    page.goto(f"https://www.xiaohongshu.com/search_result?keyword={xhs_id}&type=user", wait=7)
    info = js(page, """
    (()=>{
      const as=[...document.querySelectorAll('a[href*="/user/profile/"]')];
      let uid=null, token=null, url=null;
      for(const a of as){
        const h=a.getAttribute('href')||'';
        const m=h.match(/\\/user\\/profile\\/([0-9a-f]{16,32})/);
        const t=h.match(/xsec_token=([^&]+)/);
        if(m){ uid=m[1]; if(t){token=t[1]; url=h; break;} }
      }
      const t=(document.body.innerText||'');
      const nm=t.match(new RegExp('小红书号[:：]\\\\s*%s'));
      let nick=null;
      if(nm){ const seg=t.slice(0,nm.index).split('\\n').map(x=>x.trim()).filter(Boolean); nick=seg.length?seg[seg.length-1]:null; }
      return JSON.stringify({uid:uid, token:token, url:url, nick:nick,
                             risk:t.includes('存在风险')||t.includes('未连接到服务器')});
    })()""" % re.escape(xhs_id), tries=2)

    if not info or not info.get("uid"):
        out["status"] = "login_required" if (info or {}).get("risk") else "not_found"
        out["note"] = "搜索未解析出主页"
        return out

    uid, token = info["uid"], info.get("token")
    out["resolved_uid"] = uid
    out["home_url"] = f"https://www.xiaohongshu.com/user/profile/{uid}"

    # 2) 主页（必须带 xsec_token，否则会重定向到自己的主页）
    purl = out["home_url"]
    if token:
        purl += f"?xsec_token={token}&xsec_source=pc_search"
    page.goto(purl, wait=7)
    # 保险：无 token 或 token 失效时小红书会静默重定向到「自己」的主页，
    # 导致抓到完全错误的博主。这里校验一次，不一致就重试一轮搜索。
    landed = js(page, """(()=>{const m=location.href.match(/user\\/profile\\/([0-9a-f]{16,32})/); return m?m[1]:null})()""")
    if landed and landed != uid:
        out["note"] = f"主页被重定向到 {landed}（xsec_token 失效），已重试"
        page.goto(f"https://www.xiaohongshu.com/search_result?keyword={xhs_id}&type=user", wait=6)
        info = js(page, """
        (()=>{
          const as=[...document.querySelectorAll('a[href*="/user/profile/"]')];
          for(const a of as){
            const h=a.getAttribute('href')||'';
            const m=h.match(/\\/user\\/profile\\/([0-9a-f]{16,32})/);
            const t=h.match(/xsec_token=([^&]+)/);
            if(m&&t) return JSON.stringify({uid:m[1], token:t[1]});
          }
          return JSON.stringify({uid:null, token:null});
        })()""", tries=2)
        if not info or not info.get("uid") or not info.get("token"):
            out["status"] = "login_required"
            out["note"] = "重试后仍未取到有效主页 token"
            return out
        uid, token = info["uid"], info["token"]
        out["resolved_uid"] = uid
        out["home_url"] = f"https://www.xiaohongshu.com/user/profile/{uid}"
        page.goto(f"{out['home_url']}?xsec_token={token}&xsec_source=pc_search", wait=7)
        landed2 = js(page, """(()=>{const m=location.href.match(/user\\/profile\\/([0-9a-f]{16,32})/); return m?m[1]:null})()""")
        if landed2 and landed2 != uid:
            out["status"] = "login_required"
            out["note"] = f"重试后仍被重定向到 {landed2}"
            return out
    prof = js(page, """
    (()=>{
      const t=document.title||'';
      const nick=t.replace(/\\s*-\\s*小红书\\s*$/,'').trim();
      const items=[...document.querySelectorAll('.note-item')].slice(0,%d).map(e=>{
        const id=e.getAttribute('data-note-id')||e.getAttribute('note-id');
        const as=[...e.querySelectorAll('a')].map(a=>a.getAttribute('href')||'');
        let link=null;
        for(const h of as){ if(h.includes('/'+id+'?xsec_token=')||h.match(new RegExp('/'+id+'\\\\?xsec_token='))){ link=h; break; } }
        const titleEl=e.querySelector('.title, [class*=title], .footer .title');
        return {id:id, link:link, title:(titleEl?titleEl.innerText:(e.innerText||'')).replace(/\\s+/g,' ').trim().slice(0,110)};
      });
      return JSON.stringify({nick:nick, items:items, bad:(document.body.innerText||'').includes('未连接到服务器')});
    })()""" % max_items, tries=2)

    if not prof or prof.get("bad"):
        out["status"] = "login_required"
        out["note"] = "主页打开失败（可能被限流或需重新登录）"
        return out
    out["nickname"] = prof.get("nick") or info.get("nick")

    # 3) 逐条取时间
    for it in (prof.get("items") or []):
        link = it.get("link")
        if not link:
            out["posts"].append({"title": it.get("title"), "url": None, "published": None,
                                 "note": "未取到带 token 的链接"})
            continue
        url = link if link.startswith("http") else "https://www.xiaohongshu.com" + link
        try:
            p2 = cdp.attach(new_url=url)
            # 笔记正文用 innerText 读不到（渲染在隐藏层），只能从 DOM 节点取
            d = None
            for _ in range(6):
                d = js(p2, """
                (()=>{
                  const el=document.querySelector('.bottom-left .date') || document.querySelector('.date');
                  const when=el? (el.textContent||'').trim() : null;
                  const title=(document.title||'').replace(/\\s*-\\s*小红书\\s*$/,'').trim();
                  return JSON.stringify({when:when, title:title.slice(0,100)});
                })()""")
                if d and not isinstance(d, str) and d.get("when"):
                    break
                time.sleep(2)
            p2.close()
        except Exception as e:
            out["posts"].append({"title": it.get("title"), "url": url,
                                 "published": None, "err": str(e)[:80]})
            continue
        pub = parse_when((d or {}).get("when") if not isinstance(d, str) else None, today)
        out["posts"].append({
            "title": ((d or {}).get("title") or it.get("title") or "")[:100],
            "url": url,
            "published": pub,
            "when_raw": (d or {}).get("when") if not isinstance(d, str) else None,
        })
    return out


# ---------------------------------------------------------------- 雪球
def fetch_xueqiu(uid, today, max_items, page):
    """雪球主页无需登录即可读。"""
    out = {"platform_uid": uid, "status": "ok", "nickname": None,
           "resolved_uid": uid, "home_url": f"https://xueqiu.com/u/{uid}", "posts": []}
    page.goto(out["home_url"], wait=7)
    # 滚动加载，雪球时间线是懒加载的
    for _ in range(3):
        try:
            page.eval("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        time.sleep(1.5)
    prof = js(page, """
    (()=>{
      const t=document.title||'';
      const nick=t.replace(/\\s*-\\s*雪球\\s*$/,'').trim();
      const arts=[...document.querySelectorAll('.timeline__item, .article, [class*=timeline]')];
      let txt='';
      if(arts.length){
        txt=arts.map(a=>(a.innerText||'')).join('\\n');
      }
      if(txt.length<200) txt=(document.body.innerText||'');
      return JSON.stringify({nick:nick, items:[{txt:txt.replace(/\\s+/g,' ').slice(0,8000)}],
                             needLogin:(document.body.innerText||'').includes('立即登录/注册')});
    })()""", tries=2)

    if not prof:
        out["status"] = "error"
        out["note"] = "页面读取失败"
        return out
    out["nickname"] = prof.get("nick")
    # 雪球文本形如「昵称 + 时间 + ·来自Android + 正文」，正文在时间戳之后
    PAT = re.compile(r"(?:(\d{4})-)??(\d{1,2})-(\d{1,2})\s+\d{1,2}:\d{2}")
    nick = prof.get("nick") or ""
    for blk in (prof.get("items") or []):
        txt = blk.get("txt", "")
        hits = list(PAT.finditer(txt))
        for i, m in enumerate(hits):
            end = hits[i + 1].start() if i + 1 < len(hits) else len(txt)
            when = parse_when(m.group(0), today)
            body = txt[m.end():end]
            # 去掉来源标记、置顶标、昵称残留
            body = re.sub(r"^[·\s]*(来自|转自)\s*\S+", "", body).strip()
            body = re.sub(r"^置顶", "", body).strip()
            body = re.sub(r"^%s" % re.escape(nick), "", body).strip()
            body = re.sub(r"\s*\d+\s*$", "", body).strip()  # 尾部互动数
            if len(body) < 6:
                continue
            out["posts"].append({
                "title": body[:160],
                "url": out["home_url"],
                "published": when,
                "when_raw": m.group(0),
            })
            if len(out["posts"]) >= max_items:
                break
        if len(out["posts"]) >= max_items:
            break
    if not out["posts"]:
        out["status"] = "no_posts"
        out["note"] = "未解析出帖子（页面结构可能变化）"
    return out


# ---------------------------------------------------------------- 微博
def _weibo_clean(body, nick, when_raw):
    """去掉正文前缀（昵称/时间/来自 XXX）和尾部互动噪音。"""
    t = (body or "").replace("\u200b", "")
    if nick:
        t = re.sub(r"^\s*" + re.escape(nick) + r"\s*", "", t)
    if when_raw:
        t = re.sub(r"^\s*" + re.escape(when_raw) + r"\s*", "", t)
    t = re.sub(r"^\s*来自\s*\S+\s*", "", t)                 # 「来自 微博视频号」
    t = re.sub(r"\s*(\.\.\.展开|展开全文|收起)\s*$", "", t)
    t = re.sub(r"\s*展开\s*$", "", t)
    t = re.sub(r"\s*(转发|评论)\s*[\d.]*万?\s*$", "", t)     # 尾部计数
    return t.strip()


def fetch_weibo(uid, today, max_items, page):
    """微博个人主页（需登录态）。

    新版 UI 结构：article > .wbpro-feed-content 是正文，时间是一个叶子节点里的
    相对时间文案（刚刚/N分钟前/N小时前/今天 HH:MM/MM-DD）。主页懒加载，需滚动。
    """
    home = f"https://weibo.com/u/{uid}"
    out = {"platform_uid": uid, "status": "ok", "nickname": None,
           "resolved_uid": uid, "home_url": home, "posts": [], "note": None}
    page.goto(home, wait=9)

    prof = js(page, """
    (()=>{
      const t=document.title||'';
      const nick=t.replace(/^@/,'').replace(/\\s*的个人主页\\s*$/,'').trim();
      const body=(document.body.innerText||'');
      return JSON.stringify({nick:nick, needLogin:body.includes('请登录后使用'),
                             txt:body.replace(/\\s+/g,' ').slice(0,600)});
    })()""", tries=2)
    if not prof:
        out["status"] = "error"
        out["note"] = "页面求值失败"
        return out
    nick = prof.get("nick")
    # 未登录时 title 形如「- 微博」，不是真昵称
    out["nickname"] = None if (not nick or re.match(r"^-\s*微博$", nick)) else nick
    if prof.get("needLogin"):
        out["status"] = "login_required"
        out["note"] = "微博需要登录态，请在调试浏览器里登录一次 weibo.com"
        return out
    if blocked(page):
        out["status"] = "blocked"
        out["note"] = "微博页面被风控拦截"
        return out

    # 主页懒加载，滚两屏把最近的微博都拉出来
    for _ in range(3):
        try:
            js(page, "window.scrollTo(0, document.body.scrollHeight);", tries=1)
        except Exception:  # noqa: BLE001
            break
        time.sleep(2.0)

    items = js(page, """
    (()=>{
      const RE=/^(刚刚|\\d+秒前|\\d+分钟前|\\d+小时前|今天\\s|昨天\\s|前天\\s|\\d{1,2}-\\d{1,2}|\\d{4}-\\d{2}-\\d{2})/;
      const out=[];
      for(const a of document.querySelectorAll('article')){
        let when=null;
        for(const el of a.querySelectorAll('*')){
          if(el.children.length) continue;
          const s=(el.textContent||'').trim();
          if(s && RE.test(s)){ when=s; break; }
        }
        const c=a.querySelector('.wbpro-feed-content');
        const body=c ? (c.innerText||c.textContent||'') : (a.innerText||'');
        let link=null;
        for(const x of a.querySelectorAll('a')){
          const h=x.getAttribute('href')||'';
          if(/^\\/\\d+\\/[A-Za-z0-9]{6,}/.test(h)){
            link = h.startsWith('http') ? h : ('https://weibo.com'+h);
            break;
          }
        }
        if(!when && !body.trim()) continue;
        out.push({when:when, body:body.replace(/\\s+/g,' ').trim(), link:link});
      }
      return JSON.stringify(out);
    })()""", default=[], tries=2) or []
    if not isinstance(items, list):
        items = []

    for it in items:
        when_raw = (it.get("when") or "").strip()
        body = _weibo_clean(it.get("body"), out["nickname"], when_raw)
        if not body:
            continue
        out["posts"].append({
            "title": body[:160],
            "url": it.get("link") or home,
            "published": parse_when(when_raw, today),
            "when_raw": when_raw,
        })
        if len(out["posts"]) >= max_items:
            break
    if not out["posts"]:
        out["status"] = "no_posts"
        out["note"] = "未解析出微博内容（页面结构可能变化）"
    return out


# ---------------------------------------------------------------- 微信公众号
def fetch_wechat(name, today, max_items, page):
    """【已停用，2026-09-14】公众号抓取，保留实现以备将来接镜像源。

    为什么停用（结论：这条路走不通）
      1. 腾讯没有开放任何「按公众号拉取最新文章」的接口，第三方 MCP 也没有
         —— 企业微信那套是内部消息/文档，跟关注外部公众号是两回事。
      2. 加登录态也解不开：障碍不是身份认证，而是微信根本不对外暴露文章列表。
      3. 唯一免登录入口是搜狗微信（下面这条实现），实测 7 个号里 3 个能搜到，
         但**索引滞后严重**（最近一条常是几个月前），拿不到 T-1 更新。
         对「监控最新发布」这个目的来说，取不到最新 = 无效，故整块下线。

    保留的两个坑记在这里，将来真的接镜像源（雪球/头条同名号）时可复用：
      1. 搜狗会把「正文提到这个名字」的文章也搜出来 —— 必须用结果里
         span.all-time-y2 的实际公众号名做强校验，只留本号发布的内容。
      2. 搜狗限速很激进，间隔 <4 秒会直接断开 CDP 连接。
    """
    from urllib.parse import quote
    time.sleep(4.0)  # 搜狗限速很激进，间隔太短会直接断开连接
    query = f"https://weixin.sogou.com/weixin?type=2&query={quote(name)}"
    out = {"platform_uid": name, "status": "ok", "nickname": name,
           "resolved_uid": name, "home_url": query, "posts": [], "note": None}
    page.goto(query, wait=8)

    guard = js(page, """
    (()=>{
      const t=(document.body.innerText||'').replace(/\\s+/g,' ');
      return JSON.stringify({url:location.href, txt:t.slice(0,400)});
    })()""", tries=2) or {}
    gtxt = (guard.get("txt") or "") if isinstance(guard, dict) else str(guard)
    gurl = (guard.get("url") or "") if isinstance(guard, dict) else ""
    if "请输入验证码" in gtxt or "antispider" in gurl or "反爬" in gtxt:
        out["status"] = "blocked"
        out["note"] = "搜狗微信触发验证码，请稍后在调试浏览器里手动过一次"
        return out

    items = js(page, """
    (()=>{
      const out=[];
      for(const li of document.querySelectorAll('ul.news-list > li')){
        const box=li.querySelector('.txt-box'); if(!box) continue;
        const a=box.querySelector('h3 a'); if(!a) continue;
        const accEl=box.querySelector('.s-p .all-time-y2');
        const dtEl=box.querySelector('.s-p .s2');
        const sumEl=box.querySelector('p.txt-info');
        // 日期节点里混着一段 document.write(...) 脚本，正则只取真正的日期文案
        let dt = dtEl ? (dtEl.textContent||'').trim() : '';
        const dm = dt.match(/(\d{4}-\d{1,2}-\d{1,2}|\d+\s*(?:天前|小时前|分钟前)|昨天|今天)/);
        dt = dm ? dm[1] : dt.replace(/^[\s\S]*?\)\s*/, '').trim();
        let href=a.getAttribute('href')||'';
        if(href.indexOf('/link')===0) href='https://weixin.sogou.com'+href;
        out.push({
          title:(a.textContent||'').trim(),
          account: accEl ? (accEl.textContent||'').trim() : '',
          date: dt,
          summary: sumEl ? (sumEl.textContent||'').trim() : '',
          url: href
        });
      }
      return JSON.stringify(out);
    })()""", default=[], tries=2) or []
    if not isinstance(items, list):
        items = []

    norm = lambda s: re.sub(r"\s+", "", s or "")  # noqa: E731
    for it in items:
        if norm(it.get("account")) != norm(name):
            continue  # 只是提到了这个名字，不是本号发的
        when = parse_when(it.get("date"), today)
        title = (it.get("title") or "").strip()
        if not title:
            continue
        summary = (it.get("summary") or "").strip()
        out["posts"].append({
            "title": f"{title}　—　{summary}"[:200] if summary else title,
            "url": it.get("url") or query,
            "published": when,
            "when_raw": it.get("date"),
        })
        if len(out["posts"]) >= max_items:
            break
    if not out["posts"]:
        out["status"] = "no_posts"
        if items:
            out["note"] = ("搜狗微信只召回到「提及该名字」的文章，未收录该号作为发布方；"
                           "请确认公众号全称是否一致")
        else:
            out["note"] = "搜狗微信未收录该公众号（搜狗索引未覆盖）"
    return out


ADAPTERS = {"douyin": fetch_douyin, "xhs": fetch_xhs,
            "xueqiu": fetch_xueqiu, "weibo": fetch_weibo,
            "wechat": fetch_wechat}

STATE_PATH = os.path.join(DATA, "creators_state.json")


def load_creator_state():
    """上次成功抓到的博主昵称快照，用于改名检测。"""
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_creator_state(result, prev):
    """只在本次成功拿到昵称时才覆盖，避免把 null 写进去丢掉历史。"""
    state = dict(prev)
    for c in result.get("creators", []):
        key = f"{c.get('platform')}:{c.get('platform_uid')}"
        if not c.get("nickname"):
            continue
        state[key] = {
            "nickname": c["nickname"],
            "resolved_uid": c.get("resolved_uid"),
            "home_url": c.get("home_url"),
            "last_seen": result.get("date"),
        }
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"),
                    help="运行日 T，格式 YYYY-MM-DD")
    ap.add_argument("--window", type=int, default=1,
                    help="回溯天数，1 表示只看 T-1 和 T")
    ap.add_argument("--max-items", type=int, default=4, help="每个博主最多取几条")
    ap.add_argument("--platforms", default="", help="只跑指定平台，逗号分隔")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    today = datetime.strptime(args.date, "%Y-%m-%d")
    window = [ (today - timedelta(days=i)).date().isoformat() for i in range(0, args.window + 1) ]

    if not cdp.port_alive():
        print("[!] 未检测到调试浏览器，尝试拉起…", file=sys.stderr)
        if not cdp.ensure_chrome():
            print("[x] 无法启动 Chrome（需带 --remote-debugging-port=9222）", file=sys.stderr)
            sys.exit(2)

    wanted = [p.strip() for p in args.platforms.split(",") if p.strip()]
    todo = [c for c in CREATORS if not wanted or c[0] in wanted]

    prev_state = load_creator_state()
    page = cdp.attach(new_url="about:blank")
    result = {"date": args.date, "window": window, "creators": [], "errors": []}

    for platform, uid in todo:
        fn = ADAPTERS.get(platform)
        label = f"{PLATFORM_CN.get(platform, platform)} {uid}"
        if not fn:
            continue
        print(f"[·] {label} …", file=sys.stderr)
        try:
            rec = fn(uid, today, args.max_items, page)
        except Exception as e:
            # CDP 连接可能被风控打断（搜狗限速尤其容易），重开一个页面再试一次
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5)
            try:
                page = cdp.attach(new_url="about:blank")
                rec = fn(uid, today, args.max_items, page)
            except Exception as e2:
                rec = {"platform_uid": uid, "status": "error",
                       "note": f"{str(e)[:80]} / 重试后仍失败：{str(e2)[:80]}",
                       "nickname": None, "resolved_uid": None,
                       "home_url": None, "posts": []}
        rec["platform"] = platform
        # 只保留窗口内的
        rec["posts_window"] = [p for p in rec.get("posts", []) if p.get("published") in window]
        rec["posts_all"] = rec.pop("posts", [])
        # 改名检测：与上次成功抓到的昵称比对，改名会在日报里标出来
        key = f"{platform}:{uid}"
        old = (prev_state.get(key) or {}).get("nickname")
        if old and rec.get("nickname") and old != rec["nickname"]:
            rec["renamed"] = old
            print(f"    ⚠ 检测到改名：{old} → {rec['nickname']}", file=sys.stderr)
        result["creators"].append(rec)
        n = len(rec["posts_window"])
        print(f"    → {rec['status']}  昵称={rec.get('nickname')}  窗口内 {n} 条", file=sys.stderr)

    page.close()
    save_creator_state(result, prev_state)

    os.makedirs(DATA, exist_ok=True)
    out = args.out or os.path.join(DATA, f"social_{args.date.replace('-', '')}.json")
    # 只跑部分平台时，与已有结果合并，避免把其他平台的数据冲掉
    if wanted and os.path.exists(out):
        try:
            with open(out, encoding="utf-8") as fh:
                old = json.load(fh)
            bykey = {(c.get("platform"), c.get("platform_uid")): c
                     for c in (old.get("creators") or [])}
            for c in result["creators"]:
                bykey[(c.get("platform"), c.get("platform_uid"))] = c
            result["creators"] = list(bykey.values())
            result["window"] = old.get("window") or result["window"]
        except Exception:
            pass
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=1)
    print("written:", out)
    ok = sum(1 for c in result["creators"] if c["status"] == "ok")
    print(f"成功 {ok}/{len(result['creators'])}")


if __name__ == "__main__":
    main()
