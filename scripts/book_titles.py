#!/usr/bin/env python3
"""M4.5b book titles via BWiki content join.

The official book-title table (ReadingExcelConfigData) no longer exists in any
maintained dump, but local Readable/CHS/Book*.txt hold the verbatim book text.
BWiki transcribes the same official text on {{书籍}} template pages, so we join
by normalized-text containment instead of hash.

Outputs index/book_titles.db:
  book_titles(book TEXT PRIMARY KEY, title TEXT, page TEXT, url TEXT)
Used by build_index.py to label 书籍:<title> when a join is found.

Usage: python3 scripts/book_titles.py [--dump]   # --dump skips fetching, uses cached pages json
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
API = "https://wiki.biligame.com/ys/api.php"
CACHE = os.path.join(ROOT, "index", "wiki_book_pages.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TeyvatTextSearch/1.0"}

KEEP = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf0-9a-zA-Z]+")


def norm(s):
    return "".join(KEEP.findall(s))


def api(params):
    params = dict(params, format="json")
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            print(f"[api] retry {attempt}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError("api failed: " + str(params))


def api_get(params):
    params = dict(params, format="json")
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def list_book_pages():
    titles = set()
    # insource search finds every page transcluding the book template fields
    offset = 0
    while True:
        d = api_get({"action": "query", "list": "search",
                     "srsearch": 'insource:"书籍名="',
                     "srlimit": 50, "sroffset": offset})
        got = d.get("query", {}).get("search", [])
        for g in got:
            if g.get("ns") == 0:
                titles.add(g["title"])
        offset += len(got)
        if not got or offset >= 10000:
            break
        time.sleep(0.4)
    # plus the category, as a safety net
    cont = {}
    while True:
        d = api_get(dict({"action": "query", "list": "categorymembers",
                          "cmtitle": "Category:书籍", "cmlimit": 500}, **cont))
        for g in d.get("query", {}).get("categorymembers", []):
            if g.get("ns") == 0:
                titles.add(g["title"])
        if "continue" not in d:
            break
        cont = d["continue"]
        time.sleep(0.4)
    return sorted(titles)


def fetch_pages(titles):
    pages = {}
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        d = api({"action": "query", "prop": "revisions",
                 "titles": "|".join(batch), "rvprop": "content",
                 "rvslots": "main"})
        for p in d.get("query", {}).get("pages", {}).values():
            if "revisions" in p:
                pages[p["title"]] = p["revisions"][0]["slots"]["main"]["*"]
        print(f"  fetched {len(pages)}/{len(titles)}", flush=True)
        time.sleep(0.5)
    return pages


def strip_wiki(t):
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"[{}|]", " ", t)
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true",
                    help="reuse cached wiki pages json instead of fetching")
    args = ap.parse_args()

    if args.dump:
        pages = json.load(open(CACHE, encoding="utf-8"))
    else:
        print("listing book pages...")
        titles = list_book_pages()
        print(f"  {len(titles)} candidate pages")
        pages = fetch_pages(titles)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False)
    print(f"cached {len(pages)} pages")

    # build normalized corpus with page attribution
    parts, marks = [], []
    for title, wt in pages.items():
        m = re.search(r"书籍名\s*=\s*([^\n|{}]*)", wt)
        real_title = (m.group(1).strip() if m else title)
        body = "".join(v for k, v in re.findall(
            r"(卷\d+内容)\s*=\s*(.*?)(?=\n\|\s*卷\d+|\n\|[^\n=]+=|\Z)", wt, re.S))
        n = norm(strip_wiki(body))
        parts.append(n)
        marks.append((len("".join(parts[:len(parts) - 1])), real_title, title))
    hay = "".join(parts)
    print(f"haystack: {len(hay)} normalized chars")

    # match local book texts
    rd = os.path.join(ROOT, "data", "repo", "Readable", "CHS")
    outp = os.path.join(ROOT, "index", "book_titles.db")
    if os.path.exists(outp):
        os.remove(outp)
    out = sqlite3.connect(outp)
    out.execute("CREATE TABLE book_titles(book TEXT PRIMARY KEY, title TEXT, page TEXT, url TEXT)")
    total = matched = 0
    for fn in sorted(os.listdir(rd)):
        if not (fn.startswith("Book") and fn.endswith(".txt")):
            continue
        total += 1
        book = fn[:-4]
        n = norm(open(os.path.join(rd, fn), encoding="utf-8", errors="ignore").read())
        if len(n) < 30:
            continue
        pos = hay.find(n[:60])
        while pos != -1:
            if hay[pos:pos + len(n)] == n:
                acc = ""
                apage = ""
                for off, t, pg in marks:
                    if off <= pos:
                        acc, apage = t, pg
                out.execute("INSERT OR REPLACE INTO book_titles VALUES (?,?,?,?)",
                            (book, acc, apage,
                             "https://wiki.biligame.com/ys/" +
                             urllib.parse.quote(apage.replace(" ", "_"))))
                matched += 1
                break
            pos = hay.find(n[:60], pos + 1)
    out.commit()
    print(f"matched {matched}/{total} Book* files -> {outp}")


if __name__ == "__main__":
    main()
