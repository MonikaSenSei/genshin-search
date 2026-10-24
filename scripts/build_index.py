#!/usr/bin/env python3
"""M1 build v2: TextMap + Readable books + Subtitles -> SQLite FTS5.

Provenance: reverse-reference scan of all ExcelBinOutput story tables.
Text ids referenced by no table at all (QE-script dialogue, verified absent
from every JSON and BinOutput binary in the dump) are kept and honestly
labelled 出处未定.

Usage: python3 build_index.py [--repo data/repo] [--out index/genshin.db]
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Story-bearing table classes (substring match on ExcelConfigData name),
# curated from the measured reference distribution (2026-10-23).
STORY_TABLE_KEYS = [
    "dialog", "mainquest", "quest", "questsummarization", "reminder",
    "viewcodex", "materialcodex", "codex", "gadget", "item", "food",
    "dailytask", "book", "subtitle", "talk",
]
# ...minus these refinements (minigame/shop/system variants of the above).
STORY_TABLE_DENY = [
    "gcg", "activity", "beyond", "home", "music", "gallery", "shop",
    "costume", "pvp", "brick", "bomber", "golf", "race", "parkour",
    "snowball", "diving", "dungeon", "level", "schedule", "coop",
    "custom", "snez", "pitch", "naturalist", "holiday", "demon",
    "title", "manualtextmap",
]

# textmap values inside a row that make good human-readable provenance labels
LABEL_KEYS = ("titletextmap", "showname", "nametextmap", "subtitletextmap",
              "talkrolename", "suitname")


def table_class(name):
    low = name.lower()
    for d in STORY_TABLE_DENY:
        if d in low:
            return None
    for k in STORY_TABLE_KEYS:
        if k in low:
            return k
    return None


def load_textmap(repo):
    with open(os.path.join(repo, "TextMap", "TextMapCHS.json"), encoding="utf-8") as f:
        return json.load(f)


def scan_table(path, tm_keys, tm):
    """Return set of (textmap_id, provenance_detail)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = set()

    def label_for(row):
        for k, v in row.items():
            if isinstance(v, int) and any(lk in k.lower() for lk in LABEL_KEYS):
                t = tm.get(str(v))
                if t and len(t.strip()) <= 40:
                    return t.strip()
        return None

    def handle_row(row):
        lbl = label_for(row)
        ids = set()

        def walk(o):
            if isinstance(o, dict):
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
            elif isinstance(o, int) and o in tm_keys:
                ids.add(o)
            elif isinstance(o, str) and o.isdigit() and len(o) > 9 and int(o) in tm_keys:
                ids.add(int(o))
        walk(row)
        for mid in ids:
            if str(mid) == (row.get("id") and str(row.get("id"))):
                continue
            out.add((mid, lbl))

    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict):
                handle_row(row)
    elif isinstance(data, dict):
        for row in data.values():
            if isinstance(row, dict):
                handle_row(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.path.join(ROOT, "data", "repo"))
    ap.add_argument("--out", default=os.path.join(ROOT, "index", "genshin.db"))
    args = ap.parse_args()
    if os.path.exists(args.out):
        os.remove(args.out)

    print("loading TextMap...")
    tm = load_textmap(args.repo)
    tm_keys = {int(k) for k in tm}
    print(f"  {len(tm)} entries")

    print("reverse-scanning story tables...")
    refs = defaultdict(list)  # textmap_id -> [(class, label)]
    per_table = Counter()
    ebi = os.path.join(args.repo, "ExcelBinOutput")

    # --- M2: per-line speaker + conversation cast from the dialog graph ---
    # Speaker resolution (verified 2026-10-23):
    #   TALK_ROLE_PLAYER -> 旅行者
    #   TALK_ROLE_NPC    -> talkRole.id -> NpcExcelConfigData.nameTextMapHash
    #                       -> TextMap_MediumCHS.json (short-label textmap)
    # The row's own talkRoleNameTextMapHash is per-row random in this dump
    # (203,908 unique, zero resolvable) and must NOT be used.
    print("extracting per-line speakers from DialogExcelConfigData...")
    speakers = defaultdict(set)          # textmap_id -> {speaker name}
    dids_of = defaultdict(set)          # textmap_id -> {dialog row ids}
    chain_of = {}                        # dialog id -> component id
    dialog_rows = {}                     # dialog id -> (textmap_id, speaker name)

    def load_json(path):
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return list(d.values()) if isinstance(d, dict) else d

    medium = None
    mpath = os.path.join(args.repo, "TextMap", "TextMap_MediumCHS.json")
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            medium = json.load(f)
        print(f"  medium textmap: {len(medium)} entries")

    def label(h):
        if not h or not medium:
            return ""
        t = medium.get(str(h)) or tm.get(str(h))
        return (t or "").strip()

    npc_name = {}
    for r in load_json(os.path.join(ebi, "NpcExcelConfigData.json")) or []:
        nid, nm = r.get("id"), r.get("nameTextMapHash")
        if nid is not None and nm:
            name = label(nm)
            if name:
                npc_name[int(nid)] = name
    gadget_name = {}
    need_gadget = set()
    drows = load_json(os.path.join(ebi, "DialogExcelConfigData.json")) or []
    for r in drows:
        trole = r.get("talkRole") or {}
        if trole.get("type") == "TALK_ROLE_GADGET" and trole.get("id", "").isdigit():
            need_gadget.add(int(trole["id"]))
    for r in load_json(os.path.join(ebi, "GadgetExcelConfigData.json")) or []:
        if r.get("id") in need_gadget:
            nm = r.get("nameTextMapHash") or r.get("nameTextMapId")
            name = label(nm)
            if name:
                gadget_name[int(r["id"])] = name

    if drows:
        nxt = {}
        parent = {}
        for r in drows:
            did = r.get("GFLDJMJKIKE")
            tmap = r.get("talkContentTextMapHash")
            trole = r.get("talkRole") or {}
            name = ""
            if trole.get("type") == "TALK_ROLE_PLAYER":
                name = "旅行者"
            elif trole.get("type") == "TALK_ROLE_NPC" and str(trole.get("id", "")).isdigit():
                name = npc_name.get(int(trole["id"]), "")
            elif trole.get("type") == "TALK_ROLE_GADGET" and str(trole.get("id", "")).isdigit():
                name = gadget_name.get(int(trole["id"]), "")
            if did is None:
                continue
            nxt[did] = [d for d in r.get("nextDialogs", []) if isinstance(d, int)]
            if tmap:
                dialog_rows[did] = (tmap, name)
        def find(x):
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        def union(a, b):
            parent.setdefault(a, a)
            parent.setdefault(b, b)
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
        for d, kids in nxt.items():
            for k in kids:
                union(d, k)
        roots = defaultdict(set)         # conversation component -> member ids
        for did in dialog_rows:
            r = find(did)
            chain_of[did] = r
            roots[r].add(did)
        cast_of = {}                     # chain root -> {speakers in chain}
        for r, members in roots.items():
            cast_of[r] = {dialog_rows[d][1] for d in members if dialog_rows[d][1]}
        for did, (tmap, name) in dialog_rows.items():
            if name:
                speakers[tmap].add(name)
            dids_of[tmap].add(did)
        print(f"  dialog rows: {len(drows)}, lines w/ speaker name: "
              f"{sum(1 for _, n in dialog_rows.values() if n)}")

    for fn in sorted(os.listdir(ebi)):
        if not fn.endswith(".json"):
            continue
        table = fn[:-len("ExcelConfigData.json")]
        cls = table_class(table)
        if cls is None:
            continue
        try:
            found = scan_table(os.path.join(ebi, fn), tm_keys, tm)
        except Exception as e:
            print(f"  !! {fn}: {e}", file=sys.stderr)
            continue
        per_table[cls] += len(found)
        for mid, lbl in found:
            refs[mid].append((cls, lbl))
    print(f"  referenced by story tables: {len(refs)}")

    db = sqlite3.connect(args.out)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("""CREATE VIRTUAL TABLE docs USING fts5(
        text, body UNINDEXED, corpus_type UNINDEXED, source UNINDEXED,
        speaker UNINDEXED, cast UNINDEXED,
        tok='unicode61')""")

    n_doc = 0
    seen = set()
    stats = Counter()
    n_speaker = 0

    def emit(corpus_type, text, source, speaker="", cast=""):
        nonlocal n_doc, n_speaker
        key = text.strip()
        if len(key) < 2 or key in seen:
            return
        seen.add(key)
        db.execute("INSERT INTO docs VALUES (?,?,?,?,?,?)",
                   (tok_cjk(key), key, corpus_type, source, speaker, cast))
        n_doc += 1
        if speaker:
            n_speaker += 1
        stats[(corpus_type, source != "出处未定")] += 1

    # 1) TextMap ids referenced by story tables
    for mid, rl in refs.items():
        text = tm.get(str(mid)) or ""
        if not text.strip():
            continue
        classes = sorted({c for c, _ in rl})
        labels = [lbl for _, lbl in rl if lbl]
        src = None
        spk = ""
        cast = ""
        if "dialog" in classes:
            spk = "、".join(sorted(speakers.get(mid, set()))[:4])
            chain_cast = set()
            for did in dids_of.get(mid, ()):
                chain_cast |= cast_of.get(chain_of.get(did), set())
            chain_cast.discard(None)
            cast = "、".join(sorted(chain_cast)[:8])
            src = "对白（在场）"
        if src is None:
            tag = ",".join(classes)
            src = f"{tag}" + (f"｜{'、'.join(sorted(set(labels))[:3])}" if labels else "")
        emit("textmap:" + ",".join(classes), text, src, spk, cast)

    # 2) orphan story-looking text (QE-script dialogue etc.). BinOutput/Talk
    # backfill (scripts/resolve_qe.py -> index/qe_src.db) gives most of them a
    # real quest/npc provenance + speaker; the rest stays honestly 出处未定.
    qe = {}
    qpath = os.path.join(ROOT, "index", "qe_src.db")
    if os.path.exists(qpath):
        qc = sqlite3.connect(qpath)
        qe = {r[0]: (r[1], r[2]) for r in
              qc.execute("SELECT id, source, speaker FROM qe")}
        print(f"  qe provenance map: {len(qe)} ids")
    orphans_kept = 0
    for k, v in tm.items():
        if int(k) in refs:
            continue
        s = v.strip()
        if len(s) < 6 or not re.search(r"[。！？…]", s):
            continue
        q = qe.get(int(k))
        if q:
            emit("textmap:unreferenced", s, q[0], q[1], "")
        else:
            emit("textmap:unreferenced", s, "出处未定")
        orphans_kept += 1
    print(f"  orphan story-shaped kept: {orphans_kept}")

    # 3) Readable books (titles from scripts/book_titles.py join when found;
    # the official title table no longer exists in any dump)
    book_title: dict = {}
    bt = os.path.join(ROOT, "index", "book_titles.db")
    if os.path.exists(bt):
        btc = sqlite3.connect(bt)
        book_title = {r[0]: r[1] for r in
                      btc.execute("SELECT book, title FROM book_titles")}
        print(f"  book titles: {len(book_title)} joined")
    rd = os.path.join(args.repo, "Readable", "CHS")
    for fn in sorted(os.listdir(rd)):
        if not fn.endswith(".txt"):
            continue
        book = fn[:-4]
        title = book_title.get(book, book)
        label = f"书籍:{title}"
        # Title card: book titles live only in the (now-dead) official title
        # table, so no book's own text contains its title — without this doc,
        # searching a title could never return the book itself. Kept as a
        # separate doc so body text stays verbatim.
        if book in book_title:
            emit("book_title", f"《{title}》 本书全文已收录于本检索库，正文见同来源结果。", label)
        with open(os.path.join(rd, fn), encoding="utf-8") as f:
            content = f.read()
        for para in split_blocks(content):
            emit("book", para, label)

    # 4) Subtitles
    sd = os.path.join(args.repo, "Subtitle", "CHS")
    for fn in sorted(os.listdir(sd)):
        if not fn.endswith(".srt"):
            continue
        sub = fn[:-4]
        for text in parse_srt(os.path.join(sd, fn)):
            emit("subtitle", text, f"字幕:{sub}")

    db.commit()
    total = db.execute("SELECT count(*) FROM docs").fetchone()[0]
    print(f"per-class refs: {dict(per_table)}")
    print(f"corpus stats: {dict(stats)}")
    print(f"docs with speaker attribution: {n_speaker}")
    print(f"TOTAL docs: {total} -> {args.out}")

    # coverage measurement vs raw corpus (control term)
    term = "坎瑞亚"
    raw_uniq = {v.strip() for v in tm.values() if term in v}
    idx = db.execute("SELECT body, source FROM docs WHERE docs MATCH ?",
                     (tok_query(term),)).fetchall()
    indexed = {b for b, _ in idx}
    with_src = sum(1 for b, s in idx if s != "出处未定")
    print(f"\nCONTROL '{term}': raw unique texts={len(raw_uniq)} indexed={len(indexed)} "
          f"with_source={with_src} missing={len(raw_uniq - indexed)}")


def split_blocks(text):
    out = []
    for p in re.split(r"\n{2,}", text):
        p = p.strip()
        if len(p) >= 2:
            out.append(p)
    return out


def parse_srt(path):
    with open(path, encoding="utf-8-sig") as f:
        raw = f.read()
    out = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [l.strip() for l in block.splitlines()]
        lines = [l for l in lines if l and not l.isdigit() and "-->" not in l]
        t = " ".join(lines).strip()
        if len(t) >= 2:
            out.append(t)
    return out


def tok_cjk(text):
    return re.sub(r"([\u3400-\u9fff\uf900-\ufaff])", r" \1 ", text)


def tok_query(q):
    toks = re.findall(r"[\u3400-\u9fff\uf900-\ufaff]|[A-Za-z0-9]+", q)
    return '"' + " ".join(toks) + '"'


if __name__ == "__main__":
    main()
