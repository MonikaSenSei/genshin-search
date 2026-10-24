#!/usr/bin/env python3
"""M3 social fetcher: official-site news + miyoushe official stream + Bilibili video descriptions.

Sources (all CN-network anonymous, verified 2026-10-23):
  takumi : ys.mihoyo.com news via act-api-takumi-static content_v2 (channel 717 = news root)
  mys    : miyoushe official news feed getNewsList(type=2) + getPostFull for body
  bili   : bilibili official account (mid 401742177) video titles+descriptions via wbi-signed API

Bilibili DYNAMICS are login-walled since 2026 (space dynamic tab + polymer feed both
require login) -> fallback per PLAN risk section: official site + miyoushe carry the same text.

Cross-source dedup: normalized body hash; first-inserted post wins, alternates recorded in
crossrefs. Re-runs are incremental (walk pages until ids already known).

Usage:
  python3 scripts/social_fetch.py backfill [--source takumi,mys,bili]
  python3 scripts/social_fetch.py update
  python3 scripts/social_fetch.py search <keyword> [--limit N]
  python3 scripts/social_fetch.py stats
"""
import argparse
import datetime as dt
import hashlib
import html as htmllib
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "index", "social.db")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")
BILI_MID = 401742177            # 原神官方 B站账号
TAKUMI_APP = "16471662a82d418a"
TAKUMI_GID = "10000079"
TAKUMI_NEWS_ROOT_CHAN = 717     # news root (iTotal covers child channels 719/720-723)
TAKUMI_URL = "https://ys.mihoyo.com/main/news/detail/{}"
MYS_GID = 2
MYS_OFFICIAL_UID = "75276539"

# ---------------------------------------------------------------- http
_BUVID = ""

def _req(url, headers=None, method=None):
    h = {"User-Agent": UA}
    if _BUVID:
        h["Cookie"] = _BUVID
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")

def get_json(url, headers=None):
    return json.loads(_req(url, headers))

def sleep_polite(a=0.4, b=0.9):
    import random
    time.sleep(random.uniform(a, b))

# ---------------------------------------------------------------- html -> text
_TAG_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_TAG_BREAK = re.compile(r"<(?:br|/p|/div|/h\d|/li)[^>]*>", re.I)
_TAG_ANY = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t\u00a0]+")
_MANY_NL = re.compile(r"\n{3,}")

def html_to_text(s):
    if not s:
        return ""
    s = _TAG_SCRIPT.sub("", s)
    s = _TAG_BREAK.sub("\n", s)
    s = _TAG_ANY.sub("", s)
    s = htmllib.unescape(s)
    s = _SPACES.sub(" ", s)
    s = _MANY_NL.sub("\n\n", s)
    return s.strip()

def norm_hash(text):
    t = re.sub(r"\s+", "", text or "")
    return hashlib.sha1(t.encode("utf-8")).hexdigest()

# ---------------------------------------------------------------- db
# M1 convention: CJK per-character tokenization (FTS5 unicode61 has no CCI segmenter).
def tok_cjk(text):
    return re.sub(r"([\u3400-\u9fff\uf900-\ufaff])", r" \1 ", text or "")

def tok_query(q):
    toks = re.findall(r"[\u3400-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+", q)
    return '"' + " ".join(t.replace('"', '""') for t in toks) + '"' if toks else None

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts(
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  ext_id TEXT NOT NULL,
  url TEXT,
  title TEXT,
  body TEXT,
  pub_ts INTEGER,
  pub_str TEXT,
  body_hash TEXT,
  created_at INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_src ON posts(source, ext_id);
CREATE INDEX IF NOT EXISTS ix_hash ON posts(body_hash);
CREATE TABLE IF NOT EXISTS crossrefs(
  post_id INTEGER NOT NULL,
  source TEXT NOT NULL,
  ext_id TEXT NOT NULL,
  url TEXT,
  UNIQUE(source, ext_id)
);
CREATE VIRTUAL TABLE IF NOT EXISTS posts_fts USING fts5(title, body);
"""

def open_db():
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    return con

def known_ids(con, source):
    return {r[0] for r in con.execute("SELECT ext_id FROM posts WHERE source=?", (source,))}

def insert_post(con, source, ext_id, url, title, body, pub_ts):
    """Insert or update by (source, ext_id). Cross-source duplicates go to crossrefs.
    Returns 'new' | 'dup-cross' | 'updated' | 'unchanged'."""
    body = html_to_text(body) if "<" in (body or "") else (body or "")
    title = html_to_text(title) if "<" in (title or "") else (title or "")
    h = norm_hash(body)
    pub_str = (dt.datetime.fromtimestamp(pub_ts).strftime("%Y-%m-%d %H:%M")
               if pub_ts else "")
    cur = con.execute("SELECT id, title, body FROM posts WHERE source=? AND ext_id=?", (source, ext_id))
    row = cur.fetchone()
    if row:
        rid, title_pre, body_pre = row
        if body_pre == body:
            return "unchanged"
        con.execute("UPDATE posts SET title=?, body=?, body_hash=?, pub_ts=?, pub_str=? WHERE id=?",
                    (title, body, h, pub_ts, pub_str, rid))
        con.execute("INSERT INTO posts_fts(posts_fts, rowid, title, body) VALUES('delete',?,?,?)",
                    (rid, tok_cjk(title_pre), tok_cjk(body_pre)))
        con.execute("INSERT INTO posts_fts(rowid, title, body) VALUES(?,?,?)",
                    (rid, tok_cjk(title), tok_cjk(body)))
        return "updated"
    other = con.execute("SELECT id FROM posts WHERE body_hash=? AND body<>''", (h,)).fetchone()
    if other and body:
        con.execute("INSERT OR IGNORE INTO crossrefs(post_id, source, ext_id, url) VALUES(?,?,?,?)",
                    (other[0], source, ext_id, url))
        return "dup-cross"
    cur = con.execute("INSERT INTO posts(source, ext_id, url, title, body, pub_ts, pub_str, body_hash, created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (source, ext_id, url, title, body, pub_ts, pub_str, h, int(time.time())))
    con.execute("INSERT INTO posts_fts(rowid, title, body) VALUES(?,?,?)",
                (cur.lastrowid, tok_cjk(title), tok_cjk(body)))
    return "new"

# ---------------------------------------------------------------- bilibili (wbi)
_MIXIN_TAB = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,
              29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,
              22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52]

def bili_bootstrap():
    global _BUVID
    spi = get_json("https://api.bilibili.com/x/frontend/finger/spi")
    _BUVID = f"buvid3={spi['data']['b_3']}; buvid4={spi['data']['b_4']}"
    nav = get_json("https://api.bilibili.com/x/web-interface/nav")
    img = nav["data"]["wbi_img"]["img_url"].split("/")[-1].split(".")[0]
    sub = nav["data"]["wbi_img"]["sub_url"].split("/")[-1].split(".")[0]
    return "".join((img + sub)[i] for i in _MIXIN_TAB)[:32]

def bili_get(url, referer):
    """intermittent risk control (HTTP 412 / code -799,-352): fresh buvid + backoff."""
    last = None
    for attempt in range(4):
        try:
            j = get_json(url, {"Referer": referer,
                               "Accept": "application/json, text/plain, */*",
                               "Accept-Language": "zh-CN,zh;q=0.9"})
            if j.get("code") in (-799, -352) and attempt < 3:
                last = f"code {j.get('code')}"
            else:
                return j
        except Exception as e:
            last = str(e)
        time.sleep(4 * (attempt + 1))
        bili_bootstrap()
    raise RuntimeError(f"bili risk control unresolved: {last}")

def bili_sign(params, mixin):
    p = {k: re.sub(r"[!'()*]", "", str(v)) for k, v in params.items()}
    p["wts"] = str(int(time.time()))
    q = "&".join(f"{urllib.parse.quote(k)}={urllib.parse.quote(p[k])}" for k in sorted(p))
    return q + "&w_rid=" + hashlib.md5((q + mixin).encode()).hexdigest()

def fetch_bili(con, incremental):
    mixin = bili_bootstrap()
    pn, new, dupc, seen_fully_known = 1, 0, 0, 0
    referer = f"https://space.bilibili.com/{BILI_MID}/video"
    while True:
        params = {"mid": BILI_MID, "ps": 50, "pn": pn, "order": "pubdate", "platform": "web"}
        j = bili_get("https://api.bilibili.com/x/space/wbi/arc/search?" + bili_sign(params, mixin), referer)
        if j.get("code") != 0:
            print(f"[bili] api code {j.get('code')} at pn={pn}", file=sys.stderr)
            break
        vlist = (j.get("data") or {}).get("list", {}).get("vlist") or []
        if not vlist:
            break
        page_unchanged = 0
        for v in vlist:
            r = insert_post(con, "bili", v["bvid"],
                            f"https://www.bilibili.com/video/{v['bvid']}",
                            v.get("title", ""), v.get("description", ""),
                            v.get("pubdate") or 0)
            if r == "new":
                new += 1
            elif r == "dup-cross":
                dupc += 1
            elif r == "unchanged":
                page_unchanged += 1
        con.commit()
        print(f"[bili] page {pn}: {len(vlist)} videos (new={new})", flush=True)
        if incremental and page_unchanged == len(vlist):
            break
        total = (j.get("data") or {}).get("page", {}).get("count", 0)
        if pn * 50 >= total:
            break
        pn += 1
        sleep_polite()
    print(f"[bili] done: new={new} cross-dup={dupc}")

# ---------------------------------------------------------------- takumi (official site)
def fetch_takumi(con, incremental):
    base = ("https://act-api-takumi-static.mihoyo.com/content_v2_user/app/" +
            TAKUMI_APP + f"/getContentList?iAppId=43&iChanId={TAKUMI_NEWS_ROOT_CHAN}"
            "&iPageSize=100&sLangKey=zh-cn")
    page, new, dupc, total = 1, 0, 0, None
    known = known_ids(con, "takumi") if incremental else set()
    while True:
        j = get_json(base + f"&iPage={page}")
        if j.get("retcode") != 0:
            print(f"[takumi] retcode {j.get('retcode')} page {page}", file=sys.stderr)
            break
        data = j.get("data") or {}
        items = data.get("list") or []
        total = data.get("iTotal", 0)
        if not items:
            break
        unknown = 0
        for it in items:
            if it["iInfoId"] in known:
                continue
            unknown += 1
            try:
                pub_ts = int(dt.datetime.strptime(it["dtCreateTime"], "%Y-%m-%d %H:%M:%S")
                            .timestamp())
            except (ValueError, KeyError):
                pub_ts = 0
            r = insert_post(con, "takumi", str(it["iInfoId"]),
                            TAKUMI_URL.format(it["iInfoId"]),
                            it.get("sTitle", ""), it.get("sContent", ""), pub_ts)
            if r == "new":
                new += 1
            elif r == "dup-cross":
                dupc += 1
        con.commit()
        print(f"[takumi] page {page}: {len(items)}/{total} fetched (new={new})", flush=True)
        if page * 100 >= total:
            break
        page += 1
        sleep_polite(0.3, 0.7)
    print(f"[takumi] done: new={new} cross-dup={dupc}")

# ---------------------------------------------------------------- miyoushe official stream
def mys_list_page(last_id):
    url = ("https://bbs-api-static.miyoushe.com/painter/wapi/getNewsList"
           f"?client_type=4&gids={MYS_GID}&last_id={last_id}&page_size=20&type=2")
    return get_json(url, {"Referer": "https://www.miyoushe.com/ys/"})

def mys_post_body(post_id):
    url = (f"https://bbs-api.miyoushe.com/post/wapi/getPostFull?post_id={post_id}"
           f"&gids={MYS_GID}&is_show_pre=0&show_hot_jump=1")
    last = None
    for attempt in range(3):
        j = get_json(url, {"Referer": "https://www.miyoushe.com/ys/", "x-rpc-client_type": "5"})
        p = (((j.get("data") or {}).get("post")) or {}).get("post")
        if p is not None:
            return p.get("subject", ""), p.get("content", "") or p.get("structured_content", ""), p.get("created_at", 0)
        last = f"retcode {j.get('retcode')}"
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"detail failed {post_id}: {last}")

def fetch_mys(con, incremental):
    known = known_ids(con, "mys")
    last_id, new, dupc, rounds_since_new, known_page_streak = "", 0, 0, 0, 0
    body_fail_streak = 0
    while True:
        j = mys_list_page(last_id)
        if j.get("retcode") != 0:
            print(f"[mys] retcode {j.get('retcode')}", file=sys.stderr)
            break
        data = j.get("data") or {}
        items = data.get("list") or []
        if not items:
            break
        fresh = [it["post"]["post_id"] for it in items if it["post"]["post_id"] not in known]
        for it in items:
            p = it["post"]
            pid = p["post_id"]
            if pid in known:
                continue
            try:
                subject, content, created = mys_post_body(pid)
                body_fail_streak = 0
            except Exception as e:
                # leave the id unknown -> a later run retries it
                print(f"[mys] detail fail {pid}: {e}", file=sys.stderr)
                body_fail_streak += 1
                if body_fail_streak >= 5:
                    print("[mys] risk-control gate on bodies; aborting, "
                          "pending bodies retried next run", file=sys.stderr)
                    con.commit()
                    return
                continue
            known.add(pid)
            r = insert_post(con, "mys", pid,
                            f"https://www.miyoushe.com/ys/article/{pid}",
                            subject, content, created or p.get("created_at", 0))
            if r == "new":
                new += 1
            elif r == "dup-cross":
                dupc += 1
            sleep_polite(0.25, 0.6)
        con.commit()
        print(f"[mys] last_id={last_id} page items={len(items)} fresh={len(fresh)} (new={new})", flush=True)
        if incremental:
            # the known newest prefix must not end the walk (older posts can
            # sit behind a fully-known page); stop only after 10 consecutive
            # fully-known pages
            known_page_streak = 0 if fresh else known_page_streak + 1
            if known_page_streak >= 10:
                break
        if data.get("is_last"):
            break
        last_id = data.get("last_id") or str(items[-1]["post"]["post_id"])
        sleep_polite(0.3, 0.8)
    print(f"[mys] done: new={new} cross-dup={dupc}")

# ---------------------------------------------------------------- commands
def do_stats(con):
    print("posts per source:")
    for s, n in con.execute("SELECT source, COUNT(*) FROM posts GROUP BY source"):
        print(f"  {s}: {n}")
    n = con.execute("SELECT COUNT(*) FROM crossrefs").fetchone()[0]
    print(f"cross-source duplicates recorded: {n}")
    tot = con.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    print(f"total unique: {tot}")

def excerpt(body, kw, ctx=60):
    i = (body or "").find(kw)
    if i < 0:
        return ""
    a = max(0, i - ctx)
    b = min(len(body), i + len(kw) + ctx)
    return ("…" if a else "") + body[a:b].replace("\n", " ") + ("…" if b < len(body) else "")

def do_search(con, kw, limit):
    q = tok_query(kw)
    if not q:
        print("query yields no tokens")
        return
    rows = con.execute(
        "SELECT p.source, p.ext_id, p.pub_str, p.title, p.url, p.body "
        "FROM posts_fts JOIN posts p ON p.id = posts_fts.rowid "
        "WHERE posts_fts MATCH ? ORDER BY rank LIMIT ?", (q, limit))
    n = 0
    for src, ext, pub, title, url, body in rows:
        n += 1
        alts = [f"{a}:{b}" for a, b in con.execute(
            "SELECT source, ext_id FROM crossrefs WHERE post_id=(SELECT id FROM posts WHERE source=? AND ext_id=?)",
            (src, ext))]
        print(f"[{src}] {pub} {title}")
        print(f"  {url}" + (f"  | also: {', '.join(alts)}" if alts else ""))
        snip = excerpt(title, kw, 40) or excerpt(body, kw)
        if snip:
            print(f"  {snip}")
    print(f"--- {n} hits for {kw!r}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["backfill", "update", "search", "stats"])
    ap.add_argument("--source", default="takumi,mys,bili")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("kw", nargs="?", default=None)
    args = ap.parse_args()
    con = open_db()
    if args.cmd == "stats":
        do_stats(con)
    elif args.cmd == "search":
        if not args.kw:
            sys.exit("search needs a keyword")
        do_search(con, args.kw, args.limit)
    else:
        incremental = args.cmd == "update"
        for src in args.source.split(","):
            if src == "takumi":
                fetch_takumi(con, incremental)
            elif src == "mys":
                fetch_mys(con, incremental)
            elif src == "bili":
                fetch_bili(con, incremental)
        con.commit()
        do_stats(con)

if __name__ == "__main__":
    main()
