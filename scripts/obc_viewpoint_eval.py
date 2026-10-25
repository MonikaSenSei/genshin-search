#!/usr/bin/env python3
"""M4.6 step 3f: 观景点 channel (253) vs ViewCodex names/descs in index;
also MaterialCodex resolved names vs 背包(13)."""
import json, re, sqlite3, unicodedata, sys
sys.path.insert(0, 'scripts')
from obc_probe import channel_entries

def norm(s):
    s = unicodedata.normalize('NFKC', s or '').lower()
    s = re.sub(r'【[^】]*】', '', s)
    return re.sub(r'[\W_]+', '', s, flags=re.UNICODE)

# fetch channel 253 entries
node = channel_entries(253, 1, 200)['list'][0]
vp = node.get('list') or []
print('观景点 entries:', len(vp))
vp_names = {norm(it['title']): it['content_id'] for it in vp if norm(it['title'])}

EB = 'data/repo/ExcelBinOutput'
TM = 'data/repo/TextMap'
tm = json.load(open(f'{TM}/TextMapCHS.json', encoding='utf-8'))
db = sqlite3.connect('index/genshin.db')
bodies = {r[0] for r in db.execute('select body from docs')}

def rows(n):
    d = json.load(open(f'{EB}/{n}.json', encoding='utf-8'))
    return d if isinstance(d, list) else list(d.values())[0]

vc = rows('ViewCodexExcelConfigData')
named = inidx = both = 0
for r in vc:
    name = tm.get(str(r.get('nameTextMapHash', '')), '')
    desc = tm.get(str(r.get('descTextMapHash', '')), '').replace('\\n', '\n')
    n_ok = norm(name) in vp_names
    t_ok = desc in bodies
    if n_ok: named += 1
    if t_ok: inidx += 1
    if n_ok and t_ok: both += 1
print(f'ViewCodex: ent={len(vc)} name_on_景点={named} desc_in_index={inidx} jumpable_docs={both}')
