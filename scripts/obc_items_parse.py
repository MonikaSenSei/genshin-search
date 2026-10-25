#!/usr/bin/env python3
"""M4.7 items layer: parse cached OBC item pages -> data/obc_items.json
Lite card fields only: icon, star, category, desc/effect, story, obtain, url.
Sources of fields per type:
  weapon   equipment_base_info(name/image/category/star) + good_desc(attr,effect)
           + collapse_panel(story)
  food/material material_base_info(name/img/star/attr[描述]/materials[获取方式])
           + collapse_panel(story)
  artifact rich_base_info(attr: 稀有度/获取途径) + artifact_list_v2 x5 per-slot
           (name/desc/story); card = set name, story = per-slot stories.
"""
import json, os, re, html, sys

RAW = 'data/obc_items_raw'
URL = 'https://baike.mihoyo.com/ys/obc/content/{}/detail'

TAG = re.compile(r'<[^>]+>')

def to_text(s):
    if not isinstance(s, str):
        return ''
    s = s.replace('<br>', '\n').replace('</p>', '\n')
    s = TAG.sub('', s)
    s = html.unescape(s)
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n\s*\n+', '\n', s)
    return s.strip()

def attr_to_map(attr):
    m = {}
    for kv in attr or []:
        k = to_text(kv.get('key', '')).rstrip(':：')
        v = '\n'.join(to_text(x) for x in kv.get('value', []))
        if k:
            m[k] = v
    return m

def first_text(vals):
    for v in vals:
        t = to_text(v)
        if t:
            return t
    return ''

def parse_page(p, fallback_name):
    out = {'name': p.get('name') or fallback_name, 'alias': p.get('alias_name') or '',
           'icon': p.get('icon_url') or '', 'category': '', 'star': 0,
           'desc': '', 'effect': '', 'story': '', 'obtain': ''}
    slots = []
    stories = []
    for m in p.get('modules') or []:
        for c in m.get('components') or []:
            cid = c.get('component_id')
            try:
                d = json.loads(c['data']) if isinstance(c.get('data'), str) else (c.get('data') or {})
            except Exception:
                d = {}
            if cid == 'equipment_base_info':
                out['name'] = d.get('name') or out['name']
                out['icon'] = d.get('image') or out['icon']
                out['category'] = d.get('category') or ''
                out['star'] = int(d.get('star') or 0)
            elif cid == 'good_desc':
                am = attr_to_map(d.get('attr'))
                out['obtain'] = am.get('获取途径', '') or am.get('获取方式', '')
                out['effect'] = to_text(d.get('rich_text', ''))
                out['desc'] = am.get('描述', '') or out['desc']
            elif cid == 'material_base_info':
                if d.get('name') and d['name'] != out['name']:
                    continue  # variant row (奇怪的X/美味的X); keep base row
                out['icon'] = d.get('img') or out['icon']
                out['star'] = int(d.get('star') or 0) or out['star']
                am = attr_to_map(d.get('attr'))
                out['desc'] = am.get('描述', '') or out['desc']
                mm = d.get('materials') or {}
                out['obtain'] = to_text(mm.get('value', '')) or out['obtain']
            elif cid == 'rich_base_info':
                am = attr_to_map(d.get('list'))
                out['star'] = 0  # artifact rarity is text (4星/5星)
                out['category'] = '圣遗物套装'
                out['obtain'] = am.get('获取途径', '') or am.get('获取方式', '')
                out['rarity'] = am.get('稀有度', '')
            elif cid == 'artifact_list_v2':
                slot = {'slot': to_text(m.get('name', '')),
                        'name': first_text((d.get('name') or {}).get('value', [])),
                        'icon': d.get('icon_url') or '',
                        'desc': first_text((d.get('desc') or {}).get('value', [])),
                        'story': first_text((d.get('story') or {}).get('value', []))}
                slots.append(slot)
            elif cid == 'collapse_panel':
                t = to_text(d.get('rich_text', ''))
                if t:
                    stories.append(t)
    if slots:
        out['slots'] = slots
        out['story'] = '\n\n'.join(s['story'] for s in slots if s['story']) or '\n\n'.join(stories)
    else:
        out['story'] = max(stories, key=len) if stories else ''
    return out

def main():
    index = json.load(open('data/obc_channel_entries.json'))
    kinds = {}
    for ch, kind in (('5', 'weapon'), ('218', 'artifact'), ('21', 'food'), ('13', 'material')):
        for it in index[ch]:
            kinds[it['content_id']] = kind
    items, bad = [], []
    for fn in sorted(os.listdir(RAW)):
        cid = int(fn[:-5])
        raw = json.load(open(os.path.join(RAW, fn)))
        try:
            rec = parse_page(raw['page'], raw.get('list_title', ''))
        except Exception as e:
            bad.append((cid, repr(e)))
            continue
        rec['id'] = cid
        rec['kind'] = raw.get('kind') or kinds.get(cid, '')
        rec['url'] = URL.format(cid)
        if not rec['desc'] and not rec['effect'] and not rec['story'] and not rec.get('slots'):
            bad.append((cid, 'empty-content'))
            continue
        items.append(rec)
    json.dump(items, open('data/obc_items.json', 'w'), ensure_ascii=False)
    print(f'parsed items={len(items)} skipped={len(bad)}')
    from collections import Counter
    print(Counter(r['kind'] for r in items))
    print('skipped sample:', bad[:10])

if __name__ == '__main__':
    main()
