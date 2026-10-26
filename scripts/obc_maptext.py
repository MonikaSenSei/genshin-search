#!/usr/bin/env python3
"""M4.12 map-text layer: 观测枢 图鉴>地图文本 channel (251) crawl + join.

Each entry = one in-world pickup document: title carries its region
(「留言条【白冕宫】」), the interactive_dialogue component holds the full
readable text, and a collapse_panel module may link related quests.

Pipeline:
  1. channel 251 entry list                    (cache data/obc_channel_251.json)
  2. entry_page crawl per entry                (per-entry files data/obc_maptext_raw/<id>.json, resumable)
  3. (join against Readable/CHS/BookNNN happens in a later step; this script
      only crawls and can --join for a quick coverage probe)

Usage: python3 scripts/obc_maptext.py [--join]
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
from obc_probe import channel_entries, get as api_get

UA = ("Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0")
CH_ID = 251
CH_CACHE = os.path.join(ROOT, "data", "obc_channel_%d.json" % CH_ID)
RAW_DIR = os.path.join(ROOT, "data", "obc_maptext_raw")
ENTRY_API = "https://act-api-takumi.mihoyo.com/hoyowiki/genshin/wapi/entry_page?entry_page_id={eid}&app_sn=ys_obc"

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
    """page dict -> {title, region, text, quests:[names]}"""
    title = page.get("name") or ""
    m = re.search(r"【(.+?)】\s*$", title)
    region = m.group(1) if m else ""
    texts, quests = [], []
    for mod in page.get("modules") or []:
        for c in mod.get("components") or []:
            cid = c.get("component_id")
            try:
                data = json.loads(c["data"]) if isinstance(c.get("data"), str) else (c.get("data") or {})
            except Exception:
                continue
            if cid == "interactive_dialogue":
                for item in data.get("list") or []:
                    conts = (item.get("contents") or {})
                    for v in conts.values():
                        if isinstance(v, dict) and v.get("dialogue"):
                            texts.append(strip_rich(v["dialogue"]))
            elif cid == "collapse_panel":
                rt = data.get("rich_text") or ""
                for q in re.findall(r'data-entry-name="([^"]+)"', rt):
                    quests.append(q)
    return {"title": title, "region": region,
            "text": "\n".join(texts).strip(), "quests": sorted(set(quests))}


def crawl(entries):
    os.makedirs(RAW_DIR, exist_ok=True)
    done = skip = fail = 0
    for i, e in enumerate(entries):
        eid = str(e["content_id"])
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
            print("  FAIL %s %s: %s" % (eid, e.get("title"), ex), flush=True)
        if (done + 1) % 50 == 0:
            print("  progress: done=%d skip=%d fail=%d" % (done, skip, fail), flush=True)
        time.sleep(0.3)
    print("DONE done=%d skip=%d fail=%d" % (done, skip, fail))


def load_all():
    out = {}
    for fn in os.listdir(RAW_DIR):
        if fn.endswith(".json"):
            out[fn[:-5]] = json.load(open(os.path.join(RAW_DIR, fn), encoding="utf-8"))
    return out


def join_probe():
    """Quick coverage probe: OBC entry text vs local BookNNN (dump side).
    Map texts are 1:1 docs: containment either direction, or 6-gram coverage
    >=0.9 on the shorter side (transcription single-char drift).
    Fast path: 12-char anchor substring prefilter, full compare on candidates.
    """
    REPO = os.path.join(ROOT, "data", "repo", "Readable", "CHS")
    local = {}
    for fn in os.listdir(REPO):
        if fn.endswith(".txt"):
            t = open(os.path.join(REPO, fn), encoding="utf-8").read()
            n = norm(t)
            if len(n) >= 10:
                local[fn[:-4]] = n
    anchors = []  # (anchor, book) — head/tail 12-grams of every local doc
    for book, lt in local.items():
        anchors.append((lt[:12], book))
        if len(lt) >= 24:
            anchors.append((lt[-12:], book))

    def ngrams(s, k=6):
        return {s[i:i + k] for i in range(len(s) - k + 1)} if len(s) >= k else {s}

    recs = load_all()
    matched = {}
    amb = set()
    for eid, r in recs.items():
        nt = norm(r["text"])
        if len(nt) < 10:
            continue
        cands = {b for a, b in anchors if a in nt}
        nta = {nt[:12], nt[-12:]}
        cands |= {b for b, lt in local.items() if any(a in lt for a in nta)}
        best = None
        for book in cands:
            lt = local[book]
            lg = ngrams(lt)
            ng = ngrams(nt)
            cov = max(len(lg & ng) / max(len(lg), 1), len(lg & ng) / max(len(ng), 1))
            cont = lt in nt or nt in lt
            if cov >= 0.9 or cont:
                score = (1 if cont else 0, cov, len(lt))
                if best is None or score > best[0]:
                    best = (score, book)
        if best:
            if best[1] in matched:
                amb.add(best[1])
            matched[best[1]] = eid
    json.dump({b: {"eid": e} for b, e in sorted(matched.items()) if b not in amb},
              open(os.path.join(ROOT, "data", "maptext_match.json"), "w"),
              ensure_ascii=False)
    print("crawled=%d local_docs=%d matched=%d ambiguous=%d" %
          (len(recs), len(local), len(matched) - len(amb), len(amb)))
    return matched


def verify_urls():
    """HEAD every map-text entry URL; cache {eid: {url, ok}} to
    data/maptext_urls.json. Unchanged eids keep their previous result."""
    cache_path = os.path.join(ROOT, "data", "maptext_urls.json")
    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    recs = load_all()
    import urllib.request
    req_h = {"User-Agent": UA, "Referer": "https://baike.mihoyo.com/"}
    dead = 0
    for eid in sorted(recs):
        url = f"https://baike.mihoyo.com/ys/obc/content/{eid}/detail?bbs_presentation_style=no_header"
        if eid in cache and cache[eid]["url"] == url:
            if not cache[eid]["ok"]:
                dead += 1
            continue
        try:
            req = urllib.request.Request(url, method="HEAD", headers=req_h)
            code = urllib.request.urlopen(req, timeout=15).status
        except Exception:
            code = 0
        cache[eid] = {"url": url, "ok": code == 200}
        if code != 200:
            dead += 1
        time.sleep(0.25)
    json.dump(cache, open(cache_path, "w"), ensure_ascii=False)
    print(f"verified {len(cache)} map-text urls, dead: {dead}")


if __name__ == "__main__":
    if not os.path.exists(CH_CACHE):
        entries = None
        d = api_get("https://act-api-takumi-static.mihoyo.com/common/blackboard/ys_obc/v1/home/content/list?app_sn=ys_obc&channel_id=%d" % CH_ID)
        lst = (d.get("data") or {}).get("list") or [{}]
        entries = lst[0].get("list") or []
        # dedupe by content_id
        seen, uniq = set(), []
        for x in entries:
            cid = str(x.get("content_id"))
            if cid not in seen:
                seen.add(cid)
                uniq.append(x)
        json.dump(uniq, open(CH_CACHE, "w"), ensure_ascii=False)
        entries = uniq
    else:
        entries = json.load(open(CH_CACHE))
    print("channel %d entries: %d" % (CH_ID, len(entries)))
    if "--verify" in sys.argv:
        verify_urls()
        sys.exit(0)
    crawl(entries)
    if "--join" in sys.argv:
        join_probe()
