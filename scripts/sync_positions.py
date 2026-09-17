import json, datetime, pathlib

HOLD = json.loads(pathlib.Path('/tmp/cloud_holdings.json').read_text())
WATCH = json.loads(pathlib.Path('/tmp/cloud_watchlist.json').read_text())
P = pathlib.Path('data/positions.json')
old = json.loads(P.read_text())
old_h = {h['code']: h for h in old.get('holdings', [])}
old_w = {w['code']: w for w in old.get('watchlist', [])}

def num(v):
    f = float(v)
    return int(f) if f == int(f) else f

holdings = []
for h in HOLD:
    o = old_h.get(h['code'], {})
    holdings.append({
        "code": h['code'], "name": h['name'], "market": h['market'],
        "asset_type": h['asset_type'], "shares": num(h['shares']),
        "cost_price": num(h['cost_price']), "currency": h['currency'],
        # 云端 note 为 null 时保留本地已确认的口径说明（如做 T 摊薄致成本为负、部分标的无行情数据）
        "note": h['note'] if h['note'] else o.get('note'),
    })

watchlist = []
for w in WATCH:
    o = old_w.get(w['code'], {})
    watchlist.append({
        "code": w['code'], "name": w['name'], "market": w['market'],
        "asset_type": w['asset_type'], "tags": w['tags'] or [],
        "reason": w.get('reason') or o.get('reason'),
    })

out = {
    "_note": "云端 holdings / watchlist 两张表的本地镜像，App 构建用。改动请同步云端，两边保持一致。",
    "synced_at": datetime.datetime.now().replace(microsecond=0).isoformat(),
    "holdings": holdings,
    "watchlist": watchlist,
}
P.write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(f"positions.json 已刷新：holdings {len(holdings)} 条 / watchlist {len(watchlist)} 条")
