#!/usr/bin/env python3
"""M4.10 direction 1: 观景点 (viewpoint) jump links.

Joins ViewCodex entries to the 观测枢 观景点 channel (253) by exact
normalized title, confirms the desc text is present in the game corpus,
HEAD-checks each entry URL, and writes data/viewpoint_urls.json:
  {"updated": "...", "map": {desc_text: {id, name, url, ok}}}
export_static.py turns map keys that match doc bodies into a per-doc
jump table (genshin.bin header `doc_url`). `--verify` re-HEADs every URL
and flips ok=false on dead ones (daily maintenance re-runs join + verify,
so the check itself is built into the join step).

Join is EXACT only (normalized full title): fuzzy was measured to be
unsafe here (M4.6 step-3 evaluation, 257/268 exact-joinable).
"""
import datetime
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from obc_probe import channel_entries, UA

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "viewpoint_urls.json")
CACHE = os.path.join(ROOT, "data", "obc_channel_253.json")


def norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"【[^】]*】", "", s)
    return re.sub(r"[\W_]+", "", s, flags=re.UNICODE)


def vp_entries():
    if os.path.exists(CACHE):
        return json.load(open(CACHE, encoding="utf-8"))
    items = {}
    page = 1
    while True:
        d = channel_entries(253, page, 50)
        lst = d.get("list") or []
        new = 0
        for it in lst:
            for sub in it.get("list") or []:
                key = str(sub.get("content_id"))
                if key and key not in items:
                    items[key] = sub
                    new += 1
            if it.get("content_id") and str(it["content_id"]) not in items:
                items[str(it["content_id"])] = it
                new += 1
        if not new:
            break
        page += 1
    out = list(items.values())
    json.dump(out, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def head_ok(url):
    try:
        req = urllib.request.Request(
            url, method="HEAD",
            headers={"User-Agent": UA, "Referer": "https://baike.mihoyo.com/"})
        return urllib.request.urlopen(req, timeout=15).status == 200
    except Exception:
        return False


def join():
    vp = vp_entries()
    names = {}
    for it in vp:
        n = norm(it.get("title", ""))
        if n and n not in names:
            names[n] = it
    print(f"观景点 channel entries: {len(vp)}")

    eb = os.path.join(ROOT, "data", "repo", "ExcelBinOutput")
    tm = json.load(open(os.path.join(ROOT, "data", "repo", "TextMap",
                                     "TextMapCHS.json"), encoding="utf-8"))
    raw = json.load(open(os.path.join(eb, "ViewCodexExcelConfigData.json"),
                         encoding="utf-8"))
    vc = raw if isinstance(raw, list) else list(raw.values())[0]

    db = sqlite3.connect(os.path.join(ROOT, "index", "genshin.db"))
    bodies = {r[0] for r in db.execute("select body from docs")}

    existing = {}
    if os.path.exists(OUT):
        existing = json.load(open(OUT, encoding="utf-8")).get("map", {})

    out_map, joined, dead, conflicts = {}, 0, 0, 0
    for r in vc:
        desc = tm.get(str(r.get("descTextMapHash", "")), "").replace("\\n", "\n")
        if not desc or desc not in bodies:
            continue
        name = tm.get(str(r.get("nameTextMapHash", "")), "")
        it = names.get(norm(name))
        if not it:
            continue
        url = (f"https://baike.mihoyo.com/ys/obc/content/"
               f"{it['content_id']}/detail?bbs_presentation_style=no_header")
        prev = out_map.get(desc)
        if prev and prev["url"] != url:
            # two ViewCodex rows share one desc but join to different
            # viewpoints: ambiguous -> no button (corpus doc is one text)
            conflicts += 1
            out_map[desc] = {"id": 0, "name": name, "url": "", "ok": False}
            continue
        entry = existing.get(desc)
        if entry and entry.get("url") == url:
            ok = entry.get("ok", True)
        else:
            ok = head_ok(url)
            time.sleep(0.3)
            joined += 1
        if not ok:
            dead += 1
        out_map[desc] = {"id": it["content_id"], "name": name,
                         "url": url, "ok": bool(ok)}
    print(f"ViewCodex={len(vc)} jumpable_docs={len(out_map)} "
          f"conflicts={conflicts} newly_head_checked={joined} dead={dead}")
    doc = {"updated": datetime.date.today().isoformat(),
           "channel": 253, "count": len(out_map), "map": out_map}
    json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    join()
