#!/usr/bin/env python3
"""M4.7 items layer: fetch OBC entry_page details for all item-line channels.
Channels: 5=武器 218=圣遗物 21=料理 13=背包/材料.
Incremental & resumable: raw pages cached one JSON per entry under
data/obc_items_raw/<id>.json; rerun fills gaps. Failures logged, not fatal."""
import sys, os, json, time
sys.path.insert(0, 'scripts')
from obc_probe import get

OUT = 'data/obc_items_raw'
CHANNELS = {'5': 'weapon', '218': 'artifact', '21': 'food', '13': 'material'}
os.makedirs(OUT, exist_ok=True)

data = json.load(open('data/obc_channel_entries.json'))
todo = []
for ch, kind in CHANNELS.items():
    seen = set()
    for it in data[ch]:
        cid = it['content_id']
        if cid in seen:
            continue
        seen.add(cid)
        todo.append((cid, kind, it['title']))
print('entries to fetch (deduped):', len(todo))

def entry_page(eid):
    return get(f"https://act-api-takumi.mihoyo.com/hoyowiki/genshin/wapi/entry_page?entry_page_id={eid}&app_sn=ys_obc")["data"]["page"]

done = fail = skip = 0
for cid, kind, title in todo:
    path = os.path.join(OUT, f'{cid}.json')
    if os.path.exists(path):
        skip += 1
        continue
    ok = False
    for attempt in range(3):
        try:
            p = entry_page(cid)
            json.dump({'id': cid, 'kind': kind, 'list_title': title, 'page': p},
                      open(path, 'w'), ensure_ascii=False)
            ok = True
            break
        except Exception as e:
            time.sleep(2 * (attempt + 1))
    if ok:
        done += 1
    else:
        fail += 1
        print('FAIL', cid, kind, title)
    if (done + fail) % 50 == 0:
        print(f'progress: done={done} skip={skip} fail={fail}', flush=True)
    time.sleep(0.35)
print(f'DONE done={done} skip={skip} fail={fail}')
