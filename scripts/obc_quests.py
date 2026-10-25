#!/usr/bin/env python3
"""M4.11: world-quest / archon-quest jump links to 观测枢 (task channel 43).

Index docs carry provenance label 任务「<title>」; OBC quest entries are
standalone world quests (verbatim titles) or composed act titles
('第一章 第四幕「我们终将重逢」', '黄金梦乡·沙海迷踪', '系列任务').
Join rule (M4.6 lesson): EXACT key equality only — full normalized title,
「…」 bracket segments, dot-separated segments (series/volume halves).
NO substring fallback (that produced noise: 不速之客→泡泡桔色的不速之客).
Ambiguous title hitting >1 distinct entry -> no button.

Output data/quest_urls.json: {"updated":..., "map": {<title>: {id,url,ok}}}}
URLs HEAD-checked (cached ok when unchanged); export_static.py appends a
src_url for 任务「title」 labels. --verify = re-HEAD only.
"""
import datetime
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from obc_probe import channel_entries, UA

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "quest_urls.json")


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"《|》", "", s)
    return re.sub(r"[\W_]+", "", s, flags=re.UNICODE)


def obc_keys(title):
    # only specific keys: full title, 「…」 segments, and the part after
    # 第N幕/第N章. Do NOT split on ·: series tokens collide across volumes
    # (全能美食队·* all match each other) -> ambiguity. Series-prefix and
    # volume-half matching happens from the index side instead.
    ks = {norm(title)}
    for seg in re.findall(r"[「『]([^」』]+)[」』]", title):
        ks.add(norm(seg))
    m = re.search(r"第[一二三四五六七八九十百千0-9]+[章幕折卷集回折]?序?[·.:：\s]*(.{2,40})$", title)
    if m:
        ks.add(norm(m.group(1)))
    return {k for k in ks if len(k) >= 2}


def idx_keys(t):
    """tiered keys for one index title: (tier, key) — lower tier = more
    specific. Full title and its 「」 segments are tier 0; series/volume
    halves from ·-splits tier 1; whole-title-equals-OBC-series-prefix tier 2
    handled via prefix map."""
    n = norm(t)
    ks = [(0, n)]
    for seg in re.findall(r"[「『]([^」』]+)[」』]", t):
        ks.append((0, norm(seg)))
    parts = [norm(p) for p in re.split(r"[·・.．]", t)]
    parts = [p for p in parts if len(p) >= 2]
    if len(parts) >= 2:
        for p in parts:
            ks.append((1, p))
    return [(tier, k) for tier, k in ks if len(k) >= 2]


def fetch_channel():
    items = {}
    page = 1
    while True:
        d = channel_entries(43, page, 50)
        lst = d.get("list") or []
        new = 0
        for it in lst:
            for sub in it.get("list") or []:
                k = str(sub.get("content_id"))
                if k and k not in items:
                    items[k] = sub
                    new += 1
            if it.get("content_id") and str(it["content_id"]) not in items:
                items[str(it["content_id"])] = it
                new += 1
        if not new:
            break
        page += 1
    out = list(items.values())
    json.dump(out, open(os.path.join(ROOT, "data", "obc_channel_43.json"),
                        "w", encoding="utf-8"), ensure_ascii=False)
    return out


def head_ok(url):
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": UA, "Referer": "https://baike.mihoyo.com/"})
        return urllib.request.urlopen(req, timeout=15).status == 200
    except Exception:
        return False


def main():
    verify_only = "--verify" in sys.argv
    existing = {}
    if os.path.exists(OUT):
        existing = json.load(open(OUT, encoding="utf-8")).get("map", {})

    import sqlite3
    db = sqlite3.connect(os.path.join(ROOT, "index", "genshin.db"))
    rows = db.execute(
        "SELECT source, count(*) FROM docs WHERE source LIKE '任务「%' GROUP BY 1"
    ).fetchall()
    titles = []
    for src, c in rows:
        m = re.match(r"任务「(.+)」$", src)
        t = m.group(1) if m else src[len("任务「"):].rstrip("」")
        t = t.replace("$UNRELEASED", "").strip()
        if t:
            titles.append((t, c))
    print(f"index quest titles: {len(titles)}")

    matched = {}
    if not verify_only:
        entries = fetch_channel()
        print(f"OBC quest entries (dedup): {len(entries)}")
        by_key = {}
        by_prefix = {}  # SERIES half (first part) of composed 'S·V' entries
        for it in entries:
            title = it.get("title", "")
            for k in obc_keys(title):
                by_key.setdefault(k, set()).add((it["content_id"], title))
            parts = re.split(r"[·・.．]", title)
            if len(parts) >= 2 and len(norm(parts[0])) >= 2:
                by_prefix.setdefault(norm(parts[0]), set()).add(
                    (it["content_id"], title))

        ambig = 0
        for t, c in titles:
            keys = idx_keys(t)
            n = norm(t)
            # tier 0: exact full title / bracket segment equality
            hits = set()
            for tier, k in keys:
                if tier == 0:
                    hits |= by_key.get(k, set())
            if not hits:
                # tier 1/2: index half or whole title == the SERIES half of a
                # composed 'S·V' entry -> jump to that entry. NOT the OBC
                # series half matched against index halves (that mixed
                # 加尔恰的赞歌·关键物品 into 适配性赠礼 and 其五 into
                # 危影重重·其五 — generic volume markers collide).
                for tier, k in keys:
                    if tier == 1:
                        hits |= by_prefix.get(k, set())
                if not hits:
                    hits = by_prefix.get(n, set())
            cids = {h[0] for h in hits}
            if len(cids) == 1:
                matched[t] = next(iter(hits))
            elif len(cids) > 1:
                ambig += 1
        print(f"matched titles: {len(matched)} ambiguous: {ambig}")
        doc_hits = sum(c for t, c in titles if t in matched)
        print(f"docs covered: {doc_hits}")

    out_map, checked, dead = {}, 0, 0
    src = existing if verify_only else {
        t: {"id": cid, "url": f"https://baike.mihoyo.com/ys/obc/content/{cid}/detail?bbs_presentation_style=no_header",
            "ok": True} for t, (cid, _) in matched.items()}
    for t, e in src.items():
        url = e["url"]
        if verify_only or existing.get(t, {}).get("url") != url or "--force" in sys.argv:
            ok = head_ok(url)
            checked += 1
            time.sleep(0.25)
        else:
            ok = e.get("ok", True)
        if not ok:
            dead += 1
        out_map[t] = {"id": e["id"], "url": url, "ok": bool(ok)}
    print(f"quests mapped: {len(out_map)} head-checked: {checked} dead: {dead}")
    doc = {"updated": datetime.date.today().isoformat(), "channel": 43,
           "count": len(out_map), "map": out_map}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
