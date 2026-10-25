#!/usr/bin/env python3
"""Verify quest join results via wiki search: unmatched -> really absent?
matched -> does the entry really correspond?"""
import sys, json, time, re, random
sys.path.insert(0, 'scripts')
from obc_probe import get
from urllib.parse import quote
W = "https://act-api-takumi.mihoyo.com/hoyowiki/genshin/wapi"

def search(kw):
    d = get(f"{W}/search?app_sn=ys_obc&keyword={quote(kw)}")
    return (d.get('data') or {}).get('list') or []

m = json.load(open('data/obc_quest_match.json'))
random.seed(7)
un = [t for t in m['unmatched'] if '$' not in t]
def clean(h):
    s = re.sub(r'</?em>', '', h.get('name', ''))
    return s.replace(' ', '').replace('！', '').replace('!', '')

print("== UNMATCHED samples ==")
for kw in random.sample(un, 6):
    hits = search(kw)
    kwc = kw.replace(' ', '').replace('！', '').replace('!', '')
    exact = [h for h in hits if kwc in clean(h)]
    print(f"{kw}: hits={len(hits)} exact_title={len(exact)}")
    for h in hits[:3]:
        print('   ', h.get('entry_page_id'), re.sub(r'</?em>', '', h.get('name', ''))[:50], [mm.get('id') for mm in (h.get('menus') or [])])
    time.sleep(0.5)
print("== MATCHED samples ==")
for kw, cid in random.sample(list(m['matched'].items()), 4):
    hits = search(kw)
    print(f"{kw} (assigned content_id={cid}) search hits={len(hits)}")
    for h in hits[:3]:
        print('   ', h.get('entry_page_id'), re.sub(r'</?em>', '', h.get('name', ''))[:50])
    time.sleep(0.5)
