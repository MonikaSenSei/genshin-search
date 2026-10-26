#!/usr/bin/env python3
"""M4.12 book injection: OBC-transcribed volumes that have NO text in the dump.

Direction 3 (user rule: the book layer follows 观测枢's book list exactly).
scripts/obc_books.py join leaves some OBC book-channel volumes unmatched
because the dump side is empty/placeholder. Inject those as books when the
volume is provably a real in-world readable: its exact title appears as a
717-series book gadget name (GadgetExcelConfigData + TextMap chain).

Rows go into index/book_titles.db with a synthetic key 'inject:<eid>:<vi>'
(source='obc' -> gets 书名 card + jump URL like any joined book); the body
text is emitted into the index by build_index.py from data/obc_books_raw.json.

Usage: python3 scripts/obc_book_inject.py [--dry]
"""
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from obc_books import join_all, vol_label, norm

RAW_CACHE = os.path.join(ROOT, "data", "obc_books_raw.json")
GADGETS = os.path.join(ROOT, "data", "repo", "ExcelBinOutput", "GadgetExcelConfigData.json")
NAMES = os.path.join(ROOT, "data", "book_gadget_names.json")
DB = os.path.join(ROOT, "index", "book_titles.db")
MIN_CHARS = 100  # normalized chars; below this the "volume" is a stub/quote line


def gadget_book_names():
    """{normalized title: gadget id} for all 717-series book gadgets whose
    name resolves via TextMap/TextMap_Medium. Cached to data/."""
    if os.path.exists(NAMES):
        return json.load(open(NAMES, encoding="utf-8"))
    import glob
    tm = json.load(open(os.path.join(ROOT, "data", "repo", "TextMap", "TextMapCHS.json"), encoding="utf-8"))
    med = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "data", "repo", "TextMap", "TextMap_MediumCHS*.json"))):
        med.update(json.load(open(p, encoding="utf-8")))
    def T(h):
        return tm.get(str(h)) or med.get(str(h))
    g = json.load(open(GADGETS, encoding="utf-8"))
    g = g if isinstance(g, list) else list(g.values())
    out = {}
    for e in g:
        i = e.get("id")
        if isinstance(i, int) and 71700000 <= i < 71800000:
            nm = T(e.get("interactNameTextMapHash")) or T(e.get("nameTextMapHash"))
            if nm:
                out[norm(nm)] = i
    json.dump(out, open(NAMES, "w"), ensure_ascii=False)
    return out


def main(dry=False):
    raw = json.load(open(RAW_CACHE, encoding="utf-8"))
    entries = json.load(open(os.path.join(ROOT, "data", "obc_channel_68.json"), encoding="utf-8"))
    _, matches = join_all(raw)
    matched_pairs = {(eid, label) for label, eid in matches.values()}
    gnames = gadget_book_names()
    print(f"gadget-named books: {len(gnames)}")

    inj = []
    for eid, entry in raw.items():
        base = entry["title"]
        for vi, m in enumerate(entry["modules"]):
            ntext = norm(m["text"])
            if len(ntext) < 20:
                continue
            lab = vol_label(base, m.get("name") or "")
            if (eid, lab) in matched_pairs:
                continue
            if len(ntext) < MIN_CHARS:
                print(f"  skip stub  {lab} ({len(ntext)} chars)")
                continue
            if norm(lab) not in gnames:
                print(f"  skip no-gadget {lab} ({len(ntext)} chars)")
                continue
            inj.append((eid, vi, lab, ntext))
    print(f"injectable volumes: {len(inj)}")
    for eid, vi, lab, ntext in inj:
        print(f"  INJECT {eid}:{vi} {lab} ({len(ntext)} chars)")
    if dry:
        return

    conn = sqlite3.connect(DB)
    for eid, vi, lab, _ in inj:
        url = f"https://baike.mihoyo.com/ys/obc/content/{eid}/detail?bbs_presentation_style=no_header"
        conn.execute(
            "INSERT INTO book_titles(book,title,page,url,source) VALUES(?,?,?,?,?) "
            "ON CONFLICT(book) DO UPDATE SET title=excluded.title, page=excluded.page, "
            "url=excluded.url, source=excluded.source",
            (f"inject:{eid}:{vi}", lab, f"inject:obc:{eid}", url, "obc"))
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM book_titles WHERE book LIKE 'inject:%'").fetchone()[0]
    print(f"book_titles inject rows: {n}")


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)
