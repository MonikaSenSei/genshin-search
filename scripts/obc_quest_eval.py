#!/usr/bin/env python3
"""M4.6 step 3b: join index quest-title sources against OBC 任务 channel entries.
Reports distinct-title and doc-level coverage; prints unmatched samples."""
import sqlite3, json, re, unicodedata, sys, collections

DB = 'index/genshin.db'
data = json.load(open('data/obc_channel_entries.json'))

def norm(s):
    s = unicodedata.normalize('NFKC', s)
    s = s.lower()
    s = re.sub(r'[\W_]+', '', s, flags=re.UNICODE)
    return s

obc = collections.defaultdict(list)
for it in data['43']:
    obc[norm(it['title'])].append((it['content_id'], it['title']))

db = sqlite3.connect(DB)
idx = db.execute("select source, count(*) c from docs where source like '任务「%' group by 1").fetchall()

hit_titles = 0
hit_docs = 0
miss = []
for src, c in idx:
    m = re.match(r'任务「(.+)」$', src)
    title = m.group(1) if m else src
    if norm(title) in obc:
        hit_titles += 1
        hit_docs += c
    else:
        miss.append((title, c))

print(f"index distinct quest titles: {len(idx)}, docs: {sum(c for _,c in idx)}")
print(f"matched via exact normalized title: {hit_titles} titles / {hit_docs} docs")
# try substring containment fallback (OBC title may carry suffix like 「魔神任务」prefix)
miss2 = []
for title, c in miss:
    nt = norm(title)
    found = None
    for k, v in obc.items():
        if nt and (nt in k or k in nt):
            found = v[0]
            break
    if found:
        hit_titles += 1
        hit_docs += c
    else:
        miss2.append((title, c))
print(f"after containment fallback: {hit_titles} titles / {hit_docs} docs")
miss2.sort(key=lambda x: -x[1])
print(f"UNMATCHED titles: {len(miss2)}, docs: {sum(c for _,c in miss2)}")
for t, c in miss2[:40]:
    print(' MISS', c, t)
# reverse: how many OBC quest entries are NOT in index
idx_norm = {norm(re.match(r'任务「(.+)」$', s).group(1) if re.match(r'任务「(.+)」$', s) else s) for s, _ in idx}
rev = [(t['content_id'], t['title']) for t in data['43'] if norm(t['title']) not in idx_norm]
print(f"OBC entries with no index source: {len(rev)}")
