#!/usr/bin/env python3
"""M4.6 step 3c: quest coverage, title-composition-aware join.
OBC quest entries name acts as 组合式: '第一章 第四幕「我们终将重逢」', '森林书 第三章「…」'
or bare. Build all candidate keys per entry (full title, 「…」 segments, tail after
第N幕/第N章, series-qualified), normalized, then match index 任务「X」 titles.
Outputs data/obc_quest_match.json (title -> content_id) and stats."""
import sqlite3, json, re, unicodedata, collections, sys

DB = 'index/genshin.db'

def norm(s):
    s = unicodedata.normalize('NFKC', s).lower()
    return re.sub(r'[\W_]+', '', s, flags=re.UNICODE)

def keys_for(title):
    """candidate join keys for one OBC entry title"""
    ks = {norm(title)}
    for seg in re.findall(r'[「『]([^」』]+)[」』]', title):
        ks.add(norm(seg))
    m = re.search(r'第[一二三四五六七八九十百千0-9]+[章幕折卷集]序?[·.:：\s]*(.{2,40})$', title)
    if m:
        ks.add(norm(m.group(1)))
    return {k for k in ks if k}

data = json.load(open('data/obc_channel_entries.json'))
obc = collections.defaultdict(list)
for it in data['43']:
    for k in keys_for(it['title']):
        obc[k].append((it['content_id'], it['title']))

db = sqlite3.connect(DB)
idx = db.execute("select source, count(*) c from docs where source like '任务「%' group by 1").fetchall()

matched, unmatched = {}, []
for src, c in idx:
    m = re.match(r'任务「(.+)」$', src)
    title = m.group(1) if m else src[len('任务「'):]
    n = norm(title)
    hit = None
    if n in obc:
        hit = obc[n][0]
    else:
        # containment fallback: title contained in some bracketed/segment key
        cands = [(len(k), v[0]) for k, v in obc.items() if len(k) >= 4 and (n in k or (k in n and len(k) >= max(4, len(n) - 2)))]
        if cands:
            hit = min(cands)[1]
    if hit:
        matched[title] = hit
    else:
        unmatched.append((title, c))

print(f"titles: {len(idx)}  matched: {len(matched)}  unmatched: {len(unmatched)}")
tot = sum(c for _, c in idx)
md = sum(c for s, c in idx if s in matched or s.replace('任务「', '', 1).rstrip('」') in matched)
print(f"docs: total={tot} matched≈{md}")
unmatched.sort(key=lambda x: -x[1])
print("top unmatched:", *[f'\n  {c} {t}' for t, c in unmatched[:25]])
json.dump({'matched': matched, 'unmatched': [t for t, _ in unmatched]},
          open('data/obc_quest_match.json', 'w'), ensure_ascii=False, indent=1)
print('saved data/obc_quest_match.json')
