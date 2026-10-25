#!/usr/bin/env python3
"""M4.6 step 3a: count entries per OBC channel (live). list API nests the
channel node: data.list[0].list holds its content items."""
import sys, time, json
sys.path.insert(0, 'scripts')
from obc_probe import channel_entries

targets = {43: '任务', 25: '角色', 5: '武器', 218: '圣遗物', 21: '食物',
           6: '敌人', 13: '背包', 20: 'NPC&商店', 251: '地图文本',
           252: '成就', 261: '角色逸闻', 279: '角色彩蛋', 255: '组织'}

out = {}
for cid, name in targets.items():
    for page in (1, 2):
        node = channel_entries(cid, page, 100)['list'][0]
        items = node.get('list') or []
        out[cid] = out.get(cid, []) + items
        if len(items) < 100:
            break
        time.sleep(0.4)
    print(cid, name, 'entries=', len(out[cid]))
    time.sleep(0.3)

json.dump(out, open('data/obc_channel_entries.json', 'w'), ensure_ascii=False)
print('saved data/obc_channel_entries.json')
