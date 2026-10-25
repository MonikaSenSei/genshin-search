#!/usr/bin/env python3
"""M4.6 step 3e: item-layer coverage. For each entity table:
 - how many of its desc/name texts are IN our index (jumpable docs)
 - how many of its names match an OBC entry title in the mapped channel
 -> intersection = docs that could get a verified jump URL."""
import json, os, re, sqlite3, unicodedata, collections, sys

EB = 'data/repo/ExcelBinOutput'
TM = 'data/repo/TextMap'

def norm(s):
    s = unicodedata.normalize('NFKC', s or '').lower()
    s = re.sub(r'【[^】]*】', '', s)          # OBC decorates NPC titles: 逢岩【千岩军教头】
    return re.sub(r'[\W_]+', '', s, flags=re.UNICODE)

tm = json.load(open(f'{TM}/TextMapCHS.json', encoding='utf-8'))
tmm = json.load(open(f'{TM}/TextMap_MediumCHS.json', encoding='utf-8'))
tm_all = {**tmm, **tm}

db = sqlite3.connect('index/genshin.db')
bodies = {r[0] for r in db.execute('select body from docs')}

obc = json.load(open('data/obc_channel_entries.json'))
obc_names = {}
for ch in ('5', '25', '218', '21', '13', '20', '6'):
    s = set()
    for it in obc[ch]:
        s.add(norm(it['title']))
        a = it.get('alias_name') or ''
        if a:
            for part in re.split(r'[;,，、]', a):
                s.add(norm(part))
    obc_names[ch] = {x for x in s if x}
    print(f'OBC ch {ch}: {len(obc_names[ch])} distinct normalized names (from {len(obc[ch])} entries)')

def table_rows(name):
    d = json.load(open(f'{EB}/{name}.json', encoding='utf-8'))
    return d if isinstance(d, list) else list(d.values())[0]

def evaluate(label, table, ch, use_medium=False, desc_field='descTextMapHash'):
    rows = table_rows(table)
    n = len(rows)
    in_idx = 0
    named = 0
    both = 0
    for r in rows:
        name_s = tm_all.get(str(r.get('nameTextMapHash', '')), '')
        desc_s = tm_all.get(str(r.get(desc_field, '')), '') if r.get(desc_field) else ''
        t_in = (desc_s and desc_s in bodies)
        n_ok = bool(name_s) and norm(name_s) in obc_names[ch]
        if t_in: in_idx += 1
        if n_ok: named += 1
        if t_in and n_ok: both += 1
    print(f'{label:24} entities={n:>6}  desc_in_index={in_idx:>5}  name_on_wiki={named:>6}  both(jumpable docs)={both:>5}')

# weapons
evaluate('武器', 'WeaponExcelConfigData', '5')
# characters (playable+NPC avatars)
evaluate('角色/头像', 'AvatarExcelConfigData', '25')
# food/recipes
evaluate('料理', 'CookRecipeExcelConfigData', '21')
# materials (背包线)
evaluate('材料', 'MaterialExcelConfigData', '13')
# material codex (the actual codex docs in index)
evaluate('材料图鉴', 'MaterialCodexExcelConfigData', '13')
# view codex
evaluate('ViewCodex', 'ViewCodexExcelConfigData', '13')
# NPC names live in TextMap_Medium; no desc -> name join only
rows = table_rows('NpcExcelConfigData')
named = sum(1 for r in rows if norm(tm_all.get(str(r.get('nameTextMapHash', '')), '')) in obc_names['20'])
print(f'{"NPC":24} entities={len(rows):>6}  name_on_wiki={named:>6}')
