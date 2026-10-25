#!/usr/bin/env python3
"""Inventory-style OBC item detail probe: enumerate component schemas per entry type."""
import sys, json, time
sys.path.insert(0, 'scripts')
from obc_probe import get

def entry_page(eid):
    return get(f"https://act-api-takumi.mihoyo.com/hoyowiki/genshin/wapi/entry_page?entry_page_id={eid}&app_sn=ys_obc")["data"]["page"]

samples = [
    ('武器-苍耀', 505478), ('武器-香韵奏者', 505323),
    ('食物-仙茗酥', 510043), ('背包-吞吞鲸', 510128), ('圣遗物-血红之证', 509294),
]
for label, eid in samples:
    p = entry_page(eid)
    print('=' * 24, label, p.get('name'), 'icon=' , bool(p.get('icon_url')))
    for m in p['modules']:
        for c in (m.get('components') or []):
            cid = c.get('component_id')
            data = c.get('data')
            try:
                d = json.loads(data) if isinstance(data, str) else data
            except Exception:
                d = data
            if isinstance(d, dict):
                info = {k: (str(v)[:60] + ('…' if len(str(v)) > 60 else '')) for k, v in list(d.items())[:14]}
                print(f'  [{m.get("name","")}] {cid} keys={list(d.keys())}')
                for k, v in list(info.items())[:10]:
                    print('      ', k, '=', v)
            else:
                print(f'  [{m.get("name","")}] {cid} rawlen={len(str(d))} sample={str(d)[:100]}')
    time.sleep(0.5)
