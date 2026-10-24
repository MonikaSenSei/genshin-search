#!/usr/bin/env python3
"""M4.6 book titles via official 观测枢 wiki (baike.mihoyo.com/ys/obc).

Pipeline:
  1. channel 68 (图鉴>书籍) entry list   -> 93 series entries (cached obc_channel_68.json)
  2. entry_page API per entry           -> per-volume rich_text (cached obc_books_raw.json)
  3. exact normalized-text join against Readable/CHS/BookNNN.txt
  4. upsert into index/book_titles.db (source='obc' beats 'bwiki'; re-tag 'bwiki'
     rows whose series is confirmed by an OBC join to the OBC url)

Schema (rebuilt with source column):
  book_titles(book TEXT PRIMARY KEY, title TEXT, page TEXT, url TEXT, source TEXT)

Usage: python3 scripts/obc_books.py [--fetch]   # default: use cached raw json
"""
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from obc_probe import channel_entries, get as api_get

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")
ENTRY_API = "https://act-api-takumi.mihoyo.com/hoyowiki/genshin/wapi/entry_page?entry_page_id={eid}&app_sn=ys_obc"
CH_CACHE = os.path.join(ROOT, "data", "obc_channel_68.json")
RAW_CACHE = os.path.join(ROOT, "data", "obc_books_raw.json")
DB = os.path.join(ROOT, "index", "book_titles.db")
REPO = os.path.join(ROOT, "data", "repo", "Readable", "CHS")

KEEP = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf0-9a-zA-Z]+")
BR_TAG = re.compile(r"<br\s*/?>|</p>", re.I)


def norm(s):
    return "".join(KEEP.findall(s))


def strip_rich(rt):
    """rich_text HTML -> text with newline-separated paragraphs."""
    if not rt:
        return ""
    t = BR_TAG.sub("\n", rt)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t)


def fetch_raw(entries):
    raw = {}
    if os.path.exists(RAW_CACHE):
        raw = json.load(open(RAW_CACHE))
    for i, e in enumerate(entries):
        eid = str(e["content_id"])
        if eid in raw:
            continue
        d = api_get(ENTRY_API.format(eid=eid))
        p = (d.get("data") or {}).get("page") or {}
        modules = []
        for m in p.get("modules") or []:
            txts = []
            for c in m.get("components") or []:
                if c.get("component_id") != "collapse_panel":
                    continue
                try:
                    data = json.loads(c["data"])
                except Exception:
                    continue
                txts.append(strip_rich(data.get("rich_text", "")))
            modules.append({"module_id": m.get("id"), "name": m.get("name") or "",
                            "text": "\n".join(txts)})
        raw[eid] = {"title": p.get("name") or e["title"], "modules": modules}
        print(f"  [{i+1}/{len(entries)}] {eid} {e['title']}: {len(modules)} modules", flush=True)
        json.dump(raw, open(RAW_CACHE, "w"), ensure_ascii=False)
        time.sleep(0.5)
    return raw


VOL_PREFIX = re.compile(r"^(第[一二三四五六七八九十百千\d]+[卷章篇讲]|卷[一二三四五六七八九十\d]+|[其之一二三四五六七八九十\d]+)\s*")


def ngrams(s, n=6):
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else {s}


def vol_label(base, name):
    """Display title for a volume module. 观测枢 names modules inconsistently:
    sometimes 'series·vol', sometimes bare 'vol', sometimes ''. Never assume
    the module name alone is a complete title — if it doesn't carry the series
    name, compose base·name (and empty names fall back to the series name)."""
    name = re.sub(r"\s+", "", name or "")
    name = name.strip("·—-")
    base_ns = re.sub(r"\s+", "", base or "")
    if not name:
        return base
    if name.replace("·", "").startswith(base_ns.replace("·", "")):
        return name
    return f"{base_ns}·{name}" if base_ns else name


def join_all(raw, min_cov=0.9):
    """Return ({BookNNN: norm_text}, {BookNNN: (display_title, entry_id)}).

    Matching is tolerant: the wiki is a community transcription and differs
    from the data dump by single characters (measured: OBC dropped 出 in
    日月前事, and prepends 「第N卷」 headers to the text itself). Exact
    normalized containment fails on those. So: strip a leading volume marker
    from the wiki text, then match on 6-gram coverage of the local text in
    the wiki text (>= min_cov) OR exact containment. One book takes the
    best-scoring volume; ties resolved by score."""
    local = {}
    for fn in sorted(os.listdir(REPO)):
        if fn.endswith(".txt"):
            local[fn[:-4]] = norm(open(os.path.join(REPO, fn), encoding="utf-8").read())
    cands = []  # (score, len, book, label, eid)
    for eid, entry in raw.items():
        base = entry["title"]
        vols = []
        for m in entry["modules"]:
            ntext = norm(m["text"])
            if len(ntext) < 20:
                continue
            vols.append((vol_label(base, m.get("name") or ""), ntext,
                         VOL_PREFIX.sub("", ntext)))
        for book, ltext in local.items():
            if len(ltext) < 10:
                continue
            lg = ngrams(ltext)
            for label, ntext, ntext2 in vols:
                ng = ngrams(ntext)
                ng2 = ngrams(ntext2) if ntext2 != ntext else ng
                cov = max(len(lg & ng), len(lg & ng2)) / len(lg)
                exact = ltext in ntext or ltext in ntext2 or ntext in ltext
                if cov >= min_cov or exact:
                    cands.append((cov, len(ltext), book, label, eid))
    cands.sort(reverse=True)
    matches, taken = {}, set()
    for cov, _, book, label, eid in cands:
        if book in taken:
            continue
        taken.add(book)
        matches[book] = (label, eid)
    return local, matches


def upsert_db(matches, entries):
    eid_by = {str(e["content_id"]): e for e in entries}
    conn = sqlite3.connect(DB)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(book_titles)")]
    if "source" not in cols:
        conn.execute("ALTER TABLE book_titles ADD COLUMN source TEXT DEFAULT 'bwiki'")
    obc_urls = {}
    for book, (title, eid) in sorted(matches.items()):
        url = f"https://baike.mihoyo.com/ys/obc/content/{eid}/detail?bbs_presentation_style=no_header"
        conn.execute("INSERT INTO book_titles(book,title,page,url,source) VALUES(?,?,?,?,?) "
                     "ON CONFLICT(book) DO UPDATE SET title=excluded.title, page=excluded.page, "
                     "url=excluded.url, source=excluded.source",
                     (book, title, f"obc:{eid}", url, "obc"))
        obc_urls.setdefault(eid, 0)
        obc_urls[eid] += 1
    # re-tag bwiki rows whose series name is confirmed by an OBC-joined title
    series_to_eid = {}
    for t, eid in matches.values():
        series_to_eid.setdefault(re.sub(r"[·].*$", "", t).strip(), eid)
    n_ret = 0
    for row in conn.execute("SELECT book, title, source FROM book_titles WHERE source='bwiki'"):
        series = re.sub(r"·.*$", "", row[1]).strip()
        eid = series_to_eid.get(series)
        if eid:
            conn.execute("UPDATE book_titles SET url=?, source='bwiki->obc' WHERE book=?",
                         (f"https://baike.mihoyo.com/ys/obc/content/{eid}/detail?bbs_presentation_style=no_header",
                          row[0]))
            n_ret += 1
    conn.commit()
    n_obc = conn.execute("SELECT COUNT(*) FROM book_titles WHERE source='obc'").fetchone()[0]
    n_total = conn.execute("SELECT COUNT(*) FROM book_titles").fetchone()[0]
    n_books = len(os.listdir(REPO))
    print(f"joined via OBC: {n_obc} books across {len(obc_urls)} wiki entries; "
          f"retagged bwiki rows: {n_ret}; total rows {n_total}/{n_books}")


def verify_urls():
    """HEAD-check every obc/bwiki->obc url; mark dead rows source='stale'."""
    conn = sqlite3.connect(DB)
    urls = {}
    for url, in conn.execute(
            "SELECT DISTINCT url FROM book_titles WHERE source IN ('obc','bwiki->obc')"):
        urls[url] = True
    import urllib.request
    req_h = {"User-Agent": UA, "Referer": "https://baike.mihoyo.com/"}
    dead = []
    for url in sorted(urls):
        try:
            req = urllib.request.Request(url, method="HEAD", headers=req_h)
            code = urllib.request.urlopen(req, timeout=15).status
        except Exception as e:
            code = f"ERR {e}"
        ok = code == 200
        print(f"  {'ok ' if ok else 'DEAD'} {code} {url}")
        if not ok:
            dead.append(url)
        time.sleep(0.4)
    for url in dead:
        conn.execute("UPDATE book_titles SET source='stale' WHERE url=?", (url,))
    conn.commit()
    print(f"verified {len(urls)} urls, dead: {len(dead)}")


if __name__ == "__main__":
    if "--verify" in sys.argv:
        verify_urls()
        sys.exit(0)
    do_fetch = "--fetch" in sys.argv
    entries = json.load(open(CH_CACHE))
    if do_fetch:
        raw = fetch_raw(entries)
    else:
        if not os.path.exists(RAW_CACHE):
            sys.exit("no cached raw json; run with --fetch first")
        raw = json.load(open(RAW_CACHE))
    total_vols = sum(len([m for m in e["modules"] if len(norm(m["text"])) >= 20]) for e in raw.values())
    print(f"entries: {len(raw)}, volumes with text: {total_vols}")
    local, matches = join_all(raw)
    by_title = {}
    for book, (title, eid) in matches.items():
        by_title.setdefault((title, eid), []).append(book)
    for (title, eid), books in sorted(by_title.items()):
        print(f"  {title} (obc:{eid}) <- {','.join(sorted(books))}")
    upsert_db(matches, entries)
