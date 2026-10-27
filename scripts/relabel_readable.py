#!/usr/bin/env python3
"""M4.12 readable relabel: replace opaque BookNNN/WeaponNNN provenance labels.

User rule: unlabeled Readable docs must not show raw IDs to users; use the
real name when the data proves one, else a category name; and rank this
whole layer below the main corpus.

Name sources (grounded, no guessing):
  WeaponNNN / RelicNNN_x -> numeric id in filename:
    Weapon: WeaponExcelConfigData id -> nameTextMapHash -> TextMap (exact)
    Relic:  set id -> OBC artifact-set story containment (obc_items.json)
    jump URL: items card layer (data/obc_items.json) by exact name join
  everything else -> category classifier over content (letter/script/notice/
    verse/short-fragment/miscellany), label 世界文书:未收录·<类别>

Output: data/pickup_labels.json  {filebase: {"label": str, "ctype": str,
        "url": str, "junk": bool}}
build_index.py consumes it; re-run after each dump update + obc_items refresh.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = os.path.join(ROOT, "data", "repo")
OUT = os.path.join(ROOT, "data", "pickup_labels.json")

KEEP = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf0-9a-zA-Z]+")
TAG = re.compile(r"<[^>]+>")


def norm(s):
    return "".join(KEEP.findall(s or ""))


def load_textmaps():
    tm = json.load(open(os.path.join(REPO, "TextMap", "TextMapCHS.json"), encoding="utf-8"))
    med = {}
    for p in sorted(glob.glob(os.path.join(REPO, "TextMap", "TextMap_MediumCHS*.json"))):
        med.update(json.load(open(p, encoding="utf-8")))
    return tm, med


def weapon_names():
    w = json.load(open(os.path.join(REPO, "ExcelBinOutput", "WeaponExcelConfigData.json"), encoding="utf-8"))
    w = w if isinstance(w, list) else list(w.values())
    tm, med = load_textmaps()
    out = {}
    for x in w:
        nm = tm.get(str(x.get("nameTextMapHash"))) or med.get(str(x.get("nameTextMapHash")))
        if nm:
            out[x["id"]] = nm
    return out


def item_urls_and_stories():
    items = json.load(open(os.path.join(ROOT, "data", "obc_items.json"), encoding="utf-8"))
    urls = {}   # normalized name -> url
    stories = {}  # normalized story text -> set name (artifacts) + weapon name
    for it in items:
        url = it.get("url", "")
        for n in [it.get("name", "")] + [a for a in re.split(r"[、,，]", it.get("alias", ""))]:
            n = n.strip()
            if n:
                urls.setdefault(norm(n), url)
        st = norm(it.get("story", ""))
        if st:
            stories[st] = it.get("name", "")
    return urls, stories


LETTER = re.compile(r"此致|敬启|展信|见信|亲爱的|挚爱的|给.{1,12}的信|你的朋友|忠实的朋友|敬上|顿首")
DIARY = re.compile(r"^(?:\d{1,2}月\d{1,2}日|第[一二三四五六七八九十\d]+天|Day\s*\d+)|日志|日记", re.M)
NOTICE = re.compile(r"告示|公告|启事|通知|通告|招聘|征集")
SCRIPT_LINE = re.compile(r"^[^：\n]{1,12}：")


def classify(text):
    body = TAG.sub(" ", text)
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    core = norm(text)
    if not lines:
        return "残句"
    first = lines[0]
    if NOTICE.search(first) or NOTICE.search(lines[0][:14] if len(lines) > 1 else first[:14]):
        return "告示"
    if len(core) < 60:
        return "残句"
    if LETTER.search(text):
        return "信件"
    if DIARY.search(text):
        return "日记"
    if len(lines) >= 4:
        scripty = sum(1 for l in lines if SCRIPT_LINE.match(l))
        if scripty >= max(4, len(lines) * 0.35):
            return "剧本"
        short = sum(1 for l in lines if len(l) <= 20)
        if short >= len(lines) * 0.7:
            return "诗"
    return "杂记"


def fuzzy_story_match(npart, istories):
    """Best-effort set join when exact containment fails: fraction of the
    part's chars covered by matching blocks against each OBC story."""
    if len(npart) < 30:
        return None
    from difflib import SequenceMatcher
    best, best_cov = None, 0.0
    for st, setname in istories.items():
        sm = SequenceMatcher(None, npart, st, autojunk=False)
        # ratio() is symmetric over both strings, so a full cover of the
        # short part inside a long story has ratio ~ 2*Lp/(Lp+Ls); gate on
        # that converted bound instead of a flat 0.85.
        gate = 2 * 0.85 * len(npart) / (len(npart) + len(st))
        if sm.real_quick_ratio() < gate or sm.quick_ratio() < gate:
            continue
        cov = sum(b.size for b in sm.get_matching_blocks()) / len(npart)
        if cov > best_cov:
            best, best_cov = setname, cov
    return best if best_cov >= 0.85 else None


def main():
    rd = os.path.join(REPO, "Readable", "CHS")
    wnames = weapon_names()
    iurls, istories = item_urls_and_stories()
    print(f"weapon ids named: {len(wnames)}; item url keys: {len(iurls)}; story sets: {len(istories)}")
    bt = os.path.join(ROOT, "index", "book_titles.db")
    import sqlite3
    named = set()
    if os.path.exists(bt):
        named = {r[0] for r in sqlite3.connect(bt).execute("SELECT book FROM book_titles")}
    # maptext-joined dump files (scripts/obc_maptext.py join_probe): real
    # title + region + OBC url come from the 地图文本 channel
    maptext = {}
    mt_match = os.path.join(ROOT, "data", "maptext_match.json")
    mt_raw = os.path.join(ROOT, "data", "obc_maptext_raw")
    if os.path.exists(mt_match):
        for base, info in json.load(open(mt_match, encoding="utf-8")).items():
            fp = os.path.join(mt_raw, info["eid"] + ".json")
            if os.path.exists(fp):
                rec = json.load(open(fp, encoding="utf-8"))
                maptext[base] = {"label": f"世界文书:{rec['title']}", "ctype": "maptext",
                                 "url": f"https://baike.mihoyo.com/ys/obc/content/{info['eid']}/detail?bbs_presentation_style=no_header"}
    out = {}
    stats = {"junk": 0, "weapon_named": 0, "relic_named": 0, "flavor_generic": 0,
             "maptext": 0, "category": {}}
    for fn in sorted(os.listdir(rd)):
        if not fn.endswith(".txt"):
            continue
        base = fn[:-4]
        if base in named:
            continue  # joined books keep their book_titles labels
        if base in maptext:
            out[base] = maptext[base]
            stats["maptext"] += 1
            continue
        text = open(os.path.join(rd, fn), encoding="utf-8").read()
        core = norm(TAG.sub(" ", text))
        # junk: image-only / test residue / placeholders / too short
        if (len(core) < 8 or "？？？" in text
                or re.search(r"（\s*test\s*）", text, re.I)):
            out[base] = {"junk": True}
            stats["junk"] += 1
            continue
        m = re.fullmatch(r"Weapon(\d+)", base)
        if m:
            nm = wnames.get(int(m.group(1)))
            if nm:
                out[base] = {"label": f"物品故事:{nm}", "ctype": "flavor",
                             "url": iurls.get(norm(nm), "")}
                stats["weapon_named"] += 1
                continue
            out[base] = {"label": "物品故事:未收录·武器", "ctype": "flavor", "url": ""}
            stats["flavor_generic"] += 1
            continue
        m = re.fullmatch(r"Relic(\d+)(?:_\d+)?", base)
        if m:
            # artifact set story parts: containment into a set's full story
            hit = None
            npart = norm(TAG.sub(" ", text))
            if len(npart) >= 30:
                for st, setname in istories.items():
                    if npart in st:
                        hit = setname
                        break
            if hit is None:
                # OBC wiki text differs from game dump by variant/revision
                # glyphs (櫻/樱, 虛/虚, single-char edits). Exact containment
                # breaks on one char; fall back to char-coverage ratio.
                hit = fuzzy_story_match(npart, istories)
            if hit:
                out[base] = {"label": f"物品故事:{hit}", "ctype": "flavor",
                             "url": iurls.get(norm(hit), "")}
                stats["relic_named"] += 1
                continue
            out[base] = {"label": "物品故事:未收录·圣遗物", "ctype": "flavor", "url": ""}
            stats["flavor_generic"] += 1
            continue
        # costume flavor: real flavor text for outfits (CostumeNNN ids)
        if re.fullmatch(r"Costume\d+", base):
            out[base] = {"label": "物品故事:未收录·衣装", "ctype": "flavor", "url": ""}
            stats["flavor_generic"] += 1
            continue
        cat = classify(text)
        out[base] = {"label": f"世界文书:未收录·{cat}", "ctype": "pickup", "url": ""}
        stats["category"][cat] = stats["category"].get(cat, 0) + 1
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    print(f"labeled {len(out)} readable files -> {OUT}")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
