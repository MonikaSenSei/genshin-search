#!/usr/bin/env python3
"""M4.6 step 3d: per-corpus-type quest coverage + 活动(105) channel join test."""
import sys, json, re, sqlite3, time, unicodedata, collections
sys.path.insert(0, 'scripts')
from obc_probe import channel_entries

def norm(s):
    s = unicodedata.normalize('NFKC', s).lower()
    return re.sub(r'[\W_]+', '', s, flags=re.UNICODE)

def keys_for(title):
    ks = {norm(title)}
    for seg in re.findall(r'[「『]([^」』]+)[」』]', title):
        ks.add(norm(seg))
    m = re.search(r'第[一二三四五六七八九十百千0-9]+[章幕折卷集]序?[·.:：\s]*(.{2,40})$', title)
    if m:
        ks.add(norm(m.group(1)))
    return {k for k in ks if k}

data = json.load(open('data/obc_channel_entries.json'))
obq = collections.defaultdict(list)
for it in data['43']:
    for k in keys_for(it['title']):
        obq[k].append(it['content_id'])

# fetch 活动 channel entries
node = channel_entries(105, 1, 100)['list'][0]
acts = node.get('list') or []
print('活动 channel entries:', len(acts))
oba = collections.defaultdict(list)
for it in acts:
    for k in keys_for(it['title']):
        oba[k].append(it['content_id'])

db = sqlite3.connect('index/genshin.db')
rows = db.execute("select corpus_type, source, count(*) c from docs where source like '任务「%' group by 1,2").fetchall()
by_type = collections.defaultdict(lambda: [0, 0, 0, 0])  # titles, docs, matched_t, matched_d
for ct, src, c in rows:
    m = re.match(r'任务「(.+)」$', src)
    title = (m.group(1) if m else src[len('任务「'):]).replace('$UNRELEASED', '').strip()
    n = norm(title)
    t = by_type[ct]
    t[0] += 1; t[1] += c
    hit = n in obq
    if not hit:
        cands = [(len(k), v[0]) for k, v in obq.items() if len(k) >= 4 and n in k]
        hit = bool(cands)
    in_act = False
    if not hit:
        cands = [(len(k), v[0]) for k, v in oba.items() if len(k) >= 4 and (n in k or (k in n and len(k) >= max(4, len(n) - 2)))]
        in_act = bool(cands)
    if hit or in_act:
        t[2] += 1; t[3] += c

print(f"{'corpus_type':28} {'titles':>7} {'docs':>7} {'matched':>8} {'m_docs':>7}")
for ct, t in sorted(by_type.items(), key=lambda x: -x[1][1]):
    print(f"{ct:28} {t[0]:>7} {t[1]:>7} {t[2]:>8} {t[3]:>7}")
T = sum(t[0] for t in by_type.values()); D = sum(t[1] for t in by_type.values())
MT = sum(t[2] for t in by_type.values()); MD = sum(t[3] for t in by_type.values())
print(f"{'TOTAL':28} {T:>7} {D:>7} {MT:>8} {MD:>7}  ({MT/T:.1%} titles, {MD/D:.1%} docs)")
