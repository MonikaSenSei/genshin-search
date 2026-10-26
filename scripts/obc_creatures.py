#!/usr/bin/env python3
"""M4.13 creature-codex naming: 观测枢 敌人 channel (6) crawl + join.

AnimalCodex rows (provenance class 'codex') carry only descTextMapHash; the
monster/clockwork display name is absent from every TextMap in the dump. The
OBC enemy entries hold BOTH: title = display name, good_desc/collapse_panel
rich_text = the verbatim codex description. Join by description text.

Pipeline:
  1. channel 6 entry list           (cached data/obc_channel_6.json)
  2. entry_page crawl per entry     (data/obc_creatures_raw/<id>.json, resumable)
  3. --join: map AnimalCodex descTextMapHash -> {name, url} via description
     containment / 6-gram tolerance -> data/codex_match.json
     (URL liveness HEAD-built-in, cached across runs)

Usage: python3 scripts/obc_creatures.py [--join] [--verify-only]
"""
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from obc_probe import get as api_get

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")
CH_ID = 6
CH_CACHE = os.path.join(ROOT, "data", "obc_channel_%d.json" % CH_ID)
RAW_DIR = os.path.join(ROOT, "data", "obc_creatures_raw")
MATCH = os.path.join(ROOT, "data", "codex_match.json")
ENTRY_API = "https://act-api-takumi.mihoyo.com/hoyowiki/genshin/wapi/entry_page?entry_page_id={eid}&app_sn=ys_obc"
DETAIL = "https://baike.mihoyo.com/ys/obc/content/{eid}/detail?bbs_presentation_style=no_header"

KEEP = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf0-9a-zA-Z]+")
BR_TAG = re.compile(r"<br\s*/?>|</p>", re.I)


def norm(s):
    return "".join(KEEP.findall(s or ""))


def strip_rich(rt):
    if not rt:
        return ""
    t = BR_TAG.sub("\n", rt)
    t = re.sub(r"<[^>]+>", "", t)
    import html
    return html.unescape(t)


def parse_entry(page):
    """entry_page -> {title, text}: all rich_text from good_desc + panels."""
    title = page.get("name") or ""
    texts = []
    for mod in page.get("modules") or []:
        for c in mod.get("components") or []:
            if c.get("component_id") not in ("good_desc", "collapse_panel"):
                continue
            data = c.get("data")
            data = json.loads(data) if isinstance(data, str) else (data or {})
            for rt in [data.get("rich_text") or ""]:
                texts.append(strip_rich(rt))
            for a in data.get("attr") or []:
                for v in a.get("value") or []:
                    if isinstance(v, str):
                        texts.append(strip_rich(v))
    return {"title": title, "text": "\n".join(texts).strip()}


def crawl():
    entries = {e["content_id"]: e["title"]
               for e in json.load(open(CH_CACHE, encoding="utf-8"))}
    os.makedirs(RAW_DIR, exist_ok=True)
    done = skip = fail = 0
    for eid, _t in entries.items():
        eid = str(eid)
        fp = os.path.join(RAW_DIR, eid + ".json")
        if os.path.exists(fp):
            skip += 1
            continue
        try:
            d = api_get(ENTRY_API.format(eid=eid))
            page = (d.get("data") or {}).get("page") or {}
            rec = parse_entry(page)
            rec["id"] = eid
            json.dump(rec, open(fp, "w"), ensure_ascii=False)
            done += 1
        except Exception as ex:
            fail += 1
            print("  FAIL %s: %s" % (eid, ex), flush=True)
        if done and done % 50 == 0:
            print("  progress: done=%d skip=%d fail=%d" % (done, skip, fail), flush=True)
        time.sleep(0.3)
    print("DONE done=%d skip=%d fail=%d" % (done, skip, fail))


def load_all():
    out = {}
    for fn in os.listdir(RAW_DIR):
        if fn.endswith(".json"):
            out[fn[:-5]] = json.load(open(os.path.join(RAW_DIR, fn), encoding="utf-8"))
    return out


def ngrams(s, k=6):
    return {s[i:i + k] for i in range(len(s) - k + 1)} if len(s) >= k else {s}


def join_probe(verify_only=False):
    repo = os.path.join(ROOT, "data", "repo")
    tm = json.load(open(os.path.join(repo, "TextMap", "TextMapCHS.json"),
                        encoding="utf-8"))
    ac = json.load(open(os.path.join(repo, "ExcelBinOutput",
                                     "AnimalCodexExcelConfigData.json"),
                        encoding="utf-8"))
    descs = {}
    for row in ac:
        h = row.get("descTextMapHash")
        t = tm.get(str(h)) if h else None
        if t:
            n = norm(t)
            if len(n) >= 12:
                descs[str(h)] = n
    prev = {}
    if os.path.exists(MATCH):
        prev = json.load(open(MATCH, encoding="utf-8"))

    recs = load_all()
    entry_norm = {eid: norm(r["text"]) for eid, r in recs.items()}
    matched = dict(prev)
    amb = 0
    if not verify_only:
        hit = miss = 0
        for h, ln in descs.items():
            anchor = ln[len(ln) // 2 - 6:len(ln) // 2 + 6]
            cands = [eid for eid, en in entry_norm.items() if anchor in en]
            best = None
            for eid in cands:
                en = entry_norm[eid]
                if ln in en or en in ln:
                    best = eid
                    break
                cover = len(ngrams(ln) & ngrams(en)) / max(1, len(ngrams(ln)))
                if cover >= 0.9:
                    best = eid
                    break
            if not best:
                miss += 1
                continue
            name = recs[best]["title"]
            others = {recs[c]["title"] for c in cands
                      if c != best and recs[c]["title"] != name and
                      (ln in entry_norm[c] or entry_norm[c] in ln)}
            if others:
                amb += 1
                continue
            matched[h] = {"name": name, "id": best,
                          "url": DETAIL.format(eid=best), "ok": None}
            hit += 1
        print("join: local_descs=%d matched=%d miss=%d ambiguous=%d"
              % (len(descs), hit, miss, amb))

    # URL liveness (skip when unchanged & already checked)
    to_check = [(h, r) for h, r in matched.items() if r.get("ok") is None]
    for h, r in to_check:
        req = urllib.request.Request(r["url"], method="HEAD",
                                    headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                r["ok"] = resp.status == 200
        except Exception:
            r["ok"] = False
        time.sleep(0.2)
    dead = sum(1 for r in matched.values() if not r.get("ok"))
    json.dump(matched, open(MATCH, "w"), ensure_ascii=False)
    print("codex_match: %d entries, dead: %d -> %s" % (len(matched), dead, MATCH))


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--join" in args or "--verify-only" in args:
        join_probe(verify_only="--verify-only" in args)
    else:
        crawl()
